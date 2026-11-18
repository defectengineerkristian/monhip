"""Sprachausgabe (lokal) mit Piper (github.com/rhasspy/piper, MIT-Lizenz): Antworten vorlesen und der Gesprächsmodus.

Programm von GitHub nach server/piper-b<build>-cpu/ – fertig für Windows und Linux (x86_64, aarch64). Es rechnet auf
dem Prozessor (gut 20-mal schneller als gesprochen) und braucht keinen Grafikspeicher. Stimmen von Hugging Face nach
modelle/stimmen/, und zwar aus dem Stand v1.0.0 von rhasspy/piper-voices: Neuere Fassungen dort sind für das
Python-Piper (piper1-gpl) neu gerechnet und lassen sich mit dem fertigen Programm nicht mehr laden
(„… is not a single codepoint“). Die Prüfsummen hier passen zu genau diesem Stand.

Ablauf: Antwort (Markdown – auch Stück für Stück, während sie entsteht) → vorlesbare Sätze (SpeechStream: ohne Code,
Links und Markdown-Zeichen) → ein laufendes piper liest sie zeilenweise von stdin und schreibt je Zeile eine WAV-Datei
(--output_dir) → Wiedergabe (Windows: winsound; Linux: pw-play, paplay oder aplay). Erzeugen und Abspielen laufen in
zwei Threads, so ist der nächste Satz fertig, bevor der vorige verklungen ist.
"""

from i18n import tr

import collections
import os
import platform
import queue
import re
import shutil
import subprocess
import threading
import time
import wave
from pathlib import Path

import downloads
import engines
import llamacpp
import plattform
from backend import _end_with_app, library_dirs
from images import TEMP_DIR
from markdown_lite import classify, closes_fence, is_separator_row, plain, split_row

try:
    import winsound
except ImportError:  # Linux
    winsound = None

PIPER_DIR = llamacpp.SERVER_DIR
VOICE_DIR = plattform.DATA_DIR / "modelle" / "stimmen"
RELEASE_URL = "https://api.github.com/repos/rhasspy/piper/releases/tags/2023.11.14-2"  # letzte Fassung (Archiv)
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/{path}"
EXE = plattform.exe("piper")
_FOLDER_RE = re.compile(r"piper-b(\d+)-(.+)$")   # server/piper-b202311142-cpu
IDLE_SECONDS = 600                                # so lange bleibt piper nach dem letzten Satz geladen
MAX_CHUNK = 350                                   # längere Sätze werden an Kommas geteilt

