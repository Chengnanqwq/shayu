# 写一个傻鱼插件

一个插件 = **一个 `.py` 文件**，或者**一个带 `plugin.json` 的目录**。
放进安装目录的 `plugins/` 里，面板「插件市场」点刷新就生效，不用重启、不用改主程序。

---

## 一、最小可用

```python
NAME = "打招呼"
VERSION = "1.0.0"

async def on_message(ctx):
    if ctx["text"].startswith("/你好"):
        await ctx["reply"]("你好呀。")
        return True
    return False
```

三行元数据 + 一个钩子，就能跑。

---

## 二、能挂哪些钩子

| 钩子 | 时机 | 签名 | 返回值 |
|---|---|---|---|
| `on_message` | 收到消息（主流程之前） | `on_message(ctx)` | `True`/非空 → 这条消息算处理完；`str` → 当成回复发出去；`None`/`False` → 交给下一个插件 |
| `on_reply` | **回复发出之前**（QQ 私聊 / 群聊 / 桌面聊天都过） | `on_reply(ans, ctx)` | 返回新字符串 → 用它；其他 → 用原句 |
| `commands` | 面板展示命令表 | `commands()` | `{"/命令": "说明"}`；列表/元组也收 |
| `setup` | 插件加载时一次 | `setup(api)` | 忽略；异常只记 warning |
| `ui_html` / `ui_css` / `ui_js` | 面板启动时 | `ui_xxx()` 返回字符串 | 注入到面板（见第五节） |
| `handle_http` | 请求 `/plug/<插件>/<路径>` | `handle_http(path, query, body)` | `dict`（JSON）/ `str`（文本）/ `(status, payload)` |
| `on_config` | 启动时 | `on_config(cfg)` | 返回新配置 dict（可选） |

**别名**（写错名字也认）：
```
消息入口  on_message / handle / on_msg / handle_message / on_event / run
回复改写  on_reply / rewrite_reply / post_reply
命令表    commands / get_commands / COMMANDS / CMDS
初始化    setup / register / on_load / init
接口      handle_http / on_http / http
```

---

## 三、兼容性（这里最宽松）

### 怎么放都认

```
plugins/天气.py                 平铺
plugins/聊天/天气.py            一层分类目录
plugins/天气/__init__.py        目录式包（可以带资源文件）
plugins/天气/plugin.json        纯界面插件（一行 Python 都不用写）
plugins/天气.py.disabled        禁用，但面板里看得到、能一键启用
plugins/_草稿.py .隐藏.py       自动跳过
plugins/_removed/               卸载区，跳过
```

### 怎么写都认

- **同步 / 异步**都行：`def` 和 `async def` 自动适配
- **签名自动降级**：`fn(ctx)` → `fn(text, ctx)` → `fn(text)` → `fn()` → `fn(**ctx)`
  只有抛 `TypeError` 才降级，插件内部的真实错误不会被吞
- **类式插件**（AstrBot 那种）：

  ```python
  class MyPlugin:
      NAME = "类式插件"
      VERSION = "0.9"
      async def on_message(self, ctx):
          ...
  ```

  有钩子的类会被自动实例化（构造要参数就退回用类，静态方法照样跑）
- **ctx 两种写法**：`ctx["text"]` 与 `ctx.text` 等价，另补了
  `msg / message / content / raw_text`、`reply / send / send_msg`、`user / user_id / uid`
- **元数据缺一半也能用**：`NAME`、`VERSION`、`DESC`、`AUTHOR` 取到哪个算哪个，都没有就用文件名

### 编码

`utf-8-sig → utf-8 → gb18030 → gbk → big5 → latin-1`，全失败才放弃。
非 UTF-8 的插件会先转码到 `plugins/__cache__/`（该目录不会被当成插件）。

### 出错怎么办

- 插件抛异常 → 只影响它自己，记在它的 `error` 里，别的插件照跑
- 缺依赖 → 面板显示「缺依赖: xxx」
- 语法错误 → 面板显示行号
- 单次调用超 20 秒 → 跳过这个插件

---

## 四、给插件的 API（`setup(api)` 里拿）

```python
def setup(api):
    api.log("加载了")

    def tick(a):
        if a.memory_count() > 3000:
            a.notify("记忆快满了")

    api.every(600, tick)          # 每 10 分钟跑一次
```

