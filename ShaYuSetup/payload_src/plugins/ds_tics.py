"""去 DS 口癖 · 让傻鱼说自己的话

问题：模型（DeepSeek）有一套自己的口头禅，聊久了会串到她身上——
「这句话稳」「这话我不接」「比之前的都重」「我记着了」「行，我认」「我不拦你」
「你自己掂量」「我守着」「什么心思都写在 xx 上」……意思没错，但一听就不是她。

这一版按「DS 口癖大全」那张图把清单补全了（40+ 条）：
  但他没躲 / 这个账我记住了 / 你去，我跟 / 睡吧，我守着 / 没接你的 xxx /
  他记得这事 / 认你 / 不催 / 这是别人告诉你的还是你自己想明白的 / xx 就是认了 /
  很直 / 稳 / 平 / 回去睡 / 我跟 ……

在**回复出口**做一次清洗：
  1. 整句都是口癖 → 删掉
  2. 半句是口癖 → 只删那半句，保留有用信息
  3. 删空了 → 换成一句她自己的短句（不重复原话）
  4. 顺手压掉「哦。」「嗯。」这种单字敷衍，以及连续两轮同开头

不联网、不读写文件，纯字符串处理，出错只返回原句。
"""

NAME = "去 DS 口癖"
VERSION = "1.2.0"
DESC = "删掉模型自带的口头禅（按 DS 口癖大全补齐 40+ 条），让回复回到她的口气"
AUTHOR = "ShaYu"
ENABLED = True

COMMANDS = {"/口癖": "看这条规则挡了哪些说法"}

import re

# 顺序有讲究：长句在前，避免「比之前的都重」被「比…重」先啃掉一半
PATTERNS = (
    # —— 长句 / 带从句的，先匹配 ——
    r"这(?:句)?话?是[^，,。！？]{1,6}告诉你的[，,]?\s*还是你自己想(?:的|明白的)?",
    r"声音没(?:抖|变)[，,]?\s*(?:但|只是)?比刚才(?:稳|重|轻|平)?",
    r"你?这(?:句)?话?我(?:记着|记住|记下)了?(?:这事)?",
    r"(?:他|她|你|ta)(?:还)?记得这事",
    r"没接你(?:的|那句)[^，,。！？!?\s]{0,8}",
    r"你(?:去|走|先走)[，,]?\s*(?:我)?跟(?:上|着)?",
    r"睡吧[，,]?\s*我(?:守着|在这守着)?",
    r"这(?:句)?话?(?:我)?(?:不接|接不了|接不住)",
    r"这(?:句)?话?(?:很)?稳(?:了|得很)?",
    r"这(?:句)?话?接(?:得|的)漂亮",
    r"这(?:句)?话?(?:我)?(?:收下|留着|记下)了?",
    r"这(?:句)?话?(?:不是客套|是(?:ta|他|她)?告诉你的)",
    r"比之前(?:的)?都?(?:重|轻|强|稳|平)",
    r"比刚才(?:稳|重|轻|平)",
    r"比[^。！？!?，,]{1,12}(?:沉|重|稳|轻|平)",
    r"这(?:个)?账我?(?:记着|记住|记下)了?",
    r"但?(?:他|她|你)?没躲",                     # 但他没躲
    r"什么心思都写(?:着|在)?[^，,。！？\s]{0,10}(?:上|了)?",
    r"问别人还是问自己",
    r"(?:自己)?掂量(?:一下|吧)?",
    r"行[，,]?\s*(?:我)?认(?:得实|这个|下来|了)?",
    r"[^，,。！？\s]{1,6}就是认了",
    r"我?(?:也)?不拦(?:你)?|我?(?:也)?不催(?:你)?",
    r"我(?:记着|记住|记下)了|我记着这事",
    r"我(?:没躲)",
    r"收不回去|说的比谁都响",
    r"我(?:守着|在这守着)",
    r"认(?:得实|这个|下来|你)",
    r"^(?:很|挺)(?:稳|平|直)[。！？!?]?$",
    r"^(?:稳|平|直)[。！？!?]?$",
    r"^我跟[。！？!?]?$",
    r"^回去睡(?:吧|了)?[。！？!?]?$",
    r"^不催[。！？!?]?$",
)
RE = re.compile("|".join(PATTERNS))
SPLIT = re.compile(r"(?<=[。！？!?…\n])")

FILLER_OPEN = ("哦", "嗯", "啊", "唉", "行吧", "好吧")
FALLBACK = ("嗯，你说。", "我听着呢。", "说下去。", "然后呢。", "你继续。")

STATE = {"cleaned": 0, "seen": 0, "last": ""}


def clean(text: str) -> str:
    """核心：把口癖句去掉，剩下的拼回来。"""
    a = (text or "").strip()
    if not a:
        return a
    kept = []
    for seg in SPLIT.split(a):
        if not seg.strip():
            continue
        if RE.search(seg):
            rest = RE.sub("", seg)
            rest = re.sub(r"^[，,、\s]+", "", rest)
            rest = re.sub(r"[，,、\s]+$", "", rest).strip()
            if len(rest.strip("。！？!?… ")) >= 4:
                if rest[-1] not in "。！？!?…":
                    rest += "。"
                kept.append(rest)
            continue
        kept.append(seg)
    out = "".join(kept).strip()
    out = re.sub(r"^[，,、\s]+", "", out)
    out = re.sub(r"([。！？!?])\1+", r"\1", out)
    out = re.sub(r"^行[，,]\s*", "", out)
    if not out:
        out = FALLBACK[sum(map(ord, a)) % len(FALLBACK)]
    return out


def de_tic(text: str) -> str:
    """顺带压单字敷衍和连续同开头。"""
    if (text or "").strip("。.…，, 　") == "":
        return text          # 「……」这类占位回复，原样放过
    a = clean(text)
    prev = STATE["last"]
    for t in FILLER_OPEN:
        if a.startswith(t) and prev.startswith(t):
            rest = a[len(t):].lstrip("，,。.、…~ 　")
            if rest:
                a = rest
            break
    bare = a.strip("。.…，, 　")
    if len(bare) <= 1 and len(prev.strip("。.…，, 　")) <= 1:
        a += "你自己心里没数？"
    STATE["last"] = a
    return a


def on_reply(ans, ctx=None):
    """出口钩子：插件加载器会在每条回复发出前调它。"""
    STATE["seen"] += 1
    new = de_tic(ans)
    if new != ans:
        STATE["cleaned"] += 1
    return new


def commands():
    return COMMANDS


def stats():
    return {"总数": STATE["seen"], "改过": STATE["cleaned"]}
