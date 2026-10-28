"""Eigene Bedienelemente: Felder mit einfärbbarem Scrollbalken, abgerundete Rechtecke, ModeSwitch, PopupMenu."""

import math
import sys
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from themes import mix_hex

WATCH_MS = 150  # PopupMenu: so oft prüfen, ob das Programm noch im Vordergrund ist


def scrolled(parent, widget=tk.Text, **kw):
    """Text- oder Listenfeld mit ttk-Scrollbalken (der native lässt sich nicht einfärben) → (Rahmen, Feld)."""
    frame = ttk.Frame(parent)
    w = widget(frame, **kw)
    sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=w.yview)
    w.configure(yscrollcommand=sb.set)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    w.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    return frame, w


def _pixel(under: str, fill: str, outline: str | None, width: int, r: int, d: float) -> str:
    """Farbe eines Eck-Pixels im Abstand d vom Mittelpunkt; mit Rand ein Ring der Breite width um denselben Punkt."""
    if not outline:
        return mix_hex(under, fill, r - d + 0.5)
    outer = max(0.0, min(1.0, r - d + 0.5))
    inner = max(0.0, min(1.0, r - width - d + 0.5))
    return mix_hex(under, mix_hex(outline, fill, inner / outer), outer) if outer else under


def _corners(master, cache: dict, r: int, fill: str, under: str, outline: str | None = None, width: int = 0) -> list:
    """Kantengeglättete Viertelkreise (oben links, oben rechts, unten links, unten rechts)."""
    key = (r, fill, under, outline, width)
    if key not in cache:
        imgs = []
        for cx, cy in ((r, r), (0, r), (r, 0), (0, 0)):
            img = tk.PhotoImage(master=master, width=r, height=r)
            rows = []
            for y in range(r):
                row = [_pixel(under, fill, outline, width, r, math.hypot(x + 0.5 - cx, y + 0.5 - cy)) for x in range(r)]
                rows.append("{" + " ".join(row) + "}")
            img.put(" ".join(rows))
            imgs.append(img)
        cache[key] = imgs
    return cache[key]


