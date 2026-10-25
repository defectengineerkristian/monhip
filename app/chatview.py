"""Chatverlauf in einem tk.Text (bleibt markier- und kopierbar): Nutzer-Sprechblasen rechts, Markdown-Antworten
links, aufklappbare Denkprozess-/Werkzeug-Blöcke.

Tags mit Nummer N (Infos in self.blocks[N]): hdr:N Kopfzeile, body:N Inhalt, cpy:N „Kopieren“, ccp:N „Code
kopieren“, code:N, lnk:N, tbl:N, act:N anklickbare Zeile (action). Geschrieben wird nur in `with self._edit():` (für den Nutzer schreibgeschützt).
Das Textfeld selbst nie per configure ändern (state, cursor …): Tk vermisst danach den ganzen Verlauf neu.
"""

import ctypes
import math
import os
import re
import sys
import time
import tkinter as tk
import webbrowser
from contextlib import contextmanager
from tkinter import font as tkfont
from tkinter import ttk

from markdown_lite import ListLevels, classify, closes_fence, inline, is_separator_row, plain, split_row
from themes import mix_hex
from widgets import rounded

FAMILY, MONO = "Segoe UI", "Consolas"
MAX_COLUMN = 820          # maximale Breite der Chatspalte (Pixel bei 100 %)
PULSE_MS = 40
THUMB_KEEP = 80           # so viele Vorschaubilder bleiben beim Leeren der Ansicht im Speicher
BULLETS = ["•", "◦", "▪", "‣"]
WIN_CURSORS = {"hand2": 32649, "xterm": 32513}  # IDC_HAND, IDC_IBEAM
CLOSED, OPENED = "▸", "▾"
# Farbe des Typ-Abzeichens auf Datei-Kärtchen (sonst Akzentfarbe des Designs)
BADGE_COLORS = {"PDF": "#d0473a", "DOC": "#2b5fb4", "DOCX": "#2b5fb4", "ODT": "#2b5fb4", "RTF": "#2b5fb4",
                "XLSX": "#21804a", "XLS": "#21804a", "CSV": "#21804a", "ODS": "#21804a",
                "PPTX": "#d0542b", "PPT": "#d0542b", "ODP": "#d0542b"}

# ---------------------------------------------------------------- Code-Hervorhebung

KEYWORDS = frozenset("""
abstract and as assert async await auto bool boolean break byte case catch char class const constexpr continue
def default defer del delete do double elif else enum except export extends extern false final finally float fn
for foreach from func function go goto if impl implements import in include inline int interface internal is
lambda let long loop match mod module mut namespace new nil none not null of or override package pass private
protected pub public raise readonly ref return self short signed sizeof static string struct super switch
template this throw throws trait true try type typedef typename typeof uint union unsigned use using val var
virtual void volatile where while with yield None True False print println printf len range echo function
""".split())
HASH_LANGS = {"python", "py", "sh", "bash", "shell", "zsh", "powershell", "ps1", "ps", "pwsh", "ruby", "rb",
              "yaml", "yml", "toml", "r", "perl", "makefile", "dockerfile", "ini", "conf", "julia", "elixir", "nim"}
PLAIN_LANGS = {"text", "txt", "plaintext", "output", "console", "log", "csv", "markdown", "md"}
_STR = r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\'|`[^`\n]*`'
_REST = r"(?P<num>\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|(?P<id>[A-Za-z_]\w*)"
_HL = {
    "hash": re.compile(rf"(?P<com>#.*$)|(?P<str>{_STR})|{_REST}"),
    "slash": re.compile(rf"(?P<com>//.*$|/\*.*?(?:\*/|$))|(?P<str>{_STR})|{_REST}"),
    "both": re.compile(rf"(?P<com>#.*$|//.*$)|(?P<str>{_STR})|{_REST}"),
    "sql": re.compile(rf"(?P<com>--.*$)|(?P<str>{_STR})|{_REST}"),
    "html": re.compile(rf"(?P<com><!--.*?(?:-->|$))|(?P<str>{_STR})|{_REST}"),
}


def highlight(line: str, lang: str) -> list[tuple[int, int, str]]:
    """[(start, ende, art)] mit art in kw / str / com / num – bewusst einfach, Zeile für Zeile."""
    if lang in PLAIN_LANGS:
        return []
    style = ("hash" if lang in HASH_LANGS else "sql" if lang in ("sql", "lua") else
             "html" if lang in ("html", "xml", "svg", "vue") else "both" if not lang else "slash")
    spans = []
    for m in _HL[style].finditer(line):
        kind = m.lastgroup
        if kind != "id":
            spans.append((m.start(), m.end(), kind))
        elif m.group() in KEYWORDS:
            spans.append((m.start(), m.end(), "kw"))
    return spans


