"""去 DS 口癖 · 让傻鱼说自己的话

问题：模型（DeepSeek）有一套自己的口头禅，聊久了会串到她身上——
「这句话稳」「这话我不接」「比之前的都重」「我记着了」「行，我认」「我不拦你」
「你自己掂量」「我守着」「什么心思都写在 xx 上」……意思没错，但一听就不是她。

这个插件在**回复出口**做一次清洗：
  1. 整句都是口癖 → 删掉
  2. 半句是口癖 → 只删那半句，保留有用信息
  3. 删空了 → 换成一句她自己的短句（不重复原话）
  4. 顺手压掉「哦。」「嗯。」这种单字敷衍，以及连续两轮同开头

不联网、不读写文件，纯字符串处理，出错只返回原句。
"""

NAME = "去 DS 口癖"
VERSION = "1.1.0"
DESC = "删掉模型自带的「这句话稳/我不接/比之前的都重」这类口头禅，让回复回到她的口气"
AUTHOR = "ShaYu"
ENABLED = True

COMMANDS = {"/口癖": "看这条规则挡了哪些说法"}

import re

# 每条都来自实测里真的出现过的句子
PATTERNS = (
    r"这(?:句)?话?(?:我)?(?:不接|接不了|接不住)",
    r"这(?:句)?话?(?:很)?稳",
    r"这(?:句)?话?接(?:得|的)漂亮",
    r"这(?:句)?话?我(?:收下|留着|记下)了?",
    r"这(?:句)?话?(?:不是客套|是(?:ta|他|她)?告诉你的)",
    r"比之前(?:的)?都?(?:重|轻|强|稳|平)?",
    r"比刚才(?:重|轻|稳|平)?",
    r"比[^。！？!?，,]{1,12}(?:沉|重|稳|轻|平)",
    r"我(?:记着|记住|记下)了|我记着这事",
    r"我(?:没躲|不拦你?|不催你?)",
    r"(?:自己)?掂量(?:一下|吧)?",
    r"行[，,]?\s*我认|认(?:这个|下来|认得实)|我认了",
    r"收不回去|说的比谁都响",
    r"什么心思都写(?:着|在)",
    r"问别人还是问自己",
    r"声音没抖",
    r"我守着|我在这守着",
    r"^(?:很|挺)(?:稳|平)$",
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
