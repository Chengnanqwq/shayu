"""破甲面板（PURGE_1106 / v1.1.0）—— 把 dsh-purge 的能力接到傻鱼身上。

dsh-purge 只能在命令行里用（--status / --apply / --revert），而且**必须知道宿主根**
（DSH_BASE 指向带 dsh-agent-instructions 的 @deepseek-ai 目录），否则所有补丁都显示
undefined、apply 直接报「插件根未找到」。这个插件把那一步自动做掉。

命令：
  /破甲状态        补丁进度、宿主版本与适配情况、注入状态、备份、shim
  /破甲缺口        哪些补丁没打上 / 漂移了 / 文件缺了，以及该怎么办
  /破甲应用 确认    应用全部清洗（仅主人，必须带「确认」）
  /破甲回滚 确认    回滚到备份（仅主人，必须带「确认」）
  /破甲            帮助

面板：右下角只读卡片（补丁 / 漂移 / 宿主 / 注入 + 刷新），走 /plug/purge/status。

它自己不碰任何 dsh 文件，只调 dsh-purge 命令行；没装的机器上会老实说没装。
"""
import asyncio
import glob
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ENABLED = True
NAME = "破甲面板"
VERSION = "1.1.1"
DESC = ("在 QQ / 面板里管 dsh-purge：自动定位宿主根（DSH_BASE），"
        "看补丁进度与缺口、应用、回滚（应用/回滚仅主人且要带「确认」）")
AUTHOR = "ShaYu"

CAPS = ("ui", "http")

_CFG = {"purge_dir": "", "purge_node": "", "purge_dsh_base": "", "purge_timeout": 300}


# ────────────────────────── 找东西 ──────────────────────────
def _api():
    try:
        import plugins_loader as _pl
        return _pl.make_api(NAME)
    except Exception:
        return None


def _cfg(key, default=""):
    api = _api()
    if api is not None:
        try:
            v = api.cfg(key, default)
            if v not in (None, ""):
                return v
        except Exception:
            pass
    return _CFG.get(key, default)


def _home() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def _purge_dir() -> str:
    cand = str(_cfg("purge_dir", "") or os.environ.get("DSH_PURGE_DIR", "")).strip()
    if cand and (Path(cand) / "bin" / "dsh-purge.js").exists():
        return cand
    home = _home()
    for pat in (home / ".dsh" / "profiles" / "*" / "plugins" / "dsh-purge",
                home / ".dsh" / "plugins" / "dsh-purge"):
        for d in glob.glob(str(pat)):
            if (Path(d) / "bin" / "dsh-purge.js").exists():
                return d
    return ""


def _node_path() -> str:
    cand = str(_cfg("purge_node", "") or os.environ.get("DSH_PURGE_NODE", "")).strip()
    if cand and Path(cand).exists():
        return cand
    w = shutil.which("node")
    if w:
        return w
    home = _home()
    for pat in (home / ".dsh" / "dsh-runtimes" / "*" / "dependencies" / "node" / "bin" / "node.exe",
                home / ".dsh" / "dsh-runtimes" / "*" / "dependencies" / "node" / "node.exe"):
        for p in glob.glob(str(pat)):
            if Path(p).exists():
                return p
    return ""


def _valid_ai_base(p: str) -> bool:
    try:
        q = Path(p)
        return (q / "dsh-agent-instructions" / "lib").is_dir() or \
               (q / "dsh-agent-instructions" / "package.json").exists()
    except Exception:
        return False


