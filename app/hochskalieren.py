"""Bilder hochskalieren mit Real-ESRGAN (github.com/xinntao/Real-ESRGAN, BSD-3-Clause) über sd-cli von
stable-diffusion.cpp (-M upscale) – dieselbe Bild-Engine wie beim Erzeugen, nur das Programm daneben statt sd-server.
Die Modelle (.pth, je eines für Fotos und für Illustrationen) kommen von GitHub nach modelle/bild/Real-ESRGAN/.

Real-ESRGAN vergrößert immer 4×; „2×“ ist 4× und danach sauber verkleinert (images.fit) – schärfer als nur 2× zu
strecken. Gerechnet wird in Kacheln auf der Grafikkarte (etwa 1 GB Grafikspeicher, ein Bild mit 1024 Pixeln in
etwa 20 s); reicht der Speicher nicht, geht es über den Prozessor (deutlich langsamer)."""

from i18n import tr

import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path

import downloads
import images
import plattform
import rocm_runtime
import sdcpp
from backend import _end_with_app, library_dirs

MODEL_DIR = sdcpp.MODEL_DIR / "Real-ESRGAN"
CLI_NAMES = ("sd-cli", "sd")   # neuere Releases: sd-cli, ältere: sd
NEED_MIB = 1500                # Grafikspeicher fürs Rechnen in Kacheln (gemessen etwa 1 GB) samt Reserve
TILE = 128
FACTORS = (2, 4)
UPSCALERS = {  # Schlüssel → Name (Auswahl oben), Datei, Download, Größe in MB, SHA-256
    "photo": {"name": "Real-ESRGAN – " + tr('Fotos'), "file": "RealESRGAN_x4plus.pth",
              "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
              "mb": 64, "sha256": "4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1"},
    "art": {"name": "Real-ESRGAN – " + tr('Illustrationen'), "file": "RealESRGAN_x4plus_anime_6B.pth",
            "url": "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
            "mb": 17, "sha256": "f872d837d3c90ed2e05227bed711af5671a6fd1c9f7d7e91c911a61f155e99da"},
}
DEFAULT = "photo"
LICENSE = tr('Real-ESRGAN: BSD-3-Clause – die Ergebnisse dürfen auch kommerziell genutzt werden.')
_PROGRESS = re.compile(rb"\|\s*(\d+)/(\d+)\s*-")  # „|=====>   |  3/12 - 5.52it/s“
_LOADED = b"loading tensors completed"            # ab hier zählt der Balken die Kacheln


class Cancelled(RuntimeError):
    """Abgebrochen („Stopp“)."""


def key(name: str | None) -> str:
    return name if name in UPSCALERS else DEFAULT


def model_path(name: str) -> Path:
    return MODEL_DIR / UPSCALERS[key(name)]["file"]


def find_cli() -> Path | None:
    """sd-cli neben dem sd-server der installierten Bild-Engine (unter Linux sonst aus dem PATH)."""
    server = sdcpp.find_server()
    if server:
        for name in CLI_NAMES:
            exe = server.parent / plattform.exe(name)
            if exe.is_file():
                return exe
    if not plattform.WINDOWS:
        found = plattform.which("sd-cli")
        return Path(found) if found else None
    return None


def ready(name: str) -> bool:
    return bool(find_cli() and model_path(name).is_file())


def describe(name: str) -> str:
    """Stand oben rechts unter der Auswahl."""
    up = UPSCALERS[key(name)]
    if not find_cli():
        return tr('Bild-Engine fehlt noch – wird beim ersten Hochskalieren heruntergeladen')
    if not model_path(name).is_file():
        return tr('Fehlt noch – wird beim ersten Hochskalieren heruntergeladen ({0} MB)', up["mb"])
    return tr('Bereit: {0}', up["name"])


def result_size(width: int, height: int, factor: int) -> tuple[int, int]:
    return width * factor, height * factor


def plan(name: str) -> dict:
    """Was fehlt (Netzwerk – im Thread): ggf. die Bild-Engine (wie sdcpp.plan, aber ohne Bildmodell) und das
    Hochskalier-Modell. Aufbau wie sdcpp.plan, damit sdcpp.install es laden kann."""
    up = UPSCALERS[key(name)]
    if find_cli():
        p = {"tag": "", "kind": "", "gpu": "", "target": None, "program": [], "runtime": None}
    else:
        p = sdcpp.plan(sdcpp.model_key(None))
        if not p.get("program") and not find_cli():
            raise RuntimeError(tr('Die installierte Bild-Engine enthält kein sd-cli – bitte unter Einstellungen → '
                                  'Bilder aktualisieren.'))
    dest = model_path(name)
    p["weights"] = [] if dest.is_file() else [(dest.name, up["url"], downloads.head_size(up["url"]) or
                                               up["mb"] * 2 ** 20, dest, up["sha256"])]
    p["size"] = (sum(x[2] for x in p.get("program") or []) + sum(x[2] for x in p["weights"])
                 + (p["runtime"]["size"] if p.get("runtime") else 0))
    return p


