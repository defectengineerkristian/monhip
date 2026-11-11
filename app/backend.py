"""Backend: findet Modelle, startet/stoppt llama-server und spricht mit seiner OpenAI-kompatiblen API."""

from i18n import tr

import contextlib
import ctypes
import http.client
import json
import os
import re
import secrets
import shlex
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import images
import plattform


# ---------------------------------------------------------------- Modelle

# Aufgeteiltes Modell: „Name-00001-of-00003.gguf“ … – llama-server bekommt den ersten Teil und lädt die übrigen
# aus demselben Ordner selbst nach
_SHARD_RE = re.compile(r"^(.*)-(\d{5})-of-(\d{5})\.gguf$", re.I)

# Empfohlene Sprachmodelle zum Herunterladen (Einstellungen → Modelle → Herunterladen…). Dieselben bietet der
# Windows-Installer an (installer/windows/src/Model.cs, nur lokal) – beide Listen gleich halten
# (progress/tests/test_modelle.py).
# "gb" = Download in GiB (wie die Modellliste), "need_gb" = empfohlener Arbeits- + Grafikspeicher.
HF_URL = "https://huggingface.co/{repo}/resolve/main/{path}"
CATALOG = {
    "qwen3.8-27b": {
        "name": "Qwen3.8-27B · Q4_K_M", "repo": "unsloth/Qwen3.8-27B-GGUF", "folder": "Qwen3.8-27B",
        "files": ("Qwen3.8-27B-UD-Q4_K_M.gguf", "mmproj-F16.gguf"), "gb": 16.2, "need_gb": 20},
    "qwen3.8-flash-next": {
        "name": "Qwen3.8-Flash-Next · UD-IQ1_S", "repo": "unsloth/Qwen3.8-Flash-Next-GGUF",
        "folder": "Qwen3.8-Flash-Next",
        "files": ("UD-IQ1_S/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf",
                  "UD-IQ1_S/Qwen3.8-Flash-Next-UD-IQ1_S-00002-of-00003.gguf",
                  "UD-IQ1_S/Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf", "mmproj-F16.gguf"),
        "gb": 62.7, "need_gb": 72},
}


def catalog_files(key: str, model_dir: Path) -> list[tuple[str, Path]]:
    """(URL, Zieldatei) aller Dateien eines empfohlenen Modells – alle flach in modelle/<folder>/, das Modell
    zuerst (bei aufgeteilten Modellen der erste Teil), Bildverständnis (mmproj) zuletzt."""
    entry = CATALOG[key]
    folder = model_dir / entry["folder"]
    return [(HF_URL.format(repo=entry["repo"], path=f), folder / f.rsplit("/", 1)[-1]) for f in entry["files"]]


def link_files(url: str, model_dir: Path) -> list[tuple[str, Path]] | None:
    """Direktlink zu einer .gguf-Datei → [(URL, Zieldatei in model_dir)], None bei einem anderen Link. Zeigt er auf
    einen Teil eines aufgeteilten Modells („…-00002-of-00003.gguf“), alle Teile – einer allein lässt sich nicht laden."""
    url = url.strip().replace("/blob/", "/resolve/")
    base, _, query = url.partition("?")
    base = base.rstrip("/")
    name = base.split("/")[-1]
    if not name.lower().endswith(".gguf") or "://" not in base:
        return None
    prefix = base[:-len(name)]
    return [(prefix + p.name + ("?" + query if query else ""), model_dir / p.name) for p in shard_parts(Path(name))]


def shard_parts(model: Path) -> list[Path]:
    """Alle Teile eines aufgeteilten Modells (vom ersten Teil aus), sonst nur die Datei selbst."""
    m = _SHARD_RE.match(model.name)
    if not m:
        return [model]
    count = int(m.group(3))
    return [model.with_name(f"{m.group(1)}-{i:05d}-of-{count:05d}.gguf") for i in range(1, count + 1)]


