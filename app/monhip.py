"""Monhip: lokale GGUF-Modelle laden, chatten und als Agent arbeiten lassen (Aufbau: siehe CLAUDE.md)."""

from i18n import LANGUAGES as UI_LANGUAGES, error_text, get_language, initialize, resolve_language, tr

import json
import os
import queue
import secrets
import threading
import tkinter as tk
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter import font as tkfont

initialize(Path(__file__).resolve().parent.parent / "config.json")

import chats
import context
import dialogs
import documents
import downloads
import experte
import filedrop
import icons
import images
import llamacpp
import memory
import projekt
import prozesse
import reminders
import room as room_net
import speech
from agent import Agent, date_line, describe_call, format_args, result_ok, run_conversation, time_label, tool_budget
from backend import LlamaServer, find_mmproj, find_models, thinking_title
from chatview import ChatView
from roomui import RoomMode
from themes import FAMILY, THEMES, ThemeManager, label_to_key, mix_hex
from widgets import ModeSwitch, PopupMenu, rounded, scrolled

VERSION = "1.4.3"  # auf GitHub als Release „v1.4.3“ (danach richtet sich das Update im Installer)
TIME_FMT = "%Y-%m-%d %H:%M"  # „_time“ einer Nutzernachricht: ihre Uhrzeit fürs Modell (_api_message)
APP_DIR = Path(__file__).resolve().parent.parent  # Code in app/, Daten daneben
CONFIG_FILE = APP_DIR / "config.json"
MODEL_DIR = APP_DIR / "modelle"  # wird immer durchsucht, Ziel für Downloads
ICON_FILE = Path(__file__).resolve().with_name("monhip.ico")
MAX_ATTACHMENTS = 10

DEFAULTS = {
    "ui_language": get_language(),
    "folders": [],                 # weitere Modellordner
    "extra_models": [],
    "server_exe": "",
    "ctx": 16384,                  # Kontext in Tokens (Einstellungen → Laden)
    "ngl": "auto",
    "temperature": 0.7,
    "max_tokens": 4096,
    "extra_args": "",
    "vision": True,                # mmproj neben dem Modell mitladen
    "image_tokens": 2048,
    "system_prompt": "Du bist ein hilfreicher Assistent. Antworte auf Deutsch.",
    "think_titles": True,
    "auto_compress": True,         # ältere Unterhaltung zusammenfassen, wenn der Kontext knapp wird
    "agent_enabled": False,        # Dateien & Ordner
    "agent_commands": True,        # PowerShell & Python
    "git_enabled": False,          # Git & GitHub (nur zusammen mit Dateien & Ordner)
    "agent_workspace": str(Path.home() / "Desktop" / "Agent-Arbeitsordner"),
    "agent_folders": [],
    "agent_confirm": True,
    "web_enabled": True,
    "brave_key": "",
    "memory_enabled": True,
    "reminders_enabled": True,
    "screenshots_enabled": False,
    "speech_model": speech.DEFAULT_MODEL,
    "speech_language": "de",
    "last_model": "",
    "theme": "dark",
    # Teamwork
    "mode": "chat",
    "room_name": "",
    "room_ai": "",
    "room_mode": "limited",        # Erlaubnis der eigenen KI im Teamwork: all | limited | strict (roomui.ROOM_MODES)
    "client_id": "",               # Kennung dieser Installation (Wiederbeitritt nach Neustart)
}


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # tiefe Kopie
    try:
        cfg.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    cfg["ui_language"] = resolve_language(cfg.get("ui_language"))
    # Alte Einträge aus der Zeit mit LM Studio verwerfen
    if ".lmstudio" in cfg["server_exe"].lower():
        cfg["server_exe"] = ""
    cfg["folders"] = [f for f in cfg["folders"] if ".lmstudio" not in f.lower() and not same_path(f, MODEL_DIR)]
    cfg["extra_models"] = [f for f in cfg["extra_models"] if ".lmstudio" not in f.lower()]
    cfg.pop("show_thinking", None)
    cfg.pop("room_tools", None)  # bis 28.10.2026: Häkchen je Werkzeug – die KI im Raum hat jetzt immer alle (room_mode)
    if cfg.get("room_mode") not in ("all", "limited", "strict"):
        cfg["room_mode"] = DEFAULTS["room_mode"]
    try:  # „auto“ (bis 27.10.2026 Standard) gibt es nicht mehr → Standardwert
        cfg["ctx"] = int(cfg["ctx"])
    except (TypeError, ValueError):
        cfg["ctx"] = DEFAULTS["ctx"]
    return cfg


