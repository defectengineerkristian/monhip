"""Backend: findet Modelle, startet/stoppt llama-server und spricht mit seiner OpenAI-kompatiblen API."""

from i18n import tr

import ctypes
import json
import os
import re
import shlex
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import images


# ---------------------------------------------------------------- Modelle

def find_models(folders: list[str]) -> list[Path]:
    """Alle .gguf-Dateien in den Ordnern (ohne Vision-Projektoren und Teil-Downloads)."""
    seen, models = set(), []
    for folder in folders:
        root = Path(folder)
        if not root.is_dir():
            continue
        for p in root.rglob("*.gguf"):
            if p.name.lower().startswith("mmproj") or p in seen:
                continue
            seen.add(p)
            models.append(p)
    return sorted(models, key=lambda p: p.name.lower())


def find_mmproj(model: Path) -> Path | None:
    """Bild-Projektor (mmproj-*.gguf) im Ordner des Modells – bei mehreren der mit dem ähnlichsten Namen."""
    found = sorted(model.parent.glob("mmproj*.gguf"))
    if not found:
        return None
    name = model.stem.lower()
    return max(found, key=lambda p: len(os.path.commonprefix([p.stem.lower()[6:].lstrip("-_."), name])))


_job = None  # Windows-Job-Objekt: alle llama-server-Prozesse enden mit Monhip


def _end_with_app(proc: subprocess.Popen) -> bool:
    """proc an ein Job-Objekt mit KILL_ON_JOB_CLOSE hängen: Endet das Programm (auch durch Absturz), beendet
    Windows den llama-server mit – sonst bliebe er mit vielen GB im Speicher."""
    global _job
    if os.name != "nt":
        return False
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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------- Server-Prozess

AUTO_MIN_CTX, AUTO_MAX_CTX = 16384, 65536  # Kontext „auto“: mindestens (Werkzeuge) / höchstens so viel
AUTO_TARGET_CTX = 32768                    # „auto“ nimmt mindestens so viel – lagert dafür Schichten in den RAM aus
FIT_MARGIN_MIB = 1024                      # so viel Grafikspeicher lässt --fit frei (wie llama.cpp)
RAM_RESERVE_MIB = 4096                     # so viel Arbeitsspeicher bleibt für Windows und andere Programme


