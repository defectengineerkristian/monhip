"""3D-Modelle aus einem Bild mit trellis.cpp (github.com/pwilkin/trellis.cpp) – Microsofts TRELLIS.2 in C++/GGML,
ohne Python: Programm von GitHub (server/trellis-<Version>-<Art>/), Modelldateien von Hugging Face
(modelle/3d/<Variante>/). Für jedes Modell startet Monhip trellis-cli (Bild → GLB mit Textur) und liest den
Fortschritt aus seiner Ausgabe; danach beendet es sich und der Grafikspeicher ist wieder frei. Einen Server mit
offenem Port (trellis-server antwortet jedem, ohne Schlüssel) braucht es dafür nicht.

Grafikkarte: NVIDIA nimmt CUDA, wenn Treiber und Karte dazu passen (das CUDA-13-Paket ab Turing, das CUDA-12-Paket für
Pascal/Volta), sonst – wie AMD und Intel – Vulkan, das ohne Zusätze läuft. Ein Paket für den Prozessor allein gibt es
nicht (dort bräuchte ein Modell Stunden). Linux: dieselben Programme als .tar.gz; ein trellis-cli aus dem PATH (selbst
gebaut) geht ebenso."""

from i18n import tr

import os
import platform
import re
import shlex
import subprocess
import threading
import time
from pathlib import Path

import downloads
import engines
import llamacpp
import plattform
from backend import _end_with_app, library_dirs

SERVER_DIR = llamacpp.SERVER_DIR
MODEL_DIR = plattform.DATA_DIR / "modelle" / "3d"
RELEASES_URL = "https://api.github.com/repos/pwilkin/trellis.cpp/releases?per_page=10"
HF_URL = "https://huggingface.co/ilintar/trellis2-gguf/resolve/main/{path}"
CLI_EXE = plattform.exe("trellis-cli")
FILES = ("birefnet.gguf", "dinov3.gguf", "ss_flow.gguf", "ss_dec.gguf", "shape_flow_512.gguf", "shape_flow_1024.gguf",
         "shape_dec.gguf", "tex_flow_512.gguf", "tex_flow_1024.gguf", "tex_dec.gguf")
_FOLDER_RE = re.compile(r"trellis-([\d.]+)-(cuda12|cuda|vulkan)$")   # Ordner in server/: trellis-0.8.1-vulkan …
_TAG_RE = re.compile(r"v?(\d+(?:\.\d+)*)$")                          # Releases heißen „v0.8.1“
# Varianten der Modelldateien: dieselben Namen, in Unterordnern des Repositorys (wie im Installer von trellis.cpp)
VARIANTS = {  # die erste ist der Standard (DEFAULT_VARIANT)
    "q8": {"name": "TRELLIS.2 (Q8)", "sub": "q8/", "gb": 9.5,
           "label": tr('TRELLIS.2 – nahezu volle Genauigkeit (9,5 GB)')},
    "f16": {"name": "TRELLIS.2", "sub": "", "gb": 16.5,
            "label": tr('TRELLIS.2 – volle Genauigkeit (16,5 GB)')},
    "q4": {"name": "TRELLIS.2 (Q4)", "sub": "q4/", "gb": 6.0,
           "label": tr('TRELLIS.2 – kleiner, etwas ungenauer (6 GB)')},
}
DEFAULT_VARIANT = "q8"
LICENSE = tr('TRELLIS.2 und BiRefNet: MIT-Lizenz · DINOv3 (Bildverständnis): DINOv3-Lizenz von Meta')
RESOLUTIONS = (1024, 512)  # Feinheit der Form: 1024 (Standard, ab 16 GB Grafikspeicher) bzw. 512 (schneller)
# Die Schritte von trellis-cli („[4/7] shape SLAT flow …“) und ihr ungefährer Anteil an der Rechenzeit
STAGE_SHARE = {1: 0.03, 2: 0.02, 3: 0.12, 4: 0.38, 5: 0.08, 6: 0.30, 7: 0.07}
_STAGE_RE = re.compile(r"^\s*\[(\d)/\d\]")
_FLOW_RE = re.compile(r"\[flow\]\s+\[[#.]*\]\s*(\d+)/(\d+).*?(?:~(\d+)s left)?\s*$")


def stage_name(n: int) -> str:
    return {1: tr('Hintergrund entfernen'), 2: tr('Bild auswerten'), 3: tr('Grundform'), 4: tr('Form verfeinern'),
            5: tr('Oberfläche bilden'), 6: tr('Farben und Material'), 7: tr('Speichern')}.get(n, "")


class Cancelled(RuntimeError):
    """Abgebrochen („Stopp“)."""


# ---------------------------------------------------------------- Installiert?

def variant_key(key: str | None) -> str:
    """Gültige Variante: die gewählte, sonst eine schon vollständig vorhandene, sonst der Standard."""
    if key in VARIANTS:
        return key
    return next((k for k in VARIANTS if model_ready(k)), DEFAULT_VARIANT)


