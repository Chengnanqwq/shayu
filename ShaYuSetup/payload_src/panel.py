#!/usr/bin/env python3
"""傻鱼管理面板（本地 WebUI）—— 装完之后的管理界面。

像 AstrBot 的 dashboard：浏览器里改配置、看状态、看日志、看大脑。

  · 配置：把 config.json 的**所有键**渲染成表单（开关 / 数字 / 文本 / JSON），
          改完点保存，先备份成 config.json.bak-时间戳 再写回
  · 大脑：内嵌 brain_viz.html，四套配色（星系 / 原野 / 书页 / 终端）
  · 日志：读 logs/bot-*.log 的尾巴
  · 状态：bot 进程、QQ 连接、端口

启动：pythonw panel.py  →  浏览器 http://127.0.0.1:6201
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import cfg_meta
except Exception:
    cfg_meta = None

HERE = Path(__file__).resolve().parent
CFG_PATH = HERE / "config.json"
LOG_DIR = HERE / "logs"
BRAIN_HTML = HERE / "brain_viz.html"
PORT = int(os.environ.get("SHayu_PANEL_PORT", "6201"))

# ---------------------------------------------------------------- 工具


def read_cfg() -> dict:
    try:
        return json.loads(CFG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_cfg(cfg: dict) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = CFG_PATH.with_suffix(f".json.bak-{ts}")
    try:
        if CFG_PATH.exists():
            bak.write_bytes(CFG_PATH.read_bytes())
    except Exception:
        pass
    CFG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return bak.name


def build_config_view(cfg: dict) -> dict:
    """把 config.json 整理成面板好渲染的列表：带中文名、说明、分组，隐藏内部状态。"""
    items = []
    hidden = set(getattr(cfg_meta, "HIDDEN", set())) if cfg_meta else set()
    meta_map = getattr(cfg_meta, "META", {}) if cfg_meta else {}
    feat_map = getattr(cfg_meta, "FEATURE_META", {}) if cfg_meta else {}
    groups = getattr(cfg_meta, "GROUPS", [["raw", "设置"]]) if cfg_meta else [["raw", "设置"]]

    def walk(o, pre=""):
        for k, v in o.items():
            p = (pre + "." + k) if pre else k
            if p in hidden:
                continue
            if isinstance(v, dict):
                walk(v, p)
                continue
            g, name, desc = meta_map.get(p, ("raw", p, "还没写中文说明的配置项"))
            items.append({"path": p, "group": g, "name": name, "desc": desc,
                          "raw": p, "value": v})

    # features 单独列（每个开关一行，中文说明来自 FEATURE_META）
    body = {k: v for k, v in cfg.items() if k != "features"}
    walk(body)
    for k, v in (cfg.get("features") or {}).items():
        if not isinstance(v, (bool, int, float, str)):
            continue
        items.append({"path": "features." + k, "group": "feat",
                      "name": feat_map.get(k, k), "desc": "功能开关",
                      "raw": "features." + k, "value": v})
    # 按分组顺序排
    order = {g: i for i, (g, _) in enumerate(groups)}
    items.sort(key=lambda it: (order.get(it["group"], 99), it["name"]))
    return {"items": items, "groups": [{"key": g, "name": n} for g, n in groups]}


def bot_running():
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine"],
            capture_output=True, text=True, timeout=8).stdout
        for ln in out.splitlines():
            if "bot.py" in ln and str(HERE) in ln:
                return ln.strip().split()[-1]
    except Exception:
        pass
    return None


DEFAULT_COLORS = {
    "person": "#FF3B5C", "empathy": "#FF6FB5", "quote": "#C238FF", "feeling": "#8A5CFF",
    "skill": "#3D7DFF", "fact": "#00D4FF", "meme": "#00E59B", "object": "#7ED957",
    "event": "#FFC53D", "agreement": "#FFF066", "visual": "#FF8A3D", "work": "#8FA0B8",
}
COLOR_NAMES = {
    "person": "人物", "empathy": "别人的情绪", "quote": "金句", "feeling": "情绪",
    "skill": "技能", "fact": "事实", "meme": "梗", "object": "实物",
    "event": "事件", "agreement": "约定", "visual": "视觉", "work": "短期",
}
COLORS_FILE = HERE / "brain_colors.json"


def read_colors() -> dict:
    out = dict(DEFAULT_COLORS)
    try:
        d = json.loads(COLORS_FILE.read_text(encoding="utf-8"))
        for k, v in d.items():
            if k in out and isinstance(v, str) and v.startswith("#"):
                out[k] = v
    except Exception:
        pass
    return out


def write_colors(d: dict) -> dict:
    cur = read_colors()
    for k, v in (d or {}).items():
        if k in cur and isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            cur[k] = v
    COLORS_FILE.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    return cur


def inject_colors(html_src: str) -> str:
    """把 brain_viz.html 里写死的 COLORS 换成用户存的那套。"""
    m = re.search(r"var COLORS = \{[^}]*\};", html_src, re.S)
    if not m:
        return html_src
    cols = read_colors()
    body = "var COLORS = {\n" + ",\n".join(f'  {k}: "{v}"' for k, v in cols.items()) + "\n};"
    return html_src.replace(m.group(0), body, 1)


def read_soul() -> dict:
    try:
        return json.loads((HERE / "soul.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_brain() -> dict:
    out = {"nodes": 0, "edges": 0}
    try:
        b = json.loads((HERE / "brain_memory.json").read_text(encoding="utf-8"))
        out["nodes"] = len(b.get("nodes") or {})
        ed = b.get("edges") or {}
        out["edges"] = sum(len(v) for v in ed.values()) if isinstance(ed, dict) else len(ed)
    except Exception:
        pass
    return out


def today_stats() -> dict:
    """从当天的日志里数一数收了多少条、回了多少条、主动说了几次。"""
    p = LOG_DIR / f"bot-{time.strftime('%Y-%m-%d')}.log"
    out = {"recv": 0, "sent": 0, "proactive": 0, "errors": 0}
    if not p.exists():
        return out
    try:
        txt = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return out
    out["recv"] = len(re.findall(r"收到\[", txt))
    out["sent"] = len(re.findall(r"发出", txt))
    out["proactive"] = len(re.findall(r"主动接话|自主决策:|冒泡", txt))
    out["errors"] = len(re.findall(r"Traceback|异常|失败:", txt))
    return out


def proc_info(pid) -> dict:
    if not pid:
        return {}
    try:
        out = subprocess.run(
            ["wmic", "process", "where", f"ProcessId={pid}", "get",
             "WorkingSetSize,KernelModeTime,UserModeTime", "/format:csv"],
            capture_output=True, text=True, timeout=8).stdout
        for ln in out.splitlines():
            parts = [x for x in ln.strip().split(",") if x]
            if len(parts) >= 4 and parts[-1].isdigit():
                return {"mem_mb": round(int(parts[-3]) / 1024 / 1024, 1)}
    except Exception:
        pass
    return {}


def tail_log(n=200):
    if not LOG_DIR.exists():
        return "（还没有日志）"
    files = sorted(LOG_DIR.glob("bot-*.log"))
    if not files:
        return "（还没有日志）"
    try:
        lines = files[-1].read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except Exception as e:
        return f"读日志失败：{e}"


# ---------------------------------------------------------------- 前端
PAGE = r"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>傻鱼面板</title>
<style>
:root{--bg:#f7f6fb;--card:#fff;--tx:#302c42;--sub:#8c8a9b;--ok:#48bb78;--bad:#e85a64;
      --acc:#7c6adc;--line:#eceaf3}
*{box-sizing:border-box}
body{margin:0;font-family:"Microsoft YaHei UI",system-ui;background:var(--bg);color:var(--tx);
     display:flex;height:100vh;overflow:hidden}
nav{width:190px;background:#2f2a45;color:#cfc9e6;padding:18px 0;flex-shrink:0;
    transition:width .18s}
@media (max-width:820px){nav{width:132px}nav a{padding:10px 12px;font-size:12px}
  main{padding:14px 14px}.grid{grid-template-columns:1fr}}
nav h1{font-size:15px;margin:0 18px 18px;color:#fff}
nav a{display:block;padding:10px 18px;color:#cfc9e6;text-decoration:none;font-size:13px;cursor:pointer}
nav a.on{background:#413a5e;color:#fff;border-left:3px solid var(--acc)}
nav .foot{position:absolute;bottom:14px;left:18px;font-size:11px;color:#8d86a8}
main{flex:1;overflow:auto;padding:20px 24px}
h2{font-size:17px;margin:0 0 14px}
.card{background:var(--card);border-radius:12px;padding:16px 18px;margin-bottom:14px;
      box-shadow:0 1px 3px rgba(0,0,0,.05)}
.row{display:flex;gap:10px;align-items:center}
button{background:var(--acc);color:#fff;border:0;border-radius:8px;padding:9px 18px;
       font-size:13px;font-family:inherit;cursor:pointer;font-weight:600}
button.ghost{background:#efeff5;color:var(--tx)}
button:disabled{opacity:.5}
input[type=text],input[type=number],textarea,select{width:100%;padding:8px 10px;
       border:1px solid var(--line);border-radius:7px;font-size:13px;font-family:inherit;outline:none}
input:focus,textarea:focus{border-color:var(--acc)}
textarea{min-height:70px;resize:vertical;line-height:1.65}
textarea.long{min-height:260px;font-size:12.5px}
label.f{display:block;margin:12px 0 4px;font-size:12px;color:var(--sub)}
.k{font-family:Consolas,monospace;font-size:12px;color:var(--acc)}
.sw{position:relative;display:inline-block;width:42px;height:22px;vertical-align:middle}
.sw input{opacity:0;width:0;height:0}
.sw i{position:absolute;inset:0;background:#d8d6e2;border-radius:11px;transition:.2s;cursor:pointer}
.sw i:before{content:"";position:absolute;width:18px;height:18px;left:2px;top:2px;background:#fff;
             border-radius:50%;transition:.2s}
.sw input:checked+i{background:var(--ok)}
.sw input:checked+i:before{transform:translateX(20px)}
details{border:1px solid var(--line);border-radius:9px;padding:10px 12px;margin:10px 0}
details summary{cursor:pointer;font-size:13px;font-weight:600}
.hero{background:linear-gradient(135deg,#5b4b9e 0%,#7c6adc 55%,#9d7ce8 100%);
      color:#fff;border-radius:14px;padding:20px 22px;margin-bottom:14px;
      display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px;
      box-shadow:0 6px 18px rgba(124,106,220,.25)}
.hero-t{font-size:19px;font-weight:700;letter-spacing:.5px}
.hero-s{font-size:12px;color:#ded6ff;margin-top:5px}
.hero-r{display:flex;gap:22px}
.kpi{text-align:center}
.kpi b{display:block;font-size:22px;font-weight:700;line-height:1.1}
.kpi span{font-size:11px;color:#ded6ff}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin-bottom:14px}
.card{background:var(--card);border-radius:12px;padding:16px 18px;
      box-shadow:0 1px 3px rgba(0,0,0,.05);transition:box-shadow .18s,transform .18s}
.card:hover{box-shadow:0 4px 14px rgba(80,60,160,.10);transform:translateY(-1px)}
.ct{font-size:13px;font-weight:700;margin-bottom:12px;color:var(--tx)}
.kv{display:flex;justify-content:space-between;font-size:12px;color:var(--sub)}
.kv b{color:var(--tx);font-size:13px}
.mini{display:grid;grid-template-columns:1fr 1fr;gap:12px;text-align:center}
.mini b{display:block;font-size:20px;color:var(--acc)}
.mini span{font-size:11px;color:var(--sub)}
.stat{display:flex;gap:14px;flex-wrap:wrap}
.stat div{flex:1;min-width:150px;background:var(--card);border-radius:12px;padding:14px 16px;
          box-shadow:0 1px 3px rgba(0,0,0,.05)}
.stat b{display:block;font-size:20px;margin-top:6px}
pre{background:#1d1a2b;color:#cfd3e6;padding:14px;border-radius:10px;overflow:auto;
    font-size:12px;line-height:1.6;max-height:62vh}
/* 沉浸模式：侧栏/工具条收走，iframe 铺满，右上角浮退出按钮 */
#fsExit{display:none;position:fixed;top:14px;right:18px;z-index:10000;cursor:pointer;
  background:rgba(30,26,48,.88);color:#fff;border-radius:20px;padding:9px 18px;
  font-size:13px;font-weight:600;box-shadow:0 4px 16px rgba(0,0,0,.35);
  border:1px solid rgba(255,255,255,.18);backdrop-filter:blur(6px);transition:all .16s}
#fsExit:hover{background:var(--acc);transform:translateY(-1px)}
#fsExit span{font-size:11px;font-weight:400;opacity:.7}
body.immersive nav,body.immersive #main > *:not(#bf):not(#fsExit){display:none !important}
body.immersive main{padding:0 !important;overflow:hidden}
body.immersive #bf{position:fixed !important;inset:0 !important;width:100vw !important;
  height:100vh !important;border-radius:0 !important;z-index:9998}
body.immersive #fsExit{display:block}
.cfgbar{display:flex;gap:12px;align-items:flex-start;justify-content:space-between;
  flex-wrap:wrap;margin-bottom:12px}
.cfgtabs{display:flex;gap:6px;flex-wrap:wrap;flex:1;min-width:0}
.ctab{background:#fff;color:var(--tx);border:1px solid var(--line);border-radius:20px;
  padding:7px 14px;font-size:12.5px;font-weight:600;display:inline-flex;align-items:center;gap:6px;
  transition:all .16s;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.ctab i{font-style:normal;font-size:10px;background:#efeff5;color:var(--sub);
  border-radius:9px;padding:1px 6px}
.ctab:hover{border-color:var(--acc);color:var(--acc)}
.ctab.on{background:var(--acc);border-color:var(--acc);color:#fff}
.ctab.on i{background:rgba(255,255,255,.25);color:#fff}
.cfgact{display:flex;gap:8px;flex:none}
.gsec{padding-top:2px}
.themes{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.themes button{padding:8px 16px;font-size:12px}
.themes button.on{box-shadow:0 0 0 2px var(--acc) inset}
iframe{width:100%;height:calc(100vh - 118px);border:0;border-radius:10px;background:#05070f}
main{display:flex;flex-direction:column}
#main h2{margin-bottom:10px}
.tip{font-size:12px;color:var(--sub);margin-top:8px}
</style></head><body>
<nav>
  <h1>傻鱼面板</h1>
  <a data-t="status" class="on">状态</a>
  <a data-t="config">配置</a>
  <a data-t="brain">大脑</a>
  <a data-t="log">日志</a>
  <div class="foot">v1 · 本地 WebUI</div>
</nav>
<main id="main"></main>
<script>
let CFG = null, TAB = 'brain';
const $ = s => document.querySelector(s);
document.querySelectorAll('nav a').forEach(a=>{
  a.onclick = ()=>{
    document.querySelectorAll('nav a').forEach(x=>x.classList.remove('on'));
    a.classList.add('on'); TAB = a.dataset.t; render();
  };
  a.classList.toggle('on', a.dataset.t === TAB);   // 初始高亮跟着当前页走
});
function h(t){return String(t??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
async function jget(u){return await (await fetch(u)).json()}
async function jpost(u,b){return await (await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify(b||{})})).json()}

function render(){
  if(TAB==='status') return status();
  if(TAB==='config') return config();
  if(TAB==='brain') return brain();
  if(TAB==='log') return logv();
}
async function status(){
  const s = await jget('/api/status');
  const t = s.today || {}, b = s.brain || {}, m = s.mood || {}, e = s.emotions || {};
  const bar = (v, max, color) => {
    const p = Math.max(0, Math.min(100, (v / (max||1)) * 100));
    return `<div style="height:6px;background:#eeedf4;border-radius:3px;overflow:hidden;margin-top:5px">
      <i style="display:block;height:100%;width:${p}%;background:${color};border-radius:3px"></i></div>`;
  };
  const EMON = {joy:'开心',anger:'生气',sadness:'难过',gratitude:'感激',fear:'害怕',hope:'期待',hurt:'委屈',pride:'得意'};
  const emoHtml = Object.entries(EMON).map(([k,n])=>{
    const v = Number(e[k]||0);
    return `<div style="margin-bottom:9px">
      <div style="display:flex;justify-content:space-between;font-size:11px">
        <span>${n}</span><span class="tip">${v.toFixed(1)}</span></div>
      ${bar(v, 20, v>12?'#e85a64':(v>5?'#f59e42':'#48bb78'))}</div>`;
  }).join('');

  $('#main').innerHTML = `
  <div class="hero">
    <div>
      <div class="hero-t">${s.asleep?'睡着中':'在线上'}</div>
      <div class="hero-s">${s.pid?('PID '+s.pid+' · 已陪了你 '+s.alive_h+' 小时'):'没在跑'}</div>
    </div>
    <div class="hero-r">
      <div class="kpi"><b>${s.turns}</b><span>对话轮次</span></div>
      <div class="kpi"><b>${t.recv||0}</b><span>今日收到</span></div>
      <div class="kpi"><b>${t.sent||0}</b><span>今日回了</span></div>
      <div class="kpi"><b>${t.proactive||0}</b><span>主动开口</span></div>
    </div>
  </div>

  <div class="grid">
    <div class="card">
      <div class="ct">她现在的心情</div>
      <div class="kv"><span>愉悦 v</span><b>${(m.v||0).toFixed(2)}</b></div>${bar((m.v||0)+1, 2, '#48bb78')}
      <div class="kv" style="margin-top:10px"><span>兴奋 a</span><b>${(m.a||0).toFixed(2)}</b></div>${bar(m.a||0, 1, '#5684e6')}
      <div class="tip" style="margin-top:10px">${m.where?('刚在：'+h(m.where)):'——'}</div>
    </div>

    <div class="card">
      <div class="ct">八维情绪</div>
      ${emoHtml}
    </div>

    <div class="card">
      <div class="ct">身体状态</div>
      <div class="kv"><span>精神</span><b>${s.spirit}</b></div>${bar(s.spirit, 100, '#5684e6')}
      <div class="kv" style="margin-top:10px"><span>疲劳</span><b>${s.fatigue}</b></div>${bar(s.fatigue, 100, s.fatigue>80?'#e85a64':'#f59e42')}
      <div class="kv" style="margin-top:10px"><span>吃过</span><b>${(s.rice||{}).bowls||0} 碗</b></div>
      ${bar((s.rice||{}).full||0, 100, '#48bb78')}
    </div>

    <div class="card">
      <div class="ct">记忆与关系</div>
      <div class="mini">
        <div><b>${b.nodes||0}</b><span>记忆节点</span></div>
        <div><b>${b.edges||0}</b><span>联想连线</span></div>
        <div><b>${s.rel||0}</b><span>认识的人</span></div>
        <div><b>${s.skills||0}</b><span>学会的事</span></div>
      </div>
      <div class="tip" style="margin-top:12px">配置 ${s.cfg_keys} 项 · 插件 ${s.plugins} 个 · 模型 ${h(s.model)}</div>
    </div>
  </div>

  <div class="card" style="display:flex;align-items:center;gap:10px;margin-top:2px">
    <button onclick="jpost('/api/bot/start').then(()=>setTimeout(render,1500))">启动</button>
    <button class="ghost" onclick="jpost('/api/bot/stop').then(()=>setTimeout(render,900))">停止</button>
    <button class="ghost" onclick="render()">刷新</button>
    <span class="tip">${h(s.hint||'')}${s.proc&&s.proc.mem_mb?(' · 内存 '+s.proc.mem_mb+' MB'):''}</span>
  </div>

  <div class="card">
    <div class="ct">最近的动静 <span class="tip">（今日 ${t.errors||0} 条异常）</span></div>
    <pre style="max-height:200px" id="recent">加载中…</pre>
  </div>`;
  jget('/api/log').then(r=>{
    const txt = (r.text||'').split('\n').slice(-12).join('\n');
    const el = document.getElementById('recent');
    if(el) el.textContent = txt || '（还没有日志）';
  });
}
function field(key, val, path){
  const id = 'f_' + path;
  if(typeof val === 'boolean')
    return `<label class="f"><span class="k">${h(key)}</span></label>
      <label class="sw"><input type="checkbox" id="${id}" ${val?'checked':''}><i></i></label>`;
  if(typeof val === 'number')
    return `<label class="f"><span class="k">${h(key)}</span></label>
      <input type="number" id="${id}" value="${val}">`;
  if(typeof val === 'string'){
    const long = val.length > 60 || val.includes('\\n');
    return `<label class="f"><span class="k">${h(key)}</span></label>` +
      (long ? `<textarea id="${id}">${h(val)}</textarea>`
            : `<input type="text" id="${id}" value="${h(val)}">`);
  }
  return `<label class="f"><span class="k">${h(key)}</span>（JSON）</label>
    <textarea id="${id}">${h(JSON.stringify(val, null, 1))}</textarea>`;
}
function walk(obj, prefix){
  let out = '';
  for(const k of Object.keys(obj)){
    const v = obj[k], p = prefix ? prefix+'.'+k : k;
    if(v && typeof v === 'object' && !Array.isArray(v)){
      out += `<details ${Object.keys(v).length<=8?'open':''}><summary>${h(k)}</summary>${walk(v,p)}</details>`;
    } else {
      out += field(k, v, p);
    }
  }
  return out;
}
let VIEW = null, CURG = null;
async function config(){
  VIEW = await jget('/api/config');
  const groups = VIEW.groups.filter(g => VIEW.items.some(it => it.group === g.key));
  if(!CURG || !groups.some(g => g.key === CURG)) CURG = groups[0] ? groups[0].key : 'raw';
  const cnt = k => VIEW.items.filter(it => it.group === k).length;
  $('#main').innerHTML = `<h2>配置</h2>
    <div class="cfgbar">
      <div class="cfgtabs">
        ${groups.map(g => `<button class="ctab${g.key===CURG?' on':''}" data-g="${g.key}"
           onclick="switchGroup('${g.key}')">${h(g.name)}<i>${cnt(g.key)}</i></button>`).join('')}
      </div>
      <div class="cfgact">
        <button onclick="saveCfg()">保存全部</button>
        <button class="ghost" onclick="config()">重新读取</button>
      </div>
    </div>
    <div class="card" style="padding-top:8px">
      <div class="tip" style="margin-bottom:6px">改完点保存，会先把旧配置备份一份。多数项要重启机器人才生效。
        <span id="savemsg"></span></div>
      ${groups.map(g => `<div class="gsec" data-k="${g.key}"
          style="display:${g.key===CURG?'block':'none'}">
          ${VIEW.items.filter(it=>it.group===g.key).map(it=>fmtItem(it)).join('')}
        </div>`).join('')}
    </div>`;
}
function switchGroup(k){
  CURG = k;
  document.querySelectorAll('.ctab').forEach(b => b.classList.toggle('on', b.dataset.g === k));
  document.querySelectorAll('.gsec').forEach(d => {
    d.style.display = (d.dataset.k === k) ? 'block' : 'none';
  });
  $('#main').scrollTop = 0;
}
function fmtItem(it){
  const id = 'c_' + it.path.replace(/\./g,'__');
  const tag = `<div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:2px">
      <span style="font-size:13px">${h(it.name)}</span>
      <span class="tip" style="font-family:Consolas,monospace">${h(it.raw)}</span></div>
    <div class="tip" style="margin:2px 0 6px">${h(it.desc)}</div>`;
  let ctl;
  if(typeof it.value === 'boolean')
    ctl = `<label class="sw"><input type="checkbox" id="${id}" ${it.value?'checked':''}><i></i></label>`;
  else if(typeof it.value === 'number')
    ctl = `<input type="number" id="${id}" value="${it.value}" step="any">`;
  else if(typeof it.value === 'string'){
    const long = it.value.length > 60 || it.value.includes('\n');
    ctl = long ? `<textarea class="long" id="${id}">${h(it.value)}</textarea>`
               : `<input type="text" id="${id}" value="${h(it.value)}">`;
  } else
    ctl = `<textarea id="${id}">${h(JSON.stringify(it.value,null,1))}</textarea>`;
  return `<div style="padding:10px 0;border-bottom:1px solid #f2f1f7">${tag}${ctl}</div>`;
}
function setPath(obj, path, val){
  const ks = path.split('.'); let o = obj;
  for(let i=0;i<ks.length-1;i++) o = o[ks[i]];
  o[ks[ks.length-1]] = val;
}
function getPath(obj, path){
  const ks = path.split('.'); let o = obj;
  for(const k of ks) o = o?.[k];
  return o;
}
async function saveCfg(){
  const cfg = await jget('/api/config/raw');
  let bad = 0;
  VIEW.items.forEach(it=>{
    const el = document.getElementById('c_' + it.path.replace(/\./g,'__'));
    if(!el) return;
    let v;
    if(el.type==='checkbox') v = el.checked;
    else if(el.type==='number'){ v = Number(el.value); if(isNaN(v)) { bad++; return; } }
    else if(typeof it.value === 'object'){
      try{ v = JSON.parse(el.value); }catch(e){ bad++; return; }
    }
    else v = el.value;
    setPath(cfg, it.path, v);
  });
  const r = await jpost('/api/config', cfg);
  const m = $('#savemsg');
  m.textContent = r.ok ? ('已保存（备份 ' + r.backup + '）' + (bad?('，'+bad+' 项格式不对没保存'):''))
                       : ('失败：'+r.error);
  m.style.color = r.ok ? 'var(--ok)' : 'var(--bad)';
}
const THEMES = [['galaxy','星系'],['forest','原野'],['paper','书页'],['terminal','终端']];
async function brain(){
  const cur = localStorage.getItem('brain_theme') || 'galaxy';
  $('#main').innerHTML = `<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px">
      <div class="themes" style="margin:0">${THEMES.map(([k,n])=>
        `<button class="${k===cur?'on':''}" onclick="setTheme('${k}')">${n}</button>`).join('')}</div>
      <button class="ghost" onclick="window.location.href='/atlas'">记忆星图</button>
      <button class="ghost" id="fsBtn" onclick="fullBrain()">全屏看</button>
      <button class="ghost" onclick="toggleColors()">调色</button>
      <span class="tip">滚轮放大缩小 · 拖动平移 · 右下角 ＋/－ · 按 0 复位</span>
    </div>
    <div id="colorBox" style="display:none;background:#fff;border-radius:12px;
         padding:14px 16px;margin-bottom:10px;box-shadow:0 1px 3px rgba(0,0,0,.05)"></div>
    <div id="fsExit" onclick="fullBrain()">退出全屏 ✕ <span>（或按 Esc）</span></div>
    <iframe id="bf" src="/brain?theme=${cur}" allowfullscreen
      style="width:100%;height:calc(100vh - 128px)"></iframe>`;
}
function fullBrain(){
  const on = document.body.classList.toggle('immersive');
  const b = document.getElementById('fsBtn');
  if(b) b.textContent = on ? '退出全屏' : '全屏看';
}
// 沉浸模式下按 Esc 回来
document.addEventListener('keydown', function(e){
  if(e.key === 'Escape' && document.body.classList.contains('immersive')){
    document.body.classList.remove('immersive');
    const b = document.getElementById('fsBtn');
    if(b) b.textContent = '全屏看';
  }
});
let COLS = null, CNames = {};
async function toggleColors(){
  const box = document.getElementById('colorBox');
  if(box.style.display !== 'none'){ box.style.display = 'none'; return; }
  if(!COLS){
    const d = await jget('/api/colors');
    COLS = d.colors; CNames = d.names;
  }
  box.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px">
    ${Object.keys(COLS).map(k=>`
      <div style="display:flex;align-items:center;gap:8px;background:#faf9fd;border-radius:8px;padding:8px 10px">
        <input type="color" id="col_${k}" value="${COLS[k]}"
          style="width:34px;height:26px;border:0;background:none;padding:0;cursor:pointer">
        <div style="flex:1">
          <div style="font-size:12px">${h(CNames[k]||k)}</div>
          <div class="tip" style="font-family:Consolas,monospace;font-size:10px" id="hex_${k}">${COLS[k]}</div>
        </div>
      </div>`).join('')}
  </div>
  <div class="row" style="margin-top:12px">
    <button onclick="saveColors()">保存配色</button>
    <button class="ghost" onclick="resetColors()">恢复默认</button>
    <span class="tip" id="colmsg"></span>
  </div>`;
  box.style.display = 'block';
  Object.keys(COLS).forEach(k=>{
    const el = document.getElementById('col_'+k);
    el.oninput = ()=>{ document.getElementById('hex_'+k).textContent = el.value.toUpperCase(); };
  });
}
async function saveColors(){
  const body = {};
  Object.keys(COLS).forEach(k=>{ body[k] = document.getElementById('col_'+k).value.toUpperCase(); });
  const r = await jpost('/api/colors', body);
  const m = document.getElementById('colmsg');
  if(r.ok){
    COLS = r.colors;
    m.textContent = '已保存，画面正在换色…'; m.style.color = 'var(--ok)';
    document.getElementById('bf').src = '/brain?theme=' + (localStorage.getItem('brain_theme')||'galaxy') + '&t=' + Date.now();
    setTimeout(()=>{ m.textContent = '已保存'; }, 1500);
  } else { m.textContent = '失败：'+r.error; m.style.color = 'var(--bad)'; }
}
async function resetColors(){
  const body = {};
  Object.keys(COLS).forEach(k=>{ body[k] = null; });
  // 逐项写回默认：后端会忽略非法值，这里直接覆盖成默认表
  const d = await jget('/api/colors');
  Object.keys(d.defaults).forEach(k=>{ body[k] = d.defaults[k]; });
  const r = await jpost('/api/colors', body);
  if(r.ok){
    COLS = r.colors;
    Object.keys(COLS).forEach(k=>{
      const el = document.getElementById('col_'+k);
      if(el){ el.value = COLS[k]; document.getElementById('hex_'+k).textContent = COLS[k].toUpperCase(); }
    });
    document.getElementById('bf').src = '/brain?theme=' + (localStorage.getItem('brain_theme')||'galaxy') + '&t=' + Date.now();
    document.getElementById('colmsg').textContent = '已恢复默认';
  }
}
function setTheme(t){
  localStorage.setItem('brain_theme', t);
  document.getElementById('bf').src = '/brain?theme=' + t;
  document.querySelectorAll('.themes button').forEach(b=>b.classList.remove('on'));
  event.target.classList.add('on');
}
async function logv(){
  const r = await jget('/api/log');
  $('#main').innerHTML = `<h2>日志</h2>
    <div class="row" style="margin-bottom:10px">
      <button class="ghost" onclick="logv()">刷新</button>
      <span class="tip">${h(r.file||'')}</span></div>
    <pre>${h(r.text)}</pre>`;
}
render(); setInterval(()=>{ if(TAB==='status') render(); }, 5000);
</script></body></html>"""

