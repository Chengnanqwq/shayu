/* 应用版本 + 检查更新
   版本号用 0.002 这种小数目格式（跟代码提交大致对应），比较按浮点。
   当前版本不写死在代码里：build_payload.ps1 会把发货索引里的 app.version 抄进 www/version.json，
   这样"当前版本"和"最新版本"只有一个真源。 */
let APP_VERSION = "0.001";
let APP_LATEST = null;

async function loadLocalVersion() {
  try {
    const r = await fetch("version.json", { cache: "no-store" });
    if (!r.ok) return;
    const d = await r.json();
    if (d && d.version) APP_VERSION = String(d.version);
  } catch { /* 没有 version.json 就用内置兜底值 */ }
}

function cmpVer(a, b) {
  const na = parseFloat(a);
  const nb = parseFloat(b);
  if (isNaN(na) || isNaN(nb)) {
    // 兜底：按字符串段比较（兼容 1.2.3 这种）
    const pa = String(a || "0").split(".").map(Number);
    const pb = String(b || "0").split(".").map(Number);
    for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
      const x = pa[i] || 0, y = pb[i] || 0;
      if (x !== y) return x > y ? 1 : -1;
    }
    return 0;
  }
  if (na > nb + 1e-9) return 1;
  if (na < nb - 1e-9) return -1;
  return 0;
}

function updateBanner() {
  const box = document.getElementById("verBar");
  if (!box) return;
  if (!APP_LATEST) { box.style.display = "none"; return; }
  const newer = cmpVer(APP_LATEST.version, APP_VERSION) > 0;
  box.style.display = "flex";
  if (!newer) {
    box.className = "ver-bar ok";
    box.innerHTML = `<span>已是最新版本 <b>v${APP_VERSION}</b></span>`;
    return;
  }
  box.className = "ver-bar new";
  const url = APP_LATEST.url || "";
  box.innerHTML = `
    <span>有新版本 <b>v${esc(APP_LATEST.version)}</b>
      <i>当前 v${APP_VERSION}</i></span>
    ${APP_LATEST.notes ? `<em>${esc(APP_LATEST.notes)}</em>` : ""}
    ${url ? `<a href="${esc(url)}" target="_blank">去下载</a>` : ""}`;
}

async function checkAppVersion() {
  await loadLocalVersion();
  try {
    const r = await fetch(PANEL + "/api/market", { cache: "no-store" });
    const d = await r.json();
    APP_LATEST = d.app || null;
  } catch { APP_LATEST = null; }
  updateBanner();
}