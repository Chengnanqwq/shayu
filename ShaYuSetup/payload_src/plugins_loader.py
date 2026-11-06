"""插件加载器 v2（PLUGIN_1106）—— 目标：**别拒绝任何写法**。

一个插件只要是个 .py（或一个目录），就应该能装进来；写得糙、写得旧、写着别的生态的
习惯，也尽量让它跑起来，而不是一句「加载失败」把作者挡在门外。

──── 一、发现（怎么放都认）──────────────────────────────
    plugins/表情.py                 平铺
    plugins/聊天/表情.py            一层子目录（分类目录，加载时忽略目录名）
    plugins/表情/__init__.py        目录式插件（包里可带资源文件）
    plugins/表情.py.disabled        禁用但照样列出来（面板里能一键启用）
    plugins/_草稿.py  /.隐藏.py    _ 和 . 开头的自动跳过，不进列表
    plugins/_removed/               卸载区，跳过

──── 二、元数据（有一半就够）────────────────────────────
    NAME / PLUGIN_NAME / TITLE / MODULE_NAME      → 显示名（都没有就用文件名）
    VERSION / PLUGIN_VERSION / __version__        → 版本
    DESC / DESCRIPTION / SUMMARY / __doc__ 首行   → 说明
    AUTHOR / __author__ / BY                      → 作者
    ENABLED / ENABLE / ACTIVE / DISABLED          → 开关（DISABLED 取反）

──── 三、钩子（叫什么名字都接）──────────────────────────
    消息入口：on_message / handle / on_msg / handle_message / on_event / run
    初始化：  setup / register / on_load / init（把 ctx 或 bot 传进去，异常只警告）
    命令表：  commands() / get_commands() / COMMANDS / CMDS
              dict / [(cmd, desc)] / [{"cmd":..., "desc":...}] / 纯字符串列表 都收

    类式插件（AstrBot 那种 class + 方法的写法）：模块里只要有一个类带上面任一方法名，
    就自动实例化并当成插件用；构造失败就用类本身（静态方法也能跑）。

    签名容错：fn(ctx) → fn(text, ctx) → fn(msg, ctx) → fn(**ctx) → fn()
              TypeError/参数不匹配时才降级，正常写法不受影响。
    返回值：  True/非空 → 这条消息我处理了；返回 str → 当成回复内容自动发出去；
              None/False/空 → 交给下一个插件。

──── 四、ctx 兼容（dict 和对象两种写法都能用）──────────────
    ctx["text"] 与 ctx.text 等价；消息文本同时提供 text/msg/message/content/raw_text，
    发送同时提供 reply/send/send_msg，身份同时提供 user/user_id/uid/sender。

──── 五、容错底线──────────────────────────────────────
    · 编码：utf-8-sig → utf-8 → gb18030 → gbk → latin-1，全失败才放弃
    · 依赖缺失（ImportError / ModuleNotFoundError）单独标记，面板提示「缺依赖: xxx」
    · 任何插件抛异常只影响它自己：记 error，别的插件照常跑
    · 单插件超时（默认 20s）跳过，不拖死消息链
    · load_all() 幂等：重复调用会先卸载旧模块（热重载、卸载插件都能立刻生效）
"""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import os
import re
import sys
import time
import traceback
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent / "plugins"
PLUGIN_TIMEOUT = 20          # 单个插件单次调用的秒数上限

_NAME_KEYS = ("NAME", "PLUGIN_NAME", "TITLE", "MODULE_NAME", "name")
_VER_KEYS = ("VERSION", "PLUGIN_VERSION", "__version__", "version")
_DESC_KEYS = ("DESC", "DESCRIPTION", "SUMMARY", "description", "desc")
_AUTHOR_KEYS = ("AUTHOR", "__author__", "BY", "author")
_ON_KEYS = ("ENABLED", "ENABLE", "ACTIVE", "enabled")
_OFF_KEYS = ("DISABLED", "disabled")
_MSG_HOOKS = ("on_message", "handle", "on_msg", "handle_message", "on_event", "run")
_INIT_HOOKS = ("setup", "register", "on_load", "init")
_REPLY_HOOKS = ("on_reply", "rewrite_reply", "post_reply")
# APP_1106：应用级能力——插件可以改配置、注入面板 UI、挂自己的 HTTP 接口
_UI_HOOKS = ("ui_html", "ui_css", "ui_js")
_HTTP_HOOKS = ("handle_http", "on_http", "http")
_CONFIG_HOOKS = ("on_config", "tune_config")
_CMD_HOOKS = ("commands", "get_commands", "COMMANDS", "CMDS", "cmd_list")

