# 上传到 GitHub（三种方式，任选一种）

仓库已经整理好：`D:\RVC\FishWin_pub`（4.3 MB，48 个文件，不含视频 / 安装包 / 运行时 / 协议端）。
下面三种方式都能上去，**先看「上传前检查」**。

---

## 上传前检查（30 秒）

```powershell
cd D:\RVC\FishWin_pub
# 1) 确认没有密钥（应无输出）
Get-ChildItem -Recurse -File -Include *.py,*.cs,*.js,*.json,*.ps1,*.md |
  Select-String -Pattern 'sk-[A-Za-z0-9]{10,}|store_token"\s*:\s*"[^"]+|BEGIN [A-Z ]*PRIVATE KEY'
# 2) 确认没有大文件（应都在 3MB 以下）
Get-ChildItem -Recurse -File | Sort-Object Length -Descending | Select-Object -First 5 Name, @{n='MB';e={[math]::Round($_.Length/1MB,2)}}
```

当前这份已经检查过：`config.json` 的 `llm_key` / `store_token` / `tts.api_key` 都是空字符串，
内部运维文档（含服务器地址）已剔除。

---

## 方式 A：装了 Git（推荐，能用命令就用这个）

```powershell
# 1) 装 git（一次就好）
winget install --id Git.Git -e

# 2) 在仓库里初始化并提交
cd D:\RVC\FishWin_pub
git init -b main
git add -A
git -c user.name="ShaYu" -c user.email="you@example.com" commit -m "傻鱼 ShaYu: 本地 QQ AI 伴侣（面板 + 机器人 + 安装器 + 插件商店模板）"

# 3) 看提交了什么（确认没有意外文件）
git show --stat HEAD

# 4) 在 GitHub 网页上新建空仓库（不要勾 README/.gitignore），然后：
git remote add origin https://github.com/<你的名字>/shayu.git
git push -u origin main
```

可以用 SSH 的话把 remote 换成 `git@github.com:<你的名字>/shayu.git`。

---

## 方式 B：没装 Git，用 GitHub 网页上传

1. 打开 https://github.com/new → 仓库名 `shayu` → Public → **不要**勾 README / .gitignore → Create
2. 页面点 **uploading an existing file**
3. 把 `D:\RVC\FishWin_pub` 里的**全部内容**拖进去（文件夹会保留层级）
4. Commit message 写「傻鱼 ShaYu 初始提交」→ Commit changes
5. 之后想改：直接网页编辑，或按方式 A 再接管

> 网页上传单次最多 100 个文件、单文件 25 MB；这份是 48 个文件、最大 2.9 MB，可以直接拖。

---

## 方式 C：GitHub Desktop（图形化，适合长期维护）

1. 装 GitHub Desktop → File → Add local repository → 选 `D:\RVC\FishWin_pub`
2. 它会提示 “create a repository” → 点 Create，Name 填 `shayu`，不要勾 Git LFS
3. 右上角 **Publish repository** → 取消勾选 “Keep this code private” → Publish

---

## 传完之后建议做的三件事

1. **加 Topics**：仓库页右上齿轮 → `qq-bot` `ai-companion` `local-first` `privacy` `python` `csharp` `webview2`
2. **Release（可选）**：如果以后要把 `傻鱼安装包.exe` 放出来，用 Release 附件（单文件上限 2 GB），
   **不要**把安装包提交进仓库
3. **README 里的占位**：如果你要挂自己的下载地址，改 README 的「快速开始」那节；
   不要在 README 里写服务器 IP、QQ 号、任何 token

---

## 常见问题

**Q：`ShaYuSetup/payload_src/runtime/` 和 `snowluma/` 为什么没有？**
A：那是便携 Python 和第三方协议端，加起来 700 MB+，且各有自己的许可证。`.gitignore` 已排除；
需要打包的人自己放进去（README 里有说明）。

**Q：`payload.zip` / `payload.dat` / `dist/` 呢？**
A：构建产物，同样已排除，跑 `build_payload.ps1` 会重新生成。

**Q：为什么要剔除交接文档？**
A：里面是本机运维笔记（服务器地址、ssh key 路径、部署命令），不适合公开。需要的话留在本地即可。

**Q：视频放哪？**
A：视频不进仓库。要发布就上传到 B 站 / 视频号 / 官网，或作为 Release 附件单独给。
