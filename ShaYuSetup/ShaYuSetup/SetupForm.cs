using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO.Compression;
using System.Net.Http;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Windows.Forms;
using Microsoft.Win32;

namespace ShaYuSetup;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        // .NET 5+ 默认不带 GBK，写 .bat 前必须注册，否则 GetEncoding("gbk") 会抛
        Encoding.RegisterProvider(CodePagesEncodingProvider.Instance);
        ApplicationConfiguration.Initialize();
        Application.Run(new SetupForm());
    }
}

/// <summary>内嵌的多尺寸应用图标。</summary>
static class Ico
{
    private static Icon? _cached;
    public static Icon Get
    {
        get
        {
            if (_cached is not null) return _cached;
            try
            {
                using var s = typeof(Ico).Assembly.GetManifestResourceStream("ShaYuSetup.icon.ico");
                if (s is not null) _cached = new Icon(s);
            }
            catch { }
            return _cached ??= SystemIcons.Application;
        }
    }
}

// ── 配色 ───────────────────────────────────────────────
static class C
{
    public static readonly Color Bg = Color.FromArgb(14, 16, 23);
    public static readonly Color Panel = Color.FromArgb(22, 25, 36);
    public static readonly Color Line = Color.FromArgb(38, 43, 60);
    public static readonly Color Text = Color.FromArgb(232, 236, 246);
    public static readonly Color Sub = Color.FromArgb(140, 148, 168);
    public static readonly Color Acc = Color.FromArgb(139, 123, 240);
    public static readonly Color Ok = Color.FromArgb(52, 211, 153);
    public static readonly Color Bad = Color.FromArgb(248, 113, 113);
    public static readonly Color Warn = Color.FromArgb(251, 191, 36);
    public static readonly Font FontBase = new("Microsoft YaHei UI", 9.5f);
    public static readonly Font FontTitle = new("Microsoft YaHei UI", 16f, FontStyle.Bold);
    public static readonly Font FontSmall = new("Microsoft YaHei UI", 8.5f);
}

class SetupForm : Form
{
    // 调试用：set SHAYU_STEP=4 直接从第 4 步开始；set SHAYU_TARGET=D:\xxx 换安装目录
    private int _step = int.TryParse(Environment.GetEnvironmentVariable("SHAYU_STEP"), out var _s)
        ? Math.Clamp(_s, 1, 5) : 1;
    private readonly Panel _host = new();
    private readonly Label _stepLabel = new();

    public string TargetDir = Environment.GetEnvironmentVariable("SHAYU_TARGET") is { Length: > 3 } _t
        ? _t : @"D:\ShaYu";
    public string SelfQq = "123456789", MasterQq = "987654321", LlmKey = "sk-test123";
    /// <summary>面板端口：环境检验时探到的空闲口，装完写进 config.json 和 app\settings.json。</summary>
    public int PanelPort = 6200;
    /// <summary>机器人反向 WS 端口：协议端（SnowLuma）要连的那个，两边必须一致。</summary>
    public int WsPort = 6199;

    public SetupForm()
    {
        Text = "傻鱼 · 安装";
        Size = new Size(820, 640);
        MinimumSize = new Size(760, 600);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = C.Bg;
        ForeColor = C.Text;
        Font = C.FontBase;
        Icon = Ico.Get;
        DoubleBuffered = true;

        var head = new Panel { Dock = DockStyle.Top, Height = 72, BackColor = C.Bg };
        head.Controls.Add(new Label
        {
            Text = "🐟  傻鱼 · 安装向导",
            Font = new Font("Microsoft YaHei UI", 13f, FontStyle.Bold),
            ForeColor = C.Text, Location = new Point(28, 16), AutoSize = true
        });
        _stepLabel.Text = "第 1 / 5 步";
        _stepLabel.Font = C.FontSmall;
        _stepLabel.ForeColor = C.Sub;
        _stepLabel.Location = new Point(30, 46);
        _stepLabel.AutoSize = true;
        head.Controls.Add(_stepLabel);
        Controls.Add(head);

        _host.Dock = DockStyle.Fill;
        _host.Padding = new Padding(28, 6, 28, 20);
        Controls.Add(_host);
        _host.BringToFront();

        Render();
    }

    // ── 步骤渲染 ────────────────────────────────────────
    private void Render()
    {
        _host.Controls.Clear();
        _stepLabel.Text = $"第 {_step} / 5 步";
        switch (_step)
        {
            case 1: Step1(); break;
            case 2: Step2(); break;
            case 3: Step3(); break;
            case 4: Step4(); break;
            case 5: Step5(); break;
        }
    }

