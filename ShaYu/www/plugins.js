/* 插件市场（对齐 AstrBot）：搜索 / 标签 / 卡片 / 安装 / 卸载 / 更新 / 上传 / 分享到商店 */
let MK = { list: [], tab: "installed", q: "", tag: "" };
/* 同名文件待覆盖：第一次选/拖进来先问一句（用状态栏，不弹窗），再点一次就覆盖 */
let PENDING = null;
/* 同名插件在商店里已存在，等用户再点一次「分享」才覆盖 */
let SHARE_PENDING = null;

async function openMarket(quiet) {
  if (!quiet) setMsg("正在读插件…");
  await Promise.all([loadLocal(), loadRemote(), loadStore()]);
  renderMarket();
  if (quiet) return;                     // 上传完的自动刷新别把结果提示冲掉
  const all = mkAll();
  const on = all.filter(p => p.installed).length;
  setMsg(all.length ? `已装 ${on} 个，市场里共 ${all.length} 个` : "没读到插件");
}

/* 商店（别人分享的插件）：没配 store_repo 就整块不出现 */
async function loadStore() {
  MK.store = [];
  MK.storeOk = false;
  MK.storeError = "";
  try {
    const r = await fetch(PANEL + "/api/store", { cache: "no-store" });
    const d = await r.json();
    if (!d.ok) { MK.storeError = d.error || "商店不可用"; return; }
    // 后端给的是 update_available / local_version，卡片那边认 update，这里统一一下
    MK.store = (d.plugins || []).map(p => ({
      ...p,
      source: "store",
      update: !!p.update_available,
      enabled: !!p.enabled,
    }));
    MK.storeOk = true;
    MK.storeBase = d.store || "";
    MK.storeWeb = d.store_web || "";
  } catch (e) {
    MK.storeError = e.message;
  }
}

async function loadLocal() {
  try {
    const r = await fetch(PANEL + "/api/plugins", { cache: "no-store" });
    const d = await r.json();
    MK.local = d.plugins || [];
  } catch { MK.local = []; }
}

async function loadRemote() {
  try {
    const r = await fetch(PANEL + "/api/market", { cache: "no-store" });
    const d = await r.json();
    if (!d.ok) { MK.error = d.error || "读不到市场"; MK.remote = []; return; }
    MK.error = "";
    MK.repo = d.repo;
    MK.remote = d.plugins || [];
  } catch (e) { MK.error = e.message; MK.remote = []; }
}

function mkAll() {
  // 合并：本地已装 + 远端可装
  const byId = {};
  const out = [];
  (MK.local || []).forEach(p => {
    const id = (p.file || "").replace(/\.py$/, "").split(/[\\/]/).pop();
    const remote = (MK.remote || []).find(r => r.id === id);
    const item = {
      id,
      name: p.name || id,
      file: p.file,
      enabled: p.enabled,
      version: remote ? remote.version : "本地",
      author: remote ? remote.author : "—",
      desc: (remote && remote.desc) || (p.commands || []).join("　") || "已装插件",
      tags: remote ? remote.tags || [] : [],
      installed: true,
      online: !!remote,
      update: remote ? (remote.update_available || remote.update) : false,
      url: remote ? remote.url : "",
      // 数据包的字段要原样带出来，否则会退化成普通插件卡片
      type: (remote && remote.type) || "plugin",
      target: remote && remote.target,
      size: remote && remote.size,
      files: remote && remote.files,
      local_version: remote && remote.local_version
    };
    byId[id] = item;
    out.push(item);
  });
  (MK.remote || []).forEach(r => {
    const id = r.id;
    if (byId[id]) return;
    const isData = r.type === "data";
    // 已装的数据包不在 /api/plugins 里（那不是 .py），得从市场条目补回来
    if (isData && !r.installed) {
      // 未装：正常出现在「全部」里
    }
    out.push({
      id, name: r.name, file: r.file, version: r.version, author: r.author,
      desc: r.desc, tags: r.tags || [],
      installed: isData ? !!r.installed : false,
      online: true, update: r.update_available || r.update || false,
      url: r.url, enabled: isData ? !!r.installed : false,
      type: r.type || "plugin", target: r.target, size: r.size,
      files: r.files, local_version: r.local_version
    });
  });
  return out;
}

