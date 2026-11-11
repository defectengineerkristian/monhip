"""Seitenleiste „Browser“ rechts im Chat (siehe browser.py): Kopfzeile mit Zurück/Vor/Neu laden/Adresse, darunter
der eingebettete Browser. Wartet das Modell auf den Nutzer (Anmeldung, Captcha), steht oben ein Hinweis mit „Fertig –
weiter“. BrowserTools ist die Seite für das Modell (agent.Agent, im Hintergrund-Thread)."""

from i18n import tr

import threading
import tkinter as tk
import webbrowser
from tkinter import ttk

import browser
import dialogs
import icons
import plattform
from themes import FAMILY

WIDTH_SHARE = 0.5    # höchstens dieser Anteil am Fenster, wenn der Browser aufgeht – der Chat behält dabei seine
MIN_WIDTH, MAX_WIDTH = 420, 980  # Kopfzeile ganz (main_need); so schmal bzw. breit höchstens (Pixel bei 100 %)


class BrowserPanel:
    def __init__(self, app, before, main_need=lambda: 0):
        """before: Hauptbereich (die Leiste liegt rechts daneben); main_need() → so breit muss er mindestens bleiben."""
        self.app = app
        self._main_need = main_need
        self._closing = False
        s = self.s = app.ui_scale
        self.host = browser.Host(on_event=lambda msg: app.ui(self._on_event, msg))
        self.visible = False
        self.url_var = tk.StringVar()
        self._installing = False
        self._answer: threading.Event | None = None   # wartet das Modell gerade auf den Nutzer?
        self._result = ""
        self._before = before

        self.outer = ttk.Frame(app.root, style="Sidebar.TFrame", width=round(620 * s))
        self.outer.pack_propagate(False)
        self.sep = ttk.Separator(app.root, orient=tk.VERTICAL)
        head = self.head = ttk.Frame(self.outer, style="Sidebar.TFrame", padding=(8, 8, 8, 6))
        head.pack(side=tk.TOP, fill=tk.X)
        for name, cmd in (("chev_left", lambda: self._nav("back")), ("chev_right", lambda: self._nav("forward")),
                          ("refresh", lambda: self._nav("reload"))):
            ttk.Button(head, style="Sidebar.TButton", width=3, command=cmd, **icons.only(name)).pack(side=tk.LEFT)
        ttk.Button(head, style="Sidebar.TButton", width=3, command=self.hide, **icons.only("close")).pack(
            side=tk.RIGHT)
        ttk.Button(head, style="Sidebar.TButton", width=3, command=self._external, **icons.only("globe")).pack(
            side=tk.RIGHT, padx=(4, 0))
        self.url_entry = ttk.Entry(head, textvariable=self.url_var)
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
        self.url_entry.bind("<Return>", lambda e: self.navigate(self.url_var.get()))

        # Hinweis, wenn das Modell auf den Nutzer wartet (Anmeldung, Captcha)
        self.banner = ttk.Frame(self.outer, style="Sidebar.TFrame", padding=(12, 4, 8, 8))
        self.banner_var = tk.StringVar()
        ttk.Label(self.banner, textvariable=self.banner_var, style="SidebarText.TLabel", wraplength=round(560 * s),
                  justify=tk.LEFT).pack(side=tk.TOP, anchor="w")
        bb = ttk.Frame(self.banner, style="Sidebar.TFrame")
        bb.pack(side=tk.TOP, anchor="w", pady=(6, 0))
        ttk.Button(bb, text=tr('Fertig – weiter'), style="Accent.TButton", command=lambda: self._finish(True),
                   **icons.opts("check", "accent_fg")).pack(side=tk.LEFT)
        ttk.Button(bb, text=tr('Abbrechen'), command=lambda: self._finish(False)).pack(side=tk.LEFT, padx=(6, 0))

        # Fläche für den Browser; solange er (noch) nicht da ist, ein Hinweis darin
        self.view = app.theme.register_frame(tk.Frame(self.outer, borderwidth=0, highlightthickness=0))
        self.view.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.view.bind("<Configure>", lambda e: browser.fit(self.host.hwnd, e.width, e.height))
        self.note = ttk.Frame(self.view, padding=20)
        self.note_var = tk.StringVar()
        ttk.Label(self.note, textvariable=self.note_var, style="Muted.TLabel", wraplength=round(420 * s),
                  justify=tk.CENTER).pack()
        self.install_btn = ttk.Button(self.note, text=tr('Browser einrichten'), style="Accent.TButton",
                                      command=self.install, **icons.opts("download", "accent_fg"))
        self._show_note()

    # ------------------------------------------------------------ Sichtbarkeit

    def show(self):
        if not self.visible:
            self.visible = True
            root = self.app.root
            left = self._before.winfo_rootx() - root.winfo_rootx()  # Seitenleiste links
            room = root.winfo_width() - left - self._main_need()
            width = min(room, round(root.winfo_width() * WIDTH_SHARE), round(MAX_WIDTH * self.s))
            self.outer.configure(width=max(round(MIN_WIDTH * self.s), width))
            self.outer.pack(side=tk.RIGHT, fill=tk.Y, before=self._before)
            self.sep.pack(side=tk.RIGHT, fill=tk.Y, before=self._before)
        self._start()

    def hide(self):
        """Nur zuklappen – der Browser läuft weiter (Anmeldungen, offene Seite bleiben)."""
        if self.visible:
            self.visible = False
            self.outer.pack_forget()
            self.sep.pack_forget()
        if self._answer is not None:
            self._finish(False)

    def toggle(self):
        self.hide() if self.visible else self.show()

    def shutdown(self):
        self._closing = True
        if self._answer is not None:
            self._finish(False)
        self.host.stop()

    # ------------------------------------------------------------ Browser starten, Ereignisse

    def _show_note(self):
        if not browser.available():
            self.note_var.set(tr('Für den Browser braucht Monhip die Zusatzbibliothek pywebview (einmalig, etwa 20 MB).')
                              if plattform.WINDOWS else
                              tr('Für den Browser braucht Monhip pywebview: sudo apt install {0}', browser.LINUX_PACKAGES))
            if plattform.WINDOWS:
                self.install_btn.pack(pady=(12, 0))
        elif not browser.EMBED:
            self.note_var.set(tr('Der Browser öffnet sich unter Linux als eigenes Fenster.'))
            self.install_btn.pack_forget()
        else:
            self.note_var.set(tr('Browser startet …'))
            self.install_btn.pack_forget()
        self.note.place(relx=0.5, rely=0.3, anchor="center")

    def _start(self):
        if self.host.running() or not browser.available():
            self._show_note()
            return
        root = self.app.root
        size = (round(MAX_WIDTH * self.s * 0.8), root.winfo_height())
        pos = (root.winfo_rootx() + root.winfo_width(), root.winfo_rooty())  # Linux: rechts neben Monhip
        try:
            self.host.start(size=size, pos=pos, start_page=browser.start_page(self.app.theme.pal))
        except OSError as e:
            self.note_var.set(tr('Der Browser ließ sich nicht starten: {0}', e))
            return
        self._show_note()

    def _on_event(self, msg: dict):
        """Ereignisse des Browsers (im Tk-Thread)."""
        if self._closing:
            return
        event = msg.get("event")
        if event == "ready" and browser.EMBED and self.host.hwnd:
            self.note.place_forget()
            browser.embed(self.host.hwnd, self.view.winfo_id())
            browser.fit(self.host.hwnd, self.view.winfo_width(), self.view.winfo_height())
        elif event == "loaded":
            if self.app.root.focus_get() is not self.url_entry:
                self.url_var.set("" if msg.get("url") == "about:blank" else msg.get("url", ""))
        elif event in ("closed", "exit"):
            self._show_note()

    def install(self):
        if self._installing:
            return
        self._installing = True
        self.install_btn.state(["disabled"])
        self.note_var.set(tr('Installiere pywebview … (das dauert etwa eine Minute)'))

        def done(_result, error):
            self._installing = False
            self.install_btn.state(["!disabled"])
            if error:
                self.note_var.set(error)
                return
            self.install_btn.pack_forget()
            self._start()

        self.app.background(browser.install, done)

    # ------------------------------------------------------------ Bedienen (Nutzer)

    def navigate(self, url: str):
        try:
            url = browser.normalize_url(url)
        except browser.BrowserError as e:
            dialogs.showerror(tr('Browser'), str(e))
            return
        self.url_var.set(url)
        self.show()
        self.app.root.focus_set()
        if self.host.running():
            threading.Thread(target=self._quiet, args=("open",), kwargs={"url": url}, daemon=True).start()

    def _nav(self, op: str):
        if self.host.running():
            threading.Thread(target=self._quiet, args=(op,), daemon=True).start()

    def _quiet(self, op: str, **args):
        try:
            self.host.request(op, **args)
        except browser.BrowserError:
            pass

    def _external(self):
        url = self.url_var.get().strip()
        if url.startswith(("http://", "https://")):
            webbrowser.open(url)

    # ------------------------------------------------------------ Auf den Nutzer warten

    def ask(self, message: str, answer: threading.Event):
        """Hinweis oben im Browser zeigen (im Tk-Thread); answer wird gesetzt, sobald der Nutzer fertig ist."""
        self._answer, self._result = answer, ""
        self.banner_var.set(message)
        self.banner.pack(side=tk.TOP, fill=tk.X, after=self.head)
        self.show()
        self.app.notify_done(tr('Monhip braucht dich im Browser'), message)

    def _finish(self, done: bool):
        self._result = "done" if done else "cancel"
        self.banner.pack_forget()
        answer, self._answer = self._answer, None
        if answer is not None:
            answer.set()