| 方法 | 说明 |
|---|---|
| `api.cfg(key=None, default=None)` | 读配置（不传 key 返回整个 dict） |
| `api.set_cfg(key, value)` | 写配置 |
| `api.notify(text)` | 给主人推一条消息（走 bot 自己的通道） |
| `api.memory_add(text, kind="fact", imp=0.6, subj="", tags=[])` | 写一条记忆 |
| `api.memory_count()` | 记忆节点数（拿不到返回 -1） |
| `api.every(seconds, fn)` | 注册周期任务，`fn(api)` |
| `api.log(*args)` | 打日志，前缀会带插件名 |

能力拿不到时返回 `None`/`False`，插件自己判空即可。

---

## 五、改界面（应用级插件）

插件不只能改她说什么，也能改**应用长什么样**。

```python
CAPS = ("ui", "http")      # 声明要界面 + 接口权限

def ui_html():
    return '<div class="my-card">记忆：<b id="mc">…</b></div>'

def ui_css():
    return '.my-card{position:fixed;right:16px;bottom:16px;padding:12px;border-radius:12px;' \
           'background:rgba(20,22,38,.9);color:#cfd6ff}'

def ui_js():
    return """
    fetch(shayu.api('/plug/我的插件/stats')).then(r => r.json())
      .then(d => document.getElementById('mc').textContent = d.nodes);
    """

def handle_http(path, query=None, body=b""):
    return 200, {"ok": True, "nodes": 1234}
```

面板启动时会拉 `/api/plugins/ui`，把 CSS 塞进 `<head>`、HTML 塞进 `<body>`、
JS 用 `new Function("shayu", code)` 执行。JS 里能用的只有一个小对象：

```js
shayu.api(path, opts)   // fetch(PANEL + path)
shayu.panel()           // 面板地址
shayu.toast("文字")      // 右下角弹一条
```

> JS 拿不到全局变量，只能用 `shayu` 给的这三个。这是有意的：插件之间别互相污染。

### 纯界面插件（不写 Python）

```
plugins/时钟/
  plugin.json    {"name":"时钟","version":"1.0.0","caps":["ui"],"html":"ui.html","css":"ui.css","js":"ui.js"}
  ui.html
  ui.css
  ui.js
  logo.png       ← 通过 /plug/时钟/logo.png 就能访问
```

没有 `handle_http` 时，`/plug/<插件>/<路径>` 会直接读插件目录里的文件（自动带 content-type）。

---

## 六、四个最小例子

**① 回一句话**
```python
NAME = "打招呼"; VERSION = "1.0.0"
async def on_message(ctx):
    if ctx["text"].startswith("/你好"):
        await ctx["reply"]("你好呀。")
        return True
    return False
```

**② 改她说话的方式**
```python
NAME = "别叫我哦"; VERSION = "1.0.0"
def on_reply(ans, ctx=None):
    return ans.replace("哦。", "嗯。")
```

**③ 自己的接口 + 定时任务**
```python
NAME = "心跳"; VERSION = "1.0.0"
CAPS = ("http", "timer")

def handle_http(path, query=None, body=b""):
    return 200, {"ok": True, "beats": 42}

def setup(api):
    api.every(300, lambda a: a.log("还活着"))
```

**④ 枚举式规则（老写法）**
```python
NAME = "关键词"; VERSION = "1.0.0"
HANDLERS = {
    r"^/天气\s*(.+)$": lambda m, ctx: f"想看 {m.group(1)} 的天气？我查不了实时数据。",
}
def on_message(ctx):
    import re
    for pat, fn in HANDLERS.items():
        m = re.match(pat, ctx["text"])
        if m:
            r = fn(m, ctx)
            return r if isinstance(r, str) else True
    return False
```

---

## 七、投稿到商店

三种方式都不用我给权限：

| 方式 | 适合 | 做法 |
|---|---|---|
| 提 PR | 会 git | fork → `plugins/xxx.py` → 改 `index.json` → PR，CI 自动校验 |
| 填表单 | 不想碰 git | 提 Issue 选「投稿一个插件」，贴代码 |
| 面板分享 | 装了傻鱼 | 填 `store_token` 后点「分享」 |

CI 会检查：只收 `.py`、≤256 KB、文件名合规、`ast.parse` 通过、有 `on_message` 或 `commands`、
`index.json` 每条必须有 `id` 且指向真实文件。

---

## 八、写插件的几条经验

- **别写死路径**：用 `Path(__file__).resolve().parent.parent` 找安装目录
- **别阻塞**：耗时操作放 `asyncio.to_thread`，或干脆用 `api.every` 定时做
- **别崩主流程**：自己的异常自己接住，返回 `False` 让它继续
- **别存密钥**：要 key 就让用户填进配置，插件读 `api.cfg()`
- **卸载友好**：不要往安装目录根写文件，写自己的目录或 `sandbox/`