_LOADED: list[dict] = []
_READY = False
_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin-1")


# ── ctx：dict 和属性两种写法都能用 ──────────────────────────
class Ctx(dict):
    """既能 ctx["text"] 又能 ctx.text；缺的键返回空值而不是抛 KeyError。"""

    _ALIASES = {
        "text": ("text", "msg", "message", "content", "raw_text"),
        "reply": ("reply", "send", "send_msg", "send_text"),
        "user": ("user", "user_id", "uid", "sender", "qq"),
        "is_admin": ("is_admin", "admin", "is_owner"),
        "is_master": ("is_master", "master"),
    }

    def __getattr__(self, k):
        for name in self._ALIASES.get(k, (k,)):
            if name in self:
                return self[name]
        return None

    def __setattr__(self, k, v):
        self[k] = v

    def get_text(self) -> str:
        for name in self._ALIASES["text"]:
            v = self.get(name)
            if isinstance(v, str):
                return v
        return ""

    async def say(self, text: str):
        for name in self._ALIASES["reply"]:
            fn = self.get(name)
            if callable(fn):
                r = fn(text)
                if inspect.isawaitable(r):
                    await r
                return r
        return None


def _wrap_ctx(ctx: dict) -> Ctx:
    c = Ctx(ctx or {})
    txt = c.get_text()
    for k in ("text", "msg", "message", "content", "raw_text"):
        c.setdefault(k, txt)
    uid = c.get("user")
    for k in ("user", "user_id", "uid", "sender"):
        c.setdefault(k, uid)
    c.setdefault("is_admin", bool(c.get("is_admin")))
    c.setdefault("is_master", bool(c.get("is_master")))
    return c


# ── 发现 ───────────────────────────────────────────────
def _iter_units():
    """产出 (path, enabled_by_name, kind)。path 是 .py 或包目录。"""
    if not PLUGIN_DIR.is_dir():
        return []
    out = []
    for p in sorted(PLUGIN_DIR.rglob("*")):
        rel = p.relative_to(PLUGIN_DIR).as_posix()
        rel_parts = p.relative_to(PLUGIN_DIR).parts
        # 跳过卸载区、缓存、版本库，以及一切 _ / . 开头的目录（_removed、__cache__、_draft 等）
        if any(seg in ("__pycache__", ".git", "node_modules") for seg in rel_parts):
            continue
        if any(seg.startswith("_") or seg.startswith(".") for seg in rel_parts):
            continue
        if p.is_dir() and (p / "plugin.json").is_file():
            out.append((p, True, "manifest"))       # COMPAT_1106：纯界面插件
        elif p.is_dir() and (p / "__init__.py").is_file():
            out.append((p, True, "package"))
        elif p.is_file():
            low = p.name.lower()
            if low.endswith(".py"):
                out.append((p, True, "module"))
            elif low.endswith((".py.disabled", ".py.off", ".py.bak")):
                out.append((p, False, "module"))
    return out


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in _ENCODINGS:
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def _import_file(path: Path, modname: str):
    """加载源码。非 utf-8 的插件先落到缓存目录转码，importlib 才不会崩。"""
    src = path
    try:
        path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        cache = PLUGIN_DIR / "__cache__"
        cache.mkdir(parents=True, exist_ok=True)
        src = cache / (path.stem + ".py")
        src.write_text(_read_text(path), encoding="utf-8")

    spec = importlib.util.spec_from_file_location(modname, str(src))
    if spec is None or spec.loader is None:
        raise ImportError("不是可导入的 Python 文件")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def _import_package(path: Path, modname: str):
    spec = importlib.util.spec_from_file_location(
        modname, str(path / "__init__.py"), submodule_search_locations=[str(path)])
    if spec is None or spec.loader is None:
        raise ImportError("包不可导入")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


