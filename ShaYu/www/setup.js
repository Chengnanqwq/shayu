/* 安装向导 + 插件列表（只显示真实存在的） */
let SETUP_STEP = 1;
let FOUND_PLUGINS = [];

function needSetup() {
  // 没走过引导就先进引导（哪怕 panelUrl 有默认值）
  return !SETTINGS || SETTINGS.setupDone !== true;
}

function showSetup() {
  document.getElementById("setup").classList.add("on");
  SETUP_STEP = 1;
  renderSetup();
}

function closeSetup() {
  document.getElementById("setup").classList.remove("on");
  load(true);
}

function renderSetup() {
  const box = document.getElementById("setupBody");
  const dots = [1, 2, 3].map(i =>
    `<span class="sd ${i === SETUP_STEP ? "on" : ""} ${i < SETUP_STEP ? "done" : ""}"></span>`).join("");
  const names = ["连接机器人", "挑功能", "完成"];
  const head = `<div class="setup-head">
      <div class="setup-logo">🐟</div>
      <h2>初次设置</h2>
      <p>${names[SETUP_STEP - 1]}</p>
      <div class="setup-dots">${dots}</div>
    </div>`;

  let body = "";
  if (SETUP_STEP === 1) {
    const url = (SETTINGS && SETTINGS.panelUrl) || "http://127.0.0.1:6200";
    body = `
      <label class="sf-label">机器人面板地址</label>
      <input class="sf-inp" id="setupUrl" value="${esc(url)}"
        placeholder="http://127.0.0.1:6200">
      <div class="sf-hint">装在本机就填 127.0.0.1:6200；装在自己服务器上就填服务器地址。
        <br>不知道填什么？先把 bot 跑起来，它启动时会打印这个地址。</div>
      <div class="sf-row">
        <button class="sf-btn ghost" onclick="testSetup()">测试连接</button>
        <span class="sf-msg" id="setupMsg"></span>
      </div>
      <div class="sf-actions">
        <button class="sf-btn" onclick="setupNext(1)">下一步</button>
      </div>`;
  } else if (SETUP_STEP === 2) {
    body = `
      <div class="sf-hint" style="margin-bottom:14px">
        这些是机器人里<span style="color:#b9aaff">已经装好</span>的能力，不要的可以关掉。
        想装更多去 GitHub 插件仓库下载 .py 丢进 plugins 目录。
      </div>
      <div id="setupPlugins" class="sf-plugins">正在读取…</div>
      <div class="sf-actions">
        <button class="sf-btn ghost" onclick="setupBack(2)">上一步</button>
        <button class="sf-btn" onclick="setupNext(2)">下一步</button>
      </div>`;
  } else {
    body = `
      <div class="sf-done">
        <div class="sf-check">✓</div>
        <h3>可以开始了</h3>
        <p>左侧是她的记忆宇宙，右边那排是她现在的状态。</p>
      </div>
      <div class="sf-actions">
        <button class="sf-btn" onclick="finishSetup()">进入</button>
      </div>`;
  }
  box.innerHTML = head + `<div class="setup-main">${body}</div>`;
  if (SETUP_STEP === 2) loadSetupPlugins();
}

async function testSetup() {
  const url = document.getElementById("setupUrl").value.trim();
  const m = document.getElementById("setupMsg");
  m.textContent = "测试中…";
  m.style.color = "#8b93ad";
  try {
    const r = await fetch(url.replace(/\/$/, "") + "/api/status", { cache: "no-store" });
    if (r.ok) {
      const d = await r.json();
      m.textContent = "连上了 ✔" + (d.llm_model ? "　模型 " + d.llm_model : "");
      m.style.color = "#34d399";
    } else {
      m.textContent = "有响应但状态不对：" + r.status;
      m.style.color = "#fbbf24";
    }
  } catch (e) {
    m.textContent = "连不上，检查地址或确认 bot 在跑";
    m.style.color = "#f87171";
  }
}

function setupNext(step) {
  if (step === 1) {
    const url = document.getElementById("setupUrl").value.trim();
    if (!url) { alert("先填面板地址"); return; }
    if (!SETTINGS) SETTINGS = {};
    SETTINGS.panelUrl = url;
    post({ cmd: "saveSettings", settings: SETTINGS });
    SETUP_STEP = 2;
  } else {
    SETUP_STEP = 3;
  }
  renderSetup();
}

function setupBack(step) {
  SETUP_STEP = Math.max(1, step - 1);
  renderSetup();
}

function finishSetup() {
  if (!SETTINGS.plugins) SETTINGS.plugins = {};
  SETTINGS.setupDone = true;
  post({ cmd: "saveSettings", settings: SETTINGS });
  closeSetup();
}

async function loadSetupPlugins() {
  const box = document.getElementById("setupPlugins");
  const url = (SETTINGS && SETTINGS.panelUrl) || PANEL;
  try {
    const r = await fetch(url.replace(/\/$/, "") + "/api/plugins", { cache: "no-store" });
    const d = await r.json();
    FOUND_PLUGINS = d.plugins || [];
  } catch { FOUND_PLUGINS = []; }

  if (!FOUND_PLUGINS.length) {
    box.innerHTML = `<div class="sf-empty">读不到插件列表，先确认面板地址对不对</div>`;
    return;
  }
  box.innerHTML = FOUND_PLUGINS.map(p => `
    <label class="sf-pl">
      <input type="checkbox" ${p.enabled ? "checked" : ""} data-file="${esc(p.file)}">
      <div>
        <div class="sf-pl-name">${esc(p.name)}</div>
        <div class="sf-pl-cmd">${(p.commands || []).slice(0, 3).join("　") || p.file}</div>
      </div>
    </label>`).join("");
}