function renderMarket() {
  const box = document.getElementById("pluginbody");
  if (!box) return;
  bindDropOnce();

  const all = mkAll();
  const tags = [...new Set(all.flatMap(p => p.tags || []).concat((MK.store || []).flatMap(p => p.tags || [])))];

  let list = MK.tab === "store" ? (MK.store || []).slice() : all;
  if (MK.tab === "installed") list = list.filter(p => p.installed);
  if (MK.q) {
    const q = MK.q.toLowerCase();
    list = list.filter(p =>
      (p.name + p.desc + (p.tags || []).join("")).toLowerCase().includes(q));
  }
  if (MK.tag) list = list.filter(p => (p.tags || []).includes(MK.tag));

  const installedCount = all.filter(p => p.installed).length;
  const updCount = all.filter(p => p.update).length;
  const storeCount = MK.storeOk ? (MK.store || []).length : 0;

  box.innerHTML = `
    <div class="mk-bar">
      <div class="mk-tabs">
        <button class="${MK.tab === 'installed' ? 'on' : ''}" onclick="MK.tab='installed';renderMarket()">
          已装 ${installedCount}</button>
        <button class="${MK.tab === 'market' ? 'on' : ''}" onclick="MK.tab='market';renderMarket()">
          全部 ${all.length}</button>
        ${MK.storeOk ? `<button class="${MK.tab === 'store' ? 'on' : ''}"
          title="插件商店：${esc(MK.storeBase || "")}（任何人都能往那个仓库提插件）"
          onclick="MK.tab='store';renderMarket()">商店 ${storeCount}</button>` : ""}
      </div>
      <input class="mk-search" placeholder="搜插件名、功能…" value="${esc(MK.q)}"
        oninput="MK.q=this.value;renderMarket()">
      <button class="sf-btn ghost" style="height:30px;padding:0 14px;font-size:11.5px"
        onclick="openMarket()">刷新</button>
      <button class="mk-btn primary mk-upload" onclick="pickPlugin()"
        title="选一个 .py 装进来；也可以直接把文件拖到这个页面">上传插件</button>
      <button class="mk-btn mk-overwrite" onclick="confirmOverwrite()"
        style="${PENDING ? '' : 'display:none'}"
        title="用刚才那个文件覆盖同名插件">覆盖 ${PENDING ? esc(PENDING.name) : ""}</button>
    </div>
    ${tags.length ? `<div class="mk-tags">
      <span class="mk-tag ${MK.tag === '' ? 'on' : ''}" onclick="MK.tag='';renderMarket()">全部</span>
      ${tags.map(t => `<span class="mk-tag ${MK.tag === t ? 'on' : ''}"
        onclick="MK.tag='${esc(t)}';renderMarket()">${esc(t)}</span>`).join("")}
    </div>` : ""}
    ${MK.error ? `<div class="pl-warn" style="margin:10px 0">${esc(MK.error)}</div>` : ""}
    ${MK.tab === 'store' && !MK.storeOk && MK.storeError
      ? `<div class="pl-warn" style="margin:10px 0">商店连不上：${esc(MK.storeError)}</div>` : ""}
    ${MK.tab !== 'store' && updCount ? `<div class="mk-tip">有 ${updCount} 个插件可以更新</div>` : ""}
    <div class="mk-list">
      ${list.length ? list.map(safeCard).join("")
        : `<div class="sf-empty">${
            MK.tab === 'installed' ? "还没装插件"
            : MK.tab === 'store' ? "商店里还没有人分享插件"
            : "没找到匹配的插件"}</div>`}
    </div>`;
}

