"""QQ 资料插件（PROFILE_1105）—— 移植 astrbot_plugin_qqprofile。

它只用了两个接口：
    set_qq_profile(nickname=...)  改昵称
    set_qq_avatar(file=...)       换头像

傻鱼原来只有换头像（avatar_candidates + set_qq_avatar），没有改昵称。
这里补上，并把换头像也收成命令。
"""
import os
from pathlib import Path

def _root() -> "Path":
    """插件所在目录的上一级就是安装根目录；换机器/换系统都不用改路径。"""
    here = Path(__file__).resolve().parent          # plugins/
    for cand in (here.parent,):                     # 安装根目录
        if cand.exists():
            return cand
    return here.parent


ENABLED = True
NAME = "QQ资料"

AVATAR_DIRS = [str(_root() / "avatars"), str(_root() / "avatar")]


def commands() -> dict:
    return {"/昵称 <名字>": "改 QQ 昵称", "/换头像 [关键词]": "换一张头像", "/头像列表": "看有哪些头像"}


def _avatars() -> list:
    out = []
    for d in AVATAR_DIRS:
        p = Path(d)
        if p.is_dir():
            out += [f for f in p.iterdir()
                    if f.is_file() and f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif")]
    return sorted(out)


async def on_message(ctx: dict) -> bool:
    raw = (ctx.get("raw") or "").strip()
    if not raw.startswith(("/昵称", "/换头像", "/头像列表")):
        return False
    if not (ctx.get("is_master") or ctx.get("is_admin")):
        return False
    call = ctx.get("call")

    if raw.startswith("/头像列表"):
        fs = _avatars()
        if not fs:
            await ctx["reply"]("头像目录是空的（放几张图到 avatars/ 里就能用）")
            return True
        await ctx["reply"]("可选头像 %d 张：%s" % (len(fs), "、".join(f.name for f in fs[:8])))
        return True

    if raw.startswith("/换头像"):
        kw = raw[4:].strip()
        fs = _avatars()
        if kw:
            fs = [f for f in fs if kw in f.name] or fs
        if not fs:
            await ctx["reply"]("没有可选的头像")
            return True
        import random
        pick = random.choice(fs)
        try:
            res = await call("set_qq_avatar", {"file": str(pick)})
        except Exception as e:
            await ctx["reply"](f"换头像失败：{type(e).__name__}")
            return True
        ok = isinstance(res, dict) and str(res.get("status") or res.get("retcode")) in ("ok", "0", "None")
        print(f"[profile] 换头像 {pick.name} -> {str(res)[:100]}", flush=True)
        await ctx["reply"]("换好了" if ok else "没换成")
        return True

    # /昵称 <名字>
    name = raw[3:].strip().strip("「」“”\"'")
    if not name:
        await ctx["reply"]("改什么？/昵称 小鲸鱼")
        return True
    if len(name) > 24:
        await ctx["reply"]("昵称太长了，24 字以内")
        return True
    try:
        res = await call("set_qq_profile", {"nickname": name})
    except Exception as e:
        await ctx["reply"](f"改昵称失败：{type(e).__name__}")
        return True
    ok = isinstance(res, dict) and str(res.get("status") or res.get("retcode")) in ("ok", "0", "None")
    print(f"[profile] 昵称改成 {name} -> {str(res)[:100]}", flush=True)
    await ctx["reply"](f"昵称改成「{name}」" if ok else "没改成")
    return True
