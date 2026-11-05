<#
  打包 payload.zip：机器人代码 + 主程序(app/) + 便携 Python(runtime/)

  用法：
    pwsh -File build_payload.ps1              # 正常打包
    pwsh -File build_payload.ps1 -SkipBuild   # 主程序已经编好了，省一次 dotnet build

  结构（装完之后的目录长这样）：
    <安装目录>/
      bot.py soul.py brain.py ... plugins/ config.json index.json
      runtime/            便携 Python
      app/                主程序 ShaYu.exe + www（面板前端）
      启动.bat  卸载.bat
#>
param(
  [switch]$SkipBuild,
  [switch]$SkipSetup,                               # 安装器已经编好了，只重打 payload
  [string]$PayloadZip,                              # 默认取 runtime_source.zip 当 runtime 来源
  [string]$OutZip = "payload.zip",
  [string]$SnowLumaSrc = "D:\SnowLuma",             # 本机 SnowLuma 装在哪；没有就跳过（包变小）
  [switch]$NoSnowLuma
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here                      # FishWin
$dist = Join-Path $here "ShaYuSetup"                  # 安装器工程目录
$shaYu = Join-Path $root "ShaYu"
$payloadSrc = Join-Path $here "payload_src"
if (-not $PayloadZip) { $PayloadZip = Join-Path $dist "runtime_source.zip" }

function Say($m) { Write-Host "  $m" }

# ── 0. 当前版本号：只有一个真源（payload_src\index.json 的 app.version）──
# 写一份到 www\version.json，前端读它当"当前版本"，免得代码里再写死一个数字
$verFile = Join-Path $shaYu "www\version.json"
try {
  $idxTmp = Get-Content (Join-Path $payloadSrc "index.json") -Raw -Encoding UTF8 | ConvertFrom-Json
  $ver = [string]$idxTmp.app.version
  if ($ver) {
    "{`"version`": `"$ver`"}" | Set-Content $verFile -Encoding UTF8 -NoNewline
    Say "当前版本 $ver（写进 www\version.json）"
  }
} catch { Say "读 index.json 版本号失败，前端会退回内置值" }

# ── 1. 主程序 ────────────────────────────────────────────
if (-not $SkipBuild) {
  Say "编译主程序 …"
  Get-Process ShaYu -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Milliseconds 400
  Push-Location $shaYu
  dotnet build -c Release --nologo -v q
  $buildOk = $LASTEXITCODE -eq 0
  Pop-Location
  if (-not $buildOk) { throw "主程序编译失败" }
}

$appDir = Join-Path $shaYu "bin\Release\net10.0-windows"
if (-not (Test-Path (Join-Path $appDir "ShaYu.exe"))) { throw "找不到 $appDir\ShaYu.exe" }

# www 必须是最新的（以前踩过：改了 css 没同步，跑的是旧文件）
$wwwSrc = Join-Path $shaYu "www"
$wwwOut = Join-Path $appDir "www"
foreach ($f in Get-ChildItem $wwwSrc -File) {
  $d = Join-Path $wwwOut $f.Name
  if (-not (Test-Path $d) -or (Get-FileHash $f.FullName).Hash -ne (Get-FileHash $d).Hash) {
    Copy-Item $f.FullName $d -Force
    Say "同步 www\$($f.Name)"
  }
}

# ── 2. 收集要进 zip 的文件 ───────────────────────────────
# 只收主程序真正要用的东西。win-x64 是以前自包含发布留下的 169MB 垃圾，别打包
$appFiles = @(
  "ShaYu.exe", "ShaYu.dll", "ShaYu.deps.json", "ShaYu.runtimeconfig.json",
  "Microsoft.Web.WebView2.Core.dll", "Microsoft.Web.WebView2.WinForms.dll",
  "WebView2Loader.dll"
)
foreach ($sub in @("runtimes", "www")) {
  $p = Join-Path $appDir $sub
  if (Test-Path $p) { $appFiles += $sub }
}

