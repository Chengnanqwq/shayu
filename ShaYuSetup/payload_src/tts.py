# -*- coding: utf-8 -*-
"""tts.py —— 可配置的语音合成（原文直发，不加工）

设计原则（按需求）：
  · 请求头/请求体都存“原文”，只做占位符替换，替换后逐字节发送
  · 不自动补 Content-Type / Authorization，不 JSON.parse 再序列化
  · 三种模式：文字提示语音(chat) / 预设音色(preset) / 语音克隆(clone)
  · 每种模式各有一套 path + 头 + 体，独立保存
"""

from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path

import requests

BASE = Path(__file__).parent
CONF = BASE / "tts_config.json"
AUDIO_DIR = BASE / "tts"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_HEADERS = ("Content-Type: application/json\n"
                   "api-key: {{api_key}}")

DEFAULT_BODY = ('{"model":"{{model}}","messages":[{"role":"assistant","content":"{{text}}"}],'
                '"audio":{"format":"mp3","voice":"{{voice}}"}}')

DEFAULTS = {
    "base_url": "https://api.xiaomimimo.com/v1",
    "api_key": "",
    "model": "mimo-v2.5-tts",
    "models": [],
    "mode": "preset",
    "modes": {
        "chat": {
            "path": "/chat/completions",
            "headers": DEFAULT_HEADERS,
            "body": DEFAULT_BODY,
        },
        "preset": {
            "path": "/chat/completions",
            "headers": DEFAULT_HEADERS,
            "body": DEFAULT_BODY,
            "voice": "冰糖",
            "voices": ["mimo_default", "冰糖", "茉莉", "苏打", "白桦", "Mia", "Chloe", "Milo", "Dean"],
        },
        "clone": {
            "path": "/chat/completions",
            "headers": DEFAULT_HEADERS,
            "body": ('{"model":"mimo-v2.5-tts-voiceclone",'
                     '"messages":[{"role":"assistant","content":"{{text}}"}],'
                     '"audio":{"format":"mp3","voice":"{{sample_b64}}"}}'),
            "voice": "",
            "sample": "",
            "clone_path": "",
            "clone_headers": DEFAULT_HEADERS,
            "clone_body": "",
        },
    },
    "timeout": 120,
}