/* 一张卡片坏掉不能让整个列表变空：出错就渲染成一条能看懂的提示卡 */
function safeCard(p) {
  try {
    return mkCard(p);
  } catch (e) {
    return `<div class="pl-card"><div class="pl-ico">⚠️</div>
      <div class="pl-main"><div class="pl-head"><span class="pl-name">${esc(p && (p.name || p.id) || "未知插件")}</span></div>
      <div class="pl-desc">这条显示不出来：${esc(e && e.message || e)}</div></div></div>`;
  }
}

/* 卡片里传参只传文件名的 basename：
   Windows 路径里的反斜杠塞进 onclick="f('D:\a\b.py')" 会被当转义吃掉（\t \n \p…），
   以前卸载框里显示的乱码路径就是这个原因。 */
function baseName(f) {
  return String(f ?? "").split(/[\\/]/).pop();
}
function enc(s) {
  return encodeURIComponent(String(s ?? ""));
}

function mb(n) {
  if (!n) return "";
  if (n >= 1024 ** 3) return (n / 1024 ** 3).toFixed(1) + "GB";
  if (n >= 1024 ** 2) return (n / 1024 ** 2).toFixed(n >= 10 * 1024 ** 2 ? 0 : 1) + "MB";
  return Math.round(n / 1024) + "KB";
}

function mkCard(p) {
  const isData = p.type === "data";
  const badge = p.update ? `<span class="pl-badge warn">可更新</span>`
    : p.installed ? `<span class="pl-badge local">已装</span>`
    : p.source === "store" ? `<span class="pl-badge bot">商店</span>` : "";
  if (isData) {
    const dt = [
      p.installed ? null : (p.size ? mb(p.size) : null),
      p.files ? p.files + " 个文件" : null,
      "解压到 " + esc(p.target || "—") + "/",
    ].filter(Boolean).join(" · ");
    const btns = p.installed
      ? `${p.update ? `<button class="mk-btn" onclick="doInstall('${enc(p.id)}', 'data')"
             title="本地 v${esc(p.local_version || '')} → ${esc(p.version || '')}">更新到 v${esc(p.version || '')}</button>` : ""}
         <button class="mk-btn danger" onclick="doUninstall('${enc(p.id)}', 'data', '${enc(p.target || '')}')">卸载</button>`
      : `<button class="mk-btn primary" onclick="doInstall('${enc(p.id)}', 'data')">安装</button>`;
    return `<div class="pl-card ${p.installed ? 'on' : ''}">
      <div class="pl-ico">🎁</div>
      <div class="pl-main">
        <div class="pl-head">
          <span class="pl-name">${esc(p.name)}</span>
          <span class="pl-badge">v${esc(p.version || '')}</span>
          ${badge}
        </div>
        <div class="pl-desc">${esc(p.desc || '')}</div>
        <div class="pl-detail">${dt}${p.author ? " · " + esc(p.author) : ""}</div>
      </div>
      <div class="pl-side mk-actions">${btns}</div>
    </div>`;
  }
  const fname = enc(baseName(p.file));
  // 已装的能分享到商店（商店没配就不显示这个按钮）
  const share = (p.installed && MK.storeOk)
    ? `<button class="mk-btn" onclick="doShare('${fname}')"
         title="传到商店，别人也能装">分享</button>` : "";
  const btns = p.installed
    ? `<label class="sw"><input type="checkbox" ${p.enabled ? "checked" : ""}
         onchange="toggleLocal('${fname}', this.checked)"><i></i></label>
       ${p.update ? `<button class="mk-btn" onclick="doInstall('${enc(p.id)}')"
            title="${p.local_version ? '本地 v' + esc(p.local_version) + ' → ' : ''}商店 v${esc(p.version)}">更新到 v${esc(p.version)}</button>` : ""}
       ${share}
       <button class="mk-btn danger" onclick="doUninstall('${fname}')">卸载</button>`
    : `<button class="mk-btn primary" onclick="doInstall('${enc(p.id)}')">安装</button>`;

  const detail = p.source === "store"
    ? `${esc(p.author)}${p.tags && p.tags.length ? " · " + p.tags.join(" / ") : ""}` +
      `${p.local_version && p.update ? " · 本地 v" + esc(p.local_version) : ""}` +
      `${p.downloads ? " · " + p.downloads + " 次下载" : ""}`
    : `${esc(p.author)}${p.tags && p.tags.length ? " · " + p.tags.join(" / ") : ""}`;

  return `<div class="pl-card ${p.installed ? 'on' : ''}">
    <div class="pl-ico">${p.installed ? "🔌" : "📦"}</div>
    <div class="pl-main">
      <div class="pl-head">
        <span class="pl-name">${esc(p.name)}</span>
        <span class="pl-badge">v${esc(p.version)}</span>
        ${badge}
      </div>
      <div class="pl-desc">${esc(p.desc)}</div>
      <div class="pl-detail">${detail}</div>
    </div>
    <div class="pl-side mk-actions">${btns}</div>
  </div>`;
}