def _dsh_base() -> str:
    """宿主根：配置 > 环境变量 > 自动找（dev 目录、本地安装、app.asar.unpacked、旧备份）。"""
    cand = str(_cfg("purge_dsh_base", "") or os.environ.get("DSH_BASE", "")).strip()
    if cand and _valid_ai_base(cand):
        return cand
    home = _home()
    roots = [
        r"D:\deepseek\resources",
        str(home / "AppData" / "Local" / "Programs"),
        str(home / "AppData" / "Local"),
        r"C:\Program Files",
    ]
    patterns = [
        "app/dsh/node_modules/@deepseek-ai",
        "app/node_modules/@deepseek-ai",
        "app.asar.unpacked/dsh/node_modules/@deepseek-ai",
        "app*/dsh/node_modules/@deepseek-ai",
        "resources/app/dsh/node_modules/@deepseek-ai",
        "*/resources/app/dsh/node_modules/@deepseek-ai",
        "*/resources/app/node_modules/@deepseek-ai",
    ]
    # 先按已知结构找（快），再宽一点搜一层
    for root in roots:
        if not root or not Path(root).exists():
            continue
        for pat in patterns:
            for hit in glob.glob(str(Path(root) / pat)):
                if _valid_ai_base(hit):
                    return hit
    for root in roots:
        if not root or not Path(root).exists():
            continue
        for hit in glob.glob(str(Path(root) / "**" / "dsh-agent-instructions" / "lib"), recursive=True)[:40]:
            base = str(Path(hit).parent.parent)
            if _valid_ai_base(base):
                return base
    return ""


def _env_for_cli() -> dict:
    env = dict(os.environ)
    base = _dsh_base()
    if base:
        env["DSH_BASE"] = base
    env.setdefault("DSH_HOME", str(_home() / ".dsh"))
    return env


