"""Farbschemata (Designs) für Monhip.

Neue Designs: einfach einen weiteren Eintrag in THEMES mit denselben Schlüsseln anlegen.
"""

from i18n import tr

import base64
import math
import struct
import sys
import tkinter as tk
import zlib
from tkinter import font as tkfont
from tkinter import ttk

FONT = ("Segoe UI", 9)

THEMES = {
    "dark": {
        "label": tr('Dunkel (Grau/Orange)'),
        "dark": True,
        "bg": "#262624",          # Hauptfläche / Chat
        "sidebar": "#1f1e1d",     # Chatliste links
        "side_sel": "#383733",    # ausgewählter Chat
        "side_hover": "#2b2a28",
        "surface": "#30302e",     # Eingabefelder, Listen
        "raised": "#3b3a36",      # Knöpfe, Reiter, Scrollbalken
        "hover": "#4a4843",
        "border": "#45433e",
        "fg": "#ece9e1",
        "muted": "#9d998e",
        "accent": "#d97757",
        "accent_hover": "#e3896a",
        "accent_fg": "#1f1e1d",
        "select_bg": "#5e3b2d",
        "select_fg": "#ffffff",
        # Chatverlauf (chatview.py)
        "chat": {
            "fg": "#ece9e1", "muted": "#9d998e", "accent": "#e3896a",
            "bubble": "#b65f3f", "bubble_fg": "#fff8f3",
            "code_bg": "#1e1d1b", "code_hdr": "#2d2c29", "code_fg": "#e6e2d8",
            "think_bg": "#2c2b28", "think_fg": "#aaa69b", "link": "#ec9f80", "rule": "#45433e",
            "error": "#ff7b72", "ok": "#7ec699", "warn": "#e8a75a",
            "kw": "#cc99cd", "str": "#9fd28a", "com": "#7d7a72", "num": "#f0a45d",
            # Namensfarben der Teilnehmer im Gruppenchat (Teamwork)
            "people": ["#e3896a", "#7ec699", "#8fb4f0", "#d7a0e8", "#e8c46a", "#6fd1d1"],
        },
    },
    "light": {
        "label": tr('Hell (Weiß/Violett)'),
        "dark": False,
        "bg": "#ffffff",
        "sidebar": "#f5f2fe",
        "side_sel": "#e7dffd",
        "side_hover": "#eee8fe",
        "surface": "#ffffff",
        "raised": "#efeafc",
        "hover": "#e2d9f9",
        "border": "#dcd4f1",
        "fg": "#1f1b2d",
        "muted": "#6c6784",
        "accent": "#7c3aed",
        "accent_hover": "#6d28d9",
        "accent_fg": "#ffffff",
        "select_bg": "#e2d8fd",
        "select_fg": "#3b1a7a",
        "chat": {
            "fg": "#1f1b2d", "muted": "#6c6784", "accent": "#7c3aed",
            "bubble": "#7c3aed", "bubble_fg": "#ffffff",
            "code_bg": "#f6f4fb", "code_hdr": "#ebe6f8", "code_fg": "#2a2540",
            "think_bg": "#f8f6fd", "think_fg": "#5f5a75", "link": "#6d28d9", "rule": "#dcd4f1",
            "error": "#c81e1e", "ok": "#2f8a4c", "warn": "#b45309",
            "kw": "#7c3aed", "str": "#2f7d32", "com": "#8b87a0", "num": "#b4530b",
            "people": ["#c2410c", "#15803d", "#1d4ed8", "#9333ea", "#a16207", "#0e7490"],
        },
    },
    "system": {
        "label": tr('Windows-Standard'),
        "dark": False,
        "chat": {
            "fg": "#1b1b1b", "muted": "#6b6b6b", "accent": "#0b63c5",
            "bubble": "#e4e4e9", "bubble_fg": "#1b1b1b",
            "code_bg": "#f5f5f5", "code_hdr": "#e9e9e9", "code_fg": "#1b1b1b",
            "think_bg": "#f7f7f7", "think_fg": "#555555", "link": "#0b63c5", "rule": "#d0d0d0",
            "error": "#c01c28", "ok": "#26a269", "warn": "#a15c00",
            "kw": "#1a5fb4", "str": "#a31515", "com": "#008000", "num": "#098658",
            "people": ["#c2410c", "#15803d", "#1d4ed8", "#9333ea", "#a16207", "#0e7490"],
        },
    },
}

TEXT_OPTS = ("background", "foreground", "insertbackground", "selectbackground", "selectforeground",
             "highlightthickness", "highlightbackground", "highlightcolor", "borderwidth", "relief")