class BrowserTools:
    """Der Browser für das Modell (agent.Agent – läuft im Hintergrund-Thread): öffnen, lesen, klicken, eingeben,
    den Nutzer etwas im Browser erledigen lassen."""

    def __init__(self, panel: BrowserPanel):
        self.panel = panel
        self.app = panel.app
        self.page: dict = {}   # zuletzt gelesene Seite (für die Bestätigung: was wird geklickt?)

    def is_open(self) -> bool:
        """Ist die Seitenleiste gerade offen? Dann soll das Modell den Browser auch für Suchen nehmen."""
        return self.panel.visible

    def _ensure(self):
        if not browser.available():
            self.app.ui(self.panel.show)
            raise browser.BrowserError(
                "Der Browser ist noch nicht eingerichtet. Bitte den Nutzer, ihn in der Seitenleiste „Browser“ "
                "einzurichten (Knopf „Browser einrichten“), oder lies die Seite mit fetch_url.")
        if not self.panel.host.running() or not self.panel.visible:
            started = threading.Event()
            self.app.ui(lambda: (self.panel.show(), started.set()))
            started.wait(10)

    def open(self, url: str) -> str:
        url = browser.normalize_url(url)
        self._ensure()
        self.app.ui(self.panel.url_var.set, url)
        result = self.panel.host.request("open", url=url)
        text = self.read()
        return text if result.get("loaded") else "Hinweis: Die Seite lädt noch.\n\n" + text

    def read(self, start: int = 0) -> str:
        self._ensure()
        self.page = self.panel.host.request("read") or {}
        if not self.page.get("title") and not (self.page.get("text") or "").strip():  # lädt gerade (Weiterleitung)
            self.panel.host.request("settle", timeout=10)
            self.page = self.panel.host.request("read") or {}
        return browser.page_text(self.page, start)

    def describe(self, nr) -> str:
        """Was hinter Nummer nr steckt – für die Rückfrage vor dem Klicken bzw. Eingeben."""
        item = next((i for i in self.page.get("items") or [] if i.get("nr") == int(nr)), None)
        where = f"{self.page.get('title') or ''}\n{self.page.get('url') or ''}".strip()
        if not item:
            return f"[{nr}]\n{where}"
        return f"[{nr}] {browser.KINDS.get(item.get('kind'), 'Element')}: {item.get('label') or ''}\n{where}"

    def click(self, nr) -> str:
        self._ensure()
        out = self.panel.host.request("click", nr=int(nr))
        if out.get("result") == "missing":
            raise browser.BrowserError(f"Element [{nr}] gibt es nicht (mehr) – erst browser_lesen.")
        return ("Geklickt." if not out.get("navigated") else "Geklickt, neue Seite geladen.") + "\n\n" + self.read()

    def type(self, nr, text: str, enter: bool = False) -> str:
        self._ensure()
        out = self.panel.host.request("type", nr=int(nr), text=str(text), enter=bool(enter))
        if out.get("result") == "password":
            raise browser.BrowserError("Passwörter gibt der Nutzer selbst ein – bitte ihn mit browser_nutzer_fragen.")
        if out.get("result") == "missing":
            raise browser.BrowserError(f"Element [{nr}] gibt es nicht (mehr) – erst browser_lesen.")
        return "Eingegeben." + ("\n\n" + self.read() if enter else "")

    def ask_user(self, message: str, stop: threading.Event | None = None) -> str:
        """Zeigt den Hinweis im Browser und wartet, bis der Nutzer „Fertig – weiter“ oder „Abbrechen“ drückt
        (oder die Antwort gestoppt wird)."""
        self._ensure()
        answer = threading.Event()
        self.app.ui(self.panel.ask, str(message).strip() or tr('Bitte im Browser weitermachen.'), answer)
        while not answer.wait(0.25):
            if stop is not None and stop.is_set():
                self.app.ui(self.panel._finish, False)
                return "Abgebrochen (Antwort gestoppt)."
        if self.panel._result != "done":
            return "Der Nutzer hat abgebrochen."
        return "Der Nutzer ist fertig.\n\n" + self.read()
