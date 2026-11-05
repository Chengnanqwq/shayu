"""表情图库插件（MEME_1105b）—— 接到现有的 emotes/ 体系上。

上一版新建了 meme_img/ 目录，跟 bot.py 里已经有的 emotes/ 体系（157 张、
load_emotes() / match_emote() / [表情:标签] 标记）重复了。现在合并：

  · 收图直接写进 emotes/自动收集/，文件名按现有规范「自动收集_收到的_<hash>.<ext>」
    （load_emotes 取文件名第二段当标签 → 标签就是「收到的」）
  · 收完调 ctx["reload_emotes"]()，不用重启就能被 [表情:收到的] 和随机表情用到
  · /发表情 直接走同一条路：扫 emotes/ 选图，send_image 发出去
"""
import hashlib
import os
import random
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
NAME = "表情图库"

EMOTE_ROOT = _root() / "emotes"
INBOX = EMOTE_ROOT / "自动收集"
EXTS = (".gif", ".png", ".jpg", ".jpeg")


def commands() -> dict:
    return {"/发表情 [关键词]": "随机发一张表情", "/表情库": "看库里有多少张"}


def _all() -> list:
    if not EMOTE_ROOT.exists():
        return []
    return [f for f in EMOTE_ROOT.rglob("*") if f.is_file() and f.suffix.lower() in EXTS]


def _tag_of(p: Path) -> str:
    parts = p.stem.split("_")
    return parts[1] if len(parts) >= 2 else p.stem


def _collect(images: list, ctx: dict) -> int:
    if not images:
        return 0
    INBOX.mkdir(parents=True, exist_ok=True)
    added = 0
    for b in images:
        if not (5000 <= len(b) <= 2 * 1024 * 1024):
            continue
        h = hashlib.md5(b).hexdigest()[:10]
        ext = ".gif" if b[:3] == b"GIF" else (".png" if b[:4] == b"\x89PNG" else ".jpg")
        p = INBOX / ("自动收集_收到的_%s%s" % (h, ext))
        if p.exists():
            continue
        try:
            p.write_bytes(b)
            added += 1
        except Exception:
            continue
    if added:
        try:
            fn = ctx.get("reload_emotes")
            if callable(fn):
                fn()          # 让 bot 的 EMOTES 立刻认识新图
        except Exception:
            pass
        print(f"[meme] 收进 emotes {added} 张", flush=True)
    return added


async def on_message(ctx: dict) -> bool:
    raw = (ctx.get("raw") or "").strip()

    # 收图：主人/管理员发的图自动进 emotes（不吞消息）
    if (ctx.get("is_master") or ctx.get("is_admin")) and not raw.startswith("/"):
        if ctx.get("images"):
            _collect(ctx["images"], ctx)
        return False

    if raw.startswith("/表情库"):
        fs = _all()
        if not fs:
            await ctx["reply"]("一张图都没有")
            return True
        from collections import Counter
        c = Counter(_tag_of(f) for f in fs)
        top = "、".join(f"{k}×{v}" for k, v in c.most_common(6))
        await ctx["reply"](f"表情库 {len(fs)} 张（{len(c)} 个标签）：{top}")
        return True

    if raw.startswith("/发表情"):
        kw = raw[4:].strip()
        fs = _all()
        if not fs:
            await ctx["reply"]("没图可发")
            return True
        if kw:
            hit = [f for f in fs if kw in _tag_of(f) or kw in f.stem]
            fs = hit or fs
        p = random.choice(fs)
        try:
            await ctx["send_image"](str(p))
        except Exception as e:
            await ctx["reply"](f"发不出去：{str(e)[:50]}")
        return True

    return False