# ── 元数据 ─────────────────────────────────────────────
def _first(obj, keys, default=None):
    for k in keys:
        if isinstance(obj, dict) and k in obj:
            return obj[k]
        v = getattr(obj, k, None)
        if v is not None:
            return v
    return default


def _meta(mod, path: Path, target=None) -> dict:
    """元数据容错：实例/类的属性优先，其次模块变量，最后退回文件名。"""
    name = _first(target, _NAME_KEYS) if target is not None else None
    if not name:
        name = _first(mod, _NAME_KEYS)
    if not name:
        name = path.stem
    ver = _first(target, _VER_KEYS, "") if target is not None else ""
    if not ver:
        ver = _first(mod, _VER_KEYS, "")
    desc = (_first(target, _DESC_KEYS) if target is not None else None) or _first(mod, _DESC_KEYS)
    if not desc:
        doc = (getattr(mod, "__doc__", "") or "").strip()
        if not doc and target is not None:
            doc = (getattr(target, "__doc__", "") or "").strip()
        desc = doc.splitlines()[0].strip() if doc else ""
    author = (_first(target, _AUTHOR_KEYS) if target is not None else None) or _first(mod, _AUTHOR_KEYS, "")
    enabled = True
    on = _first(mod, _ON_KEYS)
    off = _first(mod, _OFF_KEYS)
    if on is not None:
        enabled = bool(on)
    if off is not None:
        enabled = not bool(off)
    return {
        "name": str(name),
        "version": str(ver or ""),
        "desc": str(desc or ""),
        "author": str(author or ""),
        "enabled": enabled,
    }


def _target_of(mod):
    """模块本身，或者模块里那个「像插件」的类/实例。"""
    for attr in ("PLUGIN", "plugin", "star", "STAR"):
        obj = getattr(mod, attr, None)
        if obj is not None:
            return obj
    classes = []
    for _, obj in vars(mod).items():
        if inspect.isclass(obj) and obj.__module__ == mod.__name__:
            if any(callable(getattr(obj, h, None)) for h in _MSG_HOOKS):
                classes.append(obj)
    if not classes:
        return mod
    cls = classes[0]
    try:
        return cls()                     # 无参构造；AstrBot 风格插件多数可以
    except Exception:
        return cls                       # 构造要参数就用类本身（静态方法/类方法照样跑）


def _hook(obj, names):
    for n in names:
        fn = getattr(obj, n, None) if not isinstance(obj, dict) else obj.get(n)
        if callable(fn):
            return fn
    return None


def _commands_of(mod, target):
    for holder in (target, mod):
        for name in _CMD_HOOKS:
            v = getattr(holder, name, None) if not isinstance(holder, dict) else holder.get(name)
            if v is None:
                continue
            try:
                if callable(v):
                    v = v()
            except Exception:
                continue
            out = {}
            if isinstance(v, dict):
                for k, val in v.items():
                    out[str(k)] = str(val)
            elif isinstance(v, (list, tuple, set)):
                for item in v:
                    if isinstance(item, str):
                        out[item.split()[0] if item.split() else item] = item
                    elif isinstance(item, (list, tuple)) and len(item) >= 1:
                        out[str(item[0])] = str(item[1]) if len(item) > 1 else ""
                    elif isinstance(item, dict):
                        cmd = item.get("cmd") or item.get("command") or item.get("name")
                        if cmd:
                            out[str(cmd)] = str(item.get("desc") or item.get("help") or "")
            if out:
                return out
    return {}


# ── 调用适配 ───────────────────────────────────────────
async def _maybe_await(v):
    return await v if inspect.isawaitable(v) else v


