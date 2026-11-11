"""Bereich „Bilder“ – der dritte Modus neben Chat und Teamwork, mit drei Unterbereichen in der Seitenleiste:
„Bild erstellen“ (aus einer Beschreibung), „Bild bearbeiten“ (ein eigenes Bild auswählen, hineinziehen oder mit
Strg+V einfügen und beschreiben, was sich daran ändern soll) und „3D-Modell“ (aus einem Bild ein 3D-Modell mit Farben,
trellis.py; ansehen im Browser und als STL für den 3D-Druck, modell3d.py). Darunter die Galerie der bisherigen Bilder
und 3D-Modelle (galerie.py).

Oben rechts wie im Chat: Bildmodell wählen (sdcpp.MODELS), „Modell laden“ und Entladen. Ein Bildmodell besteht aus
mehreren Dateien (Bildmodell, Textverständnis, VAE …); fehlen welche oder die Bild-Engine, fragt Monhip und lädt sie
vor dem Laden herunter – Fortschritt unten auf der Seite.

Mitte: große Vorschau – während des Erzeugens mit Fortschritt und Zwischenbild –, darunter Speichern, Kopieren,
Im Ordner zeigen, Bearbeiten, Beschreibung übernehmen. Unten die Beschreibung mit Format (nur beim Erstellen; beim
Bearbeiten richtet sich das Ergebnis nach der Vorlage), Anzahl, „Beschreibung verbessern“ (über das geladene
Sprachmodell) und „Generieren“.

Grafikspeicher: Sprach- und Bildmodell passen auf vielen Karten nicht gleichzeitig hinein. Ist beim Laden ein
Sprachmodell geladen und zu wenig frei, fragt Monhip und entlädt es (auf Wunsch künftig ohne Rückfrage). Umgekehrt gibt
das Laden eines Sprachmodells den Speicher des Bildmodells frei (release).
"""

from i18n import error_text, tr

import base64
import itertools
import json
import os
import random
import re
import tempfile
import threading
import time
import tkinter as tk
import urllib.request
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk

import backend
import dialogs
import filedrop
import galerie
import icons
import images
import modell3d
import plattform
import sdcpp
import trellis
from backend import model_name
from themes import FAMILY
from widgets import Glide, PopupMenu

THUMB = 56                      # Vorschaubilder der Galerie (Pixel bei 100 %)
SOURCE_THUMB = 44               # Vorlage beim Bearbeiten (Höhe in Pixeln bei 100 %)
SOURCE_MAX = 2048               # Vorlage wird höchstens so groß (längere Seite) ans Bildmodell geschickt
FORMATS = {"square": (1024, 1024), "portrait": (832, 1216), "landscape": (1216, 832)}
COUNTS = ("1", "2", "3", "4")
PHOTO_CACHE = 4                 # so viele zuletzt gezeigte Bilder bleiben dekodiert (samt sauberer Fassung)
HQ_DELAY_MS = 180               # so lange nach einer Größenänderung, bis die Vorschau sauber neu verkleinert wird

# Für das Sprachmodell („Beschreibung verbessern“) – bleibt deutsch wie alle Texte für Modelle
IMPROVE_PROMPT = (
    "Du verbesserst Bildbeschreibungen für ein Bildmodell. Mache aus der Beschreibung des Nutzers eine "
    "anschauliche, genaue Bildbeschreibung auf Englisch (die versteht das Bildmodell am besten): Motiv, Umgebung, "
    "Licht, Farben, Perspektive und Stil in zwei bis vier Sätzen, als Fließtext. Behalte alles bei, was der Nutzer "
    "ausdrücklich wünscht – auch Texte, die im Bild stehen sollen, wörtlich –, und erfinde nichts, was dem "
    "widerspricht. Antworte nur mit der Beschreibung, ohne Einleitung, ohne Überschrift und ohne Anführungszeichen.")
IMPROVE_EDIT_PROMPT = (
    "Du verbesserst Anweisungen zum Bearbeiten eines vorhandenen Bildes für ein Bildmodell. Mache aus der Anweisung "
    "des Nutzers eine klare, genaue Anweisung auf Englisch (die versteht das Bildmodell am besten): was sich ändern "
    "soll – Gegenstand, Ort im Bild, Farbe, Stil –, und dass alles Übrige unverändert bleibt. Ein bis drei Sätze, "
    "als Fließtext. Behalte alles bei, was der Nutzer ausdrücklich wünscht – auch Texte, die im Bild stehen sollen, "
    "wörtlich –, und erfinde keine weiteren Änderungen. Antworte nur mit der Anweisung, ohne Einleitung, ohne "
    "Überschrift und ohne Anführungszeichen.")

IMPROVE_3D_PROMPT = (
    "Du verbesserst Beschreibungen für ein Bild, aus dem danach ein 3D-Modell entsteht. Mache aus der Beschreibung "
    "des Nutzers eine genaue Bildbeschreibung auf Englisch (die versteht das Bildmodell am besten): genau ein "
    "Gegenstand bzw. eine Figur, vollständig zu sehen – Form, Material, Farben und Details in zwei bis drei Sätzen, als "
    "Fließtext. Keine Umgebung, keine Szene, kein Text im Bild. Behalte alles bei, was der Nutzer ausdrücklich wünscht, "
    "und erfinde nichts, was dem widerspricht. Antworte nur mit der Beschreibung, ohne Einleitung, ohne Überschrift "
    "und ohne Anführungszeichen.")
# Hängt Monhip beim 3D-Modell aus einer Beschreibung ans Bild an: so wird das Bild eine gute Vorlage für TRELLIS.2
OBJECT_HINT = (". A single complete object, centered and fully in frame, isolated on a plain white background, "
               "three-quarter view from slightly above, soft even studio lighting, no shadow on the ground, no text, "
               "no other objects.")


def format_labels() -> dict[str, str]:
    return {"square": tr('Quadrat (1024 × 1024)'), "portrait": tr('Hochformat (832 × 1216)'),
            "landscape": tr('Querformat (1216 × 832)')}


def improve_prompt(base_url: str, text: str, timeout: float = 180, system: str = IMPROVE_PROMPT) -> str:
    """Bildbeschreibung bzw. Bearbeitungsanweisung über das geladene Sprachmodell ausbauen (eine kurze Anfrage ohne
    Denkprozess)."""
    payload = {"messages": [{"role": "system", "content": system},
                            {"role": "user", "content": text.strip()}],
               "stream": False, "max_tokens": 400, "temperature": 0.7,
               "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(base_url + "/v1/chat/completions", data=json.dumps(payload).encode("utf-8"),
                                 headers=backend._auth({"Content-Type": "application/json"}))
    with backend._local.open(req, timeout=timeout) as r:  # mit Schlüssel, nie über einen Proxy (wie backend)
        msg = json.loads(r.read())["choices"][0]["message"]
    out = re.sub(r"(?s)<think>.*?(</think>|$)", "", msg.get("content") or "").strip()
    return out.strip(" \"'„“”«»").strip()