def model_files(key: str) -> list[tuple[Path, str]]:
    """[(Zieldatei, URL)] der Modelldateien einer Variante."""
    v = VARIANTS[variant_key(key)]
    folder = MODEL_DIR / variant_key(key)
    return [(folder / name, HF_URL.format(path=v["sub"] + name)) for name in FILES]


def model_ready(key: str) -> bool:
    if key not in VARIANTS:
        return False
    return all(dest.is_file() for dest, _ in model_files(key))


def find_cli() -> Path | None:
    """trellis-cli(.exe) – CUDA vor Vulkan, neueste Version zuerst; unter Linux sonst der aus dem PATH."""
    return engines.find_program(SERVER_DIR, _FOLDER_RE, CLI_EXE,
                                order=lambda m: tuple(-int(x) for x in m.group(1).split(".")))


def ready(key: str) -> bool:
    return bool(find_cli() and model_ready(key))


_kind_label = engines.kind_label


def describe(key: str) -> str:
    """Kurzer Stand für Einstellungen und Kopfzeile: Programm und Modell."""
    exe = find_cli()
    m = _FOLDER_RE.match(exe.parent.name) if exe else None
    if not exe:
        program = tr('3D-Engine noch nicht installiert')
    elif m:
        program = f"trellis.cpp {m.group(1)} ({_kind_label(m.group(2))})"
    else:
        program = f"trellis-cli ({exe})"
    name = VARIANTS[variant_key(key)]["name"]
    return program + (tr(' · Modell {0}', name) if model_ready(variant_key(key)) else
                      tr(' · Modell {0} fehlt noch', name))


def missing_gb(key: str) -> float:
    """Ungefähr noch herunterzuladen (GB), ohne Netz: Anteil der fehlenden Modelldateien, dazu das Programm."""
    files = model_files(key)
    gone = sum(1 for dest, _ in files if not dest.is_file())
    return VARIANTS[variant_key(key)]["gb"] * gone / len(files) + (0.0 if find_cli() else 0.5)


# ---------------------------------------------------------------- Herunterladen

def compute_capability() -> tuple[int, int] | None:
    """Compute Capability der ersten NVIDIA-Karte (nvidia-smi), z. B. (8, 9) – unbekannt: None."""
    out = llamacpp._run(["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"])
    m = re.search(r"(\d+)\.(\d+)", out)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _pick(release: dict, vendor: str, cuda: tuple[int, int] | None, cc: tuple[int, int] | None,
          linux: bool = not plattform.WINDOWS) -> tuple[str, dict | None]:
    """Passendes Paket eines Releases → (Art, Asset). CUDA nur, wenn der Treiber die CUDA-Version des Pakets kann und
    die Karte zu den mitgebauten passt: „cuda“ (CUDA 13, ab Turing 7.5), „cuda12“ (CUDA 12.9, Pascal/Volta 6.0–7.0) –
    sonst Vulkan (läuft auch auf NVIDIA). Programme gibt es nur für x64."""
    if platform.machine().lower() not in ("amd64", "x86_64", "x64"):
        return "", None
    ending = "linux-x64.tar.gz" if linux else "windows-x64.zip"
    assets = {a.get("name"): a for a in release.get("assets", [])}
    if vendor == "nvidia" and cuda and cc:
        if cc >= (7, 5) and cuda >= (13, 0) and f"trellis-cuda-{ending}" in assets:
            return "cuda", assets[f"trellis-cuda-{ending}"]
        if (6, 0) <= cc < (7, 5) and cuda >= (12, 0) and f"trellis-cuda12-{ending}" in assets:
            return "cuda12", assets[f"trellis-cuda12-{ending}"]
    if f"trellis-vulkan-{ending}" in assets:
        return "vulkan", assets[f"trellis-vulkan-{ending}"]
    return "", None


def plan(key: str = DEFAULT_VARIANT, update: bool = True) -> dict:
    """Was fehlt (Netzwerk – im Thread aufrufen): program = [(name, url, größe, sha256)] des Programms (leer, wenn das
    neueste schon da ist), weights = [(name, url, größe, ziel)] der fehlenden Modelldateien, size = alles zusammen.
    update=False: eine vorhandene 3D-Engine nicht aktualisieren, nur Fehlendes laden."""
    key = variant_key(key)
    weights = [(dest.name, url, downloads.head_size(url), dest) for dest, url in model_files(key)
               if not dest.is_file()]
    base = {"tag": "", "kind": "", "gpu": "", "target": None, "program": [], "weights": weights, "variant": key}
    if not update and find_cli():
        return {**base, "size": sum(x[2] for x in weights)}
    vendor, gpu, cuda = llamacpp.detect_gpu()
    cc = compute_capability() if vendor == "nvidia" else None
    system = None if plattform.WINDOWS else plattform.which("trellis-cli")
    try:
        releases = downloads.get_json(RELEASES_URL)
    except (OSError, ValueError):
        if not (system or find_cli()):
            raise
        releases = []
    tag, kind, target, program = "", "", None, []
    for rel in releases:
        m = _TAG_RE.match(rel.get("tag_name", ""))
        if rel.get("draft") or rel.get("prerelease") or not m:
            continue
        kind, asset = _pick(rel, vendor, cuda, cc)
        if asset:
            tag, target = rel["tag_name"], SERVER_DIR / f"trellis-{m.group(1)}-{kind}"
            if not (target / CLI_EXE).is_file():
                program = [(asset["name"], asset["browser_download_url"], asset.get("size", 0),
                            downloads.asset_sha256(asset))]
            break
    else:
        if not (system or find_cli()):
            raise RuntimeError(tr('Auf GitHub wurde keine passende Version von trellis.cpp gefunden.'))
    return {**base, "tag": tag, "kind": _kind_label(kind) if kind else "", "gpu": gpu, "target": target,
            "program": program, "size": sum(x[2] for x in program) + sum(x[2] for x in weights)}


