"""Seitenleiste „Quellen & Recherche“: zeigt live, was die KI im Internet sucht und liest und welche Dokumentseiten sie
im Experten-Modus nutzt – genau den Text, den das Modell bekommt (kein eingebauter Browser: der lüde jede Seite ein
zweites Mal, mit Cookies und Skripten, und zeigte oft etwas anderes). Dazu „Im Browser öffnen“, bei Dokumenten
Seitenbild, „Datei öffnen“ und „Im Ordner zeigen“; Quellenangaben in Antworten („Vertrag.pdf, Seite 4“) öffnen die
Seite hier.

Gebaut wird alles aus den Werkzeugaufrufen (Name, Argumente, Ergebnis) – live während einer Antwort und beim Öffnen
eines gespeicherten Chats aus dem Verlauf; im Chat wird dafür nichts Zusätzliches gespeichert. Die Ergebnisse haben
feste Formate (web.search, web.fetch, experte.Library.search/read) – die parse_*-Funktionen lesen sie zurück.
"""

from i18n import tr

import base64
import json
import re
import shutil
import tempfile
import threading
import time
import tkinter as tk
import unicodedata
import webbrowser
from pathlib import Path
from tkinter import ttk

import experte
import icons
import plattform
from themes import FAMILY, mix_hex

WIDTH = 400               # Breite der Seitenleiste (Pixel bei 100 %)
FOLLOW_PAUSE = 8.0        # hat der Nutzer selbst etwas ausgewählt, springt die Ansicht so lange nicht mit
TOOLS = {"web_search", "fetch_url", "experte_suchen", "experte_lesen"}
ANSWER_TAGS = {"p", "li", "quote", "md_h1", "md_h2", "md_h3", "td", "th"}  # Antworttext in chatview (nicht Werkzeuge)


# ---------------------------------------------------------------- Ergebnisse der Werkzeuge zurücklesen

def parse_web_search(result: str) -> list[dict]:
    """web.search: „[1] Titel\\nURL\\nKurztext“ je Treffer, durch Leerzeilen getrennt."""
    out = []
    for block in (result or "").strip().split("\n\n"):
        m = re.match(r"\[(\d+)\] (.*)\n(\S+)(?:\n(.*))?\Z", block.strip(), re.S)
        if m:
            out.append({"title": m[2].strip(), "url": m[3].strip(), "snippet": " ".join((m[4] or "").split())})
    return out


def parse_page(result: str) -> dict | None:
    """web.fetch: „Quelle: …\\nTitel: …\\n\\nText“ und evtl. „…(Zeichen a–b von n …)“ am Ende."""
    m = re.match(r"Quelle: (.*)\nTitel: (.*)\n\n", result or "")
    if not m:
        return None
    body = result[m.end():]
    page = {"url": m[1].strip(), "title": m[2].strip(), "start": 0, "end": None, "total": None}
    r = re.search(r"\n…\(Zeichen (\d+)–(\d+) von (\d+)[^)]*\)\Z", body)
    if r:
        body = body[:r.start()]
        page.update(start=int(r[1]), end=int(r[2]), total=int(r[3]))
    page["text"] = body
    return page


DOC_HIT = re.compile(r"^\d+\. (.+?) · (Seite|Abschnitt) (\d+): (.*?)( \(nur einzelne Suchwörter\))?$", re.M)


def parse_doc_hits(result: str) -> list[dict]:
    """experte.Library.search: „1. Datei · Seite 4: … »Treffer« …“."""
    return [{"file": m[1], "art": m[2], "nr": int(m[3]), "snippet": m[4], "partly": bool(m[5])}
            for m in DOC_HIT.finditer(result or "")]


