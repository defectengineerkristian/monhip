"""Browser in der Seitenleiste – Nutzer und Modell teilen ihn: Das Modell öffnet und liest Seiten, klickt und füllt
Felder aus; Anmeldungen und Captchas erledigt der Nutzer selbst darin (browser_nutzer_fragen), danach liest das
Modell weiter. Anmeldungen bleiben im Browser gespeichert (DATA_DIR/browser).

Der Browser selbst ist pywebview (Zusatzbibliothek – unter Windows über WebView2/Edge, unter Linux über WebKitGTK) in
einem eigenen Prozess (browser_host.py). Unter Windows sitzt sein Fenster in der Seitenleiste von Monhip (SetParent),
unter Linux ist es ein eigenes Fenster daneben.

Hier: Verfügbarkeit und Installation, der Prozess (Host) mit seinem Protokoll, das Einbetten und die Aufbereitung
einer Seite für das Modell (page_text). Die Seitenleiste selbst steht in browserpanel.py."""

from i18n import tr

import importlib.util
import itertools
import json
import os
import queue
import re
import subprocess
import sys
import sysconfig
import threading
from pathlib import Path

import plattform

HOST = Path(__file__).with_name("browser_host.py")
STORAGE = plattform.DATA_DIR / "browser"   # Cookies und Anmeldungen
PACKAGE = "pywebview"
LINUX_PACKAGES = "python3-webview gir1.2-webkit2-4.1"  # Debian/Ubuntu: pywebview samt WebKitGTK aus dem System
TEXT_CHARS = 6000                          # so viel Seitentext je browser_lesen
MAX_ITEMS = 80                             # so viele Bedienelemente je browser_lesen
EMBED = plattform.WINDOWS                  # unter Linux lässt sich das GTK-Fenster nicht in Tk setzen


class BrowserError(RuntimeError):
    """Für das Modell verständlicher Fehler (Browser fehlt, Seite lädt nicht, Element weg …)."""


# ---------------------------------------------------------------- Verfügbar? Installieren

def available() -> bool:
    """pywebview für den Python, mit dem Monhip läuft, installiert? (ohne es hier zu laden)"""
    importlib.invalidate_caches()
    return importlib.util.find_spec("webview") is not None


def python_exe(console: bool = False) -> str:
    """Python für den Browser-Prozess (pythonw ohne Konsolenfenster) bzw. für pip (python)."""
    exe = Path(sys.executable)
    if plattform.WINDOWS:
        name = "python.exe" if console else "pythonw.exe"
        if exe.with_name(name).is_file():
            return str(exe.with_name(name))
    return str(exe)