$stage = Join-Path $env:TEMP ("shayu_payload_" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $stage | Out-Null
$stageApp = Join-Path $stage "app"
New-Item -ItemType Directory -Force -Path $stageApp | Out-Null

foreach ($f in $appFiles) {
  $src = Join-Path $appDir $f
  if (-not (Test-Path $src)) { Say "跳过缺失的 $f"; continue }
  Copy-Item $src $stageApp -Recurse -Force
}
# 主程序不带头一次运行就用的设置（安装器会写自己的）
Remove-Item (Join-Path $stageApp "settings.json") -ErrorAction SilentlyContinue

# ── 3. 打 zip：runtime 从旧包搬，其余重新收 ─────────────
Add-Type -AssemblyName System.IO.Compression.FileSystem
if (-not (Test-Path $PayloadZip)) { throw "找不到 runtime 来源：$PayloadZip" }
$outPath = Join-Path $here $OutZip
if (Test-Path $outPath) {
  $bak = "$outPath.bak-" + (Get-Date -Format "MMdd-HHmmss")
  Move-Item $outPath $bak
  Say "旧包备份 → $(Split-Path -Leaf $bak)"
}

$srcZip = [System.IO.Compression.ZipFile]::OpenRead($PayloadZip)
$zip = [System.IO.Compression.ZipFile]::Open($outPath, "Create")
$runtimeCount = 0
try {
  Say "搬 runtime/ …"
  foreach ($e in $srcZip.Entries) {
    if ($e.FullName -notmatch '^runtime[\\/]') { continue }
    $ne = $zip.CreateEntry($e.FullName, [System.IO.Compression.CompressionLevel]::Optimal)
    $s = $e.Open(); $d = $ne.Open()
    $s.CopyTo($d)
    $d.Dispose(); $s.Dispose()
    $runtimeCount++
  }

  Say "收 payload_src/ …"
  $srcCount = 0
  foreach ($f in Get-ChildItem $payloadSrc -Recurse -File |
                  Where-Object { $_.FullName -notmatch '\\__pycache__\\' -and $_.Extension -ne '.pyc' -and $_.Name -notlike '*.bak*' }) {
    $rel = $f.FullName.Substring($payloadSrc.Length + 1) -replace '\\', '/'
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
      $zip, $f.FullName, $rel, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    $srcCount++
  }

  Say "收 app/ …"
  $appCount = 0
  foreach ($f in Get-ChildItem $stageApp -Recurse -File) {
    $rel = "app/" + ($f.FullName.Substring($stageApp.Length + 1) -replace '\\', '/')
    [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
      $zip, $f.FullName, $rel, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    $appCount++
  }

  # ── SnowLuma（QQ 协议端）：只收程序本体 ────────────────
  # 绝对不能带 app\data、data（里面有每个 QQ 号的聊天库和登录会话）、logs、
  # 也不能带 app\config\onebot_<qq>.json / webui.json（别人的账号和密码）
  $snowCount = 0
  if (-not $NoSnowLuma -and (Test-Path (Join-Path $SnowLumaSrc "app\node.exe"))) {
    Say "收 snowluma/ …"
    $snowApp = Join-Path $SnowLumaSrc "app"
    $snowFiles = @("node.exe", "index.mjs", "package.json", "release.json",
                   "EULA.md", "PRIVACY.md", "check-node-version.cjs", "launcher.bat")
    foreach ($f in $snowFiles) {
      $p = Join-Path $snowApp $f
      if (-not (Test-Path $p)) { continue }
      [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
        $zip, $p, "snowluma/app/$f", [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
      $snowCount++
    }
    foreach ($d in @("client", "native")) {
      $dir = Join-Path $snowApp $d
      if (-not (Test-Path $dir)) { continue }
      foreach ($f in Get-ChildItem $dir -Recurse -File) {
        $rel = "snowluma/app/$d/" + ($f.FullName.Substring($dir.Length + 1) -replace '\\', '/')
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
          $zip, $f.FullName, $rel, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
        $snowCount++
      }
    }
    # 空壳目录：SnowLuma 自己往里写配置、数据和日志
    foreach ($d in @("snowluma/config/", "snowluma/data/", "snowluma/logs/",
                     "snowluma/app/config/", "snowluma/app/data/", "snowluma/app/logs/")) {
      $zip.CreateEntry($d) | Out-Null
    }
  } elseif (-not $NoSnowLuma) {
    Say "没找到 $SnowLumaSrc\app\node.exe，这次不带协议端"
  }
}
finally {
  $zip.Dispose()
  $srcZip.Dispose()
  Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
}

$mb = [math]::Round((Get-Item $outPath).Length / 1MB, 1)
Say "payload.zip = $mb MB（runtime $runtimeCount / 机器人 $srcCount / 主程序 $appCount / 协议端 $snowCount）"

# ── 4. 同步内嵌资源：安装器把 payload.dat 当 EmbeddedResource 编进 dll ──
# 不在这里同步的话，改了 bot 代码重编安装器，嵌进去的还是上一次的包
Copy-Item $outPath (Join-Path $dist "payload.dat") -Force
Say "payload.dat 已同步（安装器内嵌资源）"

if (-not $SkipSetup) {
  Say "编译安装器 …"
  Get-Process ShaYuSetup -ErrorAction SilentlyContinue | Stop-Process -Force
  Start-Sleep -Milliseconds 300
  Push-Location $dist
  dotnet build -c Release --nologo -v q
  $setupOk = $LASTEXITCODE -eq 0
  Pop-Location
  if (-not $setupOk) { throw "安装器编译失败" }
}

$setupBin = Join-Path $dist "bin\Release\net10.0-windows"
New-Item -ItemType Directory -Force -Path $setupBin | Out-Null
Copy-Item $outPath (Join-Path $setupBin "payload.zip") -Force
Say "已放到 $setupBin\payload.zip"

# ── 5. 出可发货的单文件安装包 ────────────────────────────
# 注意：以前试过「exe 尾部追加 zip + 8 字节长度」，.NET apphost 会当成 bundle 直接退出。
# 现在改成自包含单文件发布：payload 走内嵌资源，目标机不用装 .NET。
if (-not $SkipSetup) {
  Say "发布自包含单文件安装包（要一分钟）…"
  $publishDir = Join-Path $root "dist\publish"
  Push-Location $dist
  dotnet publish -c Release -r win-x64 --self-contained true `
    -p:PublishSingleFile=true -p:EnableCompressionInSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true -o $publishDir --nologo -v q
  $pubOk = $LASTEXITCODE -eq 0
  Pop-Location
  if (-not $pubOk) { throw "单文件发布失败" }
  $shipping = Join-Path $publishDir "ShaYuSetup.exe"
  $dest = Join-Path $root "dist\傻鱼安装包.exe"
  Move-Item $shipping $dest -Force   # 别留两份 76MB
  Say ("单文件 {0:N1} MB → dist\傻鱼安装包.exe" -f ((Get-Item $dest).Length / 1MB))
}

Write-Host "完成。" -ForegroundColor Green
