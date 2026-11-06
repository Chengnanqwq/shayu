# 傻鱼 ShaYu

**把 AI 留在你电脑里。** 一个跑在本机的 QQ AI 伴侣：人设、记忆、语音、插件全部在本地，
聊天记录不上云，断网也能跑（模型可换本地部署）。

> 本仓库只包含**软件源码**（桌面面板 + 机器人本体 + 安装器 + 插件商店模板）。
> 宣传视频与演示素材不在仓库里。

## ⬇ 下载安装包

|  |  |
|---|---|
| **[傻鱼安装包 v0.009（114 MB）](https://github.com/Chengnanqwq/shayu/releases/download/v0.009/ShaYu-Setup-v0.009.exe)** | Windows 10 / 11 64 位 · 单文件自包含 · 自带运行时与协议端 |
| [全部版本 / 更新记录](https://github.com/Chengnanqwq/shayu/releases) | 最新版永远在 Releases 里 |
| [使用教程（docx）](docs/傻鱼使用教程.docx) | 从装到用，含每一步截图 |
| [插件商店仓库](https://github.com/Chengnanqwq/shayu-plugins) | 装完在面板里直接能看到 |

> 安装时请选**英文、无空格的路径**（例如 `D:\ShaYu`），约 300 MB；
> 校验：`SHA256 = 0B33573F64F13F28EAC6DE0FA6E4B2362D5F038D9A16C07BED054F1A76BE3FA2`



## 自带插件

| 插件 | 干什么 |
|---|---|
| **去 DS 口癖** | 删掉模型自带的「这句话稳 / 我不接 / 比之前的都重 / 我记着了」这类口头禅，让回复回到她自己的口气 |
| 表情图库 | 收到图自动入库，`/发表情` 随机发，回话时顺手甩图 |
| QQ空间 | 读说说 / 点赞 / 评论 / 看访客 / 发说说 |
| QQ资料 | 改昵称、换头像、看头像列表 |
| 改签名 | 改长签名，每天限 10 次，认自然语言 |
| 插件示例 | 最小可跑示例，照着改就能写自己的 |

插件可以挂四种钩子：`on_message`（收消息）、`commands`（命令表）、**`on_reply`（改写回复）**、
`setup`（加载时初始化）。写法与容错见[插件商店仓库](https://github.com/Chengnanqwq/shayu-plugins)。

---

## 它是什么

傻鱼由三层组成，全部跑在你自己这台电脑上：

| 层 | 是什么 | 干什么 | 位置 |
|---|---|---|---|
| ① QQ 协议端 | SnowLuma（也兼容 NapCat） | 登录 QQ、收发消息，转成 OneBot v11 事件 | `snowluma/`（安装器自带，不入库） |
| ② 机器人本体 | `bot.py` + 便携 Python | 人设、记忆、情绪、调模型、分条回复 | `ShaYuSetup/payload_src/` |
| ③ 主程序面板 | `ShaYu.exe`（C# WinForms + WebView2） | 状态、参数、插件市场、记忆星系 | `ShaYu/` |

一条消息的完整路径：

```
QQ 客户端 → 协议端(:3000) → ws://127.0.0.1:6199 → bot.py → 模型 API → 分条回复 → QQ
```

**关键在最后一段**：除了「bot.py → 模型 API」这一段会发出你这句话的文本，其余全在本机。
聊天记录、人设、记忆、配置都写在安装目录里，删目录 = 删干净。

---

## 功能

- **人设可换**：8 个分段字段（名字 / 身份 / 性格 / 说话方式 / 喜欢讨厌 / 不做的事 / 补充），
  保存即生效；也兼容旧的「整段人设」模式
- **长期记忆**：六类记忆（人物 / 事实 / 约定 / 情绪 / 经历 / 技能）组成一张会衰减、会自整理的关系网，
  存 `brain_memory.json`，可用「记忆星系」可视化浏览
- **语音**：TTS 三种模式（文字描述音色 / 预设音色 / 声音克隆），任意 OpenAI 风格 HTTP 接口
- **翻唱**：本机 RVC 推理（需要 NVIDIA 显卡），一首约 3 分钟
- **插件**：单个 `.py` 即插件，拖进面板即装，热重载，可启用 / 卸载
- **插件商店**：商店就是一个公开 GitHub 仓库（`index.json` + `plugins/*.py`），可读可 PR
- **数据包**：表情库这类大文件以 zip 形式在市场里安装，解压到指定目录
- **卸载干净**：设置页底部一键，删整个安装目录，并清桌面快捷方式

---

## 仓库结构

```
ShaYu/                        主程序（C# WinForms + WebView2）
  MainForm.cs                 窗口、工具栏状态、面板宿主、卸载入口
  AppIcon.cs                  内嵌多尺寸图标
  www/                        面板前端（index / config / plugins / version / setup）
  ShaYu.csproj
ShaYuSetup/                   安装器 + 机器人源码 + 打包脚本
  ShaYuSetup/SetupForm.cs     五步安装向导：环境检验、写配置、解包、快捷方式
  build_payload.ps1           把源码 + 便携 Python + 协议端打成 payload.zip → 单文件安装包
  make_pack.py                把一个目录打成「数据包」并打印市场索引条目
  payload_src/                随包发布的机器人源码
    bot.py                    主循环、消息处理、记忆提炼、面板 HTTP API
    soul.py                   情绪 / 关系 / 作息 / 睡眠
    brain.py                  记忆图谱：节点、衰减、反思、导出
    panel.py / tts.py / plugins_loader.py / growth.py …
    plugins/                  内置插件：表情图库、QQ空间、QQ资料、改签名、示例
    config.json               默认配置（所有密钥留空）
    index.json                自带插件与数据包索引
store_repo_template/          插件商店仓库模板（含 CI 校验 workflow）
docs/傻鱼使用教程.docx          面向用户的使用教程
```

---

## 快速开始（自己编译）

**依赖**：Windows 10/11 64 位、.NET 8+ SDK、Node.js（协议端）、Python 3.10+（打包用）、WebView2 Runtime

1. 编译主程序

   ```powershell
   cd ShaYu
   dotnet build -c Release
   ```

2. 打包机器人 + 安装包（需要先准备好便携 Python 和协议端，脚本里有说明）

   ```powershell
   cd ShaYuSetup
   pwsh -File build_payload.ps1 -SkipBuild        # 只重打 payload
   pwsh -File build_payload.ps1                   # 全量：payload + 单文件安装包
   ```

3. 手工运行（不打包）：把 `payload_src/` 复制到一个目录，装好 `websockets`、`requests`，
   用 `python bot.py` 启动机器人；面板用 `ShaYu.exe` 指向 `http://127.0.0.1:6200`

> 安装器不联网下载任何东西；协议端与便携 Python 由你在打包时放进 `payload_src/`。

---

## 写一个插件

放到 `plugins/` 下一个 `.py` 就行，最小示例：

```python
NAME = "打招呼"
VERSION = "1.0.0"
ENABLED = True

def commands():
    return {"/hello": "回一句你好"}

async def on_message(ctx):
    if ctx["text"].startswith("/hello"):
        await ctx["reply"]("你好呀。")
        return True
    return False
```

规则：

- 必须能被 `ast.parse` 通过，否则面板拒绝写入（免得机器人起不来）
- 文件名只能字母数字下划线横线，别用下划线开头
- 卸载只是移到 `plugins/_removed/`，随时能找回

## 开一个插件商店

`store_repo_template/` 是一个可直接推的仓库骨架：

```
index.json                       插件与数据包的索引
plugins/*.py                     插件本体
.github/workflows/validate.yml   PR 自动校验（.py、大小、命名、语法、是否有 on_message）
```

做法：新建公开仓库（或用模板）→ 改 `index.json` → 在面板「参数设置 → 插件商店」填
`store_repo`（例如 `yourname/shayu-plugins`）→ 市场里就多一个「商店 N」标签。

分享插件需要 token；不想给 token 就提 PR，CI 会校验。

---

## 隐私说明（重要）

- 只有一次外出请求：**bot.py → 你配置的模型 API**（默认 DeepSeek），内容是这一轮的文本片段
- 语音合成（如启用）与模型服务都由你自己提供 key，本仓库不含任何密钥
- 记忆、人设、聊天记录、配置全部在安装目录；`config.json` 里所有密钥默认空
- 仓库里的 `config.json` 是模板，`llm_key` / `store_token` / `tts.api_key` 全为空字符串

---

## 安全提醒

- 协议端（SnowLuma / NapCat）属于第三方项目，请遵守其许可与使用条款
- 用小号跑机器人，不要用主号登录协议端
- 面板默认只监听 `127.0.0.1`，不要把它暴露到公网
- 任何有写权限的 token 都不要写进仓库


## 文档

| 文件 | 内容 |
|---|---|
| [使用教程](docs/傻鱼使用教程.docx) | 从装到用，含每一步截图 |
| [评测报告](docs/评测报告.md) | 66 轮情感 / 道德测试的原始结论与修复对照 |
| [更新记录](CHANGELOG.md) | 每个版本改了什么 |
| [上传说明](UPLOAD.md) | 想自己发一份的话，怎么发 |

---

## 许可

MIT，见 [LICENSE](LICENSE)。

第三方组件（协议端、便携 Python、RVC 等）遵循各自许可，不随本仓库分发。
