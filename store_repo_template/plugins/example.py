"""示例插件：发 /ping 回一句 pong。

想分享自己的插件，就照着这个文件的结构写一个 .py 丢进 plugins/，
再把它的信息加进 index.json（用傻鱼面板里的「分享」按钮会自动做这两件事）。

一个插件最少要有：ENABLED / NAME，和 commands() 或 on_message() 之一。
"""
ENABLED = True
NAME = "示例插件"
VERSION = "1.0.0"


def commands():
    return {"/ping": "测试一下：回一句 pong"}


async def on_message(ctx):
    raw = (ctx.get("raw") or "").strip()
    if not raw.startswith("/ping"):
        return False
    await ctx["reply"]("pong")
    return True