def rounded(canvas: tk.Canvas, cache: dict, x: float, y: float, w: float, h: float, r: int, fill: str, under: str,
            tags=(), outline: str | None = None, width: int = 1):
    """Abgerundetes Rechteck mit glatten Ecken auf einem Canvas, optional mit Rand (outline, width Pixel).

    Den Rand in einem Stück zeichnen, nicht als zwei Rechtecke übereinander – sonst übermalen die Ecken des inneren
    die geglättete Rundung des äußeren mit eckigen Pixeln."""
    x, y, w, h = round(x), round(y), round(w), round(h)
    r = max(1, min(r, w // 2, h // 2))
    if outline:
        width = max(1, min(width, r - 1)) if r > 1 else 0
        canvas.create_rectangle(x + r, y, x + w - r, y + h, fill=outline, outline="", tags=tags)
        canvas.create_rectangle(x, y + r, x + w, y + h - r, fill=outline, outline="", tags=tags)
        canvas.create_rectangle(x + r, y + width, x + w - r, y + h - width, fill=fill, outline="", tags=tags)
        canvas.create_rectangle(x + width, y + r, x + w - width, y + h - r, fill=fill, outline="", tags=tags)
    else:
        canvas.create_rectangle(x + r, y, x + w - r, y + h, fill=fill, outline="", tags=tags)
        canvas.create_rectangle(x, y + r, x + w, y + h - r, fill=fill, outline="", tags=tags)
    nw, ne, sw, se = _corners(canvas, cache, r, fill, under, outline, width if outline else 0)
    canvas.create_image(x, y, image=nw, anchor="nw", tags=tags)
    canvas.create_image(x + w - r, y, image=ne, anchor="nw", tags=tags)
    canvas.create_image(x, y + h - r, image=sw, anchor="nw", tags=tags)
    canvas.create_image(x + w - r, y + h - r, image=se, anchor="nw", tags=tags)


class ModeSwitch(tk.Canvas):
    """Umschalter: Segmente nebeneinander, die Markierung gleitet beim Wechsel weich zur Auswahl."""

    DURATION = 0.18  # Sekunden für das Gleiten

    def __init__(self, master, items: list[tuple[str, str]], command, scale: float = 1.0):
        self.s = scale
        super().__init__(master, height=round(30 * scale), highlightthickness=0, borderwidth=0, cursor="hand2")
        self.items, self.command = items, command
        self.value: str | None = None
        self.hover: str | None = None
        self.col = {"bg": "#1f1e1d", "track": "#2b2a28", "pill": "#383733", "border": "#d97757",
                    "fg": "#ece9e1", "muted": "#9d998e"}
        self.f_on = tkfont.Font(root=self, family="Segoe UI", size=9, weight="bold")
        self.f_off = tkfont.Font(root=self, family="Segoe UI", size=9)
        self._pill: tuple[float, float] | None = None   # aktuelle Position (x, Breite) der Markierung
        self._anim = None
        self._cache: dict = {}
        self.bind("<Configure>", lambda e: self._redraw(snap=True))
        self.bind("<Button-1>", self._on_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))

    # ------------------------------------------------------------ Außen

    def set_colors(self, **colors):
        self.col.update(colors)
        self._cache.clear()
        self.configure(background=self.col["bg"])
        self._redraw()

    def select(self, value: str, animate: bool = True):
        if value == self.value and self._pill:
            return
        self.value = value
        target = self._target()
        if not animate or not self._pill or not target or not self.winfo_ismapped():
            self._pill = target
            self._redraw()
            return
        start, t0 = self._pill, time.monotonic()
        if self._anim:
            self.after_cancel(self._anim)

        def step():
            t = min(1.0, (time.monotonic() - t0) / self.DURATION)
            k = 1 - (1 - t) ** 3  # sanft abbremsen
            goal = self._target() or start
            self._pill = (start[0] + (goal[0] - start[0]) * k, start[1] + (goal[1] - start[1]) * k)
            self._redraw()
            self._anim = self.after(12, step) if t < 1 else None

        step()

    # ------------------------------------------------------------ Aufteilung & Zeichnen

    def _segments(self) -> list[tuple[str, float, float]]:
        """[(Schlüssel, x, Breite)] – Breite nach Textlänge, zusammen so breit wie das Canvas."""
        w = self.winfo_width()
        if w <= 1:
            return []
        pad = 3 * self.s
        natural = [self.f_on.measure(label) + 20 * self.s for _, label in self.items]
        factor = (w - 2 * pad) / sum(natural)
        out, x = [], pad
        for (key, _), n in zip(self.items, natural):
            out.append((key, x, n * factor))
            x += n * factor
        return out

    def _target(self) -> tuple[float, float] | None:
        for key, x, w in self._segments():
            if key == self.value:
                return x, w
        return None

    def _redraw(self, snap: bool = False):
        if snap and not self._anim:
            self._pill = self._target() or self._pill
        self.delete("all")
        w, h, c, s = self.winfo_width(), self.winfo_height(), self.col, self.s
        if w <= 1:
            return
        rounded(self, self._cache, 0, 0, w, h, round(9 * s), c["track"], c["bg"])
        if self._pill:
            x, pw = self._pill
            inset = 3 * s
            rounded(self, self._cache, x, inset, pw, h - 2 * inset, round(7 * s), c["pill"], c["track"],
                    outline=c["border"])
        for key, x, sw in self._segments():
            label = dict(self.items)[key]
            on = key == self.value
            color = c["fg"] if on or key == self.hover else mix_hex(c["muted"], c["fg"], 0.15)
            self.create_text(x + sw / 2, h / 2, text=label, fill=color, font=self.f_on if on else self.f_off)

    # ------------------------------------------------------------ Maus

    def _key_at(self, x: float) -> str | None:
        for key, sx, sw in self._segments():
            if sx <= x < sx + sw:
                return key
        return None

    def _on_click(self, e):
        key = self._key_at(e.x)
        if key and key != self.value:
            self.command(key)

    def _on_motion(self, e):
        self._set_hover(self._key_at(e.x))

    def _set_hover(self, key):
        if key != self.hover:
            self.hover = key
            self._redraw()


def _work_area(x: int, y: int, widget: tk.Misc) -> tuple[int, int, int, int]:
    """Arbeitsbereich (ohne Taskleiste) des Bildschirms, auf dem der Punkt liegt: links, oben, rechts, unten."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class MonitorInfo(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                            ("dwFlags", wintypes.DWORD)]
            user32 = ctypes.windll.user32
            user32.MonitorFromPoint.restype = ctypes.c_void_p
            user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
            user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MonitorInfo)]
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(user32.MonitorFromPoint(wintypes.POINT(x, y), 2), ctypes.byref(info)):
                r = info.rcWork
                return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
    return 0, 0, widget.winfo_screenwidth(), widget.winfo_screenheight()


def _app_active() -> bool:
    """Gehört das Vordergrundfenster zu diesem Programm? (Ohne Fenster im Vordergrund – kurz beim Umschalten – ja.)"""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        import os
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = ctypes.c_void_p
        user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return True
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value == os.getpid()
    except Exception:
        return True


def _round_window(win: tk.Misc, border: str):
    """Windows 11: kleine runde Ecken wie bei Systemmenüs, Rahmenlinie in der Designfarbe (sonst wirkungslos)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(win.wm_frame(), 16)
        dwm = ctypes.windll.dwmapi
        corner = ctypes.c_int(3)  # DWMWCP_ROUNDSMALL
        dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
        r, g, b = (int(border[i:i + 2], 16) for i in (1, 3, 5))
        color = ctypes.c_uint(r | g << 8 | b << 16)
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(color), ctypes.sizeof(color))
    except Exception:
        pass


