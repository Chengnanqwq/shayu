# -*- coding: utf-8 -*-
"""growth.py —— 傻鱼的「自主学习 / 进化」（GROWTH_TIGHT_1104 收紧版）

旧版三个毛病，导致小本本里全是一晚上重复四遍的"学到"：
  1. 每次都必须输出 1~3 条 → 没东西可学也得凑；
  2. 没有任何去重 → 同一句话隔一轮又"学到"一遍；
  3. 提示词允许把一次失败反推成通用规律 → "语音音调太高会变沙哑"这种自己猜的
     东西被当成真理写进长期记忆。

现在：
  · 一次最多 1 条，真有明确的纠正/事实才记，否则输出「无」；
  · 写入前跟最近 80 条成长记录做规范化比对（同前缀/包含关系都算重复）；
  · 提示词明确禁止把单次事故写成通则、禁止写空话套话。
"""

from __future__ import annotations

import re
import time
from pathlib import Path

GROWTH_LOG = "growth.md"

SYSTEM = (
    "你在整理自己今天真正学到的东西。标准很严：只有「这次确实被纠正过的事实」"
    "或「某个具体的人身上确实发生的一件具体的事」才值得记。"
    "不要把一次失误反推成通用规律，不要写做人的道理，不要写空话。"
    "大多数时候你其实没什么新东西可学 —— 那种情况就只输出「无」。"
)

PROMPT = (
    "下面是最近发生的事和你现在的状态。\n\n"
    "{context}\n\n"
    "最多输出 1 行（真的没有新东西就只输出「无」），三种前缀选一种：\n"
    "学到：……  （必须是被明确纠正过、或当场确认过的事实；自己猜的、推断的都不算）\n"
    "认识：……  （某个具体的人做的一件具体的事，不是对「人性」的总结）\n"
    "决定：……  （下次具体怎么做，一句话，可执行）\n"
    "\n硬要求：\n"
    "· 不许把单次事故写成通则（例：某次调参数出问题 → 不能写成「某种操作一定怎样」）；\n"
    "· 不许写「要多观察」「要更细心」「别太当真」这类没有信息量的空话；\n"
    "· 不许复述已经记过的事；\n"
    "· 每条不超过 30 字。"
)

_PUNCT = re.compile(r"[\s，。！？、,.!?：:；;…\-—_()（）「」『』\"'“”]+")


def _norm(s: str) -> str:
    return _PUNCT.sub("", str(s or ""))[:60]


def _load_recent(brain, limit: int = 80) -> list[str]:
    """取最近若干条成长记录（用于去重）。"""
    try:
        base = Path(brain.dir) if brain is not None else Path(".")
        p = base / GROWTH_LOG
        if not p.exists():
            return []
        lines = [ln.strip() for ln in p.read_text(encoding="utf-8").split("\n") if ln.strip()]
        out = []
        for ln in lines[-limit:]:
            # "- 2026-11-04 04:43 学到：xxx" → "学到：xxx"
            out.append(re.sub(r"^-\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s*", "", ln))
        return out
    except Exception:
        return []


def _is_dup(text: str, existing: list[str]) -> bool:
    nt = _norm(text)
    if len(nt) < 4:
        return True
    for e in existing:
        ne = _norm(e)
        if not ne:
            continue
        if nt == ne:
            return True
        # 前缀相同（12 字足够判定是同一句），或互相包含
        if len(nt) >= 12 and len(ne) >= 12 and nt[:12] == ne[:12]:
            return True
        if nt in ne or ne in nt:
            return True
    return False


def _context(brain, core, recent: str) -> str:
    parts = []
    if core is not None:
        try:
            parts.append("【她的状态】\n" + core.block("", ""))
        except Exception:
            pass
    if recent:
        parts.append("【最近的事】\n" + recent[-1800:])
    return "\n\n".join(parts)


def grow_once(brain, core, llm_chat, recent: str) -> list[str]:
    """跑一次成长。返回这次真正新长出来的条目（通常 0~1 条）。"""
    ctx = _context(brain, core, recent)
    if not ctx.strip():
        return []
    try:
        out = llm_chat([{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": PROMPT.format(context=ctx)}],
                       timeout=60, max_tokens=160)
    except Exception as e:
        print(f"[growth] 成长失败: {e}")
        return []

    existing = _load_recent(brain)
    lines = []
    for raw in str(out).split("\n"):
        t = raw.strip().lstrip("-*·0123456789.、 ").strip()
        if not t or t == "无":
            continue
        if not t.startswith(("学到", "认识", "决定")):
            continue
        if len(t) > 46:
            t = t[:46]
        if len(t) < 6:
            continue
        if _is_dup(t, existing):
            print(f"[growth] 跳过重复：{t[:30]}")
            continue
        lines.append(t)
        break          # 一次只留一条

    if not lines:
        print("[growth] 这轮没什么新东西，留白")
        return []

    stamp = time.strftime("%Y-%m-%d %H:%M")
    for t in lines:
        try:
            if brain is not None:
                brain.add_insight(t, "growth", [], imp=0.6)
        except Exception as e:
            print(f"[growth] 写进脑子失败: {e}")
    try:
        base = Path(brain.dir) if brain is not None else Path(".")
        with (base / GROWTH_LOG).open("a", encoding="utf-8") as f:
            for t in lines:
                f.write(f"- {stamp} {t}\n")
    except Exception:
        pass
    if core is not None:
        try:
            core.observe("growth", "", " ".join(lines), "")
        except Exception:
            pass
    print(f"[growth] 长出 {len(lines)} 条：{lines[0][:30]}")
    return lines


def read_growth(brain, limit: int = 10) -> list[str]:
    try:
        base = Path(brain.dir) if brain is not None else Path(".")
        p = base / GROWTH_LOG
        if not p.exists():
            return []
        return [ln.strip() for ln in p.read_text(encoding="utf-8").split("\n") if ln.strip()][-limit:]
    except Exception:
        return []