def same_path(a, b) -> bool:
    return Path(a) == Path(b)  # unter Windows ohne Groß-/Kleinschreibung, / und \ gleich


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.cfg = load_config()
        if not self.cfg["client_id"]:
            self.cfg["client_id"] = secrets.token_hex(8)
        self.app_dir = APP_DIR
        self.mode = None                 # "chat" | "room", gesetzt durch set_mode()
        self._chat_title = tr('Neuer Chat')
        self.events: queue.Queue = queue.Queue()
        self.server = LlamaServer(lambda t: self.events.put(("log", t)))
        self.servers = llamacpp.find_llama_servers()
        self._downloads: dict[str, threading.Event] = {}  # laufende Downloads → Abbruch-Signal
        self.recorder = speech.Recorder()
        self._transcribing = False
        self.background(images.cleanup_temp)
        self.models: list[Path] = []
        self.sel_model: Path | None = None
        self.history: list[dict] = []
        self.chat_data: dict | None = None  # None = neuer, noch ungespeicherter Chat
        self.stop_event = threading.Event()
        self.load_cancel = threading.Event()
        self.busy = False
        self.stream_q: deque = deque()   # Chat-Ereignisse in Reihenfolge (Text wird daraus gleichmäßig „getippt“)
        self.turn: dict = {}             # Zustand der laufenden Antwort
        self._draining = False
        self.attachments: list[dict] = []
        self.quote: str | None = None    # „Antworten“ auf eine markierte Stelle
        self.expert_job: experte.Job | None = None   # laufende Auswertung (Experten-Modus, höchstens eine)
        self._expert_job_chat: str | None = None      # … gestartet für diesen Chat
        self._expert_text = ""                        # Fortschritt der laufenden Auswertung
        self._expert_paused = False                   # … hält gerade an („Pausieren“ ist angekommen)
        self._ctx: tuple[int | None, bool] = (None, False)  # Kontextanzeige: (belegte Tokens, genau gemessen?)
        self._meter_gen = 0              # spätere Schätzungen überschreiben keine neueren Messungen
        self._meter_cache: dict = {}
        self._hover = None
        self._pointer = None             # Chat unter dem Mauszeiger
        self._menu_item = None           # Chat mit offenem Menü
        self._dots: set = set()          # Chats, bei denen „•••“ steht
        self._ctx_item = None
        self._tree_rows = None
        self.sources_win = None
        self.dl_win = None

        try:
            root.attributes("-alpha", 0.0)  # unsichtbar aufbauen, fertig gefärbt einblenden
        except tk.TclError:
            pass
        root.title("Monhip")
        try:
            root.iconbitmap(default=str(ICON_FILE))  # gilt auch für alle Dialoge
        except tk.TclError:
            pass
        root.minsize(900, 600)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.theme = ThemeManager(root)
        self.ui_scale = max(1.0, float(root.tk.call("tk", "scaling")) / 1.333)
        # Startgröße: Platz für die ganze Teamwork-Seitenleiste – höchstens so groß wie der Bildschirm (Taskleiste)
        root.geometry(f"{min(round(1320 * self.ui_scale), root.winfo_screenwidth() - 40)}x"
                      f"{min(round(980 * self.ui_scale), root.winfo_screenheight() - 90)}")
        dialogs.setup(root, self.theme, self.ui_scale)
        self._chip_fonts = (tkfont.Font(font=(FAMILY, 9)), tkfont.Font(font=(FAMILY, 8)))

        self._build_sidebar()
        self._build_main()
        self._build_settings()
        self.set_theme(self.cfg.get("theme", "dark"), save=False)
        self.room = RoomMode(self, self.room_side, self.room_view)
        self.refresh_models()
        self.refresh_chat_list()
        self.new_chat()
        self.set_mode(self.cfg.get("mode", "chat"))
        root.bind("<Control-n>", lambda e: self.new_chat())
        root.after(300, lambda: filedrop.enable_drop(root, self.add_attachments))
        self.root.after(50, self._poll_events)
        self.root.after(3000, self._check_reminders)  # auch verpasste vom letzten Mal
        self.theme.present(root, fade_ms=220)

    # ================================================================ Threads

    def ui(self, fn, *args):
        """fn(*args) im Tk-Thread ausführen – von Hintergrund-Threads aus der einzige Weg zur Oberfläche."""
        self.events.put(("call", (fn, args)))

    def background(self, work, done=None):
        """work() im Hintergrund; danach done(ergebnis, fehlertext|None) im Tk-Thread."""
        def run():
            try:
                result, err = work(), None
            except Exception as e:
                result, err = None, error_text(e) or type(e).__name__
            if done:
                self.ui(done, result, err)
        threading.Thread(target=run, daemon=True).start()

    # ================================================================ Oberfläche: Seitenleiste

    def _build_sidebar(self):
        side = ttk.Frame(self.root, style="Sidebar.TFrame", width=round(260 * self.ui_scale))
        side.pack(side=tk.LEFT, fill=tk.Y)
        side.pack_propagate(False)

        # Moduswahl: Chat | Teamwork
        modes = ttk.Frame(side, style="Sidebar.TFrame", padding=(8, 10, 8, 6))
        modes.pack(side=tk.TOP, fill=tk.X)
        self.mode_switch = ModeSwitch(modes, [("chat", "Chat"), ("room", "Teamwork")], self.set_mode,
                                      self.ui_scale)
        self.mode_switch.pack(fill=tk.X)

        bottom = ttk.Frame(side, style="Sidebar.TFrame", padding=(8, 6, 8, 10))
        bottom.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Button(bottom, text=tr('Einstellungen'), style="Sidebar.TButton", **icons.opts("settings"),
                   command=self.open_settings).pack(fill=tk.X)

        # Chatliste und Raum-Panel liegen fertig übereinander; set_mode() holt eins nach vorn (flackert nicht)
        body = ttk.Frame(side, style="Sidebar.TFrame")
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        self.chat_side = ttk.Frame(body, style="Sidebar.TFrame")
        self.room_side = ttk.Frame(body, style="Sidebar.TFrame")
        self.chat_side.grid(row=0, column=0, sticky="nsew")
        self.room_side.grid(row=0, column=0, sticky="nsew")

        top = ttk.Frame(self.chat_side, style="Sidebar.TFrame", padding=(8, 6, 8, 6))
        top.pack(side=tk.TOP, fill=tk.X)
        ttk.Button(top, text=tr('Neuer Chat'), style="Sidebar.TButton", command=self.new_chat, **icons.opts("add")).pack(fill=tk.X)

        lf = ttk.Frame(self.chat_side, style="Sidebar.TFrame", padding=(8, 0, 2, 0))
        lf.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        # Spalte „menu“: „•••“ öffnet das Menü
        tree = ttk.Treeview(lf, columns=("menu",), show="tree", selectmode="browse", style="Sidebar.Treeview")
        tree.column("#0", width=160, stretch=True)
        tree.column("menu", width=round(30 * self.ui_scale), minwidth=round(30 * self.ui_scale), stretch=False,
                    anchor="center")
        sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=tree.yview, style="Sidebar.Vertical.TScrollbar")
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree.tag_configure("group", font=(FAMILY, 8, "bold"))
        tree.bind("<<TreeviewSelect>>", self._on_chat_select)
        tree.bind("<Motion>", self._on_tree_hover)
        tree.bind("<Leave>", self._on_tree_leave)
        tree.bind("<Button-1>", self._on_tree_click)
        tree.bind("<Button-3>", self._on_tree_menu)
        tree.bind("<F2>", lambda e: self.rename_chat(self._current_tree_chat()))
        tree.bind("<Delete>", lambda e: self.delete_chat(self._current_tree_chat()))
        self.chat_tree = tree

        menu = PopupMenu(self.root, self.ui_scale)
        menu.add_command(label=tr('Umbenennen…'), command=lambda: self.rename_chat(self._ctx_item))
        menu.add_command(label=tr('Löschen'), command=lambda: self.delete_chat(self._ctx_item))
        self.theme.register_menu(menu)
        self.chat_menu = menu

    # ================================================================ Oberfläche: Chatbereich

    def _build_main(self):
        ttk.Separator(self.root, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y)
        main = ttk.Frame(self.root)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ---- Kopfzeile: Chat-Titel links, Modell rechts
        top = ttk.Frame(main, style="Top.TFrame", padding=(18, 10, 14, 8))
        top.pack(side=tk.TOP, fill=tk.X)
        self.title_var = tk.StringVar(value=tr('Neuer Chat'))
        # width=1 + Gewicht: langer Titel wird abgeschnitten, statt die Modellauswahl zu verdrängen
        ttk.Label(top, textvariable=self.title_var, style="Title.TLabel", width=1).grid(
            row=0, column=0, rowspan=2, sticky="ew", padx=(0, 12))
        self.model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(top, textvariable=self.model_var, state="readonly", width=34)
        self.model_combo.grid(row=0, column=2, sticky="e")
        self.model_combo.bind("<<ComboboxSelected>>", lambda e: self._select_model(self.model_combo.current()))
        self.theme.register_combo(self.model_combo)
        self.load_btn = ttk.Button(top, text=tr('Modell laden'), style="Accent.TButton", command=self.load_model,
                                   **icons.opts("play", "accent_fg"))
        self.load_btn.grid(row=0, column=3, padx=(6, 0))
        ttk.Button(top, width=3, command=self.unload_model, **icons.only("stop")).grid(row=0, column=4, padx=(4, 0))
        self.status_var = tk.StringVar(value=tr('Kein Modell geladen'))
        self._status_labels = [ttk.Label(top, textvariable=self.status_var, style="Muted.TLabel")]
        self._status_labels[0].grid(row=1, column=2, columnspan=3, sticky="e", pady=(3, 0))
        top.columnconfigure(0, weight=1)
        ttk.Separator(main).pack(side=tk.TOP, fill=tk.X)

        # ---- Eingabe (zuerst packen, damit sie beim Verkleinern sichtbar bleibt)
        meter = ttk.Frame(main, padding=(18, 0, 18, 6))  # Kontextanzeige ganz unten, rechts
        meter.pack(side=tk.BOTTOM, fill=tk.X)
        self._meter = meter  # feste Höhe: _fix_meter_height
        self.ctx_bar = tk.Canvas(meter, width=round(64 * self.ui_scale), height=max(4, round(5 * self.ui_scale)),
                                 highlightthickness=0, borderwidth=0)
        self.ctx_bar.pack(side=tk.RIGHT, padx=(8, 0))
        self.ctx_text = tk.StringVar()
        ttk.Label(meter, textvariable=self.ctx_text, style="Muted.TLabel", font=(FAMILY, 8)).pack(side=tk.RIGHT)
        # Experten-Modus (nur im Chat): Häkchen, Fortschritt der Auswertung, „Pausieren · Stoppen“ bzw. „Fortsetzen“
        self.expert_bar = ttk.Frame(meter)
        self.expert_bar.pack(side=tk.LEFT)
        self.expert_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.expert_bar, text=tr('Experten-Modus'), variable=self.expert_var,
                        command=self._toggle_expert).pack(side=tk.LEFT)
        self.expert_status = tk.StringVar()
        ttk.Label(self.expert_bar, textvariable=self.expert_status, style="Muted.TLabel", font=(FAMILY, 8)).pack(
            side=tk.LEFT, padx=(10, 0))
        self.expert_links = ttk.Frame(self.expert_bar)
        self.expert_links.pack(side=tk.LEFT)
        inp = ttk.Frame(main, padding=(18, 6, 18, 4))
        inp.pack(side=tk.BOTTOM, fill=tk.X)
        self._inp_frame = inp
        self.send_btn = ttk.Button(inp, text=tr('Senden'), style="Accent.TButton", width=8, command=self._send_or_stop)
        self.send_btn.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        ttk.Button(inp, style="Attach.TButton", width=2, command=self.pick_attachments, **icons.only("add", size=18)).pack(
            side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        self.mic_btn = ttk.Button(inp, style="Attach.TButton", width=2, command=self.toggle_dictation,
                                  **icons.only("mic", size=18))
        self.mic_btn.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        field = ttk.Frame(inp, style="Input.TFrame")  # zeichnet Fläche und runden Rand um das Textfeld
        field.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.input = tk.Text(field, height=2, width=1, wrap=tk.WORD, font=(FAMILY, 11), padx=8, pady=4)
        self.input.pack(fill=tk.BOTH, expand=True)
        self.input.bind("<Return>", self._on_enter)
        self.input.bind("<<Paste>>", self._on_paste)
        self.theme.register_field(field, self.input)
        # Anhänge/Zitat – nur sichtbar, wenn etwas da ist
        self.attach_bar = ttk.Frame(main, padding=(18, 8, 18, 0))

        # ---- Verlauf: normaler Chat und Gruppenchat übereinander, set_mode() holt einen nach vorn
        box = ttk.Frame(main)
        box.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.chat_frame, self.chat, self.view = self._make_chat_view(box)
        self.room_frame, self.room_chat, self.room_view = self._make_chat_view(box)
        self.view.on_quote = self.set_quote  # „Antworten“ nur im normalen Chat
        self.chat_frame.grid(row=0, column=0, sticky="nsew")
        self.room_frame.grid(row=0, column=0, sticky="nsew")

    def _make_chat_view(self, parent):
        # tk.Frame statt ttk (wie widgets.scrolled): ChatView setzt das Textfeld mit fester Breite mittig hinein
        # (fixed_column) und färbt den Rand daneben wie den Verlauf
        frame = tk.Frame(parent, borderwidth=0, highlightthickness=0)
        # randlos auch in „Windows-Standard“ (stellt die Originalwerte wieder her) – sonst umrahmt eine Linie die Spalte
        text = tk.Text(frame, wrap=tk.WORD, font=(FAMILY, 11), pady=14, width=1, height=1, borderwidth=0,
                       highlightthickness=0, relief=tk.FLAT)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.theme.register_text(text, role="plain")
        view = ChatView(text, self.ui_scale, register_menu=self.theme.register_menu)
        view.attach_scrollbar(sb)
        view.fixed_column()
        return frame, text, view

    # ================================================================ Modus: Chat | Teamwork

    def set_mode(self, mode: str):
        mode = mode if mode in ("chat", "room") else "chat"
        if mode == self.mode:
            return
        first = self.mode is None
        self.mode = self.cfg["mode"] = mode
        room = mode == "room"
        self.mode_switch.select(mode, animate=not first)
        self.room.mentions.hide()
        self._draw_meter()  # im Teamwork: Kontext der eigenen KI
        if room:
            self.room.estimate(50)  # geschätzt wird nur im sichtbaren Bereich
        self._update_expert_row()
        (self.room_view if room else self.view).set_active(True)  # holt eine verpasste Größenänderung nach
        (self.view if room else self.room_view).set_active(False)
        (self.room_side if room else self.chat_side).tkraise()
        (self.room_frame if room else self.chat_frame).tkraise()
        self._send_label(self.busy and not room)
        self.update_title()
        self.input.focus_set()

    def update_title(self):
        if self.mode == "room":
            info = self.room.info
            title = f"Teamwork  ·  {info['room']}" if info else "Teamwork"
        else:
            title = self._chat_title
        self.title_var.set(title if len(title) <= 60 else title[:59] + "…")

    def theme_chat(self) -> dict:
        """Chatfarben des aktuellen Designs (für RoomMode, z. B. Namensfarben)."""
        return THEMES[self.theme.key]["chat"]

    # ================================================================ Oberfläche: Einstellungen

    def _build_settings(self):
        win = tk.Toplevel(self.root)
        win.withdraw()
        win.title(tr('Einstellungen'))
        w, h = round(840 * self.ui_scale), round(600 * self.ui_scale)
        win.geometry(f"{w}x{h}")
        win.minsize(560, 460)
        win.transient(self.root)
        win.protocol("WM_DELETE_WINDOW", self.close_settings)
        win.bind("<Escape>", lambda e: self.close_settings())
        self.theme.register_window(win)
        self.settings_win = win
        self._settings_placed = False

        outer = ttk.Frame(win, padding=12)
        outer.pack(fill=tk.BOTH, expand=True)
        bar = ttk.Frame(outer)
        bar.pack(side=tk.BOTTOM, fill=tk.X, pady=(10, 0))
        ttk.Button(bar, text=tr('Schließen'), command=self.close_settings).pack(side=tk.RIGHT)
        ttk.Label(bar, text=tr('Monhip v{0}  ·  Änderungen werden automatisch gespeichert.', VERSION),
                  style="Muted.TLabel").pack(side=tk.LEFT)
        nb = ttk.Notebook(outer)
        nb.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.settings_nb = nb
        tabs = {}
        for key, title in [("models", tr('Modelle')), ("load", tr('Laden')), ("tools", tr('Werkzeuge')), ("memory", tr('Gedächtnis')),
                           ("speech", tr('Sprache')), ("prompt", tr('System-Prompt')), ("look", tr('Darstellung')),
                           ("log", tr('Server-Log'))]:
            tabs[key] = ttk.Frame(nb, padding=14)
            nb.add(tabs[key], text=title)
        self.settings_tabs = tabs

        # ---- Modelle
        t = tabs["models"]
        self.models_info = tk.StringVar()
        ttk.Label(t, textvariable=self.models_info).pack(anchor="w")
        lf, self.model_list = self._listbox(t, font=(FAMILY, 10))
        lf.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.model_list.bind("<<ListboxSelect>>", self._on_model_list_select)
        self.model_list.bind("<Double-Button-1>",
                             lambda e: self.load_model() if self.models else self.open_model_dir())
        bf = ttk.Frame(t)
        bf.pack(fill=tk.X, pady=(8, 0))
        for i, (txt, cmd) in enumerate([(tr('Aktualisieren'), self.refresh_models),
                                        (tr('Modellordner öffnen'), self.open_model_dir),
                                        (tr('Weitere Ordner…'), self.open_sources),
                                        (tr('Datei öffnen…'), lambda: self.add_file(self.settings_win)),
                                        (tr('Herunterladen…'), self.open_download)]):
            ttk.Button(bf, text=txt, command=cmd).grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0))
            bf.columnconfigure(i, weight=1)
        lb = ttk.Frame(t)
        lb.pack(fill=tk.X, pady=(12, 0))
        self.load_btn2 = ttk.Button(lb, text=tr('Modell laden'), style="Accent.TButton", command=self.load_model,
                                    **icons.opts("play", "accent_fg"))
        self.load_btn2.pack(side=tk.LEFT)
        ttk.Button(lb, text=tr('Entladen'), command=self.unload_model, **icons.opts("stop")).pack(
            side=tk.LEFT, padx=(4, 0))
        self._status_labels.append(ttk.Label(lb, textvariable=self.status_var, style="Muted.TLabel"))
        self._status_labels[-1].pack(side=tk.LEFT, padx=(10, 0))

        # ---- Laden
        t = tabs["load"]
        self.server_var = tk.StringVar()
        labels = [s["label"] for s in self.servers] + [tr('Eigene llama-server.exe…')]
        ttk.Label(t, text="Backend").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=3)
        self.server_combo = ttk.Combobox(t, textvariable=self.server_var, values=labels, state="readonly")
        self.server_combo.grid(row=0, column=1, sticky="ew", pady=3)
        self.server_combo.bind("<<ComboboxSelected>>", self._on_server_selected)
        self.theme.register_combo(self.server_combo)
        if self.cfg["server_exe"]:
            match = [s["label"] for s in self.servers if s["exe"] == self.cfg["server_exe"]]
            self.server_var.set(match[0] if match else self.cfg["server_exe"])
        elif self.servers:
            self.server_var.set(self.servers[0]["label"])
        self.srv_btn = ttk.Button(t, text=tr('llama.cpp herunterladen / aktualisieren'), command=self.download_server)
        self.srv_btn.grid(row=1, column=1, sticky="w", pady=(4, 0))
        self.srv_status = tk.StringVar(value=tr('Neueste Version von github.com/ggml-org/llama.cpp, passend zur Grafikkarte')
                                       if self.servers else tr('Noch nicht installiert – wird zum Laden von Modellen gebraucht'))
        ttk.Label(t, textvariable=self.srv_status, style="Muted.TLabel", wraplength=round(480 * self.ui_scale)
                  ).grid(row=2, column=1, sticky="w", pady=(0, 8))

        self.ctx_var = tk.StringVar(value=str(self.cfg["ctx"]))
        self.ngl_var = tk.StringVar(value=self.cfg["ngl"])
        self.extra_var = tk.StringVar(value=self.cfg["extra_args"])
        self.temp_var = tk.StringVar(value=str(self.cfg["temperature"]))
        self.maxtok_var = tk.StringVar(value=str(self.cfg["max_tokens"]))
        self.vision_var = tk.BooleanVar(value=self.cfg["vision"])
        self.imgtok_var = tk.StringVar(value=str(self.cfg["image_tokens"]))
        rows = [(tr('Kontext (Tokens)'), self.ctx_var, tr('Mindestens 16384 für Websuche')),
                (tr('GPU-Layers'), self.ngl_var, tr('„auto“ passt das Modell an den Grafikspeicher an')),
                (tr('Extra-Argumente'), self.extra_var, tr('z. B. --n-cpu-moe 10 oder -fa on')),
                (tr('Temperatur'), self.temp_var, tr('niedriger = sachlicher, höher = kreativer')),
                (tr('Max. Antwort-Tokens'), self.maxtok_var, ""),
                (tr('Max. Tokens pro Bild'), self.imgtok_var, tr('mehr = Details und kleine Schrift besser erkennbar, braucht aber mehr Kontext'))]
        r = 3
        for txt, var, hint in rows:
            ttk.Label(t, text=txt).grid(row=r, column=0, sticky="w", padx=(0, 12), pady=(3, 0))
            ttk.Entry(t, textvariable=var).grid(row=r, column=1, sticky="ew", pady=(3, 0))
            r += 1
            if hint:
                ttk.Label(t, text=hint, style="Muted.TLabel").grid(row=r, column=1, sticky="w")
                r += 1
        ttk.Checkbutton(t, text=tr('Bildverständnis laden (mmproj-Datei im Ordner des Modells, ca. 1 GB Grafikspeicher)'),
                        variable=self.vision_var).grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.compress_var = tk.BooleanVar(value=self.cfg["auto_compress"])
        ttk.Checkbutton(t, text=tr('Ältere Unterhaltung automatisch zusammenfassen, wenn der Kontext knapp wird'),
                        variable=self.compress_var).grid(row=r + 1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        t.columnconfigure(1, weight=1)

        # ---- Werkzeuge
        t = tabs["tools"]
        self.web_var = tk.BooleanVar(value=self.cfg["web_enabled"])
        self.brave_var = tk.StringVar(value=self.cfg["brave_key"])
        self.agent_var = tk.BooleanVar(value=self.cfg["agent_enabled"])
        self.cmd_var = tk.BooleanVar(value=self.cfg["agent_commands"])
        self.git_var = tk.BooleanVar(value=self.cfg["git_enabled"])
        self.confirm_var = tk.BooleanVar(value=self.cfg["agent_confirm"])
        self.ws_var = tk.StringVar(value=self.cfg["agent_workspace"])
        self.extra_folders: list[str] = list(self.cfg["agent_folders"])
        ttk.Checkbutton(t, text=tr('Internetzugriff (Websuche & Seiten lesen)'), variable=self.web_var).grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(t, text=tr('Brave-API-Key (optional, falls DuckDuckGo blockiert)'), style="Muted.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(6, 2))
        ttk.Entry(t, textvariable=self.brave_var, show="•").grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Separator(t).grid(row=3, column=0, columnspan=2, sticky="ew", pady=12)
        self.screen_var = tk.BooleanVar(value=self.cfg["screenshots_enabled"])
        ttk.Checkbutton(t, text=tr(
            'Dateien & Ordner – lesen, schreiben, Bilder ansehen, Word/Excel/PowerPoint, Programmierprojekte'), variable=self.agent_var).grid(row=4, column=0, columnspan=2,
                                                                                     sticky="w")
        ttk.Checkbutton(t, text=tr('Befehle & Programme ausführen (PowerShell, Python)'), variable=self.cmd_var).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Checkbutton(t, text=tr(
            'Git & GitHub – Commits, Branches, Push und Pull Requests (nur mit Dateien & Ordner; Push fragt jedes Mal)'),
            variable=self.git_var).grid(row=6, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Checkbutton(t, text=tr(
            'Bildschirmfotos – das Modell darf deinen Bildschirm ansehen (fragt jedes Mal, nur mit Bildverständnis)'), variable=self.screen_var).grid(
            row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Checkbutton(t, text=tr('Jede Aktion bestätigen (empfohlen)'), variable=self.confirm_var).grid(
            row=8, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Label(t, text=tr(
            'Freigegebene Ordner – nur hier darf das Modell lesen und schreiben. ★ = Arbeitsordner (Standard für '
            'neue Dateien):'), style="Muted.TLabel",
                  wraplength=round(600 * self.ui_scale)).grid(row=9, column=0, columnspan=2, sticky="w", pady=(10, 2))
        lf, self.folder_list = self._listbox(t, height=5)
        lf.grid(row=10, column=0, columnspan=2, sticky="nsew")
        self.folder_list.bind("<Delete>", lambda e: self._remove_folder())
        bf = ttk.Frame(t)
        bf.grid(row=11, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(bf, text=tr('Ordner hinzufügen…'), command=self._add_folder).pack(side=tk.LEFT)
        ttk.Button(bf, text=tr('Als Arbeitsordner'), command=self._main_folder, **icons.opts("star")).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(bf, text=tr('Entfernen'), command=self._remove_folder).pack(side=tk.LEFT, padx=(4, 0))
        t.columnconfigure(0, weight=1)
        t.rowconfigure(10, weight=1)
        self._fill_folders()

        # ---- Gedächtnis und Erinnerungen
        t = tabs["memory"]
        self.memory_var = tk.BooleanVar(value=self.cfg["memory_enabled"])
        self.reminder_var = tk.BooleanVar(value=self.cfg["reminders_enabled"])
        wrap = round(600 * self.ui_scale)
        ttk.Checkbutton(t, text=tr('Gedächtnis – das Modell darf sich Dinge über alle Chats hinweg merken'),
                        variable=self.memory_var).grid(row=0, column=0, sticky="w")
        ttk.Label(t, text=tr(
            'Zum Beispiel „Merk dir, dass ich kurze Antworten mag“. Jeder neue Chat bekommt das Gemerkte mit.'), style="Muted.TLabel", wraplength=wrap).grid(row=1, column=0, sticky="w",
                                                                                     pady=(2, 6))
        frame, self.memory_list = self._listbox(t, height=4)
        frame.grid(row=2, column=0, sticky="nsew")
        self.memory_list.bind("<Delete>", lambda e: self._forget_selected())
        bf = ttk.Frame(t)
        bf.grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Button(bf, text=tr('Löschen'), command=self._forget_selected).pack(side=tk.LEFT)
        ttk.Button(bf, text=tr('Alles vergessen'), command=self._forget_all).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Separator(t).grid(row=4, column=0, sticky="ew", pady=12)
        ttk.Checkbutton(t, text=tr('Erinnerungen – das Modell darf Erinnerungen stellen (Windows-Benachrichtigung)'),
                        variable=self.reminder_var).grid(row=5, column=0, sticky="w")
        ttk.Label(t, text=tr(
            'Zum Beispiel „Erinnere mich in 20 Minuten an den Ofen“. Fällige Erinnerungen erscheinen, solange das '
            'Programm läuft – sonst beim nächsten Start.'), style="Muted.TLabel",
                  wraplength=wrap).grid(row=6, column=0, sticky="w", pady=(2, 6))
        frame, self.reminder_list = self._listbox(t, height=4)
        frame.grid(row=7, column=0, sticky="nsew")
        self.reminder_list.bind("<Delete>", lambda e: self._cancel_selected_reminder())
        ttk.Button(t, text=tr('Löschen'), command=self._cancel_selected_reminder).grid(row=8, column=0, sticky="w",
                                                                                 pady=(6, 0))
        t.columnconfigure(0, weight=1)
        t.rowconfigure(2, weight=1)
        t.rowconfigure(7, weight=1)
        self._fill_memory()

        # ---- Sprache (whisper.cpp)
        t = tabs["speech"]
        self.speech_model_var = tk.StringVar(value=speech.MODELS.get(self.cfg["speech_model"],
                                                                     speech.MODELS[speech.DEFAULT_MODEL]))
        self.speech_lang_var = tk.StringVar(value=next((k for k, v in speech.LANGUAGES.items()
                                                        if v == self.cfg["speech_language"]), tr("Deutsch")))
        ttk.Label(t, text=tr('Spracherkennung'),
                  style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        self.speech_btn = ttk.Button(t, text=tr('Spracherkennung herunterladen / aktualisieren'),
                                     command=self.download_speech)
        self.speech_btn.grid(row=2, column=0, columnspan=2, sticky="w")
        self.speech_status = tk.StringVar(value=speech.describe())
        ttk.Label(t, textvariable=self.speech_status, style="Muted.TLabel", wraplength=wrap).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(2, 12))
        for r, (label, var, values) in enumerate(((tr('Modell'), self.speech_model_var, list(speech.MODELS.values())),
                                                  (tr('Sprache'), self.speech_lang_var, list(speech.LANGUAGES))), 4):
            ttk.Label(t, text=label).grid(row=r, column=0, sticky="w", padx=(0, 12), pady=3)
            combo = ttk.Combobox(t, textvariable=var, values=values, state="readonly", width=48)
            combo.grid(row=r, column=1, sticky="w", pady=3)
            self.theme.register_combo(combo)
        t.columnconfigure(1, weight=1)

        # ---- System-Prompt
        t = tabs["prompt"]
        ttk.Label(t, text=tr('Wird jeder Unterhaltung als Anweisung vorangestellt:')).pack(anchor="w", pady=(0, 6))
        sys_frame, self.sys_text = scrolled(t, wrap=tk.WORD, font=(FAMILY, 10), padx=8, pady=6)
        sys_frame.pack(fill=tk.BOTH, expand=True)
        self.sys_text.insert("1.0", self.cfg["system_prompt"])
        self.theme.register_text(self.sys_text)

        # ---- Darstellung
        t = tabs["look"]
        ttk.Label(t, text=tr('Design')).grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.theme_var = tk.StringVar()
        self.theme_combo = ttk.Combobox(t, textvariable=self.theme_var, state="readonly", width=28,
                                        values=[th["label"] for th in THEMES.values()])
        self.theme_combo.grid(row=0, column=1, sticky="w")
        self.theme_combo.bind("<<ComboboxSelected>>",
                              lambda e: self.set_theme(label_to_key(self.theme_var.get())))
        self.theme.register_combo(self.theme_combo)
        ttk.Label(t, text=tr('Eigene Farben: in themes.py einen Eintrag in THEMES anpassen oder hinzufügen.'),
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        ttk.Separator(t).grid(row=2, column=0, columnspan=2, sticky="ew", pady=14)
        self.think_title_var = tk.BooleanVar(value=self.cfg["think_titles"])
        ttk.Checkbutton(t, text=tr('Denkprozess mit kurzer Überschrift zusammenfassen'),
                        variable=self.think_title_var).grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Label(t, text=tr(
            'Nach jeder Antwort fasst das geladene Modell seinen (zugeklappten) Denkprozess in wenigen Wörtern '
            'zusammen – eine kleine zusätzliche Anfrage. Ausgeschaltet heißt der Block einfach „Gedankengang“.'), style="Muted.TLabel",
                  wraplength=round(560 * self.ui_scale)).grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(t, text=tr("Oberflächensprache")).grid(row=5, column=0, sticky="w", pady=(18, 0))
        self.ui_language_var = tk.StringVar(value=next(
            label for label, code in UI_LANGUAGES.items() if code == self.cfg["ui_language"]))
        self.ui_language_combo = ttk.Combobox(t, textvariable=self.ui_language_var, values=list(UI_LANGUAGES),
                                             state="readonly", width=28)
        self.ui_language_combo.grid(row=5, column=1, sticky="w", pady=(18, 0))
        self.ui_language_combo.bind("<<ComboboxSelected>>", self._change_ui_language)
        self.theme.register_combo(self.ui_language_combo)

        # ---- Server-Log
        t = tabs["log"]
        log_frame, self.log = scrolled(t, wrap=tk.NONE, state=tk.DISABLED, font=("Consolas", 9),
                                            padx=6, pady=4)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.theme.register_text(self.log)

    def _change_ui_language(self, _event=None):
        language = UI_LANGUAGES.get(self.ui_language_var.get())
        if not language or language == self.cfg["ui_language"]:
            return
        self.cfg["ui_language"] = language
        self.save_config()
        dialogs.showinfo(tr("Oberflächensprache"),
                         tr("Die neue Oberflächensprache wird beim nächsten Start von Monhip verwendet."),
                         parent=self.settings_win)

    def open_settings(self, tab: str | None = None):
        win = self.settings_win
        if tab:
            self.settings_nb.select(self.settings_tabs[tab])
        if win.winfo_viewable():
            win.lift()
            win.focus_set()
            return
        geometry = None
        if not self._settings_placed:
            self.root.update_idletasks()
            w, h = round(840 * self.ui_scale), round(600 * self.ui_scale)
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - w) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - h) // 3)
            geometry = f"{w}x{h}+{x}+{y}"
            self._settings_placed = True
        self.theme.present(win, geometry)
        win.focus_set()

    def close_settings(self):
        self.save_config()
        self.settings_win.withdraw()

    def set_theme(self, key: str, save: bool = True):
        theme = self.theme.apply(key)
        self.theme_var.set(theme["label"])
        self.view.apply_theme(theme["chat"])
        self.room_view.apply_theme(theme["chat"])
        p = self.theme.pal
        if p:
            self.mode_switch.set_colors(bg=p["sidebar"], track=p["side_hover"] if p["dark"] else p["side_sel"],
                                        pill=p["side_sel"] if p["dark"] else p["surface"], border=p["accent"],
                                        fg=p["fg"], muted=p["muted"])
        else:  # Windows-Standard: neutrale Grautöne auf der Fensterfarbe
            r, g, b = (v // 257 for v in self.root.winfo_rgb(self.root.cget("background")))
            self.mode_switch.set_colors(bg=f"#{r:02x}{g:02x}{b:02x}", track="#e1e1e1", pill="#ffffff",
                                        border="#0b63c5", fg="#1b1b1b", muted="#5f5f5f")
        if hasattr(self, "room"):
            self.room.refresh_panel()  # Teilnehmerliste nutzt Farben aus dem Design
        muted = theme.get("muted", "#777777")
        self.chat_tree.tag_configure("group", foreground=muted)
        self._meter_cache.clear()
        self._draw_meter()
        self._fix_meter_height()  # das Häkchen kann je Design anders hoch sein
        self.chat_tree.tag_configure("hover", background=theme.get("side_hover", "#e8e8e8"))
        self.cfg["theme"] = self.theme.key
        if save:
            self.save_config()

    # ================================================================ Chatliste

    def refresh_chat_list(self):
        """Chatliste mit Datumsgruppen – neu aufgebaut nur, wenn sich Reihenfolge, Titel oder Gruppen ändern."""
        rows, last = [], None
        for c in chats.list_all():
            group = chats.group_label(c["updated"])
            if group != last:
                rows.append((f"grp:{group}", "  " + group.upper(), "group"))
                last = group
            rows.append((c["id"], (tr('  Experte · ') if c.get("expert") else "  ") + c["title"], "chat"))
        if rows != self._tree_rows:
            tree = self.chat_tree
            self._tree_rows, self._hover, self._dots = rows, None, set()
            tree.delete(*tree.get_children())
            for iid, text, tag in rows:
                tree.insert("", tk.END, iid=iid, text=text, tags=(tag,))
        self._sync_tree_selection()

    def _sync_tree_selection(self):
        cid = self.chat_data["id"] if self.chat_data else None
        if cid and self.chat_tree.exists(cid):
            if self.chat_tree.selection() != (cid,):
                self.chat_tree.selection_set(cid)
            self.chat_tree.see(cid)
        elif self.chat_tree.selection():
            self.chat_tree.selection_remove(*self.chat_tree.selection())
        self._update_dots()

    def _set_title(self, title: str):
        self._chat_title = title
        self.update_title()

    def _current_tree_chat(self):
        sel = self.chat_tree.selection()
        return sel[0] if sel and not sel[0].startswith("grp:") else None

    def _on_chat_select(self, _e=None):
        self._set_hover(None)
        self._update_dots()
        sel = self.chat_tree.selection()
        if not sel:
            return
        item = sel[0]
        if self.chat_data and item == self.chat_data["id"]:
            return
        if item.startswith("grp:"):
            self._sync_tree_selection()
            return
        if self.busy:
            self._sync_tree_selection()
            dialogs.showinfo("Monhip", tr('Bitte warten, bis die Antwort fertig ist (oder „Stopp“ drücken).'))
            return
        self.open_chat(item)

    def _set_hover(self, item):
        tree = self.chat_tree
        if item == self._hover:
            return
        if self._hover and tree.exists(self._hover):
            tree.item(self._hover, tags=[t for t in tree.item(self._hover, "tags") if t != "hover"])
        self._hover = None
        if item and not item.startswith("grp:") and item not in tree.selection():
            tree.item(item, tags=list(tree.item(item, "tags")) + ["hover"])
            self._hover = item

    def _on_tree_hover(self, e):
        row = self.chat_tree.identify_row(e.y) or None
        self._set_hover(row)
        if row != self._pointer:
            self._pointer = row
            self._update_dots()

    def _on_tree_leave(self, _e=None):
        self._set_hover(None)
        self._pointer = None
        self._update_dots()

    def _update_dots(self):
        """„⋯“ beim geöffneten Chat, beim Chat unter der Maus und beim Chat mit offenem Menü anzeigen."""
        tree = self.chat_tree
        want = {i for i in (self._pointer, self._menu_item, *tree.selection())
                if i and not i.startswith("grp:") and tree.exists(i)}
        for i in self._dots - want:
            if tree.exists(i):
                tree.set(i, "menu", "")
        for i in want - self._dots:
            tree.set(i, "menu", "•••")
        self._dots = want

    def _on_tree_click(self, e):
        """Klick auf „⋯“ öffnet das Menü, ohne den Chat zu wechseln."""
        tree = self.chat_tree
        item = tree.identify_row(e.y)
        if tree.identify_column(e.x) != "#1" or not item or item.startswith("grp:"):
            return None
        x, y, _w, h = tree.bbox(item, "menu")
        self._open_chat_menu(item, tree.winfo_rootx() + x, tree.winfo_rooty() + y + h)
        return "break"

    def _on_tree_menu(self, e):
        item = self.chat_tree.identify_row(e.y)
        if not item or item.startswith("grp:"):
            return
        self._open_chat_menu(item, e.x_root, e.y_root)

    def _open_chat_menu(self, item, x, y):
        self._ctx_item = self._menu_item = item
        self._update_dots()
        try:
            self.chat_menu.tk_popup(x, y)
        finally:
            self.chat_menu.grab_release()
            self._menu_item = None
            self._update_dots()

    def rename_chat(self, chat_id):
        if not chat_id:
            return
        current = self.chat_data if self.chat_data and self.chat_data["id"] == chat_id else None
        data = current or chats.load(chat_id)
        if not data:
            return
        title = dialogs.askstring(tr('Chat umbenennen'), tr('Neuer Name:'), data.get("title", ""))
        if not title:
            return
        data["title"] = title
        if current is not None:
            self._set_title(title)
            if self.busy:  # wird nach der Antwort ohnehin gespeichert
                self.chat_tree.item(chat_id, text=(tr('  Experte · ') if current.get("experte") else "  ") + title)
                return
            data["messages"] = self.history
        chats.save(data, touch=False)  # touch=False: Sortierung bleibt
        self.refresh_chat_list()

    def delete_chat(self, chat_id):
        if not chat_id:
            return
        is_current = self.chat_data and self.chat_data["id"] == chat_id
        if is_current and self.busy:
            dialogs.showinfo("Monhip", tr('Dieser Chat läuft gerade noch. Bitte erst „Stopp“ drücken.'))
            return
        if self.expert_job and self._expert_job_chat == chat_id:  # Auswertung dieses Chats anhalten
            self.expert_job.stop_event.set()
        chats.delete(chat_id)
        if is_current:
            self.chat_data = None
            self.new_chat()
        self.refresh_chat_list()

    # ================================================================ Chat öffnen / anzeigen

    def new_chat(self):
        if self.mode == "room":  # „+ Neuer Chat“/Strg+N führt zurück in den normalen Chat
            self.set_mode("chat")
        if self.busy:
            return
        self.chat_data = None
        self.history = []
        self._set_title(tr('Neuer Chat'))
        self._sync_tree_selection()
        self._show_placeholder()
        self._estimate_context()
        self._update_expert_row()
        self.input.focus_set()

    def open_chat(self, chat_id):
        data = chats.load(chat_id)
        if not data:
            dialogs.showerror("Monhip", tr('Der Chat konnte nicht geladen werden.'))
            self.refresh_chat_list()
            return
        self.chat_data = data
        self.history = data.get("messages", [])
        self._set_title(data.get("title", "Chat"))
        self._render_history()
        self._update_expert_row()
        self.input.focus_set()

    def _show_placeholder(self):
        expert = (self.chat_data or {}).get("experte")
        if expert and self.server.model:
            self.view.placeholder(tr('Experte für „{0}“', Path(expert['quelle']).name),
                                  tr(
                                      'Stelle Fragen zu den Dokumenten im Ordner – die KI sucht die passenden '
                                      'Stellen und nennt Datei und Seite.\n\nDie Auswertung steht unten im Fenster; '
                                      'Fragen gehen schon, während sie läuft.'))
        elif self.server.model:
            what = tr('Dokumente und Bilder') if self.server.vision else tr('Dokumente')
            self.view.placeholder(tr(
                'Womit kann ich helfen?'), tr(
                'Geladen: {0}\n\n{1} anhängen: „+“ klicken, Dateien ins Fenster ziehen oder mit Strg+V einfügen',
                self.server.model.stem,
                what))
        else:
            self.view.placeholder(tr('Kein Modell geladen'), tr('Oben rechts ein Modell auswählen und „Modell laden“ klicken.'))

    def _render_history(self):
        """Gespeicherten Chat anzeigen: Nutzer rechts, Antworten links, Denkprozess/Werkzeuge zugeklappt."""
        self.view.clear()
        if not self.history:
            self._show_placeholder()
            return
        results = {m.get("tool_call_id"): m.get("content") or "" for m in self.history if m.get("role") == "tool"}
        with self.view.batch():  # erst am Ende einmal ans Ende scrollen
            for i, m in enumerate(self.history):
                role, content = m.get("role"), m.get("content") or ""
                if m.get("_summary_before"):  # alles davor kennt das Modell nur noch als Zusammenfassung
                    self.view.think_static(m["_summary_before"], self._summary_title(m.get("_summary_count") or i),
                                           icon="≡")
                if role == "user":
                    self.view.user(m.get("_text", content), self._display_files(m.get("_files")), m.get("_quote"),
                                   self._msg_actions(i))
                elif role == "assistant":
                    if m.get("_thinking"):
                        self.view.think_static(m["_thinking"], m.get("_thinking_title"), m.get("_thinking_secs"))
                    if content:
                        self.view.markdown(content)
                    for c in m.get("tool_calls") or []:
                        fn = c.get("function", {})
                        icon, label, detail = describe_call(fn.get("name", ""), fn.get("arguments", ""))
                        res = results.get(c.get("id"))
                        self.view.tool_static(label, detail, format_args(fn.get("arguments", "")), res,
                                              result_ok(res), icon)
                    if content and not m.get("tool_calls"):
                        self.view.footer(content)
        self.view.scroll_end()
        self._estimate_context()

    def _save_chat(self, touch: bool = True):
        if self.chat_data is None:
            return
        self.chat_data["messages"] = self.history
        try:
            chats.save(self.chat_data, touch=touch)
        except OSError as e:
            self.view.note(tr('Chat konnte nicht gespeichert werden: {0}', e), "error")
        self.refresh_chat_list()

    # ================================================================ Modelle

    def open_model_dir(self):
        MODEL_DIR.mkdir(exist_ok=True)
        os.startfile(MODEL_DIR)

    def refresh_models(self):
        MODEL_DIR.mkdir(exist_ok=True)  # damit man Modelle gleich hineinlegen kann
        self.models = find_models([str(MODEL_DIR)] + self.cfg["folders"])
        for f in self.cfg["extra_models"]:
            p = Path(f)
            if p.is_file() and p not in self.models:
                self.models.append(p)
        self.model_list.delete(0, tk.END)
        for p in self.models:
            gb = p.stat().st_size / 1024 ** 3
            self.model_list.insert(tk.END, f"  {p.stem}   ({gb:.1f} GB)")
        if self.models:
            self.models_info.set(tr('{0} Modelle gefunden', len(self.models)))
            self.model_combo.configure(values=[p.stem for p in self.models])
        else:
            self.models_info.set(tr('Keine Modelle gefunden'))
            self.model_list.insert(tk.END, tr('  Keine .gguf-Modelle gefunden.'))
            self.model_list.insert(tk.END, tr('  Doppelklick hier öffnet den Modellordner – Modelle einfach hineinlegen'))
            self.model_list.insert(tk.END, tr('  und „Aktualisieren“ klicken, oder über „Herunterladen…“ laden.'))
            self.model_combo.configure(values=[])
            self.model_var.set(tr('Keine Modelle – siehe Einstellungen'))

        wanted = self.sel_model or (Path(self.cfg["last_model"]) if self.cfg["last_model"] else None)
        idx = next((i for i, p in enumerate(self.models) if wanted and same_path(p, wanted)), None)
        if idx is None and wanted:  # z. B. nach dem Verschieben in einen anderen Ordner: gleicher Dateiname
            idx = next((i for i, p in enumerate(self.models) if p.name.lower() == wanted.name.lower()), None)
        if idx is None and self.models:
            idx = 0
        self.sel_model = None
        if idx is not None:
            self._select_model(idx)
        self._fill_sources()

    def _select_model(self, idx: int):
        if idx is None or not (0 <= idx < len(self.models)):
            return
        self.sel_model = self.models[idx]
        self.model_combo.current(idx)
        self.model_list.selection_clear(0, tk.END)
        self.model_list.selection_set(idx)
        self.model_list.see(idx)

    def _on_model_list_select(self, _e=None):
        sel = self.model_list.curselection()
        if sel and sel[0] < len(self.models):
            self._select_model(sel[0])

    def add_folder(self, parent=None) -> bool:
        d = filedialog.askdirectory(title=tr('Ordner mit GGUF-Modellen wählen'), parent=parent or self.root)
        if not d:
            return False
        if not any(same_path(d, f) for f in [str(MODEL_DIR)] + self.cfg["folders"]):
            self.cfg["folders"].append(str(Path(d)))
            self.save_config()
        self.refresh_models()
        return True

    def add_file(self, parent=None):
        f = filedialog.askopenfilename(title=tr('GGUF-Modell öffnen'), filetypes=[(tr("GGUF-Modelle"), "*.gguf")],
                                       parent=parent or self.root)
        if f:
            f = str(Path(f))
            if not any(same_path(f, x) for x in self.cfg["extra_models"]):
                self.cfg["extra_models"].append(f)
            self.cfg["last_model"] = f
            self.sel_model = Path(f)
            self.save_config()
            self.refresh_models()

    # ---------------------------------------------------------------- Modellordner-Dialog

    def open_sources(self):
        """Ordner (und Einzeldateien), in denen zusätzlich nach Modellen gesucht wird."""
        if self.sources_win and self.sources_win.winfo_exists():
            self.sources_win.lift()
            return
        win = dialogs.window(tr('Weitere Modellordner'), self.settings_win, resizable=True)
        win.minsize(520, 300)
        self.sources_win = win
        body = ttk.Frame(win, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=tr(
            'In diesen Ordnern (inkl. aller Unterordner) wird nach .gguf-Modellen gesucht. Der eigene Ordner '
            '„modelle“ ist immer dabei:')).pack(anchor="w")
        lf, lst = self._listbox(body)
        lf.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.sources_list = lst
        lst.bind("<Double-Button-1>", lambda e: self._change_source())
        lst.bind("<Delete>", lambda e: self._remove_source())

        bf = ttk.Frame(body)
        bf.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(bf, text=tr('Ordner hinzufügen…'), style="Accent.TButton",
                   command=lambda: self.add_folder(win)).pack(side=tk.LEFT)
        ttk.Button(bf, text=tr('Datei hinzufügen…'), command=lambda: self.add_file(win)).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(bf, text=tr('Ändern…'), command=self._change_source).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(bf, text=tr('Entfernen'), command=self._remove_source).pack(side=tk.LEFT, padx=(4, 0))
        ttk.Button(bf, text=tr('Schließen'), command=win.destroy).pack(side=tk.RIGHT)
        ttk.Label(body, style="Muted.TLabel",
                  text=tr('„Entfernen“ nimmt den Eintrag nur aus der Liste, die Modelldateien bleiben erhalten.')
                  ).pack(anchor="w", pady=(6, 0))
        self._fill_sources()
        dialogs.present(win, self.settings_win, size=(round(760 * self.ui_scale), round(400 * self.ui_scale)))

    def _sources(self) -> list[tuple[str, str]]:
        return ([("own", str(MODEL_DIR))] + [("folders", f) for f in self.cfg["folders"]] +
                [("extra_models", f) for f in self.cfg["extra_models"]])

    def _fill_sources(self):
        if not (self.sources_win and self.sources_win.winfo_exists()):
            return
        lst = self.sources_list
        sel = lst.curselection()
        lst.delete(0, tk.END)
        for kind, path in self._sources():
            p = Path(path)
            if kind in ("own", "folders"):
                if not p.is_dir():
                    info = tr('Ordner nicht gefunden')
                else:
                    n = sum(1 for m in self.models if m.is_relative_to(p))
                    info = tr('{0} Modell', n) + ("" if n == 1 else "e")
                lst.insert(tk.END, f"{tr('Eigener Ordner') if kind == 'own' else tr('Ordner')}  ·  {info}  ·  {path}")
            else:
                lst.insert(tk.END, tr('Datei  ·  ') + ("" if p.is_file() else tr('nicht gefunden  ·  ')) + path)
        if sel and sel[0] < lst.size():
            lst.selection_set(sel[0])

    def _selected_source(self):
        sel = self.sources_list.curselection()
        items = self._sources()
        if not sel or sel[0] >= len(items):
            dialogs.showinfo(tr('Modellordner'), tr('Bitte zuerst einen Eintrag in der Liste auswählen.'),
                             parent=self.sources_win)
            return None
        if items[sel[0]][0] == "own":
            dialogs.showinfo(tr(
                'Modellordner'), tr(
                'Der eigene Ordner „modelle“ gehört zum Programm und wird immer durchsucht – Modelle einfach dort '
                'hineinlegen.'), parent=self.sources_win)
            return None
        return items[sel[0]]

    def _change_source(self):
        item = self._selected_source()
        if not item:
            return
        kind, old = item
        if kind == "folders":
            new = filedialog.askdirectory(title=tr('Neuen Modellordner wählen'), parent=self.sources_win,
                                          initialdir=old if Path(old).is_dir() else None)
        else:
            new = filedialog.askopenfilename(title=tr('GGUF-Modell wählen'), parent=self.sources_win,
                                             filetypes=[(tr("GGUF-Modelle"), "*.gguf")])
        if not new:
            return
        lst = self.cfg[kind]
        i = lst.index(old)
        if any(same_path(new, x) for x in lst):
            lst.pop(i)  # schon vorhanden -> alten Eintrag nur entfernen
        else:
            lst[i] = str(Path(new))
        self.save_config()
        self.refresh_models()

    def _remove_source(self):
        item = self._selected_source()
        if not item:
            return
        kind, path = item
        self.cfg[kind].remove(path)
        self.save_config()
        self.refresh_models()

    # ---------------------------------------------------------------- Backend (llama.cpp) und Downloads

    def _on_server_selected(self, _e=None):
        if self.server_var.get().startswith(tr('Eigene')):
            f = filedialog.askopenfilename(title=tr('llama-server.exe wählen'), filetypes=[("llama-server", "*.exe")],
                                           parent=self.settings_win)
            self.server_var.set(f or (self.servers[0]["label"] if self.servers else ""))

    def _selected_server(self) -> dict | None:
        v = self.server_var.get()
        for s in self.servers:
            if s["label"] == v:
                return s
        if v and Path(v).is_file():
            return {"label": v, "exe": v}
        return None

    def _refresh_servers(self, select_exe: str | None = None):
        """Liest server/ neu ein und aktualisiert die Backend-Auswahl."""
        self.servers = llamacpp.find_llama_servers()
        labels = [s["label"] for s in self.servers]
        self.server_combo.configure(values=labels + [tr('Eigene llama-server.exe…')])
        match = [s["label"] for s in self.servers if select_exe and same_path(s["exe"], select_exe)]
        if match:
            self.server_var.set(match[0])
        elif self.server_var.get() not in labels and not Path(self.server_var.get()).is_file():
            self.server_var.set(labels[0] if labels else "")

    def _download_flow(self, btn, status, find, offer, install, finished, confirm=True):
        """Version suchen (Thread) → nachfragen → herunterladen, Fortschritt in status; während des Downloads
        bricht derselbe Knopf ab. offer(plan) → (Titel, Frage, Name) oder None, wenn schon alles aktuell ist."""
        key = str(btn)
        if key in self._downloads:
            self._downloads[key].set()
            return
        if btn.instate(["disabled"]):
            return
        btn.configure(state=tk.DISABLED)
        status.set(tr('Erkenne Grafikkarte und suche die neueste Version …'))
        label = btn.cget("text")

        def progress(name, done, total):
            pct = f"{done * 100 / total:.0f} % " if total else ""
            status.set(tr('Lade {0} … {1}({2:.0f} / {3:.0f} MB)', name, pct, done / 1024 ** 2, total / 1024 ** 2))

        def installed(plan, name, cancel, result, err):
            self._downloads.pop(key, None)
            btn.configure(text=label)
            if err:
                status.set(tr('Download abgebrochen.') if cancel.is_set() else tr('Download von {0} fehlgeschlagen: {1}', name, err))
            else:
                finished(plan, result)

        def planned(plan, err):
            btn.configure(state=tk.NORMAL)
            if err:
                status.set(tr('Suche fehlgeschlagen: {0}', err))
                return
            question = offer(plan)
            if not question:
                return
            title, text, name = question
            if confirm and not dialogs.askyesno(title, text, parent=self.settings_win):
                status.set(tr('Download abgebrochen.'))
                return
            cancel = self._downloads[key] = threading.Event()
            btn.configure(text=tr('Download abbrechen'))
            status.set(tr('Lade {0} … 0 %', name))
            self.background(lambda: install(plan, lambda d, n: self.ui(progress, name, d, n), cancel),
                            lambda result, err: installed(plan, name, cancel, result, err))

        self.background(find, planned)

    def download_server(self, confirm=True):
        def offer(plan):
            name = f"llama.cpp {plan['tag']} ({plan['kind']})"
            if plan["installed"]:
                self._refresh_servers(str(plan["target"] / "llama-server.exe"))
                self.srv_status.set(tr('{0} ist bereits die neueste Version.', name))
                return None
            return (tr(
                'llama.cpp herunterladen'), tr(
                'Grafikkarte: {0}\nPassende Version: {1}\nDownload: {2:.0f} MB\n\nJetzt herunterladen?',
                plan['gpu'],
                name,
                plan['size'] / 1024 ** 2), name)

        def finished(plan, exe):
            self._refresh_servers(str(exe))
            self.save_config()
            self.srv_status.set(tr('llama.cpp {0} ({1}) installiert – Modelle können jetzt geladen werden.', plan['tag'], plan['kind']))

        self._download_flow(self.srv_btn, self.srv_status, llamacpp.plan, offer, llamacpp.install, finished, confirm)

    # ---------------------------------------------------------------- Laden / Entladen

    def _set_load_buttons(self, state):
        for b in (self.load_btn, self.load_btn2):
            b.configure(state=state)

    def load_model(self):
        model = self.sel_model
        if not model:
            if not self.models:
                dialogs.showinfo("Monhip", tr(
                    'Es wurden keine Modelle gefunden. Lege deine .gguf-Modelle in den Ordner „modelle“ '
                    '(„Modellordner öffnen“) oder lade eines herunter.'))
                self.open_settings("models")
            else:
                dialogs.showinfo("Monhip", tr('Bitte zuerst ein Modell auswählen.'))
            return
        server = self._selected_server()
        if not server:
            if dialogs.askyesno("Monhip", tr(
                'Zum Laden von Modellen wird llama.cpp gebraucht, das noch nicht installiert ist.\n\nJetzt die '
                'passende Version für deine Grafikkarte von GitHub herunterladen (einmalig, je nach Grafikkarte '
                '20–600 MB)?')):
                self.open_settings("load")
                self.download_server(confirm=False)
            return
        try:
            ctx = int(self.ctx_var.get())
        except ValueError:
            dialogs.showerror("Monhip", tr('Kontext muss eine Zahl sein (Einstellungen → Laden).'))
            return
        mmproj = find_mmproj(model) if self.vision_var.get() else None
        try:
            image_tokens = int(self.imgtok_var.get()) if self.imgtok_var.get().strip() else None
        except ValueError:
            dialogs.showerror("Monhip", tr('„Max. Tokens pro Bild“ muss eine Zahl sein (Einstellungen → Laden).'))
            return
        self.cfg["last_model"] = str(model)
        self.save_config()
        self.load_cancel.set()  # ein noch laufendes Laden (z. B. Doppelklick) still abbrechen
        cancel = self.load_cancel = threading.Event()
        ngl, extra = self.ngl_var.get().strip(), self.extra_var.get()
        self._set_load_buttons(tk.DISABLED)
        self._set_status(tr('Lade {0} …', model.stem))
        self.background(lambda: self.server.start(server, model, ctx, ngl, extra, cancel, mmproj=mmproj,
                                                  image_tokens=image_tokens),
                        lambda _, err: self._loaded(model, cancel, err))

    def _loaded(self, model: Path, cancel: threading.Event, err: str | None):
        if cancel.is_set():  # inzwischen entladen
            return
        self._set_load_buttons(tk.NORMAL)
        if err:
            self._set_status(tr('Laden fehlgeschlagen – Details unter Einstellungen → Server-Log'))
            dialogs.showerror("Monhip", err)
            return
        self._set_status(tr('Geladen: {0}', model.stem) + (tr('  ·  versteht Bilder') if self.server.vision else "")
                         + (tr('  ·  Kontext {0:,}', self.server.n_ctx).replace(",", ".") if self.server.n_ctx else ""),
                         ok=True)
        if self.view.is_placeholder:
            self._show_placeholder()
        self.room.model_changed()
        self._estimate_context()

    def unload_model(self):
        self.load_cancel.set()
        self.stop_event.set()
        if self.expert_job:  # ohne Modell geht die Auswertung nicht weiter („Fortsetzen“ nach dem Laden)
            self.expert_job.stop_event.set()
        self.server.model = None
        threading.Thread(target=self.server.stop, daemon=True).start()
        self._set_status(tr('Kein Modell geladen'))
        self._set_load_buttons(tk.NORMAL)
        if self.view.is_placeholder:
            self._show_placeholder()
        self.room.model_changed()
        self._estimate_context()

    # ---------------------------------------------------------------- Kontextgröße

    def _ctx_value(self) -> int:
        """Kontext in Tokens: der des geladenen Modells, sonst die Einstellung."""
        if self.server.n_ctx:
            return self.server.n_ctx
        try:
            return int(self.ctx_var.get())
        except ValueError:
            return DEFAULTS["ctx"]

    # ---------------------------------------------------------------- Freigegebene Ordner

    def _fill_folders(self):
        lst = self.folder_list
        lst.delete(0, tk.END)
        lst.insert(tk.END, f"★  {self.ws_var.get()}")
        for f in self.extra_folders:
            lst.insert(tk.END, f"     {f}")

    def _add_folder(self):
        d = filedialog.askdirectory(title=tr('Ordner für das Modell freigeben'), parent=self.settings_win)
        if not d:
            return
        d = str(Path(d))
        if not any(same_path(d, f) for f in [self.ws_var.get(), *self.extra_folders]):
            self.extra_folders.append(d)
        self._fill_folders()
        self.save_config()

    def _selected_folder(self) -> int | None:
        sel = self.folder_list.curselection()
        if not sel:
            dialogs.showinfo(tr('Freigegebene Ordner'), tr('Bitte zuerst einen Ordner in der Liste auswählen.'),
                             parent=self.settings_win)
            return None
        return sel[0]

    def _main_folder(self):
        i = self._selected_folder()
        if not i:  # None oder schon der Arbeitsordner
            return
        new = self.extra_folders.pop(i - 1)
        self.extra_folders.insert(0, self.ws_var.get())
        self.ws_var.set(new)
        self._fill_folders()
        self.save_config()

    def _remove_folder(self):
        i = self._selected_folder()
        if i is None:
            return
        if i == 0:
            if not self.extra_folders:
                dialogs.showinfo(tr(
                    'Freigegebene Ordner'), tr(
                    'Mindestens ein Arbeitsordner wird gebraucht. Erst einen weiteren Ordner hinzufügen.'), parent=self.settings_win)
                return
            self.ws_var.set(self.extra_folders.pop(0))
        else:
            self.extra_folders.pop(i - 1)
        self._fill_folders()
        self.save_config()

    # ---------------------------------------------------------------- Gedächtnis & Erinnerungen

    def _listbox(self, parent, **kw) -> tuple[ttk.Frame, tk.Listbox]:
        frame, lst = scrolled(parent, tk.Listbox, **{"activestyle": "none", "exportselection": False,
                                                     "font": (FAMILY, 9), **kw})
        self.theme.register_list(lst)
        return frame, lst

    def _fill_memory(self):
        """Listen im Reiter „Gedächtnis“ neu füllen (nach Werkzeugaufrufen, fälligen Erinnerungen, Löschen)."""
        self._memory_items = memory.load()
        self._reminder_items = reminders.load()
        for lst, items, text, empty in (
                (self.memory_list, self._memory_items, lambda n: n["text"], tr('(noch nichts gemerkt)')),
                (self.reminder_list, self._reminder_items, reminders.describe, tr('(keine offenen Erinnerungen)'))):
            lst.delete(0, tk.END)
            for item in items:
                lst.insert(tk.END, f"[{item['id']}]  {text(item)}")
            if not items:
                lst.insert(tk.END, empty)

    @staticmethod
    def _picked(lst: tk.Listbox, items: list[dict]) -> dict | None:
        sel = lst.curselection()
        return items[sel[0]] if sel and sel[0] < len(items) else None

    def _forget_selected(self):
        note = self._picked(self.memory_list, self._memory_items)
        if note:
            memory.remove(note["id"])
            self._fill_memory()

    def _forget_all(self):
        if self._memory_items and dialogs.askyesno(tr('Gedächtnis'), tr('Alles Gemerkte löschen?'), parent=self.settings_win):
            memory.clear()
            self._fill_memory()

    def _cancel_selected_reminder(self):
        item = self._picked(self.reminder_list, self._reminder_items)
        if item:
            reminders.remove(item["id"])
            self._fill_memory()

    def _check_reminders(self):
        """Alle 15 s: fällige Erinnerungen als Windows-Benachrichtigung (die braucht ~1 s → im Thread)."""
        try:
            fired = reminders.due()
        except OSError:
            fired = []
        now = datetime.now()
        for item in fired:
            due = datetime.strptime(item["due"], "%Y-%m-%d %H:%M")
            text = item["text"] + (tr('  (verpasst – war für {0:%d.%m. %H:%M} Uhr)', due)
                                   if now - due > timedelta(minutes=2) else "")
            threading.Thread(target=self._notify_reminder, args=(text,), daemon=True).start()
        if fired:
            self._fill_memory()
        self.root.after(15_000, self._check_reminders)

    def _notify_reminder(self, text: str):
        if not reminders.notify(tr('Erinnerung'), text):  # Benachrichtigungen aus? Dann eine Meldung im Programm
            self.ui(dialogs.showinfo, tr('Erinnerung'), text)

    def _screenshot_from_worker(self):
        """Läuft im Agenten-Thread (take_screenshot) und wartet, bis der Tk-Thread das Foto gemacht hat."""
        done, box = threading.Event(), {}
        self.ui(self._take_screenshot, done, box)
        done.wait()
        if "error" in box:
            raise RuntimeError(box["error"])
        return box["shot"]

    def _take_screenshot(self, done: threading.Event, box: dict):
        """Programm kurz minimieren, damit es nicht selbst auf dem Foto ist, dann wiederherstellen."""
        self.root.iconify()

        def shoot():
            try:
                box["shot"] = images.screenshot()
            except Exception as e:
                box["error"] = error_text(e) or type(e).__name__
            finally:
                self.root.deiconify()
                self.root.lift()
                done.set()

        self.root.after(500, shoot)  # Minimier-Animation abwarten

    # ---------------------------------------------------------------- Spracherkennung (whisper.cpp)

    def _speech_settings(self) -> tuple[str, str]:
        """(Modell-Dateiname, Sprachkürzel) aus den Einstellungen – nur im Tk-Thread lesen."""
        model = next((k for k, v in speech.MODELS.items() if v == self.speech_model_var.get()), speech.DEFAULT_MODEL)
        return model, speech.LANGUAGES.get(self.speech_lang_var.get(), "de")

    def toggle_dictation(self):
        """Mikrofon: Aufnahme starten – beim zweiten Klick beenden, abschreiben (im Thread) und ins Eingabefeld setzen."""
        if self._transcribing:
            return
        model, language = self._speech_settings()
        if self.recorder.active:
            try:
                path = self.recorder.stop()
            except RuntimeError as e:
                self.mic_btn.configure(width=2, **icons.only("mic", size=18))
                dialogs.showerror(tr('Spracherkennung'), tr('Die Aufnahme konnte nicht gespeichert werden: {0}', e))
                return
            self._transcribing = True
            self.mic_btn.configure(text="…", width=2, image="")

            def work():
                try:
                    return speech.transcribe(path, model, language)
                finally:
                    path.unlink(missing_ok=True)

            self.background(work, self._dictated)
            return
        if not speech.ready(model):
            if dialogs.askyesno(tr(
                'Spracherkennung'), tr(
                'Zum Diktieren wird die Spracherkennung (whisper.cpp und ein Whisper-Modell) gebraucht. Sie läuft '
                'komplett auf deinem PC.\n\nJetzt herunterladen (einmalig, je nach Grafikkarte etwa 0,5–1,5 GB)?')):
                self.open_settings("speech")
                self.download_speech(confirm=False)
            return
        try:
            self.recorder.start()
        except RuntimeError as e:
            dialogs.showerror(tr(
                'Spracherkennung'), tr(
                'Die Aufnahme konnte nicht starten: {0}\n\nIst ein Mikrofon angeschlossen und in Windows freigegeben?',
                e))
            return
        self._tick_recording()

    def _tick_recording(self):
        if not self.recorder.active:
            return
        secs = int(self.recorder.seconds())
        if secs >= 600:  # höchstens 10 Minuten am Stück
            return self.toggle_dictation()
        self.mic_btn.configure(text=f"{secs // 60}:{secs % 60:02d}", width=5, **icons.opts("stop", size=18))
        self.root.after(250, self._tick_recording)

    def _dictated(self, text: str, err: str | None):
        self._transcribing = False
        self.mic_btn.configure(width=2, **icons.only("mic", size=18))
        if err:
            dialogs.showerror(tr('Spracherkennung'), err)
            return
        spoken = " ".join(text.split())
        if not spoken:
            dialogs.showinfo(tr('Spracherkennung'), tr('Es wurde nichts erkannt. War das Mikrofon an (und nicht stumm)?'))
            return
        before = self.input.get("insert-1c", "insert")
        self.input.insert("insert", (" " if before and not before.isspace() else "") + spoken)
        self.input.focus_set()

    def download_speech(self, confirm=True):
        model = self._speech_settings()[0]

        def offer(plan):
            if not plan["program"] and not plan["model"]:
                self.speech_status.set(tr('Alles aktuell: {0}', speech.describe(model)))
                return None
            parts = []
            if plan["program"]:
                parts.append(f"whisper.cpp {plan['tag']} ({plan['kind']}): {plan['program'][2] / 1024 ** 2:.0f} MB")
            if plan["model"]:
                parts.append(tr('Modell {0}: {1:.0f} MB', plan['model'][0], plan['model'][2] / 1024 ** 2))
            return (tr('Spracherkennung herunterladen'), tr('Grafikkarte: {0}\n', plan['gpu']) + "\n".join(parts)
                    + tr('\n\nZusammen {0:.0f} MB – jetzt herunterladen?', plan['size'] / 1024 ** 2), tr('Spracherkennung'))

        def finished(plan, _):
            self.speech_status.set(tr('Installiert: {0} – zum Diktieren auf das Mikrofon neben dem Eingabefeld klicken.',
                                      speech.describe(model)))

        self._download_flow(self.speech_btn, self.speech_status, lambda: speech.plan(model), offer, speech.install,
                            finished, confirm)

    # ================================================================ Anhänge (Dokumente)

    def pick_attachments(self):
        files = filedialog.askopenfilenames(
            title=tr('Dokumente, Bilder und Audio anhängen'), parent=self.root,
            filetypes=[(tr('Dokumente, Bilder und Audio'), "*.pdf *.docx *.xlsx *.pptx *.odt *.ods *.odp *.rtf *.txt *.md "
                                                       "*.csv *.json *.html *.htm *.xml *.log *.png *.jpg *.jpeg *.bmp "
                                                       "*.gif *.wav *.mp3 *.flac *.ogg"),
                       (tr('Bilder'), "*.png *.jpg *.jpeg *.bmp *.gif"), ("Audio", "*.wav *.mp3 *.flac *.ogg"),
                       (tr('Alle Dateien'), "*.*")])
        self.add_attachments(files)

    def add_attachments(self, paths):
        """Dateien anhängen (Knopf, Drag & Drop, Strg+V). Gelesen wird im Hintergrund."""
        skipped, thumb = 0, round(220 * self.ui_scale)
        for p in paths:
            p = Path(p)
            if any(same_path(a["path"], p) for a in self.attachments):
                continue
            if len(self.attachments) >= MAX_ATTACHMENTS:
                skipped += 1
                continue
            att = {"path": p, "status": "loading", "doc": None, "error": ""}
            self.attachments.append(att)
            share = self.mode == "room"  # im Raum geht jede Datei – nicht lesbare nur zum Herunterladen
            self.background(lambda p=p, opts=self._speech_settings(): self._read_attachment(p, thumb, opts, share),
                            lambda doc, err, att=att: self._attached(att, doc, err))
        self._render_attachments()
        if skipped:
            dialogs.showinfo("Monhip", tr('Höchstens {0} Dateien pro Nachricht – {1} wurden nicht angehängt.', MAX_ATTACHMENTS, skipped))
        self.input.focus_set()

    @staticmethod
    def _read_attachment(path: Path, thumb_size: int, speech_opts: tuple[str, str],
                         share: bool = False) -> documents.Document:
        """Läuft im Hintergrund-Thread. share (Teamwork): was sich nicht lesen lässt (Programm, Archiv …), wird
        trotzdem angehängt – als Datei, die die anderen herunterladen können."""
        try:
            return App._read_readable(path, thumb_size, speech_opts)
        except ValueError:
            if not share or not path.is_file():
                raise
        if path.stat().st_size > room_net.MAX_FILE:
            raise ValueError(tr('Zu groß zum Teilen ({0}, höchstens 100 MB).', documents.human_size(path.stat().st_size)))
        return documents.Document(path, projekt.file_kind(path), "", share_only=True)

    @staticmethod
    def _read_readable(path: Path, thumb_size: int, speech_opts: tuple[str, str]) -> documents.Document:
        if images.is_image(path):  # Vorschau als PNG, weil Tk kein JPG kann
            return images.read(path, images.TEMP_DIR / f"vorschau-{secrets.token_hex(4)}.png", thumb_size)
        if speech.is_audio(path):
            if not speech.ready(speech_opts[0]):
                raise ValueError(tr('Zum Abschreiben erst die Spracherkennung herunterladen (Einstellungen → Sprache).'))
            text = speech.transcribe(path, *speech_opts)
            if not text.strip():
                raise ValueError(tr('In der Aufnahme wurde keine Sprache erkannt.'))
            return documents.Document(path, tr('Audio ({0}, abgeschrieben)', path.suffix[1:].upper()), text)
        return documents.read(path)

    def _attached(self, att: dict, doc, err: str | None):
        if any(a is att for a in self.attachments):  # inzwischen entfernt oder gesendet?
            att.update(status="error" if err else "ok", doc=doc, error=err or "")
            self._render_attachments()

    def remove_attachment(self, att: dict):
        if att in self.attachments:
            self.attachments.remove(att)
        self._render_attachments()

    def _render_attachments(self):
        """Kärtchen über dem Eingabefeld: ggf. das Zitat („Antwort auf …“), dann je Anhang Name, Infozeile
        (bzw. Fehler) und ✕ zum Entfernen."""
        bar = self.attach_bar
        for w in bar.winfo_children():
            w.destroy()
        if not self.attachments and not self.quote:
            bar.pack_forget()
            return
        bar.pack(side=tk.BOTTOM, fill=tk.X, after=self._inp_frame)
        if self.quote:
            short = " ".join(self.quote.split())
            short = short if len(short) <= 90 else short[:89].rstrip() + "…"
            self._chip(bar, tr('Antwort auf'), f"„{short}“", "ChipInfo.TLabel",
                       lambda: (setattr(self, "quote", None), self._render_attachments()), icon="reply"
                       ).pack(side=tk.TOP, anchor="w", pady=(0, 4))
        avail = max(300, self.chat.winfo_width() - round(36 * self.ui_scale))
        f_name, f_info = self._chip_fonts
        row, used = None, avail
        for att in self.attachments:
            name = att["path"].name
            name = name if len(name) <= 34 else name[:22] + "…" + name[-10:]
            icon = None
            if att["status"] == "loading":
                style = "ChipInfo.TLabel"
                info = tr('wird abgeschrieben …') if speech.is_audio(att["path"]) else tr('wird gelesen …')
            elif att["status"] == "ok":
                info, style = att["doc"].info, "ChipInfo.TLabel"
            else:
                info, style, icon = att["error"][:70], "ChipError.TLabel", "warning"
            chip = self._chip(bar, name, info, style, lambda a=att: self.remove_attachment(a), icon=icon)
            # Breite aus den Schriftmaßen – update_idletasks könnte hier andere Ereignisse auslösen
            width = (f_name.measure(name) + f_info.measure(info) + round((63 + (23 if icon else 0)) * self.ui_scale))
            if row is None or used + width > avail:  # passt nicht mehr → neue Zeile
                row = ttk.Frame(bar)
                row.pack(side=tk.TOP, fill=tk.X, pady=(0, 4))
                used = 0
            chip.pack(in_=row, side=tk.LEFT, padx=(0, 6))
            chip.lift()  # sonst läge die später erzeugte Zeile über dem Kärtchen
            used += width

    @staticmethod
    def _chip(parent, label: str, info: str, info_style: str, on_close, icon: str | None = None) -> ttk.Frame:
        """Kärtchen „Name  Info  ✕“ (noch nicht angeordnet), ggf. mit Icon vor dem Namen (Warnung bei Fehlern rot)."""
        chip = ttk.Frame(parent, style="Chip.TFrame", padding=(10, 4, 3, 4))
        role = "error" if icon == "warning" else "fg"
        ttk.Label(chip, text=label, style="Chip.TLabel",
                  **(icons.opts(icon, role, disabled=None) if icon else {})).pack(side=tk.LEFT)
        ttk.Label(chip, text=info, style=info_style).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(chip, style="Chip.TButton", width=2, command=on_close,
                   **icons.only("close", "muted", 12, active="fg")).pack(side=tk.LEFT, padx=(6, 0))
        return chip

    def _on_paste(self, _e=None):
        """Strg+V: im Explorer kopierte Dateien bzw. ein Bild (Screenshot) werden angehängt, sonst normal
        Text einfügen."""
        files = filedrop.clipboard_files()
        if files:
            self.add_attachments(files)
            return "break"
        if filedrop.clipboard_has_image():
            self.background(images.save_clipboard, self._pasted_image)
            return "break"
        return None

    def _pasted_image(self, path: Path | None, _err):
        if path:
            self.add_attachments([path])
        else:
            dialogs.showerror("Monhip", tr('Das Bild aus der Zwischenablage konnte nicht übernommen werden.'))

    def _display_files(self, files: list[dict] | None) -> list[dict] | None:
        """Kärtchen-Daten für die Anzeige: bei Bildern Pfad und Vorschaubild aus chats/bilder/ ergänzen."""
        if not files:
            return files
        out = []
        for f in files:
            if f.get("image"):
                p = chats.image_path(f["image"])
                f = {**f, "path": str(p), "thumb": str(chats.thumb_path(p))}
            out.append(f)
        return out

    def _api_message(self, m: dict) -> dict:
        """Nachricht mit gespeicherten Bildern (`_images`, relativ zu chats/bilder) für den Server vorbereiten:
        Die Bildpfade kommen nach `_image_files`, das backend._api_messages als image_url-Teile mitschickt.
        Ohne Bildverständnis (oder wenn die Datei fehlt) bekommt das Modell nur einen Hinweis. Nutzernachrichten
        bekommen ihre feste Uhrzeit (`_time`) angehängt – so bleibt der Anfang der Unterhaltung gleich (date_line)."""
        if m.get("role") == "user" and m.get("_time"):
            try:
                label = time_label(datetime.strptime(m["_time"], TIME_FMT))
            except ValueError:
                label = ""
            if label:
                m = {**m, "content": f"{m.get('content') or ''}\n\n[{label}]"}
        rels = m.get("_images")
        if not rels:
            return m
        files, missing = [], []
        for rel in rels:
            p = chats.image_path(rel)
            if self.server.vision and p.is_file():
                files.append(str(p))
            else:
                missing.append(p.name.split("-", 1)[-1])
        text = m.get("content") or ""
        if missing:
            note = "[Hier war ein Bild, das gerade nicht verfügbar ist: " + ", ".join(missing) + "]"
            text = f"{text}\n\n{note}" if text else note
        return {**m, "content": text, "_image_files": files}

    def _compose_message(self, text: str, docs: list) -> tuple[str, list[dict]]:
        """Nachricht ans Modell: eigener Text + Dokumente in <dokument>-Blöcken. Zu lange Dokumente werden
        gekürzt, damit sie in den Kontext passen (grob 3 Zeichen pro Token, 60 % des Kontexts)."""
        if not docs:
            return text, []
        per_doc = max(4000, int(self._ctx_value() * 0.6 * 3) // len(docs))
        parts, meta = ([text] if text else []), []
        for doc in docs:
            body, note = doc.text, ""
            if len(body) > per_doc:
                body = body[:per_doc]
                note = (f"\n[… gekürzt: nur die ersten {per_doc:,} von {len(doc.text):,} Zeichen passen in den "
                        "Kontext]").replace(",", ".")
            parts.append(f'<dokument name="{doc.name}" art="{doc.kind}">\n{body}{note}\n</dokument>')
            meta.append({"name": doc.name, "info": doc.info + (" · gekürzt" if note else ""), "path": str(doc.path)})
        return "\n\n".join(parts), meta

    def _on_enter(self, e):
        if e.state & 0x0001:  # Shift
            return None
        self.send()
        return "break"

    def _send_or_stop(self):
        if self.busy and self.mode == "chat":
            self.stop_event.set()
        else:
            self.send()

    def _set_busy(self, busy: bool):
        self.busy = busy
        if self.mode == "chat":  # im Raum-Modus bleibt der Knopf „Senden“ (die eigene KI stoppt man links)
            self._send_label(busy)

    def _send_label(self, stop: bool):
        """Senden-Knopf: „Senden“ bzw. während einer Antwort „Stopp“ mit Icon."""
        self.send_btn.configure(text=tr('Stopp') if stop else tr('Senden'),
                                **(icons.opts("stop", "accent_fg") if stop else {"image": ""}))

    def _set_status(self, text: str, ok: bool = False):
        """Statuszeile des Modells (Kopfzeile und Reiter Laden) – mit Haken, wenn es geladen ist."""
        self.status_var.set(text)
        for label in self._status_labels:
            label.configure(**(icons.opts("check", "ok", 14, disabled=None) if ok else {"image": ""}))

    def send(self):
        text = self.input.get("1.0", tk.END).strip()
        if self.busy and self.mode == "chat":
            return
        if any(a["status"] == "loading" for a in self.attachments):
            dialogs.showinfo("Monhip", tr('Die angehängten Dokumente werden noch gelesen – einen Moment bitte.'))
            return
        docs = [a["doc"] for a in self.attachments if a["status"] == "ok"]
        if not text and not docs:
            return
        pics = [d for d in docs if d.image]
        quote = self.quote if text else None  # ein Zitat allein ist keine Nachricht
        if self.mode == "room":  # Gruppenchat: Text + lesbare Dokumente an die KIs, jede Datei zum Herunterladen
            content, _meta = self._compose_message(text, [d for d in docs if not d.image and not d.share_only])
            notes = [f"[{'Bild' if d.image else 'Datei'} geteilt: {d.name}]" for d in docs if d.image or d.share_only]
            content = "\n\n".join(p for p in (content, "\n".join(notes)) if p)
            shares = [{"path": str(d.path), "name": d.name, "info": d.info, "image": bool(d.image)} for d in docs]
            if self.room.send(text, self._with_quote(quote, content), shares):
                self.input.delete("1.0", tk.END)
                self._clear_compose()
            return
        only_shared = [d.name for d in docs if d.share_only]
        if only_shared:
            dialogs.showinfo("Monhip", "„" + "“, „".join(only_shared) + tr(
                '“ kann das Modell nicht lesen – solche Dateien lassen sich nur in Teamwork teilen. Bitte entfernen'
                ' (✕).'))
            return
        if pics and self.server.model and not self.server.vision:
            dialogs.showinfo("Monhip", tr(
                'Das geladene Modell kann keine Bilder ansehen. Dafür muss neben dem Modell eine mmproj-Datei '
                'liegen und unter Einstellungen → Laden „Bildverständnis laden“ eingeschaltet sein – dann das '
                'Modell neu laden.'))
            return
        prepared = self._prepare_turn()
        if not prepared:
            return

        if self.chat_data is None:
            self.chat_data = chats.new_chat()
            self.chat_data["title"] = chats.make_title(text or docs[0].name)
            self._set_title(self.chat_data["title"])

        try:  # Bilder zum Chat kopieren (chats/bilder/<id>/), damit sie auch später noch ans Modell gehen
            rels = [chats.store_image(self.chat_data["id"], d.path, d.thumb) for d in pics]
        except OSError as e:
            dialogs.showerror("Monhip", tr('Bild konnte nicht gespeichert werden: {0}', e))
            return
        self.input.delete("1.0", tk.END)
        content, files_meta = self._compose_message(text, [d for d in docs if not d.image])
        files_meta += [{"name": d.name, "info": d.info, "image": rel} for d, rel in zip(pics, rels)]
        self._clear_compose()
        self.view.user(text, self._display_files(files_meta), quote, self._msg_actions(len(self.history)))
        msg = {"role": "user", "content": self._with_quote(quote, content), "_time": datetime.now().strftime(TIME_FMT)}
        if docs or quote:  # Anzeige: eigener Text + Kärtchen/Zitat statt des ganzen Modelltexts
            msg["_text"] = text
        if docs:
            msg["_files"] = files_meta
        if quote:
            msg["_quote"] = quote
        if rels:
            msg["_images"] = rels
        self.history.append(msg)
        self._save_chat()
        self._launch_turn(*prepared)

    def _prepare_turn(self):
        """Prüft, ob eine Antwort gestartet werden kann, und baut die Werkzeuge. → (params, agent) oder None."""
        if not self.server.is_running() or not self.server.model:
            dialogs.showinfo("Monhip", tr('Bitte zuerst oben rechts ein Modell laden.'))
            return None
        try:
            params = {"temperature": float(self.temp_var.get()), "max_tokens": int(self.maxtok_var.get())}
        except ValueError:
            dialogs.showerror("Monhip", tr('Temperatur / Max. Tokens ungültig (Einstellungen → Laden).'))
            return None

        if (self.agent_var.get() or self.cmd_var.get()):
            try:
                Path(self.ws_var.get()).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                dialogs.showerror("Monhip", tr('Arbeitsordner nicht verfügbar: {0}', e))
                return None
        return params, self._make_agent()

    def _make_agent(self) -> Agent | None:
        """Werkzeuge nach den aktuellen Einstellungen (ohne Prüfungen – die macht _prepare_turn)."""
        files, commands, web_access = self.agent_var.get(), self.cmd_var.get(), self.web_var.get()
        mem, rem = self.memory_var.get(), self.reminder_var.get()
        shots = self.screen_var.get() and self.server.vision
        expert = (self.chat_data or {}).get("experte")
        library = experte.Library(Path(expert["quelle"])) if expert else None  # Experten-Chat: Dokumente durchsuchen
        if not (files or commands or web_access or mem or rem or shots or library):
            return None
        return Agent(self._confirm_from_worker, files=files, commands=commands, workspace=self.ws_var.get(),
                     folders=self.extra_folders, confirm_actions=self.confirm_var.get(),
                     web_access=web_access, brave_key=self.brave_var.get(), memory=mem, reminders=rem,
                     vision=self.server.vision, screenshot=self._screenshot_from_worker if shots else None,
                     expert=library, expert_start=self._expert_from_worker, git=self.git_var.get())

    def _system_prompt(self, agent: Agent | None) -> str:
        system = self.sys_text.get("1.0", tk.END).strip()
        system += "\n\n" + date_line("die Uhrzeit steht am Ende jeder Nachricht")  # ohne Uhrzeit, siehe date_line
        return (system + "\n\n" + agent.system_prompt()).strip() if agent else system.strip()

    def _image_tokens(self) -> int:
        """Höchstens so viele Tokens kostet ein Bild im Verlauf (0 ohne Bildverständnis)."""
        if not self.server.vision:
            return 0
        try:
            return int(self.imgtok_var.get())
        except ValueError:
            return DEFAULTS["image_tokens"]

    def _launch_turn(self, params: dict, agent: Agent | None):
        """Lässt das Modell auf den Verlauf antworten (im Hintergrund-Thread; Ergebnis kommt als „done“). Wird der
        Kontext knapp, fasst context.Window vorher die älteren Nachrichten zusammen (Ereignis „compressed“) – auch noch
        mitten in der Antwort, wenn der Server „Kontext voll“ meldet."""
        self.turn = {"step": 0, "think": None, "thinks": [], "tool": None, "tps": None}
        if self.expert_job:  # Auswertung wartet, solange das Modell antwortet (beide teilen es sich)
            self.expert_job.pause_chat.set()
        system = self._system_prompt(agent)
        api_msgs = [self._api_message(m) for m in self.history]
        history = self.history  # bleibt bis „done“ unverändert (Bearbeiten/Fassungen sind solange gesperrt)

        self._set_busy(True)
        self.stop_event.clear()
        base_url = self.server.base_url
        n_ctx = self._ctx_value()
        budget = tool_budget(n_ctx)  # ältere Werkzeug-Ergebnisse beim Senden kürzen
        auto, image_tokens, tools = self.compress_var.get(), self._image_tokens(), agent.tools if agent else None
        put = lambda k, t: self.events.put((k, t))
        window = context.Window(base_url, system, history, api_msgs, tools, n_ctx, params.get("max_tokens") or 0,
                                image_tokens, self.stop_event, put, auto, budget)

        def work():
            try:
                messages = window.begin()  # fasst vor dem Senden zusammen, wenn der Verlauf zu voll ist
            except Exception as e:  # z. B. Server beim Zählen nicht erreichbar – dann eben ohne Zusammenfassen
                put("error", tr('Kontext konnte nicht geprüft werden: {0}', e))
                messages = window.plain()
            if self.stop_event.is_set():  # beim Zusammenfassen gestoppt
                put("done", [])
                return
            n_before = len(messages)
            try:
                # meldet der Server mitten in der Antwort „Kontext voll“, komprimiert window und der Schritt
                # wird wiederholt – die KI macht von selbst weiter
                run_conversation(base_url, messages, params, agent, self.stop_event, put, budget=budget,
                                 prepare=window.prepare, on_overflow=window.overflow)
            except Exception as e:
                put("error", error_text(e))
            # Neue Nachrichten (Antworten, Tool-Ergebnisse) in den Verlauf übernehmen
            put("done", messages[n_before:])

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------------- Experten-Modus (experte.py)

    def _toggle_expert(self):
        """Häkchen „Experten-Modus“: an → Ordner wählen und Auswertung starten, aus → Chat wieder normal."""
        ok = self._expert_on() if self.expert_var.get() else self._expert_off()
        if not ok:  # abgebrochen: Häkchen zurück
            self.expert_var.set(not self.expert_var.get())

    def _expert_on(self) -> bool:
        if self.busy:
            dialogs.showinfo(tr('Experten-Modus'), tr('Bitte warten, bis die laufende Antwort fertig ist.'))
            return False
        if not (self.server.is_running() and self.server.model):
            dialogs.showinfo(tr('Experten-Modus'), tr('Zuerst oben rechts ein Modell laden – es wertet die Dokumente aus.'))
            return False
        if self.expert_job:
            dialogs.showinfo(tr(
                'Experten-Modus'), tr(
                'Es läuft schon eine Auswertung („{0}“). Bitte warten, bis sie fertig ist, oder sie unten im '
                'Fenster stoppen.',
                self.expert_job.source.name))
            return False
        choice = self._expert_dialog()
        if not choice:
            return False
        folder, focus = choice
        if self.chat_data is None:  # neuer Chat: heißt wie der Ordner
            self.chat_data = chats.new_chat()
            self.chat_data["title"] = folder.name or str(folder)
            self._set_title(self.chat_data["title"])
        self.chat_data["experte"] = {"quelle": str(folder), "schwerpunkt": focus}
        self._save_chat()
        if not self.history:
            self._show_placeholder()
        self._start_expert_job()
        return True

    def _expert_off(self) -> bool:
        cfg = (self.chat_data or {}).get("experte")
        if not cfg:
            return True
        if self.busy:
            dialogs.showinfo(tr('Experten-Modus'), tr('Bitte warten, bis die laufende Antwort fertig ist.'))
            return False
        if self.expert_job and self._expert_job_chat == self.chat_data["id"]:
            if not dialogs.askyesno(tr(
                'Experten-Modus beenden'), tr(
                'Die Auswertung läuft noch. Anhalten und den Experten-Modus für diesen Chat beenden?\n\nDie '
                'bisherigen Ergebnisse bleiben erhalten – beim erneuten Einschalten geht es dort weiter.')):
                return False
            self.expert_job.stop_event.set()
        self.chat_data.pop("experte", None)
        self._save_chat(touch=False)
        if self.view.is_placeholder:
            self._show_placeholder()
        self._update_expert_row()
        return True

    def _expert_dialog(self) -> tuple[Path, str] | None:
        """Ordner wählen, dann kurzer Dialog mit Anzahl der Dokumente und optionalem Schwerpunkt."""
        chosen = filedialog.askdirectory(title=tr('Ordner mit den Dokumenten wählen'), parent=self.root)
        if not chosen:
            return None
        folder = Path(chosen).resolve()
        count = len(experte.find_documents(folder))
        if not count:
            dialogs.showinfo(tr(
                'Experten-Modus'), tr(
                'In diesem Ordner wurden keine lesbaren Dokumente gefunden (PDF, Word, Excel, PowerPoint, '
                'OpenDocument, RTF, Text).'))
            return None
        status = experte.status_of(folder)
        if status:
            about = (tr('{0} Dokumente – {1} davon sind schon ausgewertet; neue und geänderte werden ergänzt.', count, status['ok']))
        else:
            about = (tr(
                '{0} Dokumente. Jedes wird einzeln vom geladenen Modell zusammengefasst und für die Suche erfasst –'
                ' bei vielen Dateien kann das Stunden dauern. Fragen gehen schon währenddessen.',
                count))
        win = dialogs.window(tr('Experten-Modus'), self.root)
        body = ttk.Frame(win, padding=18)
        body.pack(fill=tk.BOTH, expand=True)
        wrap = round(460 * self.ui_scale)
        ttk.Label(body, text=tr('Experten-Modus'), style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text=str(folder), wraplength=wrap).pack(anchor="w", pady=(8, 0))
        ttk.Label(body, text=about, style="Muted.TLabel", wraplength=wrap).pack(anchor="w", pady=(4, 12))
        ttk.Label(body, text=tr('Schwerpunkt (optional)')).pack(anchor="w")
        focus = tk.StringVar(value=(status or {}).get("schwerpunkt", ""))
        entry = ttk.Entry(body, textvariable=focus, width=58)
        entry.pack(fill=tk.X, pady=(4, 2))
        ttk.Label(body, text=tr(
            'Zum Beispiel „Kündigungsfristen“ – jede Zusammenfassung arbeitet das zusätzlich heraus. Ein geänderter'
            ' Schwerpunkt wertet alle Dokumente neu aus.'), style="Muted.TLabel",
                  wraplength=wrap).pack(anchor="w")
        result = {}

        def start(_e=None):
            result["focus"] = focus.get().strip()
            win.destroy()

        bf = ttk.Frame(body)
        bf.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(bf, text=tr('Abbrechen'), command=win.destroy).pack(side=tk.RIGHT)
        ttk.Button(bf, text=tr('Auswertung starten'), style="Accent.TButton", command=start).pack(side=tk.RIGHT,
                                                                                            padx=(0, 6))
        entry.bind("<Return>", start)
        win.bind("<Escape>", lambda e: win.destroy())
        dialogs.present(win, self.root, modal=True, focus=entry)
        return (folder, result["focus"]) if "focus" in result else None

    def _start_expert_job(self, cfg: dict | None = None):
        """Auswertung für den Experten-Chat starten bzw. fortsetzen (fertige Dokumente werden übersprungen)."""
        cfg = cfg or (self.chat_data or {}).get("experte")
        if not cfg or self.expert_job:
            return
        if not (self.server.is_running() and self.server.model):
            dialogs.showinfo(tr('Experten-Modus'), tr('Zum Fortsetzen zuerst oben rechts ein Modell laden.'))
            return
        holder = {}
        job = experte.Job(Path(cfg["quelle"]), self.server.base_url, self._ctx_value(), self.server.vision,
                          cfg.get("schwerpunkt", ""), lambda k, d: self.ui(self._expert_event, holder["job"], k, d))
        holder["job"] = job
        self.expert_job, self._expert_job_chat = job, self.chat_data["id"]
        self._expert_text, self._expert_paused = tr('Auswertung „{0}“ beginnt …', job.source.name), False
        if self.busy:  # gestartet von der KI mitten in einer Antwort
            job.pause_chat.set()
        job.start()
        self._update_expert_row()

    def _expert_event(self, job, kind: str, data):
        """Fortschritt der Auswertung (aus dem Job-Thread über self.ui)."""
        if job is not self.expert_job:
            return
        name = job.source.name
        if kind == "start":
            self._expert_text = (tr('Auswertung „{0}“: {1} von {2} Dokumenten', name, data['total'] - data['todo'], data['total'])
                                 if data["todo"] else tr('Auswertung „{0}“: alles aktuell, Überblick wird geprüft', name))
        elif kind == "file":
            if data["rel"]:
                self._expert_text = (tr(
                    'Auswertung „{0}“: {1} von {2} · {3}{4}',
                    name,
                    data['done'],
                    data['total'],
                    Path(data['rel']).name,
                    self._eta_text(data.get('eta'))))
            else:
                self._expert_text = tr('Auswertung „{0}“: Gesamtüberblick wird erstellt', name)
        elif kind == "page":  # eingescanntes PDF: Seite für Seite
            self._expert_text = (tr(
                'Auswertung „{0}“: {1} von {2} · {3} · Seite {4} von {5}{6}',
                name,
                data['done'],
                data['total'],
                Path(data['rel']).name,
                data['page'],
                data['pages'],
                self._eta_text(data.get('eta'))))
        elif kind in ("paused", "resumed"):
            self._expert_paused = kind == "paused"
        elif kind in ("finished", "stopped", "fatal"):
            self.expert_job = None
            if kind == "fatal":
                note = str(data)
            else:
                extras = [f"{data[k]} {label}" for k, label in (("scan", tr('Scans ohne Bildverständnis nicht gelesen')),
                                                                 ("fehler", tr('nicht lesbar')), (tr('leer'), tr('ohne Text')))
                          if data.get(k)]
                note = ((tr(
                    'Auswertung abgeschlossen: {0} von {1} Dokumenten in „{2}“ ausgewertet',
                    data['ok'],
                    data['total'],
                    name) if kind == "finished" else
                         tr(
                             'Auswertung gestoppt: {0} von {1} Dokumenten in „{2}“ ausgewertet – „Fortsetzen“ macht'
                             ' dort weiter',
                             data['ok'],
                             data['total'],
                             name)) + (f" ({', '.join(extras)})" if extras else "") + ".")
            if self.chat_data and self.chat_data["id"] == self._expert_job_chat and not self.busy:
                self.view.note(note, "warn" if kind == "fatal" else "note")
        self._update_expert_row()

    @staticmethod
    def _eta_text(eta: float | None) -> str:
        """„ · noch ca. 12 Min.“ bzw. „ · noch ca. 2,5 Std.“ (leer, solange die Restzeit unbekannt ist)."""
        if eta is None:
            return ""
        return (tr(' · noch ca. {0} Std.', f'{eta / 3600:.1f}'.replace('.', ',')) if eta >= 5400
                else tr(' · noch ca. {0} Min.', max(1, round(eta / 60))))

    def _update_expert_row(self):
        """Leiste unten links: Häkchen nach dem Chat, Fortschritt bzw. Stand, passende Verweise."""
        if self.mode == "room":
            self.expert_bar.pack_forget()
            return
        if not self.expert_bar.winfo_ismapped():
            self.expert_bar.pack(side=tk.LEFT)
        cfg = (self.chat_data or {}).get("experte")
        self.expert_var.set(bool(cfg))
        for w in self.expert_links.winfo_children():
            w.destroy()
        job = self.expert_job
        if job:
            # Zusatz erst hier: ein schon unterwegs befindlicher Fortschritt überschreibt ihn sonst
            pause = (tr(' · angehalten') if self._expert_paused else tr(' · wird angehalten …')) if job.pause_user.is_set() else ""
            self.expert_status.set(self._expert_text + pause)
            self._expert_link(tr('Fortsetzen') if job.pause_user.is_set() else tr('Pausieren'), self._expert_pause)
            self._expert_link(tr('Stoppen'), lambda: job.stop_event.set())
            return
        if not cfg:
            self.expert_status.set("")
            return
        folder = Path(cfg["quelle"])
        st = experte.status_of(folder)
        if not folder.is_dir():
            self.expert_status.set(tr('Ordner „{0}“ nicht gefunden', folder.name))
        elif st and st["fertig"]:
            self.expert_status.set(tr('Experte für „{0}“ · {1} Dokumente', folder.name, st['ok']))
            self._expert_link(tr('Aktualisieren'), self._start_expert_job)
        else:
            self.expert_status.set(tr(
                'Auswertung „{0}“ unvollständig ({1} von {2})',
                folder.name,
                st['ok'] if st else 0,
                st['dateien'] if st and st['dateien'] else '…'))
            self._expert_link(tr('Fortsetzen'), self._start_expert_job)

    def _expert_link(self, text: str, command):
        link = ttk.Label(self.expert_links, text=text, style="Muted.TLabel", font=(FAMILY, 8, "underline"),
                         cursor="hand2")
        link.pack(side=tk.LEFT, padx=(8, 0))
        link.bind("<Button-1>", lambda e: command())

    def _expert_pause(self):
        job = self.expert_job
        if job:
            if job.pause_user.is_set():
                job.pause_user.clear()
            else:
                job.pause_user.set()
            self._update_expert_row()

    def _expert_from_worker(self, folder: Path, focus: str) -> str:
        """Werkzeug ordner_auswerten (im Agenten-Thread): den Chat im Tk-Thread zum Experten-Chat machen."""
        done, box = threading.Event(), {}

        def run():
            try:
                box["msg"] = self._expert_start_from_ai(folder, focus)
            except Exception as e:
                box["msg"] = tr('Fehler: {0}', e)
            finally:
                done.set()

        self.ui(run)
        done.wait()
        return box["msg"]

    def _expert_start_from_ai(self, folder: Path, focus: str) -> str:
        if self.expert_job:
            return (f"Fehler: Es läuft schon eine Auswertung („{self.expert_job.source.name}“) – erst danach ist eine "
                    "weitere möglich.")
        count = len(experte.find_documents(folder))
        if not count:
            return "Fehler: In diesem Ordner gibt es keine lesbaren Dokumente."
        if self.chat_data is None:
            return "Fehler: Kein Chat geöffnet."
        self.chat_data["experte"] = {"quelle": str(Path(folder).resolve()), "schwerpunkt": focus}
        self._save_chat(touch=False)
        self._start_expert_job()
        return (f"Experten-Modus gestartet: {count} Dokumente in „{Path(folder).name}“ werden im Hintergrund "
                "ausgewertet (Fortschritt unten im Fenster). Die Werkzeuge zum Durchsuchen gibt es ab der nächsten "
                "Nachricht; ausgewertete Dokumente sind sofort durchsuchbar.")

    # ---------------------------------------------------------------- Kontextanzeige

    @staticmethod
    def _summary_title(count: int) -> str:
        return tr('Ältere Unterhaltung zusammengefasst  ·  {0} Nachrichten', count)

    def _estimate_context(self):
        """Kontextanzeige für den gezeigten Chat neu bestimmen (zählt im Hintergrund mit dem Server). Genaue
        Werte kommen nach jeder Antwort vom Server („usage“)."""
        self._meter_gen += 1
        gen, self._ctx = self._meter_gen, (None, False)
        self._draw_meter()
        if not (self.server.is_running() and self.server.model and self.server.n_ctx):
            return
        agent = self._make_agent()
        start, summary = context.latest_summary(self.history)
        msgs = [{"role": "system", "content": context.with_summary(self._system_prompt(agent), summary)}] + \
            [self._api_message(m) for m in self.history[start:]]
        base_url, tools, image_tokens = self.server.base_url, agent.tools if agent else None, self._image_tokens()

        def done(total, err):
            if gen == self._meter_gen and not err:
                self._ctx = (total, False)
                self._draw_meter()

        self.background(lambda: context.measure(base_url, msgs, tools, image_tokens)[0], done)

    def _set_context(self, used: int):
        self._meter_gen += 1
        self._ctx = (used, True)
        self._draw_meter()

    def _fix_meter_height(self):
        """Zeile unter der Eingabe mit fester Höhe: Der Moduswechsel blendet das Experten-Häkchen aus und ein – änderte
        sich dabei ihre Höhe, vermaß Tk jedes Mal den ganzen Chatverlauf neu (~13 ms bei einem langen Chat)."""
        m = self._meter
        m.update_idletasks()
        m.configure(height=max(w.winfo_reqheight() for w in m.winfo_children()) + 6)  # + Innenabstand unten
        m.pack_propagate(False)

    def _draw_meter(self):
        """„Kontext 9.800 / 16.384 · 60 %“ mit kleinem Balken (grün, ab 75 % orange, ab 90 % rot). Im Teamwork der
        Kontext der eigenen KI (RoomMode.ctx)."""
        c = self.ctx_bar
        c.delete("all")
        if self.theme.pal:
            bg = self.theme.pal["bg"]
        else:
            bg = "#%02x%02x%02x" % tuple(v // 257 for v in self.root.winfo_rgb(self.root.cget("background")))
        c.configure(background=bg)
        total = self.server.n_ctx if self.server.model else None
        room = self.mode == "room"
        used, exact = self.room.ctx if room else self._ctx
        if self.mode not in ("chat", "room") or not total or (room and not self.room.connected):
            self.ctx_text.set("")
            return
        fmt = lambda n: f"{n:,}".replace(",", ".")
        label = tr('Kontext deiner KI') if room else tr('Kontext')
        if used is None:
            self.ctx_text.set(f"{label} … / {fmt(total)}")
            return
        frac = min(1.0, used / total)
        self.ctx_text.set(f"{label} {'' if exact else '≈ '}{fmt(used)} / {fmt(total)}  ·  {round(frac * 100)} %")
        col = self.theme_chat()
        color = col["ok"] if frac < 0.75 else col["warn"] if frac < 0.9 else col["error"]
        w, h = int(c.cget("width")), int(c.cget("height"))
        track = mix_hex(bg, col["muted"], 0.35)
        rounded(c, self._meter_cache, 0, 0, w, h, h // 2, track, bg)
        if frac > 0:
            rounded(c, self._meter_cache, 0, 0, max(h, w * frac), h, h // 2, color, track)

    # ---------------------------------------------------------------- Bearbeiten, Kopieren, Zitieren

    def _msg_actions(self, index: int) -> dict:
        """„Kopieren“/„Bearbeiten“ unter der eigenen Nachricht Nummer index im Verlauf – und „‹ 2/3 ›“, wenn es
        von ihr mehrere Fassungen gibt."""
        m = self.history[index] if index < len(self.history) else {}
        actions = {"on_edit": lambda new_text: self.edit_message(index, new_text)}
        if m.get("_variants"):
            actions["versions"] = (m.get("_variant", 0), len(m["_variants"]))
            actions["on_version"] = lambda k: self.switch_version(index, k)
        return actions

    def _tail(self, index: int) -> list[dict]:
        """Verlauf ab Nachricht index als aufbewahrte Fassung (ohne die Fassungs-Liste selbst)."""
        first = {k: v for k, v in self.history[index].items() if k not in ("_variants", "_variant")}
        return [first] + self.history[index + 1:]

    def switch_version(self, index: int, k: int):
        """Zu einer anderen Fassung einer bearbeiteten Nachricht wechseln – samt allen Antworten danach.
        Fassungen liegen in der Nachricht: `_variants` = Verläufe ab hier; an der Stelle `_variant` (der gerade
        gezeigten) steht None, weil diese Fassung im Verlauf selbst steht."""
        if self.busy:
            dialogs.showinfo("Monhip", tr('Bitte warten, bis die laufende Antwort fertig ist (oder „Stopp“).'))
            return
        m = self.history[index] if 0 <= index < len(self.history) else {}
        variants, cur = list(m.get("_variants") or []), m.get("_variant", 0)
        if not 0 <= k < len(variants) or k == cur or not variants[k]:
            return
        variants[cur] = self._tail(index)
        target, variants[k] = variants[k], None
        self.history = self.history[:index] + [{**target[0], "_variants": variants, "_variant": k}] + target[1:]
        y = self.chat.yview()[0]
        self._save_chat(touch=False)  # Fassung wechseln ändert nicht die Reihenfolge der Chats
        self._render_history()
        self.view.scroll_to(y)

    def edit_message(self, index: int, new_text: str) -> bool:
        """Eigene Nachricht ändern: Die bisherige Fassung samt allem danach bleibt als Version erhalten (‹ 1/2 ›),
        das Modell antwortet auf die neue. False = nicht möglich (das Bearbeitungsfeld bleibt offen)."""
        if self.busy:
            dialogs.showinfo("Monhip", tr('Bitte warten, bis die laufende Antwort fertig ist (oder „Stopp“).'))
            return False
        if not (0 <= index < len(self.history)) or self.history[index].get("role") != "user":
            return False
        prepared = self._prepare_turn()
        if not prepared:
            return False
        old = self.history[index]
        old_text = old.get("_text", old.get("content") or "")
        old_head = self._with_quote(old.get("_quote"), old_text)
        content = old.get("content") or ""
        docs_part = content[len(old_head):].lstrip("\n") if content.startswith(old_head) else ""
        new_head = self._with_quote(old.get("_quote"), new_text)
        msg = {**old, "content": "\n\n".join(p for p in (new_head, docs_part) if p),
               "_time": datetime.now().strftime(TIME_FMT)}
        if "_text" in old:
            msg["_text"] = new_text
        # Bisherige Fassung samt Antworten als Version aufheben (‹ 1/2 ›); die neue ist die letzte
        variants = list(old.get("_variants") or [None])
        variants[old.get("_variant", 0)] = self._tail(index)
        msg["_variants"], msg["_variant"] = variants + [None], len(variants)
        self.history = self.history[:index] + [msg]
        self._save_chat()
        self._render_history()
        self._launch_turn(*prepared)
        return True

    @staticmethod
    def _with_quote(quote: str | None, text: str) -> str:
        """So geht ein Zitat („Antworten“) ans Modell: als Block vor dem eigenen Text."""
        if not quote:
            return text
        block = "Ich beziehe mich auf diese Stelle deiner Antwort:\n" + "\n".join(
            "> " + ln for ln in quote.strip().splitlines())
        return f"{block}\n\n{text}" if text else block

    def _clear_compose(self):
        self.attachments.clear()
        self.quote = None
        self._render_attachments()

    def set_quote(self, text: str):
        """„Antworten“ auf eine markierte Stelle: Zitat über dem Eingabefeld, geht mit der nächsten Nachricht mit."""
        self.quote = text.strip()[:2000]
        self._render_attachments()
        self.input.focus_set()

    def _confirm_from_worker(self, title, text) -> str:
        """Wird im Hintergrund-Thread aufgerufen und wartet auf die Antwort: "yes", "no" oder "all"."""
        done, box = threading.Event(), {}
        self.events.put(("confirm", (title, text, done, box)))
        done.wait()
        return box.get("answer", "no")

    def ask_confirm(self, title: str, text: str) -> str:
        """Bestätigungsdialog im aktuellen Design mit Vorschau (z. B. Dateiinhalt oder Befehl)."""
        win = dialogs.window(title, self.root, resizable=True)
        body = ttk.Frame(win, padding=16)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=title, style="Title.TLabel").pack(anchor="w")
        ttk.Label(body, text=tr('Das Modell möchte folgende Aktion ausführen:'), style="Muted.TLabel").pack(
            anchor="w", pady=(2, 8))
        lines = text.count("\n") + 1
        frame, box = scrolled(body, wrap=tk.WORD, width=88, height=max(4, min(lines + 1, 18)),
                              font=("Consolas", 9), padx=8, pady=6)
        frame.pack(fill=tk.BOTH, expand=True)
        box.insert("1.0", text)
        box.configure(state=tk.DISABLED)
        self.theme.register_text(box)
        result = {"answer": "no"}

        def answer(value):
            result["answer"] = value
            win.destroy()

        bf = ttk.Frame(body)
        bf.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(bf, text=tr('Ablehnen'), command=lambda: answer("no")).pack(side=tk.RIGHT)
        ttk.Button(bf, text=tr('Alle erlauben'), command=lambda: answer("all")).pack(side=tk.RIGHT, padx=(0, 6))
        ok = ttk.Button(bf, text=tr('Erlauben'), style="Accent.TButton", command=lambda: answer("yes"))
        ok.pack(side=tk.RIGHT, padx=(0, 6))
        ttk.Label(bf, text=tr('„Alle erlauben“ gilt bis zum Ende dieser Antwort.'), style="Muted.TLabel").pack(
            side=tk.LEFT)
        win.bind("<Escape>", lambda e: answer("no"))
        win.protocol("WM_DELETE_WINDOW", lambda: answer("no"))
        dialogs.present(win, self.root, modal=True, focus=ok)
        return result["answer"]

    # ================================================================ Event-Schleife

    STREAM_EVENTS = {"assistant_start", "reasoning", "content", "tool_call", "tool_result", "stats", "info",
                     "error", "confirm", "done", "usage", "compress", "compressed", "context_full"}

    def _poll_events(self):
        """Ereignisse aus den Threads abholen. Die nächste Runde wird zuerst geplant, damit es auch weitergeht,
        während ein Handler einen Dialog offen hält (verschachtelte Ereignisschleife)."""
        fast = self.busy or self.stream_q or self.room.ai_busy  # während einer Antwort flüssiger
        self.root.after(15 if fast else 50, self._poll_events)
        logs = []
        try:
            while True:
                kind, data = self.events.get_nowait()
                if kind == "log":       # beim Laden kommen Hunderte Zeilen → gesammelt einfügen
                    logs.append(data)
                elif kind in self.STREAM_EVENTS:
                    self.stream_q.append((kind, data))
                else:
                    self._handle(kind, data)
        except queue.Empty:
            pass
        if logs:
            self._append_log("".join(logs))
        self._drain_stream()

    def _drain_stream(self):
        """Gibt pro Durchlauf nur einen Teil des Textes aus – je größer der Rückstand, desto mehr.
        So erscheint die Antwort gleichmäßig statt in Schüben."""
        if self._draining or not self.stream_q:
            return
        self._draining = True
        try:
            q = self.stream_q
            backlog = sum(len(d) for k, d in q if k == "content")
            budget = max(3, -(-backlog // 6))
            text, reasoning = [], []

            def flush():
                if reasoning:
                    self._on_reasoning("".join(reasoning))
                    reasoning.clear()
                if text:
                    self._on_content("".join(text))
                    text.clear()

            while q:
                kind, data = q[0]
                if kind == "content":
                    if budget <= 0:
                        break
                    if reasoning:
                        flush()
                    piece = data[:budget]
                    if len(piece) < len(data):
                        q[0] = (kind, data[len(piece):])
                    else:
                        q.popleft()
                    budget -= len(piece)
                    text.append(piece)
                elif kind == "reasoning":
                    if text:
                        flush()
                    q.popleft()
                    reasoning.append(data)
                else:
                    flush()
                    q.popleft()
                    self._handle_stream(kind, data)
            flush()
        finally:
            self._draining = False

    def _on_reasoning(self, data: str):
        if self.turn.get("think") is None:
            if not data.strip():  # nur Leerzeichen/Zeilenumbrüche: (noch) keinen Block anlegen
                return
            self.turn["think"] = self.view.think_begin()
            self.turn["think_step"] = self.turn.get("step", 0)
        self.view.think_append(self.turn["think"], data)

    def _on_content(self, data: str):
        self._close_think()
        self.view.md_append(data)

    def _close_think(self):
        n = self.turn.get("think")
        if n is not None:
            secs = self.view.think_end(n)
            self.turn.setdefault("thinks", []).append((n, self.turn.get("think_step", 0), secs))
            self.turn["think"] = None

    def _handle_stream(self, kind, data):
        view = self.view
        if kind == "assistant_start":
            self._close_think()
            view.md_finish()
            self.turn["step"] = self.turn.get("step", 0) + 1
            view.show_pending()
        elif kind == "tool_call":
            self._close_think()
            name, args = data
            icon, label, detail = describe_call(name, args)
            self.turn["tool"] = view.tool_begin(label, detail, format_args(args), icon)
        elif kind == "tool_result":
            if self.turn.get("tool") is not None:
                view.tool_end(self.turn["tool"], data, result_ok(data))
                self.turn["tool"] = None
        elif kind == "stats":
            self.turn["tps"] = data
        elif kind == "usage":
            self._set_context(data)
        elif kind == "context_full":  # mitten in der Antwort – statt der Server-Fehlermeldung
            self._close_think()
            view.hide_pending()
            view.note(tr(context.FULL_NOTE), "warn")
            view.show_pending(tr('Komprimiere die Unterhaltung …'))
        elif kind == "compress":
            view.hide_pending()
            view.show_pending(tr('Fasse ältere Unterhaltung zusammen …'))
        elif kind == "compressed":  # Zusammenfassung an die erste vollständige Nachricht hängen (wird gespeichert)
            index, summary, count = data
            if 0 <= index < len(self.history):
                self.history[index]["_summary_before"] = summary
                self.history[index]["_summary_count"] = count
                self._save_chat(touch=False)
            view.hide_pending()
            view.think_static(summary, self._summary_title(count), icon="≡")
        elif kind == "info":
            self._close_think()
            view.note(data)
        elif kind == "error":
            self._close_think()
            view.note(tr('Fehler: {0}', data), "error")
        elif kind == "confirm":
            title, text, done, box = data
            box["answer"] = self.ask_confirm(title, text)
            done.set()
        elif kind == "done":
            self._finish_turn(data)

    def _finish_turn(self, new_messages: list):
        if self.expert_job:
            self.expert_job.pause_chat.clear()
        self._close_think()
        self.view.hide_pending()
        self.view.md_finish()
        for m in new_messages:  # Bilder aus view_image/take_screenshot zum Chat kopieren, wie angehängte Bilder
            shown = m.pop("_image_files", None)
            if shown and self.chat_data:
                rels = []
                for f in shown:
                    try:
                        rels.append(chats.store_image(self.chat_data["id"], Path(f)))
                    except OSError:
                        pass
                if rels:
                    m["_images"] = rels
        self.history.extend(new_messages)
        self._fill_memory()  # das Modell hat evtl. etwas gemerkt oder eine Erinnerung gestellt
        assistants = [m for m in new_messages if m.get("role") == "assistant"]
        jobs = []
        for n, step, secs in self.turn.get("thinks", []):
            if 0 < step <= len(assistants):
                msg = assistants[step - 1]
                msg["_thinking_secs"] = secs
                if len(msg.get("_thinking", "")) >= 40:  # für ein paar Wörter lohnt keine Überschrift
                    jobs.append((n, msg))
        if self.stop_event.is_set():
            self.view.note(tr('[gestoppt]'))
        last = assistants[-1] if assistants else None
        if last and last.get("content") and not last.get("tool_calls"):
            self.view.footer(last["content"], self.turn.get("tps"))
        self._set_busy(False)
        self._save_chat()
        if jobs and self.think_title_var.get():
            self._make_think_titles(jobs)

    def _make_think_titles(self, jobs: list):
        """Lässt das Modell im Hintergrund eine kurze Überschrift für jeden Denkprozess formulieren."""
        if not self.server.is_running():
            return
        base_url, gen, chat = self.server.base_url, self.view.gen, self.chat_data
        items = [(n, msg, msg["_thinking"]) for n, msg in jobs]

        def work():
            for n, msg, text in items:
                try:
                    title = thinking_title(base_url, text)
                except Exception:
                    title = ""
                if title:
                    self.ui(self._set_think_title, gen, n, msg, chat, title)

        threading.Thread(target=work, daemon=True).start()

    def _handle(self, kind, data):
        if kind == "call":
            fn, args = data
            fn(*args)
        elif kind == "room":            # vom Gastgeber (RoomClient-Thread)
            self.room.on_client_event(*data)
        elif kind == "room_ai":         # Antwort der eigenen KI im Raum
            self.room.on_ai_event(data)
        elif kind == "room_ready":      # Raum erstellt / beigetreten (oder Fehler)
            self.room.on_ready(data)

    def _append_log(self, text: str):
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, text)
        if int(self.log.index("end-1c").split(".")[0]) > 5000:
            self.log.delete("1.0", "1000.0")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _set_think_title(self, gen: int, n: int, msg: dict, chat: dict | None, title: str):
        msg["_thinking_title"] = title
        if gen == self.view.gen:
            self.view.set_think_title(n, title)
        try:
            if chat is self.chat_data:
                if not self.busy:  # sonst wird ohnehin nach der laufenden Antwort gespeichert
                    chats.save(chat, touch=False)
            elif chat and chats.exists(chat["id"]):
                chats.save(chat, touch=False)
        except OSError:
            pass

    # ================================================================ Modell herunterladen

    def open_download(self):
        if self.dl_win and self.dl_win.winfo_exists():
            self.dl_win.lift()
            return
        win = self.dl_win = dialogs.window(tr('Modell herunterladen'), self.settings_win)
        body = ttk.Frame(win, padding=10)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=tr('Direktlink zu einer .gguf-Datei (z.B. Hugging Face → Files → Datei → Link kopieren):')
                  ).pack(anchor="w", pady=(0, 2))
        url_var = tk.StringVar()
        entry = ttk.Entry(body, textvariable=url_var)
        entry.pack(fill=tk.X)
        ttk.Label(body, text=tr('Ziel: {0}', MODEL_DIR), style="Muted.TLabel").pack(anchor="w", pady=4)
        self.dl_bar = ttk.Progressbar(body, maximum=100)
        self.dl_bar.pack(fill=tk.X)
        self.dl_label = ttk.Label(body, text="")
        self.dl_label.pack(anchor="w")
        cancel = threading.Event()

        def close():
            cancel.set()
            win.destroy()

        def start():
            if self._download(url_var.get().strip(), cancel):
                start_btn.configure(state=tk.DISABLED)

        bf = ttk.Frame(body)
        bf.pack(pady=(6, 0))
        start_btn = ttk.Button(bf, text=tr('Herunterladen'), style="Accent.TButton", command=start)
        start_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(bf, text=tr('Abbrechen'), command=close).pack(side=tk.LEFT, padx=4)
        win.protocol("WM_DELETE_WINDOW", close)
        entry.bind("<Return>", lambda e: start_btn.invoke())
        dialogs.present(win, self.settings_win, size=(round(640 * self.ui_scale), round(200 * self.ui_scale)),
                        focus=entry)

    def _download(self, url: str, cancel: threading.Event) -> bool:
        url = url.replace("/blob/", "/resolve/")
        name = url.split("?")[0].rstrip("/").split("/")[-1]
        if not name.lower().endswith(".gguf"):
            dialogs.showerror("Download", tr('Der Link muss auf eine .gguf-Datei zeigen.'), parent=self.dl_win)
            return False
        MODEL_DIR.mkdir(exist_ok=True)
        target = MODEL_DIR / name
        part = target.with_name(name + ".part")
        self._downloads["modell"] = cancel

        def work():
            try:
                downloads.download(url, part, lambda d, n: self.ui(self._dl_update, d, n), cancel)
                part.replace(target)
            except BaseException:
                part.unlink(missing_ok=True)
                raise

        self.background(work, lambda _, err: self._dl_finished(cancel, err))
        return True

    def _dl_update(self, done, total):
        if self.dl_win and self.dl_win.winfo_exists():
            if total:
                self.dl_bar["value"] = done * 100 / total
            self.dl_label.configure(text=f"{done / 1024 ** 3:.2f} / {total / 1024 ** 3:.2f} GB")

    def _dl_finished(self, cancel: threading.Event, err: str | None):
        if self._downloads.get("modell") is cancel:
            del self._downloads["modell"]
        open_win = self.dl_win and self.dl_win.winfo_exists()
        if err:
            if open_win:  # sonst hat der Nutzer selbst abgebrochen
                dialogs.showerror("Download", tr('Fehlgeschlagen: {0}', err), parent=self.dl_win)
            return
        self.refresh_models()
        if open_win:
            self.dl_win.destroy()
        dialogs.showinfo("Download", tr('Modell heruntergeladen und zur Liste hinzugefügt.'))

    # ================================================================ Konfiguration

    def save_config(self):
        server = self._selected_server()
        try:
            ctx = int(self.ctx_var.get())
        except ValueError:
            ctx = self.cfg["ctx"]  # Tippfehler: bisherige Zahl behalten
        self.cfg.update({
            "ui_language": UI_LANGUAGES.get(self.ui_language_var.get(), self.cfg["ui_language"]),
            "server_exe": server["exe"] if server else "",
            "ctx": ctx,
            "ngl": self.ngl_var.get().strip() or "auto",
            "extra_args": self.extra_var.get(),
            "vision": self.vision_var.get(),
            "image_tokens": self.imgtok_var.get().strip(),
            "temperature": self.temp_var.get(),
            "max_tokens": self.maxtok_var.get(),
            "system_prompt": self.sys_text.get("1.0", tk.END).strip(),
            "think_titles": self.think_title_var.get(),
            "auto_compress": self.compress_var.get(),
            "agent_enabled": self.agent_var.get(),
            "agent_commands": self.cmd_var.get(),
            "git_enabled": self.git_var.get(),
            "agent_workspace": self.ws_var.get(),
            "agent_folders": list(self.extra_folders),
            "agent_confirm": self.confirm_var.get(),
            "web_enabled": self.web_var.get(),
            "brave_key": self.brave_var.get().strip(),
            "memory_enabled": self.memory_var.get(),
            "reminders_enabled": self.reminder_var.get(),
            "screenshots_enabled": self.screen_var.get(),
            "speech_model": self._speech_settings()[0],
            "speech_language": self._speech_settings()[1],
            "theme": self.theme.key,
        })
        try:
            CONFIG_FILE.write_text(json.dumps(self.cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def on_close(self):
        self.save_config()
        self.root.withdraw()  # sofort weg – Server beenden und Raum schließen dauert evtl. ein paar Sekunden
        self.stop_event.set()
        if self.expert_job:  # fertige Dateien sind gespeichert, beim nächsten Mal geht es dort weiter
            self.expert_job.stop_event.set()
        for cancel in self._downloads.values():
            cancel.set()
        self.recorder.cancel()
        self.room.ai_stop.set()
        self.room.shutdown()  # Raum verlassen bzw. eigenen Raum schließen (Verlauf bleibt gespeichert)
        prozesse.stop_all()   # Hintergrund-Prozesse des Agenten (Webserver usw.)
        self.server.stop()
        self.root.destroy()


if __name__ == "__main__":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Monhip")  # Taskleiste: eigenes Symbol statt Python
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()