async def _call_reply(fn, ans: str, ctx: Ctx):
    """调用 on_reply：按 (ans, ctx) → (ans) → (ctx) 的顺序试，取第一个不报错的。

    以前偷懒直接把 ctx 当第一个参数传，结果是 ans 变成了 dict，回复里出现
    "{'text': '...'}" 这种东西——插件没错，是调用约定错了。
    """
    candidates = (
        lambda: fn(ans, ctx),
        lambda: fn(ans),
        lambda: fn({"reply": ans, "text": ans}),
    )
    for make in candidates:
        try:
            return await _maybe_await(make())
        except TypeError:
            continue
    return None


def _call_init(init, api):
    """INIT_FIX_1106：调 setup(api) / register(api) 这类初始化钩子。

    它拿到的是插件 API（读配置、发消息、写记忆、定时器），不是消息上下文。
    按 init(api) → init() → init(**{}) 依次试，只降级 TypeError。
    同步返回原值，异步返回可 await 对象，交给调用方决定要不要 create_task。
    """
    for make in (lambda: init(api), lambda: init(), lambda: init(**{})):
        try:
            return make()
        except TypeError:
            continue
    return None


async def _call_any(fn, ctx: Ctx):
    """按优先级试几种签名；只有 TypeError 才降级，避免误判插件内部错误。"""
    text = ctx.get_text()
    tries = (
        lambda: fn(ctx),
        lambda: fn(text, ctx),
        lambda: fn(text),
        lambda: fn(),
        lambda: fn(**{k: v for k, v in ctx.items() if isinstance(k, str) and k.isidentifier()}),
    )
    last = None
    for make in tries:
        try:
            return await _maybe_await(make())
        except TypeError as e:
            last = e
            continue
        except Exception:
            raise
    if last:
        raise last
    return None


def _result_to_reply(res, ctx: Ctx):
    """返回值归一化：str 视为要发出去的话。"""
    if isinstance(res, str) and res.strip():
        return True, res
    return bool(res), None


# ── 加载 ───────────────────────────────────────────────
def _unload():
    for p in list(_LOADED):
        name = p.get("modname")
        if name and name in sys.modules:
            sys.modules.pop(name, None)
    _LOADED.clear()


