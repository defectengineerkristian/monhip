"""Hintergrund-Prozesse (prozess_starten, prozess_ausgabe, prozess_stoppen): Programme, die weiterlaufen sollen –
Webserver, `npm run dev`, Beobachter –, statt wie run_command bis zum Ende zu warten. Sie gehören zur App, nicht
zu einer Antwort: Sie laufen über Antworten hinweg und werden beim Beenden von Monhip gestoppt (stop_all)."""

import atexit
import os
import subprocess
import threading
import time

from backend import _end_with_app

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
MAX_RUNNING = 5
KEEP_BYTES = 200_000    # so viel Ausgabe je Prozess bleibt im Speicher (das Ende)
READ_CHARS = 4000       # prozess_ausgabe: höchstens so viel auf einmal (das Neueste)
MAX_WAIT = 30


class ProzessError(Exception):
    """Fehler, den das Modell als verständlichen Satz bekommt (wie agent.ToolError)."""


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds} s" if seconds < 120 else f"{seconds // 60} min"


class Prozess:
    def __init__(self, nr: int, name: str, argv: list[str], cwd):
        self.nr, self.name, self.cwd = nr, name, str(cwd)
        self.started = time.time()
        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")  # Python-Ausgabe sofort sehen
        self.proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, creationflags=NO_WINDOW | NEW_GROUP, env=env)
        _end_with_app(self.proc)  # Job-Objekt: endet mit Monhip samt Unterprozessen, auch nach einem Absturz
        self._buf = bytearray()
        self._dropped = 0       # so viele Bytes vom Anfang sind schon verworfen
        self._read = 0          # bis hierher hat das Modell gelesen (absolut)
        self._ended = False
        self._cond = threading.Condition()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for chunk in iter(lambda: self.proc.stdout.read1(4096), b""):
            with self._cond:
                self._buf += chunk
                if len(self._buf) > KEEP_BYTES:
                    cut = len(self._buf) - KEEP_BYTES
                    del self._buf[:cut]
                    self._dropped += cut
                self._cond.notify_all()
        self.proc.wait()
        with self._cond:
            self._ended = True
            self._cond.notify_all()

    def running(self) -> bool:
        return self.proc.poll() is None

    def status(self) -> str:
        rc = self.proc.poll()
        if rc is None:
            return f"läuft seit {_duration(time.time() - self.started)}"
        return f"beendet mit Exit-Code {rc}"

    def wait_end(self, seconds: float):
        """Bis zu seconds warten – oder bis der Prozess (samt Ausgabe) zu Ende ist."""
        deadline = time.time() + seconds
        with self._cond:
            while not self._ended and time.time() < deadline:
                self._cond.wait(deadline - time.time())

    def read_new(self, wait: float = 0) -> str:
        """Ausgabe seit dem letzten Abruf; wartet bis zu wait Sekunden, falls noch nichts Neues da ist."""
        deadline = time.time() + max(0.0, min(float(wait or 0), MAX_WAIT))
        with self._cond:
            while self._dropped + len(self._buf) == self._read and not self._ended and time.time() < deadline:
                self._cond.wait(deadline - time.time())
            start = max(self._read, self._dropped)
            skipped = start > self._read
            data = bytes(self._buf[start - self._dropped:])
            self._read = self._dropped + len(self._buf)
        text = data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(text) > READ_CHARS:
            text, skipped = text[-READ_CHARS:], True
        return ("…(ältere Ausgabe ausgelassen)\n" if skipped else "") + text

    def stop(self):
        if self.running():
            if os.name == "nt":  # samt allen Programmen, die der Befehl gestartet hat (z. B. node unter npm)
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"], capture_output=True,
                               stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=15)
            else:
                self.proc.kill()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def line(self) -> str:
        return f"[{self.nr}] {self.name} – {self.status()} (Ordner: {self.cwd})"


_procs: dict[int, Prozess] = {}
_lock = threading.Lock()


def start(argv: list[str], cwd, name: str) -> Prozess:
    with _lock:
        if sum(p.running() for p in _procs.values()) >= MAX_RUNNING:
            raise ProzessError(f"Es laufen schon {MAX_RUNNING} Hintergrund-Prozesse – erst einen mit "
                               "prozess_stoppen beenden.")
        nr = max(_procs, default=0) + 1
        p = _procs[nr] = Prozess(nr, " ".join(str(name).split())[:60] or f"Prozess {nr}", argv, cwd)
    return p


def get(nr) -> Prozess:
    try:
        return _procs[int(str(nr).lstrip("#[").rstrip("]"))]
    except (KeyError, ValueError):
        raise ProzessError(f"Einen Prozess [{nr}] gibt es nicht.\n{listing()}") from None


def listing() -> str:
    if not _procs:
        return "Keine Hintergrund-Prozesse."
    return "Hintergrund-Prozesse:\n" + "\n".join(p.line() for p in _procs.values())


def prompt_block() -> str:
    """Für den System-Prompt: was gerade läuft (auch aus früheren Antworten)."""
    running = [p for p in _procs.values() if p.running()]
    if not running:
        return ""
    return "Laufende Hintergrund-Prozesse:\n" + "\n".join(p.line() for p in running)


def stop_all():
    for p in list(_procs.values()):
        try:
            p.stop()
        except Exception:
            pass


atexit.register(stop_all)
