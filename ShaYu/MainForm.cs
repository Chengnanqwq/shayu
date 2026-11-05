using System.Diagnostics;
using System.Drawing;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace ShaYu;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        Application.Run(new MainForm());
    }
}

/// <summary>用户设置。存在 exe 旁边的 settings.json，换台机器就换这份文件。</summary>
public class Settings
{
    public string PanelUrl { get; set; } = "http://127.0.0.1:6200";
    public string LocalPanelUrl { get; set; } = "http://127.0.0.1:6201";
    public int SingPort { get; set; } = 7100;
    public int SnowPort { get; set; } = 3000;
    public int TunnelPort { get; set; } = 16199;
    public string RvcDir { get; set; } = "";
    public string SnowLumaDir { get; set; } = "";
    public string SnowLumaExe { get; set; } = "";
    public string SingStartScript { get; set; } = "";
    public string SepPython { get; set; } = "";
    public string SingServerPy { get; set; } = "";
    public string TunnelScript { get; set; } = "";
    public string SshUser { get; set; } = "root";
    public string SshHost { get; set; } = "";
    public string SshKey { get; set; } = "";
    public string ServiceName { get; set; } = "fishbot";
    public bool SetupDone { get; set; } = false;
    public string TtsKey { get; set; } = "";

    /// <summary>插件开关（本地类插件用）。没写进这里的一律视为关闭。</summary>
    public Dictionary<string, bool> Plugins { get; set; } = new()
    {
        ["remote"] = false, ["rvc"] = false
    };

    public bool HasRemote => !string.IsNullOrWhiteSpace(SshHost);
    public bool HasRvc => !string.IsNullOrWhiteSpace(RvcDir);
    public bool HasSnow => !string.IsNullOrWhiteSpace(SnowLumaDir) && !string.IsNullOrWhiteSpace(SnowLumaExe);
    public bool HasTunnel => !string.IsNullOrWhiteSpace(TunnelScript);
    public bool Ok => !string.IsNullOrWhiteSpace(PanelUrl);
}