def load_all(verbose: bool = True) -> int:
    """扫描并加载全部插件，返回可用插件数。可重复调用（热重载）。"""
    global _READY
    _unload()
    ok = 0
    for path, name_enabled, kind in _iter_units():
        stem = path.stem if kind == "module" else path.name
        modname = "fish_plugin_" + re.sub(r"\W", "_", stem)
        rec = {
            "name": stem, "version": "", "desc": "", "author": "",
            "enabled": bool(name_enabled), "path": path, "modname": modname,
            "module": None, "target": None, "error": "", "missing": "",
            "kind": kind, "commands": {}, "hooks": [],
        }
        if kind == "manifest":
            # 纯界面插件：目录里只有 plugin.json + html/css/js，不执行任何 Python
            try:
                import json as _json
                man = _json.loads((path / "plugin.json").read_text(encoding="utf-8-sig"))
            except Exception as e:
                rec["error"] = f"plugin.json 读不了: {e}"
                _LOADED.append(rec)
                continue
            rec["name"] = str(man.get("name") or path.name)
            rec["version"] = str(man.get("version") or "")
            rec["desc"] = str(man.get("desc") or "")
            rec["author"] = str(man.get("author") or "")
            rec["enabled"] = bool(man.get("enabled", True)) and name_enabled
            rec["caps"] = list(man.get("caps") or ["ui"])
            rec["manifest"] = man
            rec["module"] = None
            rec["target"] = None
            rec["hooks"] = ["ui_html", "ui_css", "ui_js", "assets"]
            rec["commands"] = dict(man.get("commands") or {})
            _LOADED.append(rec)
            continue

        if not name_enabled and kind == "module" and path.suffix != ".py":
            # .disabled / .off：不导入（后缀不是 .py 导进来必失败），只安全地读一下名字和版本
            try:
                import ast
                tree = ast.parse(_read_text(path))
                for node in tree.body:
                    if isinstance(node, ast.Assign) and len(node.targets) == 1:
                        tgt = node.targets[0]
                        if isinstance(tgt, ast.Name) and tgt.id in ("NAME", "VERSION", "DESC"):
                            with __import__("contextlib").suppress(Exception):
                                rec[{"NAME": "name", "VERSION": "version",
                                     "DESC": "desc"}[tgt.id]] = str(ast.literal_eval(node.value))
            except Exception:
                pass
            rec["error"] = ""
            _LOADED.append(rec)
            continue
        try:
            mod = _import_package(path, modname) if kind == "package" else _import_file(path, modname)
            rec["module"] = mod
            target0 = _target_of(mod)
            rec.update(_meta(mod, path, target0))
            rec["enabled"] = bool(rec["enabled"] and name_enabled)
            target = _target_of(mod)
            rec["target"] = target
            rec["commands"] = _commands_of(mod, target)
            rec["caps"] = list(getattr(target, "CAPS", ()) or [])
            rec["hooks"] = [h for h in (_MSG_HOOKS + _REPLY_HOOKS + _UI_HOOKS + _HTTP_HOOKS + _CONFIG_HOOKS)
                            if callable(getattr(target, h, None) if not isinstance(target, dict)
                                        else target.get(h))]

            init = _hook(target, _INIT_HOOKS) or _hook(mod, _INIT_HOOKS)
            if init:
                try:
                    # INIT_FIX_1106：init 钩子收的是 PluginAPI，不是消息的 Ctx。
                    # 以前图省事借 _call_any 来调，而它第一条就是 ctx.get_text()，
                    # PluginAPI 没这个方法 → 抛 AttributeError 被 create_task 吞掉，
                    # 结果所有插件的 setup(api)（api.every / memory_add / notify / set_cfg）全部失效。
                    r = _call_init(init, make_api(rec["name"]))
                    if inspect.isawaitable(r):
                        asyncio.get_event_loop().create_task(r)
                except Exception as e:
                    rec["error"] = f"init 失败（已忽略）：{type(e).__name__}: {e}"
                    if verbose:
                        print(f"[plugins] {rec['name']} init 失败：{rec['error']}", flush=True)
            if rec["hooks"]:
                ok += 1
        except (ImportError, ModuleNotFoundError) as e:
            rec["error"] = f"缺依赖：{e.name or e}"
            rec["missing"] = getattr(e, "name", "") or ""
            rec["name"] = rec["name"] or stem
        except SyntaxError as e:
            rec["error"] = f"语法错误：第 {e.lineno} 行 {e.msg}"
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            if verbose:
                print(f"[plugins] {stem} 加载异常：{rec['error']}", flush=True)
        _LOADED.append(rec)
    _READY = True
    if verbose:
        usable = [p for p in _LOADED if p["enabled"] and p["hooks"]]
        bad = [p for p in _LOADED if p["error"]]
        print(f"[plugins] 可用 {len(usable)} 个："
              f"{', '.join(p['name'] for p in usable) or '（无）'}", flush=True)
        if bad:
            print(f"[plugins] 有 {len(bad)} 个装不上："
                  f"{', '.join(p['name'] + '(' + p['error'][:40] + ')' for p in bad)}", flush=True)
    return ok


def list_plugins() -> list[dict]:
    if not _READY:
        load_all(verbose=False)
    return [{
        "name": p["name"], "version": p["version"], "desc": p["desc"], "author": p["author"],
        "enabled": p["enabled"], "path": p["path"].name, "kind": p["kind"],
        "commands": p["commands"], "hooks": p["hooks"],
        "error": p["error"], "missing": p["missing"],
    } for p in _LOADED]


def _find(identifier: str):
    ident = str(identifier or "").strip()
    for p in _LOADED:
        if ident in (p["name"], p["path"].name, p["path"].stem, Path(p["path"]).stem):
            return p
    return None


def set_enabled(identifier: str, on: bool) -> bool:
    """开关插件。禁用不改文件名，只在内存里生效（重启后重新按 ENABLED 判断）。"""
    p = _find(identifier)
    if not p:
        return False
    p["enabled"] = bool(on)
    return True