def fit_photo(src: tk.PhotoImage, box_w: int, box_h: int, master) -> tk.PhotoImage:
    """src so groß wie möglich in box_w × box_h – als Bruch zoom/subsample, den Tk in einem Durchgang rechnet (~1 ms
    für 1024 × 1024). Mit nur ganzen Faktoren sprang das Bild sichtbar: Zwischenbild 128 px × 5 = 640, dann das
    fertige grob 1024 / 2 = 512 und kurz darauf sauber 700 px. Jetzt liegen alle drei nur wenige Pixel auseinander."""
    sw, sh = max(1, src.width()), max(1, src.height())
    best, size = None, 0
    for d in range(1, 9):
        cw, ch = -(-sw // d), -(-sh // d)  # so rechnet Tk: erst jedes d-te Pixel, dann z-fach
        z = min(box_w // cw, box_h // ch)
        if z >= 1 and cw * z > size:
            best, size = (z, d), cw * z
    if best is None:  # selbst 1/8 ist zu groß: ganzzahlig wie früher
        return src.subsample(max(-(-sw // max(1, box_w)), -(-sh // max(1, box_h))))
    z, d = best
    if (z, d) == (1, 1):
        return src
    out = tk.PhotoImage(master=master)
    out.tk.call(out, "copy", src, "-zoom", z, z, "-subsample", d, d)
    return out


def short(text: str, font, width: int) -> str:
    """Erste Zeile von text, gekürzt mit „…“, damit sie in width Pixel passt. Die passende Länge wird halbierend
    gesucht: Zeichen für Zeichen kürzen hieß bei einer ausgebauten Beschreibung (gut 1000 Zeichen) über tausend
    Messungen in Tk je Eintrag – bei 200 Bildern stand die Oberfläche nach jedem neuen Bild über eine Minute."""
    line = " ".join((text or "").split())
    # jedes Zeichen ist mindestens ein Pixel breit: mehr Zeichen als Pixel passen nie (spart das Messen langer Texte)
    if len(line) <= width and font.measure(line) <= width:
        return line
    lo, hi = 0, min(len(line), width)  # längster Anfang, der mit „…“ noch passt
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if font.measure(line[:mid] + "…") <= width:
            lo = mid
        else:
            hi = mid - 1
    return line[:lo].rstrip() + "…"


def resolution_labels() -> dict[int, str]:
    """Feinheit der Form beim 3D-Modell (trellis.RESOLUTIONS)."""
    return {1024: tr('Fein (1024)'), 512: tr('Schnell (512)')}  # 1024 braucht etwa 16 GB Grafikspeicher


def compatibility_labels() -> dict[str, str]:
    return {"auto": tr('Automatisch'), "normal": tr('Normal'), "compatible": tr('Kompatibel (langsamer)')}


def clock(secs: float) -> str:
    """„45 s“ bzw. „3:07 min“."""
    secs = int(secs)
    return tr('{0} s', secs) if secs < 60 else tr('{0}:{1:02d} min', secs // 60, secs % 60)


def first_image(paths) -> Path | None:
    """Erstes Bild unter abgelegten bzw. eingefügten Dateien."""
    return next((Path(p) for p in paths if images.is_image(p) and Path(p).is_file()), None)


class ImageMode:
    """Seitenleiste (side_parent) und Hauptbereich (eine Seite, die im Bilder-Modus über main_parent liegt)."""

    _counter = itertools.count(1)

    def __init__(self, app, side_parent: ttk.Frame, main_parent: tk.Frame):
        self.app = app
        self.s = app.ui_scale
        self.gallery = galerie.Gallery()
        self.server = sdcpp.ImageServer(lambda t: app.events.put(("log", t)),
                                        lambda: app.cfg.get("image_qwen_compatibility", "auto"))
        self.busy = False
        self.stop_event = threading.Event()
        self.mode = "create"                       # Unterbereich: "create" (Bild erstellen), "edit" (bearbeiten), "3d"
        self._drafts = {"create": "", "edit": "", "3d": ""}  # Beschreibung je Unterbereich (beim Wechsel aufgehoben)
        self.source: dict | None = None            # Vorlage (Bearbeiten, 3D-Modell): path, png, thumb, w, h, name
        self._source_img: tk.PhotoImage | None = None
        self.shown: dict | None = None             # Bild in der großen Vorschau (Galerie-Eintrag)
        self._full: tk.PhotoImage | None = None    # … in voller Größe (Galerie-Bild oder Vorlage)
        self._full_path: Path | None = None        # … und seine Datei
        self._display: tk.PhotoImage | None = None # … so groß, wie es gerade zu sehen ist
        self._hq: tuple | None = None              # (Datei, Breite, Höhe) der sauber verkleinerten Fassung
        self._hq_after = None
        self._live: tk.PhotoImage | None = None    # Zwischenbild während des Erzeugens
        self._live_src: tk.PhotoImage | None = None
        self._thumbs: dict[str, tk.PhotoImage] = {}
        self._labels: dict[tuple[str, int], str] = {}  # gekürzte Beschriftungen der Galerie (_short)
        # zuletzt gezeigte Bilder: Datei → {"stamp", "full", "hq": (Breite, Höhe, PhotoImage)} – Hin- und Herblättern
        # ohne neu zu dekodieren (~30 ms) und ohne neu sauber zu verkleinern (unter Windows ein PowerShell-Aufruf)
        self._photos: dict[str, dict] = {}
        self._listed = False                       # Galerie erst beim ersten Zeigen füllen (schneller Start)
        self._ctx_item: dict | None = None
        self._t0 = 0.0
        self._phase = ""                           # "download", "load" (Bildmodell laden), "run" bzw. "run3d" (rechnen)
        self._stage: dict = {}                     # Stand beim 3D-Modell (trellis.parse_progress)
        self._chain = False                        # 3D-Modell aus einer Beschreibung: erst Bild, dann 3D
        self._prefix = ""                          # … davor in der Statuszeile: „Teil 1 von 2 (Bild)“ usw.
        self._dl_kind = "image"                    # was gerade heruntergeladen wird: "image" bzw. "3d"
        self._steps = (0, 1, 1)                    # (erledigte Schritte, alle Schritte, Anzahl Bilder)
        self._tick_after = None
        self._checking = False                     # sucht gerade, was fürs Bildmodell fehlt
        self._font = None
        self.bg, self.muted = "#ffffff", "#777777"
        self._build_side(side_parent)
        self._build_page(main_parent)
        self._apply_mode()

    # ================================================================ Aufbau

    def _build_side(self, parent):
        top = ttk.Frame(parent, style="Sidebar.TFrame", padding=(8, 6, 8, 6))
        top.pack(side=tk.TOP, fill=tk.X)
        # Unterbereiche – wie die Einträge von Teamwork; der gewählte ist markiert
        self.create_btn = ttk.Button(top, text=tr('Bild erstellen'), style="Sidebar.TButton",
                                     command=lambda: self.set_mode("create", fresh=True),
                                     **icons.opts("add", lower=1))
        self.create_btn.pack(fill=tk.X)
        self.edit_btn = ttk.Button(top, text=tr('Bild bearbeiten'), style="Sidebar.TButton",
                                   command=lambda: self.set_mode("edit"), **icons.opts("edit", lower=1))
        self.edit_btn.pack(fill=tk.X)
        self.model3d_btn = ttk.Button(top, text=tr('3D-Modell'), style="Sidebar.TButton",
                                      command=lambda: self.set_mode("3d"), **icons.opts("refresh", lower=1))
        self.model3d_btn.pack(fill=tk.X)
        head = ttk.Frame(parent, style="Sidebar.TFrame", padding=(14, 10, 12, 4))
        head.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(head, text=tr('Galerie'), style="Sidebar.TLabel").pack(side=tk.LEFT)
        self.count_var = tk.StringVar()
        ttk.Label(head, textvariable=self.count_var, style="SidebarMuted.TLabel").pack(side=tk.RIGHT)
        lf = ttk.Frame(parent, style="Sidebar.TFrame", padding=(8, 0, 2, 0))
        lf.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(lf, show="tree", selectmode="browse", style="Gallery.Sidebar.Treeview")
        tree.column("#0", width=160, stretch=True)
        sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=tree.yview, style="Sidebar.Vertical.TScrollbar")
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree.bind("<<TreeviewSelect>>", self._on_select)
        tree.bind("<Double-Button-1>", lambda e: self.open_file(self._item_at(e.y)))
        tree.bind("<Button-3>", self._on_menu)
        tree.bind("<Delete>", lambda e: self.delete(self._selected()))
        self.tree = tree

        menu = PopupMenu(self.app.root, self.s)
        for label, cmd in ((tr('Öffnen'), self.open_file), (tr('Bearbeiten'), self.edit_item),
                           (tr('In 3D umwandeln'), self.to_3d),
                           (tr('Im Ordner zeigen'), self.show_in_folder), (tr('Kopieren'), self.copy),
                           (tr('Speichern unter…'), self.save_as), (tr('Beschreibung übernehmen'), self.reuse_prompt),
                           (tr('Löschen'), self.delete)):
            menu.add_command(label=label, command=lambda c=cmd: c(self._ctx_item))
        self.app.theme.register_menu(menu)
        self.menu = menu
        menu3d = PopupMenu(self.app.root, self.s)  # für 3D-Modelle in der Galerie
        for label, cmd in ((tr('Ansehen'), self.view_3d), (tr('Als STL speichern…'), self.save_stl),
                           (tr('GLB speichern unter…'), self.save_glb), (tr('Im Ordner zeigen'), self.show_in_folder),
                           (tr('Löschen'), self.delete)):
            menu3d.add_command(label=label, command=lambda c=cmd: c(self._ctx_item))
        self.app.theme.register_menu(menu3d)
        self.menu3d = menu3d

    def _build_page(self, parent):
        theme = self.app.theme
        # liegt im Bilder-Modus über dem ganzen Chatbereich (place), sonst unsichtbar
        page = theme.register_frame(tk.Frame(parent, borderwidth=0, highlightthickness=0))
        self.page = page

        # ---- Kopfzeile wie im Chat: Titel links, Bildmodell rechts (wählen, laden, entladen), darunter der Stand
        top = ttk.Frame(page, style="Top.TFrame", padding=(18, 10, 14, 8))
        top.pack(side=tk.TOP, fill=tk.X)
        self.title_var = tk.StringVar()
        ttk.Label(top, textvariable=self.title_var, style="Title.TLabel", width=1).grid(
            row=0, column=0, rowspan=2, sticky="ew", padx=(0, 12))
        self.pick_var = tk.StringVar(value=sdcpp.MODELS[self.model_key()]["name"])
        self.pick = ttk.Combobox(top, textvariable=self.pick_var, state="readonly", width=28,
                                 values=[m["name"] for m in sdcpp.MODELS.values()])
        self.pick.grid(row=0, column=2, sticky="e")
        self.pick.bind("<<ComboboxSelected>>", self._on_pick)
        theme.register_combo(self.pick)
        self.load_btn = ttk.Button(top, text=tr('Modell laden'), style="Accent.TButton", command=self.load,
                                   **icons.opts("play", "accent_fg"))
        self.load_btn.grid(row=0, column=3, padx=(6, 0))
        self.unload_btn = ttk.Button(top, width=3, command=self.unload, **icons.only("stop"))
        self.unload_btn.grid(row=0, column=4, padx=(4, 0))
        ttk.Button(top, text=tr('Einrichten'), command=lambda: self.app.open_settings("images"),
                   **icons.opts("settings")).grid(row=0, column=5, padx=(10, 0))
        self.engine_var = tk.StringVar()
        ttk.Label(top, textvariable=self.engine_var, style="Muted.TLabel").grid(
            row=1, column=2, columnspan=4, sticky="e", pady=(3, 0))
        top.columnconfigure(0, weight=1)
        ttk.Separator(page).pack(side=tk.TOP, fill=tk.X)

        # ---- unten: Beschreibung und Knöpfe (zuerst packen, damit sie beim Verkleinern sichtbar bleiben)
        opts = ttk.Frame(page, padding=(18, 2, 18, 12))
        opts.pack(side=tk.BOTTOM, fill=tk.X)
        self._opts = opts
        cfg = self.app.cfg
        self.format_var = tk.StringVar(value=format_labels().get(cfg.get("image_format"), format_labels()["square"]))
        self.count_choice = tk.StringVar(value=str(cfg.get("image_count", 1)) if str(cfg.get("image_count", 1))
                                         in COUNTS else "1")
        self.format_label = ttk.Label(opts, text=tr('Format'))
        self.format_label.pack(side=tk.LEFT)
        self.format_combo = ttk.Combobox(opts, textvariable=self.format_var, values=list(format_labels().values()),
                                         state="readonly", width=24)
        self.format_combo.pack(side=tk.LEFT, padx=(6, 14))
        theme.register_combo(self.format_combo)
        self.count_label = ttk.Label(opts, text=tr('Anzahl'))
        self.count_label.pack(side=tk.LEFT)
        cnt = ttk.Combobox(opts, textvariable=self.count_choice, values=COUNTS, state="readonly", width=3)
        cnt.pack(side=tk.LEFT, padx=(6, 14))
        theme.register_combo(cnt)
        self.count_combo = cnt
        res = cfg.get("model3d_res") if cfg.get("model3d_res") in trellis.RESOLUTIONS else trellis.RESOLUTIONS[0]
        self.res_var = tk.StringVar(value=resolution_labels()[res])
        self.from_var = tk.StringVar(value="text" if cfg.get("model3d_from") == "text" else "image")
        self.from_frame = ttk.Frame(opts)
        for value, label in (("image", tr('Aus einem Bild')), ("text", tr('Aus einer Beschreibung'))):
            ttk.Radiobutton(self.from_frame, text=label, value=value, variable=self.from_var,
                            command=self._on_from).pack(side=tk.LEFT, padx=(0, 12))
        self.res_label = ttk.Label(opts, text=tr('Feinheit'))
        self.res_combo = ttk.Combobox(opts, textvariable=self.res_var, values=list(resolution_labels().values()),
                                      state="readonly", width=14)
        theme.register_combo(self.res_combo)
        self.gen_btn = ttk.Button(opts, text=tr('Generieren'), style="Accent.TButton", command=self.generate,
                                  **icons.opts("play", "accent_fg"))
        self.gen_btn.pack(side=tk.RIGHT)
        self.improve_btn = ttk.Button(opts, text=tr('Beschreibung verbessern'), command=self.improve,
                                      **icons.opts("edit"))
        self.improve_btn.pack(side=tk.RIGHT, padx=(0, 8))

        inp = ttk.Frame(page, padding=(18, 6, 18, 8))
        inp.pack(side=tk.BOTTOM, fill=tk.X)
        self._inp = inp
        field = ttk.Frame(inp, style="Input.TFrame")
        field.pack(fill=tk.BOTH, expand=True)
        # so hoch wie das Eingabefeld im Chat
        self.prompt = tk.Text(field, height=2, width=1, wrap=tk.WORD, font=(FAMILY, 11), padx=8, pady=4, undo=True)
        self.prompt.pack(fill=tk.BOTH, expand=True)
        self.prompt.bind("<Return>", self._on_enter)
        self.prompt.bind("<<Paste>>", self._on_paste)
        theme.register_field(field, self.prompt)

        # Vorlage beim Bearbeiten (nur im Unterbereich „Bild bearbeiten“, über der Beschreibung)
        row = ttk.Frame(page, padding=(18, 8, 18, 0))
        self.source_row = row
        self.source_label = ttk.Label(row, cursor="hand2")
        self.source_label.pack(side=tk.LEFT)
        self.source_label.bind("<Button-1>", lambda e: self.show_source())
        self.source_var = tk.StringVar()
        ttk.Label(row, textvariable=self.source_var, style="Muted.TLabel").pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(row, text=tr('Bild auswählen…'), command=self.choose_source, **icons.opts("upload")).pack(
            side=tk.RIGHT)
        self.source_clear = ttk.Button(row, width=3, command=self.clear_source, **icons.only("close"))

        # Fortschritt (nur während Download, Laden und Erzeugen) und Statuszeile
        self.progress_row = ttk.Frame(page, padding=(18, 4, 18, 0))
        self.progress = ttk.Progressbar(self.progress_row, mode="determinate", maximum=100)
        self.progress.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.glide = Glide(self.progress)  # Fortschritt gleitet statt in ganzen Rechenschritten zu springen
        self.status_var = tk.StringVar()
        self.status = ttk.Label(page, textvariable=self.status_var, style="Muted.TLabel", padding=(18, 4, 18, 0))
        self.status.pack(side=tk.BOTTOM, fill=tk.X)
        self.progress_row.pack(side=tk.BOTTOM, fill=tk.X)
        self.progress_row.pack_forget()

        # ---- Mitte: große Vorschau, darunter die Aktionen zum gezeigten Bild
        self.actions = ttk.Frame(page, padding=(18, 4, 18, 0))
        for label, icon, cmd in ((tr('Speichern unter…'), "download", self.save_as),
                                 (tr('Kopieren'), "copy", self.copy),
                                 (tr('Im Ordner zeigen'), "folder", self.show_in_folder),
                                 (tr('Bearbeiten'), "edit", self.edit_item),
                                 (tr('In 3D'), "refresh", self.to_3d),
                                 (tr('Beschreibung übernehmen'), "reply", self.reuse_prompt)):
            ttk.Button(self.actions, text=label, command=lambda c=cmd: c(self.shown), **icons.opts(icon)).pack(
                side=tk.LEFT, padx=(0, 6))
        self.info_var = tk.StringVar()
        ttk.Label(self.actions, textvariable=self.info_var, style="Muted.TLabel").pack(side=tk.RIGHT)
        self.actions.pack(side=tk.BOTTOM, fill=tk.X)
        # … bzw. zum gezeigten 3D-Modell (statt der Bild-Aktionen)
        self.actions3d = ttk.Frame(page, padding=(18, 4, 18, 0))
        ttk.Button(self.actions3d, text=tr('Ansehen'), style="Accent.TButton", command=lambda: self.view_3d(self.shown),
                   **icons.opts("play", "accent_fg")).pack(side=tk.LEFT, padx=(0, 6))
        for label, icon, cmd in ((tr('Als STL speichern…'), "download", self.save_stl),
                                 (tr('GLB speichern unter…'), "download", self.save_glb),
                                 (tr('Im Ordner zeigen'), "folder", self.show_in_folder)):
            ttk.Button(self.actions3d, text=label, command=lambda c=cmd: c(self.shown), **icons.opts(icon)).pack(
                side=tk.LEFT, padx=(0, 6))
        ttk.Label(self.actions3d, textvariable=self.info_var, style="Muted.TLabel").pack(side=tk.RIGHT)
        self.canvas = tk.Canvas(page, highlightthickness=0, borderwidth=0)
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=18, pady=(12, 4))
        self.canvas.bind("<Configure>", lambda e: self._redraw(schedule_hq=True))
        self.canvas.bind("<Double-Button-1>", lambda e: self.open_file(self.shown))
        self.canvas.bind("<<Paste>>", self._on_paste)
        self.canvas.bind("<Button-1>", lambda e: self.canvas.focus_set()
                         if self.mode == "3d" and self.from_var.get() == "image" else None)
        self.setup_btn = ttk.Button(self.canvas, text=tr('Jetzt einrichten'), style="Accent.TButton",
                                    command=self.load, **icons.opts("download", "accent_fg"))
        self.choose_btn = ttk.Button(self.canvas, text=tr('Bild auswählen…'), style="Accent.TButton",
                                     command=self.choose_source, **icons.opts("upload", "accent_fg"))
        self._update_actions()
        self.update_engine()

    # ================================================================ Modus und Unterbereiche

    def show(self):
        self.page.place(x=0, y=0, relwidth=1, relheight=1)
        self.page.lift()
        if not self._listed:
            self._listed = True
            self.refresh_list()
        self.update_engine()
        self.model_changed()

    def hide(self):
        self.page.place_forget()

    def focus(self):
        # beim 3D-Modell aus einem Bild gibt es keine Beschreibung: die Vorschau nimmt Strg+V für ein Bild entgegen
        (self.canvas if self.mode == "3d" and self.from_var.get() == "image" else self.prompt).focus_set()

    def set_mode(self, mode: str, fresh: bool = False):
        """Unterbereich wechseln: „create“ (Bild erstellen), „edit“ (Bild bearbeiten) bzw. „3d“ (3D-Modell). fresh: ein
        erneuter Klick auf „Bild erstellen“ beginnt ein neues Bild (leere Vorschau und Beschreibung)."""
        if mode != self.mode and self.busy:
            self._set_status(tr('Bitte warten, bis das Bild fertig ist – oder es mit „Stopp“ abbrechen.'))
            return
        changed = mode != self.mode
        if changed:
            self._drafts[self.mode] = self.prompt.get("1.0", tk.END).rstrip("\n")
            self.mode = mode
            self.prompt.delete("1.0", tk.END)
            self.prompt.insert("1.0", self._drafts[mode])
            self.prompt.edit_reset()
        self._apply_mode()
        if changed:
            self.tree.selection_remove(self.tree.selection())
            if (mode == "edit" or (mode == "3d" and self.from_var.get() == "image")) and self.source:
                self.show_source()
            else:
                self.show_image(None)
        elif fresh and mode == "create":
            self.new_image()
            return
        self.focus()

    def _apply_mode(self):
        """Seitenleiste, Titel und Bedienelemente passend zum Unterbereich. Beim Bearbeiten richtet sich das Format
        nach der Vorlage; beim 3D-Modell gibt es keine Beschreibung, dafür die Feinheit, und oben die Variante von
        TRELLIS.2 statt des Bildmodells (geladen wird es erst fürs Erzeugen – kein „Modell laden“)."""
        edit, mode3d = self.mode == "edit", self.mode == "3d"
        from_text = mode3d and self.from_var.get() == "text"  # 3D-Modell aus einer Beschreibung
        for btn, key in ((self.create_btn, "create"), (self.edit_btn, "edit"), (self.model3d_btn, "3d")):
            btn.state(["selected" if key == self.mode else "!selected"])
        self.title_var.set({"edit": tr('Bild bearbeiten'), "3d": tr('3D-Modell')}.get(self.mode, tr('Bild erstellen')))
        if mode3d and not from_text:
            self._inp.pack_forget()
            self.improve_btn.pack_forget()
        else:
            if not self._inp.winfo_manager():
                self._inp.pack(side=tk.BOTTOM, fill=tk.X, after=self._opts)
            if not self.improve_btn.winfo_manager():
                self.improve_btn.pack(side=tk.RIGHT, padx=(0, 8))
        for w in (self.format_label, self.format_combo, self.count_label, self.count_combo, self.from_frame,
                  self.res_label, self.res_combo):
            w.pack_forget()
        if mode3d:
            self.from_frame.pack(side=tk.LEFT, padx=(0, 6))
            self.res_label.pack(side=tk.LEFT)
            self.res_combo.pack(side=tk.LEFT, padx=(6, 14))
        else:
            if not edit:
                self.format_label.pack(side=tk.LEFT)
                self.format_combo.pack(side=tk.LEFT, padx=(6, 14))
            self.count_label.pack(side=tk.LEFT)
            self.count_combo.pack(side=tk.LEFT, padx=(6, 14))
        self.source_row.pack_forget()
        if edit or (mode3d and not from_text):
            self.source_row.pack(side=tk.BOTTOM, fill=tk.X, after=self._opts if mode3d else self._inp)
        if mode3d:
            self.load_btn.grid_remove()
            self.unload_btn.grid_remove()
            self.pick.configure(values=[v["name"] for v in trellis.VARIANTS.values()])
        else:
            self.load_btn.grid()
            self.unload_btn.grid()
            self.pick.configure(values=[m["name"] for m in sdcpp.MODELS.values()])
        self.gen_btn.configure(text=self._gen_text())
        self.update_engine()
        self._update_source_row()

    def _on_from(self):
        """„Aus einem Bild“ / „Aus einer Beschreibung“ umgeschaltet."""
        self.app.cfg["model3d_from"] = self.from_var.get()
        self._apply_mode()
        if self.from_var.get() == "image" and self.source and self.shown is None:
            self.show_source()
        elif self.from_var.get() == "text" and self.shown is None:
            self.show_image(None)
        self.focus()

    def _gen_text(self) -> str:
        if self.busy:
            return tr('Stopp')
        return tr('3D-Modell erzeugen') if self.mode == "3d" else tr('Generieren')

    def variant_key(self) -> str:
        return trellis.variant_key(self.app.cfg.get("model3d_variant"))

    def _res(self) -> int:
        return next((k for k, v in resolution_labels().items() if v == self.res_var.get()), trellis.RESOLUTIONS[0])

    def new_image(self):
        """Leere Vorschau, Beschreibung leeren – für das nächste Bild (Strg+N)."""
        if self.mode != "create":
            self.set_mode("create")
        self.tree.selection_remove(self.tree.selection())
        self.show_image(None)
        self.prompt.delete("1.0", tk.END)
        self.focus()

    def refresh_theme(self):
        pal = self.app.theme.pal
        self.bg = pal["bg"] if pal else self.app.root.cget("background")
        self.muted = pal["muted"] if pal else "#666666"
        self.canvas.configure(background=self.bg)
        row = round(THUMB * self.s) + round(12 * self.s)
        style = self.app.theme.style
        style.configure("Gallery.Sidebar.Treeview", rowheight=row)
        self._redraw()

    # ================================================================ Galerie

    def refresh_list(self, select: str | None = None):
        from tkinter import font as tkfont
        if self._font is None:
            self._font = tkfont.Font(font=(FAMILY, 10))
        tree = self.tree
        tree.delete(*tree.get_children())
        width = max(80, round(260 * self.s) - round(THUMB * self.s) - round(48 * self.s))
        missing = []
        items = self.gallery.snapshot()
        year = datetime.now().year
        for item in items:
            when = ""
            try:
                t = datetime.fromisoformat(item["created"])
                when = t.strftime("%d.%m. %H:%M" if t.year == year else "%d.%m.%Y")
            except (KeyError, ValueError):
                pass
            size = (tr('3D-Modell') if item.get("model3d") else
                    f"{item['width']}×{item['height']}" if item.get("width") else "")
            text = (self._short(item.get("prompt") or tr('(ohne Beschreibung)'), width) + "\n"
                    + self._short(" · ".join(x for x in (when, size) if x), width))
            img = self._thumb(item)
            if img is None:
                missing.append(item)
            tree.insert("", tk.END, iid=item["file"], text=" " + text.replace("\n", "\n "),
                        image=img or icons.image("photo", "muted", round(THUMB * self.s)) or "")
        n = len(items)
        self.count_var.set(tr('{0} Bilder', n) if n != 1 else tr('1 Bild'))
        if select and tree.exists(select):
            tree.selection_set(select)
            tree.see(select)
        if missing:
            self.app.background(lambda: self._make_thumbs(missing), lambda *_: None)

    def _short(self, text: str, width: int) -> str:
        """short() mit Gedächtnis: refresh_list beschriftet nach jedem neuen Bild alle Einträge neu."""
        key = (text, width)
        if key not in self._labels:
            if len(self._labels) > 4000:
                self._labels.clear()
            self._labels[key] = short(text, self._font, width)
        return self._labels[key]

    def _thumb(self, item: dict) -> tk.PhotoImage | None:
        """Quadratisches Vorschaubild (Mitte des Bildes) aus bilder/.vorschau/ – None, wenn es in dieser Größe noch
        fehlt. Gespeichert ist es so verkleinert, dass die kürzere Seite passt; Tk schneidet die Mitte heraus."""
        img = self._thumbs.get(item["file"])
        if img is not None:
            return img
        path, px = self.gallery.thumb(item), round(THUMB * self.s)
        try:
            if path.is_file() and min(images.png_size(path)) == px:
                full = tk.PhotoImage(master=self.tree, file=str(path))
                x0, y0 = (full.width() - px) // 2, (full.height() - px) // 2
                img = tk.PhotoImage(master=self.tree, width=px, height=px)
                img.tk.call(img, "copy", full, "-from", x0, y0, x0 + px, y0 + px)
                self._thumbs[item["file"]] = img
                return img
        except (OSError, ValueError, tk.TclError):
            pass
        return None

    def _make_thumbs(self, items: list[dict]):
        """Fehlende Vorschaubilder erzeugen (Hintergrund), jedes gleich in der Liste zeigen."""
        px = round(THUMB * self.s)
        for item in items:
            src = self.gallery.path(item)
            try:
                if src.is_file():
                    w, h = images.png_size(src)
                    f = px / max(1, min(w, h))
                    images.fit(src, self.gallery.thumb(item), max(px, round(w * f)), max(px, round(h * f)))
                    self.app.ui(self._thumb_ready, item)
            except (OSError, ValueError):
                continue

    def _thumb_ready(self, item: dict):
        self._thumbs.pop(item["file"], None)
        img = self._thumb(item)
        if img is not None and self.tree.exists(item["file"]):
            self.tree.item(item["file"], image=img)

    def _selected(self) -> dict | None:
        sel = self.tree.selection()
        return self.gallery.find(sel[0]) if sel else None

    def _item_at(self, y: int) -> dict | None:
        iid = self.tree.identify_row(y)
        return self.gallery.find(iid) if iid else None

    def _on_select(self, _e=None):
        item = self._selected()
        if item and item is not self.shown:
            self.show_image(item)

    def _on_menu(self, e):
        iid = self.tree.identify_row(e.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        self._ctx_item = self.gallery.find(iid)
        menu = self.menu3d if self._ctx_item and self._ctx_item.get("model3d") else self.menu
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    # ================================================================ Große Vorschau

    def show_image(self, item: dict | None):
        self.shown = item
        self._show_file(self.gallery.path(item) if item else None)
        if item and self._full is None:
            self.shown = None
        self._update_actions()
        self._redraw(schedule_hq=True)

    def show_source(self):
        """Die Vorlage groß zeigen (Klick auf ihr Vorschaubild: wie sah das Bild vor dem Bearbeiten aus?)."""
        if not self.source:
            return
        self.tree.selection_remove(self.tree.selection())
        self.shown = None
        self._show_file(self.source["png"])
        self._update_actions()
        self._redraw(schedule_hq=True)

    def _show_file(self, path: Path | None):
        self._full = self._display = None
        self._full_path = self._hq = None
        if not path:
            return
        key = str(path)
        try:
            st = Path(path).stat()
            stamp = (st.st_mtime_ns, st.st_size)
        except OSError:
            return
        entry = self._photos.pop(key, None)
        if not entry or entry["stamp"] != stamp:
            try:
                entry = {"stamp": stamp, "full": tk.PhotoImage(master=self.canvas, file=key), "hq": None}
            except tk.TclError:
                return
        self._photos[key] = entry  # ans Ende: zuletzt benutzt
        while len(self._photos) > PHOTO_CACHE:
            self._photos.pop(next(iter(self._photos)))
        self._full, self._full_path = entry["full"], path
        if entry["hq"] and entry["hq"][:2] == self._box():  # saubere Fassung in dieser Größe schon da
            self._display, self._hq = entry["hq"][2], (key, *entry["hq"][:2])

    def _update_actions(self):
        """Aktionen unter der Vorschau nur, solange ein Bild bzw. 3D-Modell aus der Galerie zu sehen ist."""
        item = self.shown
        is3d = bool(item and item.get("model3d"))
        for frame, want in ((self.actions, bool(item) and not is3d), (self.actions3d, is3d)):
            if not want:
                frame.pack_forget()
            elif not frame.winfo_manager():
                frame.pack(side=tk.BOTTOM, fill=tk.X, before=self.canvas)
        if is3d:
            parts = [item.get("model") or ""]
            if item.get("resolution"):
                parts.append(str(item["resolution"]))
            if item.get("triangles"):
                parts.append(tr('{0} Dreiecke', f"{item['triangles']:,}".replace(",", ".")))
            if item.get("seconds"):
                parts.append(clock(item["seconds"]))
            self.info_var.set("  ·  ".join(p for p in parts if p))
        elif item:
            parts = []
            if item.get("source"):
                parts.append(tr('bearbeitet'))
            if item.get("width"):
                parts.append(f"{item['width']} × {item['height']}")
            if item.get("seconds"):
                parts.append(tr('{0} s', item["seconds"]))
            if item.get("seed") is not None:
                parts.append(f"Seed {item['seed']}")
            self.info_var.set("  ·  ".join(parts))
        else:
            self.info_var.set("")

    def _box(self) -> tuple[int, int]:
        return max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())

    def _redraw(self, schedule_hq: bool = False):
        c = self.canvas
        c.delete("all")
        w, h = self._box()
        if w < 20 or h < 20:
            return
        if self._live is not None:
            c.create_image(w // 2, h // 2, image=self._live)
            return
        if self._full is not None:
            fw, fh = self._full.width(), self._full.height()
            if self._hq and self._hq == (str(self._full_path), w, h) and self._display is not None:
                img = self._display
            elif fw <= w and fh <= h:
                img = self._display = self._full
            else:  # sofort grob (fast so groß wie die Fläche), kurz darauf sauber verkleinert (images.fit)
                img = self._display = fit_photo(self._full, w, h, self.canvas)
                if schedule_hq:
                    self._schedule_hq()
            c.create_image(w // 2, h // 2, image=img)
            return
        # Platzhalter
        key = self.model_key()
        button = None
        # ohne Hinweistexte – was fehlt, steht oben rechts unter der Auswahl; nur „Bild auswählen…“ zum Bearbeiten
        # und für 3D aus einem Bild
        if self.mode == "3d":
            text = None
            button = self.choose_btn if self.from_var.get() != "text" else None
        elif self.mode == "edit":
            text, button = None, self.choose_btn
        elif sdcpp.ready(key):
            text = None
        else:
            text = tr('Für Bilder braucht Monhip einmalig noch: {0}.', self._missing_text())
            button = self.setup_btn
        gap = round(20 * self.s)
        if text is None:
            if button:
                c.create_window(w // 2, h // 2, window=button)
            return
        tid = c.create_text(w // 2, h // 2, text=text, width=min(w - 40, round(560 * self.s)), fill=self.muted,
                            font=(FAMILY, 11), justify=tk.CENTER, anchor="n")
        if button:  # Text und Knopf zusammen mittig – der Knopf immer unter dem Text, wie lang der auch ist
            x0, y0, x1, y1 = c.bbox(tid)
            top = max(gap, (h - (y1 - y0) - gap - button.winfo_reqheight()) // 2)
            c.coords(tid, w // 2, top)
            c.create_window(w // 2, top + (y1 - y0) + gap, window=button, anchor="n")
        else:
            x0, y0, x1, y1 = c.bbox(tid)
            c.coords(tid, w // 2, max(gap, (h - (y1 - y0)) // 2))

    def _missing_text(self) -> str:
        """Was fürs gewählte Bildmodell noch fehlt (ohne Netz geschätzt)."""
        key = self.model_key()
        name, gb = sdcpp.MODELS[key]["name"], sdcpp.missing_gb(key)
        if not sdcpp.find_server():
            return (tr('die Bild-Engine stable-diffusion.cpp und das Bildmodell {0} (zusammen etwa {1:.0f} GB)',
                       name, gb + 0.5) if gb else tr('die Bild-Engine stable-diffusion.cpp'))
        return tr('das Bildmodell {0} (etwa {1:.0f} GB)', name, max(1, gb))

    def _schedule_hq(self):
        if self._hq_after:
            self.canvas.after_cancel(self._hq_after)
        self._hq_after = self.canvas.after(HQ_DELAY_MS, self._make_hq)

    def _make_hq(self):
        """Gezeigtes Bild sauber auf die Fläche verkleinern (Hintergrund), dann austauschen."""
        self._hq_after = None
        src, (w, h) = self._full_path, self._box()
        if not src:
            return
        images.TEMP_DIR.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="bildvorschau-", suffix=".png", dir=images.TEMP_DIR)
        os.close(fd)  # PowerShell schreibt hinein, danach wird sie gelöscht – unter Windows nur ohne offenen Griff
        target = Path(name)

        def done(_r, err):
            try:
                if not err and self._full_path == src and self._box() == (w, h) and self._live is None:
                    self._display = tk.PhotoImage(master=self.canvas, file=str(target))
                    self._hq = (str(src), w, h)
                    if str(src) in self._photos:
                        self._photos[str(src)]["hq"] = (w, h, self._display)
                    self._redraw()
            except tk.TclError:
                pass
            finally:
                target.unlink(missing_ok=True)

        self.app.background(lambda: images.fit(src, target, w, h), done)

    # ================================================================ Vorlage zum Bearbeiten

    def choose_source(self):
        path = filedialog.askopenfilename(
            title=tr('Bild zum Bearbeiten auswählen'), parent=self.app.root,
            filetypes=[(tr('Bilder'), "*.png *.jpg *.jpeg *.bmp *.gif"), (tr('Alle Dateien'), "*.*")])
        if path:
            self.set_source(Path(path))

    def on_drop(self, paths):
        """Dateien aufs Fenster gezogen (Bereich Bilder): das erste Bild wird zur Vorlage zum Bearbeiten."""
        path = first_image(paths)
        if path:
            self.set_source(path)
        else:
            self._set_status(tr('Nur Bilder (PNG, JPG, BMP, GIF) lassen sich bearbeiten.'))

    def _on_paste(self, _e=None):
        """Strg+V in der Beschreibung: ein kopiertes Bild bzw. eine kopierte Bilddatei wird zur Vorlage, sonst
        normal Text einfügen."""
        path = first_image(filedrop.clipboard_files(self.app.root))
        if path:
            self.set_source(path)
            return "break"
        if filedrop.clipboard_has_image(self.app.root):
            self.app.background(images.save_clipboard, lambda p, _err: self.set_source(p) if p else
                                dialogs.showerror(tr('Bilder'), tr('Das Bild aus der Zwischenablage konnte nicht '
                                                                   'übernommen werden.')))
            return "break"
        return None

    def edit_item(self, item: dict | None):
        """Ein Bild aus der Galerie weiterbearbeiten."""
        if item:
            self.set_source(self.gallery.path(item), name=item.get("prompt"), mode="edit")

    def to_3d(self, item: dict | None):
        """Aus einem Bild der Galerie ein 3D-Modell machen: wird zur Vorlage im Unterbereich „3D-Modell“."""
        if item:
            self.set_source(self.gallery.path(item), name=item.get("prompt"), mode="3d")

    def set_source(self, path: Path, name: str | None = None, mode: str | None = None):
        """Vorlage übernehmen: als PNG (höchstens SOURCE_MAX Pixel lang) und kleines Vorschaubild in den Temp-Ordner,
        dann in den Unterbereich mode wechseln – ohne Angabe bleibt „3D-Modell“ und „Bild erstellen“ wird zu „Bild
        bearbeiten“ – und sie groß zeigen."""
        if self.busy:
            self._set_status(tr('Bitte warten, bis das Bild fertig ist – oder es mit „Stopp“ abbrechen.'))
            return
        try:
            images.check(path)
        except ValueError as e:
            dialogs.showerror(tr('Bild bearbeiten'), str(e))
            return
        n = next(self._counter)
        png = images.TEMP_DIR / f"vorlage-{os.getpid()}-{n}.png"
        thumb = images.TEMP_DIR / f"vorlage-{os.getpid()}-{n}-klein.png"
        px = round(SOURCE_THUMB * self.s)
        self._set_status(tr('Übernehme das Bild …'))

        def work():
            w, h = images.fit(path, png, SOURCE_MAX, SOURCE_MAX)
            images.fit(png, thumb, 3 * px, px)
            return w, h

        def done(size, err):
            if err:
                self._set_status("")
                dialogs.showerror(tr('Bild bearbeiten'), tr('Das Bild lässt sich nicht öffnen: {0}', err))
                return
            self.source = {"path": path, "png": png, "thumb": thumb, "w": size[0], "h": size[1],
                           "name": short(name, self._font, round(260 * self.s)) if name and self._font else path.name}
            try:
                self._source_img = tk.PhotoImage(master=self.page, file=str(thumb))
            except tk.TclError:
                self._source_img = None
            self._set_status("")
            target = mode or ("3d" if self.mode == "3d" else "edit")
            if target == "3d" and self.from_var.get() != "image":  # ein Bild gewählt: 3D-Modell aus diesem Bild
                self.from_var.set("image")
                self.app.cfg["model3d_from"] = "image"
                if self.mode == "3d":
                    self._apply_mode()
            if self.mode != target:
                self.set_mode(target)
            self._update_source_row()
            self.show_source()
            self.focus()

        self.app.background(work, done)

    def clear_source(self):
        self.source, self._source_img = None, None
        self._update_source_row()
        if self.shown is None:
            self.show_image(None)

    def _update_source_row(self):
        """Zeile über der Beschreibung: Vorschaubild der Vorlage, Name und Größe des Ergebnisses."""
        src = self.source
        if src:
            w, h = sdcpp.edit_size(src["w"], src["h"], self.model_key())
            self.source_label.configure(image=self._source_img or "", text="" if self._source_img else "▣")
            if self.mode == "3d":
                self.source_var.set(tr('{0}  ·  wird freigestellt und als 3D-Modell nachgebildet  ·  zum Vergrößern '
                                       'anklicken', src["name"]))
            else:
                self.source_var.set(tr('{0}  ·  Ergebnis {1} × {2}  ·  zum Vergrößern anklicken', src["name"], w, h))
            if not self.source_clear.winfo_manager():
                self.source_clear.pack(side=tk.RIGHT, padx=(0, 6))
        else:
            self.source_label.configure(image=icons.image("photo", "muted", round(SOURCE_THUMB * self.s * 0.6))
                                        or "", text="")
            self.source_var.set(tr('Noch kein Bild – auswählen, hierher ziehen oder mit Strg+V einfügen.'))
            self.source_clear.pack_forget()

    # ================================================================ Bildmodell wählen, laden, entladen

    def model_key(self) -> str:
        return sdcpp.model_key(self.app.cfg.get("image_model"))

    def _on_pick(self, _e=None):
        if self.mode == "3d":
            self.app.cfg["model3d_variant"] = next((k for k, v in trellis.VARIANTS.items()
                                                    if v["name"] == self.pick_var.get()), trellis.DEFAULT_VARIANT)
            self.app.save_config()
            self.update_engine()
            self._redraw()
            return
        key = next((k for k, m in sdcpp.MODELS.items() if m["name"] == self.pick_var.get()), sdcpp.DEFAULT_MODEL)
        self.app.cfg["image_model"] = key
        self.app.save_config()
        self.update_engine()
        self._update_source_row()
        self._redraw()

    def update_engine(self):
        """Stand des Bildmodells unter der Auswahl (wie „Geladen: …“ im Chat) – beim 3D-Modell der von TRELLIS.2."""
        if hasattr(self, "engine3d_status"):
            self.engine3d_status.set(trellis.describe(self.variant_key()))
        if self.mode == "3d":
            variant = self.variant_key()
            name = trellis.VARIANTS[variant]["name"]
            if self.pick_var.get() != name:
                self.pick_var.set(name)
            if self.busy and self._phase == "download":
                text = tr('Lade {0} herunter …', name)
            elif self.busy:
                text = tr('Erzeuge das 3D-Modell mit {0} …', name)
            elif self.from_var.get() == "text":
                image = sdcpp.MODELS[self.model_key()]["name"]
                ready = sdcpp.ready(self.model_key()) and trellis.ready(variant)
                text = (tr('Bild mit {0}, dann 3D mit {1}', image, name) if ready else
                        tr('Bild mit {0}, dann 3D mit {1} – fehlt noch, wird beim ersten Mal heruntergeladen', image,
                           name))
            elif trellis.ready(variant):
                text = tr('Bereit: {0}', name)
            else:
                text = tr('Fehlt noch – wird beim ersten 3D-Modell heruntergeladen (etwa {0:.0f} GB)',
                          max(1, trellis.missing_gb(variant)))
            self.engine_var.set(text)
            return
        key = self.model_key()
        m = sdcpp.MODELS[key]
        if self.pick_var.get() != m["name"]:
            self.pick_var.set(m["name"])
        loaded = sdcpp.MODELS.get(self.server.model or "", {}).get("name")
        if self.busy and self._phase == "load":
            text = tr('Lade {0} …', m["name"])
        elif self.busy and self._phase == "download":
            text = tr('Lade {0} herunter …', m["name"])
        elif self.server.ready_for(key):
            text = tr('Geladen: {0}', m["name"])
            if self.server.compatibility_active:
                text += tr(' · Kompatibel (langsamer)')
        elif not sdcpp.ready(key):
            text = (tr('Fehlt noch – „Modell laden“ lädt es herunter (etwa {0:.0f} GB)', max(1, sdcpp.missing_gb(key)))
                    if sdcpp.missing_gb(key) else tr('Bild-Engine fehlt noch – „Modell laden“ lädt sie herunter'))
        elif loaded:
            text = tr('Nicht geladen  ·  geladen ist {0}', loaded)
        else:
            text = tr('Kein Bildmodell geladen')
        self.engine_var.set(text)
        if hasattr(self, "engine_status"):
            self.engine_status.set(sdcpp.describe(key))

    def load(self):
        """„Modell laden“: fehlende Dateien herunterladen (mit Rückfrage), dann das Bildmodell laden."""
        self._run(self.model_key(), None)

    def unload(self):
        """Bildmodell entladen – bricht auch einen laufenden Download, das Laden oder ein Bild ab."""
        if self.busy:
            self.stop_event.set()
        if not self.server.is_running():
            self.update_engine()
            return

        def work():
            self.server.stop()
            self.app.ui(self.update_engine)
            self.app.ui(self._set_status, tr('Bildmodell entladen – der Grafikspeicher ist wieder frei.'))

        threading.Thread(target=work, daemon=True).start()

    def _run(self, key: str, job: dict | None, since: float | None = None):
        """Bildmodell bereitmachen (herunterladen, laden) und – mit job – Bilder erzeugen bzw. bearbeiten. since: Beginn
        eines vorausgegangenen Downloads (für die Benachrichtigung zählt die ganze Wartezeit)."""
        if self.busy or self._checking:
            return
        if not sdcpp.ready(key):
            begun = time.monotonic()
            self._offer_download(key, lambda: self._run(key, job, since=begun))
            return
        if job is None and self.server.ready_for(key):
            self._set_status(tr('{0} ist schon geladen.', sdcpp.MODELS[key]["name"]))
            return
        if not self._make_room(key):
            return
        stop = self.stop_event = threading.Event()
        self._set_busy(True)
        chat = self.app.server
        started = since or time.monotonic()

        def work():
            deadline = time.time() + 30  # entladenes Sprachmodell: warten, bis sein Speicher frei ist
            while chat.proc is not None and chat.proc.poll() is None and time.time() < deadline:
                time.sleep(0.2)
            if not self.server.ready_for(key):
                self.app.ui(self._set_phase, "load")
                self.server.start(key, stop)
            if job is None:
                return None
            self.app.ui(self._set_phase, "run")
            t0 = time.time()
            refs = [job["source"]["png"].read_bytes()] if job.get("source") else None
            count = job["count"]
            pngs = self.server.generate(job["prompt"], job["width"], job["height"], count, job["seed"], stop,
                                        lambda d, t, img: self.app.ui(self._on_progress, d, t, img, count),
                                        refs=refs)
            seconds = round((time.time() - t0) / len(pngs), 1)
            info = {"prompt": job["prompt"], "width": job["width"], "height": job["height"], "model": key,
                    "seconds": seconds}
            if job.get("source"):
                info["source"] = job["source"]["path"].name
            # von hinten einreihen: die Galerie zeigt die neuesten oben – so steht Bild 1 oben, Bild 2 darunter …
            items = [self.gallery.add(pngs[i], {**info, "seed": job["seed"] + i}) for i in reversed(range(len(pngs)))]
            return items[::-1]

        self.app.background(work, lambda items, err: self._finished(key, job, items, err, stop, started))

    def _offer_download(self, key: str, then):
        """Fehlende Dateien des Bildmodells (und ggf. die Bild-Engine) suchen, nachfragen, herunterladen – Fortschritt
        unten auf der Seite, „Stopp“ bricht ab. Danach then()."""
        name = sdcpp.MODELS[key]["name"]
        self._checking, self._dl_kind = True, "image"
        self.load_btn.configure(state=tk.DISABLED)
        self.gen_btn.configure(state=tk.DISABLED)
        self._set_status(tr('Prüfe, was für {0} noch fehlt …', name))

        def planned(plan, err):
            self._checking = False
            self.load_btn.configure(state=tk.NORMAL)
            self.gen_btn.configure(state=tk.NORMAL)
            if err:
                self._set_status(tr('Suche fehlgeschlagen: {0}', err))
                dialogs.showerror(tr('Bilder'), tr('Suche fehlgeschlagen: {0}', err))
                return
            parts = []
            if plan["program"]:
                parts.append(f"stable-diffusion.cpp {plan['tag']} ({plan['kind']}): "
                             f"{sum(x[2] for x in plan['program']) / 1024 ** 2:.0f} MB")
            if plan.get("runtime"):
                parts.append(tr('AMD-ROCm-Laufzeit {0} für deine Grafikkarte: {1:.1f} GB',
                                plan["runtime"]["version"], plan["runtime"]["size"] / 1e9))
            for fname, _url, size, _dest in plan["weights"]:
                parts.append(tr('Modelldatei {0}: {1:.2f} GB', fname, size / 1e9))
            if not parts:
                if sdcpp.ready(key):
                    then()
                else:
                    dialogs.showerror(tr('Bilder'), tr('Auf GitHub wurde keine passende Version von '
                                                       'stable-diffusion.cpp gefunden.'))
                return
            text = (tr('Für {0} fehlt noch:\n\n', name) + "\n".join(parts)
                    + tr('\n\nZusammen {0:.1f} GB – jetzt herunterladen und danach laden?', plan['size'] / 1e9))
            license_ = sdcpp.MODELS[key]["license"]
            if not dialogs.askyesno(tr('Bildmodell herunterladen'), text + "\n\n" + tr('Lizenz: {0}', license_)):
                self._set_status(tr('Download abgebrochen.'))
                return
            stop = self.stop_event = threading.Event()
            self._set_busy(True)
            self._set_phase("download")
            begun = time.monotonic()
            self.app.background(
                lambda: sdcpp.install(plan, lambda d, n: self.app.ui(self._on_download, d, n), stop),
                lambda _r, error: downloaded(error, stop, begun))

        def downloaded(error, stop, begun):
            self._set_busy(False)
            self.update_engine()
            self._update_source_row()
            self._redraw()
            if error:
                self._set_status(tr('Download abgebrochen.') if stop.is_set() else
                                 tr('Download fehlgeschlagen: {0}', error))
                if not stop.is_set():
                    self.app.notify_done(tr('Download fehlgeschlagen'), name, begun)
                    dialogs.showerror(tr('Bilder'), tr('Download fehlgeschlagen: {0}', error))
                return
            then()  # laden und ggf. das Bild erzeugen – gemeldet wird, wenn das fertig ist

        self.app.background(lambda: sdcpp.plan(key, update=False), planned)

    def _make_room(self, key: str) -> bool:
        """Ist ein Sprachmodell geladen und zu wenig Grafikspeicher frei: fragen (oder nicht, wenn so eingestellt) und
        es entladen. False = abbrechen."""
        app = self.app
        if not app.server.is_running() or self.server.ready_for(key):
            return True
        free = sdcpp.free_vram_mib()
        if free is not None and free >= sdcpp.need_vram_mib(key):
            return True  # passt auch so (z. B. kleines Sprachmodell auf großer Karte)
        if app.busy or app.room.ai_busy:
            dialogs.showinfo(tr('Bilder'), tr(
                'Das Sprachmodell antwortet gerade. Für das Bild muss es entladen werden – bitte warten, bis die '
                'Antwort fertig ist, oder sie stoppen.'))
            return False
        name = model_name(app.server.model) if app.server.model else tr('Sprachmodell')
        if app.cfg.get("image_unload") != "auto":
            ok, remember = dialogs.ask_with_option(
                tr('Grafikspeicher freimachen'),
                tr('Das Sprachmodell „{0}“ belegt den Grafikspeicher, den das Bildmodell braucht. Es wird für das Bild '
                   'entladen – im Chat lässt es sich danach mit „Modell laden“ wieder laden.', name),
                tr('Nicht mehr fragen – künftig automatisch entladen'),
                yes=tr('Entladen und fortfahren'), no=tr('Abbrechen'))
            if not ok:
                return False
            if remember:
                app.cfg["image_unload"] = "auto"
                if hasattr(self, "ask_var"):
                    self.ask_var.set(False)
                app.save_config()
        if app.expert_job:
            app.expert_job.stop_event.set()
        app.unload_model()
        self._set_status(tr('Sprachmodell „{0}“ entladen, um Grafikspeicher für das Bild freizumachen.', name))
        return True

    # ================================================================ Erzeugen und Bearbeiten

    def _format(self) -> str:
        label = self.format_var.get()
        return next((k for k, v in format_labels().items() if v == label), "square")

    def _on_enter(self, e):
        if e.state & 0x0001:  # Umschalt+Enter: neue Zeile
            return None
        self.generate()
        return "break"

    def generate(self):
        if self.gen_btn.instate(["disabled"]):  # z. B. Enter, während die Beschreibung verbessert wird
            return
        if self.busy:
            self.stop_event.set()
            self.gen_btn.configure(state=tk.DISABLED)
            self._set_status(tr('Breche ab …'))
            return
        if self.mode == "3d":
            self._generate_3d()
            return
        prompt = self.prompt.get("1.0", tk.END).strip()
        edit = self.mode == "edit"
        if edit and not self.source:
            self._set_status(tr('Bitte zuerst das Bild auswählen, das bearbeitet werden soll.'))
            self.choose_source()
            return
        if not prompt:
            self._set_status(tr('Bitte zuerst beschreiben, was sich am Bild ändern soll.') if edit else
                             tr('Bitte zuerst beschreiben, was auf dem Bild zu sehen sein soll.'))
            self.focus()
            return
        key = self.model_key()
        count = int(self.count_choice.get() or 1)
        if edit:
            width, height = sdcpp.edit_size(self.source["w"], self.source["h"], key)
            self.app.cfg.update({"image_count": count})
        else:
            fmt = self._format()
            width, height = FORMATS[fmt]
            self.app.cfg.update({"image_format": fmt, "image_count": count})
        job = {"prompt": prompt, "width": width, "height": height, "count": count,
               "seed": random.randint(0, 2 ** 31 - 1), "source": dict(self.source) if edit else None}
        self._run(key, job)

    def _set_busy(self, busy: bool):
        self.busy = busy
        self.gen_btn.configure(state=tk.NORMAL, text=self._gen_text(), **icons.opts("stop" if busy else "play", "accent_fg"))
        self.load_btn.configure(state=tk.DISABLED if busy else tk.NORMAL)
        self.pick.configure(state=tk.DISABLED if busy else "readonly")
        if self._tick_after:
            self.canvas.after_cancel(self._tick_after)
            self._tick_after = None
        self.glide.stop()
        if busy:
            self._phase, self._steps = "", (0, 1, 1)
            self.progress_row.pack(side=tk.BOTTOM, fill=tk.X, before=self.status)
            self.progress.configure(mode="indeterminate")
            self.progress.start(15)
            self._t0 = time.time()
            self._tick()
        else:
            self._phase, self._chain, self._prefix = "", False, ""
            self.progress.stop()
            self.progress_row.pack_forget()
            self._live = self._live_src = None
        self.model_changed()

    def _set_phase(self, phase: str):
        self._phase = phase
        if self._chain:  # 3D-Modell aus einer Beschreibung: zwei Teile
            self._prefix = (tr('Teil 1 von 2 (Bild)') if phase in ("load", "run") else tr('Teil 2 von 2 (3D-Modell)')
                            if phase == "run3d" else "") + "  ·  "
        if phase in ("run", "download", "run3d"):
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.glide.set(0, animate=False)
        elif phase == "load":
            self.glide.stop()
            self.progress.configure(mode="indeterminate")
            self.progress.start(15)
        self._t0 = time.time() if phase in ("load", "run3d") else self._t0
        self.update_engine()
        self._tick(once=True)

    def _tick(self, once: bool = False):
        """Statuszeile während Laden und Erzeugen (läuft jede Sekunde weiter; beim Download zählt _on_download). Beim
        3D-Modell aus einer Beschreibung steht davor, welcher der zwei Teile gerade läuft."""
        if not self.busy:
            return
        text = self._tick_text()
        if text:
            self._set_status(self._prefix + text if self._prefix.strip(" ·") else text)
        if not once:
            self._tick_after = self.canvas.after(1000, self._tick)

    def _tick_text(self) -> str:
        """Stand für die Statuszeile ("" beim Download: den zeigt _on_download)."""
        secs = int(time.time() - self._t0)
        if self._phase == "run3d":
            st = self._stage
            if st.get("stage"):
                text = tr('Stufe {0} von 7: {1}', st["stage"], trellis.stage_name(st["stage"]))
                if st.get("steps"):
                    text += "  ·  " + tr('Durchgang {0} von {1}', st["step"], st["steps"])
            else:
                text = tr('Starte die 3D-Engine …')
            return text + "  ·  " + clock(secs) + "  ·  " + tr('dauert meist 3–8 Minuten')
        if self._phase == "load":
            return tr('Lade das Bildmodell … {0} s (beim ersten Mal bis zu einer Minute)', secs)
        if self._phase == "run" and self._steps[0] == 0:  # vor dem ersten Schritt: Beschreibung/Vorlage einlesen
            return tr('Bereite vor … {0} s', secs)
        if self._phase == "run":
            done, total, count = self._steps
            per = max(1, total // max(1, count))
            nr = min(count, done // per + 1)
            text = (tr('Bild {0} von {1}', nr, count) + "  ·  " if count > 1 else "")
            return text + tr('Schritt {0} von {1}  ·  {2} s', min(per, done - (nr - 1) * per), per, secs)
        if self._phase != "download":
            return tr('Bereite vor … {0} s', secs)
        return ""

    def _on_download(self, done: int, total: int):
        if not self.busy or self._phase != "download":
            return
        self.glide.set(done, maximum=max(1, total))
        pct = done * 100 / total if total else 0
        if self._dl_kind == "3d":
            self._set_status(tr('Lade die 3D-Engine und das Modell herunter … {0:.0f} % ({1:.1f} von {2:.1f} GB)  ·  '
                                '„Stopp“ bricht ab', pct, done / 1e9, total / 1e9))
        else:
            self._set_status(tr('Lade das Bildmodell herunter … {0:.0f} % ({1:.1f} von {2:.1f} GB)  ·  „Stopp“ bricht '
                                'ab', pct, done / 1e9, total / 1e9))

    def _on_progress(self, done: int, total: int, preview: bytes | None, count: int):
        if not self.busy:
            return
        self._steps = (done, total, count)
        self.glide.set(done, maximum=total)
        if preview:
            self._show_live(preview)
        self._tick(once=True)

    def _show_live(self, png: bytes):
        """Zwischenbild (klein, aus dem Rechenstand) groß zeigen – so groß wie die Fläche (fit_photo), damit das fertige
        Bild danach nicht kleiner und dann wieder größer erscheint."""
        try:
            src = tk.PhotoImage(master=self.canvas, data=base64.b64encode(png).decode("ascii"), format="png")
        except tk.TclError:
            return
        w, h = self._box()
        self._live_src = src
        self._live = fit_photo(src, w, h, self.canvas)
        self._redraw()

    def _finished(self, key: str, job: dict | None, items, err, stop: threading.Event, started: float | None = None):
        self._set_busy(False)
        self.update_engine()
        name = sdcpp.MODELS[key]["name"]
        if err:
            if stop.is_set():
                self._set_status(tr('Abgebrochen.'))
            else:
                self._set_status(tr('Fehler: {0}', err))
                self.app.notify_done(tr('Bild fehlgeschlagen') if job else tr('Bildmodell konnte nicht geladen werden'),
                                     str(err), started)
                dialogs.showerror(tr('Bilder'), err)
            self._redraw()
            return
        if job is None:
            self._set_status(tr('{0} ist geladen.', name))
            self.app.notify_done(tr('Bildmodell geladen'), name, started)
            self._redraw()
            return
        self.app.notify_done(tr('Bild fertig') if len(items) == 1 else tr('{0} Bilder fertig', len(items)),
                             job["prompt"], started)
        self.refresh_list(select=items[0]["file"])
        self.show_image(items[0])
        secs = items[0].get("seconds")
        self._set_status(tr('Fertig – {0} s je Bild. Gespeichert in der Galerie.', secs) if len(items) == 1 else
                         tr('Fertig – {0} Bilder, je {1} s. Gespeichert in der Galerie.', len(items), secs))

    # ================================================================ 3D-Modell (trellis.py)

    def _generate_3d(self):
        """„3D-Modell erzeugen“: fehlt die 3D-Engine oder das Modell, erst nachfragen und herunterladen. Aus einer
        Beschreibung: vorher ggf. auch das Bildmodell."""
        if self.from_var.get() == "text":
            prompt = self.prompt.get("1.0", tk.END).strip()
            if not prompt:
                self._set_status(tr('Bitte zuerst beschreiben, welcher Gegenstand als 3D-Modell entstehen soll.'))
                self.focus()
                return
            key, variant, begun = self.model_key(), self.variant_key(), time.monotonic()
            self.app.cfg["model3d_res"] = self._res()

            def run():
                self._run_text_3d(prompt, key, variant, begun)

            def need_3d():
                if trellis.ready(variant):
                    run()
                else:
                    self._offer_download_3d(variant, run)

            if sdcpp.ready(key):
                need_3d()
            else:
                self._offer_download(key, need_3d)
            return
        if not self.source:
            self._set_status(tr('Bitte zuerst das Bild auswählen, aus dem das 3D-Modell entstehen soll.'))
            self.choose_source()
            return
        variant, begun = self.variant_key(), time.monotonic()  # für die Benachrichtigung zählt auch der Download
        self.app.cfg["model3d_res"] = self._res()
        if trellis.ready(variant):
            self._run_3d(variant, begun)
        else:
            self._offer_download_3d(variant, lambda: self._run_3d(variant, begun))

    def _offer_download_3d(self, variant: str, then=None):
        """Fehlendes für 3D-Modelle (3D-Engine, Modelldateien) suchen, nachfragen, herunterladen – Fortschritt unten auf
        der Seite, „Stopp“ bricht ab. Danach then()."""
        name = trellis.VARIANTS[variant]["name"]
        self._checking, self._dl_kind = True, "3d"
        self.gen_btn.configure(state=tk.DISABLED)
        self._set_status(tr('Prüfe, was für {0} noch fehlt …', name))

        def planned(plan, err):
            self._checking = False
            self.gen_btn.configure(state=tk.NORMAL)
            if err:
                self._set_status(tr('Suche fehlgeschlagen: {0}', err))
                dialogs.showerror(tr('3D-Modell'), tr('Suche fehlgeschlagen: {0}', err))
                return
            parts = []
            if plan["program"]:
                parts.append(f"trellis.cpp {plan['tag']} ({plan['kind']}): "
                             f"{sum(x[2] for x in plan['program']) / 1024 ** 2:.0f} MB")
            if plan["weights"]:
                parts.append(tr('{0}: {1} Modelldateien, {2:.1f} GB', name, len(plan["weights"]),
                                sum(x[2] for x in plan["weights"]) / 1e9))
            if not parts:
                if trellis.ready(variant) and then:
                    then()
                elif not trellis.ready(variant):
                    dialogs.showerror(tr('3D-Modell'), tr('Auf GitHub wurde keine passende Version von trellis.cpp '
                                                          'gefunden.'))
                return
            text = ((tr('Grafikkarte: {0}\n', plan["gpu"]) if plan["gpu"] else "")
                    + tr('Für 3D-Modelle fehlt noch:\n\n') + "\n".join(parts)
                    + tr('\n\nZusammen {0:.1f} GB – jetzt herunterladen?', plan["size"] / 1e9)
                    + "\n\n" + trellis.LICENSE)
            if not dialogs.askyesno(tr('3D-Engine herunterladen'), text):
                self._set_status(tr('Download abgebrochen.'))
                return
            stop = self.stop_event = threading.Event()
            self._set_busy(True)
            self._set_phase("download")
            begun = time.monotonic()
            self.app.background(
                lambda: trellis.install(plan, lambda d, n: self.app.ui(self._on_download, d, n), stop),
                lambda _r, error: downloaded(error, stop, begun))

        def downloaded(error, stop, begun):
            self._set_busy(False)
            self.update_engine()
            self._redraw()
            if error:
                self._set_status(tr('Download abgebrochen.') if stop.is_set() else
                                 tr('Download fehlgeschlagen: {0}', error))
                if not stop.is_set():
                    self.app.notify_done(tr('Download fehlgeschlagen'), name, begun)
                    dialogs.showerror(tr('3D-Modell'), tr('Download fehlgeschlagen: {0}', error))
                return
            if then:
                then()  # gleich das 3D-Modell erzeugen – gemeldet wird, wenn das fertig ist
            else:
                self._set_status(tr('Installiert: {0}', trellis.describe(variant)))

        self.app.background(lambda: trellis.plan(variant), planned)

    def _free_vram_3d(self) -> bool:
        """TRELLIS.2 braucht fast den ganzen Grafikspeicher: ein geladenes Sprachmodell wird entladen (nach Rückfrage,
        außer „nicht mehr fragen“), das Bildmodell beendet (im Hintergrund). False = abbrechen."""
        app = self.app
        if app.busy or app.room.ai_busy:
            dialogs.showinfo(tr('3D-Modell'), tr(
                'Das Sprachmodell antwortet gerade. Für das 3D-Modell muss es entladen werden – bitte warten, bis die '
                'Antwort fertig ist, oder sie stoppen.'))
            return False
        if app.server.is_running() and app.server.model:
            name = model_name(app.server.model)
            if app.cfg.get("image_unload") != "auto":
                ok, remember = dialogs.ask_with_option(
                    tr('Grafikspeicher freimachen'),
                    tr('Das Sprachmodell „{0}“ belegt den Grafikspeicher, den das 3D-Modell braucht. Es wird dafür '
                       'entladen – im Chat lässt es sich danach mit „Modell laden“ wieder laden.', name),
                    tr('Nicht mehr fragen – künftig automatisch entladen'),
                    yes=tr('Entladen und fortfahren'), no=tr('Abbrechen'))
                if not ok:
                    return False
                if remember:
                    app.cfg["image_unload"] = "auto"
                    if hasattr(self, "ask_var"):
                        self.ask_var.set(False)
                    app.save_config()
            if app.expert_job:
                app.expert_job.stop_event.set()
            app.unload_model()
        return True

    def _run_3d(self, variant: str, begun: float):
        if self.busy or not self.source:
            return
        if not self._free_vram_3d():
            return
        src, res, seed = dict(self.source), self._res(), random.randint(0, 2 ** 31 - 1)
        stop = self.stop_event = threading.Event()
        self._stage = {}
        self._set_busy(True)
        self._set_phase("run3d")
        chat, log = self.app.server, (lambda t: self.app.events.put(("log", t)))

        def work():
            self.server.stop()  # Bildmodell aus dem Grafikspeicher
            deadline = time.time() + 30  # entladenes Sprachmodell: warten, bis sein Speicher frei ist
            while chat.proc is not None and chat.proc.poll() is None and time.time() < deadline:
                time.sleep(0.2)
            images.TEMP_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="3d-", dir=images.TEMP_DIR) as folder:
                out, t0 = Path(folder) / "modell.glb", time.time()
                trellis.generate(variant, src["png"], out, res, seed, stop,
                                 lambda st: self.app.ui(self._on_3d_progress, st), log)
                info = {"prompt": src["name"] or src["path"].name, "width": src["w"], "height": src["h"],
                        "model": trellis.VARIANTS[variant]["name"], "resolution": res, "seed": seed,
                        "seconds": round(time.time() - t0)}
                try:
                    info["triangles"] = modell3d.stats(out)["triangles"]
                except (OSError, ValueError, KeyError, IndexError):
                    pass
                return self.gallery.add_model(src["png"].read_bytes(), out, info)

        self.app.background(work, lambda item, err: self._finished_3d(item, err, stop, begun))

    def _run_text_3d(self, prompt: str, key: str, variant: str, begun: float):
        """3D-Modell aus einer Beschreibung: Bildmodell laden (falls nötig), ein Bild als Vorlage erzeugen (kommt auch in
        die Galerie), Bildmodell beenden – sonst reicht der Grafikspeicher nicht – und daraus das 3D-Modell."""
        if self.busy:
            return
        if not self._free_vram_3d():
            return
        res, seed = self._res(), random.randint(0, 2 ** 31 - 1)
        stop = self.stop_event = threading.Event()
        self._stage, self._chain = {}, True
        self._set_busy(True)
        chat, log = self.app.server, (lambda t: self.app.events.put(("log", t)))
        width, height = FORMATS["square"]

        def work():
            deadline = time.time() + 30  # entladenes Sprachmodell: warten, bis sein Speicher frei ist
            while chat.proc is not None and chat.proc.poll() is None and time.time() < deadline:
                time.sleep(0.2)
            if not self.server.ready_for(key):
                self.app.ui(self._set_phase, "load")
                self.server.start(key, stop)
            self.app.ui(self._set_phase, "run")
            t0 = time.time()
            png = self.server.generate(prompt + OBJECT_HINT, width, height, 1, seed, stop,
                                       lambda d, t, img: self.app.ui(self._on_progress, d, t, img, 1))[0]
            image = self.gallery.add(png, {"prompt": prompt, "width": width, "height": height, "model": key,
                                           "seed": seed, "seconds": round(time.time() - t0)})
            self.app.ui(self._image_for_3d, image)
            self.server.stop()  # Grafikspeicher fürs 3D-Modell
            self.app.ui(self._set_phase, "run3d")
            images.TEMP_DIR.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="3d-", dir=images.TEMP_DIR) as folder:
                out, t3 = Path(folder) / "modell.glb", time.time()
                trellis.generate(variant, self.gallery.path(image), out, res, seed, stop,
                                 lambda st: self.app.ui(self._on_3d_progress, st), log)
                info = {"prompt": prompt, "width": width, "height": height, "model": trellis.VARIANTS[variant]["name"],
                        "resolution": res, "seed": seed, "seconds": round(time.time() - t3),
                        "image": image["file"]}
                try:
                    info["triangles"] = modell3d.stats(out)["triangles"]
                except (OSError, ValueError, KeyError, IndexError):
                    pass
                return self.gallery.add_model(png, out, info)

        self.app.background(work, lambda item, err: self._finished_3d(item, err, stop, begun))

    def _image_for_3d(self, item: dict):
        """Das Bild für das 3D-Modell ist fertig: in die Galerie und groß zeigen, solange das 3D-Modell entsteht."""
        self._live = self._live_src = None
        self.refresh_list(select=item["file"])
        self.show_image(item)

    def _on_3d_progress(self, state: dict):
        if not self.busy or self._phase != "run3d":
            return
        self._stage = state
        self.glide.set(round(trellis.fraction(state) * 1000), maximum=1000)
        self._tick(once=True)

    def _finished_3d(self, item, err, stop: threading.Event, begun: float):
        self._set_busy(False)
        self.update_engine()
        if err:
            if stop.is_set():
                self._set_status(tr('Abgebrochen.'))
            else:
                self._set_status(tr('Fehler: {0}', err))
                self.app.notify_done(tr('3D-Modell fehlgeschlagen'), str(err), begun)
                dialogs.showerror(tr('3D-Modell'), err)
            self._redraw()
            return
        self.refresh_list(select=item["file"])
        self.show_image(item)
        self._set_status(tr('Fertig nach {0} – das 3D-Modell steht in der Galerie. „Ansehen“ öffnet es im Browser.',
                            clock(item.get("seconds") or 0)))
        self.app.notify_done(tr('3D-Modell fertig'), item.get("prompt") or "", begun)

    def view_3d(self, item: dict | None):
        """3D-Modell im Browser zeigen: eine eigenständige Seite (modell3d.write_viewer) im Temp-Ordner öffnen."""
        glb = self.gallery.model_path(item) if item else None
        if not glb:
            if item:
                dialogs.showerror(tr('3D-Modell'), tr('Die Datei des 3D-Modells fehlt.'))
            return
        page = images.TEMP_DIR / f"3d-ansicht-{glb.stem}.html"
        self._set_status(tr('Öffne das 3D-Modell im Browser …'))

        def work():
            modell3d.write_viewer(glb, page, item.get("prompt") or glb.stem)
            plattform.open_path(page)

        self.app.background(work, lambda _r, err: self._set_status(
            tr('Das 3D-Modell ließ sich nicht öffnen: {0}', err) if err else ""))

    def _file_words(self, item: dict) -> str:
        """Dateiname aus den ersten Wörtern der Beschreibung (sonst der Name in der Galerie)."""
        words = "-".join(("".join(ch for ch in (item.get("prompt") or "") if ch.isalnum() or ch == " ")).split()[:6])
        return words or Path(item["file"]).stem

    def save_stl(self, item: dict | None):
        """Für den 3D-Druck: nach der gewünschten Höhe fragen, dann als STL speichern (modell3d.to_stl)."""
        glb = self.gallery.model_path(item) if item else None
        if not glb:
            if item:
                dialogs.showerror(tr('3D-Modell'), tr('Die Datei des 3D-Modells fehlt.'))
            return
        cfg = self.app.cfg
        answer = dialogs.askstring(tr('Als STL speichern'), tr(
            'Wie hoch soll das gedruckte Modell werden (in mm)? Breite und Tiefe passen sich an.'),
            f"{cfg.get('stl_height', 100):g}", parent=self.app.root)
        if answer is None:
            return
        try:
            height = float(answer.replace(",", ".").replace("mm", "").strip())
            if not 0 < height <= 10000:
                raise ValueError
        except ValueError:
            dialogs.showerror(tr('Als STL speichern'), tr('Bitte eine Höhe in Millimetern eingeben, z. B. 100.'))
            return
        target = filedialog.asksaveasfilename(
            title=tr('Als STL speichern'), parent=self.app.root, defaultextension=".stl",
            initialfile=self._file_words(item) + ".stl", filetypes=[(tr('STL-Datei (3D-Druck)'), "*.stl")])
        if not target:
            return
        cfg["stl_height"] = height
        self._set_status(tr('Speichere als STL …'))

        def done(size, err):
            if err:
                self._set_status("")
                dialogs.showerror(tr('Als STL speichern'), err)
            else:
                self._set_status(tr('Gespeichert: {0}  ·  {1:.0f} × {2:.0f} × {3:.0f} mm (Breite × Tiefe × Höhe)',
                                    target, *size))

        self.app.background(lambda: modell3d.to_stl(glb, Path(target), height), done)

    def save_glb(self, item: dict | None):
        glb = self.gallery.model_path(item) if item else None
        if not glb:
            if item:
                dialogs.showerror(tr('3D-Modell'), tr('Die Datei des 3D-Modells fehlt.'))
            return
        target = filedialog.asksaveasfilename(
            title=tr('GLB speichern unter…'), parent=self.app.root, defaultextension=".glb",
            initialfile=self._file_words(item) + ".glb", filetypes=[(tr('3D-Modell (GLB)'), "*.glb")])
        if not target:
            return
        try:
            Path(target).write_bytes(glb.read_bytes())
            self._set_status(tr('Gespeichert: {0}', target))
        except OSError as e:
            dialogs.showerror(tr('3D-Modell'), error_text(e))

    def _set_status(self, text: str):
        self.status_var.set(text)

    # ================================================================ Beschreibung verbessern

    def model_changed(self):
        """Sprachmodell geladen/entladen: „Beschreibung verbessern“ geht nur mit einem geladenen Modell."""
        on = self.app.server.is_running() and self.app.server.model is not None and not self.busy
        self.improve_btn.configure(state=tk.NORMAL if on else tk.DISABLED)

    def improve(self):
        text = self.prompt.get("1.0", tk.END).strip()
        if not text:
            self._set_status(tr('Zuerst eine kurze Beschreibung eingeben – das Sprachmodell baut sie dann aus.'))
            self.focus()
            return
        if not self.app.server.is_running() or self.app.busy:
            self._set_status(tr('Dafür muss im Chat ein Sprachmodell geladen sein, das gerade nicht antwortet.'))
            return
        self.improve_btn.configure(state=tk.DISABLED)
        self.gen_btn.configure(state=tk.DISABLED)  # Generieren entlüde das Sprachmodell mitten in der Anfrage
        self._set_status(tr('Das Sprachmodell verbessert die Beschreibung …'))
        url = self.app.server.base_url
        system = {"edit": IMPROVE_EDIT_PROMPT, "3d": IMPROVE_3D_PROMPT}.get(self.mode, IMPROVE_PROMPT)

        def done(result, err):
            self.gen_btn.configure(state=tk.NORMAL)
            self.model_changed()
            if err or not result:
                self._set_status(tr('Verbessern hat nicht geklappt: {0}', err or tr('leere Antwort')))
                return
            self.prompt.edit_separator()
            self.prompt.delete("1.0", tk.END)
            self.prompt.insert("1.0", result)
            self.prompt.edit_separator()
            self._set_status(tr('Beschreibung verbessert (auf Englisch – das versteht das Bildmodell am besten). '
                                'Strg+Z stellt die alte wieder her.'))

        self.app.background(lambda: improve_prompt(url, text, system=system), done)

    # ================================================================ Aktionen

    def open_file(self, item: dict | None):
        if item and item.get("model3d"):
            self.view_3d(item)
        elif item:
            try:
                plattform.open_path(self.gallery.path(item))
            except OSError as e:
                dialogs.showerror(tr('Bilder'), error_text(e))

    def show_in_folder(self, item: dict | None):
        if item:
            plattform.show_in_folder(self.gallery.model_path(item) or self.gallery.path(item))

    def copy(self, item: dict | None):
        if not item:
            return
        path = self.gallery.path(item)
        self.app.background(lambda: images.copy_image(path),
                            lambda _r, err: self._set_status(tr('Kopieren fehlgeschlagen: {0}', err) if err else
                                                             tr('Bild liegt in der Zwischenablage.')))

    def save_as(self, item: dict | None):
        if not item:
            return
        target = filedialog.asksaveasfilename(
            title=tr('Bild speichern'), parent=self.app.root, defaultextension=".png",
            initialfile=self._file_words(item) + ".png", filetypes=[(tr('PNG-Bild'), "*.png")])
        if not target:
            return
        try:
            Path(target).write_bytes(self.gallery.path(item).read_bytes())
            self._set_status(tr('Gespeichert: {0}', target))
        except OSError as e:
            dialogs.showerror(tr('Bilder'), error_text(e))

    def reuse_prompt(self, item: dict | None):
        if item and item.get("prompt"):
            self.prompt.delete("1.0", tk.END)
            self.prompt.insert("1.0", item["prompt"])
            self.focus()

    def delete(self, item: dict | None):
        if not item:
            return
        if item.get("model3d"):
            if not dialogs.askyesno(tr('3D-Modell löschen'), tr('Dieses 3D-Modell samt Vorlagebild in den Papierkorb '
                                                                'verschieben?')):
                return
        elif not dialogs.askyesno(tr('Bild löschen'), tr('Dieses Bild in den Papierkorb verschieben?')):
            return
        try:
            self.gallery.remove(item)
        except OSError as e:
            dialogs.showerror(tr('Bilder'), error_text(e))
            return
        self._thumbs.pop(item["file"], None)
        self._photos.pop(str(self.gallery.path(item)), None)
        if self.shown is item:
            self.show_image(None)
        self.refresh_list()

    # ================================================================ Für die KI (Teamwork: bild_erzeugen / bearbeiten)

    def needs_swap(self, key: str) -> bool:
        """Muss das Sprachmodell für das Bildmodell entladen werden? Ja, wenn eines geladen ist und der freie
        Grafikspeicher nicht fürs Bildmodell reicht (unbekannt, z. B. ohne NVIDIA: sicherheitshalber ja)."""
        chat = self.app.server
        if not (chat.is_running() and chat.model) or self.server.ready_for(key):
            return False
        free = sdcpp.free_vram_mib()
        return free is None or free < sdcpp.need_vram_mib(key)

    def ai_image(self, prompt: str, size: tuple[int, int] | None, count: int, stop: threading.Event,
                 ref: Path | None = None, source: str | None = None, compress=None, phase=None) -> dict:
        """Bild für die KI erzeugen bzw. (mit ref) bearbeiten – im Thread ihrer Antwort, blockiert. Reicht der
        Grafikspeicher nicht für beide Modelle: compress() (Verlauf zusammenfassen – braucht das Sprachmodell noch),
        Sprachmodell entladen, Bild rechnen, Bildmodell entladen und das Sprachmodell mit denselben Einstellungen
        wieder laden – das geschieht auch nach einem Abbruch oder Fehler. phase(name) meldet „unload“, „load“, „run“,
        „reload“. size None = beim Bearbeiten wie die Vorlage. → {"items", "swapped", "compressed", "reload_error"}.
        Fehler als RuntimeError (Texte fürs Modell), Abbruch als sdcpp.Cancelled."""
        phase = phase or (lambda _p: None)
        key = self.model_key()
        m = sdcpp.MODELS[key]
        if not sdcpp.ready(key):
            raise RuntimeError(f"Das Bildmodell {m['name']} ist auf diesem Rechner noch nicht eingerichtet – dein "
                               "Besitzer kann es im Bereich „Bilder“ mit „Modell laden“ herunterladen.")
        if self.busy or self._checking:
            raise RuntimeError("Im Bereich „Bilder“ entsteht gerade schon ein Bild – bitte gleich noch einmal.")
        self.busy = True  # sofort: kein zweites Bild und kein Laden eines Sprachmodells dazwischen (release)
        self.stop_event = stop  # „Stopp“ im Bereich Bilder bricht auch dieses Bild ab
        llm, ui = self.app.server, self.app.ui
        swap = self.needs_swap(key)
        last = llm.last if swap else None
        result = {"items": [], "swapped": swap, "compressed": False, "reload_error": None}
        ui(self._ai_begin)
        try:
            if swap:
                if compress:
                    result["compressed"] = bool(compress())
                if stop.is_set():
                    raise sdcpp.Cancelled(tr('Abgebrochen.'))
                phase("unload")
                ui(self.app._set_status, tr('Sprachmodell entladen – nach dem Bild wird es wieder geladen …'))
                llm.stop()
            refs = None
            if ref:  # Vorlage als PNG (höchstens SOURCE_MAX Pixel lang) – auch für ihre Größe
                images.TEMP_DIR.mkdir(parents=True, exist_ok=True)
                png = images.TEMP_DIR / f"vorlage-ki-{os.getpid()}-{next(self._counter)}.png"
                w, h = images.fit(ref, png, SOURCE_MAX, SOURCE_MAX)
                refs = [png.read_bytes()]
                png.unlink(missing_ok=True)
                size = size or sdcpp.edit_size(w, h, key)
            width, height = size or FORMATS["square"]
            if not self.server.ready_for(key):
                phase("load")
                ui(self._set_phase, "load")
                self.server.start(key, stop)
            phase("run")
            ui(self._set_phase, "run")
            seed, t0 = random.randint(0, 2 ** 31 - 1), time.time()
            pngs = self.server.generate(prompt, width, height, count, seed, stop,
                                        lambda d, t, img: ui(self._on_progress, d, t, img, count), refs=refs)
            info = {"prompt": prompt, "width": width, "height": height, "model": key,
                    "seconds": round((time.time() - t0) / len(pngs), 1)}
            if source:
                info["source"] = source
            items = [self.gallery.add(pngs[i], {**info, "seed": seed + i}) for i in reversed(range(len(pngs)))]
            result["items"] = items[::-1]
        finally:
            if swap:  # Bildmodell weg, Sprachmodell wie vorher wieder laden – auch nach Abbruch oder Fehler
                self.server.stop()
                phase("reload")
                ui(self.app._set_status, tr('Lade {0} wieder …', model_name(last["model"])))
                try:
                    llm.restart(threading.Event(), last)
                    ui(self.app._loaded, last["model"], threading.Event(), None)
                except Exception as e:  # die Antwort scheitert dann beim nächsten Schritt mit dieser Meldung
                    result["reload_error"] = str(e)
                    ui(self.app._set_status, tr('Laden fehlgeschlagen – Details unter Einstellungen → Server-Log'))
            ui(self._ai_end, result["items"])
        return result

    def _ai_begin(self):
        self._set_busy(True)
        self._set_status(tr('Die KI im Teamwork erzeugt ein Bild …'))

    def _ai_end(self, items: list[dict]):
        self._set_busy(False)
        self.update_engine()
        if items:
            if self._listed:
                self.refresh_list()
            self._set_status(tr('Bild für Teamwork fertig – gespeichert in der Galerie.'))
        else:
            self._set_status("")
        self._redraw()

    # ================================================================ Einstellungen

    def build_settings(self, t: ttk.Frame):
        """Reiter „Bilder“ in den Einstellungen."""
        wrap = round(600 * self.s)
        cfg = self.app.cfg
        ttk.Label(t, text=tr('Bilder erzeugen'), style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w",
                                                                         pady=(0, 12))
        self.dl_btn = ttk.Button(t, text=tr('Bild-Engine und Modell herunterladen / aktualisieren'),
                                 command=self.download)
        self.dl_btn.grid(row=1, column=0, columnspan=2, sticky="w")
        self.engine_status = tk.StringVar(value=sdcpp.describe(self.model_key()))
        ttk.Label(t, textvariable=self.engine_status, style="Muted.TLabel", wraplength=wrap).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(2, 12))
        ttk.Label(t, text=tr('Qwen-Image: Rechenmodus')).grid(row=5, column=0, sticky="w", padx=(0, 12))
        labels = compatibility_labels()
        self.compatibility_var = tk.StringVar(value=labels[sdcpp.compatibility_mode(
            cfg.get("image_qwen_compatibility", "auto"))])
        self.compatibility_combo = ttk.Combobox(t, textvariable=self.compatibility_var,
                                                values=list(labels.values()), state="readonly", width=25)
        self.compatibility_combo.grid(row=5, column=1, sticky="w")
        self.app.theme.register_combo(self.compatibility_combo)
        ttk.Label(t, text=tr('Bei Farbrauschen „Kompatibel“ wählen. Änderungen gelten ab dem nächsten Bildauftrag.'),
                  style="Muted.TLabel", wraplength=wrap).grid(row=6, column=0, columnspan=2, sticky="w", pady=(2, 0))
        ttk.Separator(t).grid(row=7, column=0, columnspan=2, sticky="ew", pady=14)
        self.ask_var = tk.BooleanVar(value=cfg.get("image_unload") != "auto")
        ttk.Checkbutton(t, text=tr('Fragen, bevor das Sprachmodell für ein Bild entladen wird'),
                        variable=self.ask_var).grid(row=8, column=0, columnspan=2, sticky="w")
        ttk.Label(t, text=tr(
            'Sprach- und Bildmodell passen oft nicht gleichzeitig in den Grafikspeicher. Ist beim Erzeugen zu wenig '
            'frei, wird das Sprachmodell entladen; lädst du im Chat ein Sprachmodell, gibt das Bildmodell seinen '
            'Speicher frei.'), style="Muted.TLabel", wraplength=wrap).grid(row=9, column=0, columnspan=2, sticky="w",
                                                                          pady=(2, 0))
        ttk.Separator(t).grid(row=10, column=0, columnspan=2, sticky="ew", pady=14)
        ttk.Label(t, text=tr('3D-Modelle'), style="Title.TLabel").grid(row=11, column=0, columnspan=2, sticky="w",
                                                                    pady=(0, 8))
        self.dl3d_btn = ttk.Button(t, text=tr('3D-Engine und Modell herunterladen / aktualisieren'),
                                   command=self.download_3d)
        self.dl3d_btn.grid(row=12, column=0, columnspan=2, sticky="w")
        self.engine3d_status = tk.StringVar(value=trellis.describe(self.variant_key()))
        ttk.Label(t, textvariable=self.engine3d_status, style="Muted.TLabel", wraplength=wrap).grid(
            row=13, column=0, columnspan=2, sticky="w", pady=(2, 8))
        ttk.Separator(t).grid(row=15, column=0, columnspan=2, sticky="ew", pady=14)
        ttk.Button(t, text=tr('Bilderordner öffnen'), command=self.open_folder, **icons.opts("folder")).grid(
            row=16, column=0, columnspan=2, sticky="w")
        t.columnconfigure(1, weight=1)

    def settings(self) -> dict:
        """Für save_config: was im Reiter eingestellt ist."""
        out = {"image_format": self._format(), "image_count": int(self.count_choice.get() or 1),
               "model3d_res": self._res(), "model3d_from": self.from_var.get()}
        if hasattr(self, "ask_var"):
            out["image_unload"] = "ask" if self.ask_var.get() else "auto"
        if hasattr(self, "compatibility_var"):
            out["image_qwen_compatibility"] = next((key for key, label in compatibility_labels().items()
                                                    if label == self.compatibility_var.get()), "auto")
        return out

    def open_folder(self):
        self.gallery.dir.mkdir(parents=True, exist_ok=True)
        try:
            plattform.open_path(self.gallery.dir)
        except OSError as e:
            dialogs.showerror(tr('Bilder'), error_text(e))

    def download(self, confirm: bool = True):
        """Einstellungen: Bild-Engine (neueste Version) und Dateien des gewählten Modells herunterladen."""
        key = self.model_key()

        def offer(plan):
            parts = []
            if plan["program"]:
                parts.append(f"stable-diffusion.cpp {plan['tag']} ({plan['kind']}): "
                             f"{sum(x[2] for x in plan['program']) / 1024 ** 2:.0f} MB")
            if plan.get("runtime"):
                parts.append(tr('AMD-ROCm-Laufzeit {0} für deine Grafikkarte: {1:.1f} GB',
                                plan["runtime"]["version"], plan["runtime"]["size"] / 1e9))
            for name, _url, size, _dest in plan["weights"]:
                parts.append(tr('Modelldatei {0}: {1:.0f} MB', name, size / 1024 ** 2))
            if not parts:
                self.engine_status.set(tr('Alles aktuell: {0}', sdcpp.describe(key)))
                return None
            return (tr('Bild-Engine herunterladen'),
                    (tr('Grafikkarte: {0}\n', plan['gpu']) if plan['gpu'] else "") + "\n".join(parts)
                    + tr('\n\nZusammen {0:.1f} GB – jetzt herunterladen?', plan['size'] / 1024 ** 3), tr('Bilder'))

        def finished(_plan, _result):
            if _plan["program"] or _plan.get("runtime"):
                self.server.require_reload()
            self.engine_status.set(tr('Installiert: {0}', sdcpp.describe(key)))
            self.update_engine()
            self._redraw()

        self.app._download_flow(self.dl_btn, self.engine_status, lambda: sdcpp.plan(key), offer, sdcpp.install,
                                finished, confirm)

    def download_3d(self, confirm: bool = True):
        """Einstellungen: 3D-Engine (neueste Version) und Dateien der gewählten Variante herunterladen."""
        variant = self.variant_key()

        def offer(plan):
            parts = []
            if plan["program"]:
                parts.append(f"trellis.cpp {plan['tag']} ({plan['kind']}): "
                             f"{sum(x[2] for x in plan['program']) / 1024 ** 2:.0f} MB")
            for name, _url, size, _dest in plan["weights"]:
                parts.append(tr('Modelldatei {0}: {1:.0f} MB', name, size / 1024 ** 2))
            if not parts:
                self.engine3d_status.set(tr('Alles aktuell: {0}', trellis.describe(variant)))
                return None
            return (tr('3D-Engine herunterladen'),
                    (tr('Grafikkarte: {0}\n', plan['gpu']) if plan['gpu'] else "") + "\n".join(parts)
                    + tr('\n\nZusammen {0:.1f} GB – jetzt herunterladen?', plan['size'] / 1024 ** 3)
                    + "\n\n" + trellis.LICENSE, tr('3D-Modelle'))

        def finished(_plan, _result):
            self.engine3d_status.set(tr('Installiert: {0}', trellis.describe(variant)))
            self.update_engine()
            self._redraw()

        self.app._download_flow(self.dl3d_btn, self.engine3d_status, lambda: trellis.plan(variant), offer,
                                trellis.install, finished, confirm)

    # ================================================================ Grafikspeicher / Ende

    def release(self) -> bool:
        """Vor dem Laden eines Sprachmodells: False, solange ein Bild entsteht (dann nicht laden). Sonst wird das
        Bildmodell beendet – das Laden ruft dafür stop_server() im Hintergrund auf, bevor llama-server startet."""
        return not self.busy

    def stop_server(self):
        if self.server.is_running():
            self.server.stop()
            self.app.ui(self.update_engine)

    def shutdown(self):
        self.stop_event.set()
        self.server.stop()
