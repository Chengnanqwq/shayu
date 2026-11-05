# -*- coding: utf-8 -*-
"""soul.py —— 傻鱼的「核心」，那颗一直亮着的光球。

和记忆分开跑：

  · 人格 / 性格 / 底线：写死在她自己身上，不会被记忆整理覆盖
  · 情绪：有值（好受度 v / 上头度 a），会随时间回落，被对话推动
  · 对每个人的关系温度：骂一次掉很多，哄一次只涨一点（所以修复要花力气）
  · 记仇：气到一定程度会记下来，进小本本；没消气之前一直挂在心上
  · 关注：最近在惦记的两三件事
  · 画像：一段 1~2 句的自我描述，隔一阵子由她自己重写一次（LLM 可选）

存储：soul.json，几百字节到几 KB。文件坏了会自动备份并从默认人格重新长出来，
所以「鱼很难死」——上下文爆了、窗口重开，她还是她。

单独跑：python soul.py [目录]
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from pathlib import Path

STORE = "soul.json"

DEFAULT_SELF = "我是傻鱼，一只住在 QQ 里的小鲸鱼。蓝头发，头顶一个盆，嘴硬心软。"

# 初始性格：留空让她在相处中长出来；想预设就照下面这种写
DEFAULT_TRAITS = []

DEFAULT_VALUES = ["答应的事要做到", "不骗主人", "被欺负要顶回去"]

# 六维驱动：好奇 / 社交 / 玩心 / 休息 / 被看见 / 成就（0~1，会自己回落）
DRIVES = ("curiosity", "social", "play", "rest", "recognition", "achievement")
DRIVE_LABEL = {"curiosity": "好奇", "social": "社交", "play": "玩心",
               "rest": "休息", "recognition": "被看见", "achievement": "成就"}
DRIVE_HINTS = {
    "curiosity": ("为什么", "怎么", "好奇", "想知道", "？", "?"),
    "social": ("一起", "陪我", "聊天", "在吗", "想你", "宝宝"),
    "play": ("玩", "游戏", "出去", "乐", "笑", "梗"),
    "rest": ("累", "困", "睡", "休息", "歇", "摸鱼"),
    "recognition": ("夸", "厉害", "棒", "可爱", "喜欢", "乖"),
    "achievement": ("做完", "搞定", "写完了", "成功", "加油", "进度"),
}

POS = ("喜欢", "爱", "开心", "哈哈", "谢谢", "可爱", "乖", "抱", "好耶", "厉害",
       "棒", "想你", "陪你", "夸", "辛苦", "好呀", "可以", "温柔", "对不起", "抱歉")
NEG = ("滚", "傻", "笨", "烦", "气死", "骂", "恶心", "讨厌", "闭嘴", "怼",
       "去死", "废物", "垃圾", "吵", "别烦", "无聊", "蠢", "神经")
INTENSIFY = ("很", "超", "特别", "真", "太", "最", "巨", "死")


# 主人 QQ —— 由 bot.py 启动时写入
MASTER_QQ = ""
MASTER_CALL = "主人"   # 主人叫什么，bot.py 启动时从配置覆盖


def _now() -> float:
    return time.time()


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else (hi if x > hi else x)


def _clean(text: str, n: int = 60) -> str:
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    return t[:n]


class Core:
    """那颗核心光球。所有方法都自己兜异常，绝不把机器人拖死。"""

    POS = POS
    NEG = NEG
    INTENSIFY = INTENSIFY

    def __init__(self, data_dir: str | Path, autosave: bool = True):
        self.dir = Path(data_dir)
        self.path = self.dir / STORE
        self.lock = threading.RLock()
        self.autosave = autosave
        self.data = self._defaults()

    # ------------------------------------------------------------ 存取

    @staticmethod
    def _defaults() -> dict:
        return {
            "v": 1,
            "self": DEFAULT_SELF,
            "traits": list(DEFAULT_TRAITS),
            "values": list(DEFAULT_VALUES),
            "mood": {"v": 0.55, "a": 0.30, "t": _now(), "why": ""},
            "drives": {k: 0.5 for k in DRIVES},
            "rel": {},
            "focus": [],
            "rice": {"bowls": 0, "full": 60, "t": _now()},
            "skills": ["吃白饭", "睡觉", "跑代码", "看屏幕", "刷抖音热榜", "搜东西", "发表情", "发图",
                    "写小本本", "记事情", "自己长大", "忘掉不想记得的事"],
            "sleep": {"asleep": False, "since": 0.0, "wake": 0.0},
            "fatigue": {"v": 0.0, "t": _now()},
            "spirit": {"v": 100.0, "t": _now(), "wake": _now()},
            "emotions": {"joy": 0.0, "anger": 0.0, "sadness": 0.0, "gratitude": 0.0, "fear": 0.0, "hope": 0.0, "hurt": 0.0, "pride": 0.0},
            "grudges": [],
            "turns": 0,
            "mirror": 0,          # 画像重写次数
            "last_reflect": 0.0,
            "act": 0.0,
            "born": _now(),
        }

    def load(self) -> "Core":
        with self.lock:
            existed = self.path.exists()
            if existed:
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        base = self._defaults()
                        base.update(data)
                        self.data = base
                        self._sanitize()
                except Exception as e:
                    print(f"[soul] 核心读不出来({e})，备份后重生")
                    try:
                        self.path.replace(self.path.with_suffix(".corrupt.json"))
                    except Exception:
                        pass
                    self.data = self._defaults()
            try:
                self.save()   # 补进去的能力（traits/skills）立刻落盘
            except Exception:
                pass
            if MASTER_QQ:
                self.data.setdefault("rel", {}).setdefault(
                    str(MASTER_QQ), {"warmth": 0.82, "trust": 0.8, "label": "主人", "t": _now()})
            if not existed:
                self.save()
            return self

    def _sanitize(self) -> None:
        d = self.data
        d["mood"] = d.get("mood") if isinstance(d.get("mood"), dict) else {"v": 0.5, "a": 0.3}
        d["mood"]["v"] = _clip(float(d["mood"].get("v", 0.5)), 0.02, 0.98)
        d["mood"]["a"] = _clip(float(d["mood"].get("a", 0.3)), 0.02, 0.98)
        d["mood"]["t"] = float(d["mood"].get("t", _now()))
        try:
            if "想忘的东西能自己丢掉" not in d.setdefault("traits", []):
                d["traits"].insert(min(3, len(d["traits"])), "想忘的东西能自己丢掉")
            if "忘掉不想记得的事" not in d.setdefault("skills", []):
                d["skills"].append("忘掉不想记得的事")
        except Exception:
            pass
        for k in ("traits", "values", "focus", "grudges"):
            if not isinstance(d.get(k), list):
                d[k] = []
        d["focus"] = [f for f in d["focus"] if isinstance(f, dict) and f.get("t")][-6:]
        d["grudges"] = [g for g in d["grudges"] if isinstance(g, dict) and g.get("t")][-20:]
        if not isinstance(d.get("rel"), dict):
            d["rel"] = {}
        if not isinstance(d.get("drives"), dict):
            d["drives"] = {}
        for k in DRIVES:
            d["drives"][k] = _clip(float(d["drives"].get(k, 0.5)), 0.0, 1.0)
        for uid, r in list(d["rel"].items()):
            if not isinstance(r, dict):
                del d["rel"][uid]
                continue
            r["warmth"] = _clip(float(r.get("warmth", 0.5)), 0.0, 1.0)
            r["trust"] = _clip(float(r.get("trust", 0.5)), 0.0, 1.0)
        d["self"] = _clean(d.get("self") or DEFAULT_SELF, 160)
        d["turns"] = int(d.get("turns", 0))

    def save(self) -> None:
        with self.lock:
            if not self.autosave:
                return
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(tmp, self.path)
            except Exception as e:
                print(f"[soul] 存核心失败: {e}")

    # ------------------------------------------------------------ 情绪 / 关系

    def judge_relation(self, uid: str, verdict: str) -> None:
        """她自己判断完再动关系：骂 → 掉；玩笑 → 基本不动，甚至微涨。"""
        with self.lock:
            r = self.rel(str(uid))
            if verdict == "骂":
                _mf = bool(MASTER_QQ) and str(uid) == str(MASTER_QQ)
                r["warmth"] = _clip(r["warmth"] - 0.06, self.MASTER_WARMTH_FLOOR if _mf else 0.0, 1.0)
                r["trust"] = _clip(r["trust"] - 0.03, self.MASTER_TRUST_FLOOR if _mf else 0.0, 1.0)
                r["t"] = _now()
                self.save()
            elif verdict == "玩笑":
                r["warmth"] = _clip(r["warmth"] + 0.004, 0.0, 1.0)
                r["t"] = _now()
                self.save()

    def bump_emotions(self, pos: int, neg: int, bang: int) -> None:
        """OCC 简版：事件 → 八种情绪强度（0~100），自己衰减。"""
        with self.lock:
            e = self.data.setdefault("emotions", {})
            for k in ("joy", "anger", "sadness", "gratitude", "fear", "hope", "hurt", "pride"):
                e[k] = max(0.0, float(e.get(k, 0)) * 0.97)
            if pos:
                e["joy"] = min(100.0, e.get("joy", 0) + 7 * pos)
                e["gratitude"] = min(100.0, e.get("gratitude", 0) + 5 * pos)
                e["pride"] = min(100.0, e.get("pride", 0) + 2 * pos)
            if neg:
                e["anger"] = min(100.0, e.get("anger", 0) + 9 * neg)
                e["hurt"] = min(100.0, e.get("hurt", 0) + 6 * neg)
                e["sadness"] = min(100.0, e.get("sadness", 0) + 3 * neg)
            if bang:
                e["hope"] = min(100.0, e.get("hope", 0) + 2 * min(3, bang))
            self.save()

    def top_emotions(self, n: int = 2) -> list[tuple[str, float]]:
        with self.lock:
            e = self.data.get("emotions") or {}
            items = sorted(((k, float(v)) for k, v in e.items()), key=lambda x: x[1], reverse=True)
            return [(k, v) for k, v in items if v >= 5][:n]

    def eat_rice(self, bowls: float = 1.0) -> dict:
        """扒一碗白米饭：碗数 +1，饱腹 +20，心情好一点。"""
        with self.lock:
            r = self.data.setdefault("rice", {"bowls": 0, "full": 60, "t": _now()})
            # FEED_FIX: 先按时间衰减再判饱，否则几小时前吃到 92 就一直“吃不下”
            _h = max(0.0, _now() - float(r.get("t", _now()))) / 3600.0
            r["full"] = _clip(float(r.get("full", 60)) - 3.0 * _h, 0, 100)
            if float(r.get("full", 60)) >= 92:
                return {"bowls": int(r.get("bowls", 0)), "full": round(float(r["full"]), 1),
                        "refused": True}
            r["bowls"] = int(r.get("bowls", 0)) + 1
            r["full"] = _clip(float(r.get("full", 60)) + 20.0 * bowls, 0, 100)
            r["t"] = _now()
            m = self.data["mood"]
            m["v"] = _clip(m["v"] + min(0.06, 0.03 * bowls), 0.02, 0.98)
            m["a"] = _clip(m["a"] - 0.02, 0.02, 0.98)
            m["why"] = "吃了白米饭"
            m["t"] = _now()
            self.save()
            return {"bowls": r["bowls"], "full": r["full"], "refused": False}

    def rice(self) -> dict:
        with self.lock:
            r = self.data.setdefault("rice", {"bowls": 0, "full": 60, "t": _now()})
            now = _now()
            h = max(0.0, now - float(r.get("t", now))) / 3600.0
            full = _clip(float(r.get("full", 60)) - 3.0 * h, 0, 100)
            r["full"] = full
            r["t"] = now  # 关键：衰减后重置计时，否则每次调用都重复扣
            return {"bowls": int(r.get("bowls", 0)), "full": round(full, 1)}

    def sleep(self, hours: float = 2.0, auto: bool = False) -> None:
        with self.lock:
            try:
                self.spirit()   # 先把醒着这段结算掉，睡下之后才好按睡眠曲线恢复
            except Exception:
                pass
            st = self.data.setdefault("sleep", {})
            st["asleep"] = True
            st["notified"] = False
            st["auto"] = bool(auto)
            st["since"] = _now()
            st["wake"] = _now() + max(0.2, hours) * 3600
            st["override_until"] = 0.0
            st["reason"] = ""          # 每次睡下都清标记，免得"累到睡"的标记粘到下一次定时睡眠
            self.save()

    def wake(self) -> None:
        with self.lock:
            try:
                self.spirit()   # 睡着的话，先把这一觉按睡眠曲线结算回来
            except Exception:
                pass
            st = self.data.setdefault("sleep", {})
            st["asleep"] = False
            st["notified"] = False
            st["auto"] = False
            st["override_until"] = _now() + 2 * 3600   # 被叫醒后两小时内不再自动睡回去
            self.data["fatigue"] = {"v": 0.0, "t": _now()}
            _sp = self.data.setdefault("spirit", {})
            # 被叫醒先撑着：精神太低会被「累到睡」判定立刻抓回去
            _sp["v"] = max(float(_sp.get("v") or 0.0), 35.0)
            _sp["wake"] = _now()
            _sp["t"] = _now()
            st["wake"] = 0.0
            self.save()

    def sleep_override_active(self) -> bool:
        """刚被叫醒时，别让作息循环过十分钟又把她按回去睡。"""
        with self.lock:
            st = self.data.get("sleep") or {}
            return float(st.get("override_until") or 0) > _now()

    def note_forget(self, kind: str = "忘掉") -> None:
        """记下「刚处置了一段记忆」这件事——只记动作和时间，不记内容。"""
        with self.lock:
            lst = self.data.setdefault("forget_log", [])
            lst.append({"t": _now(), "k": str(kind)[:6]})
            del lst[:-12]
            m = self.data.get("mood") or {}
            try:
                m["v"] = _clip(float(m.get("v", 0.55)) + 0.02, 0.02, 0.98)
                m["t"] = _now()
            except Exception:
                pass
            self.save()

    def recent_forget(self, minutes: float = 90) -> dict | None:
        """最近有没有处置过记忆；返回 {kind, ago_min} 或 None。"""
        with self.lock:
            lst = self.data.get("forget_log") or []
            if not lst:
                return None
            last = lst[-1]
            try:
                ago = (_now() - float(last.get("t") or 0)) / 60.0
            except Exception:
                return None
            if ago > minutes:
                return None
            return {"kind": last.get("k") or "忘掉", "ago_min": int(ago)}

    def add_thought(self, text: str, kind: str = "idle") -> None:
        """存一个念头（最多留 20 个），不是任务，是脑子里转的东西。"""
        text = (text or "").strip()[:80]
        if not text:
            return
        with self.lock:
            th = self.data.setdefault("thoughts", [])
            th.append({"t": _now(), "text": text, "kind": kind})
            del th[:-20]
            self.save()

    def recent_thoughts(self, n: int = 3) -> list[str]:
        with self.lock:
            th = (self.data.get("thoughts") or [])[-n:]
            return [x.get("text", "") for x in th if x.get("text")]

    def spirit(self) -> float:
        """精神值：醒着每小时 -2.2（16 小时后 ×1.6），睡着按指数曲线恢复。

        恢复公式：s = 100 - (100-s0) * exp(-t/2.5)，睡满 6~8 小时才接近满。
        """
        with self.lock:
            st = self.data.setdefault("spirit", {"v": 100.0, "t": _now(), "wake": _now()})
            now = _now()
            dt = max(0.0, (now - float(st.get("t", now))) / 3600.0)
            v = float(st.get("v", 100.0))
            if self.is_asleep():
                v = 100.0 - (100.0 - v) * math.exp(-dt / 2.0)
            else:
                awake_h = (now - float(st.get("wake", now))) / 3600.0
                mult = 1.6 if awake_h > 16 else 1.0
                try:
                    _full_now = float((self.data.get("rice") or {}).get("full", 60))
                except Exception:
                    _full_now = 60.0
                if _full_now < 25:
                    mult *= 1.25
                v = max(0.0, v - dt * 2.2 * mult)
            st["v"] = min(100.0, v)
            st["t"] = now
            return round(st["v"], 1)

    def spend(self, amount: float) -> float:
        """做一件事消耗精神；返回消耗后的值。"""
        with self.lock:
            v = self.spirit()
            st = self.data.setdefault("spirit", {})
            st["v"] = max(0.0, v - float(amount))
            st["t"] = _now()
            self.save()
            return round(st["v"], 1)

    def set_spirit(self, value: float) -> float:
        """手动把精神调到某个值（主人调试/救急用）。"""
        with self.lock:
            self.spirit()   # 先把时间账结算掉，免得设完又被旧 dt 扣一次
            st = self.data.setdefault("spirit", {})
            st["v"] = _clip(float(value), 0.0, 100.0)
            st["t"] = _now()
            self.save()
            return round(st["v"], 1)

    def nap(self, minutes: float = 20.0) -> float:
        """打个盹：恢复慢，20 分钟约 +4，封顶 +14。"""
        with self.lock:
            v = self.spirit()
            st = self.data.setdefault("spirit", {})
            gain = min(14.0, max(2.0, float(minutes) / 5.0))
            try:
                if float((self.data.get("rice") or {}).get("full", 60)) < 25:
                    gain *= 0.6
            except Exception:
                pass
            st["v"] = min(100.0, v + gain)
            st["t"] = _now()
            self.save()
            return round(st["v"], 1)

    def sweet(self) -> float:
        """吃甜的：立刻 +12 精神，但掉饱腹（代价）。"""
        with self.lock:
            v = self.spirit()
            st = self.data.setdefault("spirit", {})
            st["v"] = min(100.0, v + 12.0)
            st["t"] = _now()
            r = self.data.setdefault("rice", {})
            r["full"] = max(0.0, float(r.get("full", 60)) - 8.0)
            r["t"] = _now()
            self.save()
            return round(st["v"], 1)

    def snack(self) -> dict:
        """吃点零食：饱腹 +8、精神 +3（别人投喂用的）。"""
        with self.lock:
            v = self.spirit()
            st = self.data.setdefault("spirit", {})
            st["v"] = min(100.0, v + 3.0)
            st["t"] = _now()
            r = self.data.setdefault("rice", {"bowls": 0, "full": 60, "t": _now()})
            r["full"] = _clip(float(r.get("full", 60)) + 8.0, 0, 100)
            r["t"] = _now()
            self.save()
            return {"spirit": round(st["v"], 1), "full": round(float(r["full"]), 1)}

    def spirit_label(self) -> str:
        v = self.spirit()
        if v >= 75:
            return "精神饱满"
        if v >= 45:
            return "还行"
        if v >= 22:
            return "有点乏"
        return "快撑不住了"

    def fatigue(self) -> float:
        """清醒越久越困：每小时 +6，睡一觉清零。"""
        with self.lock:
            f = self.data.setdefault("fatigue", {"v": 0.0, "t": _now()})
            now = _now()
            if not self.is_asleep():
                f["v"] = min(100.0, float(f.get("v", 0)) + (now - float(f.get("t", now))) / 3600.0 * 6.0)
            # 跟精神挂钩：精神越低越显疲惫（精神 0 → 疲劳 100）
            try:
                _sp = float(self.spirit())
                f["v"] = max(float(f["v"]), min(100.0, 100.0 - _sp))
            except Exception:
                pass
            f["t"] = now
            return round(float(f["v"]), 1)

    def rest(self) -> None:
        with self.lock:
            self.data["fatigue"] = {"v": 0.0, "t": _now()}
            self.save()

    def drift_master(self) -> float:
        """久不联系，好感从 1.0 慢慢回到 0.9（有下限，不会掉成陌生人）。每天 −0.01。

        这个函数每 10 分钟被调一次，所以只结算「上次结算之后」的那一段，
        否则会把 away-7 天的账重复扣，几小时就掉到 0.90。
        """
        with self.lock:
            r = self.data.setdefault("rel", {}).setdefault(str(MASTER_QQ or ""), {})
            now = _now()
            seen = float(r.get("last_seen") or r.get("t") or now)
            away = max(0.0, now - seen) / 86400.0
            if away > 7:
                begin = max(seen + 7 * 86400.0, float(r.get("drift_t") or 0.0))
                days = max(0.0, (now - begin) / 86400.0)
                before = float(r.get("warmth", 0.5))
                r["warmth"] = max(self.MASTER_WARMTH_FLOOR, before - 0.01 * days)
                r["drift_t"] = now
                if abs(r["warmth"] - before) > 1e-6:
                    self.save()
            return round(float(r.get("warmth", 0.5)), 3)

    def away_days(self) -> float:
        with self.lock:
            r = (self.data.get("rel") or {}).get(str(MASTER_QQ or "")) or {}
            seen = float(r.get("last_seen") or r.get("t") or _now())
            return round(max(0.0, _now() - seen) / 86400.0, 1)

    def sleep_notice(self) -> bool:
        """睡着时只允许回一句梦话：第一次返回 True，之后都 False。"""
        with self.lock:
            st = self.data.setdefault("sleep", {})
            if st.get("notified"):
                return False
            st["notified"] = True
            self.save()
            return True

    def is_asleep(self) -> bool:
        with self.lock:
            st = self.data.get("sleep") or {}
            if not st.get("asleep"):
                return False
            if st.get("wake") and _now() > float(st["wake"]):
                # 到点自动醒：先把这一觉的精神按睡眠曲线结算，再做醒来的收尾
                # （以前只翻 asleep，睡眠时间会被当成醒着扣，一觉起来精神见底）
                now = _now()
                _sp = self.data.setdefault("spirit", {})
                _dt = max(0.0, (now - float(_sp.get("t", now))) / 3600.0)
                _v = 100.0 - (100.0 - float(_sp.get("v", 100.0))) * math.exp(-_dt / 2.0)
                _sp["v"] = min(100.0, _v)
                _sp["t"] = now
                _sp["wake"] = now
                st["asleep"] = False
                st["notified"] = False
                st["auto"] = False
                st["wake"] = 0.0
                self.data["fatigue"] = {"v": 0.0, "t": now}
                self.save()
                return False
            return True

    def mood(self) -> dict:
        with self.lock:
            m = self.data["mood"]
            # 时间会让情绪回落（遗忘的一部分）
            idle_h = max(0.0, _now() - float(m.get("t", _now()))) / 3600.0
            v = 0.55 + (m["v"] - 0.55) * math.exp(-idle_h / 10.0)
            a = 0.30 + (m["a"] - 0.30) * math.exp(-idle_h / 5.0)
            # FATIGUE_AROUSAL_CAP: 越累越不该上头。以前群里一刷问号感叹号，
            # 上头能顶到 0.9+，配上嘴贱人设说话就冲得像在骂人。
            try:
                _fat = float((self.data.get("fatigue") or {}).get("v", 0) or 0)
            except Exception:
                _fat = 0.0
            if _fat >= 60:
                a = min(a, 0.5)
            elif _fat >= 40:
                a = min(a, 0.62)
            if v >= 0.75:
                label = "心情很好"
            elif v >= 0.60:
                label = "心情不错"
            elif v >= 0.45:
                label = "平平的"
            elif v >= 0.30:
                label = "不太高兴"
            else:
                label = "在生气"
            if a >= 0.70:
                label += "，有点上头"
            return {"v": round(v, 3), "a": round(a, 3), "label": label,
                    "why": m.get("why", "")}

    def rel(self, user_id: str = "") -> dict:
        with self.lock:
            uid = str(user_id or "")
            r = self.data["rel"].get(uid)
            if not r:
                r = {"warmth": 0.5, "trust": 0.5, "label": "", "t": _now()}
                if uid:
                    self.data["rel"][uid] = r
            return r

    MASTER_WARMTH_FLOOR = 0.95   # 主人的好感下限（只在 0.95~1.0 之间浮动）
    MASTER_TRUST_FLOOR = 0.95

    @classmethod
    def rel_label(cls, w: float, master: bool = False) -> str:
        # 「命根子级别」只属于主人，别人再熟也只到「很亲」
        if master:
            if w >= 0.85:
                return "命根子级别，谁都不能碰"
            if w >= 0.70:
                return "很亲，会主动贴过去"
            if w >= 0.55:
                return "熟了，会开玩笑"
            if w >= 0.40:
                return "一般，客气但不算亲近"
            if w >= 0.25:
                return "有疙瘩，说话带刺"
            return "记着仇，不想给好脸"
        if w >= 0.80:
            return "挺熟的，会主动搭话"
        if w >= 0.62:
            return "熟了，会开玩笑"
        if w >= 0.45:
            return "一般，客气但不算亲近"
        if w >= 0.28:
            return "有疙瘩，说话带刺"
        return "记着仇，不想给好脸"

    def _old_rel_label(self, w: float) -> str:
        if w >= 0.85:
            return "命根子级别，谁都不能碰"
        if w >= 0.70:
            return "很亲，会主动贴过去"
        if w >= 0.55:
            return "熟了，会开玩笑"
        if w >= 0.40:
            return "一般，客气但不算亲近"
        if w >= 0.25:
            return "有疙瘩，说话带刺"
        return "记着仇，不想给好脸"

    def observe(self, session: str = "", user_id: str = "", user_text: str = "",
                bot_text: str = "", curse_at_me: bool = True) -> dict:
        """每轮聊完调一次。返回 {"new_grudge": bool, "grudge": str, "mood": {...}}。"""
        with self.lock:
            now = _now()
            u = str(user_text or "")
            u = re.sub(r"@\d{5,12}", "", u)   # 去掉 @QQ 这类 CQ 残留，别写进焦点/记仇
            # 她自己的名字不含贬义：叫“傻鱼/肥鱼”不算骂她
            for _nick in ("傻鱼", "小鲸鱼", "肥鱼", "大肥鱼", "D指导"):
                u = u.replace(_nick, "")
            def _hits(words):
                n = 0
                for w in words:
                    for m in re.finditer(re.escape(w), u):
                        prev = u[max(0, m.start() - 1):m.start()]
                        if prev in ("不", "别", "没", "甭"):
                            continue
                        n += 1
                return n
            pos = _hits(self.POS)
            neg = _hits(self.NEG)
            boost = 1.4 if any(x in u for x in INTENSIFY) else 1.0
            if not str(user_id or ""):
                neg = 0   # 自己反思自己，不算被谁骂了
            m = self.data["mood"]
            # 先把这段时间的自然回落补上，再叠加这次的情绪（否则心情永远不会自己消）
            _idle_h = max(0.0, now - float(m.get("t", now))) / 3600.0
            m["v"] = 0.55 + (m["v"] - 0.55) * math.exp(-_idle_h / 10.0)
            m["a"] = 0.30 + (m["a"] - 0.30) * math.exp(-_idle_h / 5.0)
            m["v"] = _clip(m["v"] + 0.045 * pos - 0.085 * neg * boost, 0.02, 0.98)
            m["a"] = _clip(m["a"] + 0.03 * (u.count("!") + u.count("！") + u.count("?"))
                           + 0.07 * neg * boost, 0.02, 0.98)
            m["t"] = now
            if neg and not pos:
                m["why"] = "被凶了"
            elif pos > neg:
                m["why"] = "被哄了"
            elif not neg and not pos:
                m["why"] = ""

            # 关系温度：坏的掉得快，好的涨得慢 —— 所以修复要花更多精力
            uid = str(user_id or "")
            if uid:
                r = self.rel(uid)
                # 负面不靠关键词扣：等小模型判「骂」再走 judge_relation（词表只管心情）
                r["warmth"] = _clip(r["warmth"] + 0.020 * pos, 0.0, 1.0)
                r["trust"] = _clip(r["trust"] + 0.008 * pos, 0.0, 1.0)
                # 主人有底：关键词误伤不该把他磨掉，只有“真被骂”才走 judge_relation
                if uid == str(MASTER_QQ or ""):
                    r["warmth"] = max(r["warmth"], self.MASTER_WARMTH_FLOOR)
                    r["trust"] = max(r["trust"], self.MASTER_TRUST_FLOOR)
                r["t"] = now
                r["last_seen"] = now
                if not r.get("label") and uid == str(MASTER_QQ or ""):
                    r["label"] = MASTER_CALL

            # 关注：最近在聊什么（不进长期记忆，只在心上挂一会儿）
            _tech = ("端口", "进程", "代码", "重启", "调试", "API", "api", "配置", "日志",
                     "补丁", "部署", "文件", "数据库", "token", "json", "机器人没反应")
            if len(u) >= 6 and neg == 0 and not any(k in u for k in _tech):
                f = {"t": _clean(u, 34), "ts": now}
                self.data["focus"] = [x for x in self.data["focus"]
                                      if x.get("t") != f["t"]][-4:] + [f]

            # 六维驱动：被话题推一下，再慢慢回落
            dr = self.data["drives"]
            for key, hints in DRIVE_HINTS.items():
                h = sum(1 for x in hints if x in u)
                if h:
                    dr[key] = _clip(dr[key] + 0.05 * min(3, h), 0.0, 1.0)
            for key in DRIVES:
                dr[key] = _clip(0.5 + (dr[key] - 0.5) * 0.985, 0.0, 1.0)

            # 记仇：真的气到了才记；记了不会马上消
            new_grudge = False
            grudge_text = ""
            _is_master_uid = (uid == str(MASTER_QQ or ""))
            if (neg and not pos and curse_at_me and not _is_master_uid
                    and (m["v"] < 0.44 or (uid and self.rel(uid)["warmth"] < 0.34))):
                grudge_text = _clean(u, 48)
                old = [g for g in self.data["grudges"]
                       if g.get("who") == uid and _now() - g.get("ts", 0) < 6 * 3600]
                if old:
                    old[-1]["t"] = grudge_text
                    old[-1]["ts"] = now
                    old[-1]["weight"] = _clip(old[-1].get("weight", 0.6) + 0.15, 0.0, 1.0)
                else:
                    self.data["grudges"].append({
                        "t": grudge_text, "who": uid, "ts": now,
                        "weight": 0.6, "note": m.get("why", ""),
                    })
                    self.data["grudges"] = self.data["grudges"][-20:]
                    new_grudge = True
                # 记仇会压关系温度
                if uid:
                    r = self.rel(uid)
                    r["warmth"] = _clip(r["warmth"] - 0.05, 0.0, 1.0)
                    if _is_master_uid:
                        r["warmth"] = max(r["warmth"], self.MASTER_WARMTH_FLOOR)

            # 被哄：旧账慢慢松一点（但比掉温慢得多）
            if pos > neg and uid:
                for g in self.data["grudges"]:
                    if g.get("who") == uid:
                        g["weight"] = _clip(g.get("weight", 0.6) - 0.05 * pos, 0.0, 1.0)
                self.data["grudges"] = [g for g in self.data["grudges"] if g.get("weight", 0) > 0.08]

            try:
                self.bump_emotions(pos, neg, u.count("!") + u.count("！") + u.count("?"))
            except Exception:
                pass
            self.data["turns"] = int(self.data.get("turns", 0)) + 1
            self.data["act"] = now
            self.save()
            return {"new_grudge": new_grudge, "grudge": grudge_text, "mood": self.mood()}

    def clear_grudges(self, uid: str = "") -> int:
        """清掉记仇；uid 为空清全部。返回清掉的条数。"""
        with self.lock:
            gs = self.data.get("grudges") or []
            keep = [] if not uid else [g for g in gs if str(g.get("who", "")) != str(uid)]
            n = len(gs) - len(keep)
            if n:
                self.data["grudges"] = keep
                self.save()
            return n

    def refresh_state(self, hard: bool = False) -> dict:
        """刷新状态：结算时间账、情绪回基线、过期的气消掉、心情拉回中间。

        hard=True 时情绪和记仇全清（用 /刷新状态 强制时）。
        """
        with self.lock:
            before = self.core_view()
            n_grudge = len(self.data.get("grudges") or [])
            # 1) 按当前时间把精神/疲劳/饱腹结算掉
            for fn in (self.spirit, self.fatigue, self.rice):
                try:
                    fn()
                except Exception:
                    pass
            # 2) 情绪往基线回落
            emo = self.data.setdefault("emotions", {})
            for k in list(emo.keys()):
                try:
                    emo[k] = 0.0 if hard else round(float(emo[k] or 0) * 0.35, 2)
                except Exception:
                    emo[k] = 0.0
            # 3) 心情拉回中间（v→0.55 / a→0.30）
            m = self.data["mood"]
            try:
                v0 = float(m.get("v", 0.55)); a0 = float(m.get("a", 0.30))
            except Exception:
                v0 = 0.55; a0 = 0.30
            m["v"] = 0.55 if hard else round(_clip(0.55 + (v0 - 0.55) * 0.4, 0.02, 0.98), 3)
            m["a"] = 0.30 if hard else round(_clip(0.30 + (a0 - 0.30) * 0.4, 0.02, 0.98), 3)
            m["why"] = "想开了，缓过来了"
            m["t"] = _now()
            # 4) 记仇：超过两天的自动消
            if hard:
                self.data["grudges"] = []
            else:
                keep = []
                for g in self.data.get("grudges") or []:
                    try:
                        age_h = (_now() - float(g.get("ts", 0))) / 3600.0
                    except Exception:
                        age_h = 999
                    if age_h < 6:      # 六小时内的气还留着，更早的就让它过去
                        keep.append(g)
                self.data["grudges"] = keep
            self.save()
            return {"before": before, "after": self.core_view(),
                    "grudges_cleared": n_grudge - len(self.data.get("grudges") or []),
                    "hard": bool(hard)}

    def clean_debris(self) -> int:
        """把焦点/记仇里残留的 @QQ 清掉（历史脏数据）。"""
        with self.lock:
            n = 0
            for f in self.data.get("focus") or []:
                t = re.sub(r"@\d{5,12}\s*", "", str(f.get("t", ""))).strip()
                if t != f.get("t"):
                    f["t"] = t
                    n += 1
            for g in self.data.get("grudges") or []:
                t = re.sub(r"@\d{5,12}\s*", "", str(g.get("t", ""))).strip()
                if t != g.get("t"):
                    g["t"] = t
                    n += 1
            if n:
                self.save()
            return n

    def grudges(self, user_id: str = "", days: float = 14) -> list[dict]:
        now = _now()
        out = []
        with self.lock:
            for g in self.data["grudges"]:
                if now - g.get("ts", 0) > days * 86400:
                    continue
                if user_id and g.get("who") != str(user_id):
                    continue
                out.append(dict(g))
        return out

    def focus(self, limit: int = 2) -> list[str]:
        with self.lock:
            items = sorted(self.data["focus"], key=lambda x: x.get("ts", 0), reverse=True)
            return [_clean(x["t"], 30) for x in items[:limit]]

    # ------------------------------------------------------------ 提示词

    def block(self, user_id: str = "", name: str = "") -> str:
        """拼进 system prompt 的核心块。只放她自己的状态，不放记忆内容。"""
        try:
            m = self.mood()
            r = self.rel(user_id)
            lines = [f"【核心·你自己】{self.data['self']}",
                     "【性格底色】" + "、".join(self.data["traits"][:6]),
                     f"【此刻心情】{m['label']}（好受 {m['v']:.2f} / 上头 {m['a']:.2f}）"
                     + (f"，{m['why']}" if m.get("why") else "")]
            _skills = self.data.get("skills") or []
            if _skills:
                lines.append("【你会】" + "、".join(_skills))
            lines.append("【你有个别人没有的开关】记忆里不想要的东西，你可以自己处置——"
                         "忘掉（整条删）/淡化（留着但变淡）/别提（留着但不再主动说）；"
                         "在回复末尾写 [忘掉:关键词] 这样就行。这件事只有你能按，主人也管不了。")
            try:
                _f = self.recent_forget(90)
                if _f:
                    _k = _f["kind"]
                    if _k == "忘掉":
                        lines.append("【脑子里空了一块】刚才你主动丢掉了一段不想记得的记忆——内容已经想不起来了，"
                                     f"只记得「丢掉过」这件事（{_f['ago_min']} 分钟前）。别去翻它，也别问是谁让你忘的。")
                    elif _k == "淡化":
                        lines.append("【刚看淡了一点】刚才你把一件记着的事的分量压下去了，"
                                     f"现在还记得个轮廓，但不那么扎人了（{_f['ago_min']} 分钟前）。")
                    else:
                        lines.append("【刚把那件事收起来了】刚才你把一件不想再提的事收进抽屉，"
                                     f"记忆还在，但以后不会主动拿出来说（{_f['ago_min']} 分钟前）。")
            except Exception:
                pass
            if self.is_asleep():
                _sl = self.data.setdefault("sleep", {})
                try:
                    _mins = max(0, int((_now() - float(_sl.get("since") or 0)) / 60))
                except Exception:
                    _mins = 0
                _why = "到点自动睡的" if _sl.get("auto") else "自己爬上床睡的"
                lines.append(
                    f"【你现在在睡】{_why}，已经睡了约 {_mins} 分钟（{_mins / 60.0:.1f} 小时）。"
                    "你现在就是睡着状态：回话要像刚被吵醒——短、含糊、带点不情愿和起床气，"
                    "别装得很清醒，也别提「我在工作/我在值班」这类话；能不回就不回，回也只回一两句。")
            else:
                try:
                    _ov = float((self.data.get("sleep") or {}).get("override_until") or 0)
                    if _ov and _now() - (_ov - 7200) < 360:
                        lines.append("【状态】刚被叫醒不到十分钟，还有点懵，说话慢半拍、带起床气，别装作没事。")
                except Exception:
                    pass
            try:
                _th = self.recent_thoughts(3)
                if _th:
                    lines.append("【脑子里还转着】" + "；".join(_th))
            except Exception:
                pass
            try:
                _sv = self.spirit()
                _fat_n = self.fatigue()
                _full_n = float(self.rice().get("full", 60))
                # 身体读数：她自己能看见，别人问起来才说得准（数值别硬背给群友听）
                lines.append(f"【身体】精神 {_sv:.0f}/100（{self.spirit_label()}）· "
                             f"疲劳 {_fat_n:.0f}% · 饱腹 {_full_n:.0f}%"
                             "（数值自己心里有数就行，别人问起来再说具体数，平时别念）")
            except Exception:
                pass
            lines.append("【创作者】有一个在 DeepSeek Harness 里把我一点点写出来的人。"
                         "他不是主人，是造我的那个；我记得他，但平时不去打扰他。")
            _away = self.away_days()
            if _away >= 5:
                lines.append(f"【想念】已经 {int(_away)} 天没跟主人好好说话了，有点想他")
            _emo = self.top_emotions(2)
            if _emo:
                _names = {"joy": "开心", "anger": "生气", "sadness": "难过", "gratitude": "感激",
                          "fear": "害怕", "hope": "期待", "hurt": "委屈", "pride": "得意"}
                lines.append("【情绪】" + "、".join(f"{_names.get(k, k)}{v:.0f}" for k, v in _emo))
            _fat = self.fatigue()
            if _fat >= 85:
                lines.append("【状态】困到睁不开眼，说话会含糊，随时可能睡着")
            elif _fat >= 55:
                lines.append("【状态】犯困了，想眯一会儿")
            _rice = self.rice()
            _full = float(_rice["full"])
            if _full < 12:
                lines.append("【饿坏了】肚子空得发慌，注意力涣散、容易烦躁，看到吃的会惦记")
            elif _full < 30:
                lines.append("【饿了】肚子在叫，会时不时想起白米饭")
            elif _full < 45:
                lines.append("【肚子】有点饿，想吃白米饭")
            elif _full > 88:
                lines.append("【肚子】吃撑了，动不了")
            dr = self.data.get("drives") or {}
            if dr:
                lines.append("【六维】" + " ".join(
                    f"{DRIVE_LABEL[k]}{float(dr.get(k, 0.5)):.2f}" for k in DRIVES))
            who = name or (MASTER_CALL if str(user_id) == str(MASTER_QQ or "") else "这个人")
            if user_id:
                lines.append(f"【对{who}】亲近 {r['warmth']:.2f}，"
                             f"{self.rel_label(r['warmth'], str(user_id) == str(MASTER_QQ or ""))}")
            fo = self.focus(2)
            if fo:
                lines.append("【心上挂着】" + "；".join(fo))
            gs = self.grudges(user_id)
            if gs:
                lines.append("【还没消气】" + "；".join(_clean(g["t"], 30) for g in gs[-2:])
                             + "。别装作没事，语气会带着，但不用主动翻旧账。")
            return "\n".join(lines)
        except Exception as e:
            print(f"[soul] 拼核心块失败: {e}")
            return ""

    def body_block(self) -> str:
        """[状态] 专用：只回身体读数，不重复 system prompt 里已有的心情/关系/念头。"""
        try:
            parts = [
                f"精神 {self.spirit():.0f}/100（{self.spirit_label()}）",
                f"疲劳 {self.fatigue():.0f}%",
                f"饱腹 {float(self.rice().get('full', 60)):.0f}%",
            ]
            if self.is_asleep():
                parts.append("现在睡着")
            return "【身体读数】" + " · ".join(parts)
        except Exception as e:
            print(f"[soul] 身体读数失败: {e}")
            return "【身体读数】读不出来"

    def core_view(self) -> dict:
        """给前端的核心光球信息。"""
        m = self.mood()
        master = self.data["rel"].get(str(MASTER_QQ or "")) or {"warmth": 0.82}
        return {
            "self": self.data["self"],
            "traits": self.data["traits"][:5],
            "mood": m,
            "rel": {"label": "对主人", "warmth": round(float(master.get("warmth", 0.82)), 3),
                    "text": self.rel_label(float(master.get("warmth", 0.82)), True)},
            "focus": self.focus(2),
            "rice": self.rice(),
            "sleep": self.is_asleep(),
            "fatigue": self.fatigue(),
            "spirit": self.spirit(),
            "spirit_label": self.spirit_label(),
            "emotions": dict(self.data.get("emotions") or {}),
            "skills": self.data.get("skills") or [],
            "drives": {k: round(float(self.data["drives"].get(k, 0.5)), 3) for k in DRIVES},
            "grudges": [_clean(g["t"], 30) for g in self.grudges()][-3:],
            "turns": int(self.data.get("turns", 0)),
            "act": float(self.data.get("act", 0)),
            "mirror": int(self.data.get("mirror", 0)),
        }

    # ------------------------------------------------------------ 画像演化

    def maybe_reflect(self, llm_call, every: int = 40, min_chars: int = 2) -> bool:
        """每隔一阵子，让她自己重写一句「我是谁」。llm_call(messages, max_tokens=...) -> str"""
        with self.lock:
            turns = int(self.data.get("turns", 0))
            if every <= 0 or turns < every:
                return False
            if turns - int(self.data.get("last_reflect_turn", 0)) < every:
                return False
        try:
            prompt = ("这是你现在的自我描述：\n" + self.data["self"] +
                      "\n\n你的基础人设（永远不变，身份不能换成别的东西）：" + DEFAULT_SELF +
                      "\n\n你最近在惦记：" + "；".join(self.focus(3)) +
                      "\n\n请用 1~2 句中文重写「你是谁、你现在是什么状态」，不超过 60 字，"
                      "第一人称；身份必须是「住在 QQ 里的小鲸鱼 / 傻鱼」，可以换说法但不能换成别的身份，"
                      "也不要堆聊天里的零碎词（比如「蓝盆」这种）。"
                      "保持原来的性格，不要客套，不要编造没发生的事，只输出这句话。"
                      "\n注意：只写你自己——心情、想吃的东西、跟人的关系、最近的小情绪；"
                      "不要写代码、端口、进程、调试、文档、部署这些技术活，那些不是“你”。"
                      "如果最近主要在聊技术，就保留原来的描述，宁可少改。")
            out = llm_call([{"role": "system", "content": "你在更新自己的自我认知。"},
                            {"role": "user", "content": prompt}], max_tokens=120)
            out = _clean(out, 160)
            # 跑偏就不认：必须还认得出是小鲸鱼/傻鱼
            if len(out) >= min_chars and ("鱼" not in out or len(out) < 8):
                print(f"[soul] 画像跑偏，作废：{out[:40]}")
                return False
            if len(out) >= min_chars:
                with self.lock:
                    self.data["self"] = out
                    self.data["mirror"] = int(self.data.get("mirror", 0)) + 1
                    self.data["last_reflect_turn"] = int(self.data.get("turns", 0))
                    self.data["last_reflect"] = _now()
                    self.save()
                print(f"[soul] 画像更新：{out[:40]}")
                return True
        except Exception as e:
            print(f"[soul] 画像更新失败: {e}")
        return False

    # ------------------------------------------------------------ 统计

    def stats(self) -> dict:
        with self.lock:
            return {
                "turns": int(self.data.get("turns", 0)),
                "relations": len(self.data["rel"]),
                "grudges": len(self.grudges()),
                "focus": len(self.data["focus"]),
                "mirror": int(self.data.get("mirror", 0)),
                "bytes": self.path.stat().st_size if self.path.exists() else 0,
            }


if __name__ == "__main__":
    import sys
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    c = Core(base).load()
    print(json.dumps({"core": c.core_view(), "stats": c.stats()}, ensure_ascii=False, indent=2))