def parse_doc_pages(result: str) -> dict | None:
    """experte.Library.read: „Datei:\\n--- Seite 4 ---\\nText …“."""
    m = re.match(r"(.+?):\n(?=--- (?:Seite|Abschnitt) \d+ ---\n)", result or "")
    if not m:
        return None
    rest = re.sub(r"\n…\(weiter mit von=\d+\)\Z", "", result[m.end():])
    parts = re.split(r"^--- (Seite|Abschnitt) (\d+) ---\n", rest, flags=re.M)
    pages = [(parts[i], int(parts[i + 1]), parts[i + 2].strip()) for i in range(1, len(parts) - 2, 3)]
    return {"file": m[1], "pages": pages} if pages else None


def _args(raw) -> dict:
    try:
        a = json.loads(raw) if isinstance(raw, str) and raw.strip() else raw or {}
        return a if isinstance(a, dict) else {}
    except ValueError:
        return {}


def fold(text: str) -> str:
    """Zeichen für Zeichen klein und ohne Umlautpunkte/Akzente – gleich lang wie text (Markieren an derselben Stelle)."""
    return "".join((unicodedata.normalize("NFKD", ch)[:1] or ch).lower() for ch in text)


def art_label(art: str) -> str:
    return tr('Abschnitt') if art == "Abschnitt" else tr('Seite')


def term_pattern(query: str) -> re.Pattern | None:
    """Wörter einer Suche (ohne Füllwörter) für die Markierung im Seitentext: jedes Wort, das sie enthält."""
    stems = sorted({experte._stem(experte._norm(w)) for p in str(query or "").split("|")
                    for w in experte.search_words(p)}, key=len, reverse=True)
    stems = [s for s in stems if len(s) >= 3]
    return re.compile(r"\w*(?:" + "|".join(map(re.escape, stems)) + r")\w*") if stems else None


def citation_pattern(files: list[str]) -> tuple[re.Pattern, dict] | None:
    """Quellenangaben in Antworten: Dateiname (mit Pfad, Name oder Name ohne Endung), dahinter evtl. „Seite 4“,
    „S. 4“, „Abschnitt 2“, „page 4“ → (Muster, Name in klein → Datei der Auswertung)."""
    names: dict[str, str] = {}
    for rel in files:
        for name in {rel, Path(rel).name, Path(rel).stem}:
            if len(name) >= 4 and name.lower() not in names:
                names[name.lower()] = rel
    if not names:
        return None
    alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    pattern = re.compile(rf"(?<![\w/\\])(?P<name>{alts})(?![\w])(?P<page>[^\n]{{0,30}}?\b(?:Seiten?|S\.|Abschnitte?|"
                         rf"p\.|pages?)\s*(?P<nr>\d+))?", re.I)
    return pattern, names


def tk_index(base: str, text: str, offset: int) -> str:
    """Tk-Index von Zeichen offset in text, das bei base beginnt – Tk 8.6 zählt Zeichen außerhalb der Grundebene
    (Emojis) doppelt."""
    extra = sum(1 for ch in text[:offset] if ord(ch) > 0xFFFF) if tk.TkVersion < 9 else 0
    return f"{base}+{offset + extra}c"


# ---------------------------------------------------------------- Seitenleiste