public class MainForm : Form
{
    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(2.5) };

    private static string SettingsPath =>
        Path.Combine(AppContext.BaseDirectory, "settings.json");

    private Settings _set = new();
    private WebView2 _web = null!;
    private NotifyIcon _tray = null!;
    private readonly System.Windows.Forms.Timer _timer = new() { Interval = 3000 };
    private bool _ready;

    public MainForm()
    {
        Text = "傻鱼";
        Size = new Size(1240, 840);
        MinimumSize = new Size(980, 660);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(10, 12, 18);
        Icon = AppIcon.Get;

        LoadSettings();

        _web = new WebView2 { Dock = DockStyle.Fill, DefaultBackgroundColor = Color.FromArgb(10, 12, 18) };
        Controls.Add(_web);

        BuildTray();

        _timer.Tick += async (_, _) => await PushStatusAsync();
        Load += async (_, _) =>
        {
            await InitWebAsync();
            await PushSettingsAsync();
            await PushStatusAsync();
            _timer.Start();
        };
        Resize += (_, _) => { if (WindowState == FormWindowState.Minimized) HideToTray(); };
        FormClosing += (_, e) =>
        {
            if (e.CloseReason == CloseReason.UserClosing && _tray.Visible)
            {
                e.Cancel = true;
                HideToTray();
            }
        };
    }

    // ── 设置读写 ────────────────────────────────────────────
    private void LoadSettings()
    {
        try
        {
            if (File.Exists(SettingsPath))
            {
                var json = File.ReadAllText(SettingsPath);
                var s = JsonSerializer.Deserialize<Settings>(json, Opts());
                if (s != null) _set = s;
            }
        }
        catch { }
    }

    private void SaveSettings(Settings s)
    {
        _set = s;
        try
        {
            File.WriteAllText(SettingsPath,
                JsonSerializer.Serialize(s, Opts()), System.Text.Encoding.UTF8);
        }
        catch { }
    }

    private static JsonSerializerOptions Opts() => new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
        PropertyNameCaseInsensitive = true
    };

    // ── WebView2 ────────────────────────────────────────────
    private static void Log(string msg)
    {
        try
        {
            File.AppendAllText(Path.Combine(AppContext.BaseDirectory, "_app.log"),
                $"{DateTime.Now:HH:mm:ss} {msg}\r\n", Encoding.UTF8);
        }
        catch { }
    }

    private async Task InitWebAsync()
    {
        if (_ready) return;
        var dataDir = Path.Combine(Path.GetTempPath(), "shayu_webview2");
        var opts = new CoreWebView2EnvironmentOptions(
            "--disable-web-security --disable-features=IsolateOrigins,site-per-process");
        var env = await CoreWebView2Environment.CreateAsync(null, dataDir, opts);
        await _web.EnsureCoreWebView2Async(env);

        var core = _web.CoreWebView2;
        core.Settings.AreDevToolsEnabled = false;
        core.Settings.IsStatusBarEnabled = false;
        core.Settings.AreDefaultContextMenusEnabled = false;
        core.Settings.IsZoomControlEnabled = false;

        var www = Path.Combine(AppContext.BaseDirectory, "www");
        core.SetVirtualHostNameToFolderMapping("shayu.app", www, CoreWebView2HostResourceAccessKind.Allow);
        core.WebMessageReceived += OnWebMessage;
        // 页面里的外链（比如"去下载"）要在系统浏览器里开：
        // 不拦的话 WebView 会自己导航走，整个面板就变成 GitHub 页面，回不来了
        core.NewWindowRequested += (_, e) =>
        {
            e.Handled = true;
            try { Process.Start(new ProcessStartInfo(e.Uri) { UseShellExecute = true })?.Dispose(); }
            catch { }
        };
        // 页面加载完再推一次：Navigate 之后立刻 Post 有可能比前端的 message 监听还早，会被丢掉
        core.NavigationCompleted += async (_, _) =>
        {
            await PushSettingsAsync();
            await PushStatusAsync();
        };
        // 由 C# 决定要不要进向导，别让前端靠 900ms 定时器猜
        var needSetup = !_set.SetupDone || string.IsNullOrWhiteSpace(_set.PanelUrl);
        var q = needSetup ? "?setup=1&v=" : "?v=";
        core.Navigate($"https://shayu.app/index.html{q}{DateTime.Now.Ticks}");
        Log($"[shayu] setupDone={_set.SetupDone} panelUrl={_set.PanelUrl} needSetup={needSetup}");
        _ready = true;
    }

    private void OnWebMessage(object? sender, CoreWebView2WebMessageReceivedEventArgs e)
    {
        try
        {
            using var doc = JsonDocument.Parse(e.WebMessageAsJson);
            var root = doc.RootElement;
            var cmd = root.TryGetProperty("cmd", out var c) ? c.GetString() : null;

            if (cmd == "act")
                Dispatch(root.TryGetProperty("act", out var a) ? a.GetString() : null);
            else if (cmd == "saveSettings")
            {
                var s = JsonSerializer.Deserialize<Settings>(root.GetProperty("settings").GetRawText(), Opts());
                if (s != null)
                {
                    SaveSettings(s);
                    _panelResolved = false;     // 用户可能改了面板地址，下个周期重新确认
                    _ = PushSettingsAsync();
                    _ = PushStatusAsync();
                    SendMsg("设置已保存");
                }
            }
            else if (cmd == "getSettings")
                _ = PushSettingsAsync();
            else if (cmd == "testPanel")
                _ = TestPanelAsync(root.TryGetProperty("url", out var u) ? u.GetString() : null);
            else if (cmd == "pickPlugin")
            {
                Log("[shayu] 收到 pickPlugin");
                _ = PickPluginAsync();
            }
            else if (cmd == "uninstall")
                UninstallApp();
        }
        catch (Exception ex) { SendMsg("出错：" + ex.Message); }
    }

    private async Task TestPanelAsync(string? url)
    {
        if (string.IsNullOrWhiteSpace(url)) { SendMsg("先填面板地址"); return; }
        try
        {
            using var r = await Http.GetAsync(url.TrimEnd('/') + "/api/status");
            SendMsg(r.IsSuccessStatusCode ? "面板连得上 ✔" : $"面板返回 {(int)r.StatusCode}");
        }
        catch (Exception e) { SendMsg("连不上：" + e.Message); }
    }

    // ── 上传插件 ────────────────────────────────────────────
    /// <summary>
    /// 市场页点「上传插件」走这里：用 WinForms 的原生选择器读文件，再 POST 给面板。
    /// 不用 &lt;input type=file&gt;，WebView2 里 Chromium 的选文件框在这个宿主要么不弹、
    /// 要么弹出来拿不到焦点，绕开它最省事。
    /// </summary>
    private async Task PickPluginAsync()
    {
        using var dlg = new OpenFileDialog
        {
            Title = "选一个插件（.py）",
            Filter = "插件文件 (*.py)|*.py|所有文件 (*.*)|*.*",
            CheckFileExists = true,
        };
        Log("[shayu] 开选择框 …");
        if (dlg.ShowDialog(this) != DialogResult.OK) { Log("[shayu] 选择框取消了"); return; }
        Log("[shayu] 选到 " + dlg.FileName);

        var path = dlg.FileName;
        var name = Path.GetFileName(path);
        if (!name.EndsWith(".py", StringComparison.OrdinalIgnoreCase))
        {
            SendMsg("只认 .py 文件");
            return;
        }
        byte[] bytes;
        try { bytes = File.ReadAllBytes(path); }
        catch (Exception e) { SendMsg("读不了这个文件：" + e.Message); return; }
        if (bytes.Length == 0) { SendMsg("这个文件是空的"); return; }

        var overwrite = false;
        using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(20) };
        for (var attempt = 0; attempt < 2; attempt++)
        {
            try
            {
                using var content = new ByteArrayContent(bytes);
                content.Headers.ContentType = new MediaTypeHeaderValue("application/octet-stream");
                var url = _set.PanelUrl.TrimEnd('/') + "/api/plugins/upload?name=" +
                          Uri.EscapeDataString(name) + (overwrite ? "&overwrite=1" : "");
                using var r = await http.PostAsync(url, content);
                var body = await r.Content.ReadAsStringAsync();
                using var doc = JsonDocument.Parse(body);
                var root = doc.RootElement;

                var ok = root.TryGetProperty("ok", out var okEl) && okEl.ValueKind == JsonValueKind.True;
                if (!ok)
                {
                    var exists = root.TryGetProperty("exists", out var exEl) && exEl.ValueKind == JsonValueKind.True;
                    if (exists && !overwrite)
                    {
                        var yes = MessageBox.Show(this,
                            $"已经有个 {name} 了，要用这个覆盖吗？", "上传插件",
                            MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes;
                        if (yes) { overwrite = true; continue; }
                        SendMsg("没覆盖，原来那个还在");
                        return;
                    }
                    var err = root.TryGetProperty("error", out var errEl) ? errEl.GetString() : "原因不明";
                    SendMsg("上传失败：" + err);
                    return;
                }

                var shown = root.TryGetProperty("name", out var nmEl) ? nmEl.GetString() : name;
                var lines = root.TryGetProperty("lines", out var lnEl) ? lnEl.GetInt32() : 0;
                Log($"[shayu] 上传插件 {name}（{bytes.Length} 字节，覆盖={overwrite}）");
                SendMsg($"{shown} 装好了：{lines} 行，已热重载");
                Post(new { type = "pluginsChanged" });   // 让市场页自己刷新
                return;
            }
            catch (Exception e)
            {
                SendMsg("上传失败：" + e.Message);
                return;
            }
        }
    }

    // ── 卸载（设置页底部那个按钮）─────────────────────────────
    /// <summary>
    /// 设成「点一下 = 整个安装目录没了」，所以确认框默认选在「否」。
    /// 自己就在 app\ 里，没法边跑边删自己：先退出，再让 cmd 延迟两秒删目录。
    /// </summary>
    private void UninstallApp()
    {
        var appDir = AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        var root = Directory.GetParent(appDir)?.FullName ?? appDir;
        if (!File.Exists(Path.Combine(root, "bot.py")))
        {
            SendMsg("这不像安装目录，没敢动：" + root);
            return;
        }

        var ok = MessageBox.Show(this,
            $"会把整个安装目录删掉：\n{root}\n\n机器人、记忆、配置、插件全都没了，确定卸载？",
            "卸载傻鱼", MessageBoxButtons.YesNo, MessageBoxIcon.Warning,
            MessageBoxDefaultButton.Button2) == DialogResult.Yes;
        if (!ok) { SendMsg("没卸，东西都还在"); return; }

        // 1) 先停掉这个目录里的机器人（别误杀别人电脑上别的 python）
        var killed = 0;
        foreach (var name in new[] { "pythonw", "python" })
        {
            foreach (var p in Process.GetProcessesByName(name))
            {
                try
                {
                    var exe = p.MainModule?.FileName ?? "";
                    if (string.IsNullOrEmpty(exe)) continue;
                    if (!exe.StartsWith(root, StringComparison.OrdinalIgnoreCase)) continue;
                    p.Kill(true);
                    killed++;
                }
                catch { }
            }
        }

        // 2) 桌面快捷方式：老版本装过「卸载傻鱼」，一起清掉
        var desk = Environment.GetFolderPath(Environment.SpecialFolder.Desktop);
        foreach (var fname in new[] { "启动傻鱼.lnk", "卸载傻鱼.lnk" })
        {
            try
            {
                var p = Path.Combine(desk, fname);
                if (File.Exists(p)) File.Delete(p);
            }
            catch { }
        }

        // 3) 退出后删目录。工作目录必须挪到 TEMP：
        //    cmd 继承我们的 CWD（就是安装根目录），那种情况下 rmdir 删不掉自己所在的目录
        try
        {
            var script = "/c ping 127.0.0.1 -n 4 >nul & rmdir /s /q \"" + root + "\"" +
                         " & ping 127.0.0.1 -n 2 >nul & rmdir /s /q \"" + root + "\"" +
                         " & ping 127.0.0.1 -n 2 >nul & rmdir /s /q \"" + root + "\"";
            Process.Start(new ProcessStartInfo("cmd.exe", script)
            {
                CreateNoWindow = true,
                UseShellExecute = false,
                WorkingDirectory = Path.GetTempPath(),
            });
        }
        catch (Exception e)
        {
            SendMsg("删不掉：" + e.Message + "，手动删 " + root + " 也行");
            return;
        }

        Log($"[shayu] 卸载 {root}（停了 {killed} 个 python 进程）");
        _tray.Visible = false;
        _timer.Stop();
        Application.Exit();
    }

    private void Dispatch(string? act)
    {
        switch (act)
        {
            case "start_sing": StartSing(); break;
            case "stop_sing": StopSing(); break;
            case "restart_snow": RestartSnow(); break;
            case "wake": WakeBot(); break;
            case "start_tunnel": StartTunnel(); break;
            case "restart_cloud": RestartCloud(); break;
            case "open_snowwebui": OpenSnowWebUi(); break;
        }
    }

    private void SendMsg(string text) => Post(new { type = "status", msg = text });

    private void Post(object o)
    {
        if (!_ready) return;
        try { _web.CoreWebView2.PostWebMessageAsJson(JsonSerializer.Serialize(o, Opts())); } catch { }
    }

    private async Task PushSettingsAsync()
    {
        await Task.Yield();
        Post(new { type = "settings", settings = _set });
    }

    // ── 状态 ────────────────────────────────────────────────
    private async Task PushStatusAsync()
    {
        if (!_ready) return;
        await ResolvePanelAsync();
        var sing = await ProbePortHttpAsync(_set.SingPort, $"http://127.0.0.1:{_set.SingPort}/health");
        var snow = await ProbePortHttpAsync(_set.SnowPort, $"http://127.0.0.1:{_set.SnowPort}/get_login_info");
        var tun = _set.HasTunnel ? ProbePort(_set.TunnelPort) : false;
        var (cloud, model) = await ProbeCloudAsync();

        Post(new
        {
            type = "status",
            sing, snow, tun, cloud, model,
            caps = new { rvc = _set.HasRvc, snow = _set.HasSnow, tunnel = _set.HasTunnel, remote = _set.HasRemote }
        });
    }

    private async Task<bool> ProbePortHttpAsync(int port, string url)
    {
        try { using var r = await Http.GetAsync(url); return r.IsSuccessStatusCode; }
        catch { return ProbePort(port); }
    }

    private bool _panelResolved;
    private bool _resolvingPanel;

    /// <summary>
    /// 面板端口可能被改过、也可能装完之后被别人占了。
    /// 配置里的地址连不上，就自己在 6200~6239 里找一个能答 /api/status 的，找到就写回配置并通知前端。
    /// </summary>
    private async Task<bool> ResolvePanelAsync()
    {
        if (_panelResolved || _resolvingPanel) return !string.IsNullOrWhiteSpace(_set.PanelUrl);
        _resolvingPanel = true;
        try
        {
            if (await PanelAnswersAsync(_set.PanelUrl)) { _panelResolved = true; return true; }
            for (var port = 6200; port < 6240; port++)
            {
                var url = $"http://127.0.0.1:{port}";
                if (!await PanelAnswersAsync(url)) continue;
                Log($"[shayu] 面板自动发现 {url}（配置里写的是 {_set.PanelUrl}）");
                _set.PanelUrl = url;
                SaveSettings(_set);
                _panelResolved = true;
                await PushSettingsAsync();     // 让前端把 iframe 和 fetch 一起换过来
                return true;
            }
            return false;
        }
        finally { _resolvingPanel = false; }
    }

    private async Task<bool> PanelAnswersAsync(string? url)
    {
        if (string.IsNullOrWhiteSpace(url)) return false;
        try
        {
            using var r = await Http.GetAsync(url.TrimEnd('/') + "/api/status");
            return r.IsSuccessStatusCode;
        }
        catch { return false; }
    }

    private async Task<(bool Ok, string Model)> ProbeCloudAsync()
    {
        if (string.IsNullOrWhiteSpace(_set.PanelUrl)) return (false, "");
        try
        {
            using var r = await Http.GetAsync(_set.PanelUrl.TrimEnd('/') + "/api/status");
            if (!r.IsSuccessStatusCode) return (false, "");
            var body = await r.Content.ReadAsStringAsync();
            using var doc = JsonDocument.Parse(body);
            var m = doc.RootElement.TryGetProperty("llm_model", out var lm) ? lm.GetString() ?? "" : "";
            return (true, m);
        }
        catch { return (false, ""); }
    }

    private static bool ProbePort(int port)
    {
        try
        {
            using var t = new TcpClient();
            return t.ConnectAsync("127.0.0.1", port).Wait(380) && t.Connected;
        }
        catch { return false; }
    }

    // ── 动作（全部走设置，不写死路径）──────────────────────
    private void StartSing() => RunAsync("启动翻唱", () =>
    {
        if (!string.IsNullOrWhiteSpace(_set.SingStartScript) && File.Exists(_set.SingStartScript))
        {
            Process.Start("wscript.exe", _set.SingStartScript)?.Dispose();
            return;
        }
        if (!string.IsNullOrWhiteSpace(_set.SepPython) && File.Exists(_set.SepPython)
            && !string.IsNullOrWhiteSpace(_set.SingServerPy) && File.Exists(_set.SingServerPy))
        {
            Process.Start(new ProcessStartInfo(_set.SepPython, _set.SingServerPy)
            {
                WorkingDirectory = Path.GetDirectoryName(_set.SepPython) ?? "",
                CreateNoWindow = true, UseShellExecute = false
            })?.Dispose();
            return;
        }
        throw new Exception("没配置翻唱启动方式，去设置里填");
    });

    private void StopSing() => RunAsync("停止翻唱", () =>
        Sh($"for /f \"tokens=5\" %a in ('netstat -ano ^| findstr :{_set.SingPort} ^| findstr LISTENING') do taskkill /PID %a /F", 15000));

    private void RestartSnow() => RunAsync("重启 SnowLuma", () =>
    {
        if (!_set.HasSnow) throw new Exception("没配置 SnowLuma 路径");
        // 只杀这个目录里的 node：现在协议端是随包带的 node.exe，
        // 无差别 taskkill 会把用户别的 node 程序一起弄死
        var root = _set.SnowLumaDir;
        foreach (var p in Process.GetProcessesByName("node"))
        {
            try
            {
                var exe = p.MainModule?.FileName ?? "";
                if (string.IsNullOrEmpty(exe)) continue;
                if (!exe.StartsWith(root, StringComparison.OrdinalIgnoreCase)) continue;
                p.Kill(true);
            }
            catch { }
        }
        Thread.Sleep(1800);
        var workDir = File.Exists(Path.Combine(root, "app", "index.mjs"))
            ? Path.Combine(root, "app") : root;
        Process.Start(new ProcessStartInfo(_set.SnowLumaExe, "index.mjs")
        { WorkingDirectory = workDir, UseShellExecute = false, CreateNoWindow = true })?.Dispose();
        Thread.Sleep(14000);
    });

    /// <summary>协议端的二维码/扫码页在它自己的 WebUI 上，点顶栏那个雪点开。</summary>
    private void OpenSnowWebUi() => RunAsync("打开 QQ 登录页", () =>
    {
        if (!_set.HasSnow) throw new Exception("这个装法没带协议端，得自己装 SnowLuma 或 NapCat");
        Process.Start(new ProcessStartInfo("http://127.0.0.1:5099") { UseShellExecute = true })?.Dispose();
    });

    private void WakeBot() => RunAsync("叫醒傻鱼", () =>
    {
        if (string.IsNullOrWhiteSpace(_set.PanelUrl)) throw new Exception("没配置面板地址");
        try { Http.GetAsync(_set.PanelUrl.TrimEnd('/') + "/api/wake").Wait(6000); } catch { }
    });

    private void StartTunnel() => RunAsync("启动隧道", () =>
    {
        if (!_set.HasTunnel) throw new Exception("没配置隧道脚本");
        if (File.Exists(_set.TunnelScript)) Process.Start("wscript.exe", _set.TunnelScript)?.Dispose();
    });

    private void RestartCloud() => RunAsync("重启云端", () =>
    {
        if (!_set.HasRemote) throw new Exception("没配置服务器地址");
        var key = string.IsNullOrWhiteSpace(_set.SshKey) ? "" : $"-i \"{_set.SshKey}\" ";
        Sh($"{key}-o ConnectTimeout=10 -o StrictHostKeyChecking=no {_set.SshUser}@{_set.SshHost} " +
           $"\"systemctl restart {_set.ServiceName}\"", 90000, "ssh.exe");
    });

    private void RunAsync(string what, Action act)
    {
        SendMsg(what + " …");
        _ = Task.Run(() =>
        {
            try
            {
                act();
                BeginInvoke(() => { SendMsg(what + " 完成"); _ = PushStatusAsync(); });
            }
            catch (Exception e) { BeginInvoke(() => SendMsg($"{what} 失败：{e.Message}")); }
        });
    }

    private static void Sh(string args, int waitMs = 0, string file = "cmd.exe")
    {
        var full = file == "cmd.exe" ? "/c " + args : args;
        var p = Process.Start(new ProcessStartInfo(file, full)
        { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true });
        if (p is null) return;
        if (waitMs > 0) p.WaitForExit(waitMs);
    }

    // ── 托盘 ────────────────────────────────────────────────
    private void BuildTray()
    {
        var menu = new ContextMenuStrip();
        menu.Items.Add("显示", null, (_, _) => ShowFromTray());
        menu.Items.Add("叫醒傻鱼", null, (_, _) => WakeBot());
        menu.Items.Add(new ToolStripSeparator());
        menu.Items.Add("退出", null, (_, _) =>
        {
            _tray.Visible = false;
            _timer.Stop();
            Application.Exit();
        });

        _tray = new NotifyIcon { Icon = AppIcon.Get, Text = "傻鱼", Visible = true, ContextMenuStrip = menu };
        _tray.DoubleClick += (_, _) => ShowFromTray();
    }

    private void HideToTray()
    {
        Hide();
        _tray.ShowBalloonTip(1000, "傻鱼", "已收进托盘，双击图标唤回", ToolTipIcon.None);
    }

    private void ShowFromTray()
    {
        Show();
        WindowState = FormWindowState.Normal;
        Activate();
    }
}