# Stimmen: Name → Beschreibung, Ordner in rhasspy/piper-voices, Sprache, SHA-256 von .onnx und .onnx.json (v1.0.0)
VOICES = {
    "de_DE-thorsten-medium": {
        "label": tr('Deutsch – Thorsten (männlich, empfohlen, 63 MB)'), "path": "de/de_DE/thorsten/medium", "lang": "de",
        "sha256": ("7e64762d8e5118bb578f2eea6207e1a35a8e0c30595010b666f983fc87bb7819",
                   "974adee790533adb273a1ac88f49027d2a1b8f0f2cf4905954a4791e79264e85")},
    "de_DE-thorsten-high": {
        "label": tr('Deutsch – Thorsten, beste Qualität (männlich, 114 MB)'), "path": "de/de_DE/thorsten/high",
        "lang": "de",
        "sha256": ("9df1c43c61149ef9b39e618e2b861fbe41e1fcea9390b2dac62e8761573ea4f1",
                   "6de734444e4c3f9e33b7ebe2746dbc19b71e85f613e79c65acf623200b99a76a")},
    "de_DE-kerstin-low": {
        "label": tr('Deutsch – Kerstin (weiblich, 63 MB)'), "path": "de/de_DE/kerstin/low", "lang": "de",
        "sha256": ("d352a7641892cebf2903859af94e9ba81a141110215fe3943bcda7f7da401b7a",
                   "56e708556b7b9b7a53c4f8957e021421e69f11a600962bba554cffbe72cf2d47")},
    "de_DE-eva_k-x_low": {
        "label": tr('Deutsch – Eva (weiblich, klein, 21 MB)'), "path": "de/de_DE/eva_k/x_low", "lang": "de",
        "sha256": ("e88cf290fbfb768bf111330d2e8a46e376b0d85e3423a28bfebbc863a260dad8",
                   "ef14b3dcb279ab4b18422a7a132877bee7a148821bd91152fb7ae9c4b3d79625")},
    "en_US-amy-medium": {
        "label": tr('Englisch – Amy (US, weiblich, 63 MB)'), "path": "en/en_US/amy/medium", "lang": "en",
        "sha256": ("b3a6e47b57b8c7fbe6a0ce2518161a50f59a9cdd8a50835c02cb02bdd6206c18",
                   "95a23eb4d42909d38df73bb9ac7f45f597dbfcde2d1bf9526fdeaf5466977d77")},
    "en_US-ryan-medium": {
        "label": tr('Englisch – Ryan (US, männlich, 63 MB)'), "path": "en/en_US/ryan/medium", "lang": "en",
        "sha256": ("abf4c274862564ed647ba0d2c47f8ee7c9b717d27bdad9219100eb310db4047a",
                   "44034c056cb15681b2ad494307c7f3f2e4499d1253c700c711fa0a4607ffe78d")},
}
DEFAULT_VOICES = {"de": "de_DE-thorsten-medium", "en": "en_US-amy-medium"}  # je Sprache der Oberfläche
SPEEDS = {"slow": 1.2, "normal": 1.0, "fast": 0.85}  # --length_scale: größer = langsamer
# Linux: Programme zum Abspielen (Name, Argumente vor der Datei)
PLAYERS = (("pw-play", ()), ("paplay", ()), ("aplay", ("-q",)))


def voice_key(name: str | None, language: str = "de") -> str:
    """Gültige Stimme: die gewählte, sonst die Standardstimme zur Sprache der Oberfläche."""
    return name if name in VOICES else DEFAULT_VOICES.get(language, DEFAULT_VOICES["de"])


def speed_value(name: str | None) -> float:
    return SPEEDS.get(name or "normal", 1.0)


def speed_labels() -> dict[str, str]:
    """Tempo für die Einstellungen: Schlüssel → Beschriftung."""
    return {"slow": tr('Langsam'), "normal": tr('Normal'), "fast": tr('Schnell')}


# ---------------------------------------------------------------- Installiert?

def find_piper() -> Path | None:
    """piper(.exe) in server/piper-b<build>-cpu/ – bewusst nicht aus dem PATH: dort liegt unter Linux oft das
    Python-Piper mit anderen Optionen."""
    return engines.find_program(PIPER_DIR, _FOLDER_RE, EXE, kind="cpu")


def voice_files(key: str) -> list[tuple[Path, str, str]]:
    """[(Zieldatei, URL, SHA-256)] einer Stimme: das Modell und seine Einstellungen (.onnx.json)."""
    v = VOICES[key]
    base = f"{v['path']}/{key}.onnx"
    return [(VOICE_DIR / f"{key}.onnx", VOICE_URL.format(path=base), v["sha256"][0]),
            (VOICE_DIR / f"{key}.onnx.json", VOICE_URL.format(path=base + ".json"), v["sha256"][1])]


def voice_ready(key: str) -> bool:
    return all(dest.is_file() for dest, _, _ in voice_files(key))


def ready(key: str) -> bool:
    return bool(find_piper() and voice_ready(key))


def describe(key: str) -> str:
    exe = find_piper()
    if not exe:
        return tr('Noch nicht installiert.')
    m = _FOLDER_RE.match(exe.parent.name)
    build = m.group(1) if m else "?"
    name = key.split("-")[1].replace("_", " ").title() if "-" in key else key
    return (f"Piper {build[:4]}.{build[4:6]}.{build[6:8]}" if len(build) >= 8 else f"Piper {build}") + (
        tr(' · Stimme {0}', name) if voice_ready(key) else tr(' · Stimme {0} fehlt noch', name))