async def dispatch(ctx: dict) -> bool:
    """把消息交给插件。任一插件返回 True（或回了文本）就算处理完。"""
    if not _READY:
        load_all()
    c = _wrap_ctx(ctx)
    for p in _LOADED:
        if not p["enabled"]:
            continue
        target = p["target"] or p["module"]
        fn = _hook(target, _MSG_HOOKS)
        if not callable(fn):
            continue
        try:
            res = await asyncio.wait_for(_call_any(fn, c), timeout=PLUGIN_TIMEOUT)
            handled, text = _result_to_reply(res, c)
            if text:
                await c.say(text)
            if handled:
                return True
        except asyncio.TimeoutError:
            p["error"] = f"超时（>{PLUGIN_TIMEOUT}s）"
            print(f"[plugins] {p['name']} 超时，跳过", flush=True)
        except Exception as e:
            p["error"] = f"{type(e).__name__}: {e}"
            print(f"[plugins] {p['name']} 出错（已隔离）：{p['error']}", flush=True)
            if "--plugin-debug" in sys.argv:
                print(traceback.format_exc()[-800:], flush=True)
    return False


async def dispatch_reply(ans: str, ctx: dict | None = None) -> str:
    """让插件改写最终回复（出口钩子）。

    每个插件都可以实现 on_reply(ans, ctx) -> str；按加载顺序串起来，
    任何一个抛异常就跳过它，不影响别的插件，也不影响这条消息本身。
    """
    if not _READY:
        load_all(verbose=False)
    out = ans
    c = _wrap_ctx(ctx or {})
    for p in _LOADED:
        if not p["enabled"]:
            continue
        target = p["target"] or p["module"]
        fn = _hook(target, _REPLY_HOOKS)
        if not callable(fn):
            continue
        try:
            r = await asyncio.wait_for(_call_reply(fn, out, c), timeout=8)
            if isinstance(r, str) and r.strip():
                out = r
            elif isinstance(r, tuple) and r and isinstance(r[0], str) and r[0].strip():
                out = r[0]
        except Exception as e:
            p["error"] = f"on_reply: {type(e).__name__}: {e}"
    return out


def dispatch_reply_sync(ans: str, ctx: dict | None = None) -> str:
    """同步版出口钩子（HTTP 线程里用）。只调同步插件，异步插件跳过。"""
    if not _READY:
        load_all(verbose=False)
    out = ans
    c = _wrap_ctx(ctx or {})
    for p in _LOADED:
        if not p["enabled"]:
            continue
        target = p["target"] or p["module"]
        fn = _hook(target, _REPLY_HOOKS)
        if not callable(fn):
            continue
        r = None
        for call in (lambda: fn(out, c), lambda: fn(out), lambda: fn({"reply": out, "text": out})):
            try:
                r = call()
                break
            except TypeError:
                continue
            except Exception as e:
                p["error"] = f"on_reply: {type(e).__name__}: {e}"
                r = None
                break
        if inspect.isawaitable(r):
            r = None
        if isinstance(r, str) and r.strip():
            out = r
    return out


# ══════════════════════════════════════════════════════════
#  EXT_1106：给插件用的 API（拓展点）
#  插件写 setup(api) 就能拿到这些能力：读配置、发消息、查/加记忆、定时器、日志
# ══════════════════════════════════════════════════════════
_BOT: dict = {}
_TIMERS: list = []
_TIMER_TASK = None        # TIMER_LOOP_1106：定时器循环的句柄，防重复启动 / 防挂错 loop


def set_bot_hooks(**kw) -> None:
    """由 bot 注入真实实现（notify / cfg / memory / send）。"""
    _BOT.update(kw)


