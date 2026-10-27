"""Spracherkennung (lokal) mit whisper.cpp: Programm von GitHub (server/whisper-<build>-<art>/), Modell von
Hugging Face (modelle/whisper/), Mikrofon-Aufnahme über die Windows-MCI-Schnittstelle, Abschreiben mit
whisper-cli – mit Grafikkarte, sonst (z. B. Grafikspeicher voll) automatisch über den Prozessor."""

from i18n import tr

import ctypes
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

import downloads
import llamacpp
from backend import _end_with_app
from images import TEMP_DIR

WHISPER_DIR = llamacpp.SERVER_DIR
MODEL_DIR = Path(__file__).resolve().parent.parent / "modelle" / "whisper"
RELEASES_URL = "https://api.github.com/repos/ggml-org/whisper.cpp/releases?per_page=10"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/"
MODELS = {  # Dateiname → Beschreibung in den Einstellungen
    "ggml-large-v3-turbo-q8_0.bin": tr('Sehr gut – large-v3-turbo (834 MB, empfohlen)'),
    "ggml-large-v3-turbo-q5_0.bin": tr('Gut – large-v3-turbo, kleiner (547 MB)'),
    "ggml-small.bin": tr('Schnell – small (465 MB, für langsame PCs)'),
}
DEFAULT_MODEL = "ggml-large-v3-turbo-q8_0.bin"
LANGUAGES = {tr('Deutsch'): "de", tr('Englisch'): "en", tr('Automatisch erkennen'): "auto"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg"}  # liest whisper-cli selbst (ohne ffmpeg)
_FOLDER_RE = re.compile(r"whisper-b(\d+)-(.+)$")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_audio(path) -> bool:
    return Path(path).suffix.lower() in AUDIO_SUFFIXES


# ---------------------------------------------------------------- Installiert?

def find_cli() -> Path | None:
    """whisper-cli.exe – CUDA vor CPU, neueste zuerst."""
    found = []
    for exe in WHISPER_DIR.glob("whisper-*/whisper-cli.exe") if WHISPER_DIR.is_dir() else []:
        m = _FOLDER_RE.match(exe.parent.name)
        if m and not exe.parent.name.endswith((".part", ".alt")):
            found.append(((0 if "cuda" in m.group(2) else 1), -int(m.group(1)), exe))
    return min(found)[2] if found else None


def find_model(name: str = DEFAULT_MODEL) -> Path | None:
    """Das gewählte Modell, sonst irgendein vorhandenes."""
    if (MODEL_DIR / name).is_file():
        return MODEL_DIR / name
    others = sorted(MODEL_DIR.glob("ggml-*.bin")) if MODEL_DIR.is_dir() else []
    return others[0] if others else None


def ready(name: str = DEFAULT_MODEL) -> bool:
    return bool(find_cli() and find_model(name))


def describe(name: str = DEFAULT_MODEL) -> str:
    exe, model = find_cli(), find_model(name)
    if not exe:
        return tr('Noch nicht installiert.')
    m = _FOLDER_RE.match(exe.parent.name)
    kind = llamacpp._kind_label(m.group(2)) if m else ""
    return (f"whisper.cpp b{m.group(1) if m else '?'} ({kind})"
            + (tr(' · Modell {0}', model.stem.removeprefix('ggml-')) if model else tr(' · noch kein Modell')))


# ---------------------------------------------------------------- Herunterladen

def _pick(release: dict, vendor: str, cuda) -> tuple[str, dict | None]:
    """CUDA-Version (höchstens die vom Treiber unterstützte), sonst CPU mit OpenBLAS – Vulkan gibt es nicht."""
    assets = {a["name"]: a for a in release.get("assets", [])}
    if vendor == "nvidia":
        pat = re.compile(r"whisper-(?:bin-win-cuda|cublas)-(\d+)\.(\d+)(?:\.\d+)?-(?:bin-)?x64\.zip$")
        versions = sorted(((int(m.group(1)), int(m.group(2))), n) for n in assets if (m := pat.match(n)))
        usable = [v for v in versions if not cuda or v[0] <= cuda]
        if usable:
            (major, minor), name = usable[-1]
            return f"cuda-{major}.{minor}", assets[name]
    for name in ("whisper-blas-bin-x64.zip", "whisper-bin-x64.zip"):
        if name in assets:
            return "cpu", assets[name]
    return "", None


def plan(model: str = DEFAULT_MODEL) -> dict:
    """Was fehlt oder neuer ist (Netzwerk – im Thread): program/model je (name, url, größe) oder None."""
    vendor, gpu, cuda = llamacpp.detect_gpu()
    for rel in downloads.get_json(RELEASES_URL):
        kind, asset = _pick(rel, vendor, cuda)
        if asset:
            break
    else:
        raise RuntimeError(tr('Auf GitHub wurde keine passende whisper.cpp-Version für Windows gefunden.'))
    build = re.sub(r"\D", "", rel["tag_name"])
    target = WHISPER_DIR / f"whisper-b{build}-{kind}"
    program = None if (target / "whisper-cli.exe").is_file() else (
        asset["name"], asset["browser_download_url"], asset["size"])
    weights = None if (MODEL_DIR / model).is_file() else (
        model, MODEL_URL + model, downloads.head_size(MODEL_URL + model))
    return {"tag": rel["tag_name"], "kind": llamacpp._kind_label(kind), "gpu": gpu, "target": target,
            "program": program, "model": weights, "size": sum(x[2] for x in (program, weights) if x)}


def install(p: dict, progress, cancel):
    done = 0
    if p["program"]:
        done = downloads.install_zips([p["program"]], p["target"], "whisper-cli.exe", progress, cancel,
                                      total=p["size"])
        downloads.remove_older(p["target"], _FOLDER_RE)
    if p["model"]:
        name, url, _ = p["model"]
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        part = MODEL_DIR / (name + ".part")
        try:
            downloads.download(url, part, progress, cancel, done, p["size"])
            part.replace(MODEL_DIR / name)
        except BaseException:
            part.unlink(missing_ok=True)
            raise


# ---------------------------------------------------------------- Abschreiben

def transcribe(audio: Path, model: str = DEFAULT_MODEL, language: str = "de", gpu: bool = True) -> str:
    """Audiodatei → Text, ein Abschnitt pro Zeile. Blockiert – im Thread aufrufen."""
    exe, weights = find_cli(), find_model(model)
    if not exe or not weights:
        raise RuntimeError(tr('Die Spracherkennung ist noch nicht installiert (Einstellungen → Sprache).'))
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="whisper-", dir=TEMP_DIR))
    try:
        args = [str(exe), "-m", str(weights), "-f", str(audio), "-l", language, "-nt", "-np", "-otxt",
                "-of", str(work / "text"), "-t", str(max(2, min(8, (os.cpu_count() or 4) // 2)))]
        if not gpu:
            args.append("-ng")
        proc = subprocess.Popen(args, cwd=str(exe.parent), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, creationflags=_NO_WINDOW)
        _end_with_app(proc)
        log = proc.communicate(timeout=3600)[0].decode("utf-8", "replace")
        out = work / "text.txt"
        if proc.returncode != 0 or not out.is_file():
            if gpu:  # z. B. Grafikspeicher vom Sprachmodell belegt
                return transcribe(audio, model, language, gpu=False)
            last = [ln for ln in log.splitlines() if ln.strip()][-3:]
            raise RuntimeError(tr('Spracherkennung fehlgeschlagen: ') + (" | ".join(last) or tr('Code {0}', proc.returncode)))
        lines = [ln.strip() for ln in out.read_text(encoding="utf-8", errors="replace").splitlines()]
        return "\n".join(ln for ln in lines if ln and ln not in ("[BLANK_AUDIO]", "[Musik]", "[MUSIC]"))
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------- Mikrofon

class Recorder:
    """Aufnahme vom Standard-Mikrofon (winmm/MCI) als WAV 16 kHz mono – das Format, das Whisper erwartet.
    Nur aus dem Tk-Thread benutzen."""

    ALIAS = "monhip_aufnahme"

    def __init__(self):
        self.active = False
        self.started = 0.0
        if os.name == "nt":
            self._send = ctypes.windll.winmm.mciSendStringW
            self._send.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
            self._error = ctypes.windll.winmm.mciGetErrorStringW
            self._error.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_uint]

    def _mci(self, command: str):
        if os.name != "nt":
            raise RuntimeError(tr('Aufnahme geht nur unter Windows.'))
        err = self._send(command, None, 0, None)
        if err:
            buf = ctypes.create_unicode_buffer(256)
            self._error(err, buf, 255)
            raise RuntimeError(buf.value or tr('MCI-Fehler {0}', err))

    def _close(self):
        try:
            self._mci(f"close {self.ALIAS}")
        except RuntimeError:
            pass

    def start(self):
        self._close()
        self._mci(f"open new type waveaudio alias {self.ALIAS}")
        try:
            self._mci(f"set {self.ALIAS} time format ms bitspersample 16 channels 1 samplespersec 16000 "
                      "bytespersec 32000 alignment 2")
            self._mci(f"record {self.ALIAS}")
        except RuntimeError:
            self._close()
            raise
        self.active, self.started = True, time.time()

    def seconds(self) -> float:
        return time.time() - self.started if self.active else 0.0

    def stop(self) -> Path:
        """Beenden und als WAV im Temp-Ordner speichern."""
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        path = TEMP_DIR / datetime.now().strftime("Diktat %Y-%m-%d %H-%M-%S.wav")
        try:
            self._mci(f"stop {self.ALIAS}")
            self._mci(f'save {self.ALIAS} "{path}"')
        finally:
            self._close()
            self.active = False
        return path

    def cancel(self):
        self._close()
        self.active = False