def fit_margin(mmproj: Path | None) -> int:
    """Reserve für --fit in MiB: 1 GB, mit Bildverständnis zusätzlich die mmproj-Datei (die rechnet llama.cpp beim
    Anpassen nicht mit, llama-fit-params kennt sie gar nicht)."""
    try:
        return FIT_MARGIN_MIB + (mmproj.stat().st_size // 2 ** 20 if mmproj else 0)
    except OSError:
        return FIT_MARGIN_MIB


def fit_params(server_exe: str, model: Path, mmproj: Path | None = None, ngl: str | None = None,
               min_ctx: int = AUTO_MIN_CTX, timeout: float = 90) -> dict | None:
    """Was llama.cpp für dieses Modell auf diesem Rechner wählen würde – llama-fit-params rechnet das aus dem
    freien Speicher, ohne die Gewichte zu laden (~2 s): {"ctx", "ngl", "experts_on_cpu"}. None = das Werkzeug fehlt
    (ältere llama.cpp-Version) oder scheitert."""
    exe = Path(server_exe).with_name("llama-fit-params.exe")
    if not exe.is_file():
        return None
    args = [str(exe), "-m", str(model), "-fitc", str(min_ctx), "-fitt", str(fit_margin(mmproj))]
    if ngl and ngl.lower() != "auto":
        args += ["-ngl", ngl]
    try:
        r = subprocess.run(args, capture_output=True, timeout=timeout, cwd=str(exe.parent), stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = r.stdout.decode("utf-8", "replace").strip().splitlines()
    line = f" {lines[-1]} " if lines else ""  # z. B. „-c 16384 -ngl 54 -ot "blk\.26\.ffn_…=CPU"“
    m = re.search(r"\s-c (\d+)\s", line)
    if r.returncode != 0 or not m:
        return None
    n = re.search(r"\s-ngl (\d+)\s", line)
    args = [t[1:-1] if len(t) > 1 and t[0] == t[-1] == '"' else t for t in shlex.split(line, posix=False)]
    return {"ctx": int(m.group(1)), "ngl": int(n.group(1)) if n else None, "experts_on_cpu": " -ot " in line,
            "args": args}


def host_mib(server_exe: str, model: Path, fitted: list) -> int | None:
    """So viel Arbeitsspeicher (MiB) bräuchte das Modell mit diesen Einstellungen (llama-fit-params --fit-print:
    Zeile „Host Modell Kontext Rechnen“). None = unbekannt."""
    exe = Path(server_exe).with_name("llama-fit-params.exe")
    try:
        r = subprocess.run([str(exe), "-m", str(model), *fitted, "-fitp", "on"], capture_output=True, timeout=90,
                           cwd=str(exe.parent), stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if parts and parts[0] == "Host" and all(p.isdigit() for p in parts[1:]):
            return sum(int(p) for p in parts[1:])
    return None


def free_ram_mib() -> int | None:
    """Freier Arbeitsspeicher in MiB (Windows: GlobalMemoryStatusEx)."""
    if sys.platform != "win32":
        return None

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    st = MEMORYSTATUSEX(dwLength=ctypes.sizeof(MEMORYSTATUSEX))
    return st.ullAvailPhys // 2 ** 20 if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)) else None


def auto_context(server_exe: str, model: Path, mmproj: Path | None = None, ngl: str | None = None) -> dict | None:
    """Kontext „auto“: mindestens AUTO_TARGET_CTX (was nicht in den Grafikspeicher passt, kommt in den RAM) –
    reicht der freie Arbeitsspeicher dafür nicht, nur AUTO_MIN_CTX. Ergebnis wie fit_params, dazu "host_mib"."""
    free, best = free_ram_mib(), None
    for floor in (AUTO_TARGET_CTX, AUTO_MIN_CTX):
        fit = fit_params(server_exe, model, mmproj, ngl, min_ctx=floor)
        if not fit:
            return best
        fit["host_mib"] = host_mib(server_exe, model, fit.get("args") or [])
        best = fit
        if free is None or fit["host_mib"] is None or fit["host_mib"] + RAM_RESERVE_MIB <= free:
            break
    return best


def gguf_info(path: Path) -> dict:
    """Aus dem Kopf einer GGUF-Datei: "block_count" (Schichten) und "context_length" (Trainings-Kontext)."""
    size = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}
    fmt = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
    info: dict = {}
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"GGUF":
                return info
            f.read(4)  # Version
            _tensors, count = struct.unpack("<QQ", f.read(16))

            def skip(kind):
                if kind == 8:  # Zeichenkette
                    f.seek(struct.unpack("<Q", f.read(8))[0], 1)
                elif kind == 9:  # Liste (z. B. die Tokens – kommt erst nach den gesuchten Werten)
                    inner, n = struct.unpack("<IQ", f.read(12))
                    if inner in (8, 9):
                        for _ in range(n):
                            skip(inner)
                    else:
                        f.seek(size[inner] * n, 1)
                else:
                    f.seek(size[kind], 1)

            for _ in range(count):
                key = f.read(struct.unpack("<Q", f.read(8))[0]).decode("utf-8", "replace")
                kind = struct.unpack("<I", f.read(4))[0]
                name = key.rsplit(".", 1)[-1]
                if name in ("block_count", "context_length") and kind in fmt and key.count(".") == 1:
                    info[name] = struct.unpack(fmt[kind], f.read(size[kind]))[0]
                    if len(info) == 2:
                        break
                else:
                    skip(kind)
    except (OSError, struct.error, KeyError, ValueError):
        pass
    return info


class LlamaServer:
    def __init__(self, log_cb):
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self.model: Path | None = None
        self.vision = False  # Modell versteht Bilder (mit mmproj geladen, laut /props)
        self.n_ctx: int | None = None  # tatsächlicher Kontext je Anfrage (laut /props)
        self.log_cb = log_cb
        self._lock = threading.Lock()  # Entladen (eigener Thread) und neues Laden können sich überschneiden
        self._start_lock = threading.Lock()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, server: dict, model: Path, ctx: int, ngl: str, extra: str,
              cancel: threading.Event, timeout: float = 900, mmproj: Path | None = None,
              image_tokens: int | None = None):
        """Startet den Server und blockiert, bis das Modell geladen ist. ctx=None = „auto“: so viel Kontext, wie
        neben dem Modell in den Speicher passt (llama-fit-params, AUTO_MIN_CTX bis AUTO_MAX_CTX). mmproj =
        Bild-Projektor (Bildverständnis), image_tokens = höchstens so viele Tokens pro Bild. cancel bricht ab
        (Entladen oder ein neues Laden)."""
        with self._start_lock:  # nie zwei Starts zugleich (z. B. Doppelklick): alten Server beenden, neuen starten
            self.stop()
            if cancel.is_set():
                raise RuntimeError("Laden abgebrochen.")
            can_fit = Path(server["exe"]).with_name("llama-fit-params.exe").is_file()  # neuere llama.cpp-Versionen
            if ctx is None:
                fit = auto_context(server["exe"], model, mmproj, ngl) if can_fit else None
                ctx = min(fit["ctx"], AUTO_MAX_CTX) if fit else (None if can_fit else AUTO_MIN_CTX)
                self.log_cb(tr("Kontext auto: {0}", ctx or tr("llama.cpp passt selbst an (mind. {0})", AUTO_MIN_CTX))
                            + (f" (llama-fit-params: {fit['ctx']})" if fit else "") + "\n")
                if cancel.is_set():
                    raise RuntimeError("Laden abgebrochen.")
            port = _free_port()
            args = [server["exe"], "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "--jinja",
                    "--no-webui"]
            args += ["-c", str(ctx)] if ctx else ["-fitc", str(AUTO_MIN_CTX)]
            if can_fit:
                args += ["-fitt", str(fit_margin(mmproj))]  # Reserve inkl. Bildverständnis
            if ngl and ngl.lower() != "auto":
                args += ["-ngl", ngl]
            if mmproj:
                args += ["--mmproj", str(mmproj)]
                if image_tokens and "--image-max-tokens" not in extra:
                    args += ["--image-max-tokens", str(image_tokens)]
            if extra.strip():
                args += shlex.split(extra, posix=False)

            env = os.environ.copy()
            exe_dir = str(Path(server["exe"]).parent)
            env["PATH"] = os.pathsep.join([exe_dir, env.get("PATH", "")])

            self.log_cb("> " + subprocess.list2cmdline(args) + "\n")
            proc = subprocess.Popen(
                args, env=env, cwd=exe_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            with self._lock:
                self.proc, self.port = proc, port
        if not _end_with_app(proc):
            self.log_cb(tr(
                'Hinweis: llama-server konnte nicht an das Programm gebunden werden – nach einem Absturz läuft er '
                'evtl. weiter (Task-Manager: llama-server.exe).\n'))
        threading.Thread(target=self._pump_log, args=(proc,), daemon=True).start()

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
                with urllib.request.urlopen(url + "/health", timeout=2) as r:
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

    def _props(self, ctx: int, url: str | None = None) -> tuple[bool, int]:
        """(versteht Bilder, Kontext je Anfrage) laut /props – der Kontext kann vom angeforderten abweichen
        (z. B. aufgeteilt auf mehrere Plätze)."""
        try:
            with urllib.request.urlopen((url or self.base_url) + "/props", timeout=5) as r:
                props = json.load(r)
        except (OSError, ValueError):
            return False, ctx
        if not isinstance(props, dict):
            return False, ctx
        n_ctx = (props.get("default_generation_settings") or {}).get("n_ctx")
        vision = bool((props.get("modalities") or {}).get("vision"))
        return vision, int(n_ctx) if isinstance(n_ctx, int) and n_ctx > 0 else ctx

    def _pump_log(self, proc):
        for raw in proc.stdout:
            self.log_cb(raw.decode("utf-8", "replace"))

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
                self.model = None
                self.vision = False
                self.n_ctx = None


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


def chat_turn(base_url: str, messages: list, params: dict, tools: list | None,
              stop: threading.Event, on_event) -> tuple[str, list, str]:
    """Ein gestreamter Modell-Aufruf → (Antworttext, Tool-Aufrufe, Denkprozess).
    on_event(art, daten): "reasoning"/"content" live, am Ende "stats" (Tokens/s)."""
    payload = {"messages": _api_messages(messages), "stream": True, **params}
    if tools:
        payload["tools"] = tools
    req = urllib.request.Request(
        base_url + "/v1/chat/completions", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})

    content, reasoning, calls = [], [], {}
    splitter = _ThinkSplitter()

    def emit(kind, text):
        (reasoning if kind == "reasoning" else content).append(text)
        on_event(kind, text)

    try:
        resp = urllib.request.urlopen(req, timeout=900)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        full = _context_full(e.code, body)
        if full:
            raise full from None
        raise RuntimeError(f"HTTP {e.code}: {body[:500]}") from None

    with resp:
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
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
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
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        msg = json.loads(r.read())["choices"][0]["message"]
    title = re.sub(r"(?s)<think>.*?(</think>|$)", "", msg.get("content") or "").strip()
    title = title.splitlines()[0] if title else ""
    title = re.sub(r"^(überschrift|titel)\s*:\s*", "", title, flags=re.I)
    title = title.strip(" \"'„“”«»*#.").strip()
    return title if len(title) <= 70 else title[:69].rstrip() + "…"