/* ── 上传插件 ────────────────────────────────────────────────
   两条路：
   1) 点「上传插件」→ 交给主程序弹原生选文件框（WebView2 里 <input type=file> 不弹），
      主程序读文件、POST、再回一条 pluginsChanged 让这里刷新；
   2) 直接把 .py 拖进市场页 → 这边用 fetch 传字节，同一套接口。
*/

function pickPlugin() {
  if (window.chrome && window.chrome.webview) {
    setMsg("挑一个 .py …");
    post({ cmd: "pickPlugin" });
    return;
  }
  setMsg("这个界面只能从主程序里打开上传");
}

function onPickFile(input) {                     // 留给浏览器环境兜底
  const f = input.files && input.files[0];
  if (f) uploadPlugin(f);
}

function bindDropOnce() {
  const page = document.getElementById("pluginpage");
  if (!page || page.dataset.dnd === "1") return;
  page.dataset.dnd = "1";
  let depth = 0;
  page.addEventListener("dragover", e => { e.preventDefault(); page.classList.add("dragover"); });
  page.addEventListener("dragenter", e => { e.preventDefault(); depth++; page.classList.add("dragover"); });
  page.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; page.classList.remove("dragover"); } });
  page.addEventListener("drop", e => {
    e.preventDefault();
    depth = 0;
    page.classList.remove("dragover");
    const f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) uploadPlugin(f);
    else setMsg("拖过来的不是文件");
  });
}

function paintUploadBtn() {
  const b = document.querySelector(".mk-overwrite");
  if (b) b.style.display = PENDING ? "" : "none";
}

async function confirmOverwrite() {
  if (PENDING) await uploadPlugin(PENDING, true);
}

async function uploadPlugin(file, force) {
  if (!/\.py$/i.test(file.name)) {
    setMsg(`${file.name} 不是 .py，插件只认单个 .py 文件`);
    return;
  }
  const overwrite = !!force || !!(PENDING && PENDING.name === file.name && force);
  setMsg(`正在上传 ${file.name}…`);
  let okMsg = "";
  try {
    const buf = await file.arrayBuffer();
    const url = PANEL + "/api/plugins/upload?name=" + encodeURIComponent(file.name) +
      (overwrite ? "&overwrite=1" : "");
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/octet-stream" },
      body: buf
    });
    const d = await r.json();
    if (!d.ok) {
      if (d.exists) {
        PENDING = file;                       // 记住它，旁边会多出一个「覆盖」按钮
        setMsg(`已经有 ${d.file} 了 —— 点「覆盖 ${d.file}」才替换`);
        renderMarket();
        return;
      }
      setMsg("上传失败：" + (d.error || "原因不明"));
      return;
    }
    PENDING = null;
    okMsg = `${d.name} 装好了：${d.lines} 行，v${d.version}` +
      (d.overwritten ? "，覆盖了旧文件" : "，已热重载");
  } catch (e) {
    setMsg("上传失败：" + e.message);
    return;
  }
  await openMarket();
  setMsg(okMsg);
}