def model_name(model: Path) -> str:
    """Anzeigename: Dateiname ohne .gguf und ohne „-00001-of-00003“."""
    m = _SHARD_RE.match(model.name)
    return m.group(1) if m else model.stem


def model_size(model: Path) -> int:
    """Größe in Bytes, bei aufgeteilten Modellen aller vorhandenen Teile zusammen."""
    return sum(p.stat().st_size for p in shard_parts(model) if p.is_file())


def find_models(folders: list[str]) -> list[Path]:
    """Alle .gguf-Dateien in den Ordnern (ohne Vision-Projektoren und Teil-Downloads); von aufgeteilten Modellen nur
    der erste Teil – die übrigen lädt llama-server selbst nach."""
    seen, models = set(), []
    for folder in folders:
        root = Path(folder)
        if not root.is_dir():
            continue
        for p in root.rglob("*.gguf"):
            if p.name.lower().startswith("mmproj") or p in seen:
                continue
            m = _SHARD_RE.match(p.name)
            if m and int(m.group(2)) != 1:
                continue
            seen.add(p)
            models.append(p)
    return sorted(models, key=lambda p: p.name.lower())


def find_mmproj(model: Path) -> Path | None:
    """Bild-Projektor (mmproj-*.gguf) im Ordner des Modells – bei mehreren der mit dem ähnlichsten Namen."""
    found = sorted(model.parent.glob("mmproj*.gguf"))
    if not found:
        return None
    name = model_name(model).lower()
    return max(found, key=lambda p: len(os.path.commonprefix([p.stem.lower()[6:].lstrip("-_."), name])))


_job = None  # Windows-Job-Objekt: alle llama-server-Prozesse enden mit Monhip