class PluginAPI:
    """传给插件的把手。拿不到的能力就是 None，插件自己判空即可。"""

    def __init__(self, name: str):
        self.name = name

    # ── 配置 ──
    def cfg(self, key: str | None = None, default=None):
        c = _BOT.get("cfg")
        c = c() if callable(c) else (c or {})
        return c.get(key, default) if key else c

    def set_cfg(self, key: str, value) -> bool:
        fn = _BOT.get("set_cfg")
        if not callable(fn):
            return False
        try:
            fn(key, value)
            return True
        except Exception:
            return False

    # ── 消息 ──
    def notify(self, text: str) -> bool:
        """给主人发一条（走 bot 自己的推送通道）。"""
        fn = _BOT.get("notify")
        if not callable(fn):
            return False
        try:
            r = fn(str(text))
            if inspect.isawaitable(r):
                loop = _BOT.get("loop")
                if loop:
                    loop.create_task(r)
            return True
        except Exception:
            return False

    # ── 主动发消息 ──
    def send(self, user_id, text: str) -> bool:
        """给某个 QQ 发一条私聊（插件做「主动接话」这类功能要用）。"""
        fn = _BOT.get("send")
        if not callable(fn):
            return False
        try:
            r = fn(str(user_id), str(text))
            if inspect.isawaitable(r):
                loop = _BOT.get("loop")
                if loop:
                    loop.create_task(r)
                else:
                    return False
            return True
        except Exception:
            return False

    # ── 记忆 ──
    def memory_add(self, text: str, kind: str = "fact", imp: float = 0.6,
                   subj: str = "", tags=None) -> bool:
        b = _BOT.get("memory")
        if b is None:
            return False
        try:
            b.add(text, "plugin:" + self.name, kind=kind, source="explicit",
                  subj=subj, imp=imp, tags=tags or [])
            return True
        except Exception:
            return False

    def memory_count(self) -> int:
        b = _BOT.get("memory")
        try:
            return len(b.nodes)
        except Exception:
            return -1

    # ── 定时器 ──
    def every(self, seconds: float, fn) -> None:
        """注册周期任务：每 seconds 秒调一次 fn(api)。"""
        _TIMERS.append({"plugin": self.name, "sec": float(seconds), "fn": fn, "next": 0.0})

    def log(self, *a) -> None:
        print("[plugin:" + self.name + "]", *a, flush=True)


def make_api(name: str) -> PluginAPI:
    return PluginAPI(name)


async def _timer_loop() -> None:
    import time as _t
    while True:
        now = _t.time()
        for t in list(_TIMERS):
            if now < t["next"]:
                continue
            t["next"] = now + max(1.0, t["sec"])
            try:
                r = t["fn"](make_api(t["plugin"]))
                if inspect.isawaitable(r):
                    await r
            except Exception as e:
                print(f"[plugins] 定时任务出错 {t['plugin']}: {type(e).__name__}: {e}", flush=True)
        await asyncio.sleep(0.5)


def start_timers(loop=None) -> None:
    """bot 启动时调一次，把插件注册的周期任务跑起来。

    TIMER_LOOP_1106：必须在「真正在跑的 loop」里起。以前 bot 在 import 阶段就调
    start_timers(None)，那会儿 loop 还没建，任务挂在临时 loop 上，主循环一启动就被销毁
    （日志里那句 Task was destroyed but it is pending，说的就是它），定时器永远不触发。
    现在记下任务句柄，重复调用直接忽略；调用方也改成了 main() 里 LOOP 就绪之后再调。
    """
    global _TIMER_TASK
    if not _TIMERS:
        return
    if _TIMER_TASK is not None and not _TIMER_TASK.done():
        return
    try:
        if loop is None:
            loop = asyncio.get_running_loop()
        _TIMER_TASK = loop.create_task(_timer_loop())
        print(f"[plugins] 定时任务 {len(_TIMERS)} 个已启动", flush=True)
    except Exception as e:
        print(f"[plugins] 定时任务启动失败: {e}", flush=True)


