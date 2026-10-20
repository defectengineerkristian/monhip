"""Backend: findet Modelle, startet/stoppt llama-server und spricht mit seiner OpenAI-kompatiblen API."""

import json
import os
import re
import shlex
import socket
import subprocess
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
    import ctypes
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

class LlamaServer:
    def __init__(self, log_cb):
        self.proc: subprocess.Popen | None = None
        self.port: int | None = None
        self.model: Path | None = None
        self.vision = False  # Modell versteht Bilder (mit mmproj geladen, laut /props)
        self.log_cb = log_cb

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, server: dict, model: Path, ctx: int, ngl: str, extra: str,
              cancel: threading.Event, timeout: float = 900, mmproj: Path | None = None,
              image_tokens: int | None = None):
        """Startet den Server und blockiert, bis das Modell geladen ist. mmproj = Bild-Projektor (Bildverständnis),
        image_tokens = höchstens so viele Tokens pro Bild."""
        self.stop()
        self.port = _free_port()
        args = [server["exe"], "-m", str(model), "--host", "127.0.0.1",
                "--port", str(self.port), "-c", str(ctx), "--jinja", "--no-webui"]
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
        self.proc = subprocess.Popen(
            args, env=env, cwd=exe_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not _end_with_app(self.proc):
            self.log_cb("Hinweis: llama-server konnte nicht an das Programm gebunden werden – nach einem Absturz "
                        "läuft er evtl. weiter (Task-Manager: llama-server.exe).\n")
        threading.Thread(target=self._pump_log, args=(self.proc,), daemon=True).start()

        deadline = time.time() + timeout
        while time.time() < deadline:
            if cancel.is_set():
                self.stop()
                raise RuntimeError("Laden abgebrochen.")
            if self.proc.poll() is not None:
                raise RuntimeError(f"Server beendet (Code {self.proc.returncode}). Siehe Server-Log.")
            try:
                with urllib.request.urlopen(self.base_url + "/health", timeout=2) as r:
                    if r.status == 200:
                        self.model = model
                        self.vision = self._has_vision()
                        return
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                pass
            time.sleep(0.5)
        self.stop()
        raise RuntimeError("Zeitüberschreitung beim Laden des Modells.")

    def _has_vision(self) -> bool:
        try:
            with urllib.request.urlopen(self.base_url + "/props", timeout=5) as r:
                return bool(json.load(r).get("modalities", {}).get("vision"))
        except (OSError, ValueError, AttributeError):
            return False

    def _pump_log(self, proc):
        for raw in proc.stdout:
            self.log_cb(raw.decode("utf-8", "replace"))

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None
        self.model = None
        self.vision = False


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
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}") from None

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
            tps = (chunk.get("timings") or {}).get("predicted_per_second")
            if tps:
                on_event("stats", tps)
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
