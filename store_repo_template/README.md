# 傻鱼插件商店（仓库版）

这个仓库就是「插件商店」本身：

- `plugins/*.py` —— 大家分享的插件
- `index.json` —— 索引（面板靠它列出商店里的插件）

## 用这个商店

在傻鱼面板「参数设置 → 其他设置」里填：

| 键 | 填什么 |
|---|---|
| `store_repo` | `你的GitHub名/这个仓库名`，例如 `shayu/shayu-plugins` |
| `store_branch` | `main` |
| `store_path` | `plugins/` |
| `store_token` | 想一键分享才填（见下）；只读不用填 |

填完回到「插件市场」，标签栏会多一个「商店 N」。

## 往商店分享插件（两种方式）

**A. 用傻鱼面板一键分享（推荐）**

1. GitHub → Settings → Developer settings → **Fine-grained personal access tokens** → Generate new token
2. 只勾这个仓库，权限给 **Contents: Read and write**
3. 复制 `github_pat_...`，粘到面板 `store_token`
4. 面板「参数设置 → 其他设置」把 `store_author` 改成你想显示的名字
5. 插件市场里，点已装插件卡片上的「分享」

面板会自动提交 `plugins/xxx.py` 并更新 `index.json`，同名再点一次是覆盖。

**B. 提 Pull Request / 网页上传（谁都能做，不用 token）**

1. 把 `你的插件.py` 放进 `plugins/`
2. 在 `index.json` 的 `plugins` 数组里加一条：

```json
{
  "id": "你的插件文件名去掉.py",
  "name": "显示名",
  "version": "1.0.0",
  "author": "你的名字",
  "desc": "一句话说明",
  "tags": ["工具"],
  "file": "plugins/你的插件.py",
  "size": 1234,
  "path": "plugins/你的插件.py",
  "updated": "2026-11-05"
}
```

3. 提 PR。CI 会替你检查（见下），维护者点合进来就上架了。

## 自动检查

`.github/workflows/validate.yml` 会在每个 PR 上跑，检查：

- 只收 `.py`、单个文件 ≤ 256KB、文件名只能是字母数字下划线横线
- 文件必须能 `ast.parse` 通过
- 必须有 `on_message()` 或 `commands()`
- `index.json` 里每条都得指到真实存在的文件

## 安全提醒

商店里的插件等于**能在你电脑上跑代码**。装之前自己看一眼源码，不认识的别装。
仓库这边只做静态检查，不做沙箱。