def ui_payload() -> list[dict]:
    """面板要注入的 UI：每个插件返回 {name, css, html, js}。

    插件里这样写就行：
        CAPS = ("ui",)
        def ui_html(): return "<div class='card'>...</div>"
        def ui_css():  return ".card{...}"
        def ui_js():   return "shayu.on('click', '#mybtn', ...)"
    """
    if not _READY:
        load_all(verbose=False)
    out = []
    for p in _LOADED:
        if not p["enabled"]:
            continue
        target = p["target"] or p["module"]
        caps = set(p.get("caps") or [])
        if "ui" not in caps and not any(callable(getattr(target, h, None)) for h in _UI_HOOKS):
            continue
        item = {"name": p["name"], "file": p["path"].name}
        man = p.get("manifest")
        if man:
            base = p["path"]
            for key in ("html", "css", "js"):
                fn = man.get(key) or (f"ui.{ 'htm' if key=='html' else key }")
                fp = base / str(fn)
                if not fp.exists() and key == "html":
                    fp = base / "ui.html"
                if fp.exists():
                    try:
                        item[key] = fp.read_text(encoding="utf-8-sig")
                    except Exception:
                        pass
            if "html" in item or "js" in item:
                out.append(item)
            continue
        for key, hooks in (("html", ("ui_html",)), ("css", ("ui_css",)), ("js", ("ui_js",))):
            fn = _hook(target, hooks)
            if not callable(fn):
                continue
            try:
                v = fn()
                if isinstance(v, str) and v.strip():
                    item[key] = v
            except Exception as e:
                p["error"] = f"{hooks[0]}: {type(e).__name__}: {e}"
        if len(item) > 2:
            out.append(item)
    return out


def http_route(name: str, path: str, query: dict | None = None, body: bytes = b""):
    """插件自己的 HTTP 接口：/plug/<插件>/<path>。

    返回 (status, payload)；插件没实现就返回 404，不会影响别的插件。
    """
    if not _READY:
        load_all(verbose=False)
    p = _find(name)
    if not p or not p["enabled"]:
        return 404, {"ok": False, "error": "没有这个插件"}
    target = p["target"] or p["module"]
    fn = _hook(target, _HTTP_HOOKS)
    if not callable(fn):
        # COMPAT_1106：没写接口就当成静态目录，直接读插件目录里的文件
        import mimetypes
        base = p["path"] if p["path"].is_dir() else p["path"].parent
        rel = (path or "").lstrip("/") or "index.html"
        if ".." in rel.split("/"):
            return 400, {"ok": False, "error": "bad path"}
        fp = base / rel
        if fp.is_file():
            ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
            try:
                return 200, fp.read_bytes(), ctype   # 二进制由调用方按 ctype 发
            except Exception as e:
                return 500, {"ok": False, "error": str(e)}
        return 404, {"ok": False, "error": "no such file"}
    try:
        r = None
        for call in (lambda: fn(path, query or {}, body), lambda: fn(path), lambda: fn()):
            try:
                r = call()
                break
            except TypeError:
                continue
        if inspect.isawaitable(r):
            return 500, {"ok": False, "error": "异步 HTTP 钩子请用同步函数"}
        if isinstance(r, tuple) and len(r) == 2:
            return int(r[0]), r[1]
        return 200, r if r is not None else {"ok": True}
    except Exception as e:
        p["error"] = f"http: {type(e).__name__}: {e}"
        return 500, {"ok": False, "error": f"{type(e).__name__}: {e}"}


def apply_config_hooks(cfg: dict) -> dict:
    """启动时让插件看一眼配置（可以是补默认值、纠正老配置）。"""
    if not _READY:
        load_all(verbose=False)
    for p in _LOADED:
        if not p["enabled"]:
            continue
        fn = _hook(p["target"] or p["module"], _CONFIG_HOOKS)
        if not callable(fn):
            continue
        try:
            out = fn(cfg)
            if isinstance(out, dict):
                cfg = out
        except Exception as e:
            p["error"] = f"on_config: {type(e).__name__}: {e}"
    return cfg


def reload_plugin(identifier: str) -> bool:
    """只重载一个（改完插件代码不用重启）。"""
    p = _find(identifier)
    if not p:
        return False
    keep = p.get("enabled", True)
    load_all(verbose=False)
    q = _find(identifier)
    if q:
        q["enabled"] = keep
    return True


def stats() -> dict:
    if not _READY:
        load_all(verbose=False)
    return {
        "total": len(_LOADED),
        "usable": sum(1 for p in _LOADED if p["enabled"] and p["hooks"]),
        "broken": sum(1 for p in _LOADED if p["error"]),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