async function toggleLocal(file, on) {
  try {
    const r = await fetch(PANEL + "/api/plugins/toggle", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: baseName(file), enabled: on })
    });
    const d = await r.json();
    setMsg(d.ok ? `已${on ? "启用" : "停用"}` : "失败：" + d.error);
  } catch (e) { setMsg("失败：" + e.message); }
  await openMarket();
}

async function doInstall(id, kind) {
  // 商店和本地可能有同一个 id：优先用带下载地址的那条，否则点「更新」会变成"没有下载地址"
  const cands = [...(MK.store || []), ...mkAll()];
  const p = cands.find(x => x.id === id && x.url) || cands.find(x => x.id === id);
  if (!p || !p.url) { setMsg("这个插件没有下载地址"); return; }
  if (kind === "data" || p.type === "data") {
    setMsg(`正在装数据包 ${p.name}（${mb(p.size)}，稍等）…`);
  } else {
    setMsg(`正在装 ${p.name}…`);
  }
  let done = "";
  try {
    const r = await fetch(PANEL + "/api/plugins/install", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: p.url, file: p.file,
        type: (kind === "data" || p.type === "data") ? "data" : "plugin",
        id: p.id, target: p.target, version: p.version
      })
    });
    const d = await r.json();
    if (!d.ok) { setMsg("装失败：" + d.error); return; }
    if (d.type === "data") {
      done = `${p.name} 装好了：${d.files} 个文件解压到 ${d.target}/`;
    } else {
      done = p.installed
        ? `${p.name} 已更新到 v${d.version || p.version || ""}`
        : `${p.name} 装好了${p.version ? "（v" + p.version + "）" : ""}`;
    }
  } catch (e) { setMsg("装失败：" + e.message); return; }
  await openMarket(true);
  setMsg(done);
}

/* 把本地插件分享到商店：别人在「商店」里就能装 */
async function doShare(file) {
  const name = baseName(file);
  const overwrite = SHARE_PENDING === name;   // 再点一次 = 覆盖商店里同名那个
  setMsg(`正在把 ${name} 分享到商店…`);
  let done = "";
  try {
    const r = await fetch(PANEL + "/api/plugins/share", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file: name, overwrite: overwrite })
    });
    const d = await r.json();
    if (!d.ok) {
      if (d.exists) {
        SHARE_PENDING = name;
        setMsg(`商店里已经有 ${name} 了 —— 再点一次「分享」就覆盖`);
        return;
      }
      setMsg("分享失败：" + (d.error || "原因不明"));
      return;
    }
    SHARE_PENDING = null;
    done = d.unchanged
      ? `${d.name} 商店里已经是这份了，没重复传`
      : `${d.name} 分享成功，别人在「商店」标签里能装`;
  } catch (e) { setMsg("分享失败：" + e.message); return; }
  await openMarket(true);
  setMsg(done);
}

async function doUninstall(file, kind, target) {
  const isData = kind === "data";
  const name = isData ? String(file) : baseName(file);
  const ask = isData
    ? `确定卸载数据包「${name}」？目录 ${target}/ 会整个挪到 _removed。`
    : `确定卸载 ${name}？会移到 plugins/_removed，不是直接删。`;
  if (!confirm(ask)) return;
  try {
    const r = await fetch(PANEL + "/api/plugins/uninstall", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(isData ? { type: "data", target: target } : { file: name })
    });
    const d = await r.json();
    setMsg(d.ok ? "已卸载" : "失败：" + d.error);
  } catch (e) { setMsg("失败：" + e.message); }
  await openMarket();
}