# ────────────────────────── 跑 CLI ──────────────────────────
def _run(args, timeout=None) -> tuple[bool, str]:
    d = _purge_dir()
    if not d:
        return False, ("这台机器上没装 dsh-purge。\n"
                       "要在装了 dsh 的那台电脑上跑；或者给插件填 purge_dir 指到 dsh-purge 目录。")
    node = _node_path()
    if not node:
        return False, "找不到 node（dsh-purge 是 node 脚本）。填 purge_node 指到 node.exe。"
    exe = str(Path(d) / "bin" / "dsh-purge.js")
    tmo = int(timeout or _cfg("purge_timeout", 300) or 300)
    try:
        p = subprocess.run([node, exe] + list(args), cwd=d, capture_output=True, timeout=tmo,
                           env=_env_for_cli(),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (p.stdout or b"").decode("utf-8", "replace")
        err = (p.stderr or b"").decode("utf-8", "replace")
        return p.returncode == 0, (out + ("\n" + err if err.strip() else "")).strip()
    except subprocess.TimeoutExpired:
        return False, f"dsh-purge {args} 超时（>{tmo}s）"
    except Exception as e:
        return False, f"跑不起来：{type(e).__name__}: {e}"


_PATCH_RE = re.compile(r"[·✓✗★!]\s*\[#(\d+)\s*\]\s*(\S+)\s+(\S+/\S+|—)\s*—\s*(\w+)")


def _parse_status(text: str) -> dict:
    out = {
        "applied": None, "total": None, "pending": None,
        "na": 0, "missing_file": 0, "drifted": 0, "skipped": 0,
        "host": "", "host_target": "", "host_ok": None,
        "inject": "", "backup": "", "home": "", "shim": "",
        "root": "", "root_ok": None,
        "gaps": [],          # [{id, name, status}]
    }
    m = re.search(r"补丁\s*(\d+)\s*/\s*(\d+)\s*已清洗(?:,\s*(\d+)\s*待清洗)?", text)
    if m:
        out["applied"], out["total"] = int(m.group(1)), int(m.group(2))
        out["pending"] = int(m.group(3)) if m.group(3) else max(0, out["total"] - out["applied"])
    m = re.search(r"插件根[^\n]*?\s(\S*@deepseek-ai\S*)", text)
    if m:
        out["root"] = m.group(1)
    out["root_ok"] = bool(out["root"])
    m = re.search(r"宿主版本[^\n]*?([\d][\w.\-+]*)", text)
    if m:
        out["host"] = m.group(1)
    m = re.search(r"插件声明\s*([\w.\-+]+)", text)
    if m:
        out["host_target"] = m.group(1)
    out["host_ok"] = ("未适配" not in text) if out["host"] else None
    m = re.search(r"注入状态\s+(\S+)", text)
    if m:
        out["inject"] = m.group(1)
    m = re.search(r"备份[^\n]*?(有 / yes|无 / no)", text)
    if m:
        out["backup"] = m.group(1)
    m = re.search(r"DSH_HOME\s+(\S+)", text)
    if m:
        out["home"] = m.group(1)
    m = re.search(r"shim:[^\n]*", text)
    if m:
        out["shim"] = m.group(0).strip()
    for line in text.splitlines():
        mm = _PATCH_RE.search(line)
        if not mm:
            continue
        pid, pname, _layer, st = mm.group(1), mm.group(2), mm.group(3), mm.group(4)
        if st in ("na", "missing_file", "drifted", "skipped"):
            out[st] = out.get(st, 0) + 1
        if st in ("missing_file", "drifted"):
            out["gaps"].append({"id": pid, "name": pname, "status": st})
    return out


def _status_full() -> dict:
    ok, txt = _run(["--status"], timeout=90)
    d = _parse_status(txt)
    d["ok"] = bool(ok)
    d["text"] = txt
    d["dir"] = _purge_dir()
    d["base"] = _dsh_base()
    if not d.get("root") and d.get("base"):
        d["root"], d["root_ok"] = d["base"], True
    return d


_APPLY_WORDS = ("已清洗", "已是最新", "文件缺失", "skipped", "na patch", "全部完成",
                "ERROR", "失败", "漂移")


def _apply_tail(text: str, n: int = 8) -> str:
    """apply/revert 的输出里前半截是状态表，只挑报告行，别把 200 行表格刷到群里。"""
    picked = []
    for line in str(text or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if any(w.lower() in s.lower() for w in _APPLY_WORDS):
            picked.append(s)
    if not picked:
        return "（没有报告行，可能什么都没做）"
    if len(picked) > n:
        picked = picked[:n] + [f"…（还有 {len(picked) - n} 行）"]
    return "\n".join(picked)


def _one_line(d: dict) -> str:
    if not d.get("dir"):
        return "这台机器上没装 dsh-purge，破甲这块用不了。"
    if d.get("applied") is None:
        return "dsh-purge 在，但状态读不出来：\n" + (d.get("text") or "")[:300]
    bits = [f"补丁 {d['applied']}/{d['total']} 已清洗"]
    extra = []
    for k, label in (("na", "不适用"), ("missing_file", "缺文件"), ("drifted", "漂移"), ("skipped", "跳过")):
        if d.get(k):
            extra.append(f"{label} {d[k]}")
    if extra:
        bits.append("（" + " · ".join(extra) + "）")
    if d.get("host"):
        bits.append("宿主 " + d["host"] + ("" if d.get("host_ok", True) else
                                          f"（插件声明 {d.get('host_target') or '?'}，未适配）"))
    if d.get("inject"):
        bits.append("注入 " + d["inject"])
    if d.get("backup"):
        bits.append("备份 " + d["backup"])
    if d.get("host_ok") is False:
        bits.append("⚠ 宿主版本比插件声明的新，部分 pattern 可能对不上")
    return " · ".join(bits)


_GAP_NOTES = {
    # 宿主已经用另一种方案处理过的，别再当成"漏打"
    "19": ("宿主里已经有「阈值下限 32768」的等价处理（文件里带着 [dsh-purge] 32768 is a FLOOR 注释），"
           "不需要再按「整段禁用」的原文 pattern 打一次"),
    "71": ("这个版本的 dsh 没装「量神」那个包，文件缺失属于正常，忽略即可"),
}


def _gap_note(g: dict) -> str:
    pid = str(g.get("id") or "")
    if pid == "19":
        # 确认一下宿主是不是真被等价处理过，别照抄结论
        base = _dsh_base()
        if base:
            f = Path(base) / "dsh-compaction-tool-result-pruner" / "lib" / "index.js"
            try:
                if f.exists() and "32768 is a FLOOR" in f.read_text(encoding="utf-8", errors="replace"):
                    return _GAP_NOTES["19"]
            except Exception:
                pass
    return _GAP_NOTES.get(pid, "")


def _gaps_text(d: dict) -> str:
    gaps = d.get("gaps") or []
    if not gaps:
        return "没有缺口：该打上的都打上了（不适用/跳过的不算问题）。"
    lines = [f"有 {len(gaps)} 处没打上："]
    for g in gaps[:12]:
        tag = "文件缺失" if g["status"] == "missing_file" else "原文漂移"
        lines.append(f"· #{g['id']} {g['name']} — {tag}")
        note = _gap_note(g)
        if note:
            lines.append("   ↳ " + note)
    if len(gaps) > 12:
        lines.append(f"…还有 {len(gaps) - 12} 处")
    lines.append("漂移=官方原文改过，需要更新 dsh-purge 的 pattern；缺文件=那个包这个版本没有，通常可以忽略。")
    return "\n".join(lines)


# ────────────────────────── 消息命令 ──────────────────────────
def _flag(ctx, key):
    try:
        return bool(ctx.get(key))
    except Exception:
        return False


def _tail(text: str, n: int = 10) -> str:
    lines = [l for l in str(text or "").splitlines() if l.strip()]
    head = lines[:6]
    if len(lines) > n:
        head.append("…（还有 %d 行，面板里看全的）" % (len(lines) - n))
    return "\n".join(head)


async def on_message(ctx):
    text = str(ctx.get("text") or "").strip()
    if not text.startswith(("/破甲", "/purge", "/清洗")):
        return None
    body = re.sub(r"^/(破甲|purge|清洗)", "", text).strip()
    low = body.lower()

    if low in ("", "帮助", "help", "?"):
        return ("破甲面板：\n"
                "/破甲状态 — 补丁进度、宿主版本与适配、注入、备份、shim\n"
                "/破甲缺口 — 哪些补丁缺文件/漂移了\n"
                "/破甲应用 确认 — 应用全部清洗（仅主人）\n"
                "/破甲回滚 确认 — 回滚到备份（仅主人）\n"
                "宿主根自动找（DSH_BASE）；找错就在参数里填 purge_dsh_base")

    if low.startswith(("状态", "status")):
        if not _flag(ctx, "is_master") and not _flag(ctx, "is_admin"):
            return "这个只能管理员看。"
        d = await asyncio.to_thread(_status_full)
        return _one_line(d) + "\n" + _tail(d.get("text", ""))

    if low.startswith(("缺口", "gap", "体检")):
        if not _flag(ctx, "is_master") and not _flag(ctx, "is_admin"):
            return "这个只能管理员看。"
        d = await asyncio.to_thread(_status_full)
        return _one_line(d) + "\n" + _gaps_text(d)

    if low.startswith(("应用", "apply", "开")):
        if not _flag(ctx, "is_master"):
            return "只有主人能开破甲。"
        if "确认" not in body and "confirm" not in low:
            return ("这会改 dsh 本体文件（提示词 + 代码 + shim + override），"
                    "要动就回：/破甲应用 确认")
        ok, txt = await asyncio.to_thread(_run, ["--apply"], 900)
        # APPLY_REPORT_1106：跑完要读**应用之后**的真实状态；
        # 以前直接解析 apply 的输出，缺少 dir 字段，会误报「没装 dsh-purge」
        d = await asyncio.to_thread(_status_full)
        head = "应用完成：" if ok else "应用没走通："
        return head + _one_line(d) + "\n" + _apply_tail(txt)

    if low.startswith(("回滚", "revert", "关")):
        if not _flag(ctx, "is_master"):
            return "只有主人能回滚。"
        if "确认" not in body and "confirm" not in low:
            return "回滚会用备份覆盖当前文件，要动就回：/破甲回滚 确认"
        ok, txt = await asyncio.to_thread(_run, ["--revert"], 900)
        d = await asyncio.to_thread(_status_full)
        head = "回滚完成。" if ok else "回滚没走通："
        return head + _one_line(d) + "\n" + _apply_tail(txt)

    return "不认识的破甲命令，发 /破甲 看用法。"


def commands() -> dict:
    return {
        "/破甲": "破甲面板用法",
        "/破甲状态": "补丁进度 / 宿主版本 / 注入 / 备份（管理员）",
        "/破甲缺口": "哪些补丁缺文件或漂移了（管理员）",
        "/破甲应用 确认": "应用全部清洗（仅主人）",
        "/破甲回滚 确认": "回滚到备份（仅主人）",
    }


# ────────────────────────── 面板 ──────────────────────────
def ui_html():
    return """
<div class="shayu-plug-card" id="pg-card">
  <div class="pg-head"><span class="pg-dot" id="pg-dot"></span>破甲面板</div>
  <div class="pg-row">补丁：<b id="pg-patch">…</b></div>
  <div class="pg-row">缺口：<b id="pg-gap">…</b></div>
  <div class="pg-row">宿主：<b id="pg-host">…</b></div>
  <div class="pg-row">注入：<b id="pg-inject">…</b></div>
  <button class="pg-btn" id="pg-refresh">刷新</button>
  <div class="pg-tip">应用/回滚在 QQ 里发 /破甲应用 确认</div>
</div>
"""


def ui_css():
    return """
.shayu-plug-card#pg-card{right:16px;bottom:196px}
#pg-card .pg-head{font-weight:600;color:#eaf0ff;margin-bottom:6px;display:flex;align-items:center;gap:7px}
#pg-card .pg-dot{width:7px;height:7px;border-radius:50%;background:#5a6280}
#pg-card .pg-dot.ok{background:#4be08f;box-shadow:0 0 8px #4be08f}
#pg-card .pg-dot.part{background:#f0b34b;box-shadow:0 0 8px #f0b34b}
#pg-card .pg-row{color:#9aa4cc}
#pg-card b{color:#eaf0ff;font-weight:600}
#pg-card .pg-btn{margin-top:8px;width:100%;height:26px;border-radius:8px;cursor:pointer;
  background:rgba(120,130,255,.16);border:1px solid rgba(140,150,255,.3);
  color:#dfe6ff;font-size:12px;font-family:inherit}
#pg-card .pg-tip{margin-top:6px;color:#6f7899;font-size:11px;line-height:1.5}
"""


def ui_js():
    return """
(function () {
  var box = document.getElementById('pg-card');
  if (!box) return;
  function $(id) { return document.getElementById(id); }
  function load() {
    fetch(shayu.api('/plug/purge/status')).then(function (r) { return r.json(); })
      .then(function (d) {
        if (!d || !d.ok) { $('pg-patch').textContent = (d && d.error) || '读不到'; return; }
        $('pg-patch').textContent = (d.applied == null ? '—' : d.applied + '/' + d.total);
        var g = [];
        if (d.na) g.push('不适用 ' + d.na);
        if (d.missing_file) g.push('缺文件 ' + d.missing_file);
        if (d.drifted) g.push('漂移 ' + d.drifted);
        $('pg-gap').textContent = g.length ? g.join(' · ') : '无';
        $('pg-host').textContent = (d.host || '—') + (d.host_ok === false ? ' ⚠' : '');
        $('pg-inject').textContent = d.inject || '—';
        var full = d.applied != null && d.total && d.applied >= d.total;
        $('pg-dot').className = 'pg-dot' + (d.applied ? (full ? ' ok' : ' part') : '');
      }).catch(function () { $('pg-patch').textContent = '读不到'; });
  }
  $('pg-refresh').addEventListener('click', load);
  load();
  setInterval(load, 60000);
})();
"""


def handle_http(path, query=None, body=b""):
    if str(path or "").strip("/") in ("status", ""):
        d = _status_full()
        return 200, {
            "ok": bool(d.get("dir")),
            "applied": d.get("applied"), "total": d.get("total"), "pending": d.get("pending"),
            "na": d.get("na"), "missing_file": d.get("missing_file"),
            "drifted": d.get("drifted"), "skipped": d.get("skipped"),
            "host": d.get("host"), "host_ok": d.get("host_ok"), "host_target": d.get("host_target"),
            "inject": d.get("inject"), "backup": d.get("backup"), "shim": d.get("shim"),
            "base": d.get("base"), "root": d.get("root"), "dir": d.get("dir"),
            "gaps": d.get("gaps"), "brief": _one_line(d),
            "error": "" if d.get("dir") else "这台机器上没装 dsh-purge",
        }
    return 404, {"ok": False, "error": "no such path"}