    private Panel Card(string title, string subtitle)
    {
        var card = new Panel { Dock = DockStyle.Fill, BackColor = C.Panel, Padding = new Padding(26, 22, 26, 22) };
        // Dock.Top 是后加的排在上面，所以先副标题再标题
        card.Controls.Add(new Label
        {
            Text = subtitle, Font = C.FontBase, ForeColor = C.Sub,
            Dock = DockStyle.Top, Height = 24, AutoSize = false,
            Padding = new Padding(0, 0, 0, 6)
        });
        card.Controls.Add(new Label
        {
            Text = title, Font = new Font("Microsoft YaHei UI", 15f, FontStyle.Bold),
            ForeColor = C.Text, Dock = DockStyle.Top, Height = 32, AutoSize = false
        });
        _host.Controls.Add(card);
        return card;
    }

    private static Label Lbl(string t, Font f, Color c, int x, int y, int w = 0)
    {
        var l = new Label { Text = t, Font = f, ForeColor = c, Location = new Point(x, y) };
        if (w > 0) { l.AutoSize = false; l.Width = w; }
        else { l.AutoSize = true; l.MaximumSize = new Size(660, 0); }   // 限宽自动换行，别撑出滚动条
        return l;
    }

    private void Step1()
    {
        var card = Card("选个安装位置", "装好之后这个目录里会有 运行时、机器人代码、配置");
        var p = new Panel { Dock = DockStyle.Fill };
        card.Controls.Add(p);
        p.BringToFront();

        p.Controls.Add(Lbl("安装到哪", C.FontSmall, C.Sub, 0, 0));
        var box = new TextBox
        {
            Text = TargetDir, Location = new Point(0, 22), Width = 640,
            BackColor = Color.FromArgb(30, 34, 48), ForeColor = C.Text, BorderStyle = BorderStyle.FixedSingle,
            Font = new Font("Consolas", 10.5f)
        };
        p.Controls.Add(box);
        var tip = Lbl("只能用英文和数字，别放中文路径或带空格的目录", C.FontSmall, C.Sub, 0, 56);
        p.Controls.Add(tip);
        var err = Lbl("", C.FontSmall, C.Bad, 0, 78);
        p.Controls.Add(err);

        var next = MakeButton("下一步", true, 640 - 108, 0);
        p.Controls.Add(next);
        next.Click += (_, _) =>
        {
            var d = box.Text.Trim().TrimEnd('\\', '/');
            var e = CheckDir(d);
            if (e != null) { err.Text = e; return; }
            TargetDir = d;
            _step = 2; Render();
        };
        // 按钮放右下
        p.Resize += (_, _) => next.Location = new Point(p.Width - 108, p.Height - 40);
        next.Location = new Point(p.Width - 108, p.Height - 40);
    }

    private static string? CheckDir(string d)
    {
        if (string.IsNullOrWhiteSpace(d)) return "先填一个位置，比如 D:\\ShaYu";
        if (d.Any(ch => ch > 127)) return "路径里不要有中文";
        if (d.Contains(' ')) return "路径里不要有空格";
        if (d.Length < 4 || d[1] != ':') return "要写完整路径，比如 D:\\ShaYu";
        var drive = d[..3];
        if (!Directory.Exists(drive)) return $"{drive} 这个盘不存在";
        try
        {
            var free = new DriveInfo(drive).AvailableFreeSpace / 1024.0 / 1024 / 1024;
            if (free < 3) return $"{drive} 只剩 {free:F1}G，至少要 3G";
        }
        catch (Exception e) { return "读不到磁盘信息：" + e.Message; }
        if (Directory.Exists(d))
        {
            var items = Directory.GetFileSystemEntries(d);
            if (items.Length > 0 && !File.Exists(Path.Combine(d, "bot.py")))
                return "这个文件夹里已经有别的东西了，换个空的";
        }
        try
        {
            Directory.CreateDirectory(d);
            var probe = Path.Combine(d, ".w");
            File.WriteAllText(probe, "x"); File.Delete(probe);
        }
        catch (Exception e) { return "写不进去（试试管理员运行）：" + e.Message; }
        return null;
    }

    private Button MakeButton(string text, bool primary, int x, int y)
    {
        var b = new Button
        {
            Text = text, Location = new Point(x, y), Size = new Size(108, 36),
            FlatStyle = FlatStyle.Flat, Font = new Font("Microsoft YaHei UI", 9.5f, FontStyle.Bold),
            BackColor = primary ? C.Acc : C.Panel, ForeColor = primary ? Color.White : C.Sub,
            Cursor = Cursors.Hand
        };
        b.FlatAppearance.BorderSize = primary ? 0 : 1;
        b.FlatAppearance.BorderColor = C.Line;
        return b;
    }