def install(p: dict, progress, cancel):
    """Lädt, was plan() aufzählt: Programm nach server/trellis-<Version>-<Art>/, dann die Modelldateien."""
    engines.install(p, SERVER_DIR, CLI_EXE, _FOLDER_RE, progress, cancel)


# ---------------------------------------------------------------- Erzeugen

def parse_progress(line: str, state: dict) -> bool:
    """Eine Zeile der Ausgabe von trellis-cli auswerten: state bekommt „stage“ (1–7), „step“/„steps“ der laufenden
    Rechnung und „eta“ (Sekunden, soweit trellis-cli sie schätzt). True, wenn sich etwas geändert hat."""
    m = _STAGE_RE.match(line)
    if m:
        state.update(stage=int(m.group(1)), step=0, steps=0, eta=None)
        return True
    m = _FLOW_RE.search(line)
    if m:
        state.update(step=int(m.group(1)), steps=int(m.group(2)), eta=int(m.group(3)) if m.group(3) else None)
        return True
    return False


def fraction(state: dict) -> float:
    """Ungefährer Anteil der erledigten Arbeit (0–1) aus parse_progress."""
    stage = state.get("stage") or 0
    done = sum(share for n, share in STAGE_SHARE.items() if n < stage)
    inner = state["step"] / state["steps"] if state.get("steps") else 0.0
    return min(1.0, done + STAGE_SHARE.get(stage, 0) * inner)


def generate(key: str, image: Path, out: Path, resolution: int, seed: int, stop: threading.Event,
             on_progress=None, log=None) -> Path:
    """Bild (PNG) → 3D-Modell (GLB) in out. Blockiert (im Thread aufrufen); on_progress(state) bei jedem neuen Stand
    (parse_progress), log(zeile) bekommt die ganze Ausgabe (Server-Log). stop bricht ab (Cancelled). Hilfsdateien
    von trellis-cli landen neben out – am besten in einem eigenen leeren Ordner."""
    exe = find_cli()
    key = variant_key(key)
    if not exe or not model_ready(key):
        raise RuntimeError(tr('3D-Engine oder Modell fehlt – bitte unter Einstellungen → Bilder herunterladen.'))
    args = [str(exe), "-i", str(image), "-o", str(out), "--models", str(MODEL_DIR / key),
            "--res", str(resolution if resolution in RESOLUTIONS else RESOLUTIONS[0]), "--seed", str(seed),
            "--require-gpu"]  # ohne Grafikkarte lieber gleich eine Meldung als stundenlanges Rechnen
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(exe.parent), env.get("PATH", "")])
    if not plattform.WINDOWS:
        env["LD_LIBRARY_PATH"] = os.pathsep.join(library_dirs(exe.parent) + [p for p in [env.get("LD_LIBRARY_PATH")] if p])
    if log:
        log("> " + (subprocess.list2cmdline(args) if plattform.WINDOWS else shlex.join(args)) + "\n")
    proc = plattform.popen(args, bound=True, env=env, cwd=str(out.parent), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    _end_with_app(proc)
    state, tail = {"stage": 0, "step": 0, "steps": 0, "eta": None}, []

    def pump():
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace")
            if log:
                log(line)
            tail.append(line.strip())
            del tail[:-12]
            if parse_progress(line, state) and on_progress:
                on_progress(dict(state))

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    while proc.poll() is None:
        if stop.is_set():
            proc.terminate()
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise Cancelled(tr('Abgebrochen.'))
        time.sleep(0.2)
    reader.join(5)
    if stop.is_set():
        raise Cancelled(tr('Abgebrochen.'))
    if proc.returncode != 0 or not out.is_file():
        reason = next((t for t in reversed(tail) if re.search(r"error|fail|require|cannot|out of memory", t, re.I)),
                      tail[-1] if tail else "")
        raise RuntimeError(tr('Das 3D-Modell ließ sich nicht erzeugen (Code {0}): {1}', proc.returncode,
                              reason or tr('Details unter Einstellungen → Server-Log')))
    return out