def _end_with_app(proc: subprocess.Popen) -> bool:
    """proc an ein Job-Objekt mit KILL_ON_JOB_CLOSE hängen: Endet das Programm (auch durch Absturz), beendet
    Windows den llama-server mit – sonst bliebe er mit vielen GB im Speicher. Unter Linux erledigt das schon der
    Start mit plattform.popen(bound=True); hier nur, ob das geklappt hat."""
    global _job
    if os.name != "nt":
        return bool(getattr(proc, "monhip_bound", False))
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    if _job is None:
        job = k32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):  # Extended…Information
            k32.CloseHandle(job)
            return False
        _job = job
    handle = k32.OpenProcess(0x0100 | 0x0001, False, proc.pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
    if not handle:
        return False
    try:
        return bool(k32.AssignProcessToJobObject(_job, handle))
    finally:
        k32.CloseHandle(handle)


def library_dirs(exe_dir: Path) -> list[str]:
    """Linux: Ordner mit Bibliotheken für LD_LIBRARY_PATH – der von llama-server und direkte Unterordner mit .so-Dateien.
    Monhip bis 02.11.2026 ließ die CUDA-Laufzeit beim Entpacken in cudart-llama-…/ liegen; so läuft auch eine solche
    Installation auf der Grafikkarte, ohne sie neu herunterzuladen."""
    dirs = [exe_dir]
    try:
        dirs += sorted(d for d in exe_dir.iterdir() if d.is_dir() and any(d.glob("*.so*")))
    except OSError:
        pass
    return [str(d) for d in dirs]


# Schlüssel für den eigenen llama-server, je Programmstart neu. Er bindet nur an 127.0.0.1 – erreichbar ist er
# damit aber für jedes Programm auf dem Rechner und für Webseiten im Browser (llama.cpp erlaubt Anfragen fremder
# Seiten, „CORS“): Eine Seite könnte die Ports abtasten, das Modell nutzen und unter /slots laufende Chats lesen.
# Übergeben wird er als Umgebungsvariable (stünde er in der Befehlszeile, sähe ihn jeder Prozess); llama-server-
# Versionen ohne LLAMA_API_KEY ignorieren sie und den Header einfach.
API_KEY = secrets.token_urlsafe(32)
# Lokale Aufrufe nie über einen Proxy aus der Umgebung (HTTP_PROXY gilt in urllib auch für 127.0.0.1): sonst gingen
# Chats an den Proxy, und das Laden endete mit „Zeitüberschreitung“, weil /health nie ankommt
_local = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _auth(headers: dict | None = None) -> dict:
    return {"Authorization": f"Bearer {API_KEY}", **(headers or {})}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------- Server-Prozess

FIT_MARGIN_MIB = 1024  # so viel Grafikspeicher lässt --fit beim Verteilen der Schichten frei (wie llama.cpp)


def fit_margin(mmproj: Path | None) -> int:
    """Reserve für --fit (Verteilung der Schichten auf die Grafikkarte) in MiB: 1 GB, mit Bildverständnis zusätzlich
    die mmproj-Datei (die rechnet llama.cpp beim Anpassen nicht mit)."""
    try:
        return FIT_MARGIN_MIB + (mmproj.stat().st_size // 2 ** 20 if mmproj else 0)
    except OSError:
        return FIT_MARGIN_MIB


class ManagedServer:
    """Gemeinsam für llama-server (LlamaServer) und sd-server (sdcpp.ImageServer): ein Programm im Hintergrund, das
    ein Modell geladen hält. _spawn startet es (Programmordner im PATH, unter Linux auch LD_LIBRARY_PATH, Befehlszeile
    ins Server-Log), _watch bindet es an Monhip und leitet seine Ausgabe ins Server-Log, stop beendet es."""

    def __init__(self, log_cb):
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self.model = None
        self.log_cb = log_cb
        self._lock = threading.Lock()  # Entladen (eigener Thread) und neues Laden können sich überschneiden
        self._start_lock = threading.Lock()  # nie zwei Starts zugleich (z. B. Doppelklick)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _spawn(self, args: list[str], exe, env: dict | None = None, adjust=None) -> subprocess.Popen:
        """Startet exe mit args; env = zusätzliche Umgebungsvariablen, adjust(umgebung) → umgebung passt sie zuletzt
        an (z. B. Pfade einer Laufzeit). Die Umgebung von Monhip selbst bleibt unverändert."""
        environ = os.environ.copy()
        exe_dir = str(Path(exe).parent)
        environ["PATH"] = os.pathsep.join([exe_dir, environ.get("PATH", "")])
        environ.update(env or {})
        if not plattform.WINDOWS:  # die .so-Dateien liegen neben dem Programm (Windows sucht DLLs dort selbst)
            environ["LD_LIBRARY_PATH"] = os.pathsep.join(
                library_dirs(Path(exe_dir)) + [p for p in [environ.get("LD_LIBRARY_PATH")] if p])
        if adjust:
            environ = adjust(environ)
        self.log_cb("> " + (subprocess.list2cmdline(args) if plattform.WINDOWS else shlex.join(args)) + "\n")
        return plattform.popen(args, bound=True, env=environ, cwd=exe_dir, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)

    def _watch(self, proc: subprocess.Popen, unbound_hint: str):
        if not _end_with_app(proc):
            self.log_cb(unbound_hint)
        threading.Thread(target=self._pump_log, args=(proc,), daemon=True).start()

    def _pump_log(self, proc):
        for raw in proc.stdout:
            self.log_cb(raw.decode("utf-8", "replace"))

    def _forget(self):
        """Der aktuelle Prozess ist beendet: was zum geladenen Modell gehört, zurücksetzen."""
        self.model = None

    def stop(self, proc: subprocess.Popen | None = None):
        """Beendet proc (Standard: den laufenden Server). Vergessen wird er nur, wenn er noch der aktuelle ist:
        Ein großes Modell braucht zum Beenden einige Sekunden – ein inzwischen neu gestarteter Server darf dabei
        nicht verloren gehen (sonst „'NoneType' object has no attribute 'poll'“ beim Laden)."""
        proc = proc or self.proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
        with self._lock:
            if self.proc is proc:
                self.proc = None
                self._forget()


class LlamaServer(ManagedServer):
    def __init__(self, log_cb):
        super().__init__(log_cb)
        self.model: Path | None = None
        self.vision = False  # Modell versteht Bilder (mit mmproj geladen, laut /props)
        self.n_ctx: int | None = None  # tatsächlicher Kontext je Anfrage (laut /props)
        self.last: dict | None = None  # womit zuletzt gestartet wurde – restart() lädt genauso wieder

    def _forget(self):
        self.model, self.vision, self.n_ctx = None, False, None

    def start(self, server: dict, model: Path, ctx: int, ngl: str, extra: str,
              cancel: threading.Event, timeout: float = 900, mmproj: Path | None = None,
              image_tokens: int | None = None):
        """Startet den Server und blockiert, bis das Modell geladen ist. ctx = Kontext in Tokens (aus den
        Einstellungen), mmproj = Bild-Projektor (Bildverständnis), image_tokens = höchstens so viele Tokens pro Bild.
        cancel bricht ab (Entladen oder ein neues Laden)."""
        global API_KEY
        with self._start_lock:  # nie zwei Starts zugleich (z. B. Doppelklick): alten Server beenden, neuen starten
            self.stop()
            if cancel.is_set():
                raise RuntimeError("Laden abgebrochen.")
            self.last = {"server": server, "model": model, "ctx": ctx, "ngl": ngl, "extra": extra, "mmproj": mmproj,
                         "image_tokens": image_tokens}
            port = _free_port()
            args = [server["exe"], "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "--jinja",
                    "--no-webui", "-c", str(ctx)]
            if Path(server["exe"]).with_name(plattform.exe("llama-fit-params")).is_file():  # neuere (kennen -fitt)
                # nur die Verteilung der Schichten auf die Grafikkarte: Reserve inkl. Bildverständnis – ein
                # angegebenes -c ändert llama.cpp dabei nie
                args += ["-fitt", str(fit_margin(mmproj))]
            if ngl and ngl.lower() != "auto":
                args += ["-ngl", ngl]
            if mmproj:
                args += ["--mmproj", str(mmproj)]
                if image_tokens and "--image-max-tokens" not in extra:
                    args += ["--image-max-tokens", str(image_tokens)]
            if extra.strip():
                args += shlex.split(extra, posix=not plattform.WINDOWS)
            if "--api-key" in args[:-1]:  # eigener Schlüssel in den Einstellungen (auch „a,b“): dann den ersten
                API_KEY = args[args.index("--api-key") + 1].split(",")[0]

            proc = self._spawn(args, server["exe"], {"LLAMA_API_KEY": API_KEY})
            with self._lock:
                self.proc, self.port = proc, port
        self._watch(proc, tr('Hinweis: llama-server konnte nicht an das Programm gebunden werden – nach einem Absturz '
                             'läuft er evtl. weiter (Task-Manager: llama-server.exe).\n'))

        # Nur den eigenen Prozess (und Port) beobachten: self.proc kann inzwischen ein anderer sein
        url = f"http://127.0.0.1:{port}"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cancel.is_set() or self.proc is not proc:
                self.stop(proc)
                raise RuntimeError("Laden abgebrochen.")
            if proc.poll() is not None:
                raise RuntimeError(f"Server beendet (Code {proc.returncode}). Siehe Server-Log.")
            try:
                with _local.open(url + "/health", timeout=2) as r:
                    ready = r.status == 200
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                ready = False
            if ready:
                vision, n_ctx = self._props(ctx, url)
                with self._lock:
                    if self.proc is proc:
                        self.model, self.vision, self.n_ctx = model, vision, n_ctx
                        return
                continue  # gerade entladen bzw. ersetzt – oben wird abgebrochen
            time.sleep(0.5)
        self.stop(proc)
        raise RuntimeError("Zeitüberschreitung beim Laden des Modells.")

    def restart(self, cancel: threading.Event, last: dict | None = None):
        """Das Modell mit denselben Einstellungen wie beim letzten Start wieder laden (blockiert wie start) – z. B.
        nachdem es für ein Bild entladen wurde. last: ein früher gemerktes self.last."""
        p = last or self.last
        if not p:
            raise RuntimeError("Es wurde noch kein Modell geladen.")
        self.start(p["server"], p["model"], p["ctx"], p["ngl"], p["extra"], cancel, mmproj=p["mmproj"],
                   image_tokens=p["image_tokens"])

    def _props(self, ctx: int, url: str | None = None) -> tuple[bool, int]:
        """(versteht Bilder, Kontext je Anfrage) laut /props – der Kontext kann vom angeforderten abweichen
        (z. B. aufgeteilt auf mehrere Plätze)."""
        try:
            with _local.open(urllib.request.Request((url or self.base_url) + "/props", headers=_auth()), timeout=5) as r:
                props = json.load(r)
        except (OSError, ValueError):
            return False, ctx
        if not isinstance(props, dict):
            return False, ctx
        n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
        vision = bool((props.get("modalities") or {}).get("vision"))
        return vision, int(n_ctx) if isinstance(n_ctx, int) and n_ctx > 0 else ctx


# ---------------------------------------------------------------- Chat-API

def _api_messages(messages: list) -> list:
    """Schlüssel mit "_" bleiben lokal. Ausnahme "_image_files": als image_url-Teile (data-URL), bei Nutzern
    vor dem Text, bei Werkzeug-Ergebnissen danach."""
    out = []
    for m in messages:
        msg = {k: v for k, v in m.items() if not k.startswith("_")}
        files = [Path(f) for f in m.get("_image_files") or [] if Path(f).is_file()]
        if files:
            pics = [{"type": "image_url", "image_url": {"url": images.data_url(f)}} for f in files]
            text = [{"type": "text", "text": msg["content"]}] if msg.get("content") else []
            msg["content"] = pics + text if m.get("role") == "user" else text + pics
        out.append(msg)
    return out


class _ThinkSplitter:
    """Trennt <think>…</think> am Anfang der Antwort ab – für Modelle, deren Denkprozess der Server
    nicht selbst als reasoning_content liefert."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.state = "start"
        self.buf = ""

    def feed(self, text: str) -> list[tuple[str, str]]:
        out = []
        self.buf += text
        while self.buf:
            if self.state == "start":
                head = self.buf.lstrip()
                if head.startswith(self.OPEN):
                    self.state, self.buf = "think", head[len(self.OPEN):]
                    continue
                if self.OPEN.startswith(head):   # könnte noch ein <think> werden
                    break
                self.state = "content"
            elif self.state == "think":
                i = self.buf.find(self.CLOSE)
                if i >= 0:
                    out.append(("reasoning", self.buf[:i]))
                    self.state, self.buf = "content", self.buf[i + len(self.CLOSE):].lstrip("\n")
                    continue
                keep = next((n for n in range(len(self.CLOSE) - 1, 0, -1) if self.buf.endswith(self.CLOSE[:n])), 0)
                out.append(("reasoning", self.buf[:len(self.buf) - keep]))
                self.buf = self.buf[len(self.buf) - keep:]
                break
            else:
                out.append(("content", self.buf))
                self.buf = ""
        return [(k, t) for k, t in out if t]

    def flush(self) -> list[tuple[str, str]]:
        rest, self.buf = self.buf, ""
        return [("reasoning" if self.state == "think" else "content", rest)] if rest else []


class ContextFull(RuntimeError):
    """Der Server lehnt ab, weil die Anfrage nicht in den Kontext passt (llama.cpp: exceed_context_size_error)."""

    def __init__(self, n_prompt: int, n_ctx: int):
        self.n_prompt, self.n_ctx = n_prompt, n_ctx
        fmt = lambda n: f"{n:,}".replace(",", ".")
        size = f"Die Anfrage braucht {fmt(n_prompt)} Tokens, der Kontext fasst {fmt(n_ctx)}. " if n_prompt else ""
        super().__init__(f"Kontextfenster voll: {size}Weiter komprimieren lässt sich die Unterhaltung nicht – bitte den "
                         "Kontext erhöhen (Einstellungen → Laden), weniger Werkzeuge einschalten oder einen neuen Chat "
                         "beginnen.")


def _context_full(code: int, body: str) -> ContextFull | None:
    if code != 400 or ("exceed_context_size" not in body and "exceeds the available context" not in body):
        return None
    n_prompt = n_ctx = 0
    try:
        err = json.loads(body).get("error") or {}
        n_prompt, n_ctx = int(err.get("n_prompt_tokens") or 0), int(err.get("n_ctx") or 0)
    except (ValueError, AttributeError, TypeError):
        pass
    if not (n_prompt and n_ctx):
        m = re.search(r"\((\d+) tokens\) exceeds the available context size \((\d+) tokens\)", body)
        if m:
            n_prompt, n_ctx = int(m.group(1)), int(m.group(2))
    return ContextFull(n_prompt, n_ctx)


STOP_POLL = 0.05  # so schnell trennt „Stopp“ eine laufende Anfrage (Sekunden)


@contextlib.contextmanager
def _cancel_on(stop: threading.Event, conn: http.client.HTTPConnection):
    """Solange der Block läuft: wird stop gesetzt, die Verbindung sofort trennen. Sonst wirkte „Stopp“ erst mit dem
    nächsten Stück Text – während der Server einen langen Prompt einliest (bei großen Chats und Q8 eine Minute und
    mehr), kommt keins. Getrennt bricht llama.cpp die Anfrage selbst ab."""
    done = threading.Event()

    def watch():
        while not done.wait(STOP_POLL):
            if stop.is_set():
                sock = conn.sock
                if sock is not None:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    try:  # shutdown allein weckt unter Windows ein wartendes recv/select nicht – Schließen schon
                        socket.close(sock.detach())
                    except OSError:
                        pass
                return

    threading.Thread(target=watch, daemon=True).start()
    try:
        yield
    finally:
        done.set()


def chat_turn(base_url: str, messages: list, params: dict, tools: list | None,
              stop: threading.Event, on_event) -> tuple[str, list, str]:
    """Ein gestreamter Modell-Aufruf → (Antworttext, Tool-Aufrufe, Denkprozess).
    on_event(art, daten): "reasoning"/"content" live, am Ende "stats" (Tokens/s). stop bricht sofort ab (auch
    während der Server noch liest) – zurück kommt, was bis dahin da war."""
    payload = {"messages": _api_messages(messages), "stream": True, **params}
    if tools:
        payload["tools"] = tools
    url = urllib.parse.urlsplit(base_url)
    conn = http.client.HTTPConnection(url.hostname, url.port or 80, timeout=900)

    content, reasoning, calls = [], [], {}
    splitter = _ThinkSplitter()

    def emit(kind, text):
        (reasoning if kind == "reasoning" else content).append(text)
        on_event(kind, text)

    if stop.is_set():
        return "", [], ""
    try:
        conn.connect()
        with _cancel_on(stop, conn):
            conn.request("POST", url.path.rstrip("/") + "/v1/chat/completions", json.dumps(payload).encode("utf-8"),
                         _auth({"Content-Type": "application/json"}))
            resp = conn.getresponse()
            if resp.status >= 400:
                body = resp.read().decode("utf-8", "replace")
                full = _context_full(resp.status, body)
                if full:
                    raise full
                raise RuntimeError(f"HTTP {resp.status}: {body[:500]}")
            for raw in resp:
                if stop.is_set():
                    break
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                timings = chunk.get("timings") or {}
                if timings.get("predicted_per_second"):
                    on_event("stats", timings["predicted_per_second"])
                used = _used_tokens(chunk.get("usage"), timings)
                if used:
                    on_event("usage", used)  # so viele Tokens belegt der Verlauf samt Antwort jetzt
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                if delta.get("reasoning_content"):
                    emit("reasoning", delta["reasoning_content"])
                if delta.get("content"):
                    for kind, text in splitter.feed(delta["content"]):
                        emit(kind, text)
                for tc in delta.get("tool_calls") or []:
                    c = calls.setdefault(tc.get("index", 0), {
                        "id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                    if tc.get("id"):
                        c["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    c["function"]["name"] += fn.get("name") or ""
                    c["function"]["arguments"] += fn.get("arguments") or ""
    except (OSError, http.client.HTTPException) as e:
        if not stop.is_set():  # gestoppt: Trennen war gewollt
            if isinstance(e, OSError):
                raise
            raise ConnectionError(f"{type(e).__name__}: {e}") from None
    finally:
        conn.close()
    for kind, text in splitter.flush():
        emit(kind, text)
    return "".join(content), [calls[i] for i in sorted(calls)], "".join(reasoning)


def _used_tokens(usage, timings: dict) -> int | None:
    """Belegter Kontext nach einer Antwort: usage (OpenAI-Form, im letzten Paket), sonst die timings von
    llama.cpp (zwischengespeicherte + neu gelesene + erzeugte Tokens)."""
    if isinstance(usage, dict):
        total = usage.get("total_tokens") or (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
        if total:
            return int(total)
    if timings.get("prompt_n") is not None and timings.get("predicted_n") is not None:
        return int((timings.get("cache_n") or 0) + timings["prompt_n"] + timings["predicted_n"]) or None
    return None


def count_tokens(base_url: str, text: str, timeout: float = 15) -> int:
    """Genaue Token-Zahl eines Textes mit dem Tokenizer des geladenen Modells (/tokenize)."""
    req = urllib.request.Request(base_url + "/tokenize", data=json.dumps({"content": text}).encode("utf-8"),
                                 headers=_auth({"Content-Type": "application/json"}))
    with _local.open(req, timeout=timeout) as r:
        return len(json.loads(r.read()).get("tokens") or [])


TITLE_PROMPT = (
    "Fasse den folgenden Denkprozess eines KI-Assistenten als knappe deutsche Überschrift mit 3 bis 7 Wörtern "
    "zusammen, so wie eine Statuszeile: Was hat der Assistent überlegt oder getan? Beispiele: "
    "„Vergleicht Python-Bibliotheken für Excel“, „Plant die Ordnerstruktur des Projekts“, "
    "„Prüft die Rechnung Schritt für Schritt“. Antworte nur mit der Überschrift, ohne Anführungszeichen "
    "und ohne Punkt am Ende.")


def thinking_title(base_url: str, thinking: str, timeout: float = 90) -> str:
    """Kurze Überschrift für einen Denkprozess (zusätzliche, kleine Anfrage an das geladene Modell)."""
    text = thinking.strip()
    if len(text) > 6000:
        text = text[:2500] + "\n…\n" + text[-3500:]
    payload = {
        "messages": [{"role": "system", "content": TITLE_PROMPT},
                     {"role": "user", "content": f"<denkprozess>\n{text}\n</denkprozess>"}],
        "stream": False, "max_tokens": 60, "temperature": 0.2,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(base_url + "/v1/chat/completions", data=json.dumps(payload).encode("utf-8"),
                                 headers=_auth({"Content-Type": "application/json"}))
    with _local.open(req, timeout=timeout) as r:
        msg = json.loads(r.read())["choices"][0]["message"]
    title = re.sub(r"(?s)<think>.*?(</think>|$)", "", msg.get("content") or "").strip()
    title = title.splitlines()[0] if title else ""
    title = re.sub(r"^(überschrift|titel)\s*:\s*", "", title, flags=re.I)
    title = title.strip(" \"'„“”«»*#.").strip()
    return title if len(title) <= 70 else title[:69].rstrip() + "…"
