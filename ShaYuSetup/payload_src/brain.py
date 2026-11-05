# -*- coding: utf-8 -*-
"""brain.py —— 傻鱼的「脑子」

不是一堆字符串，而是一张会长大的记忆网络：

  · 节点（神经元）：人物 / 事实 / 事件 / 情绪 / 约定 / 技能 / 视觉 / 工作记忆
  · 连线（突触）：同一轮聊到、同一话题、被一起想起 —— 都会被加粗
  · 激活：每次被召回，节点亮一下（前端「大脑」页面上能看到闪烁）
  · 巩固：定期合并重复、衰减不用的、剪掉孤立的、给旧账降权
  · 情绪：每个会话有自己的心情值，会被对话内容轻轻推动，然后慢慢回落

存储：brain_memory.json（原子写，纯标准库）。
对外接口刻意保持和 bot.py 里原来的 memory 函数同名同参，方便无痛替换。

单独跑：
    python brain.py            # 打印统计
    python brain.py graph      # 输出前端用的 JSON
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import re
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------- 常量

STORE_NAME = "brain_memory.json"
LEGACY_NAME = "memory.json"
SESSION_NAME = "session_memory.json"

MAX_NODES = 900
MAX_EDGES = 4200
MAX_TEXT = 160
DEDUP_SIM = 0.92          # 同一类里相似到这个程度就当同一条
CROSS_DEDUP_SIM = 0.96    # 跨会话要求更高：几乎完全相同才合并，防止不同语境被误并
CONSOLIDATE_EVERY = 40    # 每新增这么多条跑一次巩固
WORK_TTL = 3 * 86400      # 工作记忆最多活 3 天
DECAY_HALF_LIFE_DAYS = 200  # 长期记忆：200 天不用，重要度减半；两个半衰期后才会清
MAX_WORK = 80

KINDS = {
    "meme":      {"label": "梗", "color": "#2ee6c8", "imp": 0.42},
    "quote":     {"label": "金句", "color": "#ff7be5", "imp": 0.65},
    "empathy":   {"label": "别人的情绪", "color": "#ff9de2", "imp": 0.55},
    "person":    {"label": "人物", "color": "#ff5fa2", "imp": 0.82},
    "object":    {"label": "实物", "color": "#b6ff5c", "imp": 0.52},
    "skill":     {"label": "技能", "color": "#5f8dff", "imp": 0.58},
    "fact":      {"label": "事实", "color": "#43ddff", "imp": 0.60},
    "event":     {"label": "事件", "color": "#4fe08a", "imp": 0.50},
    "agreement": {"label": "约定", "color": "#ffd45e", "imp": 0.80},
    "feeling":   {"label": "情绪", "color": "#c084ff", "imp": 0.55},
    "visual":    {"label": "视觉", "color": "#ff8f5e", "imp": 0.45},
    "work":      {"label": "短期", "color": "#93a7c4", "imp": 0.22},
}
KIND_ORDER = list(KINDS)

PREFIX_KIND = {
    "称呼": "person", "身份": "person", "关系": "person", "昵称": "person", "人": "person",
    "喜好": "fact", "喜欢": "fact", "讨厌": "fact", "爱吃": "fact", "习惯": "fact",
    "正在做": "work", "在做": "work", "最近": "work", "话题": "work",
    "约定": "agreement", "答应": "agreement", "计划": "agreement",
    "技能": "skill", "会": "skill", "擅长": "skill", "工具": "skill",
    "实物": "object", "东西": "object", "物品": "object", "物件": "object",
    "情绪": "feeling", "心情": "feeling", "感觉": "feeling",
    "事件": "event", "发生": "event", "经过": "event",
    "图片": "visual", "表情": "visual", "长相": "visual", "外观": "visual",
    "其他": "fact", "事实": "fact",
    "印象": "person", "关系": "person", "近况": "event",
    "口头禅": "fact", "习惯": "fact", "态度": "feeling",
    "别人情绪": "empathy", "他人情绪": "empathy", "共情": "empathy",
}

# 人物节点的“名字”校验：叫“群友都叫我傻鱼”的句子不该进人物栏
_NAME_MARKERS = ("我", "你", "他", "她", "叫", "说", "是", "被", "喊", "群友", "对方",
                 "昵称", "非要", "都", "也", "会", "给", "让", "把", "吗", "呢", "啊",
                 "觉得", "认为", "知道", "喜欢", "讨厌", "最近", "今天", "昨天",
                 "调侃", "语气", "熟", "直接", "答应")


def _is_master_subj(node) -> bool:
    """这个记忆的主语是不是主人。称呼从配置读，不写死。"""
    try:
        import bot as _b
        names = [x for x in (getattr(_b, "MASTER_NAME", ""), getattr(_b, "MASTER_CALL", "")) if x]
    except Exception:
        names = []
    if not names:
        names = ["主人"]
    subj = str((node or {}).get("subj") or "")
    return any(n in subj for n in names)


def _looks_like_person(s: str) -> bool:
    t = str(s or "").strip().strip("「」\"'“”")
    if not t:
        return False
    if any(w in t for w in _NAME_MARKERS):
        return False
    if len(t) > 22 and not re.search(r"\d{5,12}", t):
        return False
    if t.endswith(("、", "的", "了", "吗", "呢", "啊", "，", "。")):
        return False
    return True

# 自动工作记忆的噪音过滤：脏话、纯玩梗、无信息增量的碎片不进长期记忆
_NOISE_WORDS = ("滚", "傻逼", "煞笔", "你妈", "他妈", "tmd", "rnm", "我日", "去死",
                "废物", "垃圾", "闭嘴", "泔水", "眼淌", "艹", "焯", "卧槽", "妈的",
                "靠北", "吃席", "同床", "大副", "呜呜", "我嘞个", "栓Q", "尊嘟")


def _is_noise(s: str) -> bool:
    t = str(s or "").strip()
    if any(w in t for w in _NOISE_WORDS):
        return True
    # 去掉标点和语气词后有效内容太少，说明是感叹/打招呼/碎片
    core = re.sub(r"[\s，。、！？：；,.!?:;\"“”‘’（）()【】\[\]啊哦嗯诶呀哈嘿呜呢吗吧嘛~～]", "", t)
    return len(core) < 8

# 3D 里每个「中枢」的落脚点（单位球内），前端按这个分簇

ANCHORS = {
    "person":    (-0.52, 0.16, 0.10),
    "fact":      (-0.10, 0.56, -0.16),
    "event":     (0.46, 0.04, 0.10),
    "feeling":   (-0.04, -0.42, 0.28),
    "agreement": (-0.48, 0.58, 0.22),
    "skill":     (-0.44, -0.34, -0.24),
    "visual":    (-0.66, -0.12, -0.16),
    "work":      (0.04, 0.02, 0.52),
    "meme":      (0.66, 0.10, 0.26),
    "quote":     (-0.62, 0.30, 0.38),
    "empathy":   (0.10, -0.55, 0.62),
    "object":    (-0.28, 0.62, 0.34),
}

# ---- 星系群：拆成九个小星系，围成一圈，中间留核心 ----
GALAXIES = [
    {"name": "人物", "center": (3.30, -0.27, 0.00), "size": 1.00, "tilt": (0.55, 0.15),
     "color": [255, 120, 200]},
    {"name": "事实", "center": (2.53, 0.46, 2.12), "size": 1.10, "tilt": (-0.35, 0.55),
     "color": [110, 205, 255]},
    {"name": "工作", "center": (0.50, -0.18, 3.26), "size": 0.85, "tilt": (0.20, -0.40),
     "color": [140, 220, 160]},
    {"name": "梗·金句", "center": (-1.89, 0.64, 2.70), "size": 1.00, "tilt": (0.70, -0.50),
     "color": [110, 255, 200]},
    {"name": "经历", "center": (-3.26, -0.09, 0.50), "size": 0.72, "tilt": (-0.50, 0.70),
     "color": [110, 200, 255]},
    {"name": "情绪", "center": (-1.89, 0.82, -2.70), "size": 0.68, "tilt": (-0.40, 0.30),
     "color": [190, 150, 255]},
    {"name": "视觉", "center": (0.50, 0.37, -3.26), "size": 0.70, "tilt": (-0.60, -0.30),
     "color": [150, 160, 255]},
    {"name": "技能·实物", "center": (2.53, 0.92, -2.12), "size": 0.60, "tilt": (0.30, 0.60),
     "color": [255, 190, 120]},
    {"name": "约定", "center": (-3.26, 0.92, -0.50), "size": 0.60, "tilt": (0.30, 0.60),
     "color": [255, 210, 120]},
]
GALAXY_FOR = {
    "person": 0, "fact": 1,
    "work": 2,
    "meme": 3, "quote": 3,
    "event": 4,
    "feeling": 5, "empathy": 5,
    "visual": 6,
    "skill": 7, "object": 7,
    "agreement": 8,
}


def _galaxy_orbit(nid: str, layer: str, gi: int) -> tuple[float, float, float]:
    h = hashlib.sha1(nid.encode("utf-8")).digest()
    rnd = random.Random(int.from_bytes(h[:8], "big"))
    size = GALAXIES[gi % len(GALAXIES)]["size"]
    lo, hi = {"inner": (0.22, 0.45), "mid": (0.48, 0.75), "outer": (0.78, 1.05)}.get(
        layer, (0.48, 0.75))
    r = (lo + (hi - lo) * rnd.random()) * size
    a0 = rnd.uniform(0.0, 6.2832)
    inc = rnd.uniform(-0.18, 0.18)
    return (r, a0, inc)


def _galaxy_pos(gi: int, r: float, a0: float, inc: float) -> tuple[float, float, float]:
    g = GALAXIES[gi % len(GALAXIES)]
    lx = r * math.cos(a0)
    lz = r * math.sin(a0)
    ly = lz * math.sin(inc)
    lz2 = lz * math.cos(inc)
    ca, sa = math.cos(g["tilt"][0]), math.sin(g["tilt"][0])
    y1 = ly * ca - lz2 * sa
    z1 = ly * sa + lz2 * ca
    cb, sb = math.cos(g["tilt"][1]), math.sin(g["tilt"][1])
    x1 = lx * cb + z1 * sb
    z2 = -lx * sb + z1 * cb
    return (g["center"][0] + x1, g["center"][1] + y1, g["center"][2] + z2)

_NORM_RE = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")
_SPLIT_RE = re.compile(r"^([^：:]{1,6})[：:]\s*(.+)$", re.S)
_STOP = set("的了着过吗呢吧啊呀哦嗯是我你他她它在有和就都也很被把给对说个这那")


# ===== 艾宾浩斯遗忘曲线参数 =====
STAB_BASE = 1.5          # 新记忆的基础稳定期（天）
STAB_IMP_K = 6.0         # 越重要，稳定期越长（imp=1 时 +6 天）
STAB_GAIN = 1.6          # 每次被想起，稳定期 ×1.6（间隔重复效应）
STAB_CAP = 3650.0        # 稳定期上限（天，十年）
STAB_FLOOR = 1.2         # 稳定期下限（天）
CORE_STAB = 400.0        # 核心记忆（约定/人物/重要度≥0.8）的稳定期地板（天）
CORE_IMP = 0.8           # 重要度到这个数就算核心
CORE_KINDS = ("agreement", "person")


def _now() -> float:
    return time.time()


def _norm(text: str) -> str:
    return _NORM_RE.sub("", str(text).lower())


def _bigrams(text: str) -> set[str]:
    s = _norm(text)
    if len(s) < 2:
        return {s} if s else set()
    out = set()
    for i in range(len(s) - 1):
        a, b = s[i], s[i + 1]
        if a in _STOP and b in _STOP:
            continue
        out.add(a + b)
    return out


def _sim(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return 2.0 * inter / (len(a) + len(b))


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else (hi if x > hi else x)


class Brain:
    """一张会自己整理自己的记忆网。"""

    def __init__(self, data_dir: str | Path, autosave: bool = True):
        self.dir = Path(data_dir)
        self.path = self.dir / STORE_NAME
        self.lock = threading.RLock()
        self.autosave = autosave
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str], dict] = {}
        self.affect: dict[str, dict] = {}
        self.meta: dict = {"v": 2, "adds": 0, "created": _now(),
                           "last_consolidate": 0.0, "migrated": False}
        self._recent: dict[str, list[list]] = {}
        self._bg: dict[str, set[str]] = {}
        self._last_save = 0.0
        self._dirty = False
        self._quiet = False
        self._qcache: dict = {}
        self.cur_mood = (0.5, 0.5)

    # ------------------------------------------------------------ 存取

    def load(self) -> "Brain":
        with self.lock:
            fresh = True
            if self.path.exists():
                try:
                    data = json.loads(self.path.read_text(encoding="utf-8"))
                    self._load_dict(data)
                    try:
                        self._migrate_stab()      # 老数据补稳定期
                    except Exception:
                        pass
                    fresh = False
                except Exception as e:
                    print(f"[brain] 读脑子失败({e})，从空白开始")
                    bad = self.path.with_suffix(".corrupt.json")
                    try:
                        self.path.replace(bad)
                    except Exception:
                        pass
            if fresh:
                self._bootstrap()
            if self.autosave:
                self.consolidate()
            return self

    def _migrate_stab(self) -> None:
        """老数据没有 stab：按「已经活了多久 + 重要度」给个初始稳定期，避免一升级全忘光。"""
        now = _now()
        n_changed = 0
        for n in self.nodes.values():
            if n.get("stab"):
                continue
            try:
                age_d = max(0.0, (now - float(n.get("t0") or now)) / 86400.0)
                imp = float(n.get("imp") or 0.3)
            except Exception:
                age_d, imp = 0.0, 0.3
            _st = STAB_BASE + STAB_IMP_K * _clip(imp, 0.05, 1.0) + age_d * 0.5
            if (str(n.get("k") or "") in CORE_KINDS or imp >= CORE_IMP
                    or _is_master_subj(n)):
                _st = max(_st, CORE_STAB)
            n["stab"] = round(_clip(_st, STAB_FLOOR, STAB_CAP), 3)
            n_changed += 1
        if n_changed:
            self._dirty = True

    def _load_dict(self, data: dict) -> None:
        self.meta.update(data.get("meta") or {})
        self.meta.setdefault("v", 2)
        nodes = {}
        for n in data.get("nodes") or []:
            if not isinstance(n, dict) or not n.get("id") or not n.get("t"):
                continue
            n.setdefault("k", "fact")
            if n["k"] not in KINDS:
                n["k"] = "fact"
            n.setdefault("s", "")
            n.setdefault("subj", "")
            n.setdefault("tags", [])
            n["imp"] = _clip(float(n.get("imp", 0.5)), 0.02, 1.0)
            n["hits"] = int(n.get("hits", 0))
            n["t0"] = float(n.get("t0", _now()))
            n["t1"] = float(n.get("t1", n["t0"]))
            n["la"] = float(n.get("la", n["t1"]))
            n["act"] = float(n.get("act", 0.0))
            n.setdefault("src", "auto")
            nodes[n["id"]] = n
        self.nodes = nodes
        edges = {}
        for e in data.get("edges") or []:
            if not isinstance(e, (list, tuple)) or len(e) < 2:
                continue
            a, b = str(e[0]), str(e[1])
            if a == b or a not in nodes or b not in nodes:
                continue
            key = (a, b) if a < b else (b, a)
            w = _clip(float(e[2] if len(e) > 2 else 0.3), 0.01, 1.0)
            t = float(e[3] if len(e) > 3 else _now())
            if key in edges:
                edges[key]["w"] = _clip(edges[key]["w"] + w * 0.5, 0.01, 1.0)
            else:
                edges[key] = {"w": w, "t": t}
        self.edges = edges
        aff = {}
        for k, v in (data.get("affect") or {}).items():
            if isinstance(v, dict):
                aff[str(k)] = {"v": _clip(float(v.get("v", 0.5)), 0.02, 0.98),
                               "a": _clip(float(v.get("a", 0.3)), 0.02, 0.98),
                               "t": float(v.get("t", _now())),
                               "why": str(v.get("why", ""))[:40]}
        self.affect = aff

    def _save_dict(self) -> dict:
        edges = [[a, b, round(e["w"], 4), int(e["t"])] for (a, b), e in self.edges.items()]
        return {
            "meta": dict(self.meta, saved=_now(), nodes=len(self.nodes), edges=len(edges)),
            "nodes": list(self.nodes.values()),
            "edges": edges,
            "affect": self.affect,
        }

    def save(self, force: bool = False) -> None:
        with self.lock:
            if self._quiet:
                return
            now = _now()
            if not force and not self._dirty:
                return
            if not force and now - self._last_save < 1.5:
                return
            try:
                self.dir.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self._save_dict(), ensure_ascii=False, separators=(",", ":")),
                               encoding="utf-8")
                os.replace(tmp, self.path)
                self._last_save = now
                self._dirty = False
            except Exception as e:
                print(f"[brain] 存脑子失败: {e}")

    # ------------------------------------------------------------ 节点基础

    def _bigrams_of(self, node: dict) -> set[str]:
        bg = self._bg.get(node["id"])
        if bg is None:
            bg = _bigrams(node["t"] + node.get("subj", ""))
            self._bg[node["id"]] = bg
        return bg

    def stab_of(self, node: dict) -> float:
        """这个记忆的稳定期（天）：越重要越久，被想起来过就更久。"""
        try:
            st = float(node.get("stab") or 0.0)
        except Exception:
            st = 0.0
        if st <= 0:
            imp = float(node.get("imp") or 0.3)
            st = STAB_BASE + STAB_IMP_K * _clip(imp, 0.05, 1.0)
        # 核心记忆（约定 / 人物 / 很重要的事）不能按普通记忆那么快忘
        if self._is_core(node):
            st = max(st, CORE_STAB)
            node["stab"] = round(_clip(st, STAB_FLOOR, STAB_CAP), 3)
        elif not node.get("stab"):
            node["stab"] = round(_clip(st, STAB_FLOOR, STAB_CAP), 3)
        return _clip(st, STAB_FLOOR, STAB_CAP)

    @staticmethod
    def _is_core(node: dict) -> bool:
        """约定、人物卡、或者很重要的事 —— 这些是长期记忆，别按普通记忆衰减。"""
        try:
            if str(node.get("k") or "") in CORE_KINDS:
                return True
            if float(node.get("imp") or 0) >= CORE_IMP:
                return True
            if _is_master_subj(node):
                return True
        except Exception:
            pass
        return False

    def retention(self, node: dict, now: float | None = None) -> float:
        """艾宾浩斯保持率 R = exp(-t/S)。1=刚想起，0=快忘了。"""
        now = _now() if now is None else now
        try:
            la = float(node.get("la") or node.get("t1") or now)
            stab = max(0.3, self.stab_of(node))
        except Exception:
            return 1.0
        return math.exp(-max(0.0, now - la) / 86400.0 / stab)

    def _reinforce(self, node: dict) -> None:
        """被想起来一次就复习一次：越接近遗忘，复习越有效（间隔效应）。"""
        now = _now()
        st = self.stab_of(node)
        r = self.retention(node, now)
        gain = 1.0 + (STAB_GAIN - 1.0) * (1.0 - r)   # R=1 时几乎不长，R→0 时涨得最多
        node["stab"] = round(_clip(st * gain, STAB_FLOOR, STAB_CAP), 3)
        node["la"] = now
        node["t1"] = now
        node["hits"] = int(node.get("hits") or 0) + 1
        self._dirty = True

    def _touch(self, node: dict) -> None:
        node["t1"] = _now()
        self._dirty = True

    def _link(self, a: str, b: str, w: float = 0.3) -> None:
        if not a or not b or a == b or a not in self.nodes or b not in self.nodes:
            return
        key = (a, b) if a < b else (b, a)
        cur = self.edges.get(key)
        if cur:
            cur["w"] = _clip(cur["w"] + w * 0.6, 0.01, 1.0)
            cur["t"] = _now()
        else:
            if len(self.edges) >= MAX_EDGES:
                self._prune_edges(MAX_EDGES - 1)
            self.edges[key] = {"w": _clip(w, 0.02, 1.0), "t": _now()}
        self._dirty = True

    def _unlink(self, node_id: str) -> None:
        dead = [k for k in self.edges if node_id in k]
        for k in dead:
            self.edges.pop(k, None)

    def _new_id(self, text: str, kind: str, session: str) -> str:
        h = hashlib.sha1(f"{kind}|{session}|{_norm(text)}".encode("utf-8")).hexdigest()
        return "n" + h[:12]

    def _add_node(self, text: str, kind: str, session: str, source: str,
                  imp: float | None = None, tags: list[str] | None = None,
                  subj: str = "", t0: float | None = None) -> str:
        nid = self._new_id(text, kind, session)
        base = KINDS[kind]["imp"] if imp is None else imp
        if not subj:
            # 主语标签：文本里提到谁，就记成"关于谁"，人物卡据此归类
            try:
                _names = {}
                for p in self.nodes.values():
                    if p.get("k") != "person" or not p.get("subj"):
                        continue
                    full = p["subj"]
                    _names.setdefault(full, full)
                    bare = re.sub(r"[（(][^）)]*[）)]|\d{5,12}", "", full).strip()
                    if len(bare) >= 2:
                        _names.setdefault(bare, full)
                _hit = [(name, full) for name, full in _names.items() if name in text]
                if _hit:
                    subj = max(_hit, key=lambda x: len(x[0]))[1][:24]
            except Exception:
                pass
        node = {
            "id": nid, "k": kind, "t": text[:MAX_TEXT].strip(), "s": session,
            "subj": subj[:24], "tags": list(tags or [])[:6],
            "imp": _clip(base, 0.05, 1.0), "hits": 0,
            "t0": float(t0 or _now()), "t1": float(t0 or _now()), "la": float(t0 or _now()),
            "act": 0.0, "src": source,
            "feel": list(getattr(self, "cur_mood", (0.5, 0.5))),
        }
        self.nodes[nid] = node
        self._bg[nid] = _bigrams(node["t"] + node["subj"])
        self._dirty = True
        return nid

    def _merge_into(self, keep_id: str, drop_id: str) -> None:
        keep, drop = self.nodes.get(keep_id), self.nodes.get(drop_id)
        if not keep or not drop or keep_id == drop_id:
            return
        if len(drop["t"]) > len(keep["t"]):
            keep["t"] = drop["t"]
            self._bg[keep_id] = _bigrams(keep["t"] + keep.get("subj", ""))
        keep["imp"] = max(keep["imp"], drop["imp"])
        keep["hits"] = int(keep["hits"]) + int(drop["hits"])
        keep["t0"] = min(keep["t0"], drop["t0"])
        keep["t1"] = max(keep["t1"], drop["t1"])
        keep["la"] = max(keep["la"], drop["la"])
        keep["act"] = max(keep.get("act", 0.0), drop.get("act", 0.0))
        keep["tags"] = list(dict.fromkeys(keep.get("tags", []) + drop.get("tags", [])))[:6]
        if drop["src"] == "explicit":
            keep["src"] = "explicit"
        for key in [k for k in self.edges if drop_id in k]:
            other = key[0] if key[1] == drop_id else key[1]
            w = self.edges.pop(key)["w"]
            if other != keep_id:
                self._link(keep_id, other, min(0.8, w))
        self._unlink(drop_id)
        self.nodes.pop(drop_id, None)
        self._bg.pop(drop_id, None)
        self._dirty = True

    # ------------------------------------------------------------ 写入

    def add(self, text: str, session: str = "", kind: str | None = None,
            source: str = "auto", imp: float | None = None,
            tags: list[str] | None = None, subj: str = "") -> str | None:
        """记一条。返回节点 id（合并到旧节点时返回旧 id）。"""
        text = str(text or "").strip()
        if not text:
            return None
        m = _SPLIT_RE.match(text)
        if m and m.group(1).strip() == "梗":
            # 梗节点：去掉「梗：」前缀、保留【梗】标签、强制 meme 类型
            body = m.group(2).strip()
            if not body:
                return None
            text = body
            kind = "meme"
            tags = list(tags or [])
            if "梗" not in tags:
                tags.append("梗")
        elif m and PREFIX_KIND.get(m.group(1).strip()):
            return self.add_line(text, session, source=source)
        kind = kind if kind in KINDS else "fact"
        with self.lock:
            return self._add_locked(text, session, kind, source, imp, tags, subj)

    def add_line(self, line: str, session: str = "", source: str = "auto") -> str | None:
        """记一条「类别：内容」；没有类别就猜。"""
        line = str(line or "").strip().lstrip("-·*0123456789.、 ").strip()
        if not line or line == "无":
            return None
        m = _SPLIT_RE.match(line)
        if m:
            prefix, body = m.group(1).strip(), m.group(2).strip()
            kind = PREFIX_KIND.get(prefix)
            if kind and body:
                if kind == "person" and not _looks_like_person(body):
                    kind = "fact"      # “群友都叫我傻鱼”这类句子不是人物
                subj = ""
                if kind == "person":
                    subj = re.split(r"[（(，,。；;]", body)[0].strip()[:12]
                return self.add(body, session, kind=kind, source=source,
                                tags=[prefix], subj=subj)
        return self.add(line, session, kind=None, source=source)

    def add_insight(self, text: str, session: str = "", sources: list[str] | None = None,
                    imp: float = 0.72) -> str | None:
        """反思出来的抽象结论：比普通事实重，连回它想明白的那几条记忆。"""
        text = str(text or "").strip()
        if not text:
            return None
        nid = self.add(text, session, kind="fact", source="reflect", imp=imp, tags=["反思"])
        with self.lock:
            for sid in (sources or [])[:6]:
                if sid in self.nodes and sid != nid:
                    self._link(nid, sid, 0.5)
            if nid:
                self.save(force=True)
        return nid

    def set_mood(self, v: float, a: float = 0.5) -> None:
        """记下当前心情，写新记忆时一起存，归档时就知道当时是什么感受。"""
        self.cur_mood = (round(float(v), 2), round(float(a), 2))

    def _add_locked(self, text: str, session: str, kind: str, source: str,
                    imp: float | None, tags: list[str] | None, subj: str) -> str | None:
        text = text[:MAX_TEXT].strip()
        if len(_norm(text)) < 2:
            return None
        bg = _bigrams(text + subj)
        best, best_sim = None, 0.0          # 同会话候选
        cross, cross_sim = None, 0.0        # 跨会话候选
        for n in self.nodes.values():
            if n["k"] != kind:
                continue
            s = _sim(bg, self._bigrams_of(n))
            same_s = (n["s"] == session) or (not n["s"] and not session)
            if same_s:
                if s > best_sim:
                    best, best_sim = n, s
            elif s > cross_sim:
                cross, cross_sim = n, s
        if best is not None and best_sim >= DEDUP_SIM:
            best["imp"] = _clip(max(best["imp"], imp if imp is not None else KINDS[kind]["imp"]) + 0.02, 0.05, 1.0)
            best["hits"] += 1
            best["la"] = _now()
            if source == "explicit":
                best["src"] = "explicit"
            if tags:
                best["tags"] = list(dict.fromkeys(best.get("tags", []) + list(tags)))[:6]
            self._dirty = True
            return best["id"]

        # 跨会话几乎完全相同（阈值更高），也并到旧节点，避免同一句话在每个群各存一份
        if cross is not None and cross_sim >= CROSS_DEDUP_SIM:
            cross["imp"] = _clip(max(cross["imp"], imp if imp is not None else KINDS[kind]["imp"]) + 0.02, 0.05, 1.0)
            cross["hits"] += 1
            cross["la"] = _now()
            if tags:
                cross["tags"] = list(dict.fromkeys(cross.get("tags", []) + list(tags)))[:6]
            self._dirty = True
            return cross["id"]

        nid = self._add_node(text, kind, session, source, imp, tags, subj)

        # 同一会话里刚聊到的，自动连起来（联想的基础）
        rec = self._recent.setdefault(session, [])
        recent_ids = [x[0] for x in rec if _now() - x[1] < 120][-4:]
        for rid in recent_ids:
            self._link(nid, rid, 0.28)
        rec.append([nid, _now()])
        del rec[:-10]

        # 事件/事实里提到的人，自动连到那个人身上（这条事是谁的）
        _txt = self.nodes[nid]["t"] if nid in self.nodes else text
        for _p in list(self.nodes.values())[-300:]:
            if _p["k"] != "person" or _p["id"] == nid:
                continue
            _name = (_p.get("subj") or "").strip()
            if len(_name) >= 2 and _name in _txt:
                self._link(nid, _p["id"], 0.55)
        # 人物节点：同一个人说的事，连到人身上
        if kind == "person" and subj:
            for n in list(self.nodes.values())[-60:]:
                if n["id"] != nid and (subj in n["t"] or subj in n.get("subj", "")):
                    self._link(nid, n["id"], 0.22)

        self.meta["adds"] = int(self.meta.get("adds", 0)) + 1
        self._dirty = True
        if self.meta["adds"] % CONSOLIDATE_EVERY == 0:
            self.consolidate()
        self.save(force=(source == "explicit"))
        return nid

    # ------------------------------------------------------------ 召回

    def _activation(self, session: str, query: str, limit: int = 10) -> list[tuple[float, dict]]:
        now = _now()
        ck = (session, query, limit)
        cached = self._qcache.get(ck)
        if cached and now - cached[0] < 20:
            return [ (s, self.nodes[nid]) for s, nid in cached[1] if nid in self.nodes ]
        q = _norm(query)
        qb = _bigrams(query) if q else set()
        scored: list[tuple[float, dict]] = []
        for n in self.nodes.values():
            if n.get("mute"):
                continue
            rel = 0.0
            if qb:
                rel = _sim(qb, self._bigrams_of(n))
                if q and q in _norm(n["t"]):
                    rel = max(rel, 0.74)
                if any(q and q in _norm(t) for t in n.get("tags", [])):
                    rel = max(rel, 0.82)
            rec = self.retention(n, now)      # 艾宾浩斯：按各自稳定期衰减
            ses = 1.0 if n["s"] == session else (0.85 if not n["s"] else 0.72)
            if q:
                # 有查询时，相关性优先；没命中任何词时靠“最近 + 本会话”，不要退化成只看重要度
                _very_recent = 1.0 if (n["s"] == session and now - n["t1"] < 2 * 86400) else 0.0
                score = (0.58 * rel + 0.10 * n["imp"] + 0.16 * rec + 0.14 * ses
                         + 0.05 * min(1.0, n["hits"] / 6.0) + 0.10 * _very_recent)
            else:
                score = 0.62 * n["imp"] + 0.25 * rec + 0.13 * ses
            # 工作记忆只在最近 2 天内还算数
            if n["k"] == "work" and now - n["t0"] > WORK_TTL:
                score *= 0.25
            if score > 0.06:
                scored.append((score, n))
        scored.sort(key=lambda x: x[0], reverse=True)
        seeds = scored[:max(limit, 6)]

        # 个性化 PageRank：从这句话激活的种子出发，沿突触扩散三轮
        # （不是简单一跳，所以「关于白米饭」能带出「主人」「上次约饭」这类二度联想）
        adj: dict[str, list[tuple[str, float]]] = {}
        for (a, b), e in self.edges.items():
            adj.setdefault(a, []).append((b, e["w"]))
            adj.setdefault(b, []).append((a, e["w"]))
        base = {n["id"]: sc for sc, n in scored}
        ppr = dict(base)
        for _ in range(3):
            nxt = {k: v * 0.20 for k, v in base.items()}
            for nid, w in ppr.items():
                nbs = adj.get(nid)
                if not nbs or w < 0.015:
                    continue
                share = 0.55 * w / min(len(nbs), 16)
                for other, ew in nbs[:16]:
                    nxt[other] = nxt.get(other, 0.0) + share * ew
            ppr = nxt
        merged: dict[str, tuple[float, dict]] = {}
        for nid, b in base.items():
            merged[nid] = (b * 0.88 + ppr.get(nid, b) * 0.30, self.nodes[nid])
        for nid, val in ppr.items():
            if nid in merged or nid not in self.nodes:
                continue
            if val > 0.02:
                merged[nid] = (min(0.45, val * 1.6), self.nodes[nid])
        out = sorted(merged.values(), key=lambda x: x[0], reverse=True)

        # 被想起的节点亮一下，并把「一起被想起」写进突触
        top = out[:max(3, min(limit, 6))]
        for _, n in top:
            self._reinforce(n)      # 所有检索路径共用同一套“复习”：涨稳期、更新 la、hits+1
            n["act"] = now
        for i in range(len(top)):
            for j in range(i + 1, min(len(top), 4)):
                self._link(top[i][1]["id"], top[j][1]["id"], 0.10)
        if top:
            self._dirty = True
            try:
                self._qcache[(session, query, limit)] = (now, [(sc, n["id"]) for sc, n in out[:limit]])
                if len(self._qcache) > 200:
                    self._qcache.clear()
            except Exception:
                pass
            self.save()
        return out[:limit]

    def search(self, session: str, query: str, limit: int = 10, kinds: set[str] | None = None
               ) -> list[tuple[float, dict]]:
        with self.lock:
            hits = self._activation(session, query, max(limit * 2, 12))
            if kinds:
                hits = [(s, n) for s, n in hits if n["k"] in kinds]
            return hits[:limit]

    def query(self, keyword: str, session: str = "", limit: int = 8) -> list[str]:
        with self.lock:
            hits = self._activation(session, keyword, limit)
            return [n["t"] for _, n in hits]

    def brief(self, session: str = "", limit: int = 8) -> str:
        with self.lock:
            hits = self._activation(session, "", limit)
            return "\n".join("- " + n["t"] for _, n in hits)

    def prompt_block(self, session: str = "", query: str = "", limit: int = 7) -> str:
        """拼进 system prompt 的那块：按当前这句话去脑子里捞相关记忆。"""
        with self.lock:
            hits = self._activation(session, query, limit + 6)
            picked, seen = [], set()
            for _, n in hits:
                if n["id"] not in seen:
                    seen.add(n["id"])
                    picked.append(n)
                if len(picked) >= limit:
                    break
            # 约定优先补进来（答应过的事不能忘）
            if len(picked) < limit + 1:
                # 约定不分会话：造她的人、答应过的事，哪都该记得
                ags = sorted((n for n in self.nodes.values() if n["k"] == "agreement"),
                             key=lambda n: n["imp"], reverse=True)[:3]
                for n in ags:
                    if n["id"] not in seen and len(picked) < limit + 1:
                        seen.add(n["id"])
                        picked.append(n)
            for _n in picked[:limit + 1]:
                try:
                    self._reinforce(_n)      # 想起来一次 = 复习一次，之后忘得更慢
                except Exception:
                    pass
            lines = [f"- [{KINDS[n['k']]['label']}] {n['t'][:60]}" for n in picked[:limit + 1]]
        mood = self.mood_line(session)
        if not lines and not mood:
            return ""
        out = ""
        # 约定放最前：先认人，再谈联想
        try:
            with self.lock:
                ags = sorted((n for n in self.nodes.values() if n["k"] == "agreement"),
                             key=lambda n: n["imp"], reverse=True)[:4]
            if ags:
                out += ("【约定（你一直记得的事，提到时要认）】\n"
                        + "\n".join(f"- {n['t'][:70]}" for n in ags))
        except Exception:
            pass
        if lines:
            out += ("\n\n" if out else "") + "【你脑子里浮出来的事（按这句话相关度挑的）】\n" + "\n".join(lines)

        if mood:
            out += ("\n\n" if out else "") + "【你现在的心情】" + mood
        return out

    # ------------------------------------------------------------ 情绪

    EVENT_WORDS = ("失业", "被裁", "裁员", "住院", "生病", "发烧", "去世", "走了", "手术",
                   "分手", "离婚", "吵架", "被骂", "失恋", "离职", "考试", "面试", "搬家",
                   "欠钱", "车祸", "抑郁", "失眠", "哭")
    PEOPLE_WORDS = ("我妈", "我爸", "我哥", "我姐", "我弟", "我妹", "我对象", "我女朋友",
                    "我男朋友", "我老婆", "我老公", "我朋友", "我同事", "我领导", "我老板")

    POS_WORDS = ("喜欢", "爱", "开心", "哈哈", "谢谢", "可爱", "乖", "亲", "抱", "好耶",
                 "厉害", "棒", "想你", "陪你", "夸", "对了", "好呀", "可以", "舒服", "温柔")
    NEG_WORDS = ("滚", "傻", "笨", "烦", "气死", "骂", "恶心", "讨厌", "闭嘴", "怼",
                 "去死", "废物", "垃圾", "吵", "别烦", "无聊")

    def observe(self, session: str, user_text: str, bot_text: str = "") -> None:
        """每轮聊完调一次：推动心情 + 留一条工作记忆。"""
        with self.lock:
            now = _now()
            a = self.affect.setdefault(session, {"v": 0.5, "a": 0.3, "t": now, "why": ""})
            # 先随时间回落
            idle_h = max(0.0, now - a["t"]) / 3600.0
            a["v"] = 0.5 + (a["v"] - 0.5) * math.exp(-idle_h / 8.0)
            a["a"] = 0.3 + (a["a"] - 0.3) * math.exp(-idle_h / 4.0)

            u = str(user_text or "")
            pos = sum(1 for w in self.POS_WORDS if w in u)
            neg = sum(1 for w in self.NEG_WORDS if w in u)
            bang = u.count("!") + u.count("！") + u.count("?") + u.count("？")
            a["v"] = _clip(a["v"] + 0.05 * pos - 0.07 * neg, 0.05, 0.95)
            a["a"] = _clip(a["a"] + 0.035 * min(4, bang) + 0.06 * neg, 0.05, 0.95)
            a["t"] = now
            if neg and not pos:
                a["why"] = "被怼了"
            elif pos > neg:
                a["why"] = "被哄了"
            self._dirty = True

            text = _norm(u)[:40]
            # EVENT_1106：近况类事件（失业、住院、被骂……）不管长短都进长期记忆。
            # 以前只按长度判断，导致「我妈住院了」这种最重要的话反而被当闲聊丢掉。
            _event = next((w for w in self.EVENT_WORDS if w in u), "")
            if _event and not u.strip().startswith("@") and "CQ:" not in u:
                self._add_locked(u[:80], session, "event", "event", 0.86,
                                 ["近况", _event], "")
                _who = next((w for w in self.PEOPLE_WORDS if w in u), "")
                if _who:
                    self._add_locked(f"{_who}的事：{u[:60]}", session, "event", "event", 0.8,
                                     ["人物", _who], _who)
            if (len(text) >= 15 and not u.strip().startswith("@")
                    and "CQ:" not in u and not _is_noise(u)):
                self._add_locked(u[:60], session, "work", "work", 0.22,
                                 ["工作记忆"], "")
            self.save()

    def mood(self, session: str = "") -> dict:
        with self.lock:
            a = self.affect.get(session) or {"v": 0.5, "a": 0.3}
            v, ar = a.get("v", 0.5), a.get("a", 0.3)
            if v >= 0.72:
                label = "心情很好"
            elif v >= 0.58:
                label = "心情不错"
            elif v >= 0.44:
                label = "平平的"
            elif v >= 0.28:
                label = "有点不爽"
            else:
                label = "在气头上"
            if ar >= 0.7:
                label += "，有点上头"
            return {"v": round(v, 3), "a": round(ar, 3), "label": label,
                    "why": a.get("why", "")}

    def mood_line(self, session: str = "") -> str:
        m = self.mood(session)
        if abs(m["v"] - 0.5) < 0.09 and m["a"] < 0.55:
            return ""
        return f"{m['label']}（别直接说出来，让它自然影响语气）"

    # ------------------------------------------------------------ 维护

    def remove(self, keyword: str, session: str = "") -> int:
        keyword = str(keyword or "").strip()
        if not keyword:
            return 0
        with self.lock:
            dead = [n["id"] for n in self.nodes.values()
                    if (n["s"] in ("", session)) and keyword in n["t"]]
            for nid in dead:
                self._unlink(nid)
                self.nodes.pop(nid, None)
                self._bg.pop(nid, None)
            if dead:
                self._dirty = True
                self.save(force=True)
            return len(dead)

    def _match_nodes(self, keyword: str, session: str | None = None,
                     limit: int = 60, fuzzy: bool = True) -> list[dict]:
        """一个关键词能对上哪些记忆：先精确包含，再按二字组模糊匹配（更准地找得着）。"""
        _nz = lambda x: re.sub(r"[\s，。、！？…~·,.!?]+", "", str(x or ""))
        kwv = _nz(keyword)
        if not kwv:
            return []
        grams = [kwv[i:i + 2] for i in range(len(kwv) - 1)] if len(kwv) >= 4 else []
        hits: list[dict] = []
        for n in list(self.nodes.values()):
            if session is not None and str(n.get("s") or "") not in ("", str(session)):
                continue
            t = _nz(n.get("t"))
            if kwv in t:
                hits.append(n)
            elif fuzzy and grams:
                got = sum(1 for g in grams if g in t)
                if got / len(grams) >= 0.6:
                    hits.append(n)
            if len(hits) >= limit:
                break
        return hits

    def forget(self, keyword: str, session: str | None = None, limit: int = 60) -> int:
        """彻底忘掉：把对上的记忆整条删掉。"""
        with self.lock:
            dead = self._match_nodes(keyword, session, limit)
            for n in dead:
                nid = n["id"]
                self._unlink(nid)
                self.nodes.pop(nid, None)
                self._bg.pop(nid, None)
            if dead:
                self._dirty = True
                self.save(force=True)
            return len(dead)

    def fade(self, keyword: str, session: str | None = None, limit: int = 60) -> int:
        """淡化：不删，只把重要度和稳定期压下去，让它自己慢慢淡出。"""
        with self.lock:
            hits = self._match_nodes(keyword, session, limit)
            for n in hits:
                try:
                    n["imp"] = round(_clip(float(n.get("imp") or 0.3) * 0.35, 0.03, 1.0), 3)
                    n["stab"] = round(max(1.2, self.stab_of(n) * 0.30), 3)
                    n["la"] = _now()
                except Exception:
                    pass
            if hits:
                self._dirty = True
                self.save(force=True)
            return len(hits)

    def mute(self, keyword: str, session: str | None = None, limit: int = 60) -> int:
        """别提：记忆留着（图上还在），但以后不再被想起来、也不再进 prompt。"""
        with self.lock:
            hits = self._match_nodes(keyword, session, limit)
            for n in hits:
                n["mute"] = True
            if hits:
                self._dirty = True
                self.save(force=True)
            return len(hits)

    def unmute_all(self) -> int:
        with self.lock:
            n = 0
            for x in self.nodes.values():
                if x.get("mute"):
                    x.pop("mute", None)
                    n += 1
            if n:
                self._dirty = True
                self.save(force=True)
            return n

    def clear(self, session: str | None = None) -> int:
        with self.lock:
            if session is None:
                n = len(self.nodes)
                self.nodes.clear()
                self.edges.clear()
                self._bg.clear()
                self.affect.clear()
            else:
                dead = [k for k, v in self.nodes.items() if v["s"] == session]
                for nid in dead:
                    self._unlink(nid)
                    self.nodes.pop(nid, None)
                    self._bg.pop(nid, None)
                    self.affect.pop(session, None)
                n = len(dead)
            self._dirty = True
            self.save(force=True)
            return n

    def _prune_edges(self, keep: int) -> None:
        if len(self.edges) <= keep:
            return
        ranked = sorted(self.edges.items(), key=lambda kv: kv[1]["w"], reverse=True)
        self.edges = dict(ranked[:max(0, keep)])

    def consolidate(self) -> dict:
        """像睡觉一样整理：合并重复、降权旧账、剪掉没用的、控制体量。"""
        with self.lock:
            now = _now()
            stats = {"merged": 0, "pruned": 0, "decayed": 0, "edges": 0}
            self.meta["last_consolidate"] = now

            # 1) 工作记忆过期
            for nid in [k for k, v in self.nodes.items()
                        if v["k"] == "work" and now - v["t0"] > WORK_TTL]:
                self._unlink(nid)
                self.nodes.pop(nid, None)
                self._bg.pop(nid, None)
                stats["pruned"] += 1
            works = sorted((v for v in self.nodes.values() if v["k"] == "work"),
                           key=lambda v: v["t0"], reverse=True)
            for v in works[MAX_WORK:]:
                self._unlink(v["id"])
                self.nodes.pop(v["id"], None)
                self._bg.pop(v["id"], None)
                stats["pruned"] += 1

            # 2) 同类近义合并（用倒排索引找候选，不做全量两两比较）
            index: dict[str, list[str]] = {}
            for n in self.nodes.values():
                for bg in list(self._bigrams_of(n))[:10]:
                    index.setdefault(bg, []).append(n["id"])
            done = set()
            for n in list(self.nodes.values()):
                if n["id"] in done or n["id"] not in self.nodes:
                    continue
                merged_away = False
                cand: dict[str, int] = {}
                for bg in list(self._bigrams_of(n))[:10]:
                    for oid in index.get(bg, ())[:30]:
                        if oid != n["id"]:
                            cand[oid] = cand.get(oid, 0) + 1
                for oid, shared in sorted(cand.items(), key=lambda kv: kv[1], reverse=True)[:6]:
                    other = self.nodes.get(oid)
                    if not other or oid in done or other["k"] != n["k"]:
                        continue
                    if n["s"] and other["s"] and n["s"] != other["s"]:
                        continue
                    if shared < 2:
                        continue
                    na, nb = _norm(n["t"]), _norm(other["t"])
                    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
                    contained = len(short) >= 4 and short in long_ and len(short) >= 0.55 * len(long_)
                    if contained or _sim(self._bigrams_of(n), self._bigrams_of(other)) >= DEDUP_SIM:
                        keep, drop = (n, other) if (n["imp"], len(n["t"])) >= (other["imp"], len(other["t"])) else (other, n)
                        self._merge_into(keep["id"], drop["id"])
                        done.add(drop["id"])
                        stats["merged"] += 1
                        if drop is n:
                            merged_away = True
                            break
                if n["id"] not in self.nodes:
                    continue
                if merged_away:
                    continue

            # 3) 不用的记忆慢慢变淡：200 天半衰（用过的会重置衰减钟）
            for n in list(self.nodes.values()):
                if n["src"] == "explicit" or n["k"] == "agreement":
                    continue
                if n["k"] == "person" and n["src"] != "seen":
                    continue
                base = max(float(n.get("d") or 0.0), float(n["la"]))
                idle_days = max(0.0, now - base) / 86400
                if idle_days >= 0.5:
                    factor = 0.5 ** (idle_days / DECAY_HALF_LIFE_DAYS)
                    n["imp"] = _clip(n["imp"] * factor, 0.05, 1.0)
                    n["d"] = now
                    stats["decayed"] += 1

            # 4) 两个半衰期（400 天）还没人想起、又已经很弱的，清掉
            for n in list(self.nodes.values()):
                if n["src"] == "explicit" or n["k"] == "agreement":
                    continue
                if n["k"] == "person" and n["src"] != "seen":
                    continue
                idle_days = (now - float(n["la"])) / 86400
                if n["k"] == "person" and n["src"] == "seen" and idle_days > 30 and n["hits"] <= 1:
                    self._unlink(n["id"]); self.nodes.pop(n["id"], None); self._bg.pop(n["id"], None)
                    stats["pruned"] += 1
                    continue
                if n["imp"] < 0.08 and idle_days > 2 * DECAY_HALF_LIFE_DAYS and n["hits"] <= 1:
                    self._unlink(n["id"])
                    self.nodes.pop(n["id"], None)
                    self._bg.pop(n["id"], None)
                    stats["pruned"] += 1

            # 5) 剪边 + 控总量
            for key in [k for k, e in self.edges.items()
                        if e["w"] < 0.04 or k[0] not in self.nodes or k[1] not in self.nodes]:
                self.edges.pop(key, None)
            self._prune_edges(MAX_EDGES)

            if len(self.nodes) > MAX_NODES:
                ranked = sorted(self.nodes.values(),
                                key=lambda v: (v["src"] == "explicit", v["imp"] * 0.7 +
                                               math.exp(-max(0.0, now - v["la"]) / 86400 / 24) * 0.3),
                                reverse=True)
                for v in ranked[MAX_NODES:]:
                    self._unlink(v["id"])
                    self.nodes.pop(v["id"], None)
                    self._bg.pop(v["id"], None)
                    stats["pruned"] += 1

            stats["edges"] = len(self.edges)
            stats["nodes"] = len(self.nodes)
            self.meta["last_stats"] = stats
            self._dirty = True
            self.save(force=True)
            return stats

    # ------------------------------------------------------------ 统计 / 图

    def count(self) -> int:
        return len(self.nodes)

    # ------------------------------------------------------------ 自我调用：彩球目录 / 定点召回

    def tier(self, node: dict, now: float | None = None) -> str:
        """记忆分层：短期 / 中期 / 长期。"""
        now = now or _now()
        if node["k"] == "work":
            return "short"
        age = now - node["t0"]
        if node["imp"] >= 0.75 or node["hits"] >= 4 or age > 60 * 86400:
            return "long"
        if age < 7 * 86400 and node["hits"] < 2:
            return "short"
        return "mid"

    def catalog(self, session: str = "", limit_names: int = 6) -> str:
        """给核心看的「彩球目录」：只列有什么，不列内容。她自己决定要不要调用。"""
        with self.lock:
            by = {k: 0 for k in KINDS}
            for n in self.nodes.values():
                by[n["k"]] = by.get(n["k"], 0) + 1
            parts = [f"{KINDS[k]['label']}{by[k]}" for k in KIND_ORDER if by.get(k)]
            names = [n["subj"] for n in self.nodes.values()
                     if n["k"] == "person" and n.get("subj")]
            names = list(dict.fromkeys(names))[:limit_names]
            if not parts:
                return ""
            out = "【你的记忆球】" + " ".join(parts)
            if names:
                out += "；认识的人：" + "、".join(names)
            out += "。需要时写 [想:类型:关键词] 调出来（例如 [想:人物:主人]、[想:事实:白米饭]），不用就别写。"
            return out

    def recall_kind(self, kind: str, keyword: str, session: str = "", limit: int = 6) -> list[dict]:
        with self.lock:
            kk = kind if kind in KINDS else None
            hits = self._activation(session, keyword, max(limit * 2, 10))
            if kk:
                hits = [(s, n) for s, n in hits if n["k"] == kk]
            return [n for _, n in hits[:limit]]

    def stats(self) -> dict:
        with self.lock:
            by_kind = {k: 0 for k in KINDS}
            for n in self.nodes.values():
                by_kind[n["k"]] = by_kind.get(n["k"], 0) + 1
            return {
                "nodes": len(self.nodes),
                "edges": len(self.edges),
                "by_kind": by_kind,
                "adds": int(self.meta.get("adds", 0)),
                "sessions": len({n["s"] for n in self.nodes.values() if n["s"]}),
                "last_consolidate": self.meta.get("last_consolidate", 0),
                "limit": MAX_NODES,
            }

    def _pos(self, node: dict, counts: dict | None = None) -> tuple[float, float, float]:
        ax, ay, az = ANCHORS.get(node["k"], (0, 0, 0))
        h = hashlib.sha1(node["id"].encode("utf-8")).digest()
        rnd = random.Random(int.from_bytes(h[:8], "big"))
        if counts is None:
            counts = {}
            for v in self.nodes.values():
                counts[v["k"]] = counts.get(v["k"], 0) + 1
        region_n = counts.get(node["k"], 0) or 1
        radius = 0.09 + 0.075 * math.sqrt(min(region_n, 400) / 400.0)
        ox = rnd.uniform(-1, 1) * radius
        oy = rnd.uniform(-1, 1) * radius * 0.85
        oz = rnd.uniform(-1, 1) * radius
        # 让球壳更饱满：把点往薄的方向推开一点
        ox *= 1.0 + 0.15 * (rnd.random() - 0.5)
        return (ax * 0.82 + ox, ay * 0.82 + oy, az * 0.82 + oz)

    def export_graph(self) -> dict:
        with self.lock:
            now = _now()
            nodes = []
            regions = {}
            tiers = {"short": 0, "mid": 0, "long": 0}
            counts = {}
            for n in self.nodes.values():
                if "梗" in (n.get("tags") or []):
                    _k = "meme"
                elif "金句" in (n.get("tags") or []):
                    _k = "quote"
                elif n.get("k") == "feeling" and any(w in str(n.get("t", "")) for w in ("他", "她", "对方", "群友", "别人")):
                    _k = "empathy"
                else:
                    _k = n["k"]
                counts[_k] = counts.get(_k, 0) + 1
            for _node_idx, n in enumerate(self.nodes.values()):
                if "梗" in (n.get("tags") or []):
                    _k = "meme"
                elif "金句" in (n.get("tags") or []):
                    _k = "quote"
                elif n.get("k") == "feeling" and any(w in str(n.get("t", "")) for w in ("他", "她", "对方", "群友", "别人")):
                    _k = "empathy"
                else:
                    _k = n["k"]
                # 脑区布局：按类型落进对应脑叶，左右半球随机
                region_n = counts.get(_k, 0) or 1
                # 越牢固越靠里；今天新发生、容易忘的摊到皮层
                try:
                    _age_d = max(0.0, now - float(n.get("t0", now))) / 86400.0
                    _decay = 0.5 ** (_age_d / 200.0)
                    _base = float(n.get("imp", 0.5)) * _decay * 0.85
                    _base += min(0.2, 0.04 * float(n.get("hits", 0)))
                    if n.get("k") == "person":
                        # 人物：好感高就离核心近，好感低就漂在外层
                        _base = max(_base, float(n.get("warmth", 0.5) or 0.5))
                    if n.get("k") == "agreement":
                        # 约定（含世界约定）永远贴核心
                        _base = max(_base, 0.95)
                    if "金句" in (n.get("tags") or []):
                        _base = max(_base, 0.7)
                    if "梗" in (n.get("tags") or []):
                        _base = min(_base, 0.30)  # 梗是借来的说法，稍微靠外就行
                    if n.get("k") == "work":
                        _base = min(_base, 0.15)
                    if n.get("src") == "explicit":
                        _base = max(_base, 0.9)
                    _strength = max(0.05, min(1.0, _base))
                except Exception:
                    _strength = 0.5
                # 三层深度：忘不掉的往里收，今天的摊在皮层
                if _strength >= 0.70:
                    _layer = "inner"
                elif _strength >= 0.32:
                    _layer = "mid"
                else:
                    _layer = "outer"
                _gi = GALAXY_FOR.get(_k, 0)
                _orb_r, _orb_a, _orb_inc = _galaxy_orbit(n["id"], _layer, _gi)
                x, y, z = _galaxy_pos(_gi, _orb_r, _orb_a, _orb_inc)
                # 特别亲的人（好感 ≥0.88）不在人物星系里转，改成贴着「核心·傻鱼」转
                _core_sat = False
                if _k == "person":
                    try:
                        _w = float(n.get("warmth", 0.0) or 0.0)
                    except Exception:
                        _w = 0.0
                    if _w >= 0.88:
                        _core_sat = True
                        _gi = -1                                   # 前端识别：核心卫星
                        _rad = round(2.60 - 1.00 * min(1.0, (_w - 0.88) / 0.12), 3)   # 1.6 ~ 2.6
                        _seed = sum(ord(c) for c in str(n["id"])) % 628 / 100.0
                        _orb_r, _orb_a, _orb_inc = _rad, _seed, 0.22
                        x, y, z = _galaxy_pos(0, _orb_r, _orb_a, _orb_inc)
                        x = y = z = 0.0
                        x = _orb_r * math.cos(_orb_a)
                        z = _orb_r * math.sin(_orb_a)
                        y = z * math.sin(_orb_inc)
                nodes.append({
                    "id": n["id"], "k": _k, "t": n["t"], "s": n["s"],
                    "subj": n.get("subj", ""), "imp": round(n["imp"], 3),
                    "hits": n["hits"], "act": n.get("act", 0),
                    "tier": self.tier(n, now),
                    "r": round(self.retention(n, now), 3),        # 艾宾浩斯保持率
                    "stab": round(self.stab_of(n), 2),            # 稳定期（天）
                    "warmth": round(float(n.get("warmth", 0.0) or 0.0), 2),
                    "feel": n.get("feel") or [],
                    "layer": _layer,
                    "age": round(max(0.0, now - n["t0"]), 0),
                    "x": round(x, 4), "y": round(y, 4), "z": round(z, 4),
                    "orb": [round(_orb_r, 3), round(_orb_a, 3), round(_orb_inc, 3)],
                    "gal": _gi,
                })
                regions[_k] = regions.get(_k, 0) + 1
                tiers[self.tier(n, now)] = tiers.get(self.tier(n, now), 0) + 1
            # 位置全部来自 orb（星系里的轨道），前端每帧自己算，
            # 这里不再做 O(n²) 的防重合 —— 那套把点往原点收的推挤早就没用了，
            # 每次 /api/brain 白烧 150ms 的 CPU。
            edges = [[a, b, round(e["w"], 3)] for (a, b), e in self.edges.items()]
            sessions = sorted({n["s"] for n in self.nodes.values() if n["s"]})[:40]
            return {
                "v": 2, "now": now,
                "nodes": nodes, "edges": edges,
                "regions": [{"key": k, "label": KINDS[k]["label"], "color": KINDS[k]["color"],
                             "count": regions.get(k, 0)} for k in list(dict.fromkeys(KIND_ORDER + ["meme", "quote", "empathy"]))],
                "stats": self.stats(),
                "tiers": tiers,
                "galaxies": GALAXIES,
                "moods": {s: self.mood(s) for s in sessions},
                "default_mood": self.mood(""),
            }

    # ------------------------------------------------------------ 迁移 / 初始化

    def _bootstrap(self) -> None:
        """第一次跑：把 memory.json 老记忆 + 会话上下文搬进脑子。"""
        self._quiet = True
        legacy = self.dir / LEGACY_NAME
        moved = 0
        try:
            if legacy.exists():
                try:
                    data = json.loads(legacy.read_text(encoding="utf-8"))
                except Exception:
                    data = []
                if isinstance(data, list):
                    for e in data:
                        if not isinstance(e, dict):
                            continue
                        text = str(e.get("text") or "").strip()
                        if not text:
                            continue
                        sess = str(e.get("s") or "")
                        ts = float(e.get("t") or _now())
                        nid = self.add_line(text, sess, source="migrated")
                        if nid and nid in self.nodes:
                            self.nodes[nid]["t0"] = ts
                            self.nodes[nid]["t1"] = ts
                            moved += 1
            sess_file = self.dir / SESSION_NAME
            if sess_file.exists():
                try:
                    data = json.loads(sess_file.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
                if isinstance(data, dict):
                    for sess, msgs in list(data.items())[-30:]:
                        if not isinstance(msgs, list):
                            continue
                        for m in msgs[-2:]:
                            if not isinstance(m, dict):
                                continue
                            txt = str(m.get("content") or "").strip()
                            if 6 <= len(txt) <= 80:
                                self._add_locked(txt[:60], str(sess), "work", "work",
                                                 0.20, ["工作记忆"], "")
        finally:
            self._quiet = False
        self.meta["migrated"] = True
        self._dirty = True
        self.save(force=True)
        if moved:
            print(f"[brain] 从 memory.json 搬进来 {moved} 条老记忆")
        self.consolidate()


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    mode = "stats" if not args or args[0] in ("stats", "graph") else args[0]
    rest = args[1:] if args and args[0] in ("stats", "graph") else args
    base = Path(rest[0]) if rest else Path(__file__).parent
    b = Brain(base)
    b.load()
    if mode == "graph":
        print(json.dumps(b.export_graph(), ensure_ascii=False))
        return 0
    st = b.stats()
    print(json.dumps({"stats": st, "mood_default": b.mood("")}, ensure_ascii=False, indent=2))
    print(f"文件：{b.path}（{b.path.stat().st_size // 1024 if b.path.exists() else 0} KB）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

