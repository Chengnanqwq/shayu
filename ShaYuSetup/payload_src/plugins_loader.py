"""极简插件加载器（PLUGIN_1105）—— 借 AstrBot 的 Star 思路，但不重构主流程。

约定：
  /opt/fish_bot/plugins/<名字>.py，每个插件可以定义：

      ENABLED = True                      # 可选，默认 True
      NAME = "插件显示名"                  # 可选

      async def on_message(ctx) -> bool:  # 可选，返回 True 表示这条消息我处理完了
      def commands() -> dict[str, str]:   # 可选，返回 {"/命令": "说明"}，用于 /插件 列表

ctx 是 dict：
  ws / evt / raw / user / is_admin / is_master / msg_type / reply(async fn)

原则：插件出错绝不影响主流程 —— 所有调用都包在 try 里，异常只记日志。
"""
import asyncio
import importlib.util
import os
import traceback
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent / "plugins"

_LOADED = []          # [{'name','module','path','enabled'}]
PLUGIN_TIMEOUT = 20   # 单个插件 on_message 的秒数上限
_READY = False


def _iter_files():
    if not PLUGIN_DIR.is_dir():
        return []
    return sorted(p for p in PLUGIN_DIR.glob("*.py") if not p.name.startswith("_"))


def load_all(verbose: bool = True) -> int:
    """扫描并加载全部插件，返回成功数。重复调用是安全的。"""
    global _READY
    _LOADED.clear()
    for path in _iter_files():
        try:
            spec = importlib.util.spec_from_file_location(
                "fish_plugin_" + path.stem, str(path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            enabled = bool(getattr(mod, "ENABLED", True))
            _LOADED.append({
                "name": str(getattr(mod, "NAME", path.stem)),
                "module": mod,
                "path": path,
                "enabled": enabled,
            })
        except Exception as e:
            print(f"[plugins] 加载失败 {path.name}: {type(e).__name__}: {e}", flush=True)
    _READY = True
    _n = sum(1 for p in _LOADED if p["enabled"])
    if verbose:
        names = ", ".join(p["name"] for p in _LOADED if p["enabled"]) or "（无）"
        print(f"[plugins] 已加载 {_n} 个插件：{names}", flush=True)
    return _n


def list_plugins() -> list[dict]:
    if not _READY:
        load_all(verbose=False)
    return [{"name": p["name"], "enabled": p["enabled"], "path": p["path"].name,
             "commands": _safe_commands(p["module"])} for p in _LOADED]


def _safe_commands(mod):
    try:
        fn = getattr(mod, "commands", None)
        if callable(fn):
            r = fn()
            return dict(r) if isinstance(r, dict) else {}
    except Exception:
        pass
    return {}


async def dispatch(ctx: dict) -> bool:
    """把消息交给插件。任一插件返回 True 就认为已被处理（主流程不再继续）。"""
    if not _READY:
        load_all()
    for p in _LOADED:
        if not p["enabled"]:
            continue
        fn = getattr(p["module"], "on_message", None)
        if not callable(fn):
            continue
        try:
            # 单个插件最多 20 秒，超时就跳过它 —— 插件写歪了不能把整条消息链拖死
            if await asyncio.wait_for(fn(ctx), timeout=PLUGIN_TIMEOUT):
                return True
        except asyncio.TimeoutError:
            print(f"[plugins] {p['name']} 超时（>{PLUGIN_TIMEOUT}s），跳过", flush=True)
        except Exception as e:
            print(f"[plugins] {p['name']} on_message 出错: {type(e).__name__}: {e}", flush=True)
            print(traceback.format_exc()[-600:], flush=True)
    return False