class ChatView:
    def __init__(self, text: tk.Text, scale: float = 1.0, register_menu=None):
        self.t = text
        self.scale = scale
        self.col: dict = {}
        self.bg = "#ffffff"
        self.blocks: dict[int, dict] = {}
        self.bubbles: list[tuple[tk.Canvas, str, object]] = []  # (Canvas, "bubble"/"files", Text bzw. Dateien)
        self._thumbs: dict = {}      # Vorschaubilder angehängter Bilder: Pfad bzw. (Pfad, Verkleinerung) → PhotoImage
        self.gen = 0                 # erhöht sich bei clear(); spätere Rückmeldungen erkennen so alte Ansichten
        self.md: dict | None = None  # Zustand der gerade gestreamten Markdown-Antwort
        self.is_placeholder = False
        self._n = 0
        self._depth = 0
        self._batch = 0
        self._follow = False
        self._stick = True           # unten „kleben“ – wird nur durch eigenes Scrollen des Nutzers aufgehoben
        self._padx = None
        self._bubble_w = None
        self._layout_job = None
        self._anim_job = None
        self._live: set[int] = set()
        self._pending = False
        # Einfügeposition: normalerweise das Ende; in einem Slot (eigener Platz einer Nachricht, z. B. im
        # Gruppenchat, wo mehrere KIs gleichzeitig schreiben) dessen Marke. Siehe slot_new()/slot().
        self._at = "end-1c"
        self._pend_tag = "pending"
        self._pendings: set[str] = set()
        self._slots: dict[str, dict] = {}
        self._corners: dict = {}
        self._indent_tags: set[str] = set()
        self._scroll_left = 0.0
        self._scroll_job = None
        self._bubble_text = ""
        self._file_path = ""
        self.on_quote = None         # on_quote(text): „Antworten“ auf markierten Text (nur im normalen Chat)
        self._quote_pop = None       # kleines Feld „Antworten / Kopieren“ über einer Markierung
        self._act_job = None         # verzögertes Ausblenden von „Kopieren / Bearbeiten“
        self._make_fonts()
        self._make_tags()

        t = self.t
        t.configure(cursor="", insertontime=0)  # Mauszeiger vom Rahmen (_set_cursor), keine Schreibmarke (_readonly)
        self._cursor = None
        self._set_cursor("xterm")
        self._readonly()
        t.bind("<Configure>", self._on_configure, add="+")
        t.bind("<MouseWheel>", self._on_wheel)
        t.bind("<Button-3>", self._on_context)
        t.bind("<ButtonPress-1>", lambda e: self._hide_quote_pop(), add="+")
        t.bind("<ButtonRelease-1>", self._on_release, add="+")
        t.tag_bind("clickable", "<Enter>", self._on_enter_click)
        t.tag_bind("clickable", "<Leave>", self._on_leave_click)
        t.tag_bind("clickable", "<Button-1>", self._on_click)

        self.menu = tk.Menu(t, tearoff=0)
        self.menu.add_command(label="Kopieren", command=self._copy_selection)
        self.menu.add_command(label="Alles markieren", command=lambda: t.tag_add("sel", "1.0", "end-1c"))
        self.bubble_menu = tk.Menu(t, tearoff=0)
        self.bubble_menu.add_command(label="Text kopieren", command=lambda: self._copy(self._bubble_text))
        self.file_menu = tk.Menu(t, tearoff=0)
        self.file_menu.add_command(label="Öffnen", command=lambda: self._open_file(self._file_path))
        self.file_menu.add_command(label="Pfad kopieren", command=lambda: self._copy(self._file_path))
        if register_menu:
            register_menu(self.menu)
            register_menu(self.bubble_menu)
            register_menu(self.file_menu)

    # ================================================================ Grundlagen

    def _s(self, v: float) -> int:
        return round(v * self.scale)

    def _make_fonts(self):
        def f(size, weight="normal", slant="roman", family=FAMILY):
            return tkfont.Font(root=self.t, family=family, size=size, weight=weight, slant=slant)

        self.f_base, self.f_bold = f(11), f(11, "bold")
        self.f_italic, self.f_bi = f(11, slant="italic"), f(11, "bold", "italic")
        self.f_small, self.f_small_i, self.f_tiny = f(10), f(10, slant="italic"), f(9)
        self.f_small_b, self.f_label = f(10, "bold"), f(8, "bold")
        self.f_h1, self.f_h2, self.f_h3 = f(17, "bold"), f(14, "bold"), f(12, "bold")
        self.f_mono, self.f_mono_s = f(10, family=MONO), f(9, family=MONO)
        self.f_gap, self.f_hair = f(4), f(1)

    def _make_tags(self):
        """Reihenfolge = Priorität: später angelegte Tags gewinnen (z. B. „b“ über „p“)."""
        s, T = self._s, self.t.tag_configure
        T("p", font=self.f_base, spacing1=s(2), spacing2=s(3), spacing3=s(2))
        T("li", font=self.f_base, spacing1=s(2), spacing2=s(3), spacing3=s(2))
        T("gap", font=self.f_gap)
        T("quote", font=self.f_italic, lmargin1=s(18), lmargin2=s(18))
        T("md_h1", font=self.f_h1, spacing1=s(12), spacing3=s(4))
        T("md_h2", font=self.f_h2, spacing1=s(10), spacing3=s(3))
        T("md_h3", font=self.f_h3, spacing1=s(8), spacing3=s(2))
        T("b", font=self.f_bold)
        T("i", font=self.f_italic)
        T("bi", font=self.f_bi)
        T("s", overstrike=True)
        T("code", font=self.f_mono)
        T("link", underline=True)
        T("bullet")
        T("pre_hdr", font=self.f_tiny, lmargin1=s(12), lmargin2=s(12), spacing1=s(4), spacing3=s(4))
        T("pre", font=self.f_mono, lmargin1=s(12), lmargin2=s(12), rmargin=s(12), spacing2=s(1), wrap="char")
        T("pre_pad", font=self.f_gap)
        for k in ("c_kw", "c_str", "c_com", "c_num"):
            T(k)
        T("hr", font=self.f_hair)
        T("th", font=self.f_bold, spacing1=s(4), spacing3=s(4))
        T("td", font=self.f_base, spacing1=s(4), spacing3=s(4))
        T("trule", font=self.f_hair)
        T("trule_soft", font=self.f_hair)
        T("think_hdr", font=self.f_small, spacing1=s(6), spacing3=s(6))
        T("think_pad", font=self.f_gap)
        T("think_body", font=self.f_small, lmargin1=s(14), lmargin2=s(14), rmargin=s(14), spacing2=s(2))
        T("tool_hdr", font=self.f_small, spacing1=s(3), spacing3=s(3))
        T("tool_body", font=self.f_mono_s, lmargin1=s(14), lmargin2=s(14), rmargin=s(14), wrap="char")
        T("tool_label", font=self.f_label)
        T("st_ok")
        T("st_err")
        T("note", font=self.f_small_i, spacing1=s(4), spacing3=s(4))
        T("error", font=self.f_small, spacing1=s(4), spacing3=s(4))
        T("warn", font=self.f_small, spacing1=s(6), spacing3=s(6))
        T("footer", font=self.f_tiny, spacing1=s(2), spacing3=s(10))
        T("user", justify="right", spacing1=s(20), spacing3=s(12))
        T("user_files", justify="right", spacing1=s(20), spacing3=s(6))   # Datei-Kärtchen über der Blase
        T("user_after", justify="right", spacing3=s(12))                  # Blase direkt unter den Kärtchen
        T("user_a", justify="right", spacing1=s(20), spacing3=s(3))      # Blase mit Aktionszeile darunter
        T("user_after_a", justify="right", spacing3=s(3))
        T("user_mid", justify="right", spacing3=s(6))                    # Kärtchen zwischen Zitat und Blase
        T("uact", font=self.f_tiny, justify="right", spacing3=s(12))    # „Kopieren · Bearbeiten“ (beim Darüberfahren)
        T("uver", font=self.f_small)                                     # „‹ 2/3 ›“ – Fassungen, immer sichtbar
        T("uver_arrow", font=self.f_h2)                                  # größere Pfeile, leichter zu treffen
        T("uver_off")                                                    # Pfeil ohne weitere Fassung (blass)
        T("who", font=self.f_small_b, spacing1=s(16), spacing3=s(4))     # Absenderzeile im Gruppenchat
        T("who_sub", font=self.f_tiny)
        T("other", spacing3=s(8))                                         # Blase/Kärtchen anderer, links
        T("other_a", spacing3=s(3))                                       # … mit „Kopieren“ darunter
        T("oact", font=self.f_tiny, spacing3=s(8))
        T("slot_end", elide=True)
        T("placeholder", font=(FAMILY, 15), justify="center", spacing1=s(150), spacing3=s(6))
        T("placeholder_sub", font=(FAMILY, 10), justify="center")
        T("clickable")
        T("hover")
        T("live")

    def apply_theme(self, col: dict):
        """col = THEMES[…]["chat"]. Der Hintergrund kommt vom Textfeld selbst (auch bei „Windows-Standard“)."""
        self.col = col
        r, g, b = self.t.winfo_rgb(self.t.cget("background"))
        self.bg = "#%02x%02x%02x" % (r // 257, g // 257, b // 257)
        # Markierung auch ohne Tastaturfokus zeigen (Tk-Standard: dann unsichtbar) – wichtig für „Antworten“
        self.t.configure(inactiveselectbackground=self.t.cget("selectbackground"))
        T = self.t.tag_configure

        def band(tag, color, **kw):
            T(tag, background=color, lmargincolor=color, rmargincolor=color, **kw)

        T("bullet", foreground=col["muted"])
        T("quote", foreground=col["muted"])
        T("code", background=col["code_bg"], foreground=col["code_fg"])
        T("link", foreground=col["link"])
        band("pre_hdr", col["code_hdr"], foreground=col["muted"])
        band("pre", col["code_bg"], foreground=col["code_fg"])
        band("pre_pad", col["code_bg"])
        T("c_kw", foreground=col["kw"])
        T("c_str", foreground=col["str"])
        T("c_com", foreground=col["com"])
        T("c_num", foreground=col["num"])
        T("hr", background=col["rule"])
        T("trule", background=col["rule"])
        T("trule_soft", background=col["think_bg"])
        T("think_hdr", foreground=col["muted"])
        T("tool_hdr", foreground=col["muted"])
        band("think_pad", col["think_bg"])
        band("think_body", col["think_bg"], foreground=col["think_fg"])
        band("tool_body", col["code_bg"], foreground=col["think_fg"])
        T("tool_label", foreground=col["muted"])
        T("who_sub", foreground=col["muted"])
        T("st_ok", foreground=col["ok"])
        T("st_err", foreground=col["error"])
        T("note", foreground=col["muted"])
        T("error", foreground=col["error"])
        T("warn", foreground=col["warn"])
        T("footer", foreground=col["muted"])
        T("placeholder", foreground=col["fg"])
        T("placeholder_sub", foreground=col["muted"])
        T("hover", foreground=col["fg"])
        T("live", foreground=col["muted"])
        T("uver", foreground=col["muted"])
        T("uver_off", foreground=mix_hex(self.bg, col["muted"], 0.4))
        self._corners.clear()
        self._refresh_actions()
        self._redraw_bubbles()

    def _readonly(self):
        """Verlauf für den Nutzer schreibgeschützt, ohne state=disabled: Jedes configure eines tk.Text (auch
        state oder cursor) lässt Tk den ganzen Verlauf neu vermessen – im langen Chat ~10 ms je Schreibschritt.
        Ein eigener Bindtag vor „Text“ verwirft daher alles, was den Inhalt ändern würde; Markieren, Kopieren und
        Blättern bleiben."""
        tag = "ChatReadOnly"
        self.t.bindtags((tag,) + self.t.bindtags())
        if self.t.bind_class(tag):
            return  # schon eingerichtet (zweite ChatView)
        nav = {"Left", "Right", "Up", "Down", "Prior", "Next", "Home", "End", "Shift_L", "Shift_R", "Control_L",
               "Control_R", "Alt_L", "Alt_R", "Escape", "Caps_Lock"}

        def key(e):
            ctrl = e.state & 0x0004
            if e.keysym in nav or (ctrl and e.keysym.lower() in ("c", "a", "insert", "slash")):
                return None
            return "break"

        self.t.bind_class(tag, "<KeyPress>", key)
        for seq in ("<<Paste>>", "<<Cut>>", "<<Clear>>", "<<PasteSelection>>", "<<Undo>>", "<<Redo>>"):
            self.t.bind_class(tag, seq, lambda e: "break")

    @contextmanager
    def batch(self):
        """Viele Blöcke auf einmal schreiben (gespeicherten Chat anzeigen): erst am Ende einmal ans Ende scrollen."""
        self._batch += 1
        try:
            yield
        finally:
            self._batch -= 1
            if not self._batch and self._stick:
                self.t.see("end")

    @contextmanager
    def _edit(self, follow: bool | None = None):
        """Schreibzugriff. follow=None: ans Ende scrollen, solange der Nutzer nicht selbst hochgescrollt hat."""
        if self._depth == 0:
            self._follow = self._stick if follow is None else follow
        elif follow:
            self._follow = True
        if follow:
            self._stick = True
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
            if self._depth == 0 and self._follow and not self._batch:
                self.t.see("end")

    def _at_bottom(self) -> bool:
        return self.t.dlineinfo("end-1c") is not None

    def attach_scrollbar(self, sb):
        """Scrollbalken melden, damit Ziehen am Balken das „Unten-kleben“ auf- bzw. wieder einschaltet."""
        def command(*args):
            self.t.yview(*args)
            self._stick = self._at_bottom()
        sb.configure(command=command, cursor="arrow")  # sonst erbte er den Zeiger des Rahmens (_set_cursor)

    def _new(self, kind: str, **info) -> int:
        self._n += 1
        self.blocks[self._n] = {"kind": kind, **info}
        return self._n

    def _ensure(self):
        if self.is_placeholder:
            self.clear()

    def scroll_end(self):
        self._stick = True
        self.t.see("end")

    def scroll_to(self, fraction: float):
        """An eine Stelle scrollen (z. B. nach dem Wechsel einer Fassung dort bleiben, wo man war)."""
        self.t.update_idletasks()
        self.t.yview_moveto(fraction)
        self._stick = self._at_bottom()

    def scroll_to_index(self, index: str):
        """Eine Textstelle oben ins Fenster holen (z. B. nach „Ältere Nachrichten anzeigen“ dort bleiben)."""
        self.t.update_idletasks()
        self.t.yview(index)
        self._stick = self._at_bottom()

    # ================================================================ Leeren / Platzhalter

    def clear(self):
        self.gen += 1
        self._live.clear()
        self._pending = False
        self._pendings.clear()
        self._slots.clear()
        self._at, self._pend_tag = "end-1c", "pending"
        self.md = None
        self._stop_scroll()
        self._hide_quote_pop()
        self._stick = True
        with self._edit(follow=False):
            self.t.delete("1.0", "end")
        for c, _, _ in self.bubbles:
            try:
                c.destroy()
            except tk.TclError:
                pass
        self.bubbles.clear()
        # Vorschaubilder: nur die zuletzt benutzten behalten (ein Neuaufbau derselben Ansicht lädt sie dann nicht
        # neu, über viele Chats sammeln sie sich nicht an) – jetzt zeigt sie keine Zeichenfläche mehr
        for key in list(self._thumbs)[:-THUMB_KEEP]:
            del self._thumbs[key]
        for tag in self.t.tag_names():
            if ":" in tag:
                self.t.tag_delete(tag)
        for mark in self.t.mark_names():
            if ":" in mark:
                self.t.mark_unset(mark)
        self.blocks.clear()
        self.is_placeholder = False

    def placeholder(self, title: str, sub: str):
        self.clear()
        with self._edit(follow=False):
            self.t.insert("end", title + "\n", "placeholder")
            self.t.insert("end", sub, "placeholder_sub")
        self.is_placeholder = True

    # ================================================================ Nutzer-Sprechblase

    def user(self, text: str, files: list[dict] | None = None, quote: str | None = None,
             actions: dict | None = None):
        """Nutzernachricht rechts: optional ein Zitat (Antwort auf eine markierte Stelle) und Datei-Kärtchen (name,
        info, path), darunter die Sprechblase. actions zeigt beim Darüberfahren „Kopieren“ unter der Blase,
        mit {"on_edit": f(neuer_text) -> bool} auch „Bearbeiten“ (actions={} = nur Kopieren)."""
        self._ensure()
        self.md_finish()
        self.hide_pending()
        actions = actions if text else None
        hover: list[tk.Canvas] = []   # alles, was beim Darüberfahren die Aktionen einblendet
        with self._edit(follow=True):
            first = True
            if quote:
                c = self._canvas("arrow")
                self.bubbles.append((c, "quote", quote))
                self._draw_quote(c, quote)
                self._embed(c, "user_files")
                hover.append(c)
                first = False
            if files:
                c = self._canvas("arrow")
                self._bind_cards(c)
                c.bind("<Button-3>", lambda e, c=c: self._on_file_menu(e, self._card_path(c)))
                self.bubbles.append((c, "files", files))
                self._draw_files(c, files)
                if text:
                    self._embed(c, "user_files" if first else "user_mid")
                else:
                    self._embed(c, "user" if first else "user_after")
                hover.append(c)
                first = False
            if text or not files:
                c = self._canvas("arrow")
                c.bind("<Button-3>", lambda e, s=text: self._on_bubble_menu(e, s))
                self.bubbles.append((c, "bubble", text))
                self._draw_bubble(c, text)
                if actions is not None:
                    self._embed(c, "user_a" if first else "user_after_a")
                    self._user_actions(c, text, actions, hover + [c])
                else:
                    self._embed(c, "user" if first else "user_after")

    # ---------------------------------------------------------------- Kopieren / Bearbeiten eigener Nachrichten

    def _user_actions(self, bubble: tk.Canvas, text: str, actions: dict, hover: list, base: str = "uact"):
        """Zeile „⧉ Kopieren   ✎ Bearbeiten“ unter der Blase – unsichtbar (Hintergrundfarbe), bis die Maus über
        der Nachricht ist. base "oact": linksbündig unter der Blase eines anderen (Gruppenchat)."""
        cur, count = actions.get("versions") or (0, 1)
        n = self._new("umsg", text=text, canvas=bubble, on_edit=actions.get("on_edit"), shown=False, cur=cur,
                      on_version=actions.get("on_version"), base=base)
        tag, line = f"uact:{n}", f"uline:{n}"   # uact: ein-/ausgeblendet; uline: ganze Zeile (beim Bearbeiten weg)
        self.t.insert(self._at, "⧉ Kopieren", (base, "clickable", f"ucp:{n}", tag, line))
        if actions.get("on_edit"):
            self.t.insert(self._at, "      ", ("uact", tag, line))
            self.t.insert(self._at, "✎ Bearbeiten", ("uact", "clickable", f"ued:{n}", tag, line))
        if count > 1:  # Fassungen: immer sichtbar, ganz rechts unter der Blase
            self.t.insert(self._at, "      ", ("uact", tag, line))
            self.t.insert(self._at, "‹", ("uact", "uver", "uver_arrow", line)
                          + (("clickable", f"uvp:{n}") if cur > 0 else ("uver_off",)))
            self.t.insert(self._at, f" {cur + 1}/{count} ", ("uact", "uver", line))
            self.t.insert(self._at, "›", ("uact", "uver", "uver_arrow", line)
                          + (("clickable", f"uvn:{n}") if cur < count - 1 else ("uver_off",)))
        self.t.insert(self._at, "\n", (base, tag, line))
        self.t.tag_configure(tag, foreground=self.bg)
        for w in hover:
            w.bind("<Enter>", lambda e: self._actions_show(n), add="+")
            w.bind("<Leave>", lambda e: self._actions_hide(n), add="+")
        self.t.tag_bind(tag, "<Enter>", lambda e: self._actions_show(n))
        self.t.tag_bind(tag, "<Leave>", lambda e: self._actions_hide(n))

    def _actions_show(self, n: int):
        if self._act_job:
            self.t.after_cancel(self._act_job)
            self._act_job = None
        for m, b in self.blocks.items():
            if b["kind"] == "umsg" and b["shown"] and m != n:
                self._actions_off(m)
        b = self.blocks.get(n)
        if b:
            b["shown"] = True
            self.t.tag_configure(f"uact:{n}", foreground=self.col.get("muted", "#888888"))

    def _actions_hide(self, n: int):
        if self._act_job:
            self.t.after_cancel(self._act_job)
        self._act_job = self.t.after(400, lambda: self._actions_off(n))  # kurz warten: Weg von Blase zu Zeile

    def _actions_off(self, n: int):
        self._act_job = None
        b = self.blocks.get(n)
        if b:
            b["shown"] = False
            self.t.tag_configure(f"uact:{n}", foreground=self.bg)

    def _refresh_actions(self):
        """Nach einem Designwechsel: ausgeblendete Aktionen wieder in der (neuen) Hintergrundfarbe."""
        for n, b in self.blocks.items():
            if b["kind"] == "umsg":
                self.t.tag_configure(f"uact:{n}", foreground=self.col["muted"] if b["shown"] else self.bg)

    def _begin_edit(self, n: int):
        """Blase durch ein Eingabefeld ersetzen. Die Blase wird nur versteckt (elide) – aus dem Text gelöschte
        eingebettete Fenster zerstört Tk, beim Abbrechen kommt sie so unverändert zurück."""
        b = self.blocks.get(n)
        if not b or b.get("editing") or not b.get("on_edit"):
            return
        try:
            idx = self.t.index(str(b["canvas"]))
        except tk.TclError:
            return
        line_tags = tuple(tg for tg in self.t.tag_names(idx) if tg.startswith("user"))
        frame, box = self._editor(n, b["text"])
        with self._edit(follow=False):
            self.t.window_create(idx, window=frame)
            self.t.insert(f"{idx}+1c", "\n", line_tags)
            for tg in line_tags:
                self.t.tag_add(tg, idx)
            bubble = self.t.index(str(b["canvas"]))
            self.t.tag_add(f"uhide:{n}", bubble, f"{bubble}+2c")   # Blase samt Zeilenende
            self.t.tag_configure(f"uhide:{n}", elide=True)
            self.t.tag_configure(f"uline:{n}", elide=True)
        b["editing"] = frame
        box.focus_set()
        box.mark_set("insert", "end-1c")

    def _end_edit(self, n: int):
        b = self.blocks.get(n)
        frame = b.pop("editing", None) if b else None
        if not frame:
            return
        with self._edit(follow=False):
            try:
                i = self.t.index(str(frame))
                self.t.delete(i, f"{i}+2c")
            except tk.TclError:
                pass
            self.t.tag_configure(f"uhide:{n}", elide=False)
            self.t.tag_configure(f"uline:{n}", elide=False)

    def _editor(self, n: int, text: str) -> tuple[tk.Frame, tk.Text]:
        """Bearbeitungsfeld in Blasenbreite mit „Abbrechen“/„Senden“ (Enter sendet, Umschalt+Enter = neue Zeile)."""
        col, s = self.col, self._s
        frame = tk.Frame(self.t, background=self.bg, highlightthickness=0)
        width = max(20, (self._bubble_max() - 2 * s(12)) // max(1, self.f_base.measure("0")))
        lines = sum(1 + len(ln) // max(1, width) for ln in text.split("\n"))
        box = tk.Text(frame, wrap="word", font=self.f_base, undo=True, width=width, height=max(2, min(lines, 12)),
                      relief="flat", borderwidth=0, padx=s(12), pady=s(9), background=col["code_hdr"],
                      foreground=col["fg"], insertbackground=col["fg"], selectbackground=col["accent"],
                      selectforeground="#ffffff", highlightthickness=1, highlightbackground=col["rule"],
                      highlightcolor=col["accent"])
        box.insert("1.0", text)
        box.pack(fill=tk.X)
        bar = tk.Frame(frame, background=self.bg)
        bar.pack(fill=tk.X, pady=(s(6), s(10)))

        def submit(_e=None):
            new = box.get("1.0", "end-1c").strip()
            if not new or new == self.blocks.get(n, {}).get("text"):
                self._end_edit(n)
            elif not self.blocks[n]["on_edit"](new):  # nicht möglich (z. B. Antwort läuft) → Feld bleibt offen
                box.focus_set()
            return "break"

        def on_enter(e):
            return None if e.state & 0x0001 else submit()  # Umschalt+Enter: neue Zeile

        ttk.Button(bar, text="Senden", style="Accent.TButton", command=submit).pack(side=tk.RIGHT)
        ttk.Button(bar, text="Abbrechen", command=lambda: self._end_edit(n)).pack(side=tk.RIGHT, padx=(0, s(6)))
        tk.Label(bar, text="Die bisherige Fassung bleibt erhalten (‹ ›).", background=self.bg,
                 foreground=col["muted"], font=self.f_tiny).pack(side=tk.LEFT)
        box.bind("<Return>", on_enter)
        box.bind("<Escape>", lambda e: self._end_edit(n))
        return frame, box

    def _draw_quote(self, c: tk.Canvas, quote: str):
        """Zitat über der eigenen Nachricht: Kärtchen mit Akzentstreifen links und dem markierten Text."""
        if not self.col:
            return
        c.delete("all")
        s = self._s
        pad, bar, r = s(9), s(3), s(10)
        short = " ".join(quote.split())
        short = short if len(short) <= 220 else short[:219].rstrip() + "…"
        tid = c.create_text(pad + bar + s(9), pad, text=short, anchor="nw", font=self.f_small_i,
                            width=self._bubble_max() - 2 * pad - bar - s(9), fill=self.col["muted"])
        x1, y1, x2, y2 = c.bbox(tid)
        w, h = x2 + pad, max(y2 - y1 + 2 * pad, 2 * r + 2)
        c.configure(width=w, height=h, background=self.bg)
        self._rounded(c, 0, 0, w, h, r, self.col["code_hdr"])
        c.create_rectangle(pad, pad, pad + bar, h - pad, fill=self.col["accent"], outline="")
        c.tag_raise(tid)

    # ---------------------------------------------------------------- Gruppenchat: andere Teilnehmer (links)

    def sender(self, name: str, sub: str = "", color: str | None = None):
        """Absenderzeile über einer Nachricht anderer (Mensch oder KI), z. B. „✦ Max-KI  ·  Qwen3.8-27B“."""
        self._ensure()
        self.md_finish()
        tags = ("who",)
        if color:
            tag = "col_" + color.lstrip("#")
            self.t.tag_configure(tag, foreground=color)
            tags += (tag,)
        with self._edit():
            self.t.insert(self._at, name, tags)
            if sub:
                self.t.insert(self._at, "   " + sub, ("who", "who_sub"))
            self.t.insert(self._at, "\n", "who")

    def other(self, text: str, files: list[dict] | None = None):
        """Nachricht eines anderen Menschen: links, neutrale Blase (Kärtchen darüber), beim Darüberfahren
        „Kopieren“ darunter."""
        self._ensure()
        self.md_finish()
        hover: list[tk.Canvas] = []
        with self._edit():
            if files:
                c = self._canvas("arrow")
                self._bind_cards(c)
                self.bubbles.append((c, "files", files))
                self._draw_files(c, files)
                self._embed(c, "other")
                hover.append(c)
            if text:
                c = self._canvas("arrow")
                c.bind("<Button-3>", lambda e, s=text: self._on_bubble_menu(e, s))
                self.bubbles.append((c, "obubble", text))
                self._draw_bubble(c, text, other=True)
                self._embed(c, "other_a")
                self._user_actions(c, text, {}, hover + [c], base="oact")

    def cards(self, files: list[dict]):
        """Datei-Kärtchen links – z. B. von einer KI geteilt (im Gruppenchat im Platz ihrer Antwort)."""
        if not files:
            return
        self._ensure()
        self.md_finish()
        with self._edit():
            c = self._canvas("arrow")
            self._bind_cards(c)
            self.bubbles.append((c, "files", files))
            self._draw_files(c, files)
            self._embed(c, "other")

    def tool_line(self, icon: str, label: str, detail: str, ok: bool | None):
        """Werkzeugaufruf einer fremden KI (nur Kopfzeile – Eingaben/Ergebnisse bleiben auf deren Rechner)."""
        self._ensure()
        self.md_finish()
        text = f"{icon}  {label}" + (f"  ·  {detail}" if detail else "")
        with self._edit():
            self.t.insert(self._at, text, "tool_hdr")
            if ok is not None:
                self.t.insert(self._at, "  ✓" if ok else "  ✗", ("tool_hdr", "st_ok" if ok else "st_err"))
            self.t.insert(self._at, "\n", "tool_hdr")

    def _canvas(self, cursor: str) -> tk.Canvas:
        c = tk.Canvas(self.t, highlightthickness=0, borderwidth=0, background=self.bg, cursor=cursor)
        c.bind("<MouseWheel>", self._on_wheel)
        return c

    def _embed(self, widget, tag: str):
        idx = self.t.index(self._at)
        self.t.window_create(self._at, window=widget)
        self.t.insert(self._at, "\n", tag)
        self.t.tag_add(tag, idx)

    def _area_width(self) -> int:
        w = self.t.winfo_width()
        if w <= 1:
            w = self._s(MAX_COLUMN) + 2 * self._s(24)
        pad = self._padx if self._padx is not None else int(self.t.cget("padx"))
        return max(self._s(200), w - 2 * pad - 4)

    def _bubble_max(self) -> int:
        return min(round(self._area_width() * 0.78), self._s(620))

    def _rounded(self, c: tk.Canvas, x: int, y: int, w: int, h: int, r: int, fill: str, tags=(), under=None):
        rounded(c, self._corners, x, y, w, h, r, fill, under or self.bg, tags)

    def _draw_bubble(self, c: tk.Canvas, text: str, other: bool = False):
        """Sprechblase; other=True: neutrale Farbe für Nachrichten anderer Menschen im Gruppenchat."""
        if not self.col:
            return
        c.delete("all")
        px, py, r = self._s(14), self._s(9), self._s(13)
        fg = self.col["fg"] if other else self.col["bubble_fg"]
        tid = c.create_text(px, py, text=text.replace("\t", "    "), anchor="nw", font=self.f_base,
                            width=self._bubble_max() - 2 * px, fill=fg)
        x1, y1, x2, y2 = c.bbox(tid)
        w, h = max(x2 - x1 + 2 * px, 2 * r + 4), max(y2 - y1 + 2 * py, 2 * r + 2)
        c.configure(width=w, height=h, background=self.bg)
        self._rounded(c, 0, 0, w, h, r, self.col["code_hdr"] if other else self.col["bubble"])
        c.tag_raise(tid)

    def _thumb(self, path: str | None, max_w: int) -> tk.PhotoImage | None:
        """Vorschaubild (PNG) eines angehängten Bildes, zwischengespeichert; zu breite werden verkleinert."""
        if not path or not os.path.exists(path):
            return None
        if path in self._thumbs:
            img = self._thumbs[path] = self._thumbs.pop(path)  # ans Ende: zuletzt benutzt (siehe clear)
        else:
            try:
                img = tk.PhotoImage(master=self.t, file=path)
            except tk.TclError:
                img = None
            self._thumbs[path] = img
        if img is None or img.width() <= max_w:
            return img
        factor = min(8, -(-img.width() // max(1, max_w)))  # aufgerundet
        key = (path, factor)
        small = self._thumbs.pop(key, None) or img.subsample(factor)
        self._thumbs[key] = small
        return small

    def _draw_files(self, c: tk.Canvas, files: list[dict]):
        """Datei-Kärtchen: farbiges Typ-Abzeichen, Dateiname und Infozeile – bei Bildern stattdessen das
        Vorschaubild über Name und Infozeile; mehrere Kärtchen umbrechen."""
        if not self.col:
            return
        c.delete("all")
        s = self._s
        pad, gap, r, badge = s(9), s(6), s(10), s(34)
        line1, line2 = self.f_small_b.metrics("linespace"), self.f_tiny.metrics("linespace")
        card_h = max(badge, line1 + line2) + 2 * pad
        maxw = self._bubble_max()
        boxes, x, y, row_h = [], 0, 0, 0
        for f in files:
            name = f.get("name", "")
            name = name if len(name) <= 36 else name[:24] + "…" + name[-10:]
            info = f.get("info", "")
            text_w = max(self.f_small_b.measure(name), self.f_tiny.measure(info))
            img = self._thumb(f.get("thumb"), maxw - 2 * pad)
            if img:
                w = min(max(img.width(), text_w) + 2 * pad, maxw)
                h = pad + img.height() + s(6) + line1 + line2 + pad
            else:
                w, h = min(pad + badge + s(10) + text_w + s(14), maxw), card_h
            if x and x + w > maxw:
                x, y, row_h = 0, y + row_h + gap, 0
            boxes.append((x, y, w, h, name, info, f, img))
            x += w + gap
            row_h = max(row_h, h)
        total_w = max(bx + bw for bx, _, bw, *_ in boxes)
        c.configure(width=total_w, height=y + row_h, background=self.bg)
        row_end = {}
        for bx, by, bw, *_ in boxes:
            row_end[by] = max(row_end.get(by, 0), bx + bw)
        for i, (bx, by, bw, h, name, info, f, img) in enumerate(boxes):
            bx += total_w - row_end[by]  # jede Zeile rechtsbündig, wie die Sprechblase
            tag = f"card{i}"
            self._rounded(c, bx, by, bw, h, r, self.col["code_hdr"], tags=(tag,))
            if img:
                c.create_image(bx + pad, by + pad, image=img, anchor="nw", tags=(tag,))
                tx, ty = bx + pad, by + pad + img.height() + s(6)
            else:
                ext = (f.get("name", "").rsplit(".", 1)[-1].upper() if "." in f.get("name", "") else "DATEI")[:4]
                color = BADGE_COLORS.get(ext, self.col["accent"])
                self._rounded(c, bx + pad, by + (h - badge) // 2, badge, badge, s(7), color, tags=(tag,),
                              under=self.col["code_hdr"])
                c.create_text(bx + pad + badge // 2, by + h // 2, text=ext, fill="#ffffff", font=self.f_label,
                              tags=(tag,))
                tx, ty = bx + pad + badge + s(10), by + (h - line1 - line2) // 2
            c.create_text(tx, ty, text=name, anchor="nw", fill=self.col["fg"], font=self.f_small_b, tags=(tag,))
            c.create_text(tx, ty + line1, text=info, anchor="nw", fill=self.col["muted"], font=self.f_tiny,
                          tags=(tag,))
        c.card_paths = [f.get("path", "") for f in files]
        c.card_files = files
        c.configure(cursor="hand2" if any(f.get("action") for f in files) else "arrow")

    @staticmethod
    def _card_at(c: tk.Canvas) -> dict | None:
        for tag in c.gettags("current"):
            if tag.startswith("card") and tag[4:].isdigit():
                files = getattr(c, "card_files", [])
                i = int(tag[4:])
                return files[i] if i < len(files) else None
        return None

    def _bind_cards(self, c: tk.Canvas):
        """Kärtchen mit "action" (Teamwork: Herunterladen) reagieren auf einen Klick; die übrigen öffnet ein
        Doppelklick (angehängte Datei)."""
        def click(_e):
            card = self._card_at(c)
            if card and card.get("action"):
                card["action"]()

        def double(_e):
            card = self._card_at(c)
            if not (card and card.get("action")):
                self._open_file(self._card_path(c))

        c.bind("<Button-1>", click)
        c.bind("<Double-Button-1>", double)

    @staticmethod
    def _card_path(c: tk.Canvas) -> str:
        for tag in c.gettags("current"):
            if tag.startswith("card") and tag[4:].isdigit():
                paths = getattr(c, "card_paths", [])
                i = int(tag[4:])
                return paths[i] if i < len(paths) else ""
        return ""

    def redraw_cards(self, cards: list[dict]):
        """Nur die Kärtchen-Zeilen neu zeichnen, die eines dieser Kärtchen enthalten (z. B. Vorschau nachgeladen)."""
        wanted = {id(card) for card in cards}
        for c, kind, data in self.bubbles:
            if kind == "files" and c.winfo_exists() and any(id(f) in wanted for f in data):
                self._draw_files(c, data)

    def _redraw_bubbles(self):
        self._bubble_w = self._bubble_max()
        for c, kind, data in self.bubbles:
            if c.winfo_exists():
                if kind == "files":
                    self._draw_files(c, data)
                elif kind == "quote":
                    self._draw_quote(c, data)
                else:
                    self._draw_bubble(c, data, other=kind == "obubble")

    def _on_configure(self, _e=None):
        self._hide_quote_pop()
        if self._layout_job:
            self.t.after_cancel(self._layout_job)
        self._layout_job = self.t.after(40, self._relayout)

    def _relayout(self):
        """Spalte mittig halten und Sprechblasen an die neue Breite anpassen."""
        self._layout_job = None
        w = self.t.winfo_width()
        if w <= 1:
            return
        side = max(self._s(24), (w - self._s(MAX_COLUMN)) // 2)
        if side != self._padx:
            self._padx = side
            self.t.configure(padx=side)
        if self._bubble_max() != self._bubble_w:
            self._redraw_bubbles()
        if self._stick:
            self.t.see("end")

    # ================================================================ Markdown (auch gestreamt)

    def markdown(self, text: str):
        """Fertigen Text auf einmal darstellen (z. B. beim Öffnen eines gespeicherten Chats)."""
        self.md_append(text)
        self.md_finish()

    def _after_block(self) -> bool:
        """Steht direkt davor ein Denkprozess-/Werkzeug-Block? Dann etwas Abstand zum Antworttext."""
        tags = set(self.t.tag_names(f"{self._at}-1c"))
        return bool(tags & {"think_hdr", "tool_hdr", "think_pad", "pre_pad", "note", "error"})

    def _md_begin(self):
        self._n += 1
        self.md = {"line": "", "code": None, "table": None, "levels": ListLevels(), "any": False, "blank": True,
                   "mark": f"mdl:{self._n}"}  # Marke am Anfang der angefangenen (noch offenen) Zeile
        self.t.mark_set(self.md["mark"], self._at)
        self.t.mark_gravity(self.md["mark"], "left")

    def md_append(self, text: str):
        """Hängt gestreamten Text an. Fertige Zeilen werden endgültig gesetzt, die angefangene letzte Zeile
        wird bei jedem Aufruf neu gezeichnet (so wird z. B. **fett** fett, sobald es geschlossen ist)."""
        if not text:
            return
        self._ensure()
        self.hide_pending()
        new = self.md is None
        if new:
            self._md_begin()
        md = self.md
        lines = (md["line"] + text).split("\n")
        md["line"] = lines.pop()
        with self._edit():
            if new and self._after_block():
                self.t.insert(self._at, "\n", "gap")
                self.t.mark_set(self.md["mark"], self._at)
            self.t.delete(self.md["mark"], self._at)
            for k, line in enumerate(lines):
                self._md_line(line, partial=False, following=lines[k + 1] if k + 1 < len(lines) else None)
                self.t.mark_set(self.md["mark"], self._at)
            if md["line"]:
                self._md_line(md["line"], partial=True)

    def md_finish(self):
        md = self.md
        if md is None:
            return
        with self._edit():
            self.t.delete(self.md["mark"], self._at)
            if md["line"]:
                self._md_line(md["line"], partial=False)
            if md["code"] is not None:
                self._code_end()
            while self.t.get(f"{self._at}-1c") == "\n" and "gap" in self.t.tag_names(f"{self._at}-1c"):
                self.t.delete(f"{self._at}-1c")
        self.md = None

    def _md_line(self, line: str, partial: bool, following: str | None = None):
        """following: die nächste schon fertige Zeile (falls bekannt) – folgen weitere Tabellenzeilen, wird die
        Tabelle erst nach der letzten gesetzt statt nach jeder Zeile neu (gespeicherte Chats öffnen)."""
        md = self.md
        ins = self.t.insert
        if md["code"] is not None:
            if closes_fence(line, md["code"]["fence"]):
                if not partial:
                    self._code_end()
                return
            self._code_line(line)
            return
        kind, info = classify(line)
        if kind != "table" and not partial:
            md["table"] = None
        if kind == "blank":
            if not partial and md["any"] and not md["blank"]:
                ins(self._at, "\n", "gap")
                md["blank"] = True
            return
        if partial and kind in ("fence", "table", "hr", "pagebreak"):
            return
        gap = not md["blank"]  # Abstand vor Blöcken nur, wenn nicht schon eine Leerzeile davor stand
        if not partial:
            md["any"], md["blank"] = True, False
            if kind not in ("bullet", "number"):
                md["levels"].reset()
        if kind == "fence":
            self._code_start(info, gap)
        elif kind == "table":
            self._table_row(line, gap, defer=following is not None and classify(following)[0] == "table")
        elif kind == "heading":
            tag = f"md_h{min(info['level'], 3)}"
            self._inline(info["text"], (tag,), fonts=False, partial=partial)
            ins(self._at, "\n", tag)
        elif kind in ("hr", "pagebreak"):
            if gap:
                ins(self._at, "\n", "gap")
            ins(self._at, "\n", "hr")
            ins(self._at, "\n", "gap")
            md["blank"] = True
        elif kind in ("bullet", "number"):
            self._list_item(kind, info, partial)
        elif kind == "quote":
            self._inline(info["text"], ("p", "quote"), partial=partial)
            ins(self._at, "\n", ("p", "quote"))
        else:
            self._inline(info["text"], ("p",), partial=partial)
            ins(self._at, "\n", "p")

    def _inline(self, text: str, base: tuple, fonts: bool = True, partial: bool = False):
        for seg, st, url in inline(text):
            tags = list(base)
            if "code" in st:
                tags.append("code")
            elif fonts and "b" in st and "i" in st:
                tags.append("bi")
            elif fonts and "b" in st:
                tags.append("b")
            elif fonts and "i" in st:
                tags.append("i")
            if "s" in st:
                tags.append("s")
            if url:
                tags.append("link")
                if not partial:  # angefangene Zeilen werden ständig neu gezeichnet – erst fertige Links klickbar
                    tags += ["clickable", f"lnk:{self._new('link', url=url)}"]
            self.t.insert(self._at, seg, tuple(tags))

    def _list_item(self, kind: str, info: dict, partial: bool):
        levels = self.md["levels"]
        if partial:  # Zustand nicht verändern
            levels = ListLevels()
            levels.stack = list(self.md["levels"].stack)
        level = min(levels.level(info["indent"]), 4)
        if kind == "number":
            prefix, hang = info["num"] + ".", self.f_base.measure("00.") + self._s(7)
        elif info.get("task"):
            prefix, hang = info["task"], self.f_base.measure("☐") + self._s(8)
        else:
            prefix, hang = BULLETS[level % len(BULLETS)], self._s(18)
        lm1 = self._s(6) + level * self._s(24)
        lm2 = lm1 + hang
        tag = f"ind_{lm1}_{lm2}"
        if tag not in self._indent_tags:
            # Tabstopp genau beim Einzug: Text nach dem Aufzählungszeichen und Folgezeilen stehen bündig
            self.t.tag_configure(tag, lmargin1=lm1, lmargin2=lm2, tabs=(lm2,))
            self._indent_tags.add(tag)
        base = ("li", tag)
        self.t.insert(self._at, prefix, base + ("bullet",))
        self.t.insert(self._at, "\t", base)
        self._inline(info["text"], base, partial=partial)
        self.t.insert(self._at, "\n", base)

    # ---------------------------------------------------------------- Code-Blöcke

    def _code_start(self, info: dict, gap: bool):
        n = self._new("code")
        self.md["code"] = {"n": n, "fence": info["fence"], "lang": info["lang"]}
        if gap:
            self.t.insert(self._at, "\n", "gap")
        self.t.insert(self._at, (info["lang"] or "code") + "      ", "pre_hdr")
        self.t.insert(self._at, "⧉ Kopieren", ("pre_hdr", "clickable", f"ccp:{n}"))
        self.t.insert(self._at, "\n", "pre_hdr")
        self.t.insert(self._at, "\n", "pre_pad")

    def _code_line(self, line: str):
        code = self.md["code"]
        base = ("pre", f"code:{code['n']}")
        line = line.expandtabs(4)
        pos = 0
        for start, end, kind in highlight(line, code["lang"]):
            if start > pos:
                self.t.insert(self._at, line[pos:start], base)
            self.t.insert(self._at, line[start:end], base + (f"c_{kind}",))
            pos = end
        if pos < len(line):
            self.t.insert(self._at, line[pos:], base)
        self.t.insert(self._at, "\n", base)

    def _code_end(self):
        self.t.insert(self._at, "\n", "pre_pad")
        self.t.insert(self._at, "\n", "gap")
        self.md["code"] = None
        self.md["blank"] = True

    # ---------------------------------------------------------------- Tabellen

    def _table_row(self, line: str, gap: bool, defer: bool = False):
        md = self.md
        tb = md["table"]
        if tb is None:
            tb = md["table"] = {"n": self._new("table"), "rows": []}
            if gap:
                self.t.insert(self._at, "\n", "gap")
            self.t.mark_set(f"tbl:{tb['n']}", self._at)
            self.t.mark_gravity(f"tbl:{tb['n']}", "left")
        tb["rows"].append(line)
        md["blank"] = True
        if not defer:
            self.t.delete(f"tbl:{tb['n']}", self._at)  # Tabelle mit der neuen Zeile komplett neu setzen
            self._render_table(tb)

    def _render_table(self, tb: dict):
        rows = [split_row(r) for r in tb["rows"]]
        header = None
        if len(rows) >= 2 and is_separator_row(rows[1]):
            header, body = rows[0], rows[2:]
        elif len(rows) == 1:
            header, body = rows[0], []
        else:
            body = [r for r in rows if not is_separator_row(r)]
        all_rows = ([header] if header else []) + body
        ncols = max(len(r) for r in all_rows)
        cells = [[plain(r[c]).replace("\t", " ") if c < len(r) else "" for c in range(ncols)] for r in all_rows]
        gutter = self._s(22)
        natural = [1] * ncols
        for ri, row in enumerate(cells):
            font = self.f_bold if header and ri == 0 else self.f_base
            for c, txt in enumerate(row):
                natural[c] = max(natural[c], font.measure(txt))
        avail = self._area_width() - self._s(8) - gutter * (ncols - 1)
        widths = self._fit(natural, max(avail, ncols * self._s(40)))
        stops, x = [], 0
        for w in widths[:-1]:
            x += w + gutter
            stops.append(x)
        tag = f"tbl:{tb['n']}"
        self.t.tag_configure(tag, tabs=tuple(stops) if stops else "")
        for ri, row in enumerate(cells):
            head = header is not None and ri == 0
            font = self.f_bold if head else self.f_base
            wrapped = [self._wrap(txt, widths[c], font) for c, txt in enumerate(row)]
            for k in range(max(len(w) for w in wrapped)):
                text = "\t".join(w[k] if k < len(w) else "" for w in wrapped)
                self.t.insert(self._at, text + "\n", ("th" if head else "td", tag))
            if head:
                self.t.insert(self._at, "\n", "trule")
            elif ri < len(cells) - 1:
                self.t.insert(self._at, "\n", "trule_soft")
        self.t.insert(self._at, "\n", "gap")

    @staticmethod
    def _fit(natural: list[int], avail: int) -> list[int]:
        """Spaltenbreiten: passt alles, bleibt es natürlich; sonst bekommen schmale Spalten zuerst ihren Platz."""
        if sum(natural) <= avail:
            return list(natural)
        widths, remaining = [0] * len(natural), avail
        order = sorted(range(len(natural)), key=lambda i: natural[i])
        for k, i in enumerate(order):
            widths[i] = max(1, min(natural[i], remaining // (len(natural) - k)))
            remaining -= widths[i]
        return widths

    @staticmethod
    def _wrap(text: str, width: int, font: tkfont.Font) -> list[str]:
        if not text or font.measure(text) <= width:
            return [text]
        lines, cur = [], ""
        for word in text.split():
            cand = f"{cur} {word}" if cur else word
            if font.measure(cand) <= width:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            while len(word) > 1 and font.measure(word) > width:
                cut = len(word) - 1
                while cut > 1 and font.measure(word[:cut]) > width:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            cur = word
        if cur:
            lines.append(cur)
        return lines or [""]

    # ================================================================ „Arbeitet …“-Anzeige

    def show_pending(self, label: str = "Arbeitet …"):
        if self._pending:
            return
        self._ensure()
        self.md_finish()
        with self._edit():
            self.t.insert(self._at, f"✻  {label}", ("think_hdr", "live", self._pend_tag))
            self.t.insert(self._at, "\n", ("think_hdr", self._pend_tag))
        self._pending = True
        self._pendings.add(self._pend_tag)
        self._animate()

    def hide_pending(self):
        if not self._pending:
            return
        self._pending = False
        self._pendings.discard(self._pend_tag)
        r = self.t.tag_ranges(self._pend_tag)
        if r:
            with self._edit():
                self.t.delete(r[0], r[-1])

    # ================================================================ Slots (Plätze für gleichzeitiges Schreiben)

    def slot_new(self) -> str:
        """Reserviert am Ende des Verlaufs einen Platz für eine Nachricht. Mit `with view.slot(id):` schreiben
        alle Methoden (md_append, think_*, tool_*, footer …) dorthin – auch wenn danach schon weitere
        Nachrichten folgen. So können mehrere KIs gleichzeitig antworten."""
        self._ensure()
        self.md_finish()
        self._n += 1
        sid = f"slot:{self._n}"
        with self._edit():
            pos = self.t.index("end-1c")
            self.t.insert("end-1c", "\n", "slot_end")  # unsichtbarer Abschluss: trennt den Platz vom Rest
            self.t.mark_set(sid, pos)
            self.t.mark_gravity(sid, "right")         # wandert hinter jeden eingefügten Text
        self._slots[sid] = {"md": None, "pending": False, "ptag": f"pend:{self._n}"}
        return sid

    @contextmanager
    def slot(self, sid: str):
        st = self._slots.get(sid)
        if st is None:  # z. B. nach clear() – dann einfach am Ende schreiben
            yield
            return
        saved = (self._at, self.md, self._pending, self._pend_tag)
        self._at, self.md, self._pending, self._pend_tag = sid, st["md"], st["pending"], st["ptag"]
        try:
            yield
        finally:
            st["md"], st["pending"] = self.md, self._pending
            self._at, self.md, self._pending, self._pend_tag = saved

    # ================================================================ Aufklappbare Blöcke

    def _header_parts(self, n: int) -> list[tuple[str, tuple]]:
        b = self.blocks[n]
        chev = OPENED if b["open"] else CLOSED
        if b["kind"] == "think":
            if b["live"]:
                secs = int(time.monotonic() - b["t0"])
                return [(f"✻  Denkt nach …  {secs} s" if secs else "✻  Denkt nach …", ())]
            secs = f"  ·  {b['secs']} s" if b.get("secs") else ""
            return [(f"{b.get('icon', '✻')}  {b['title'] or 'Gedankengang'}{secs}   {chev}", ())]
        text = f"{b['icon']}  {b['label']}" + (f"  ·  {b['detail']}" if b["detail"] else "")
        if b["live"]:
            return [(text + "  …", ())]
        mark = ("  ✓", ("st_ok",)) if b["ok"] else ("  ✗", ("st_err",))
        return [(text, ()), mark, (f"   {chev}", ())]

    def _write_header(self, n: int, at: str):
        b = self.blocks[n]
        base = "think_hdr" if b["kind"] == "think" else "tool_hdr"
        for text, extra in self._header_parts(n):
            self.t.insert(at, text, (base, "clickable", f"hdr:{n}") + (("live",) if b["live"] else ()) + extra)
        return base

    def _insert_header(self, n: int):
        self.t.insert(self._at, "\n", self._write_header(n, self._at))

    def _update_header(self, n: int):
        r = self.t.tag_ranges(f"hdr:{n}")
        if n not in self.blocks or not r:
            return
        with self._edit(follow=False):
            self.t.mark_set("hdr_ins", r[0])
            self.t.mark_gravity("hdr_ins", "right")
            self.t.delete(r[0], r[-1])
            self._write_header(n, "hdr_ins")

    def toggle(self, n: int):
        b = self.blocks.get(n)
        if not b or b["kind"] not in ("think", "tool"):
            return
        b["open"] = not b["open"]
        self.t.tag_configure(f"body:{n}", elide=not b["open"])
        self._update_header(n)

    # ---------------------------------------------------------------- Denkprozess

    def think_begin(self) -> int:
        self._ensure()
        self.md_finish()
        self.hide_pending()
        n = self._new("think", open=False, live=True, t0=time.monotonic(), title=None, secs=None,
                      started=False, held="")
        self.t.tag_configure(f"body:{n}", elide=True)
        self._live.add(n)
        with self._edit():
            self._insert_header(n)
            self.t.insert(self._at, "\n", ("think_pad", f"body:{n}"))
        self._animate()
        return n

    def think_append(self, n: int, text: str):
        b = self.blocks.get(n)
        if not b:
            return
        if not b["started"]:
            text = text.lstrip()
            if not text:
                return
            b["started"] = True
        text = b["held"] + text
        body = text.rstrip("\n")
        b["held"] = text[len(body):]   # Zeilenumbrüche am Ende zurückhalten (sonst Leerzeile im Block)
        if body:
            with self._edit():
                self.t.insert(self._at, body, ("think_body", f"body:{n}"))

    def think_end(self, n: int) -> int | None:
        """Schließt den Block ab (muss noch am Ende stehen) und gibt die Dauer in Sekunden zurück."""
        b = self.blocks.get(n)
        if not b or not b["live"]:
            return b["secs"] if b else None
        b["live"] = False
        self._live.discard(n)
        b["secs"] = max(1, round(time.monotonic() - b["t0"]))
        with self._edit():
            if b["started"]:
                self.t.insert(self._at, "\n", ("think_body", f"body:{n}"))
            self.t.insert(self._at, "\n", ("think_pad", f"body:{n}"))
        self._update_header(n)
        return b["secs"]

    def think_static(self, text: str, title: str | None = None, secs: int | None = None, icon: str = "✻") -> int:
        """Fertiger, zugeklappter Block (Denkprozess eines gespeicherten Chats – oder mit icon „≡“ die
        Zusammenfassung älterer Nachrichten)."""
        self._ensure()
        self.md_finish()
        n = self._new("think", open=False, live=False, t0=0, title=title, secs=secs, started=True, held="",
                      icon=icon)
        self.t.tag_configure(f"body:{n}", elide=True)
        with self._edit():
            self._insert_header(n)
            self.t.insert(self._at, "\n", ("think_pad", f"body:{n}"))
            self.t.insert(self._at, text.strip() + "\n", ("think_body", f"body:{n}"))
            self.t.insert(self._at, "\n", ("think_pad", f"body:{n}"))
        return n

    def set_think_title(self, n: int, title: str):
        b = self.blocks.get(n)
        if b and b["kind"] == "think":
            b["title"] = title
            self._update_header(n)

    # ---------------------------------------------------------------- Werkzeuge

    def tool_begin(self, label: str, detail: str, args_text: str, icon: str = "⚙") -> int:
        self._ensure()
        self.md_finish()
        self.hide_pending()
        n = self._new("tool", open=False, live=True, label=label, detail=detail, icon=icon, ok=None)
        self.t.tag_configure(f"body:{n}", elide=True)
        self._live.add(n)
        with self._edit():
            self._insert_header(n)
            self._tool_section(n, "EINGABE", args_text)
        self._animate()
        return n

    def tool_end(self, n: int, result: str, ok: bool):
        b = self.blocks.get(n)
        if not b:
            return
        b["live"], b["ok"] = False, ok
        self._live.discard(n)
        with self._edit():
            self._tool_section(n, "ERGEBNIS", result, last=True)
        self._update_header(n)

    def tool_static(self, label: str, detail: str, args_text: str, result: str | None, ok: bool, icon="⚙"):
        self._ensure()
        self.md_finish()
        n = self._new("tool", open=False, live=False, label=label, detail=detail, icon=icon, ok=ok)
        self.t.tag_configure(f"body:{n}", elide=True)
        with self._edit():
            self._insert_header(n)
            self._tool_section(n, "EINGABE", args_text)
            self._tool_section(n, "ERGEBNIS", result if result is not None else "(kein Ergebnis)", last=True)

    def _tool_section(self, n: int, label: str, text: str, last: bool = False):
        body = f"body:{n}"
        text = text if len(text) <= 4000 else text[:4000] + "\n…"
        self.t.insert(self._at, "\n", ("pre_pad", body))
        self.t.insert(self._at, label + "\n", ("tool_body", "tool_label", body))
        self.t.insert(self._at, text.rstrip() + "\n", ("tool_body", body))
        if last:
            self.t.insert(self._at, "\n", ("pre_pad", body))

    # ---------------------------------------------------------------- Sonstiges

    def footer(self, raw: str, tps: float | None = None):
        """Zeile unter einer fertigen Antwort: „Kopieren“ (Markdown-Text) und ggf. Tokens pro Sekunde."""
        self.md_finish()
        n = self._new("copy", text=raw)
        with self._edit():
            self.t.insert(self._at, "⧉ Kopieren", ("footer", "clickable", f"cpy:{n}"))
            if tps:
                self.t.insert(self._at, f"      {tps:.1f} Tokens/s".replace(".", ","), "footer")
            self.t.insert(self._at, "\n", "footer")

    def action(self, text: str, callback):
        """Anklickbare Zeile (z. B. „Ältere Nachrichten anzeigen“); callback läuft nach dem Klick."""
        self._ensure()
        n = self._new("action", fn=callback)
        with self._edit():
            self.t.insert(self._at, text, ("footer", "clickable", f"act:{n}"))
            self.t.insert(self._at, "\n", "footer")

    def note(self, text: str, kind: str = "note"):
        """kind "note" (grau, kursiv), "warn" (Hinweis in Warnfarbe) oder "error" (rot)."""
        self._ensure()
        self.md_finish()
        self.hide_pending()
        with self._edit():
            self.t.insert(self._at, text.strip() + "\n", kind)

    # ================================================================ Animation

    def _animate(self):
        if self._anim_job is None:
            self._anim_job = self.t.after(PULSE_MS, self._anim_step)

    def _anim_step(self):
        self._anim_job = None
        if not (self._live or self._pendings) or not self.col:
            return
        now = time.monotonic()
        k = (math.sin(now * 3.4) + 1) / 2
        self.t.tag_configure("live", foreground=mix_hex(self.col["muted"], self.col["accent"], k))
        for n in list(self._live):
            b = self.blocks.get(n)
            if b and b["kind"] == "think":
                secs = int(now - b["t0"])
                if secs != b.get("shown"):
                    b["shown"] = secs
                    self._update_header(n)
        self._anim_job = self.t.after(PULSE_MS, self._anim_step)

    # ================================================================ Maus & Zwischenablage

    def _on_wheel(self, e):
        self._hide_quote_pop()  # steht an fester Stelle – beim Scrollen würde es verrutschen
        if e.delta:
            self._scroll_left -= e.delta / 120 * 3 * self.f_base.metrics("linespace")
            if self._scroll_job is None:
                self._scroll_step()
        return "break"

    def _scroll_step(self):
        """Weiches Scrollen: pro Schritt ein Teil der Reststrecke."""
        self._scroll_job = None
        left = self._scroll_left
        if abs(left) < 1:
            self._scroll_left = 0.0
            return
        move = int(left * 0.3) or (1 if left > 0 else -1)
        before = self.t.yview()
        self.t.yview_scroll(move, "pixels")
        self._scroll_left -= move
        self._stick = self._at_bottom()
        if self.t.yview() == before:  # oben oder unten angekommen
            self._scroll_left = 0.0
            return
        self._scroll_job = self.t.after(12, self._scroll_step)

    def _stop_scroll(self):
        if self._scroll_job:
            self.t.after_cancel(self._scroll_job)
            self._scroll_job = None
        self._scroll_left = 0.0

    def _set_cursor(self, name: str):
        """Mauszeiger über dem Verlauf – gesetzt am Rahmen um das Textfeld, das ihn erbt (kostet ~0,1 ms statt
        ~10 ms im langen Chat). Unter Windows zusätzlich sofort, sonst erst bei der nächsten Mausbewegung."""
        if name == self._cursor:
            return
        self._cursor = name
        self.t.master.configure(cursor=name)
        if sys.platform == "win32":
            try:
                user32 = ctypes.windll.user32
                user32.LoadCursorW.restype = ctypes.c_void_p
                user32.SetCursor.argtypes = [ctypes.c_void_p]
                if self.t.winfo_containing(*self.t.winfo_pointerxy()) is self.t:
                    user32.SetCursor(user32.LoadCursorW(None, WIN_CURSORS[name]))
            except (OSError, AttributeError, KeyError, tk.TclError):
                pass

    def _on_enter_click(self, _e=None):
        self._set_cursor("hand2")
        for tag in self.t.tag_names("current"):
            if tag.startswith("hdr:"):
                r = self.t.tag_ranges(tag)
                if r:
                    self.t.tag_add("hover", r[0], r[-1])

    def _on_leave_click(self, _e=None):
        self._set_cursor("xterm")
        self.t.tag_remove("hover", "1.0", "end")

    def _on_click(self, _e=None):
        for tag in self.t.tag_names("current"):
            kind, _, num = tag.partition(":")
            if not num.isdigit() or int(num) not in self.blocks:
                continue
            n, b = int(num), self.blocks[int(num)]
            if kind == "hdr":
                self.toggle(n)
            elif kind == "cpy":
                self._copy(b["text"])
                self._flash(tag, "✓ Kopiert", ("footer", "clickable"))
            elif kind == "ccp":
                r = self.t.tag_ranges(f"code:{n}")
                self._copy(self.t.get(r[0], r[-1]).rstrip("\n") if r else "")
                self._flash(tag, "✓ Kopiert", ("pre_hdr", "clickable"))
            elif kind == "lnk":
                webbrowser.open(b["url"])
            elif kind == "ucp":
                self._copy(b["text"])
                self._flash(tag, "✓ Kopiert", (b["base"], "clickable", f"uact:{n}"))
            elif kind == "ued":
                self._begin_edit(n)
            elif kind in ("uvp", "uvn") and b.get("on_version"):
                self.t.after_idle(lambda f=b["on_version"], k=b["cur"] + (1 if kind == "uvn" else -1): f(k))
            elif kind == "act":  # nach dem Klick – die Aktion baut die Ansicht evtl. neu auf
                self.t.after_idle(b["fn"])
            else:
                continue
            return "break"

    def _flash(self, tag: str, text: str, tags: tuple):
        """Ersetzt kurz den Text eines Knopfs (z. B. „✓ Kopiert“) und stellt ihn danach wieder her."""
        r = self.t.tag_ranges(tag)
        if not r:
            return
        old, gen = self.t.get(r[0], r[-1]), self.gen
        if old == text:
            return

        def put(s):
            rr = self.t.tag_ranges(tag)
            if gen != self.gen or not rr:
                return
            with self._edit(follow=False):
                self.t.mark_set("flash", rr[0])
                self.t.mark_gravity("flash", "right")
                self.t.delete(rr[0], rr[-1])
                self.t.insert("flash", s, tags + (tag,))

        put(text)
        self.t.after(1500, lambda: put(old))

    def _copy(self, text: str):
        self.t.clipboard_clear()
        self.t.clipboard_append(text)

    # ---------------------------------------------------------------- Markierten Text beantworten / kopieren

    def _on_release(self, e):
        if self.on_quote:
            self.t.after_idle(lambda: self._show_quote_pop(e.x, e.y))

    def _show_quote_pop(self, x: int, y: int):
        """Kleines Feld „↳ Antworten  ⧉ Kopieren“ über der Stelle, an der die Markierung endet."""
        self._hide_quote_pop()
        if not self.t.tag_ranges("sel") or not self.col:
            return
        text = self.t.get("sel.first", "sel.last").strip()
        if len(text) < 2:
            return
        col, s = self.col, self._s
        pop = tk.Frame(self.t, background=col["rule"], padx=1, pady=1)   # 1 px Rahmen
        inner = tk.Frame(pop, background=col["code_hdr"])
        inner.pack()
        hover = mix_hex(col["code_hdr"], col["fg"], 0.12)

        def answer():
            self._hide_quote_pop()
            self.t.tag_remove("sel", "1.0", "end")
            self.on_quote(text)

        def copy():
            self._copy(text)
            self._hide_quote_pop()

        for label, command in (("↳ Antworten", answer), ("⧉ Kopieren", copy)):
            btn = tk.Label(inner, text=label, font=self.f_small, background=col["code_hdr"], foreground=col["fg"],
                           padx=s(10), pady=s(5), cursor="hand2")
            btn.pack(side=tk.LEFT)
            btn.bind("<Button-1>", lambda e, f=command: f())
            btn.bind("<Enter>", lambda e, w=btn: w.configure(background=hover))
            btn.bind("<Leave>", lambda e, w=btn: w.configure(background=col["code_hdr"]))
        pop.update_idletasks()
        w, h = pop.winfo_reqwidth(), pop.winfo_reqheight()
        line = self.t.dlineinfo(f"@{x},{y}")  # Bildschirmzeile unter der Maus: Feld darüber, sonst darunter
        top, height = (line[1], line[3]) if line else (y, 0)
        px = min(max(0, x - w // 2), max(0, self.t.winfo_width() - w))
        py = top - h - s(4) if top - h - s(4) >= 0 else top + height + s(4)
        pop.place(x=px, y=py)
        self._quote_pop = pop

    def _hide_quote_pop(self):
        if self._quote_pop:
            try:
                self._quote_pop.destroy()
            except tk.TclError:
                pass
            self._quote_pop = None

    def _copy_selection(self):
        if self.t.tag_ranges("sel"):
            self._copy(self.t.get("sel.first", "sel.last"))

    def _on_context(self, e):
        self.menu.entryconfigure(0, state=tk.NORMAL if self.t.tag_ranges("sel") else tk.DISABLED)
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _on_bubble_menu(self, e, text: str):
        self._bubble_text = text
        try:
            self.bubble_menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.bubble_menu.grab_release()

    def _on_file_menu(self, e, path: str):
        if not path:
            return
        self._file_path = path
        state = tk.NORMAL if os.path.exists(path) else tk.DISABLED
        self.file_menu.entryconfigure(0, state=state)
        try:
            self.file_menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.file_menu.grab_release()

    @staticmethod
    def _open_file(path: str):
        if path and os.path.exists(path):
            os.startfile(path)