class SourcePanel:
    """Rechte Seitenleiste. app: monhip.App (theme, ui_scale, cfg, Experten-Bibliothek des Chats); before: Widget,
    vor dem sie eingepackt wird (sie liegt dann rechts neben dem Hauptbereich)."""

    def __init__(self, app, before):
        self.app = app
        s = app.ui_scale
        self.frame = ttk.Frame(app.root, style="Sidebar.TFrame", width=round(WIDTH * s))
        self.frame.pack_propagate(False)
        self._before = before
        self.sep = ttk.Separator(app.root, orient=tk.VERTICAL)
        head = ttk.Frame(self.frame, style="Sidebar.TFrame", padding=(12, 10, 8, 6))
        head.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(head, text=tr('Quellen & Recherche'), style="Sidebar.TLabel",
                  font=(FAMILY, 11, "bold")).pack(side=tk.LEFT)
        ttk.Button(head, style="Sidebar.TButton", width=3, command=self.close, **icons.only("close")).pack(
            side=tk.RIGHT)
        # oben: Liste (je Frage eine Gruppe), unten: Inhalt des gewählten Eintrags
        lf = ttk.Frame(self.frame, style="Sidebar.TFrame", padding=(8, 0, 2, 4))
        lf.pack(side=tk.TOP, fill=tk.X)
        self.tree = ttk.Treeview(lf, show="tree", selectmode="browse", style="Sidebar.Treeview", height=7)
        sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.tree.yview, style="Sidebar.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.tag_configure("group", font=(FAMILY, 8, "bold"))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.buttons = ttk.Frame(self.frame, style="Sidebar.TFrame", padding=(8, 2, 8, 8))
        self.buttons.pack(side=tk.BOTTOM, fill=tk.X)
        tf = tk.Frame(self.frame, borderwidth=0, highlightthickness=0)
        tf.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=(8, 2))
        self.text = tk.Text(tf, wrap=tk.WORD, width=1, height=1, borderwidth=0, highlightthickness=0, padx=10,
                            pady=8, font=(FAMILY, 10), cursor="arrow", insertontime=0)
        tsb = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self.text.yview)
        self.text.configure(yscrollcommand=tsb.set)
        tsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        app.theme.register_text(self.text, role="plain")
        self.text.bind("<Key>", lambda e: None if (e.state & 4 and e.keysym.lower() in ("c", "a")) else "break")
        self.text.tag_bind("link", "<Enter>", lambda e: self.text.configure(cursor="hand2"))
        self.text.tag_bind("link", "<Leave>", lambda e: self.text.configure(cursor="arrow"))
        self.text.tag_bind("link", "<Button-1>", self._on_link)

        self.entries: dict[str, dict] = {}   # Baum-Eintrag → Daten
        self.group: str | None = None        # aktuelle Frage
        self.pending: str | None = None      # Eintrag, dessen Ergebnis noch aussteht (live)
        self.read_urls: set[str] = set()     # schon gelesene Seiten (in der Treffer-Liste markiert)
        self.last_terms: re.Pattern | None = None
        self._links: dict[str, object] = {}
        self._picked = 0.0                   # wann der Nutzer zuletzt selbst etwas gewählt hat
        self._selecting = False
        self._shown: str | None = None
        self._image = None                   # Seitenbild (PhotoImage) – Verweis halten
        self.visible = False
        self._refresh_colors()

    # ------------------------------------------------------------ Sichtbarkeit

    def show(self):
        if not self.visible:
            self.frame.pack(side=tk.RIGHT, fill=tk.Y, before=self._before)
            self.sep.pack(side=tk.RIGHT, fill=tk.Y, before=self._before)
            self.visible = True

    def hide(self):
        if self.visible:
            self.frame.pack_forget()
            self.sep.pack_forget()
            self.visible = False

    def close(self):
        """Vom Nutzer geschlossen: öffnet sich nicht mehr von selbst, bis er sie wieder öffnet (Knopf „Quellen“)."""
        self.hide()
        self.app.cfg["quellen_auto"] = False

    def toggle(self):
        if self.visible:
            self.close()
        else:
            self.app.cfg["quellen_auto"] = True
            self.show()
            if not self.tree.get_children():
                self._render_empty()

    def _auto_show(self):
        if self.app.cfg.get("quellen_auto", True) and self.app.mode == "chat":
            self.show()

    # ------------------------------------------------------------ Inhalt

    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self.entries.clear()
        self.group = self.pending = self._shown = None
        self.read_urls.clear()
        self.last_terms = None
        self._render_empty()

    def question(self, text: str):
        """Neue Frage des Nutzers: eigene Gruppe, die vorigen werden zugeklappt."""
        for item in self.tree.get_children():
            self.tree.item(item, open=False)
        title = " ".join(str(text or "").split()) or tr('Frage')
        self.group = self.tree.insert("", "end", text=title if len(title) <= 60 else title[:59] + "…", open=True,
                                      tags=("group",))
        self.pending = None
        self._picked = 0.0

    def tool_call(self, name: str, raw_args, live: bool = True):
        if name not in TOOLS:
            self.pending = None
            return
        if self.group is None:
            self.question("")
        a = _args(raw_args)
        if name == "fetch_url" and a.get("start"):  # Weiterlesen: an den Eintrag derselben Seite anhängen
            same = next((i for i in reversed(self.tree.get_children(self.group))
                         if self.entries[i]["kind"] == "page" and self.entries[i]["url"] == a.get("url")), None)
            if same:
                self.pending = same
                self._set_label(same, running=True)
                if live:
                    self._follow(same)
                return
        kind = {"web_search": "web", "fetch_url": "page", "experte_suchen": "docs", "experte_lesen": "doc"}[name]
        entry = {"kind": kind, "args": a, "running": True, "error": None, "url": a.get("url", ""), "chunks": []}
        item = self.tree.insert(self.group, "end", text="")
        self.entries[item] = entry
        self.pending = item
        self._set_label(item, running=True)
        if live:
            self._auto_show()
            self._follow(item)

    def tool_result(self, result: str, live: bool = True):
        item, self.pending = self.pending, None
        if item is None or item not in self.entries:
            return
        e = self.entries[item]
        e["running"] = False
        if str(result or "").startswith(("Fehler", "Vom Nutzer abgelehnt")):
            e["error"] = result
        elif e["kind"] == "web":
            e["results"] = parse_web_search(result)
        elif e["kind"] == "page":
            page = parse_page(result)
            if page:
                e.update(url=page["url"], title=page["title"] or e.get("title", ""), total=page["total"])
                e["chunks"].append(page)
                self.read_urls.update({e["args"].get("url", ""), page["url"]})
            else:
                e["error"] = result
        elif e["kind"] == "docs":
            e["hits"] = parse_doc_hits(result)
            e["terms"] = term_pattern(e["args"].get("suchbegriffe", ""))
            self.last_terms = e["terms"] or self.last_terms
            e["note"] = result if not e["hits"] else ""
        elif e["kind"] == "doc":
            e["doc"] = parse_doc_pages(result)
            e["terms"] = self.last_terms
            if not e["doc"]:
                e["error"] = result
        self._set_label(item)
        if live and (self._shown == item or self._following()):
            self._follow(item)

    def load_history(self, history: list):
        """Gespeicherter Chat: Fragen und Werkzeugaufrufe aus dem Verlauf (ohne aufzuklappen oder mitzuspringen)."""
        self.clear()
        results = {m.get("tool_call_id"): m.get("content") or "" for m in history if m.get("role") == "tool"}
        asked = ""
        for m in history:
            if m.get("role") == "user":
                self.group = None
                asked = m.get("_text", m.get("content"))
                asked = asked if isinstance(asked, str) else ""  # Bilder: Liste von Teilen
            if m.get("role") != "assistant":
                continue
            for c in m.get("tool_calls") or []:
                fn = c.get("function", {})
                if fn.get("name") in TOOLS:
                    if self.group is None:
                        self.question(asked)
                    self.tool_call(fn.get("name"), fn.get("arguments", ""), live=False)
                    self.tool_result(results.get(c.get("id"), ""), live=False)
        self.group = None  # die nächste Frage legt ihre eigene Gruppe an
        last = self.tree.get_children()
        if last:
            self.tree.item(last[-1], open=True)
        self._render_empty()

    def documents(self) -> list[str]:
        """Dokumente, die in diesem Chat gesucht oder gelesen wurden – für klickbare Quellenangaben."""
        files = []
        for e in self.entries.values():
            names = [h["file"] for h in e.get("hits") or []] + ([e["doc"]["file"]] if e.get("doc") else [])
            files += [f for f in names if f not in files]
        return files

    def open_doc(self, rel: str, page: int | None = None):
        """Quellenangabe angeklickt: Seite aus der Auswertung zeigen (eigener Eintrag „geöffnet“)."""
        library = self.app.expert_library()
        if library is None:
            return
        page = max(1, int(page or 1))
        try:
            result = library.read(rel, page, page)
        except (LookupError, OSError, ValueError) as e:
            result = f"Fehler: {e}"
        if self.group is None:
            self.question(tr('Geöffnete Quellen'))
        a = {"datei": rel, "von": page, "bis": page}
        item = self.tree.insert(self.group, "end", text="")
        self.entries[item] = {"kind": "doc", "args": a, "running": False, "error": None, "opened": True,
                              "doc": parse_doc_pages(result), "terms": self.last_terms}
        if not self.entries[item]["doc"]:
            self.entries[item]["error"] = result
        self._set_label(item)
        self.app.cfg["quellen_auto"] = True
        self.show()
        self._select(item)

    # ------------------------------------------------------------ Liste

    def _set_label(self, item: str, running: bool = False):
        e = self.entries[item]
        a = e["args"]
        if e["kind"] == "web":
            text, icon = tr('Websuche: {0}', a.get("query", "")), "globe"
        elif e["kind"] == "page":
            title = e.get("title") or re.sub(r"^https?://(www\.)?", "", e.get("url") or a.get("url", ""))
            text, icon = tr('Liest: {0}', title), "page"
        elif e["kind"] == "docs":
            text, icon = tr('Dokumente durchsucht: {0}', a.get("suchbegriffe", "")), "search"
        else:
            doc = e.get("doc")
            nrs = [nr for _, nr, _ in doc["pages"]] if doc else [a.get("von") or 1]
            span = f"{nrs[0]}–{nrs[-1]}" if len(nrs) > 1 else f"{nrs[0]}"
            art = doc["pages"][0][0] if doc else "Seite"
            text = f"{Path(str(a.get('datei', ''))).name} · {art_label(art)} {span}" + (
                tr('  (geöffnet)') if e.get("opened") else "")
            icon = "page"
        if running:
            text += " …"
        elif e.get("error"):
            text += tr('  (Fehler)')
        self.tree.item(item, text=" " + text, image=icons.image(icon, "muted" if running else "fg") or "")

    def _following(self) -> bool:
        return time.monotonic() - self._picked > FOLLOW_PAUSE

    def _follow(self, item: str):
        """Live mitgehen – außer der Nutzer hat gerade selbst einen Eintrag gewählt."""
        if self.visible and self._following():
            self._select(item)

    def _select(self, item: str):
        self._selecting = True
        try:
            self.tree.selection_set(item)
            self.tree.see(item)
        finally:
            self._selecting = False
        self._render(item)

    def _on_select(self, _e=None):
        sel = self.tree.selection()
        if self._selecting or not sel:
            return
        if sel[0] in self.entries:
            self._picked = time.monotonic()
            self._render(sel[0])

    # ------------------------------------------------------------ Inhalt anzeigen

    def _refresh_colors(self):
        col = self.app.theme_chat()
        # Farbe als #rrggbb – „Windows-Standard“ setzt Systemfarben wie „SystemWindow“ (mix_hex kennt nur Hexwerte)
        r, g, b = (v // 257 for v in self.text.winfo_rgb(self.text.cget("background")))
        bg = f"#{r:02x}{g:02x}{b:02x}"
        t = self.text
        t.tag_configure("h", font=(FAMILY, 11, "bold"), spacing1=2, spacing3=4)
        t.tag_configure("sub", font=(FAMILY, 9, "bold"), foreground=col["muted"], spacing1=10, spacing3=2)
        t.tag_configure("muted", foreground=col["muted"], font=(FAMILY, 9))
        t.tag_configure("link", foreground=col["link"], underline=True)
        t.tag_configure("hit", background=mix_hex(bg, col["accent"], 0.38))
        t.tag_configure("read", foreground=col.get("ok", col["muted"]), font=(FAMILY, 9, "bold"))
        t.tag_configure("error", foreground=col.get("error", "#d33"))
        t.tag_configure("body", spacing1=1, spacing3=1)
        t.tag_raise("link")
        t.tag_raise("hit")

    def refresh_theme(self):
        self._refresh_colors()
        for item, e in self.entries.items():
            self._set_label(item, running=e.get("running", False))
        if self._shown in self.entries:
            self._render(self._shown, keep_scroll=True)

    def _clear_text(self):
        self.text.delete("1.0", tk.END)
        for tag in [t for t in self.text.tag_names() if t.startswith("l:")]:
            self.text.tag_delete(tag)
        self._links.clear()
        for w in self.buttons.winfo_children():
            w.destroy()
        self._image = None

    def _render_empty(self):
        if self._shown is None:
            self._clear_text()
            self.text.insert(tk.END, tr('Noch keine Quellen in diesem Chat.') + "\n\n", "h")
            self.text.insert(tk.END, tr(
                'Sucht oder liest die KI im Internet oder in den Dokumenten des Experten-Modus, erscheint hier live, '
                'was sie liest – genau der Text, den das Modell bekommt. Quellenangaben in Antworten („Datei, Seite“) '
                'öffnen die Seite hier.'), "muted")

    def _add(self, text: str, *tags):
        self.text.insert(tk.END, text, tags)

    def _add_link(self, text: str, action, *tags):
        n = f"l:{len(self._links)}"
        self._links[n] = action
        self.text.insert(tk.END, text, ("link", n, *tags))

    def _on_link(self, _e=None):
        for tag in self.text.tag_names("current"):
            if tag in self._links:
                self._links[tag]()
                return "break"

    def _add_marked(self, text: str, pattern: re.Pattern | None, *tags):
        """Text mit markierten Suchwörtern (Vergleich ohne Groß-/Kleinschreibung und Umlautpunkte)."""
        if not pattern:
            self._add(text, *tags)
            return
        pos = 0
        for m in pattern.finditer(fold(text)):
            self._add(text[pos:m.start()], *tags)
            self._add(text[m.start():m.end()], "hit", *tags)
            pos = m.end()
        self._add(text[pos:], *tags)

    def _add_snippet(self, snippet: str):
        """Treffer-Ausschnitt der Dokumentsuche: »…« markiert."""
        for i, part in enumerate(re.split(r"[»«]", snippet)):
            self._add(part, *(("hit",) if i % 2 else ()))

    def _button(self, text: str, command, icon: str | None = None):
        ttk.Button(self.buttons, text=text, command=command, **(icons.opts(icon) if icon else {})).pack(
            side=tk.LEFT, padx=(0, 6))

    def _render(self, item: str, keep_scroll: bool = False):
        e = self.entries.get(item)
        if e is None:
            return
        top = self.text.yview()[0] if keep_scroll and self._shown == item else None
        self._shown = item
        self._clear_text()
        a = e["args"]
        jump = None
        if e["kind"] == "web":
            self._add(tr('Websuche') + "\n", "sub")
            self._add(a.get("query", "") + "\n", "h")
            for i, r in enumerate(e.get("results") or [], 1):
                self._add(f"\n{i}. ")
                self._add_link(r["title"] or r["url"], lambda u=r["url"]: webbrowser.open(u))
                if r["url"] in self.read_urls:
                    self._add("  " + tr('✓ gelesen'), "read")
                self._add("\n" + re.sub(r"^https?://(www\.)?", "", r["url"]).split("/")[0] + "\n", "muted")
                if r["snippet"]:
                    self._add(r["snippet"] + "\n", "body")
        elif e["kind"] == "page":
            url = e.get("url") or a.get("url", "")
            self._add(tr('Seite, die die KI liest') + "\n", "sub")
            self._add((e.get("title") or url) + "\n", "h")
            self._add_link(url, lambda u=url: webbrowser.open(u), "muted")
            self._add("\n")
            for chunk in e["chunks"]:
                if chunk["total"]:
                    jump = self.text.index("end-1c")
                    self._add(tr('Zeichen {0}–{1} von {2}', chunk["start"], chunk["end"], chunk["total"]) + "\n",
                              "sub")
                self._add(chunk["text"].strip() + "\n", "body")
            if url:
                self._button(tr('Im Browser öffnen'), lambda u=url: webbrowser.open(u), "globe")
        elif e["kind"] == "docs":
            self._add(tr('Suche in den Dokumenten') + "\n", "sub")
            self._add(a.get("suchbegriffe", "") + ("  ·  " + str(a["datei"]) if a.get("datei") else "") + "\n", "h")
            for h in e.get("hits") or []:
                self._add("\n")
                self._add_link(f"{h['file']} · {art_label(h['art'])} {h['nr']}",
                               lambda f=h["file"], n=h["nr"]: self.open_doc(f, n))
                self._add("\n")
                self._add_snippet(h["snippet"] + "\n")
            if e.get("note"):
                self._add("\n" + e["note"] + "\n", "muted")
        else:
            doc = e.get("doc")
            rel = doc["file"] if doc else str(a.get("datei", ""))
            self._add(tr('Dokument') + "\n", "sub")
            self._add(rel + "\n", "h")
            for art, nr, body in doc["pages"] if doc else []:
                self._add(f"{art_label(art)} {nr}\n", "sub")
                self._add_marked(body + "\n", e.get("terms"), "body")
            self._doc_buttons(rel, doc["pages"][0] if doc else None)
        if e.get("running"):
            self._add("\n" + tr('… läuft') + "\n", "muted")
        if e.get("error"):
            self._add("\n" + e["error"] + "\n", "error")
        if top is not None:
            self.text.yview_moveto(top)
        elif jump and len(e.get("chunks", [])) > 1:  # Weiterlesen: dorthin, wo die KI gerade liest
            self.text.see(jump)
            self.text.yview(jump)
        else:
            self.text.yview_moveto(0)

    def _doc_buttons(self, rel: str, first):
        library = self.app.expert_library()
        if library is None or not rel:
            return
        path = library.source / rel
        if first and first[0] == "Seite" and path.suffix.lower() == ".pdf":
            self._button(tr('Seitenbild'), lambda: self._page_image(path, first[1]), "photo")
        self._button(tr('Öffnen'), lambda: self._open(path), "page")
        self._button(tr('Ordner'), lambda: self._open(path, folder=True), "folder")

    def _open(self, path: Path, folder: bool = False):
        try:
            (plattform.show_in_folder if folder else plattform.open_path)(path)
        except OSError as e:
            self.text.insert("1.0", tr('Konnte nicht geöffnet werden: {0}', e) + "\n", "error")

    def _page_image(self, pdf: Path, page: int):
        """Seite als Bild oben in den Inhalt (rendern im Hintergrund – unter Windows dauert das 1–3 s)."""
        item = self._shown
        width = max(200, self.text.winfo_width() - 40)
        self.text.insert("1.0", tr('Seitenbild wird erstellt …') + "\n", ("muted", "img_note"))

        def work():
            out = Path(tempfile.mkdtemp(prefix="monhip-seite-"))
            try:
                pngs, _total = experte.render_pdf(pdf, out, page, 1, width=width)
                data = pngs[0][1].read_bytes() if pngs else None
                error = None if pngs else tr('Seite nicht gefunden.')
            except Exception as e:  # kein pdftoppm, beschädigtes PDF …
                data, error = None, str(e)
            finally:
                shutil.rmtree(out, ignore_errors=True)
            self.text.after(0, lambda: self._show_image(item, data, error))

        threading.Thread(target=work, daemon=True).start()

    def _show_image(self, item, data: bytes | None, error: str | None):
        if self._shown != item:
            return
        ranges = self.text.tag_ranges("img_note")
        if ranges:
            self.text.delete(ranges[0], ranges[1])
        if error or not data:
            self.text.insert("1.0", tr('Kein Seitenbild: {0}', error or "") + "\n", "error")
            return
        self._image = tk.PhotoImage(master=self.text, data=base64.b64encode(data).decode("ascii"), format="png")
        self.text.image_create("1.0", image=self._image, pady=4)
        self.text.insert("1.1", "\n")
        self.text.yview_moveto(0)