LIST_OPTS = ("background", "foreground", "selectbackground", "selectforeground",
             "highlightthickness", "highlightbackground", "highlightcolor", "borderwidth", "relief")
MENU_OPTS = ("background", "foreground", "activebackground", "activeforeground", "borderwidth", "relief")


def label_to_key(label: str) -> str:
    return next((k for k, t in THEMES.items() if t["label"] == label), "dark")


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def _mix(a: tuple, b: tuple, t: float) -> tuple:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def mix_hex(a: str, b: str, t: float) -> str:
    """Mischt zwei Farben #RRGGBB (t=0 → a, t=1 → b)."""
    return "#%02x%02x%02x" % _mix(_rgb(a), _rgb(b), max(0.0, min(1.0, t)))


def _draw_checkbox(img: tk.PhotoImage, size: int, bg: str, border: str, fill: str, mark: str | None):
    """Zeichnet ein Kästchen mit runden Ecken (und ggf. Haken) kantengeglättet in ein PhotoImage."""
    bg_c, border_c, fill_c = _rgb(bg), _rgb(border), _rgb(fill)
    mark_c = _rgb(mark) if mark else None
    c, half, r, bw = size / 2, size / 2 - 0.5, size * 0.2, max(1.0, size / 14)
    pts = [(0.26 * size, 0.52 * size), (0.43 * size, 0.69 * size), (0.75 * size, 0.33 * size)]
    stroke = max(1.6, size * 0.13)

    def seg_dist(px, py, a, b):
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5

    rows = []
    for y in range(size):
        row = []
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            qx, qy = abs(px - c) - (half - r), abs(py - c) - (half - r)
            d = (max(qx, 0) ** 2 + max(qy, 0) ** 2) ** 0.5 + min(max(qx, qy), 0) - r
            col = _mix(bg_c, border_c, max(0.0, min(1.0, 0.5 - d)))
            col = _mix(col, fill_c, max(0.0, min(1.0, 0.5 - (d + bw))))
            if mark_c:
                dist = min(seg_dist(px, py, pts[0], pts[1]), seg_dist(px, py, pts[1], pts[2]))
                col = _mix(col, mark_c, max(0.0, min(1.0, stroke / 2 + 0.5 - dist)))
            row.append("#%02x%02x%02x" % col)
        rows.append("{" + " ".join(row) + "}")
    img.put(" ".join(rows), to=(0, 0))


def _png(w: int, h: int, rows: list[bytes]) -> str:
    """PNG (RGB, base64) aus fertigen Bildzeilen."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"".join(b"\x00" + row for row in rows)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return base64.b64encode(data).decode("ascii")


def _pixels(w: int, h: int, color) -> list[bytes]:
    """Bildzeilen aus color(x, y) -> (r, g, b), abgefragt in den Pixelmitten."""
    return [bytes(c for x in range(w) for c in color(x + 0.5, y + 0.5)) for y in range(h)]


def _rounded_png(r: int, mid: int, fill: str, border: str, under: str, bw: float) -> str:
    """Rechteck mit runden, kantengeglätteten Ecken auf der Farbe under – als Vorlage für ein 9-Teile-Bildelement
    (Rand r + 1). Bewusst undurchsichtig: halbtransparente Bilder mischt Tk unter Windows bei jedem Zeichnen neu.
    Die Mitte ist mid Pixel groß, weil ttk sie kachelt statt dehnt – bei 1 Pixel wären das zehntausende
    Zeichenaufrufe je Feld (Chatfeld: 2,7 s statt 0,1 ms)."""
    fill_c, border_c, under_c = _rgb(fill), _rgb(border), _rgb(under)
    k = r + 1
    half = k + 0.5  # kleines Bild: 2k + 1 Pixel, Spalte/Zeile k ist die gerade Mitte

    def color(x, y):
        qx, qy = abs(x - half) - (half - r), abs(y - half) - (half - r)
        d = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r
        outer = max(0.0, min(1.0, 0.5 - d))
        if not outer:
            return under_c
        inner = max(0.0, min(1.0, 0.5 - (d + bw)))
        return _mix(under_c, _mix(border_c, fill_c, inner / outer), outer)

    small = _pixels(2 * k + 1, 2 * k + 1, color)
    rows = [row[:3 * k] + row[3 * k:3 * k + 3] * mid + row[3 * k + 3:] for row in small]
    rows = rows[:k] + rows[k:k + 1] * mid + rows[k + 1:]
    return _png(2 * k + mid, 2 * k + mid, rows)


def _chevron_png(w: int, h: int, x0: float, y0: float, aw: float, ah: float, color: str, under: str,
                 stroke: float) -> str:
    """Pfeil „⌄“ (Aufklappen) auf der Farbe under."""
    col, under_c = _rgb(color), _rgb(under)
    pts = ((x0, y0), (x0 + aw / 2, y0 + ah), (x0 + aw, y0))

    def dist(px, py, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0.0, min(1.0, ((px - a[0]) * dx + (py - a[1]) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - a[0] - t * dx, py - a[1] - t * dy)

    def color(x, y):
        d = min(dist(x, y, pts[0], pts[1]), dist(x, y, pts[1], pts[2]))
        return _mix(under_c, col, max(0.0, min(1.0, stroke / 2 + 0.5 - d)))

    return _png(w, h, _pixels(w, h, color))


def _colorref(hex_color: str) -> int:
    """#RRGGBB -> Windows COLORREF (0x00BBGGRR)."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return r | (g << 8) | (b << 16)