def install(p: dict, progress, cancel):
    sdcpp.install(p, progress, cancel)


def _environment(exe: Path) -> dict:
    """Umgebung wie beim sd-server: Bibliotheken neben dem Programm, unter Windows ggf. die ROCm-Laufzeit."""
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(exe.parent), env.get("PATH", "")])
    if not plattform.WINDOWS:
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            library_dirs(exe.parent) + [p for p in [env.get("LD_LIBRARY_PATH")] if p])
    elif exe.parent.name.endswith("-rocm"):
        env = rocm_runtime.environment(exe, env)
    return env


def _run(args: list[str], exe: Path, stop: threading.Event, on_progress, log) -> tuple[int, list[str]]:
    """sd-cli ausführen; on_progress(erledigt, gesamt) je Kachel. → (Rückgabewert, letzte Zeilen der Ausgabe)."""
    if log:
        log("> " + (subprocess.list2cmdline(args) if plattform.WINDOWS else shlex.join(args)) + "\n")
    proc = plattform.popen(args, bound=True, env=_environment(exe), cwd=str(exe.parent), stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    _end_with_app(proc)
    tail: list[str] = []

    def pump():  # der Fortschrittsbalken kommt ohne Zeilenumbruch – daher in Stücken lesen
        rest, loaded = b"", False
        while chunk := proc.stdout.read1(4096):
            window = rest[-40:] + chunk  # ein Satz über die Grenze zweier Stücke
            if not loaded and _LOADED in window:  # davor zählt derselbe Balken die Teile des Modells
                loaded, window = True, window[window.find(_LOADED):]
            found = _PROGRESS.findall(window) if loaded else []
            if found and on_progress:
                done, total = found[-1]
                on_progress(int(done), int(total))
            rest = (rest + chunk)[-4000:]
            if log:
                log(chunk.decode("utf-8", "replace").replace("\x1b[K", ""))
        tail.extend(line.strip() for line in re.split(r"[\r\n]+", rest.decode("utf-8", "replace")) if line.strip())

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    try:
        while proc.poll() is None:
            if stop.is_set():
                proc.kill()
                proc.wait()
                raise Cancelled(tr('Abgebrochen.'))
            time.sleep(0.1)
        reader.join(5)
    finally:
        reader.join(1)
        proc.stdout.close()
    if stop.is_set():
        raise Cancelled(tr('Abgebrochen.'))
    return proc.returncode, tail[-12:]


def upscale(name: str, source: Path, out: Path, factor: int, stop: threading.Event, on_progress=None, log=None,
            on_cpu=None) -> tuple[int, int]:
    """source (PNG) → out (PNG), factor 2 oder 4. Blockiert (im Thread aufrufen). Klappt es auf der Grafikkarte
    nicht (z. B. Speicher voll), noch einmal über den Prozessor – on_cpu() meldet das vorher. → (Breite, Höhe)."""
    exe = find_cli()
    model = model_path(name)
    if not exe or not model.is_file():
        raise RuntimeError(tr('Bild-Engine oder Hochskalier-Modell fehlt.'))
    factor = factor if factor in FACTORS else 4
    four = out.with_name(out.stem + "-4x.png") if factor != 4 else out
    args = [str(exe), "-M", "upscale", "--upscale-model", str(model), "-i", str(source), "-o", str(four),
            "--upscale-tile-size", str(TILE)]
    code, tail = _run(args, exe, stop, on_progress, log)
    if code != 0 or not four.is_file():
        if on_cpu:
            on_cpu()
        four.unlink(missing_ok=True)
        code, tail = _run(args + ["--backend", "cpu"], exe, stop, on_progress, log)
    if code != 0 or not four.is_file():
        reason = next((t for t in reversed(tail) if re.search(r"error|fail|cannot|out of memory", t, re.I)),
                      tail[-1] if tail else "")
        raise RuntimeError(tr('Das Bild ließ sich nicht hochskalieren (Code {0}): {1}', code,
                              reason or tr('Details unter Einstellungen → Server-Log')))
    if four != out:  # 2×: das 4×-Ergebnis sauber auf die Hälfte verkleinern
        w, h = images.png_size(four)
        try:
            images.fit(four, out, w // 2, h // 2)
        finally:
            four.unlink(missing_ok=True)
    elif not out.is_file():
        shutil.move(str(four), str(out))
    return images.png_size(out)
