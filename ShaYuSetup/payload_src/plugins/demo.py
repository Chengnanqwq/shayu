"""示例插件：/插件 列出当前加载的插件。

同时演示两个约定：
  1. commands() 返回 {"/命令": "说明"}，会被 /插件 汇总展示
  2. on_message(ctx) 返回 True 表示这条消息处理完了，主流程不再往下走
"""
ENABLED = True
NAME = "插件示例"


def commands() -> dict:
    return {"/插件": "列出已加载的插件"}


async def on_message(ctx: dict) -> bool:
    raw = (ctx.get("raw") or "").strip()
    if not raw.startswith("/插件"):
        return False
    try:
        import plugins_loader
        rows = plugins_loader.list_plugins()
    except Exception as e:
        await ctx["reply"]("插件系统没起来：" + str(e)[:80])
        return True
    if not rows:
        await ctx["reply"]("一个插件都没加载（plugins/ 目录是空的？）")
        return True
    lines = [f"插件 {sum(1 for r in rows if r['enabled'])}/{len(rows)} 个："]
    for r in rows:
        cmds = "、".join(r["commands"].keys())
        lines.append(f"· {r['name']}（{r['path']}）" + (f" {cmds}" if cmds else "")
                     + ("" if r["enabled"] else " [已关闭]"))
    await ctx["reply"]("\n".join(lines))
    return True