# ---------------------------------------------------------------- Herunterladen

def asset_name(windows: bool | None = None, machine: str | None = None) -> str | None:
    """Name des fertigen Programms auf GitHub – None, wenn es für diesen Prozessor keines gibt."""
    if plattform.WINDOWS if windows is None else windows:
        return "piper_windows_amd64.zip"  # läuft auf Windows für ARM über die x64-Emulation
    machine = (platform.machine() if machine is None else machine).lower()
    if machine in ("x86_64", "amd64"):
        return "piper_linux_x86_64.tar.gz"
    if machine in ("aarch64", "arm64"):
        return "piper_linux_aarch64.tar.gz"
    return None


def plan(key: str) -> dict:
    """Was fehlt (Netzwerk – im Thread): program = [(name, url, größe, sha256)], weights = [(name, url, größe, ziel,
    sha256)] der fehlenden Stimmdateien, size = alles zusammen."""
    program, target, tag = [], None, ""
    if not find_piper():
        name = asset_name()
        if not name:
            raise RuntimeError(tr('Für diesen Prozessor gibt es Piper nicht als fertiges Programm.'))
        rel = downloads.get_json(RELEASE_URL)
        asset = next((a for a in rel.get("assets", []) if a.get("name") == name), None)
        if not asset:
            raise RuntimeError(tr('Auf GitHub wurde keine passende Piper-Version gefunden.'))
        tag = rel.get("tag_name", "")
        build = re.sub(r"\D", "", tag)
        target = PIPER_DIR / f"piper-b{build}-cpu"
        program = [(asset["name"], asset["browser_download_url"], asset["size"], downloads.asset_sha256(asset))]
    weights = [(dest.name, url, downloads.head_size(url), dest, sha) for dest, url, sha in voice_files(key)
               if not dest.is_file()]
    return {"tag": tag, "target": target, "program": program, "weights": weights, "voice": key,
            "size": sum(x[2] for x in program) + sum(x[2] for x in weights)}


def install(p: dict, progress, cancel):
    """Lädt, was plan() aufzählt: Programm nach server/piper-b<build>-cpu/, dann die Stimme (über .part)."""
    engines.install(p, PIPER_DIR, EXE, _FOLDER_RE, progress, cancel)


# ---------------------------------------------------------------- Text → Sätze

CODE_NOTE = {"de": "Codeblock ausgelassen.", "en": "Code block skipped."}  # gesprochen, in der Sprache der Stimme
_PREFIX = re.compile(r"^\s*(?:>\s?)*(?:#{1,6}\s+|[-*+•]\s+(?:\[[ xX]\]\s+)?|\d{1,4}[.)]\s+)?")
_END = re.compile(r"([.!?…]+)[\"'“”»)\]]*(\s+)")
# Adresse → nur der Name der Seite; Satzzeichen dahinter bleiben stehen
_URL = re.compile(r"https?://(?:www\.)?([^/\s?#]*[^/\s?#.,;:!?'\")\]])\S*?(?=[.,;:!?'\")\]]*(?:\s|$))")
_ABBREV = {"z", "b", "d", "h", "u", "a", "o", "s", "dr", "nr", "bzw", "ca", "usw", "etc", "vgl", "ggf", "evtl", "inkl",
           "zzgl", "mio", "mrd", "fr", "hr", "st", "str", "tel", "bspw", "max", "min", "mr", "mrs", "ms", "vs", "prof",
           "abs", "kap", "ff", "e.g", "i.e", "jh", "uvm", "o.ä", "u.a", "z.b", "d.h"}


