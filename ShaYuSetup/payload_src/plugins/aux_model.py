"""记忆副模（AUX_1106）—— 把「这句说给谁 / 值不值得记」这类杂活交给便宜模型

硅基流动（SiliconFlow）走的是 OpenAI 兼容接口，一个 key 能挑好几个小模型，
免费额度就够判「这句是不是在跟我说话」这种短任务了。

装法：面板参数里填 `aux_key`（硅基流动的 key），`aux_base` 默认就是官方地址；
不填 key 就不启用，一切照旧走主模型。

命令：
  /副模              看当前用哪个模型、调了几次、有没有失败
  /副模测试          逐个试一遍配置里的模型，回报延迟和结果
  /副模模型 <名字>    把某个模型提到首选（例如 Qwen/Qwen2.5-7B-Instruct）

它只提供 `aux_chat()` 这一个函数给主程序用：主程序问「这句说给谁」时会先找插件，
找不到/调不通再退回主模型，所以插件坏了也不会影响正常聊天。
"""
import json
import time
import urllib.error
import urllib.request

ENABLED = True
NAME = "记忆副模"
VERSION = "1.0.0"
DESC = "把「这句说给谁 / 值不值得记」这类杂活交给硅基流动等便宜模型，失败自动退回主模型"
AUTHOR = "ShaYu"

CAPS = ("http",)

_STATE = {"calls": 0, "ok": 0, "fail": 0, "last_model": "", "last_err": "", "last_ms": 0}

# 硅基流动上常见的免费/低价小模型；有 key 之后可以自己改 aux_models
DEFAULT_MODELS = ("Qwen/Qwen2.5-7B-Instruct", "THUDM/glm-4-9b-chat", "internlm/internlm2_5-7b-chat")


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
    return default


def _base() -> str:
    return str(_cfg("aux_base", "https://api.siliconflow.cn/v1") or "").rstrip("/")


def _key() -> str:
    return str(_cfg("aux_key", "") or "").strip()


def _models() -> list[str]:
    raw = str(_cfg("aux_models", "") or "").strip()
    if raw:
        out = [m.strip() for m in raw.replace("，", ",").split(",") if m.strip()]
    else:
        out = list(DEFAULT_MODELS)
    first = str(_cfg("aux_model", "") or "").strip()
    if first and first in out:
        out.remove(first)
    return ([first] if first else []) + out


def enabled() -> bool:
    return bool(_cfg("aux_enabled", False)) and bool(_key())


def _post(url: str, payload: dict, key: str, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode(), method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace") or "{}")


def aux_chat(messages, timeout: float = 15, max_tokens: int = 200,
             tag: str = "aux", temperature: float = 0.2) -> str:
    """主程序会先找这个函数。失败就抛异常，让主程序退回自己的模型。"""
    if not enabled():
        raise RuntimeError("副模没启用（aux_enabled/aux_key）")
    _STATE["calls"] += 1
    last = ""
    for model in _models():
        t0 = time.time()
        try:
            data = _post(_base() + "/chat/completions",
                         {"model": model, "messages": messages,
                          "temperature": float(temperature), "max_tokens": int(max_tokens)},
                         _key(), float(timeout))
            out = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            out = str(out).strip()
            if not out:
                raise RuntimeError("空回复")
            _STATE.update(ok=_STATE["ok"] + 1, last_model=model, last_err="",
                          last_ms=int((time.time() - t0) * 1000))
            return out
        except urllib.error.HTTPError as e:
            last = f"{model} → HTTP {e.code}"
            if e.code in (401, 403):
                break                      # key 有问题，换模型没用
        except Exception as e:
            last = f"{model} → {type(e).__name__}: {e}"
        _STATE["fail"] = _STATE["fail"] + 1
    _STATE["last_err"] = last[:120]
    raise RuntimeError(last or "所有副模都试过了，没一个回话")


def _probe(model: str, timeout: float = 20) -> dict:
    t0 = time.time()
    try:
        out = aux_chat([{"role": "user", "content": "只回一个词：在"}],
                       timeout=timeout, max_tokens=8, tag="probe", temperature=0.0)
        return {"model": model, "ok": True, "ms": int((time.time() - t0) * 1000), "reply": out[:40]}
    except Exception as e:
        return {"model": model, "ok": False, "ms": int((time.time() - t0) * 1000), "error": str(e)[:80]}


def commands() -> dict:
    return {
        "/副模": "记忆副模状态（模型 / 调用次数 / 失败原因）",
        "/副模测试": "逐个试一遍副模模型，看延迟",
        "/副模模型 <名字>": "把某个模型提到首选",
    }


def on_message(ctx):
    text = str(ctx.get("text") or "").strip()
    if not text.startswith("/副模"):
        return None
    is_admin = bool(ctx.get("is_master") or ctx.get("is_admin"))
    if not is_admin:
        return "这个只有管理员能看。"
    body = text[3:].strip()

    if body.startswith("测试"):
        rows = []
        for m in _models():
            r = _probe(m)
            rows.append(f"{'✅' if r['ok'] else '❌'} {m} · {r['ms']} ms"
                        + ("" if r["ok"] else f" · {r.get('error', '')[:40]}"))
        return "副模测试：\n" + "\n".join(rows[:8])

    if body.startswith("模型"):
        target = body[2:].strip()
        if not target:
            return "用法：/副模模型 Qwen/Qwen2.5-7B-Instruct"
        api = _api()
        try:
            if api:
                api.set_cfg("aux_model", target)
            return f"首选副模改成：{target}（下次调用生效）"
        except Exception as e:
            return f"改不了：{e}"

    st = (f"副模：{'开' if enabled() else '关'}\n"
          f"接口：{_base()}\n"
          f"候选：{', '.join(_models())}\n"
          f"调用：{_STATE['calls']} 次 / 成功 {_STATE['ok']} / 失败 {_STATE['fail']}\n"
          f"上次成功：{_STATE['last_model'] or '—'}（{_STATE['last_ms']} ms）")
    if _STATE["last_err"]:
        st += f"\n上次失败：{_STATE['last_err']}"
    if not _key():
        st += "\n还没填 aux_key（面板 → 参数设置 → 记忆副模）"
    return st


def handle_http(path, query=None, body=b""):
    if str(path or "").strip("/") in ("status", ""):
        return 200, {"ok": True, "enabled": enabled(), "base": _base(),
                     "models": _models(), "key_set": bool(_key()),
                     "calls": _STATE["calls"], "ok_count": _STATE["ok"],
                     "fail": _STATE["fail"], "last_model": _STATE["last_model"],
                     "last_ms": _STATE["last_ms"], "last_err": _STATE["last_err"]}
    return 404, {"ok": False, "error": "no such path"}
