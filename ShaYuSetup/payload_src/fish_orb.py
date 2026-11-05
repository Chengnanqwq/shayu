# -*- coding: utf-8 -*-
"""fish_orb.py —— 傻鱼的桌面小球（真透明、置顶、可拖、点一下说话）

Windows 分层窗口（UpdateLayeredWindow）做逐像素透明，
所以它真的是浮在壁纸/别的软件上的一颗光球，不是深色方块。

- 单击展开聊天窗（走本机 127.0.0.1:6200 的 /api/talk，和 QQ 共用核心/记忆）
- 拖动挪位置，位置记在 orb_pos.json
- 右键：聊天 / 打开大脑 / 桌面对话页 / 退出

启动：pythonw fish_orb.py（在安装目录用便携 Python 运行）
"""

from __future__ import annotations

import ctypes
import json
import math
import os
import threading
import time
import tkinter as tk
import urllib.request
from ctypes import wintypes
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

BASE = Path(__file__).parent
POS_FILE = BASE / "orb_pos.json"
API = "http://127.0.0.1:6200"
SIZE = 152
PET_IMG = BASE / "fish_pet.png"
TITLE = "傻鱼"

WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
GWL_EXSTYLE = -20
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def api(path: str, payload: dict | None = None, timeout: float = 90) -> dict:
    data, headers = None, {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def orb_frames(px: int) -> list[Image.Image]:
    """用 dsh-pet 的傻鱼立绘当外观：呼吸缩放 + 轻微上下浮。"""
    src = PET_IMG
    if src.exists():
        base = Image.open(src).convert("RGBA")
        base.thumbnail((int(px * 0.96), int(px * 0.96)), Image.LANCZOS)
        out = []
        for i in range(16):
            f = 0.955 + 0.045 * (0.5 + 0.5 * math.sin(i / 16 * 2 * math.pi))
            img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
            small = base.resize((max(24, int(base.width * f)),
                                 max(24, int(base.height * f))), Image.LANCZOS)
            glide = int(1.5 * math.sin(i / 16 * 2 * math.pi))
            off = ((px - small.width) // 2, (px - small.height) // 2 + glide)
            img.paste(small, off, small)
            out.append(img)
        return out
    return _glow_frames(px)


def _glow_frames(px: int) -> list[Image.Image]:
    """没有立绘时的备用：一团光球。"""
    base = 320
    layers = [
        ((64, 138, 255), 150, 46, 0.55),
        ((110, 202, 255), 92, 26, 0.85),
        ((236, 250, 255), 58, 10, 1.0),
    ]
    sprite = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    for color, radius, blur, alpha in layers:
        mask = Image.new("L", (base, base), 0)
        d = ImageDraw.Draw(mask)
        c = base // 2
        d.ellipse([c - radius, c - radius, c + radius, c + radius], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * alpha))
        layer = Image.new("RGBA", (base, base), color + (0,))
        layer.putalpha(mask)
        sprite = Image.alpha_composite(sprite, layer)
    out = []
    for i in range(16):
        f = 0.93 + 0.07 * (0.5 + 0.5 * math.sin(i / 16 * 2 * math.pi))
        s = max(24, int(px * f))
        img = Image.new("RGBA", (px, px), (0, 0, 0, 0))
        small = sprite.resize((s, s), Image.LANCZOS)
        off = (px - s) // 2
        img.paste(small, (off, off), small)
        out.append(img)
    return out


def to_bgra(img: Image.Image) -> bytes:
    """PIL RGBA -> 预乘 BGRA（UpdateLayeredWindow 要的格式）。"""
    data = img.tobytes()
    out = bytearray(len(data))
    for i in range(0, len(data), 4):
        r, g, b, a = data[i], data[i + 1], data[i + 2], data[i + 3]
        out[i] = b * a // 255
        out[i + 1] = g * a // 255
        out[i + 2] = r * a // 255
        out[i + 3] = a
    return bytes(out)


class Orb:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title(TITLE)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="#000000")

        self.scale = self.root.winfo_fpixels("1i") / 96.0
        self.px = max(48, int(SIZE * self.scale))
        self.frames = orb_frames(self.px)
        self.bgra_full = [to_bgra(f) for f in self.frames]

        x, y = self.load_pos()
        self.root.geometry(f"{self.px}x{self.px}+{x}+{y}")
        self.root.update_idletasks()

        self.layered = self.setup_layered()
        self.phase = 0.0
        self.dragging = False
        self.press = (0, 0)
        self.start_root = (0, 0)
        self.chat = None
        self.online = True
        self.status = {}

        self.root.bind("<ButtonPress-1>", self.on_press)
        self.root.bind("<B1-Motion>", self.on_drag)
        self.root.bind("<ButtonRelease-1>", self.on_release)
        self.root.bind("<Button-3>", self.menu)

        self.animate()
        self.poll()
        self.hotkey_poll()

    # ---------------- 分层窗口 ----------------
    def hwnd(self) -> int:
        h = user32.GetParent(self.root.winfo_id())
        return h or self.root.winfo_id()

    def setup_layered(self) -> bool:
        try:
            self.h = self.hwnd()
            style = user32.GetWindowLongW(self.h, GWL_EXSTYLE)
            user32.SetWindowLongW(self.h, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TOOLWINDOW)
            screen = user32.GetDC(0)
            self.memdc = gdi32.CreateCompatibleDC(screen)
            bmi = BITMAPINFO()
            bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.bmiHeader.biWidth = self.px
            bmi.bmiHeader.biHeight = -self.px
            bmi.bmiHeader.biPlanes = 1
            bmi.bmiHeader.biBitCount = 32
            bmi.bmiHeader.biCompression = 0
            self.bits = ctypes.c_void_p()
            self.hbmp = gdi32.CreateDIBSection(screen, ctypes.byref(bmi), 0,
                                               ctypes.byref(self.bits), None, 0)
            gdi32.SelectObject(self.memdc, self.hbmp)
            user32.ReleaseDC(0, screen)
            return bool(self.hbmp)
        except Exception as e:
            print("[orb] 分层窗口失败:", e)
            return False

    def blit(self, index: int) -> None:
        if not self.layered:
            return
        ctypes.memmove(self.bits, self.bgra_full[index], len(self.bgra_full[index]))
        pt_dst = wintypes.POINT(self.root.winfo_x(), self.root.winfo_y())
        pt_src = wintypes.POINT(0, 0)
        size = wintypes.SIZE(self.px, self.px)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(self.h, 0, ctypes.byref(pt_dst), ctypes.byref(size),
                                   self.memdc, ctypes.byref(pt_src), 0,
                                   ctypes.byref(blend), ULW_ALPHA)

    # ---------------- 位置 ----------------
    def load_pos(self) -> tuple[int, int]:
        try:
            d = json.loads(POS_FILE.read_text(encoding="utf-8"))
            x, y = int(d["x"]), int(d["y"])
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            if -self.px < x < sw - 20 and -self.px < y < sh - 20:
                return x, y
        except Exception:
            pass
        return (self.root.winfo_screenwidth() - self.px - 50,
                self.root.winfo_screenheight() - self.px - 130)

    def save_pos(self) -> None:
        try:
            POS_FILE.write_text(json.dumps({"x": self.root.winfo_x(), "y": self.root.winfo_y()}),
                                encoding="utf-8")
        except Exception:
            pass

    # ---------------- 交互 ----------------
    def on_press(self, e):
        self.dragging = True
        self.start_root = (e.x_root, e.y_root)
        self.press = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def on_drag(self, e):
        if not self.dragging:
            return
        self.root.geometry(f"+{e.x_root - self.press[0]}+{e.y_root - self.press[1]}")
        self.blit(int(self.phase) % len(self.frames))
        if self.chat is not None and self.chat.winfo_exists():
            self.place_chat()

    def on_release(self, e):
        self.dragging = False
        self.save_pos()
        moved = abs(e.x_root - self.start_root[0]) + abs(e.y_root - self.start_root[1])
        if moved < 6:
            self.toggle_chat()

    def post_action(self, name, **kw):
        import threading
        def work():
            try:
                body = {"name": name}; body.update(kw)
                data = json.dumps(body).encode("utf-8")
                req = urllib.request.Request(API + "/api/action", data=data,
                                             headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=15).read()
                self.poll_once()
            except Exception as e:
                print("[orb] 动作失败:", e)
        threading.Thread(target=work, daemon=True).start()

    def poll_once(self):
        try:
            d = json.loads(urllib.request.urlopen(API + "/api/brain", timeout=6).read())
            core = d.get("core") or {}
            m = core.get("mood") or {}
            r = core.get("rice") or {}
            self.status = {
                "mood": m.get("label") or "—",
                "fatigue": core.get("fatigue") or 0,
                "bowls": r.get("bowls") or 0,
                "sleep": bool(core.get("sleep")),
            }
        except Exception:
            self.status = {}

    def menu(self, e):
        self.poll_once()
        st = self.status or {}
        m = tk.Menu(self.root, tearoff=0, bg="#101a2e", fg="#dbe9ff",
                    activebackground="#1d3153", activeforeground="#ffffff", bd=0)
        m.add_command(label=f"{st.get('mood','—')} · 疲劳 {st.get('fatigue',0):.0f}% · {st.get('bowls',0)} 碗",
                      state="disabled")
        m.add_separator()
        m.add_command(label="喂一碗白饭", command=lambda: self.post_action("feed", bowls=1))
        if st.get("sleep"):
            m.add_command(label="叫醒她", command=lambda: self.post_action("wake"))
        else:
            m.add_command(label="哄她睡觉", command=lambda: self.post_action("sleep", hours=3))
        m.add_separator()
        m.add_command(label="聊天", command=self.toggle_chat)
        m.add_command(label="隐藏（Ctrl+Alt+S 呼出）", command=self.hide)
        m.add_command(label="打开大脑", command=lambda: os.startfile(API + "/brain"))
        m.add_command(label="桌面对话页", command=lambda: os.startfile(API + "/desk"))
        m.add_separator()
        m.add_command(label="退出", command=self.quit)
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()

    # ---------------- 动画 / 在线状态 ----------------
    def animate(self):
        self.phase = (self.phase + 0.55) % len(self.frames)
        self.blit(int(self.phase) % len(self.frames))
        self.root.after(80, self.animate)

    def poll(self):
        def work():
            try:
                ok = bool(api("/api/status", timeout=4).get("model"))
            except Exception:
                ok = False
            self.root.after(0, lambda: self.set_online(ok))
        threading.Thread(target=work, daemon=True).start()
        self.root.after(15000, self.poll)

    def set_online(self, ok: bool):
        if ok == self.online:
            return
        self.online = ok
        if ok:
            self.bgra_full = [to_bgra(f) for f in self.frames]
        else:
            faded = []
            for f in self.frames:
                g = f.copy()
                a = g.split()[3].point(lambda v: int(v * 0.5))
                g.putalpha(a)
                faded.append(g)
            self.bgra_full = [to_bgra(f) for f in faded]

    # ---------------- 聊天窗 ----------------
    def toggle_chat(self):
        if self.chat is not None and self.chat.winfo_exists():
            self.close_chat()
        else:
            self.open_chat()

    def close_chat(self):
        if self.chat is not None and self.chat.winfo_exists():
            self.chat.destroy()
        self.chat = None

    def open_chat(self):
        w, h = 360, 440
        c = tk.Toplevel(self.root)
        self.chat = c
        c.overrideredirect(True)
        c.attributes("-topmost", True)
        c.configure(bg="#0a1220")
        wrap = tk.Frame(c, bg="#0a1220", highlightthickness=1, highlightbackground="#22385e")
        wrap.pack(fill="both", expand=True)

        head = tk.Frame(wrap, bg="#0d1729", height=34)
        head.pack(fill="x")
        tk.Label(head, text="傻鱼", bg="#0d1729", fg="#9fd8ff",
                 font=("Microsoft YaHei", 10, "bold")).pack(side="left", padx=12, pady=6)
        close = tk.Label(head, text="×", bg="#0d1729", fg="#6f8fc4",
                         font=("Microsoft YaHei", 12), cursor="hand2")
        close.pack(side="right", padx=12)
        close.bind("<Button-1>", lambda e: self.close_chat())

        body = tk.Text(wrap, bg="#0a1220", fg="#dbe9ff", bd=0, highlightthickness=0,
                       wrap="word", font=("Microsoft YaHei", 10), state="disabled",
                       padx=12, pady=10, spacing1=4, spacing3=6)
        body.pack(fill="both", expand=True)
        body.tag_configure("me", foreground="#8fd8ff", justify="right")
        body.tag_configure("her", foreground="#e6f2ff")
        body.tag_configure("sys", foreground="#5c7398", justify="center",
                           font=("Microsoft YaHei", 9))
        body.tag_configure("name", foreground="#4f7fb5", font=("Microsoft YaHei", 8))

        foot = tk.Frame(wrap, bg="#0d1729")
        foot.pack(fill="x")
        entry = tk.Entry(foot, bg="#101c31", fg="#dbe9ff", insertbackground="#7fdcff",
                         relief="flat", font=("Microsoft YaHei", 10))
        entry.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=8, ipady=5)
        sendb = tk.Label(foot, text="说", bg="#1b3a63", fg="#cfeeff",
                         font=("Microsoft YaHei", 10, "bold"), padx=14, pady=4, cursor="hand2")
        sendb.pack(side="right", padx=(0, 10), pady=8)

        def append(text, tag="her", name=False):
            body.configure(state="normal")
            if name:
                body.insert("end", ("你\n" if tag == "me" else "傻鱼\n"), "name")
            body.insert("end", str(text).strip() + "\n", tag)
            body.configure(state="disabled")
            body.see("end")

        def load_history():
            try:
                hist = api("/api/desk/history", timeout=6)
            except Exception:
                hist = []
            if not hist:
                append("她记得 QQ 那边的事；你在这里说的，她也记得。", "sys")
                return
            for m in hist[-16:]:
                append(m.get("content", ""), "me" if m.get("role") == "user" else "her", True)

        def done(reply):
            body.configure(state="normal")
            last = body.index("end-2l linestart")
            if body.get(last, "end-1c").startswith("她在想"):
                body.delete(last, "end-1c")
            body.configure(state="disabled")
            append(reply, "her", True)
            sendb.configure(bg="#1b3a63")
            entry.configure(state="normal")
            entry.focus_set()

        def send(event=None):
            text = entry.get().strip()
            if not text:
                return "break"
            entry.delete(0, "end")
            append(text, "me", True)
            append("她在想…", "sys")
            entry.configure(state="disabled")
            sendb.configure(bg="#12233c")

            def work():
                try:
                    o = api("/api/talk", {"text": text}, timeout=120)
                    reply = o.get("reply") or ("出错了：" + str(o.get("error")))
                except Exception as e:
                    reply = "叫不动她：" + str(e)
                self.root.after(0, lambda: done(reply))

            threading.Thread(target=work, daemon=True).start()
            return "break"

        sendb.bind("<Button-1>", send)
        entry.bind("<Return>", send)
        self.place_chat()
        threading.Thread(target=load_history, daemon=True).start()
        entry.focus_set()

    def place_chat(self):
        if self.chat is None or not self.chat.winfo_exists():
            return
        w, h = int(362 * self.scale), int(442 * self.scale)
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        x = self.root.winfo_x() - w - 12
        if x < 8:
            x = self.root.winfo_x() + self.px + 12
        y = min(max(8, self.root.winfo_y() + self.px // 2 - h // 2), sh - h - 48)
        self.chat.geometry(f"{w}x{h}+{x}+{y}")

    def hide(self):
        self.root.withdraw()
        print("[orb] 已隐藏，Ctrl+Alt+S 呼出")

    def show(self):
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.root.geometry(f"{self.px}x{self.px}+{self.root.winfo_x()}+{self.root.winfo_y()}")
        self.blit(int(self.phase) % len(self.frames))
        print("[orb] 已显示")

    def toggle_hide(self):
        if self.root.state() == "withdrawn":
            self.show()
        else:
            self.hide()

    def hotkey_poll(self):
        try:
            down = lambda vk: bool(user32.GetAsyncKeyState(vk) & 0x8000)
            if down(0x11) and down(0x12) and down(ord("S")):
                self.toggle_hide()
                time.sleep(0.4)
        except Exception:
            pass
        self.root.after(300, self.hotkey_poll)

    def quit(self):
        self.save_pos()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    Orb().run()