def load() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        if CONF.exists():
            data = json.loads(CONF.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
                for k, v in DEFAULTS["modes"].items():
                    cfg.setdefault("modes", {}).setdefault(k, {})
                    for kk, vv in v.items():
                        cfg["modes"][k].setdefault(kk, vv)
    except Exception as e:
        print(f"[tts] 读配置失败: {e}")
    return cfg


def save(cfg: dict) -> None:
    try:
        old = load()
        for mode in ("chat", "preset", "clone"):
            src = ((cfg.get("modes") or {}).get(mode) or {})
            prev = ((old.get("modes") or {}).get(mode) or {})
            for k in ("sample", "voices"):
                if not src.get(k) and prev.get(k):
                    src[k] = prev[k]
    except Exception:
        pass
    CONF.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def fill(template: str, mapping: dict) -> str:
    """只做占位符替换，别的什么都不做。"""
    out = str(template or "")
    for k, v in mapping.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


def parse_headers(raw: str, mapping: dict) -> dict:
    """把原文头解析成 dict：一行一个 K: V；值只做占位替换，不补任何头。"""
    headers = {}
    for line in fill(raw, mapping).split("\n"):
        line = line.rstrip("\r")
        if not line.strip() or ":" not in line:
            continue
        k, v = line.split(":", 1)
        headers[k.strip()] = v.strip()
    return headers


def _extract_audio(resp: requests.Response) -> tuple[bytes | None, str]:
    ctype = (resp.headers.get("content-type") or "").lower()
    if "audio" in ctype or ctype.startswith("application/octet-stream"):
        return resp.content, "bin"
    try:
        data = resp.json()
    except Exception:
        return None, "非音频响应: " + resp.text[:200]
    # 常见返回：audio.data(base64) / data.audio / audio_url / url
    candidates = []
    def walk(x, depth=0):
        if depth > 5:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("data", "audio", "b64", "base64", "content") and isinstance(v, str) and len(v) > 200:
                    candidates.append(("b64", v))
                elif k in ("url", "audio_url") and isinstance(v, str) and v.startswith("http"):
                    candidates.append(("url", v))
                else:
                    walk(v, depth + 1)
        elif isinstance(x, list):
            for v in x:
                walk(v, depth + 1)
    walk(data)
    for kind, val in candidates:
        if kind == "b64":
            try:
                return base64.b64decode(val), "b64"
            except Exception:
                continue
        if kind == "url":
            try:
                r = requests.get(val, timeout=60)
                if r.ok and r.content:
                    return r.content, "url"
            except Exception:
                continue
    return None, "JSON 里没找到音频: " + json.dumps(data, ensure_ascii=False)[:200]


_SAMPLE_CACHE = {}


def synth(text: str, mode: str | None = None, voice: str | None = None) -> dict:
    """合成一句话，返回 {ok, path, error}。原文头体直发。"""
    cfg = load()
    mode = mode or cfg.get("mode") or "chat"
    m = cfg["modes"].get(mode) or cfg["modes"]["chat"]
    sample_b64 = ""
    if mode == "clone":
        sp = (m.get("sample") or "")
        if sp and Path(sp).exists():
            # 每次重新 base64 编码样本很费时间（样本几十 KB 起），按 mtime 缓存
            global _SAMPLE_CACHE
            try:
                _mt = Path(sp).stat().st_mtime
            except Exception:
                _mt = 0
            _key = (str(sp), _mt)
            if _SAMPLE_CACHE.get("key") != _key:
                _b64 = base64.b64encode(Path(sp).read_bytes()).decode()
                _mime = "audio/wav" if str(sp).lower().endswith(".wav") else "audio/mpeg"
                _SAMPLE_CACHE = {"key": _key, "val": f"data:{_mime};base64,{_b64}"}
                print(f"[tts] 样本缓存 {sp} ({len(_b64)//1024} KB base64)")
            sample_b64 = _SAMPLE_CACHE["val"]
    mapping = {
        "text": text,
        "sample_b64": sample_b64,
        "model": cfg.get("model", ""),
        "api_key": cfg.get("api_key", ""),
        "voice": voice if voice is not None else m.get("voice", ""),
        "name": "fish_" + str(int(time.time())),
    }
    if mode == "chat" and "voicedesign" in str(cfg.get("model", "")) and not str(m.get("voice", "")).strip():
        return {"ok": False, "error": "文字提示语音缺「声音描述」：在 /tts 的 chat 页填上再试"}
    if mode == "clone" and not sample_b64:
        return {"ok": False, "error": "克隆模式还没上传音频样本：先在「语音克隆」里上传 wav/mp3，再点试听"}
    # 没填密钥就别真去请求：新装用户一路 401 很吵，直接跳过、回退成文字
    if not str(cfg.get("api_key") or "").strip() and not cfg.get("allow_no_key"):
        return {"ok": False, "error": "还没填 TTS 密钥：主程序侧栏「语音合成」里填一下就好"}
    url = cfg.get("base_url", "").rstrip("/") + m.get("path", "")
    headers = parse_headers(m.get("headers", ""), mapping)
    body = fill(m.get("body", ""), mapping).encode("utf-8")
    try:
        resp = requests.post(url, headers=headers, data=body, timeout=int(cfg.get("timeout", 120)))
    except Exception as e:
        return {"ok": False, "error": f"请求失败: {e}"}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
    audio, how = _extract_audio(resp)
    if not audio:
        return {"ok": False, "error": how}
    path = AUDIO_DIR / f"tts_{time.strftime('%Y%m%d_%H%M%S')}.mp3"
    path.write_bytes(audio)
    try:  # 只留最近 20 条合成结果，别把磁盘塞满
        olds = sorted(AUDIO_DIR.glob("tts_*.mp3"), key=lambda f: f.stat().st_mtime)
        for f in olds[:-20]:
            f.unlink(missing_ok=True)
    except Exception:
        pass
    return {"ok": True, "path": str(path), "how": how, "bytes": len(audio)}


def fetch_models() -> dict:
    """拉模型列表：两种认证头都试，返回可用的那个的结果。"""
    cfg = load()
    key = (cfg.get("api_key") or "").strip()
    if not key:
        return {"ok": False, "error": "还没填密钥（api-key），填完再拉", "models": []}
    url = cfg.get("base_url", "").rstrip("/") + "/models"
    last = ""
    for name, headers in (("Bearer", {"Authorization": "Bearer " + key}),
                          ("api-key", {"api-key": key})):
        try:
            r = requests.get(url, headers=headers, timeout=20)
        except Exception as e:
            last = f"{name}: {e}"
            continue
        if r.status_code == 200:
            try:
                data = r.json()
                ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
            except Exception:
                return {"ok": False, "error": f"返回不是 JSON: {r.text[:160]}", "models": []}
            cfg["models"] = ids
            save(cfg)
            return {"ok": True, "models": ids, "auth": name}
        last = f"{name}: HTTP {r.status_code} {r.text[:160]}"
    return {"ok": False, "error": "两种认证都失败 → " + last, "models": []}


def save_sample(name: str, b64: str) -> dict:
    try:
        raw = base64.b64decode(b64.split(",")[-1])
        suffix = ".wav" if name.lower().endswith(".wav") else (".mp3" if name.lower().endswith(".mp3") else ".bin")
        p = AUDIO_DIR / ("clone_" + str(int(time.time())) + suffix)
        p.write_bytes(raw)
        cfg = load()
        cfg["modes"]["clone"]["sample"] = str(p)
        save(cfg)
        try:
            for f in AUDIO_DIR.glob("clone_*.mp3"):
                if str(f) != str(p):
                    f.unlink(missing_ok=True)
        except Exception:
            pass
        return {"ok": True, "path": str(p), "bytes": len(raw)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def clone_voice() -> dict:
    """用已上传样本建音色：原文头体直发，{{audio_b64}} 是样本 base64。"""
    cfg = load()
    c = cfg["modes"]["clone"]
    sample = c.get("sample", "")
    if not sample or not Path(sample).exists():
        return {"ok": False, "error": "还没上传克隆样本"}
    b64 = base64.b64encode(Path(sample).read_bytes()).decode()
    mapping = {"api_key": cfg.get("api_key", ""), "model": cfg.get("model", ""),
               "name": "fish_" + str(int(time.time())), "audio_b64": b64}
    url = cfg.get("base_url", "").rstrip("/") + c.get("clone_path", "")
    headers = parse_headers(c.get("clone_headers", ""), mapping)
    body = fill(c.get("clone_body", ""), mapping).encode("utf-8")
    try:
        resp = requests.post(url, headers=headers, data=body, timeout=int(cfg.get("timeout", 120)))
        data = resp.json() if resp.content else {}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    if resp.status_code >= 400:
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
    vid = ""
    def find_voice(x):
        if isinstance(x, dict):
            for k in ("voice", "voice_id", "id"):
                if isinstance(x.get(k), str) and x[k]:
                    return x[k]
            for v in x.values():
                r = find_voice(v)
                if r:
                    return r
        elif isinstance(x, list):
            for v in x:
                r = find_voice(v)
                if r:
                    return r
        return ""
    vid = find_voice(data)
    if vid:
        c["voice"] = vid
        save(cfg)
    return {"ok": True, "voice": vid, "raw": json.dumps(data, ensure_ascii=False)[:300]}