def _cut(text: str) -> tuple[list[str], int]:
    """Fertige Sätze vorn in text → (Sätze, Position hinter dem letzten). Abkürzungen („z. B.“, „Dr.“) und
    Ordnungszahlen („am 1. Mai“) beenden keinen Satz, ebenso wenig ein Punkt vor einem kleinen Buchstaben."""
    out, start = [], 0
    for m in _END.finditer(text):
        nxt = text[m.end():m.end() + 1]
        if nxt and nxt.islower():
            continue
        if m.group(1) == ".":
            words = text[start:m.start()].split()
            token = words[-1].lower().strip("(„\"'") if words else ""
            if token.isdigit() or token in _ABBREV or (len(token) == 1 and token.isalpha()):
                continue
        out.append(text[start:m.end()].strip())
        start = m.end()
    return out, start


def _skip_char(ch: str) -> bool:
    """Emojis, Bildzeichen und unsichtbare Verbinder – Piper läse sie sonst als Namen vor oder stolperte."""
    o = ord(ch)
    return o >= 0x1F000 or 0x2600 <= o < 0x27C0 or 0x2B00 <= o < 0x2C00 or 0xE000 <= o < 0xF900 or \
        ch in "️‍⃣"


def clean(text: str) -> str:
    """Eine Zeile Markdown → vorlesbarer Text: Hervorhebungen und Code-Zeichen weg, Links als ihr Text, Adressen nur
    als Name der Seite („github.com“), ohne Emojis. "" = nichts zum Vorlesen."""
    t = plain(text)
    t = _URL.sub(lambda m: m.group(1), t)
    t = "".join(ch for ch in t if not _skip_char(ch))
    t = re.sub(r"(?<=\w)_(?=\w)", " ", t)  # snake_case
    t = re.sub(r"[*`#~|<>]+", " ", t).replace("→", ", ").replace("⇒", ", ")
    t = " ".join(t.split()).strip(" -–—")
    return t if any(c.isalnum() for c in t) else ""


def _chunks(sentence: str) -> list[str]:
    """Überlange Sätze an Kommas/Semikolons teilen – je Zeile rechnet piper alles am Stück."""
    out = []
    while len(sentence) > MAX_CHUNK:
        cut = max(sentence.rfind(sep, 0, MAX_CHUNK) for sep in (", ", "; ", ": ", " – "))
        if cut < MAX_CHUNK // 3:
            cut = sentence.rfind(" ", 0, MAX_CHUNK)
        if cut <= 0:
            cut = MAX_CHUNK
        out.append(sentence[:cut + 1].strip())
        sentence = sentence[cut + 1:].strip()
    if sentence:
        out.append(sentence)
    return out


class SpeechStream:
    """Antworttext, wie er hereinkommt (Stück für Stück), → fertige Sätze zum Vorlesen. Ganze Zeilen werden
    eingeordnet (Codeblock, Tabelle, Liste, Überschrift); aus der angefangenen letzten Zeile kommen die Sätze heraus,
    sobald ihr Ende feststeht – so beginnt das Vorlesen, während das Modell noch schreibt."""

    def __init__(self, language: str = "de"):
        self.language = language
        self.buf = ""        # angefangene Zeile
        self.done = 0        # … davon schon ausgegeben (Zeichen)
        self.marked = False  # … ist eine Überschrift oder ein Listenpunkt
        self.fence = None    # in einem Codeblock: dessen Zaun (``` bzw. ~~~)

    def feed(self, text: str) -> list[str]:
        self.buf += text
        out = []
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            out += self._line(line)
        return out + self._partial()

    def flush(self) -> list[str]:
        """Die angefangene Zeile ist fertig (z. B. Ende eines Antwortteils vor einem Werkzeugaufruf)."""
        line, self.buf = self.buf, ""
        out = self._line(line) if line.strip() else []
        self.done, self.marked, self.fence = 0, False, None
        return out

    def _line(self, raw: str) -> list[str]:
        start, self.done = self.done, 0
        try:
            return self._classify(raw, start)
        finally:
            self.marked = False

    def _classify(self, raw: str, start: int) -> list[str]:
        if self.fence:
            if closes_fence(raw, self.fence):
                self.fence = None
            return []
        if start == 0:
            kind, info = classify(raw)
            if kind == "fence":
                self.fence = info["fence"]
                return [CODE_NOTE.get(self.language, CODE_NOTE["en"])]
            if kind in ("blank", "hr", "pagebreak"):
                return []
            if kind == "table":
                cells = split_row(raw)
                if is_separator_row(cells):
                    return []
                text = ", ".join(c for c in (clean(c) for c in cells) if c)
                return [text + "."] if text else []
        return self._speak(raw[start:], start == 0, final=True)[0]

    def _partial(self) -> list[str]:
        raw = self.buf
        if self.fence or not raw.strip() or raw.lstrip().startswith(("|", "`", "~")):
            return []
        out, used = self._speak(raw[self.done:], self.done == 0, final=False)
        self.done += used
        return out

    def _speak(self, text: str, at_start: bool, final: bool) -> tuple[list[str], int]:
        """Sätze aus text (ab dem Zeilenanfang: ohne Listen-/Überschrift-Zeichen) → (Sätze, verbrauchte Zeichen)."""
        offset = 0
        if at_start:
            m = _PREFIX.match(text)
            offset, self.marked = m.end(), bool(m.group(0).strip())
        marked, body = self.marked, text[offset:]
        parts, end = _cut(body)
        if final:
            if body[end:].strip():
                parts.append(body[end:])
            end = len(body)
        elif not parts:
            return [], 0
        out = []
        for part in parts:
            said = clean(part)
            if said:
                out += _chunks(said)
        if final and marked and out and out[-1][-1] not in ".!?:;…":
            out[-1] += "."  # Überschrift, Listenpunkt: kurze Pause statt Weiterlesen in einem Atemzug
        return out, offset + end