    private void Step2()
    {
        var card = Card("先检查一下环境", "标红的要处理，标黄的可以装完再说");
        var list = new Panel { Dock = DockStyle.Fill, AutoScroll = true };
        card.Controls.Add(list);
        list.BringToFront();

        int y = 0;
        void Add(string name, bool ok, string msg)
        {
            var row = new Panel { Location = new Point(0, y), Size = new Size(700, 46) };
            row.Controls.Add(new Label
            {
                Text = ok ? "✓" : "!",
                Font = new Font("Microsoft YaHei UI", 11f, FontStyle.Bold),
                ForeColor = ok ? C.Ok : C.Bad, Location = new Point(0, 10), AutoSize = true
            });
            row.Controls.Add(Lbl(name, C.FontBase, C.Text, 24, 4));
            row.Controls.Add(Lbl(msg, C.FontSmall, ok ? C.Sub : C.Bad, 24, 24));
            list.Controls.Add(row);
            y += 50;
        }

        var free = new DriveInfo(TargetDir[..3]).AvailableFreeSpace / 1024.0 / 1024 / 1024;
        Add("安装位置", true, $"{TargetDir}（{free:F1}G 可用）");

        Add("安装包", PayloadAvailable(),
            PayloadAvailable() ? "内置运行时和机器人代码就绪" : "安装包不完整，重新下载");

        var wv = WebView2Version();
        Add("面板组件", string.IsNullOrEmpty(wv),
            string.IsNullOrEmpty(wv)
                ? "缺 WebView2 运行库，面板起不来 —— 装一下「Evergreen Runtime」再继续"
                : $"WebView2 运行库 {wv}");

        var snowBundled = PayloadHasProtocolEnd();
        Add("QQ 协议端", snowBundled,
            snowBundled
                ? "安装包里自带 SnowLuma，装完直接扫码，不用另外下载"
                : "这次装的是精简包，协议端要自己装（SnowLuma / NapCat 都行）");

        var port = 6200;
        while (port < 6240 && !PortFree(port)) port++;
        PanelPort = port;
        Add("面板端口", port < 6240, port < 6240 ? $"用 {port}" : "6200 往后全被占了");

        var ws = 6199;
        while (ws < 6240 && !PortFree(ws)) ws++;
        WsPort = ws;
        Add("协议端端口", ws < 6240,
            ws < 6240
                ? (PortFree(3000)
                    ? $"机器人等协议端连 {ws}；3000 留给协议端对外接口"
                    : "3000 有别的程序在跑，协议端可能起不来")
                : "6199 往后全被占了");

        Add("API key", false, "下一步填");

        var next = MakeButton("下一步", true, 0, 0);
        card.Controls.Add(next);
        next.BringToFront();
        next.Click += (_, _) => { _step = 3; Render(); };
        card.Resize += (_, _) => next.Location = new Point(card.Width - 134, card.Height - 58);
        next.Location = new Point(card.Width - 134, card.Height - 58);
    }

    private static bool PortFree(int port)
    {
        try
        {
            using var s = new TcpClient();
            return !(s.ConnectAsync("127.0.0.1", port).Wait(300) && s.Connected);
        }
        catch { return true; }
    }

