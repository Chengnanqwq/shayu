"""改签名插件（SIGN_1105）—— 移植 astrbot_plugin_dafeiyu_signature。

用到的 OneBot 接口：set_self_longnick(longNick=...)

触发：
  /签名 我是小鱼        → 直接改
  /签名                 → 看当前签名（从 OneBot get_stranger_info 拿不到自己的，改从 history 读最后一次）
  主人说「把签名改成 xxx」→ 自然语言也能改
只认主人和账号主人白名单；每天按主人要求最多改 10 次。

「她自己心情变了主动改」没做：傻鱼的 llm_chat 不带 function calling，
硬塞会变成让模型输出固定格式再正则解析，容易误伤正常回复。要的话下一版单独加。
"""
import json
import re
import time
from pathlib import Path

def _root() -> "Path":
    """插件所在目录的上一级就是安装根目录；换机器/换系统都不用改路径。"""
    here = Path(__file__).resolve().parent          # plugins/
    for cand in (here.parent,):                     # 安装根目录
        if cand.exists():
            return cand
    return here.parent


ENABLED = True
NAME = "改签名"

HISTORY = _root() / "signature_history.json"
DAILY_LIMIT = 10


def commands() -> dict:
    return {"/签名 <内容>": "改 QQ 个性签名", "/签名": "看上次改成了什么"}


def _load() -> list:
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(rows: list) -> None:
    try:
        HISTORY.write_text(json.dumps(rows[-200:], ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def _today_count(rows: list) -> int:
    today = time.strftime("%Y-%m-%d")
    return sum(1 for r in rows if r.get("date") == today)


def _parse(text: str):
    """从一句话里抠出签名内容，抠不到返回 None。"""
    t = text.strip()
    if "签名" not in t:
        return None
    t = re.sub(r"^(/签名|改个?签名|换个?签名|设置签名)[\s:：,，]*", "", t)
    # 「把签名改成 xxx」「签名换成 xxx」
    m = re.search(r"签名[^。！？\n]{0,6}?(?:改成|换成|写成|写上|改为|设为|写)[\s:：]*[「“\"']?(.+?)[」”\"']?$", t)
    if m:
        t = m.group(1)
    t = t.strip().strip("「」“”\"'").strip()
    return t or None


async def on_message(ctx: dict) -> bool:
    raw = (ctx.get("raw") or "").strip()
    if "签名" not in raw:
        return False
    # 只在私聊、或群里明确叫她改的时候动，避免群聊里别人一说就跟
    if not ctx.get("is_master") and not ctx.get("is_admin"):
        return False
    body = _parse(raw)
    if not body:
        rows = _load()
        last = rows[-1].get("signature") if rows else None
        await ctx["reply"](f"现在的签名是「{last}」" if last else "还没改过签名，发「/签名 想写的话」")
        return True
    if len(body) > 40:
        await ctx["reply"]("太长了，40 字以内")
        return True
    rows = _load()
    if _today_count(rows) >= DAILY_LIMIT:
        await ctx["reply"]("今天改太多了，明天再换")
        return True
    if rows and rows[-1].get("signature") == body:
        await ctx["reply"]("本来就是这句")
        return True
    call = ctx.get("call")
    if not call:
        await ctx["reply"]("连不上 OneBot，改不了")
        return True
    try:
        res = await call("set_self_longnick", {"longNick": body})
    except Exception as e:
        await ctx["reply"](f"改签名失败：{type(e).__name__}")
        print(f"[signature] 失败 {e}", flush=True)
        return True
    ok = isinstance(res, dict) and str(res.get("status") or res.get("retcode")) in ("ok", "0", "None")
    rows.append({"date": time.strftime("%Y-%m-%d"), "time": time.strftime("%H:%M:%S"),
                 "signature": body, "by": ctx.get("user"), "res": str(res)[:120]})
    _save(rows)
    print(f"[signature] 改成「{body}」 -> {str(res)[:100]}", flush=True)
    await ctx["reply"](f"改好了：「{body}」")
    return True