def _frame_hwnd(win: tk.Misc) -> int:
    """Fenstergriff des äußeren Windows-Rahmens (dort sitzt die Titelleiste). Den gibt es erst, wenn das
    Fenster einmal angezeigt wurde – vorher ins Leere gesetzte Farben sind der Grund für weiße Titelleisten."""
    try:
        return int(win.wm_frame(), 16)
    except (tk.TclError, ValueError):
        import ctypes
        return ctypes.windll.user32.GetParent(win.winfo_id())


def set_titlebar(win: tk.Misc, pal: dict | None):
    """Färbt die Windows-Titelleiste passend (Windows 11; unter Windows 10 nur hell/dunkel).
    Wirkt nur bei angezeigten Fenstern – ThemeManager ruft es deshalb auch beim Erscheinen (<Map>) auf."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = _frame_hwnd(win)
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi
        dark = ctypes.c_int(1 if pal and pal["dark"] else 0)
        if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark)) != 0:
            dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(dark), ctypes.sizeof(dark))
        default = 0xFFFFFFFF
        caption = ctypes.c_uint(_colorref(pal["bg"]) if pal else default)
        text = ctypes.c_uint(_colorref(pal["fg"]) if pal else default)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), ctypes.sizeof(caption))
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text), ctypes.sizeof(text))
        # Rahmen neu zeichnen lassen (SWP_NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED)
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
    except Exception:
        pass


_resize_redraw_off = False


def no_resize_redraw(win: tk.Misc):
    """Windows zeichnet Tk-Fenster bei jeder Größenänderung komplett neu (Fensterklassen „TkTopLevel“ und „TkChild“
    mit CS_HREDRAW|CS_VREDRAW) – auch jedes Bedienelement, das sich gar nicht ändert. Tk zeichnet geänderte Elemente
    ohnehin selbst neu; ohne die beiden Klassen-Stile ist Ziehen am Fensterrand 3–4-mal so schnell (langer Chat
    83 → 22 ms je Schritt). Der Stil gehört zur Klasse, gilt also für alle Fenster – einmal genügt."""
    global _resize_redraw_off
    if _resize_redraw_off or sys.platform != "win32":
        return
    try:
        import ctypes
        user32 = ctypes.windll.user32
        user32.GetClassLongPtrW.restype = ctypes.c_size_t
        user32.GetClassLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        user32.SetClassLongPtrW.restype = ctypes.c_size_t
        user32.SetClassLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t]
        user32.GetClassNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]
        name = ctypes.create_unicode_buffer(32)
        for hwnd in (_frame_hwnd(win), win.winfo_id()):
            user32.GetClassNameW(hwnd, name, 32)
            if name.value in ("TkTopLevel", "TkChild"):  # nur Tks eigene Klassen (GCL_STYLE = -26, ~CS_H/VREDRAW)
                user32.SetClassLongPtrW(hwnd, -26, user32.GetClassLongPtrW(hwnd, -26) & ~0x3)
        _resize_redraw_off = True
    except Exception:
        pass


def fade(win: tk.Misc, start: float, end: float, ms: int = 140, done=None):
    """Blendet ein Fenster weich ein/aus (Fenster-Transparenz, ca. 60 Schritte pro Sekunde, sanft abgebremst)."""
    steps = max(1, ms // 16)

    def step(i: int):
        try:
            if not win.winfo_exists():
                return
            t = i / steps
            t = 1 - (1 - t) ** 3  # weich auslaufen
            win.attributes("-alpha", start + (end - start) * t)
        except tk.TclError:
            return
        if i < steps:
            win.after(16, step, i + 1)
        elif done:
            done()

    step(1)


class ThemeManager:
    """Wendet ein Design auf alle ttk-Widgets und die registrierten klassischen tk-Widgets an."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.style = ttk.Style(root)
        names = self.style.theme_names()
        self.native = "vista" if "vista" in names else self.style.theme_use()
        self.key = "system"
        self.pal: dict | None = None
        self._texts: list[tk.Text] = []
        self._lists: list[tk.Listbox] = []
        self._combos: list[ttk.Combobox] = []
        self._menus: list[tk.Menu] = []
        self._windows: list[tk.Misc] = [root]
        self._fields: list[ttk.Frame] = []
        self._orig: dict[str, dict] = {}
        self._roles: dict[str, str] = {}
        self._root_bg = root.cget("background")
        line = tkfont.Font(root=root, font=(FONT[0], 10)).metrics("linespace")
        self.row_height = round(line * 2.1)
        # Häkchen-Bilder, mitwachsend mit der Windows-Skalierung
        self._check_size = max(13, round(10.5 * float(root.tk.call("tk", "scaling"))))
        self._img_off = tk.PhotoImage(master=root, width=self._check_size, height=self._check_size)
        self._img_on = tk.PhotoImage(master=root, width=self._check_size, height=self._check_size)
        self._check_element = False
        # Abgerundete Bildelemente (Knöpfe, Felder, Kärtchen): Bilder werden beim Designwechsel neu gemalt
        self.scale = max(1.0, float(root.tk.call("tk", "scaling")) / 1.333)
        self._images: dict[str, tk.PhotoImage] = {}
        self._elements: set[str] = set()

    # ------------------------------------------------------------ Registrierung

    def _remember(self, w, opts):
        self._orig[str(w)] = {k: w.cget(k) for k in opts}

    def register_text(self, w: tk.Text, role: str = "field"):
        """role "field": Eingabefeld mit Rahmen, "plain": randlos auf dem Hintergrund (Chatverlauf),
        "inner": randlos in einem abgerundeten Rahmen (register_field)."""
        self._remember(w, TEXT_OPTS)
        self._roles[str(w)] = role
        self._texts.append(w)
        self._style_text(w)
        return w

    def register_menu(self, m):
        """tk.Menu oder widgets.PopupMenu (eigenes Menüfenster, bekommt nur die Palette über set_palette)."""
        if not hasattr(m, "set_palette"):
            self._remember(m, MENU_OPTS)
        self._menus.append(m)
        self._style_menu(m)
        return m

    def register_list(self, w: tk.Listbox):
        self._remember(w, LIST_OPTS)
        self._lists.append(w)
        self._style_list(w)
        return w

    def register_combo(self, cb: ttk.Combobox):
        self._combos.append(cb)
        self._style_combo(cb)
        return cb

    def register_field(self, frame: ttk.Frame, w: tk.Text):
        """Textfeld mit runden Ecken: frame (Stil „Input.TFrame“) zeichnet Fläche und Rand, w liegt randlos darin."""
        w.bind("<FocusIn>", lambda e: frame.state(["focus"]), add="+")
        w.bind("<FocusOut>", lambda e: frame.state(["!focus"]), add="+")
        frame.bind("<Button-1>", lambda e: w.focus_set())
        self._fields.append(frame)
        self.register_text(w, role="inner")
        self._style_field(frame)
        return w

    def register_window(self, win: tk.Toplevel):
        self._windows.append(win)
        self._style_window(win)
        return win

    def present(self, win: tk.Misc, geometry: str | None = None, fade_ms: int = 140):
        """Fenster sauber zeigen: unsichtbar platzieren, Titelleiste einfärben, dann weich einblenden –
        kein weißes Aufblitzen, kein Springen an die richtige Stelle."""
        try:
            win.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        if geometry:
            win.geometry(geometry)
        win.deiconify()
        win.lift()  # nötig: beim Start versteckt angelegte Fenster erscheinen unter Windows sonst gar nicht
        win.update_idletasks()      # jetzt existiert der Windows-Rahmen …
        set_titlebar(win, self.pal)  # … und die Farbe greift
        no_resize_redraw(win)
        fade(win, 0.0, 1.0, fade_ms)

    # ------------------------------------------------------------ Anwenden

    def apply(self, key: str) -> dict:
        if key not in THEMES:
            key = "dark"
        self.key = key
        self.pal = None if key == "system" else THEMES[key]
        if self.pal:
            self._style_ttk(self.pal)
        else:
            s = self.style
            s.theme_use(self.native)
            s.configure("Muted.TLabel", foreground="#555555")
            s.configure("Accent.TButton", font=(FONT[0], 9, "bold"))
            s.configure("Sidebar.Treeview", rowheight=self.row_height, font=(FONT[0], 10))
            s.configure("Sidebar.TButton", anchor="w", padding=(10, 6))
            s.configure("Sidebar.TLabel", foreground="#555555", font=(FONT[0], 8, "bold"))
            s.configure("Title.TLabel", font=(FONT[0], 11, "bold"))
            s.configure("Chip.TFrame", relief="solid", borderwidth=1)
            s.configure("Chip.TLabel", font=(FONT[0], 9))
            s.configure("ChipInfo.TLabel", foreground="#666666", font=(FONT[0], 8))
            s.configure("ChipError.TLabel", foreground="#c01c28", font=(FONT[0], 8))
            s.configure("Chip.TButton", padding=(2, 0), width=2)
            s.configure("SidebarText.TLabel", font=(FONT[0], 9))
            s.configure("SidebarMuted.TLabel", foreground="#666666", font=(FONT[0], 8))
            s.configure("SidebarTitle.TLabel", font=(FONT[0], 11, "bold"))
            s.configure("SidebarOk.TLabel", foreground="#26a269", font=(FONT[0], 8))
            s.configure("SidebarWarn.TLabel", foreground="#c01c28", font=(FONT[0], 8))
            s.configure("Attach.TButton", font=(FONT[0], 14), padding=(6, 0))
        for lst, fn in ((self._texts, self._style_text), (self._lists, self._style_list),
                        (self._combos, self._style_combo), (self._menus, self._style_menu),
                        (self._windows, self._style_window), (self._fields, self._style_field)):
            lst[:] = [w for w in lst if self._alive(w)]
            for w in lst:
                fn(w)
        return THEMES[key]

    @staticmethod
    def _alive(w) -> bool:
        try:
            return bool(w.winfo_exists())
        except tk.TclError:
            return False

    def _style_window(self, win):
        win.configure(background=self.pal["bg"] if self.pal else self._root_bg)
        if not getattr(win, "_titlebar_hook", False):
            # Beim (ersten und jedem weiteren) Erscheinen die Titelleiste färben – vorher gibt es sie noch nicht
            win.bind("<Map>", lambda e, w=win: set_titlebar(w, self.pal) if e.widget is w else None, add="+")
            win._titlebar_hook = True
        if win.winfo_ismapped():
            set_titlebar(win, self.pal)

    def _style_text(self, w: tk.Text):
        p = self.pal
        if not p:
            w.configure(**self._orig[str(w)])
            return
        role = self._roles.get(str(w))
        w.configure(background=p["bg"] if role == "plain" else p["surface"], foreground=p["fg"],
                    insertbackground=p["fg"], selectbackground=p["select_bg"], selectforeground=p["select_fg"],
                    highlightthickness=1 if role == "field" else 0, highlightbackground=p["border"],
                    highlightcolor=p["accent"], borderwidth=0, relief=tk.FLAT)

    def _style_field(self, frame: ttk.Frame):
        # Abstand zum runden Rand, damit das eckige Textfeld nicht über die Ecken ragt; „system“ bleibt nativ
        frame.configure(padding=round(5 * self.scale) if self.pal else 0)

    def _style_menu(self, m):
        p = self.pal
        if hasattr(m, "set_palette"):
            m.set_palette(p)
            return
        if not p:
            m.configure(**self._orig[str(m)])
            return
        m.configure(background=p["surface"], foreground=p["fg"], activebackground=p["select_bg"],
                    activeforeground=p["select_fg"], borderwidth=1, relief=tk.SOLID)

    def _style_list(self, w: tk.Listbox):
        p = self.pal
        if not p:
            w.configure(**self._orig[str(w)])
            return
        w.configure(background=p["surface"], foreground=p["fg"], selectbackground=p["select_bg"],
                    selectforeground=p["select_fg"], highlightthickness=1, highlightbackground=p["border"],
                    highlightcolor=p["accent"], borderwidth=0, relief=tk.FLAT)

    def _style_combo(self, cb: ttk.Combobox):
        """Die Aufklappliste einer Combobox ist ein klassisches tk-Widget und braucht eigene Farben."""
        try:
            popdown = cb.tk.eval(f"ttk::combobox::PopdownWindow {cb}")
            lb = f"{popdown}.f.l"
            if self.pal:
                p = self.pal
                cb.tk.call(lb, "configure", "-background", p["surface"], "-foreground", p["fg"],
                           "-selectbackground", p["select_bg"], "-selectforeground", p["select_fg"],
                           "-font", FONT)
            else:
                for opt in ("-background", "-foreground", "-selectbackground", "-selectforeground"):
                    default = cb.tk.call(lb, "configure", opt)[3]
                    cb.tk.call(lb, "configure", opt, default)
        except tk.TclError:
            pass

    def _image(self, name: str, data: str) -> tk.PhotoImage:
        """Bild anlegen bzw. neu malen – die Elemente behalten so dasselbe Bild über Designwechsel hinweg."""
        img = self._images.get(name)
        if img is None:
            img = self._images[name] = tk.PhotoImage(master=self.root, data=data, format="png")
        else:
            img.configure(data=data, format="png")
        return img

    def _round(self, element: str, r: float, under: str, looks: list, padding=1):
        """Abgerundetes, mitwachsendes Bildelement. under = Farbe hinter dem Element (füllt die Ecken);
        looks = [(zustand, füllung, rand), …]: der erste passende Zustand gewinnt, der letzte (None) ist normal."""
        r = max(2, round(r * self.scale))
        bw = max(1, round(self.scale))
        imgs = [(state, self._image(f"{element}:{i}", _rounded_png(r, 64, fill, border, under, bw)))
                for i, (state, fill, border) in enumerate(looks)]
        if element not in self._elements:
            # width/height: Mindestgröße – sonst wäre jeder Knopf so groß wie das Bild mit seiner breiten Mitte
            self.style.element_create(element, "image", imgs[-1][1], *imgs[:-1], border=r + 1, padding=padding,
                                      sticky="nsew", width=2 * r + 3, height=2 * r + 3)
            self._elements.add(element)

    def _round_button(self, style: str, element: str, r: float, under: str, looks: list):
        """Knopf-Stil mit runden Ecken (die Fläche malt das Bild, Hintergrund-Optionen spielen keine Rolle)."""
        self._round(element, r, under, looks)
        self.style.layout(style, [(element, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"})]})]})])

    def _style_ttk(self, p: dict):
        s = self.style
        s.theme_use("clam")
        flat = dict(lightcolor=p["bg"], darkcolor=p["bg"], bordercolor=p["border"])

        s.configure(".", background=p["bg"], foreground=p["fg"], fieldbackground=p["surface"],
                    troughcolor=p["surface"], focuscolor=p["accent"], selectbackground=p["select_bg"],
                    selectforeground=p["select_fg"], insertcolor=p["fg"], arrowcolor=p["muted"],
                    font=FONT, **flat)
        s.map(".", background=[("disabled", p["bg"])], foreground=[("disabled", p["muted"])],
              selectbackground=[], selectforeground=[])

        s.configure("TFrame", background=p["bg"])
        s.configure("TLabel", background=p["bg"], foreground=p["fg"])
        s.configure("Muted.TLabel", foreground=p["muted"])

        # Knöpfe mit runden Ecken (Bildelemente, Ecken in der Farbe dahinter)
        s.configure("TButton", foreground=p["fg"], padding=(10, 3), anchor="center")
        s.map("TButton", foreground=[("disabled", p["muted"])])
        self._round_button("TButton", "MS.Button.border", 7, p["bg"], [
            ("disabled", p["bg"], p["border"]), ("pressed", p["border"], p["border"]),
            ("active", p["hover"], p["hover"]), ("focus", p["raised"], p["accent"]),
            (None, p["raised"], p["border"])])
        s.configure("Accent.TButton", foreground=p["accent_fg"], font=(FONT[0], 9, "bold"))
        s.map("Accent.TButton", foreground=[("disabled", p["muted"])])
        self._round_button("Accent.TButton", "MS.Accent.border", 7, p["bg"], [
            ("disabled", p["raised"], p["raised"]), ("pressed", p["accent_hover"], p["accent_hover"]),
            ("active", p["accent_hover"], p["accent_hover"]), (None, p["accent"], p["accent"])])

        # Eingabefelder und Auswahllisten: gemeinsamer runder Rahmen, Rand beim Darüberfahren heller
        self._round("MS.Field.field", 7, p["bg"], [
            ("disabled", p["bg"], p["border"]), ("focus", p["surface"], p["accent"]),
            ("hover", p["surface"], mix_hex(p["border"], p["muted"], 0.45)), (None, p["surface"], p["border"])])
        s.configure("TEntry", foreground=p["fg"], insertcolor=p["fg"], padding=(5, 2))
        s.layout("TEntry", [("MS.Field.field", {"sticky": "nswe", "children": [
            ("Entry.padding", {"sticky": "nswe", "children": [
                ("Entry.textarea", {"sticky": "nswe"})]})]})])
        # Pfeil „⌄“ statt des eckigen Pfeilknopfs (auf der Feldfarbe; gesperrt ist das Feld so hell wie bg)
        k = self.scale
        aw, ah, left, right = 9 * k, 4.5 * k, 4 * k, 9 * k
        w, h = round(aw + left + right), round(ah + 6 * k)
        arrows = [self._image(f"MS.Combobox.downarrow:{i}",
                              _chevron_png(w, h, left, 3 * k, aw, ah, color, under, 1.4 * k))
                  for i, (color, under) in enumerate(((mix_hex(p["muted"], p["bg"], 0.4), p["bg"]),
                                                      (p["muted"], p["surface"])))]
        if "MS.Combobox.downarrow" not in self._elements:
            s.element_create("MS.Combobox.downarrow", "image", arrows[1], ("disabled", arrows[0]), sticky="")
            self._elements.add("MS.Combobox.downarrow")
        s.configure("TCombobox", foreground=p["fg"], padding=(5, 2))
        s.layout("TCombobox", [("MS.Field.field", {"sticky": "nswe", "children": [
            ("MS.Combobox.downarrow", {"side": "right", "sticky": ""}),
            ("Combobox.padding", {"expand": "1", "sticky": "nswe", "children": [
                ("Combobox.textarea", {"sticky": "nswe"})]})]})])
        s.map("TCombobox", fieldbackground=[("readonly", p["surface"])], foreground=[("readonly", p["fg"])],
              selectbackground=[("readonly", p["surface"])], selectforeground=[("readonly", p["fg"])])
        s.configure("ComboboxPopdownFrame", background=p["surface"], bordercolor=p["border"],
                    relief="solid", borderwidth=1)
        # Großes Eingabefeld im Chat (Rahmen um ein tk.Text, siehe register_field)
        self._round("MS.Input.field", 12, p["bg"], [("focus", p["surface"], p["accent"]),
                                                    (None, p["surface"], p["border"])])
        s.layout("Input.TFrame", [("MS.Input.field", {"sticky": "nswe"})])

        # Häkchen (eigene Grafik statt des Kreuzes von "clam")
        n = self._check_size
        off_border = "#%02x%02x%02x" % _mix(_rgb(p["bg"]), _rgb(p["muted"]), 0.6)
        _draw_checkbox(self._img_off, n, p["bg"], off_border, p["surface"], None)
        _draw_checkbox(self._img_on, n, p["bg"], p["accent"], p["accent"], p["accent_fg"])
        if not self._check_element:
            s.element_create("MS.Checkbutton.indicator", "image", self._img_off,
                             ("selected", self._img_on), width=n + 7, sticky="w")
            self._check_element = True
        s.layout("TCheckbutton", [("Checkbutton.padding", {"sticky": "nswe", "children": [
            ("MS.Checkbutton.indicator", {"side": "left", "sticky": ""}),
            ("Checkbutton.focus", {"side": "left", "sticky": "w", "children": [
                ("Checkbutton.label", {"sticky": "nswe"})]})]})])
        s.configure("TCheckbutton", background=p["bg"], foreground=p["fg"], focuscolor=p["bg"], padding=2)
        s.map("TCheckbutton", background=[("active", p["bg"])], foreground=[("disabled", p["muted"])])

        # Rahmen, Reiter, Trenner
        s.configure("TLabelframe", background=p["bg"], bordercolor=p["border"], lightcolor=p["bg"],
                    darkcolor=p["bg"], relief="solid", borderwidth=1)
        s.configure("TLabelframe.Label", background=p["bg"], foreground=p["accent"], font=(FONT[0], 9, "bold"))
        s.configure("TNotebook", background=p["bg"], bordercolor=p["border"], lightcolor=p["bg"],
                    darkcolor=p["bg"], tabmargins=(0, 2, 0, 0))
        s.configure("TNotebook.Tab", background=p["bg"], foreground=p["muted"], bordercolor=p["border"],
                    lightcolor=p["bg"], darkcolor=p["bg"], padding=(14, 5), focuscolor=p["bg"])
        s.map("TNotebook.Tab",
              background=[("selected", p["surface"]), ("active", p["raised"])],
              lightcolor=[("selected", p["surface"]), ("active", p["raised"])],
              foreground=[("selected", p["accent"]), ("active", p["fg"])],
              padding=[("selected", (14, 5))], expand=[("selected", (0, 2, 0, 0))])
        s.configure("TSeparator", background=p["border"])
        s.configure("TPanedwindow", background=p["bg"])
        s.configure("Sash", sashthickness=8, background=p["bg"], lightcolor=p["bg"], bordercolor=p["bg"])

        # Scrollbalken ohne Pfeile
        for orient, sticky in (("Vertical", "ns"), ("Horizontal", "we")):
            s.layout(f"{orient}.TScrollbar", [(f"{orient}.Scrollbar.trough", {"sticky": sticky, "children": [
                (f"{orient}.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        s.configure("TScrollbar", background=p["raised"], troughcolor=p["surface"], bordercolor=p["surface"],
                    lightcolor=p["raised"], darkcolor=p["raised"], arrowcolor=p["muted"], gripcount=0,
                    arrowsize=11)
        s.map("TScrollbar", background=[("pressed", p["hover"]), ("active", p["hover"])],
              lightcolor=[("pressed", p["hover"]), ("active", p["hover"])],
              darkcolor=[("pressed", p["hover"]), ("active", p["hover"])])

        s.configure("Horizontal.TProgressbar", background=p["accent"], troughcolor=p["surface"],
                    bordercolor=p["border"], lightcolor=p["accent"], darkcolor=p["accent"])

        # Seitenleiste mit Chatliste
        sb = p["sidebar"]
        s.configure("Sidebar.TFrame", background=sb)
        s.configure("Sidebar.TLabel", background=sb, foreground=p["muted"], font=(FONT[0], 8, "bold"))
        s.configure("Sidebar.TButton", foreground=p["fg"], anchor="w", padding=(10, 6), font=(FONT[0], 10))
        self._round_button("Sidebar.TButton", "MS.Sidebar.border", 8, sb, [
            ("pressed", p["side_sel"], p["side_sel"]), ("active", p["side_hover"], p["side_hover"]),
            (None, sb, sb)])
        s.configure("Sidebar.Treeview", background=sb, fieldbackground=sb, foreground=p["fg"], bordercolor=sb,
                    lightcolor=sb, darkcolor=sb, rowheight=self.row_height, font=(FONT[0], 10), borderwidth=0)
        s.map("Sidebar.Treeview", background=[("selected", p["side_sel"])], foreground=[("selected", p["fg"])])
        s.layout("Sidebar.Treeview", [("Sidebar.Treeview.treearea", {"sticky": "nswe"})])
        s.layout("Sidebar.Treeview.Item", [("Treeitem.padding", {"sticky": "nswe", "children": [
            ("Treeitem.text", {"side": "left", "sticky": ""})]})])
        s.configure("Sidebar.Vertical.TScrollbar", background=sb, troughcolor=sb, bordercolor=sb,
                    lightcolor=sb, darkcolor=sb)
        s.configure("SidebarText.TLabel", background=sb, foreground=p["fg"], font=(FONT[0], 9))
        s.configure("SidebarMuted.TLabel", background=sb, foreground=p["muted"], font=(FONT[0], 8))
        s.configure("SidebarTitle.TLabel", background=sb, foreground=p["fg"], font=(FONT[0], 11, "bold"))
        s.configure("SidebarOk.TLabel", background=sb, foreground=p["chat"]["ok"], font=(FONT[0], 8))
        s.configure("SidebarWarn.TLabel", background=sb, foreground=p["chat"]["error"], font=(FONT[0], 8))
        s.configure("Sidebar.TCheckbutton", background=sb, foreground=p["fg"], focuscolor=sb, font=(FONT[0], 9))
        s.map("Sidebar.TCheckbutton", background=[("active", sb)], foreground=[("disabled", p["muted"])])
        s.map("Sidebar.Vertical.TScrollbar", background=[("active", p["raised"])],
              lightcolor=[("active", p["raised"])], darkcolor=[("active", p["raised"])])

        # Kopfzeile über dem Chat
        s.configure("Top.TFrame", background=p["bg"])
        s.configure("Title.TLabel", background=p["bg"], foreground=p["fg"], font=(FONT[0], 11, "bold"))

        # Anhänge über dem Eingabefeld („Kärtchen“) und Büroklammer-Knopf
        chip = p["raised"]
        self._round("MS.Chip.field", 8, p["bg"], [(None, chip, chip)], padding=0)
        s.configure("Chip.TFrame", relief="flat", borderwidth=0)
        s.layout("Chip.TFrame", [("MS.Chip.field", {"sticky": "nswe"})])
        s.configure("Chip.TLabel", background=chip, foreground=p["fg"], font=(FONT[0], 9))
        s.configure("ChipInfo.TLabel", background=chip, foreground=p["muted"], font=(FONT[0], 8))
        s.configure("ChipError.TLabel", background=chip, foreground=p["chat"]["error"], font=(FONT[0], 8))
        s.configure("Chip.TButton", foreground=p["muted"], padding=(2, 0), width=2)
        s.map("Chip.TButton", foreground=[("active", p["fg"])])
        self._round_button("Chip.TButton", "MS.Chip.border", 5, chip, [
            ("pressed", p["border"], p["border"]), ("active", p["hover"], p["hover"]), (None, chip, chip)])
        s.configure("Attach.TButton", font=(FONT[0], 14), padding=(6, 0))
