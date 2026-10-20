"""Farbschemata (Designs) für Monhip.

Neue Designs: einfach einen weiteren Eintrag in THEMES mit denselben Schlüsseln anlegen.
"""

import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

FONT = ("Segoe UI", 9)

THEMES = {
    "dark": {
        "label": "Dunkel (Grau/Orange)",
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
            "error": "#ff7b72", "ok": "#7ec699",
            "kw": "#cc99cd", "str": "#9fd28a", "com": "#7d7a72", "num": "#f0a45d",
            # Namensfarben der Teilnehmer im Gruppenchat (Teamwork)
            "people": ["#e3896a", "#7ec699", "#8fb4f0", "#d7a0e8", "#e8c46a", "#6fd1d1"],
        },
    },
    "light": {
        "label": "Hell (Weiß/Violett)",
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
            "error": "#c81e1e", "ok": "#2f8a4c",
            "kw": "#7c3aed", "str": "#2f7d32", "com": "#8b87a0", "num": "#b4530b",
            "people": ["#c2410c", "#15803d", "#1d4ed8", "#9333ea", "#a16207", "#0e7490"],
        },
    },
    "system": {
        "label": "Windows-Standard",
        "dark": False,
        "chat": {
            "fg": "#1b1b1b", "muted": "#6b6b6b", "accent": "#0b63c5",
            "bubble": "#e4e4e9", "bubble_fg": "#1b1b1b",
            "code_bg": "#f5f5f5", "code_hdr": "#e9e9e9", "code_fg": "#1b1b1b",
            "think_bg": "#f7f7f7", "think_fg": "#555555", "link": "#0b63c5", "rule": "#d0d0d0",
            "error": "#c01c28", "ok": "#26a269",
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

    # ------------------------------------------------------------ Registrierung

    def _remember(self, w, opts):
        self._orig[str(w)] = {k: w.cget(k) for k in opts}

    def register_text(self, w: tk.Text, role: str = "field"):
        """role "field": Eingabefeld mit Rahmen, "plain": randlos auf dem Hintergrund (Chatverlauf)."""
        self._remember(w, TEXT_OPTS)
        self._roles[str(w)] = role
        self._texts.append(w)
        self._style_text(w)
        return w

    def register_menu(self, m: tk.Menu):
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
            s.configure("Attach.TButton", font=(FONT[0], 15), padding=(6, 0))
        for lst, fn in ((self._texts, self._style_text), (self._lists, self._style_list),
                        (self._combos, self._style_combo), (self._menus, self._style_menu),
                        (self._windows, self._style_window)):
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
        plain = self._roles.get(str(w)) == "plain"
        w.configure(background=p["bg"] if plain else p["surface"], foreground=p["fg"], insertbackground=p["fg"],
                    selectbackground=p["select_bg"], selectforeground=p["select_fg"],
                    highlightthickness=0 if plain else 1, highlightbackground=p["border"],
                    highlightcolor=p["accent"], borderwidth=0, relief=tk.FLAT)

    def _style_menu(self, m: tk.Menu):
        p = self.pal
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

        # Knöpfe
        s.configure("TButton", background=p["raised"], foreground=p["fg"], bordercolor=p["border"],
                    lightcolor=p["raised"], darkcolor=p["raised"], focuscolor=p["raised"],
                    focusthickness=0, padding=(10, 3), anchor="center")
        state_bg = [("disabled", p["bg"]), ("pressed", p["border"]), ("active", p["hover"])]
        s.map("TButton", background=state_bg, lightcolor=state_bg, darkcolor=state_bg,
              foreground=[("disabled", p["muted"])], bordercolor=[("focus", p["accent"])])
        s.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"],
                    bordercolor=p["accent"], lightcolor=p["accent"], darkcolor=p["accent"],
                    focuscolor=p["accent"], font=(FONT[0], 9, "bold"))
        accent_bg = [("disabled", p["raised"]), ("pressed", p["accent_hover"]), ("active", p["accent_hover"])]
        s.map("Accent.TButton", background=accent_bg, lightcolor=accent_bg, darkcolor=accent_bg,
              bordercolor=accent_bg, foreground=[("disabled", p["muted"])])

        # Eingabefelder
        s.configure("TEntry", fieldbackground=p["surface"], foreground=p["fg"], insertcolor=p["fg"],
                    bordercolor=p["border"], lightcolor=p["surface"], darkcolor=p["surface"], padding=(5, 2))
        s.map("TEntry", bordercolor=[("focus", p["accent"])], lightcolor=[("focus", p["accent"])],
              fieldbackground=[("disabled", p["bg"])])
        s.configure("TCombobox", fieldbackground=p["surface"], background=p["raised"], foreground=p["fg"],
                    arrowcolor=p["fg"], bordercolor=p["border"], lightcolor=p["surface"],
                    darkcolor=p["surface"], padding=(5, 2))
        s.map("TCombobox", fieldbackground=[("readonly", p["surface"])], foreground=[("readonly", p["fg"])],
              selectbackground=[("readonly", p["surface"])], selectforeground=[("readonly", p["fg"])],
              background=[("active", p["hover"]), ("pressed", p["hover"])],
              bordercolor=[("focus", p["accent"])], lightcolor=[("focus", p["accent"])],
              arrowcolor=[("disabled", p["muted"])])
        s.configure("ComboboxPopdownFrame", background=p["surface"], bordercolor=p["border"],
                    relief="solid", borderwidth=1)

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
        s.configure("Sidebar.TButton", background=sb, foreground=p["fg"], bordercolor=sb, lightcolor=sb,
                    darkcolor=sb, focuscolor=sb, anchor="w", padding=(10, 6), font=(FONT[0], 10))
        side_bg = [("pressed", p["side_sel"]), ("active", p["side_hover"])]
        s.map("Sidebar.TButton", background=side_bg, lightcolor=side_bg, darkcolor=side_bg, bordercolor=side_bg)
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
        s.configure("Chip.TFrame", background=chip, relief="flat", borderwidth=0)
        s.configure("Chip.TLabel", background=chip, foreground=p["fg"], font=(FONT[0], 9))
        s.configure("ChipInfo.TLabel", background=chip, foreground=p["muted"], font=(FONT[0], 8))
        s.configure("ChipError.TLabel", background=chip, foreground=p["chat"]["error"], font=(FONT[0], 8))
        s.configure("Chip.TButton", background=chip, foreground=p["muted"], bordercolor=chip, lightcolor=chip,
                    darkcolor=chip, focuscolor=chip, padding=(2, 0), width=2)
        chip_bg = [("pressed", p["border"]), ("active", p["hover"])]
        s.map("Chip.TButton", background=chip_bg, lightcolor=chip_bg, darkcolor=chip_bg, bordercolor=chip_bg,
              foreground=[("active", p["fg"])])
        s.configure("Attach.TButton", font=(FONT[0], 15), padding=(6, 0))
