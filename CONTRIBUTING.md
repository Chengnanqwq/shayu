# 贡献指南

## 提 Issue 前

1. 先看 `docs/傻鱼使用教程.docx` 和 README 的「隐私说明 / 安全提醒」
2. 机器人起不来时，先看安装目录里的 `logs/bot-YYYY-MM-DD.log`
3. 面板连不上时，检查 `config.json` 里的 `panel_port` 是否和面板实际访问的端口一致

Issue 里请写清：系统版本、安装路径、复现步骤、日志片段（把 key 和 QQ 号打码）。

## 提 PR

- **机器人 / 插件**（Python）：保持无第三方重依赖，只用标准库 + `websockets` + `requests`
- **面板**（C# / 前端）：保持 `ShaYu.csproj` 能单独 `dotnet build`；前端不要引入构建链
- **安装器**：改 `SetupForm.cs` 后请跑一次 `build_payload.ps1`，确认 payload 与安装包都能出
- 不要提交任何密钥、QQ 号、服务器地址、个人路径
- 提交前自查：

  ```powershell
  git diff --cached | Select-String -Pattern 'sk-[A-Za-z0-9]{10,}'
  ```

## 代码风格

- Python：4 空格缩进，函数优先小步、纯函数；错误要打印可读信息，别吞异常
- C#：保持现有 `MainForm.cs` 的分区注释风格；UI 文案中文、标点齐全
- 前端：不引入框架，保持单文件 JS，只在必要时加版本号（`?v=N`）破缓存

## 插件征集

想把自己的插件放进官方商店，可以直接改 `store_repo_template/index.json` 提 PR，
或者单独开一个公开仓库，在面板里填 `store_repo` 指向它。
