"""QQ 空间插件（QZONE_1105）—— 移植 astrbot_plugin_qzone 的读/赞/评/访客/传图。

命令（只认主人和管理员）：
  /说说 [QQ]              看说说列表（默认自己）
  /赞 <序号>               给列表里第 N 条点赞
  /评论 <序号> <内容>       评论第 N 条
  /评论列表 <序号>          看第 N 条下的评论（楼层号）
  /回复 <说说序号> <楼层> <内容>  回复某条评论
  /访客                    最近访客
  /发说说 <文字>            发说说；消息里带图就发带图说说

序号 5 分钟内有效，指向「最近一次 /说说 的结果」。
"""
import asyncio
import time

ENABLED = True
NAME = "QQ空间"

try:
    import qzone_self as QZ
except Exception as _e:
    QZ = None
    print(f"[qzone] 模块不可用: {_e}", flush=True)

_LAST = {"ts": 0.0, "rows": [], "who": ""}
_TTL = 300


def commands() -> dict:
    return {
        "/说说 [QQ]": "看说说列表",
        "/赞 <序号>": "点赞",
        "/评论 <序号> <内容>": "评论",
        "/评论列表 <序号>": "看评论",
        "/回复 <说说序> <楼层> <内容>": "回复评论",
        "/访客": "最近访客",
        "/发说说 <文字>": "发说说（带图则发图）",
    }


def _fmt(rows, who):
    if not rows:
        return f"{who} 最近没发说说"
    out = [f"{who} 最近 {len(rows)} 条："]
    for i, r in enumerate(rows, 1):
        c = (r.get("content") or "(图片)").replace("\n", " ")[:38]
        out.append(f"{i}. {c}（{r.get('comments', 0)} 评）")
    out.append("赞 /赞 1　评论 /评论 1 说点啥　看评论 /评论列表 1")
    return "\n".join(out)


def _pick(n):
    if not _LAST["rows"] or time.time() - _LAST["ts"] > _TTL:
        return None
    if 1 <= n <= len(_LAST["rows"]):
        return _LAST["rows"][n - 1]
    return None


async def on_message(ctx: dict) -> bool:
    raw = (ctx.get("raw") or "").strip()
    if not raw.startswith(("/说说", "/赞", "/评论", "/回复", "/访客", "/发说说")):
        return False
    if not (ctx.get("is_master") or ctx.get("is_admin")):
        return False
    if QZ is None:
        await ctx["reply"]("空间模块没加载起来")
        return True

    # ---------- /访客 ----------
    if raw.startswith("/访客"):
        try:
            vs = await asyncio.to_thread(QZ.recent_visitors)
        except Exception as e:
            await ctx["reply"](f"访客读不到：{str(e)[:70]}")
            return True
        if not vs:
            await ctx["reply"]("最近没人来看")
            return True
        lines = [f"最近 {len(vs)} 个访客："]
        for v in vs[:8]:
            t = v.get("time")
            ts = time.strftime("%m-%d %H:%M", time.localtime(int(t))) if str(t).isdigit() else ""
            lines.append(f"· {v.get('name') or v.get('uin')} {ts}")
        await ctx["reply"]("\n".join(lines))
        return True

    # ---------- /发说说 ----------
    if raw.startswith("/发说说"):
        text = raw[4:].strip()
        if not text:
            await ctx["reply"]("发什么？/发说说 今天好热")
            return True
        imgs = ctx.get("images") or []
        try:
            if imgs:
                res = await asyncio.to_thread(QZ.publish_with_images, text, imgs)
            else:
                res = await asyncio.to_thread(QZ.publish, text)
        except Exception as e:
            await ctx["reply"](f"发失败：{str(e)[:70]}")
            print(f"[qzone] 发说说失败 {e}", flush=True)
            return True
        print(f"[qzone] 发说说 -> {res}", flush=True)
        await ctx["reply"]("发出去了")
        return True

    # ---------- /说说 ----------
    if raw.startswith("/说说"):
        arg = raw[3:].strip()
        target = None
        if arg:
            digits = "".join(ch for ch in arg if ch.isdigit())
            if len(digits) >= 5:
                target = digits
        try:
            rows = await asyncio.to_thread(QZ.list_feeds, target, 5)
        except Exception as e:
            await ctx["reply"](f"读说说失败：{str(e)[:70]}")
            return True
        _LAST.update(ts=time.time(), rows=rows, who=target or "我")
        await ctx["reply"](_fmt(rows, "我" if not target else f"QQ {target}"))
        return True

    # ---------- /评论列表 ----------
    if raw.startswith("/评论列表"):
        arg = raw[5:].strip()
        n = int(arg) if arg.isdigit() else 0
        row = _pick(n) if n else None
        if not row:
            await ctx["reply"]("先 /说说 看一眼，再 /评论列表 1")
            return True
        detail = row.get("comments_detail") or []
        if not detail:
            await ctx["reply"]("这条还没人评论")
            return True
        lines = [f"第 {n} 条的评论："]
        for c in detail:
            lines.append(f"{c.get('tid')}. {c.get('name') or c.get('uin')}：{c.get('content')}")
        lines.append("要回就 /回复 {} <楼层> 说点啥".format(n))
        await ctx["reply"]("\n".join(lines))
        return True

    # ---------- /回复 ----------
    if raw.startswith("/回复"):
        parts = raw[3:].strip().split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit():
            await ctx["reply"]("格式：/回复 1 1 说点啥")
            return True
        row = _pick(int(parts[0]))
        if not row:
            await ctx["reply"]("序号过期了，重新 /说说")
            return True
        detail = row.get("comments_detail") or []
        floor = parts[1]
        target_c = next((c for c in detail if str(c.get("tid")) == floor), None)
        if not target_c:
            await ctx["reply"](f"没有 {floor} 楼")
            return True
        try:
            ok, why = await asyncio.to_thread(
                QZ.reply_comment, row["tid"], row["uin"], floor,
                target_c.get("uin"), parts[2])
        except Exception as e:
            await ctx["reply"](f"回复失败：{str(e)[:60]}")
            return True
        await ctx["reply"]("回了" if ok else f"没回上：{why[:50]}")
        return True

    # ---------- /赞  /评论 ----------
    body = raw[2:].strip() if raw.startswith("/赞") else raw[3:].strip()
    parts = body.split(None, 1)
    if not parts or not parts[0].isdigit():
        await ctx["reply"]("格式：/赞 1 或 /评论 1 说点啥")
        return True
    row = _pick(int(parts[0]))
    if not row:
        await ctx["reply"]("先 /说说 看一眼，再说操作哪个")
        return True
    if not row.get("tid"):
        await ctx["reply"]("这条拿不到 tid")
        return True

    if raw.startswith("/赞"):
        try:
            ok = await asyncio.to_thread(QZ.like_post, row["tid"], row["uin"])
        except Exception as e:
            await ctx["reply"](f"点赞失败：{str(e)[:50]}")
            return True
        await ctx["reply"]("赞了" if ok else "没赞上（可能赞过了）")
        return True

    content = parts[1].strip() if len(parts) > 1 else ""
    if not content:
        await ctx["reply"]("评论得说点什么")
        return True
    try:
        ok, why = await asyncio.to_thread(QZ.comment_post, row["tid"], row["uin"], content)
    except Exception as e:
        await ctx["reply"](f"评论失败：{str(e)[:50]}")
        return True
    await ctx["reply"]("评好了" if ok else f"没评上：{why[:50]}")
    return True