def install_command() -> list[str]:
    """pip-Aufruf für pywebview: in den Python von Monhip, ohne Schreibrecht dort für den Nutzer (--user); in einer
    virtuellen Umgebung gibt es --user nicht."""
    cmd = [python_exe(console=True), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", PACKAGE]
    if sys.prefix == sys.base_prefix and not os.access(sysconfig.get_paths()["purelib"], os.W_OK):
        cmd.insert(4, "--user")
    return cmd


def install(cancel: threading.Event | None = None) -> str:
    """Installiert pywebview (Netzwerk, dauert – im Thread aufrufen). Unter Linux nur mit Hinweis auf die
    Paketverwaltung (pip darf dort meist nicht ins System-Python). → Ausgabe von pip; Fehler als BrowserError."""
    if not plattform.WINDOWS:
        raise BrowserError(tr('Bitte über die Paketverwaltung installieren: sudo apt install {0}', LINUX_PACKAGES))
    proc = plattform.popen(install_command(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    lines = []
    for raw in proc.stdout:
        lines.append(raw.decode("utf-8", "replace").rstrip())
        if cancel is not None and cancel.is_set():
            plattform.kill_tree(proc)
            raise BrowserError(tr('Abgebrochen.'))
    proc.wait()
    if proc.returncode or not available():
        raise BrowserError(tr('pywebview ließ sich nicht installieren:\n{0}', "\n".join(lines[-12:])))
    return "\n".join(lines)


# ---------------------------------------------------------------- Adressen

def normalize_url(url: str) -> str:
    """„example.org“ → https://example.org; nur http(s) – keine Dateien, kein javascript: o. Ä."""
    url = (url or "").strip()
    if not url:
        raise BrowserError("Keine Adresse angegeben.")
    if re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I) and not re.match(r"^https?://", url, re.I):
        if not re.match(r"^[\w.-]+:\d+(/|$)", url):  # „localhost:8000“ ist eine Adresse, kein Schema
            raise BrowserError(f"Nur http- und https-Adressen: {url}")
    if not re.match(r"^https?://", url, re.I):
        url = ("http://" if re.match(r"^(localhost|127\.0\.0\.1|\[::1\])([:/]|$)", url, re.I) else "https://") + url
    return url


# ---------------------------------------------------------------- Startseite

START_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title><style>
html,body{{height:100%;margin:0;background:{bg};color:{fg};font-family:"Segoe UI",system-ui,sans-serif}}
main{{max-width:540px;margin:16vh auto 0;padding:0 24px}}
h1{{font-weight:600;font-size:22px;margin:0 0 18px}}
form{{display:flex;gap:8px}}
input{{flex:1;padding:10px 12px;border-radius:8px;border:1px solid {border};background:{surface};color:{fg};
font-size:15px;outline:none}}
input:focus{{border-color:{accent}}}
button{{padding:10px 18px;border:0;border-radius:8px;background:{accent};color:{accent_fg};font-weight:600;
font-size:14px;cursor:pointer}}
p{{color:{muted};font-size:14px;line-height:1.55;margin-top:22px}}
</style></head><body><main><h1>{title}</h1>
<form onsubmit="var q=document.getElementById('q').value.trim();if(q){{location.href=
/^[\w-]+(\.[\w-]+)+([/:?#]|$)/.test(q)&&q.indexOf(' ')<0?'https://'+q.replace(/^https?:\/\//,''):
'https://www.google.com/search?q='+encodeURIComponent(q);}}return false;">
<input id="q" autofocus placeholder="{placeholder}"><button>{go}</button></form>
<p>{hint}</p></main></body></html>"""


def start_page(colors: dict | None) -> str:
    """Startseite im Design von Monhip (colors: Palette aus themes.THEMES, None = hell wie das System)."""
    c = colors or {"bg": "#ffffff", "fg": "#1b1b1b", "muted": "#5f5f5f", "border": "#c8c8c8", "surface": "#ffffff",
                   "accent": "#0b63c5", "accent_fg": "#ffffff"}
    esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;").replace('"', "&quot;")  # noqa: E731
    return START_HTML.format(
        title=esc(tr('Browser')), placeholder=esc(tr('Suchen oder Adresse eingeben')), go=esc(tr('Los')),
        hint=esc(tr('Das Modell kann hier Seiten öffnen, lesen und bedienen – frag im Chat zum Beispiel „Googel nach …“ '
                    'oder „Öffne …“. Anmeldungen und Captchas erledigst du selbst, danach oben „Fertig – weiter“.')),
        **{k: c[k] for k in ("bg", "fg", "muted", "border", "surface", "accent", "accent_fg")})


# ---------------------------------------------------------------- Seite fürs Modell

KINDS = {"link": "Link", "button": "Knopf", "field": "Eingabefeld", "select": "Auswahl", "checkbox": "Kästchen",
         "radio": "Option", "password": "Passwortfeld"}


def page_text(page: dict, start: int = 0, chars: int = TEXT_CHARS, items: int = MAX_ITEMS) -> str:
    """Seite (aus READ_JS im Browser) als Text für das Modell: Titel, Adresse, Textausschnitt ab start und die
    nummerierten Bedienelemente – mit Hinweis, wenn der Nutzer etwas tun muss (Passwort, Captcha)."""
    text = re.sub(r"\n{3,}", "\n\n", (page.get("text") or "").strip())
    start = max(0, min(int(start), len(text)))
    part = text[start:start + chars]
    lines = [f"Seite: {page.get('title') or '(ohne Titel)'}", f"Adresse: {page.get('url') or ''}", ""]
    lines.append(part if part else "(kein Text)")
    if start + chars < len(text):
        lines.append(f"…(weiter mit browser_lesen, start={start + chars}; insgesamt {len(text)} Zeichen)")
    controls = page.get("items") or []
    if controls and start == 0:
        lines += ["", "Bedienelemente (Nummer für browser_klicken bzw. browser_eingeben):"]
        for it in controls[:items]:
            kind = KINDS.get(it.get("kind"), "Element")
            desc = f"[{it.get('nr')}] {kind}"
            if it.get("label"):
                desc += f": {it['label']}"
            if it.get("kind") == "password":
                desc += " – gibt der Nutzer selbst ein"
            elif it.get("value"):
                desc += f" (Inhalt: {it['value']})"
            if it.get("checked") is not None:
                desc += " (an)" if it["checked"] else " (aus)"
            lines.append(desc)
        if len(controls) > items:
            lines.append(f"…und {len(controls) - items} weitere")
    need = []
    if page.get("password"):
        need.append("ein Passwortfeld")
    if page.get("captcha"):
        need.append("ein Captcha")
    if need:
        lines += ["", f"Hinweis: Auf der Seite ist {' und '.join(need)}. Das erledigt der Nutzer selbst – bitte ihn "
                      "mit browser_nutzer_fragen darum und lies danach weiter."]
    return "\n".join(lines)


# ---------------------------------------------------------------- Prozess

class Host:
    """Der Browser-Prozess. request() wartet auf die Antwort (im Hintergrund-Thread aufrufen); on_event(nachricht)
    bekommt Ereignisse (ready mit hwnd, loaded mit url/title, closed) – aus dem Lese-Thread."""

    def __init__(self, on_event=None):
        self.on_event = on_event or (lambda msg: None)
        self.proc: subprocess.Popen | None = None
        self.hwnd: int | None = None
        self.ready = threading.Event()
        self._ids = itertools.count(1)
        self._waiting: dict[int, queue.Queue] = {}
        self._lock = threading.Lock()

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, size=(900, 800), pos=(0, 0), start_page: str = "", argv: list[str] | None = None):
        """Startet den Browser (falls er nicht schon läuft). start_page: HTML der Startseite (start_page());
        argv nur für Tests (ein Ersatz-Host)."""
        if self.running():
            return
        STORAGE.mkdir(parents=True, exist_ok=True)
        page = STORAGE / "start.html"
        if start_page:
            page.write_text(start_page, encoding="utf-8")
        args = argv or [python_exe(), str(HOST), str(STORAGE), "1" if EMBED else "0",
                        *(str(int(v)) for v in (*size, *pos)), *([str(page)] if start_page else [])]
        self.ready.clear()
        self.hwnd = None
        self.proc = plattform.popen(args, bound=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL, cwd=str(HOST.parent))
        try:
            from backend import _end_with_app  # Windows: endet mit Monhip, auch nach einem Absturz
            _end_with_app(self.proc)
        except Exception:  # noqa: BLE001 – ohne Job-Objekt beendet ihn stop() beim Schließen
            pass
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()

    def _read(self, proc):
        for raw in proc.stdout:
            try:
                msg = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if "id" in msg:
                with self._lock:
                    box = self._waiting.pop(msg["id"], None)
                if box:
                    box.put(msg)
                continue
            if msg.get("event") == "ready":
                self.hwnd = msg.get("hwnd")
                self.ready.set()
            self.on_event(msg)
        proc.stdout.close()
        with self._lock:  # Prozess beendet: wer noch wartet, bekommt einen Fehler statt ewig zu warten
            waiting, self._waiting = self._waiting, {}
        for box in waiting.values():
            box.put({"ok": False, "error": "Der Browser wurde geschlossen."})
        self.ready.set()
        self.on_event({"event": "exit"})

    def request(self, op: str, timeout: float = 45, **args):
        if not self.running():
            raise BrowserError("Der Browser ist nicht geöffnet.")
        if not self.ready.wait(30) or not self.running():
            raise BrowserError("Der Browser startet nicht.")
        rid, box = next(self._ids), queue.Queue()
        with self._lock:
            self._waiting[rid] = box
        try:
            self.proc.stdin.write((json.dumps({"id": rid, "op": op, **args}) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except OSError:
            with self._lock:
                self._waiting.pop(rid, None)
            raise BrowserError("Der Browser wurde geschlossen.") from None
        try:
            msg = box.get(timeout=timeout)
        except queue.Empty:
            with self._lock:
                self._waiting.pop(rid, None)
            raise BrowserError("Der Browser antwortet nicht.") from None
        if not msg.get("ok"):
            raise BrowserError(msg.get("error") or "Fehler im Browser.")
        return msg.get("data")

    def stop(self):
        proc = self.proc
        if proc and proc.poll() is None:
            try:
                proc.stdin.write(b'{"op": "quit"}\n')
                proc.stdin.flush()
                proc.wait(3)
            except (OSError, subprocess.TimeoutExpired):
                plattform.kill_tree(proc)
        if proc:
            try:
                proc.stdin.close()
            except OSError:
                pass
        self.proc = None


# ---------------------------------------------------------------- Einbetten (Windows)

if plattform.WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    _user32.MoveWindow.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.BOOL]
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]


def embed(hwnd: int, parent: int):
    """Fenster des Browsers als Kind in parent (winfo_id eines Tk-Frames) setzen – ohne Rahmen und Titelleiste."""
    if not plattform.WINDOWS or not hwnd:
        return
    GWL_STYLE, WS_CHILD, WS_POPUP, WS_CAPTION, WS_THICKFRAME = -16, 0x40000000, 0x80000000, 0x00C00000, 0x00040000
    style = _user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
    _user32.SetWindowLongPtrW(hwnd, GWL_STYLE, (style & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME)) | WS_CHILD)
    _user32.SetParent(hwnd, parent)
    _user32.ShowWindow(hwnd, 5)  # SW_SHOW


def fit(hwnd: int, width: int, height: int):
    if plattform.WINDOWS and hwnd:
        _user32.MoveWindow(hwnd, 0, 0, max(1, width), max(1, height), True)