    /// <summary>WebView2 运行库版本号；没装返回空串。主程序的面板全靠它。</summary>
    private static string WebView2Version()
    {
        const string guid = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}";
        string[] paths =
        {
            @"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\" + guid,
            @"SOFTWARE\Microsoft\EdgeUpdate\Clients\" + guid,
        };
        foreach (var root in new[] { Registry.LocalMachine, Registry.CurrentUser })
        {
            foreach (var p in paths)
            {
                try
                {
                    using var k = root.OpenSubKey(p);
                    var v = k?.GetValue("pv") as string;
                    if (!string.IsNullOrWhiteSpace(v) && v != "0.0.0.0") return v;
                }
                catch { }
            }
        }
        return "";
    }

    /// <summary>payload 里有没有内置的 QQ 协议端（SnowLuma）。</summary>
    private static bool PayloadHasProtocolEnd()
    {
        try
        {
            using var s = OpenPayload();
            using var z = new ZipArchive(s, ZipArchiveMode.Read);
            return z.Entries.Any(e => e.FullName.Replace('\\', '/') == "snowluma/app/node.exe");
        }
        catch { return false; }
    }

    /// <summary>payload 是否拿得到：exe 尾部追加的 zip，或者同目录的 payload.zip。</summary>
    private static bool PayloadAvailable()
    {
        try
        {
            var exe = Environment.ProcessPath;
            if (exe is not null)
            {
                using var fs = File.OpenRead(exe);
                if (fs.Length > 8)
                {
                    fs.Seek(-8, SeekOrigin.End);
                    var buf = new byte[8];
                    fs.ReadExactly(buf);
                    var len = BitConverter.ToInt64(buf);
                    if (len > 1000 && len < fs.Length - 8) return true;
                }
            }
        }
        catch { }
        return File.Exists(Path.Combine(AppContext.BaseDirectory, "payload.zip"));
    }

    private void Step3()
    {
        var card = Card("填三个东西", "前两个必填，key 可以等一下填");
        var p = new Panel { Dock = DockStyle.Fill, AutoScroll = true };
        card.Controls.Add(p);
        p.BringToFront();

        int y = 0;
        TextBox AddField(string label, string hint, string val, bool secret = false)
        {
            p.Controls.Add(Lbl(label, C.FontSmall, C.Sub, 0, y));
            y += 20;
            var t = new TextBox
            {
                Text = val, Location = new Point(0, y), Width = 420,
                BackColor = Color.FromArgb(30, 34, 48), ForeColor = C.Text,
                BorderStyle = BorderStyle.FixedSingle, Font = new Font("Consolas", 10f),
                UseSystemPasswordChar = secret
            };
            p.Controls.Add(t);
            y += 28;
            p.Controls.Add(Lbl(hint, C.FontSmall, Color.FromArgb(110, 118, 138), 0, y));
            y += 26;
            return t;
        }

        var self = AddField("机器人 QQ（小号）", "用登着机器人的那个号，不要用大号", SelfQq);
        var master = AddField("你自己 QQ（主人）", "她只听这个号的话，填你的大号", MasterQq);
        var key = AddField("DeepSeek key", "sk- 开头，没有就照下面四步申请，两分钟", LlmKey);

        // ── 申请 key 的分步说明 ──────────────────────────────
        p.Controls.Add(Lbl("key 怎么弄（第一次装才需要）", C.FontSmall, C.Warn, 0, y + 4));
        y += 26;

        var steps = new[]
        {
            "打开 platform.deepseek.com，用手机号注册或登录",
            "左边点「充值」，充 10 块就够聊很久（不充就没法调接口）",
            "左边点「API keys」→「创建 API key」，起个名字比如 shayu",
            "复制弹出的 sk- 开头那串，粘到上面的框里（只显示一次，别关窗口）",
        };
        for (int i = 0; i < steps.Length; i++)
        {
            var no = new Label
            {
                Text = (i + 1).ToString(), Font = new Font("Microsoft YaHei UI", 8f, FontStyle.Bold),
                ForeColor = Color.White, BackColor = C.Acc, TextAlign = ContentAlignment.MiddleCenter,
                Location = new Point(0, y), Size = new Size(17, 17)
            };
            p.Controls.Add(no);
            var t = Lbl(steps[i], C.FontSmall, Color.FromArgb(176, 184, 206), 26, y, 600);
            p.Controls.Add(t);
            y += 26;
        }

        var open = MakeButton("去申请页", false, 0, 0);
        open.Size = new Size(96, 30);
        open.Font = new Font("Microsoft YaHei UI", 9f, FontStyle.Bold);
        open.Location = new Point(26, y + 2);
        open.Click += (_, _) =>
        {
            try { Process.Start(new ProcessStartInfo("https://platform.deepseek.com/api_keys") { UseShellExecute = true }); }
            catch { }
        };
        p.Controls.Add(open);
        y += 40;
        p.Controls.Add(Lbl("填错了不要紧：装完在面板「参数设置 → 模型与密钥」里改，保存就生效",
            C.FontSmall, Color.FromArgb(110, 118, 138), 0, y, 620));

        var back = MakeButton("上一步", false, 0, 0);
        var next = MakeButton("下一步", true, 0, 0);
        card.Controls.Add(back); card.Controls.Add(next);
        back.BringToFront(); next.BringToFront();
        back.Click += (_, _) => { _step = 2; Render(); };
        next.Click += (_, _) =>
        {
            if (!self.Text.Trim().All(char.IsDigit) || self.Text.Trim().Length < 5)
            { MessageBox.Show("机器人 QQ 要填纯数字"); return; }
            if (!master.Text.Trim().All(char.IsDigit) || master.Text.Trim().Length < 5)
            { MessageBox.Show("主人 QQ 要填纯数字"); return; }
            SelfQq = self.Text.Trim(); MasterQq = master.Text.Trim(); LlmKey = key.Text.Trim();
            _step = 4; Render();
        };
        void Layout()
        {
            back.Location = new Point(card.Width - 250, card.Height - 58);
            next.Location = new Point(card.Width - 134, card.Height - 58);
        }
        card.Resize += (_, _) => Layout();
        Layout();
    }

    private void Step4()
    {
        var card = Card("正在安装", "把文件铺到目标目录");
        var bar = new ProgressBar
        {
            Location = new Point(0, 60), Size = new Size(680, 12),
            Style = ProgressBarStyle.Continuous, Maximum = 100
        };
        var msg = Lbl("准备中…", C.FontSmall, C.Sub, 0, 82);
        card.Controls.Add(bar); card.Controls.Add(msg);
        bar.BringToFront(); msg.BringToFront();

        var done = MakeButton("完成", true, 0, 0);
        done.Enabled = false;
        card.Controls.Add(done);
        done.BringToFront();
        done.Click += (_, _) => { _step = 5; Render(); };
        card.Resize += (_, _) => done.Location = new Point(card.Width - 134, card.Height - 58);
        done.Location = new Point(card.Width - 134, card.Height - 58);

        Task.Run(() =>
        {
            try
            {
                void Set(int pct, string t) => BeginInvoke(() => { bar.Value = Math.Min(100, pct); msg.Text = t; });
                DoInstall(Set);
                BeginInvoke(() => { done.Enabled = true; done.Text = "装好了"; });
            }
            catch (Exception e)
            {
                BeginInvoke(() => msg.Text = "失败：" + e.Message);
            }
        });
    }

    private void DoInstall(Action<int, string> set)
    {
        Directory.CreateDirectory(TargetDir);

        // payload 追加在本 exe 的末尾（最后 8 字节是它的长度），没有就用同目录的 payload.zip
        set(6, "解包安装包…");
        var tmp = Path.Combine(Path.GetTempPath(), "shayu_payload_" + Guid.NewGuid().ToString("N") + ".zip");
        using (var res = OpenPayload())
        using (var fs = File.Create(tmp))
        {
            res.CopyTo(fs);
        }

        {
            set(10, "解压到 " + TargetDir);
            using var zip = ZipFile.OpenRead(tmp);
            int total = zip.Entries.Count, done = 0;
            foreach (var e in zip.Entries)
            {
                done++;
                if (done % 40 == 0)
                    set(10 + (int)(62.0 * done / Math.Max(1, total)), $"解压 {done}/{total}");
                var dest = Path.Combine(TargetDir, e.FullName.Replace('/', Path.DirectorySeparatorChar));
                if (string.IsNullOrEmpty(e.Name)) { Directory.CreateDirectory(dest); continue; }
                Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
                e.ExtractToFile(dest, true);
            }
            try { File.Delete(tmp); } catch { }
        }

        set(76, "写机器人配置…");
        // 端口被占了就往后挪：保证 config.json 和 app\settings.json 说的是同一个口
        while (PanelPort < 6240 && !PortFree(PanelPort)) PanelPort++;
        // 协议端要连的反向 WS 口，也得是空的，而且两边写一致
        while (WsPort < 6240 && !PortFree(WsPort)) WsPort++;
        WriteBotConfig();

        set(80, "写协议端配置…");
        WriteProtocolConfig();

        set(82, "写主程序设置…");
        WriteAppSettings();

        set(88, "写启动脚本…");
        WriteLauncher();

        set(93, "写卸载脚本…");
        WriteUninstaller();

        set(97, "建快捷方式…");
        MakeShortcuts();

        set(100, "完成");
    }

    /// <summary>bot 的 config.json：三个信息 + 面板端口。必须不带 BOM。</summary>
    private void WriteBotConfig()
    {
        var cfgPath = Path.Combine(TargetDir, "config.json");
        var cfg = File.Exists(cfgPath)
            ? JsonSerializer.Deserialize<Dictionary<string, object>>(File.ReadAllText(cfgPath)) ?? new()
            : new();
        cfg["self_qq"] = SelfQq;
        cfg["master_qq"] = MasterQq;
        if (!string.IsNullOrWhiteSpace(LlmKey)) cfg["llm_key"] = LlmKey;
        cfg["panel_port"] = PanelPort;          // 环境检验时探到的空闲口
        cfg["ws_port"] = WsPort;
        cfg["ws_url"] = $"ws://127.0.0.1:{WsPort}/ws";
        // 必须不带 BOM：bot.py 的 json 解析不认 BOM（会退回默认配置）
        File.WriteAllText(cfgPath, JsonSerializer.Serialize(cfg,
            new JsonSerializerOptions { WriteIndented = true }),
            new UTF8Encoding(false));
    }

    /// <summary>
    /// SnowLuma（QQ 协议端）的初始配置：
    /// 让它作为客户端去连机器人开的反向 WS，端口跟 config.json 的 ws_port 一致。
    /// 已经装过（用户自己改过）就不覆盖。
    /// </summary>
    private void WriteProtocolConfig()
    {
        var appDir = Path.Combine(TargetDir, "snowluma", "app");
        if (!Directory.Exists(appDir)) return;                 // 这次没带协议端
        var cfgDir = Path.Combine(appDir, "config");
        Directory.CreateDirectory(cfgDir);

        var onebotPath = Path.Combine(cfgDir, "onebot.json");
        if (!File.Exists(onebotPath))
        {
            var onebot = new Dictionary<string, object>
            {
                ["networks"] = new Dictionary<string, object>
                {
                    ["httpServers"] = new object[]
                    {
                        new Dictionary<string, object>
                        {
                            ["name"] = "http-default", ["enabled"] = true,
                            ["host"] = "127.0.0.1", ["port"] = 3000, ["path"] = "/",
                            ["accessToken"] = "", ["messageFormat"] = "array",
                            ["reportSelfMessage"] = false,
                        }
                    },
                    ["httpClients"] = Array.Empty<object>(),
                    ["wsServers"] = Array.Empty<object>(),
                    ["wsClients"] = new object[]
                    {
                        new Dictionary<string, object>
                        {
                            ["name"] = "ws-shayu", ["url"] = $"ws://127.0.0.1:{WsPort}/ws",
                            ["role"] = "Universal", ["messageFormat"] = "array",
                            ["accessToken"] = "", ["reconnectIntervalMs"] = 3000,
                        }
                    },
                },
                ["musicSignUrl"] = "",
            };
            File.WriteAllText(onebotPath,
                JsonSerializer.Serialize(onebot, new JsonSerializerOptions { WriteIndented = true }),
                new UTF8Encoding(false));
        }

        var runtimePath = Path.Combine(cfgDir, "runtime.json");
        if (!File.Exists(runtimePath))
        {
            // 管理页只给本机看，端口固定 5099（主程序顶栏点「SnowLuma」就开这个）
            var runtime = new Dictionary<string, object>
            {
                ["webuiPort"] = 5099, ["webuiHost"] = "127.0.0.1", ["hookAutoLoad"] = true,
                ["webuiTls"] = new Dictionary<string, object> { ["enabled"] = false },
                ["logMaxTotalMb"] = 128, ["logRetainDays"] = 7, ["logPerUin"] = false,
            };
            File.WriteAllText(runtimePath,
                JsonSerializer.Serialize(runtime, new JsonSerializerOptions { WriteIndented = true }),
                new UTF8Encoding(false));
        }
    }

    /// <summary>主程序的 settings.json：面板地址要跟 config.json 的 panel_port 一致。</summary>
    private void WriteAppSettings()
    {
        var appDir = Path.Combine(TargetDir, "app");
        if (!Directory.Exists(appDir)) return;
        var snowDir = Path.Combine(TargetDir, "snowluma");
        var hasSnow = File.Exists(Path.Combine(snowDir, "app", "node.exe"));
        var s = new Dictionary<string, object>
        {
            ["panelUrl"] = $"http://127.0.0.1:{PanelPort}",
            ["localPanelUrl"] = $"http://127.0.0.1:{PanelPort + 1}",
            ["singPort"] = 7100,
            ["snowPort"] = 3000,
            ["tunnelPort"] = 16199,
            ["rvcDir"] = "",
            ["snowLumaDir"] = hasSnow ? snowDir : "",
            ["snowLumaExe"] = hasSnow ? Path.Combine(snowDir, "app", "node.exe") : "",
            ["singStartScript"] = "", ["sepPython"] = "", ["singServerPy"] = "",
            ["tunnelScript"] = "", ["sshUser"] = "root", ["sshHost"] = "", ["sshKey"] = "",
            ["serviceName"] = "fishbot",
            ["setupDone"] = true,
            ["ttsKey"] = "",
            ["plugins"] = new Dictionary<string, bool> { ["remote"] = false, ["rvc"] = false },
        };
        File.WriteAllText(Path.Combine(appDir, "settings.json"),
            JsonSerializer.Serialize(s, new JsonSerializerOptions { WriteIndented = true }),
            new UTF8Encoding(false));
    }

    /// <summary>
    /// 启动.bat：协议端 → 机器人 → 面板。纯 ASCII，避免 GBK 乱码。
    /// 协议端（SnowLuma）已经在自己跑就跳过；它第一次要扫码，所以只负责拉起来。
    /// </summary>
    private void WriteLauncher()
    {
        var py = Path.Combine(TargetDir, "runtime", "pythonw.exe");
        var app = Path.Combine(TargetDir, "app", "ShaYu.exe");
        var snowNode = Path.Combine(TargetDir, "snowluma", "app", "node.exe");
        var snowDir = Path.Combine(TargetDir, "snowluma", "app");
        var hasSnow = File.Exists(snowNode);
        var probePanel = $"try{{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',{PanelPort});$c.Close();exit 0}}catch{{exit 1}}";
        var probeSnow = "try{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',3000);$c.Close();exit 0}catch{exit 1}";

        var body =
            "@echo off\r\n" +
            "setlocal\r\n" +
            $"cd /d \"{TargetDir}\"\r\n" +
            "rem ---- 1) QQ protocol side (SnowLuma) ----\r\n";
        if (hasSnow)
        {
            body +=
                $"powershell -NoProfile -WindowStyle Hidden -Command \"{probeSnow}\"\r\n" +
                "if errorlevel 1 (\r\n" +
                $"  start \"SnowLuma\" /D \"{snowDir}\" \"{snowNode}\" index.mjs\r\n" +
                ")\r\n";
        }
        body +=
            "rem ---- 2) bot: skip if the panel port is already listening ----\r\n" +
            $"powershell -NoProfile -WindowStyle Hidden -Command \"{probePanel}\"\r\n" +
            "if errorlevel 1 (\r\n" +
            $"  start \"\" \"{py}\" bot.py\r\n" +
            ")\r\n" +
            "rem ---- 3) wait for the panel, up to 30s ----\r\n" +
            $"powershell -NoProfile -WindowStyle Hidden -Command \"for($i=0;$i -lt 60;$i++){{try{{$c=New-Object Net.Sockets.TcpClient;$c.Connect('127.0.0.1',{PanelPort});$c.Close();exit 0}}catch{{Start-Sleep -Milliseconds 500}}}}\"\r\n" +
            "rem ---- 4) UI ----\r\n" +
            $"start \"\" \"{app}\"\r\n" +
            "endlocal\r\n";
        WriteBat(Path.Combine(TargetDir, "启动.bat"), body);
    }

    /// <summary>卸载.bat：先把自己复制到 TEMP 再执行，否则删不掉自己所在的目录。</summary>
    private void WriteUninstaller()
    {
        // 按「可执行文件路径在安装目录下」来杀，比按命令行匹配稳：
        // python.exe/pythonw.exe/node.exe/ShaYu.exe 一次全清，用户怎么启动的都能收掉。
        var killPs =
            "Get-CimInstance Win32_Process | Where-Object { " +
            "($_.ExecutablePath -and $_.ExecutablePath.ToLower().StartsWith('" + TargetDir.ToLower().Replace("'", "''") + "')) " +
            "-or ($_.CommandLine -and $_.CommandLine -like '*" + TargetDir + "*bot.py*') " +
            "} | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }";

        var body =
            "@echo off\r\n" +
            "setlocal\r\n" +
            "if /i \"%~1\"==\"--go\" goto go\r\n" +
            $"echo 这会删掉 {TargetDir} 里的全部东西，记忆和配置也一起没。\r\n" +
            "echo.\r\n" +
            "set /p yn=确定卸载吗？输入 y 回车：\r\n" +
            "if /i not \"%yn%\"==\"y\" exit /b\r\n" +
            "copy /y \"%~f0\" \"%TEMP%\\shayu_uninstall.bat\" >nul\r\n" +
            "start \"\" \"%TEMP%\\shayu_uninstall.bat\" --go\r\n" +
            "exit /b\r\n" +
            ":go\r\n" +
            "cd /d \"%TEMP%\"\r\n" +
            "taskkill /IM ShaYu.exe /F >nul 2>&1\r\n" +
            "powershell -NoProfile -WindowStyle Hidden -Command \"" + killPs + "\"\r\n" +
            "rem 桌面可能被 OneDrive 重定向，按「快捷方式指向本目录」来删，别写死路径\r\n" +
            "powershell -NoProfile -WindowStyle Hidden -Command \"$sh=New-Object -ComObject WScript.Shell;Get-ChildItem ([Environment]::GetFolderPath('Desktop')) -Filter *.lnk | Where-Object { $sh.CreateShortcut($_.FullName).TargetPath -like '*" + TargetDir + "*' } | Remove-Item -Force\"\r\n" +
            "set n=0\r\n" +
            ":retry\r\n" +
            $"rmdir /s /q \"{TargetDir}\"\r\n" +
            $"if not exist \"{TargetDir}\" goto done\r\n" +
            "set /a n+=1\r\n" +
            "if %n% GEQ 6 goto giveup\r\n" +
            "timeout /t 2 /nobreak >nul\r\n" +
            "goto retry\r\n" +
            ":giveup\r\n" +
            "echo.\r\n" +
            "echo 有文件被占用，没删干净。\r\n" +
            $"echo 把面板和协议端都退出后再运行这个脚本，或者手动删 {TargetDir}\r\n" +
            "pause\r\n" +
            "exit\r\n" +
            ":done\r\n" +
            "exit\r\n";
        WriteBat(Path.Combine(TargetDir, "卸载.bat"), body);
    }

    private static void WriteBat(string path, string body)
    {
        Encoding enc;
        try { enc = Encoding.GetEncoding("gbk"); }
        catch { enc = new UTF8Encoding(true); }      // 兜底：GBK 拿不到就用 UTF-8 BOM
        File.WriteAllText(path, body, enc);
    }

    private void MakeShortcuts()
    {
        var desk = Environment.GetFolderPath(Environment.SpecialFolder.Desktop);
        var icon = Path.Combine(TargetDir, "app", "ShaYu.exe");
        // 桌面只放「启动」；卸载入口在面板「参数设置」页底部（别往桌上多扔一个）
        Shortcut(Path.Combine(desk, "启动傻鱼.lnk"), Path.Combine(TargetDir, "启动.bat"), TargetDir, icon);
        // 老版本可能留过「卸载傻鱼.lnk」，顺手清掉
        try
        {
            var old = Path.Combine(desk, "卸载傻鱼.lnk");
            if (File.Exists(old)) File.Delete(old);
        }
        catch { }
    }

    private static void Shortcut(string lnk, string target, string workdir, string icon)
    {
        try
        {
            var ps = "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('" + lnk + "');" +
                     "$s.TargetPath='" + target + "';$s.WorkingDirectory='" + workdir + "';" +
                     "$s.WindowStyle=7;" +
                     (string.IsNullOrEmpty(icon) ? "" : "$s.IconLocation='" + icon + "';") +
                     "$s.Save()";
            Process.Start(new ProcessStartInfo("powershell", "-NoProfile -Command \"" + ps + "\"")
            { CreateNoWindow = true, UseShellExecute = false })?.WaitForExit(15000);
        }
        catch { }
    }

    /// <summary>payload.zip 追加在本 exe 末尾，最后 8 字节是长度。</summary>
    private static Stream OpenPayload()
    {
        var exe = Environment.ProcessPath ?? throw new Exception("拿不到自己的路径");
        using var fs = File.OpenRead(exe);
        var total = fs.Length;

        // 先试「尾部追加」格式
        if (total > 8)
        {
            fs.Seek(-8, SeekOrigin.End);
            var lenBuf = new byte[8];
            fs.ReadExactly(lenBuf);
            var zipLen = BitConverter.ToInt64(lenBuf);
            if (zipLen > 1000 && zipLen < total - 8)
            {
                fs.Seek(total - 8 - zipLen, SeekOrigin.Begin);
                var data = new byte[zipLen];
                fs.ReadExactly(data);
                // 确认真的是 zip（PK 头）
                if (data.Length > 4 && data[0] == 0x50 && data[1] == 0x4B)
                    return new MemoryStream(data);
            }
        }

        // 退路 1：内嵌资源（单文件安装包走这条，最稳）
        try
        {
            var res = typeof(SetupForm).Assembly.GetManifestResourceStream("ShaYuSetup.payload.zip");
            if (res is not null) return res;
        }
        catch { }

        // 退路 2：同目录的 payload.zip（开发时用）
        var side = Path.Combine(AppContext.BaseDirectory, "payload.zip");
        if (File.Exists(side)) return File.OpenRead(side);
        throw new Exception("安装包不完整：找不到 payload");
    }

    private static void CopyDir(string src, string dst)
    {
        Directory.CreateDirectory(dst);
        foreach (var f in Directory.GetFiles(src))
            File.Copy(f, Path.Combine(dst, Path.GetFileName(f)), true);
        foreach (var d in Directory.GetDirectories(src))
            CopyDir(d, Path.Combine(dst, Path.GetFileName(d)));
    }

    private void Step5()
    {
        var card = Card("装好了", "");
        var p = new Panel { Dock = DockStyle.Fill };
        card.Controls.Add(p);
        p.BringToFront();

        p.Controls.Add(new Label
        {
            Text = "✓", Font = new Font("Microsoft YaHei UI", 34f, FontStyle.Bold),
            ForeColor = C.Ok, Location = new Point(0, 10), AutoSize = true
        });
        p.Controls.Add(Lbl("接下来这么做", new Font("Microsoft YaHei UI", 12f, FontStyle.Bold), C.Text, 0, 76));
        p.Controls.Add(Lbl(
            "1. 双击桌面「启动傻鱼」——协议端、机器人、面板会依次起来\n" +
            "2. 第一次用：浏览器打开 http://127.0.0.1:5099 ，设个管理密码\n" +
            "3. 在那个页面里给机器人小号扫码登录 QQ\n" +
            "4. 用你的大号私聊小号，发「在吗」\n" +
            "5. 她回你了，就成了（以后只需第 1 步）\n\n" +
            "装在哪：" + TargetDir + "\n" +
            "不要了：打开面板「参数设置」，拉到最底下点「卸载」",
            C.FontBase, C.Sub, 0, 106, 700));
        var btn = MakeButton("关闭", true, 0, 0);
        btn.Click += (_, _) => Close();
        card.Controls.Add(btn);
        btn.BringToFront();
        card.Resize += (_, _) => btn.Location = new Point(card.Width - 134, card.Height - 58);
        btn.Location = new Point(card.Width - 134, card.Height - 58);
    }
}