class PopupMenu:
    """Kontextmenü im Design, mit den Aufrufen von tk.Menu (add_command, entryconfigure(i, state=…), tk_popup,
    grab_release). Das native Menü hat unter Windows immer den klassischen hellen Rahmen (1 px grau + 2 px #f0f0f0 in
    Systemfarben) – auch im dunklen Design; weder Tk-Optionen noch der Dunkelmodus von uxtheme ändern ihn. In eigenen
    Designs deshalb ein randloses Fenster, im Design „Windows-Standard“ (Palette None) das native Menü.
    tk_popup wartet wie das native Menü, bis es zu ist; der gewählte Befehl läuft erst danach (after_idle)."""

    def __init__(self, master: tk.Misc, scale: float = 1.0):
        self.master, self.s = master, scale
        self.items: list[list] = []        # [Text, Befehl, Zustand]
        self.pal: dict | None = None
        self.native = tk.Menu(master, tearoff=0)
        self.win: tk.Toplevel | None = None
        self._labels: list[tk.Label] = []
        self._active: int | None = None
        self._pressed = False              # Maustaste wurde im Menü gedrückt (sonst löst Loslassen nichts aus)
        self._grabbed = False
        self._chosen = None

    # ------------------------------------------------------------ wie tk.Menu

    def add_command(self, label: str, command):
        self.items.append([label, command, tk.NORMAL])
        self.native.add_command(label=label, command=command)

    def entryconfigure(self, index: int, state: str):
        self.items[index][2] = state
        self.native.entryconfigure(index, state=state)

    def grab_release(self):
        """Nichts zu tun: das eigene Fenster gibt den Griff beim Schließen frei."""

    def winfo_exists(self) -> bool:
        return bool(self.master.winfo_exists())

    def set_palette(self, pal: dict | None):
        """Aus ThemeManager.register_menu und bei jedem Designwechsel; None = Windows-Standard."""
        self.pal = pal

    def tk_popup(self, x: int, y: int):
        if not self.pal:
            try:
                self.native.tk_popup(x, y)
            finally:
                self.native.grab_release()
            return
        self.close()
        win = self._build()
        self._place(win, x, y)
        try:
            win.grab_set()
            self._grabbed = True
        except tk.TclError:
            self._grabbed = False
        win.focus_force()
        win.after(WATCH_MS, self._watch)
        win.wait_window()
        command, self._chosen = self._chosen, None
        if command:
            self.master.after_idle(command)

    def close(self):
        win, self.win = self.win, None
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass

    # ------------------------------------------------------------ Fenster

    def _build(self) -> tk.Toplevel:
        p, s = self.pal, self.s
        win = self.win = tk.Toplevel(self.master)
        win.withdraw()
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        box = tk.Frame(win, background=p["surface"], highlightthickness=1, highlightbackground=p["border"],
                       highlightcolor=p["border"], padx=round(4 * s), pady=round(4 * s))
        box.pack(fill=tk.BOTH, expand=True)
        font = tkfont.nametofont("TkMenuFont")
        self._labels, self._active, self._pressed = [], None, False
        for i, (label, _command, _state) in enumerate(self.items):
            lab = tk.Label(box, text=label, anchor="w", font=font, borderwidth=0, padx=round(12 * s),
                           pady=round(4 * s))
            lab.pack(fill=tk.X)
            lab.bind("<Enter>", lambda e, i=i: self._activate(i))
            lab.bind("<Leave>", lambda e: self._activate(None))
            lab.bind("<ButtonRelease-1>", lambda e, i=i: self._release(e, i))
            self._labels.append(lab)
        self._paint()
        win.bind("<ButtonPress>", self._press)
        win.bind("<Escape>", lambda e: self.close())
        win.bind("<Up>", lambda e: self._step(-1))
        win.bind("<Down>", lambda e: self._step(1))
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            win.bind(key, lambda e: self._invoke(self._active))
        win.bind("<FocusOut>", lambda e: win.after(10, self._check_focus))
        return win

    def _place(self, win: tk.Toplevel, x: int, y: int):
        """An (x, y) zeigen, am Bildschirmrand nach links bzw. oben klappen."""
        win.update_idletasks()
        w, h = max(win.winfo_reqwidth(), round(120 * self.s)), win.winfo_reqheight()
        left, top, right, bottom = _work_area(x, y, win)
        if x + w > right:
            x = max(left, x - w)
        if y + h > bottom:
            y = max(top, y - h)
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.attributes("-alpha", 0.0)  # erst nach dem Runden der Ecken zeigen (sonst kurz eckig)
        win.deiconify()
        win.update_idletasks()
        _round_window(win, self.pal["border"])
        win.attributes("-alpha", 1.0)

    def _paint(self):
        p = self.pal
        for i, lab in enumerate(self._labels):
            if self.items[i][2] == tk.DISABLED:
                lab.configure(background=p["surface"], foreground=mix_hex(p["muted"], p["surface"], 0.3))
            elif i == self._active:
                lab.configure(background=p["select_bg"], foreground=p["select_fg"])
            else:
                lab.configure(background=p["surface"], foreground=p["fg"])

    def _enabled(self) -> list[int]:
        return [i for i, item in enumerate(self.items) if item[2] != tk.DISABLED]

    def _activate(self, index: int | None):
        if index is not None and index not in self._enabled():
            index = None
        if index != self._active:
            self._active = index
            self._paint()

    def _step(self, delta: int):
        enabled = self._enabled()
        if not enabled:
            return
        if self._active not in enabled:
            self._activate(enabled[0] if delta > 0 else enabled[-1])
        else:
            self._activate(enabled[(enabled.index(self._active) + delta) % len(enabled)])

    def _invoke(self, index: int | None):
        if index is not None and index in self._enabled():
            self._chosen = self.items[index][1]
            self.close()

    # ------------------------------------------------------------ Maus und Fokus

    def _inside(self, x: int, y: int) -> bool:
        win = self.win
        return bool(win) and win.winfo_rootx() <= x < win.winfo_rootx() + win.winfo_width() \
            and win.winfo_rooty() <= y < win.winfo_rooty() + win.winfo_height()

    def _press(self, e):
        """Mit dem Griff kommt jeder Klick im Programm hier an – außerhalb des Menüs schließt er es (wie nativ)."""
        self._pressed = self._inside(e.x_root, e.y_root)
        if not self._pressed:
            self.close()
        return "break"

    def _release(self, e, index: int):
        if self._pressed and str(e.widget.winfo_containing(e.x_root, e.y_root)) == str(e.widget):
            self._invoke(index)

    def _watch(self):
        """Solange offen: schließen, wenn ein anderes Programm in den Vordergrund kommt oder ein Dialog den Griff
        übernimmt. Auf <FocusOut> allein ist kein Verlass – ein randloses Fenster bekommt unter Windows nicht immer
        selbst den Fokus, dann bliebe das Menü (immer im Vordergrund) über anderen Programmen stehen."""
        win = self.win
        if win is None:
            return
        try:
            lost = self._grabbed and str(win.grab_current()) != str(win)
        except (KeyError, tk.TclError):
            lost = True
        if lost or not _app_active():
            self.close()
        else:
            win.after(WATCH_MS, self._watch)

    def _check_focus(self):
        """Fokus ging an ein anderes Programm (oder anderswohin) → schließen."""
        win = self.win
        if win is None:
            return
        try:
            focus = win.focus_get()
        except (KeyError, tk.TclError):
            focus = None
        if focus is None or not str(focus).startswith(str(win)):
            self.close()