def speakable(markdown: str, language: str = "de") -> list[str]:
    """Ganzer Text → Sätze zum Vorlesen."""
    s = SpeechStream(language)
    return s.feed(markdown) + s.flush()


# ---------------------------------------------------------------- piper und Wiedergabe

def _arg_path(p: Path) -> str:
    """Pfad als Argument für piper: Unter Windows bekommt es Argumente in der ANSI-Codepage – Pfade mit anderen
    Zeichen (etwa ein Benutzername in kyrillischer Schrift) daher über den kurzen 8.3-Namen."""
    s = str(p)
    if not plattform.WINDOWS:
        return s
    try:
        s.encode("mbcs")
        return s
    except UnicodeEncodeError:
        import ctypes
        buf = ctypes.create_unicode_buffer(32768)
        n = ctypes.windll.kernel32.GetShortPathNameW(s, buf, len(buf))
        return buf.value if 0 < n < len(buf) else s


class _Piper:
    """Ein laufendes piper mit einer Stimme: say(satz) → WAV-Datei in folder. Nur aus einem Thread benutzen."""

    def __init__(self, exe: Path, voice: str, speed: float, folder: Path, log=None):
        self.key, self.folder, self.log = (voice, speed), folder, log
        self.seen: set[str] = set()
        self.tail: collections.deque = collections.deque(maxlen=6)
        args = [str(exe), "--model", _arg_path(VOICE_DIR / f"{voice}.onnx"), "--output_dir", _arg_path(folder),
                "--length_scale", f"{speed:g}", "--sentence_silence", "0.25"]
        env = os.environ.copy()
        if not plattform.WINDOWS:  # die .so-Dateien liegen neben dem Programm
            env["LD_LIBRARY_PATH"] = os.pathsep.join(
                library_dirs(exe.parent) + [p for p in [env.get("LD_LIBRARY_PATH")] if p])
        self.proc = plattform.popen(args, bound=True, cwd=str(exe.parent), env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _end_with_app(self.proc)
        threading.Thread(target=self._pump_errors, daemon=True).start()

    def _pump_errors(self):
        for raw in self.proc.stderr:
            line = raw.decode("utf-8", "replace").strip()
            if line:
                self.tail.append(re.sub(r"^\[[^\]]*\]\s*\[piper\]\s*", "", line))
                if self.log and ("[error]" in line or "[warning]" in line):
                    self.log("Piper: " + line + "\n")

    def say(self, sentence: str) -> Path:
        """Ein Satz → fertige WAV-Datei (blockiert, bis piper sie geschrieben hat)."""
        try:
            self.proc.stdin.write((" ".join(sentence.split()) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
            line = self.proc.stdout.readline()
        except (OSError, ValueError):
            line = b""
        if not line:
            time.sleep(0.2)  # die letzte Fehlerzeile abwarten
            reason = self.tail[-1] if self.tail else tr('Code {0}', self.proc.poll())
            raise RuntimeError(tr('Die Sprachausgabe (Piper) hat sich beendet: {0}', reason))
        # piper nennt die Datei auf stdout – in welcher Kodierung, hängt vom System ab; sicherer: die neue im Ordner
        new = [p for p in self.folder.glob("*.wav") if p.name not in self.seen]
        if not new:
            raise RuntimeError(tr('Die Sprachausgabe (Piper) hat keine Datei geschrieben.'))
        path = min(new, key=lambda p: (len(p.stem), p.stem))  # Namen sind Zeitstempel: die älteste zuerst
        self.seen.add(path.name)
        return path

    def close(self):
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(2)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def find_player() -> tuple[str, tuple] | None:
    """Linux: Programm zum Abspielen von WAV-Dateien."""
    for name, args in PLAYERS:
        exe = plattform.which(name)
        if exe:
            return exe, args
    return None


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate() or 22050)


class Speaker:
    """Liest vor: start() + feed()/flush()/finish() (Stück für Stück, während eine Antwort entsteht) bzw. say() für
    einen fertigen Text; stop() bricht sofort ab. start/feed/flush/finish/stop nur aus einem Thread (dem Tk-Thread)
    aufrufen. on_state(spricht) und on_error(text) kommen aus Hintergrund-Threads; tag merkt sich, was gerade
    vorgelesen wird (z. B. der Text einer Antwort – „Vorlesen“ ist dann ein Umschalter)."""

    def __init__(self, on_state=None, on_error=None, log=None):
        self.on_state, self.on_error, self.log = on_state, on_error, log
        self.active = False
        self.tag = None
        self._lock = threading.Lock()
        self._gen = 0
        self._texts: queue.Queue = queue.Queue()
        self._wavs: queue.Queue = queue.Queue()
        self._stream: SpeechStream | None = None
        self._voice, self._speed = DEFAULT_VOICES["de"], 1.0
        self._piper: _Piper | None = None
        self._player: subprocess.Popen | None = None
        self._folder: Path | None = None
        self._threads: list[threading.Thread] = []

    # -------------------------------------------------- aus dem Tk-Thread

    def start(self, voice: str, speed: float = 1.0, tag=None):
        """Neues Vorlesen beginnen (ein laufendes endet); danach feed()/flush() und am Ende finish()."""
        self.stop()
        with self._lock:
            self._voice, self._speed, self.tag = voice, speed, tag
            self.active = True
        self._stream = SpeechStream(VOICES.get(voice, VOICES[DEFAULT_VOICES["de"]])["lang"])
        if not self._threads:
            self._threads = [threading.Thread(target=self._synth_loop, daemon=True),
                             threading.Thread(target=self._play_loop, daemon=True)]
            for t in self._threads:
                t.start()
        self._state(True)

    def feed(self, text: str):
        if self._stream:
            self._put(self._stream.feed(text))

    def flush(self):
        if self._stream:
            self._put(self._stream.flush())

    def finish(self):
        """Der Text ist vollständig: Rest vorlesen, danach meldet on_state(False) das Ende."""
        if self._stream:
            self._put(self._stream.flush())
            self._texts.put((self._gen, None))
            self._stream = None

    def say(self, markdown: str, voice: str, speed: float = 1.0, tag=None):
        self.start(voice, speed, tag)
        self.feed(markdown)
        self.finish()

    def stop(self):
        with self._lock:
            self._gen += 1
            was, self.active, self.tag = self.active, False, None
            self._halt()
        self._stream = None
        if was:
            self._state(False)

    def shutdown(self):
        self.stop()
        if self._threads:
            self._texts.put((None, None))
            self._wavs.put((None, None))
        if self._folder:
            shutil.rmtree(self._folder, ignore_errors=True)

    # -------------------------------------------------- Hintergrund

    def _put(self, sentences: list[str]):
        for s in sentences:
            self._texts.put((self._gen, s))

    def _state(self, active: bool):
        if self.on_state:
            self.on_state(active)

    def _halt(self):
        """Wiedergabe sofort beenden (unter self._lock)."""
        if winsound:
            winsound.PlaySound(None, 0)
        elif self._player and self._player.poll() is None:
            self._player.kill()
        self._player = None

    def _fail(self, gen: int, message: str):
        with self._lock:
            if gen != self._gen:
                return
            self._gen += 1
            self.active, self.tag = False, None
            self._halt()
        self._state(False)
        if self.on_error:
            self.on_error(message)

    def _get_piper(self) -> _Piper:
        key = (self._voice, self._speed)
        if self._piper and self._piper.key == key and self._piper.proc.poll() is None:
            return self._piper
        self._close_piper()
        exe = find_piper()
        if not exe or not voice_ready(self._voice):
            raise RuntimeError(tr('Die Sprachausgabe ist noch nicht installiert (Einstellungen → Sprache).'))
        if not self._folder:
            TEMP_DIR.mkdir(parents=True, exist_ok=True)
            self._folder = TEMP_DIR / f"vorlesen-{os.getpid()}"
        shutil.rmtree(self._folder, ignore_errors=True)
        self._folder.mkdir(parents=True, exist_ok=True)
        self._piper = _Piper(exe, self._voice, self._speed, self._folder, self.log)
        return self._piper

    def _close_piper(self):
        if self._piper:
            self._piper.close()
            self._piper = None

    def _synth_loop(self):
        while True:
            try:
                gen, sentence = self._texts.get(timeout=IDLE_SECONDS)
            except queue.Empty:
                self._close_piper()  # lange nichts vorgelesen: Arbeitsspeicher freigeben
                continue
            if gen is None:
                self._close_piper()
                return
            if gen != self._gen:
                continue
            if sentence is None:
                self._wavs.put((gen, None))
                continue
            try:
                path = self._get_piper().say(sentence)
            except Exception as e:  # piper fehlt, stürzt ab … – Meldung an die Oberfläche, nächstes Mal neu starten
                self._close_piper()
                self._fail(gen, str(e))
                continue
            if gen != self._gen:
                path.unlink(missing_ok=True)
                continue
            self._wavs.put((gen, path))

    def _play_loop(self):
        while True:
            gen, path = self._wavs.get()
            if gen is None:
                return
            if path is None:  # Ende des Textes
                with self._lock:
                    if gen != self._gen:
                        continue
                    self.active, self.tag = False, None
                self._state(False)
                continue
            try:
                self._play(gen, path)
            except Exception as e:
                self._fail(gen, tr('Wiedergabe fehlgeschlagen: {0}', e))
            finally:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _play(self, gen: int, path: Path):
        """Eine WAV-Datei abspielen – blockiert, bis sie zu Ende ist oder stop() kommt."""
        seconds = wav_seconds(path)
        with self._lock:
            if gen != self._gen:
                return
            if winsound:
                winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            else:
                player = find_player()
                if not player:
                    raise RuntimeError(tr('Zum Abspielen fehlt pw-play, paplay oder aplay (Paket pipewire-bin, '
                                          'pulseaudio-utils bzw. alsa-utils).'))
                self._player = plattform.popen([player[0], *player[1], str(path)], stdin=subprocess.DEVNULL,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            proc = self._player
        end = time.monotonic() + seconds + (0.05 if winsound else 2.0)
        while time.monotonic() < end and gen == self._gen:
            if proc is not None and proc.poll() is not None:
                break
            time.sleep(0.03)