# 四套配色：只调 CSS，canvas 用 hue-rotate 整体改色调，不动那 89KB 的绘制代码
THEME_CSS = """
<style id="themePatch">
/* 通用：风格纹理层，压在 canvas 上、HUD 下 */
body::after{content:"";position:fixed;inset:0;z-index:4;pointer-events:none;opacity:0;
  transition:opacity .3s}

/* ---- 星系（默认）：干净星空 + 极淡光晕 ---- */
body[data-theme="galaxy"]::after{
  opacity:1;
  background:radial-gradient(ellipse 60% 45% at 50% 45%,
             rgba(90,140,255,.10) 0%, rgba(90,140,255,0) 70%)}

/* ---- 原野：颗粒 + 暖绿萤火 ---- */
body[data-theme="forest"]{background:#06120b !important}
body[data-theme="forest"] #c{filter:hue-rotate(96deg) saturate(.9) brightness(1.05)}
body[data-theme="forest"]::after{
  opacity:1;
  background:
    radial-gradient(circle at 22% 30%, rgba(140,255,170,.16) 0%, transparent 42%),
    radial-gradient(circle at 78% 68%, rgba(190,255,120,.12) 0%, transparent 46%),
    repeating-radial-gradient(circle at 50% 50%,
      rgba(255,255,255,.028) 0 1px, transparent 1px 3px)}
body[data-theme="forest"] .hud,body[data-theme="forest"] #leftpanel>*,body[data-theme="forest"] #card{
  background:linear-gradient(160deg,rgba(10,32,20,.94),rgba(6,18,12,.94)) !important;
  border-color:#1f4a33 !important;color:#c9f0da !important}

/* ---- 书页：纸纹网格 + 低对比 ---- */
body[data-theme="paper"]{background:#f4ecd8 !important}
body[data-theme="paper"] #c{filter:invert(1) hue-rotate(180deg) saturate(.5) brightness(1.15) contrast(.92)}
body[data-theme="paper"]::after{
  opacity:1;
  background:
    repeating-linear-gradient(90deg, rgba(120,95,50,.055) 0 1px, transparent 1px 4px),
    repeating-linear-gradient(0deg, rgba(120,95,50,.045) 0 1px, transparent 1px 4px),
    radial-gradient(ellipse 80% 60% at 50% 40%, rgba(255,250,235,.5) 0%, transparent 75%)}
body[data-theme="paper"] .hud,body[data-theme="paper"] #leftpanel>*,body[data-theme="paper"] #card{
  background:linear-gradient(160deg,rgba(255,250,240,.95),rgba(244,236,216,.95)) !important;
  border-color:#d8c9a8 !important;color:#4a3f2c !important}
body[data-theme="paper"] .tbtn{color:#4a3f2c !important;border-color:#d8c9a8 !important}

/* ---- 终端：扫描线 + 暗角 + 等宽绿字 ---- */
body[data-theme="terminal"]{background:#000 !important}
body[data-theme="terminal"] #c{filter:grayscale(1) sepia(1) hue-rotate(58deg) saturate(4.5) brightness(.92)}
body[data-theme="terminal"]::after{
  opacity:1;
  background:
    repeating-linear-gradient(0deg,
      rgba(0,255,130,.05) 0 1px, transparent 1px 3px),
    radial-gradient(ellipse 75% 65% at 50% 50%,
      transparent 40%, rgba(0,0,0,.55) 100%)}
body[data-theme="terminal"] .hud,body[data-theme="terminal"] #leftpanel>*,
body[data-theme="terminal"] #card,body[data-theme="terminal"] #title,
body[data-theme="terminal"] #hint,#body[data-theme="terminal"] #legend *{
  background:rgba(0,12,0,.9) !important;border-color:#1d5f2a !important;color:#7dffa0 !important;
  font-family:Consolas,"Cascadia Mono",monospace !important;letter-spacing:.4px}
body[data-theme="terminal"] .tbtn{color:#7dffa0 !important;border-color:#1d5f2a !important}
</style>
"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body: bytes, ctype="text/html; charset=utf-8", code=200):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, o, code=200):
        self._send(json.dumps(o, ensure_ascii=False).encode(), "application/json; charset=utf-8", code)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/api/status":
            cfg = read_cfg()
            soul = read_soul()
            brain = read_brain()
            pl = len(list((HERE / "plugins").glob("*.py"))) if (HERE / "plugins").exists() else 0
            pid = bot_running()
            born = float(soul.get("born") or 0)
            alive_h = round((time.time() - born) / 3600, 1) if born else 0
            mood = soul.get("mood") or {}
            emo = soul.get("emotions") or {}
            slp = soul.get("sleep") or {}
            rice = soul.get("rice") or {}
            return self._json({
                "pid": pid,
                "alive_h": alive_h,
                "turns": int(soul.get("turns") or 0),
                "model": cfg.get("llm_model") or "",
                "self_qq": cfg.get("self_qq") or "",
                "cfg_keys": len(cfg),
                "plugins": pl,
                "brain": brain,
                "mood": {"v": round(float(mood.get("v") or 0), 2),
                         "a": round(float(mood.get("a") or 0), 2),
                         "why": mood.get("why") or "", "where": mood.get("where") or ""},
                "emotions": {k: round(float(v or 0), 1) for k, v in emo.items()},
                "fatigue": round(float((soul.get("fatigue") or {}).get("v") or 0), 1),
                "spirit": round(float((soul.get("spirit") or {}).get("v") or 0), 1),
                "asleep": bool(slp.get("asleep")),
                "sleep_reason": slp.get("reason") or "",
                "rice": {"bowls": int(rice.get("bowls") or 0),
                         "full": round(float(rice.get("full") or 0), 1)},
                "rel": len(soul.get("rel") or {}),
                "skills": len(soul.get("skills") or []),
                "today": today_stats(),
                "proc": proc_info(pid),
                "hint": "改完配置要重启机器人才生效" if pid else "机器人没在跑，点启动",
            })
        if p == "/api/config":
            return self._json(build_config_view(read_cfg()))
        if p == "/api/colors":
            return self._json({"colors": read_colors(), "names": COLOR_NAMES,
                               "defaults": DEFAULT_COLORS})
        if p == "/api/memory":
            try:
                d = json.loads((HERE / "brain_memory.json").read_text(encoding="utf-8"))
            except Exception as e:
                return self._json({"nodes": [], "edges": [], "error": str(e)})
            nodes = [{"id": n.get("id"), "k": n.get("k"), "t": n.get("t"),
                      "imp": n.get("imp"), "hits": n.get("hits"), "act": n.get("act")}
                     for n in (d.get("nodes") or [])]
            edges = [e for e in (d.get("edges") or []) if isinstance(e, list) and len(e) >= 3][:4000]
            return self._json({"nodes": nodes, "edges": edges})
        if p == "/api/config/raw":
            return self._json(read_cfg())
        if p == "/api/log":
            files = sorted(LOG_DIR.glob("bot-*.log")) if LOG_DIR.exists() else []
            return self._json({"file": files[-1].name if files else "", "text": tail_log(200)})
        if p == "/atlas":
            try:
                return self._send((HERE / "memory_atlas.html").read_bytes())
            except Exception as e:
                return self._send(("<pre>memory_atlas.html 读不到：%s</pre>" % e).encode())
        if p == "/brain":
            q = ""
            if "?" in self.path:
                q = self.path.split("?", 1)[1]
            theme = "galaxy"
            for kv in q.split("&"):
                if kv.startswith("theme="):
                    theme = kv.split("=", 1)[1]
            try:
                html_src = BRAIN_HTML.read_text(encoding="utf-8")
            except Exception as e:
                return self._send(f"<pre>brain_viz.html 读不到：{e}</pre>".encode())
            html_src = inject_colors(html_src)
            # CORE_MOOD_1105：把她的状态塞给可视化，让核心跟着变
            soul = read_soul()
            mood = soul.get("mood") or {}
            emo = soul.get("emotions") or {}
            core_mood = {
                "v": round(float(mood.get("v") or 0), 3),
                "a": round(float(mood.get("a") or 0.5), 3),
                "spirit": round(float((soul.get("spirit") or {}).get("v") or 50), 1),
                "fatigue": round(float((soul.get("fatigue") or {}).get("v") or 0), 1),
                "anger": round(float(emo.get("anger") or 0), 2),
                "joy": round(float(emo.get("joy") or 0), 2),
                "asleep": bool((soul.get("sleep") or {}).get("asleep")),
            }
            html_src = html_src.replace(
                "</head>",
                "<script>window.CORE_MOOD = %s;</script></head>"
                % __import__("json").dumps(core_mood, ensure_ascii=False), 1)
            html_src = html_src.replace("</head>", THEME_CSS + "</head>", 1)
            html_src = re.sub(r"<body([^>]*)>", lambda m: f'<body{m.group(1)} data-theme="{theme}">'
                              if "data-theme" not in m.group(1) else m.group(0), html_src, count=1)
            return self._send(html_src.encode())
        return self._send(PAGE.encode())

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0"))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            data = {}
        p = self.path.split("?")[0]
        if p == "/api/config":
            try:
                bak = write_cfg(data if isinstance(data, dict) else {})
                return self._json({"ok": True, "backup": bak})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)})
        if p == "/api/colors":
            try:
                return self._json({"ok": True, "colors": write_colors(data)})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)})
        if p == "/api/bot/start":
            try:
                py = HERE / "runtime" / "pythonw.exe"
                if not py.exists():
                    py = Path(sys.executable)
                subprocess.Popen([str(py), str(HERE / "bot.py")], cwd=str(HERE),
                                 creationflags=0x08000000)
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)})
        if p == "/api/bot/stop":
            try:
                pid = bot_running()
                if pid:
                    subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True)
                return self._json({"ok": True})
            except Exception as e:
                return self._json({"ok": False, "error": str(e)})
        return self._json({"ok": False, "error": "unknown"})


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    print(f"面板 {url}", flush=True)

    # PANEL_DESKTOP_1105：用自己的窗口，不再拉 Edge
    try:
        import webview
        webview.create_window("傻鱼面板", url, width=1280, height=900,
                              min_size=(880, 600), text_select=True)
        webview.start()
    except Exception as e:
        print(f"pywebview 起不来（{e}），退回默认浏览器", flush=True)
        import webbrowser
        webbrowser.open(url)
        while True:
            time.sleep(1)


if __name__ == "__main__":
    main()
