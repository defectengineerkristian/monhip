"""Dialoge im Design des Programms – Ersatz für tkinter.messagebox (dessen Fenster sich nicht einfärben lassen)
und gemeinsames Grundgerüst für alle eigenen Fenster: window() anlegen, present() mittig einblenden.

setup(root, theme, ui_scale) einmal in App.__init__; ohne setup fallen die Meldungen auf messagebox zurück.
"""

from i18n import error_text, tr

import tkinter as tk
from tkinter import messagebox, ttk

from themes import FAMILY

try:
    import winsound
except ImportError:
    winsound = None

_root: tk.Tk | None = None
_theme = None
_scale = 1.0

# Art → Symbol, Farbschlüssel der Palette, Farbe für „Windows-Standard“, Hinweiston (MessageBeep)
_KINDS = {
    "info": ("i", "accent", "#0067c0", 0x40),
    "error": ("!", "error", "#c42b1c", 0x10),
    "question": ("?", "accent", "#0067c0", 0x20),
}


def setup(root: tk.Tk, theme, ui_scale: float = 1.0):
    global _root, _theme, _scale
    _root, _theme, _scale = root, theme, ui_scale


def _s(v: float) -> int:
    return round(v * _scale)


def _parent(parent: tk.Misc | None) -> tk.Misc:
    try:
        if parent is not None and parent.winfo_exists() and parent.winfo_viewable():
            return parent
    except tk.TclError:
        pass
    return _root


# ---------------------------------------------------------------- Grundgerüst

def window(title: str, parent: tk.Misc | None = None, resizable: bool = False) -> tk.Toplevel:
    """Neues Fenster im Design, noch unsichtbar – erst fertig aufbauen, dann present()."""
    parent = _parent(parent)
    win = tk.Toplevel(parent)
    win.withdraw()
    win.title(title)
    win.transient(parent)
    win.resizable(resizable, resizable)
    _theme.register_window(win)
    return win


def present(win: tk.Toplevel, parent: tk.Misc | None = None, size: tuple[int, int] | None = None,
            modal: bool = False, focus: tk.Misc | None = None):
    """Mittig über parent einblenden (Titelleiste gefärbt, weich). modal: Eingaben sperren und warten, bis das
    Fenster zu ist."""
    parent = _parent(parent)
    parent.update_idletasks()
    win.update_idletasks()
    w, h = size or (win.winfo_reqwidth(), win.winfo_reqheight())
    x = parent.winfo_rootx() + max(0, (parent.winfo_width() - w) // 2)
    y = parent.winfo_rooty() + max(0, (parent.winfo_height() - h) // 3)
    _theme.present(win, f"{w}x{h}+{x}+{y}" if size else f"+{x}+{y}")
    if focus:
        focus.focus_set()
    if modal:
        try:
            win.grab_set()
        except tk.TclError:  # ein anderes Fenster hält die Eingabe gerade fest
            pass
        parent.wait_window(win)


# ---------------------------------------------------------------- Meldungen

def showinfo(title: str, message: str, parent: tk.Misc | None = None):
    _show("info", title, message, parent)


def showerror(title: str, message: str, parent: tk.Misc | None = None):
    _show("error", title, message, parent)


def askyesno(title: str, message: str, parent: tk.Misc | None = None) -> bool:
    return _show("question", title, message, parent)


def _color(key: str, fallback: str) -> str:
    pal = _theme.pal if _theme else None
    return (pal.get(key) or pal.get("chat", {}).get(key) or fallback) if pal else fallback


def _show(kind: str, title: str, message: str, parent: tk.Misc | None) -> bool:
    message = error_text(message)
    if _theme is None:
        fallback = {"info": messagebox.showinfo, "error": messagebox.showerror, "question": messagebox.askyesno}
        return bool(fallback[kind](title, message, parent=parent))
    symbol, color_key, fallback_color, sound = _KINDS[kind]
    win = window(title, parent)
    body = ttk.Frame(win, padding=(_s(18), _s(16), _s(18), _s(14)))
    body.pack(fill=tk.BOTH, expand=True)
    top = ttk.Frame(body)
    top.pack(fill=tk.X)
    size = _s(30)
    icon = tk.Canvas(top, width=size, height=size, highlightthickness=0, borderwidth=0,
                     background=ttk.Style().lookup("TFrame", "background") or "#ffffff")
    icon.create_oval(1, 1, size - 1, size - 1, fill=_color(color_key, fallback_color), outline="")
    icon.create_text(size // 2, size // 2, text=symbol, fill="#ffffff", font=(FAMILY, 12, "bold"))
    icon.pack(side=tk.LEFT, anchor="n", padx=(0, _s(14)))
    ttk.Label(top, text=message, wraplength=_s(420), justify=tk.LEFT).pack(side=tk.LEFT, anchor="w", fill=tk.X,
                                                                          pady=(_s(5), 0))
    result = {"v": False}

    def close(value: bool):
        result["v"] = value
        win.destroy()

    bf = ttk.Frame(body)
    bf.pack(fill=tk.X, pady=(_s(16), 0))
    if kind == "question":
        ttk.Button(bf, text=tr('Nein'), command=lambda: close(False)).pack(side=tk.RIGHT)
        default = ttk.Button(bf, text=tr('Ja'), style="Accent.TButton", command=lambda: close(True))
        default.pack(side=tk.RIGHT, padx=(0, _s(6)))
    else:
        default = ttk.Button(bf, text="OK", style="Accent.TButton", width=10, command=lambda: close(True))
        default.pack(side=tk.RIGHT)
    win.bind("<Return>", lambda e: default.invoke())
    win.bind("<Escape>", lambda e: close(False))
    win.protocol("WM_DELETE_WINDOW", lambda: close(False))
    win.bind("<Control-c>", lambda e: (win.clipboard_clear(), win.clipboard_append(message)))
    if winsound:
        try:
            winsound.MessageBeep(sound)
        except RuntimeError:
            pass
    present(win, parent, modal=True, focus=default)
    return result["v"]


def askstring(title: str, prompt: str, initial: str = "", parent: tk.Misc | None = None) -> str | None:
    """Eingabefeld mit OK/Abbrechen. Leere Eingabe oder Abbrechen → None."""
    win = window(title, parent)
    body = ttk.Frame(win, padding=16)
    body.pack(fill=tk.BOTH, expand=True)
    ttk.Label(body, text=prompt).pack(anchor="w")
    var = tk.StringVar(value=initial)
    entry = ttk.Entry(body, textvariable=var, width=46)
    entry.pack(fill=tk.X, pady=(6, 12))
    entry.select_range(0, tk.END)
    result = {}

    def ok(_e=None):
        result["v"] = var.get().strip()
        win.destroy()

    bf = ttk.Frame(body)
    bf.pack(fill=tk.X)
    ttk.Button(bf, text=tr('Abbrechen'), command=win.destroy).pack(side=tk.RIGHT)
    ttk.Button(bf, text="OK", style="Accent.TButton", command=ok).pack(side=tk.RIGHT, padx=(0, 6))
    entry.bind("<Return>", ok)
    win.bind("<Escape>", lambda e: win.destroy())
    present(win, parent, modal=True, focus=entry)
    return result.get("v") or None
