"""Bilder erzeugen mit stable-diffusion.cpp (github.com/leejet/stable-diffusion.cpp) – dem Gegenstück zu llama.cpp
für Bilder: Programm von GitHub (server/sd-b<build>-<art>/), Modelldateien von Hugging Face (modelle/bild/<Modell>/).
sd-server lädt das Modell einmal und hält es; Aufträge laufen über seine eigene Schnittstelle /sdcpp/v1 (abschicken,
Fortschritt samt kleinem Vorschaubild abfragen, abbrechen).

Linux: Fertige Programme gibt es für Ubuntu (Prozessor und Vulkan – Vulkan läuft auch auf NVIDIA mit dem proprietären
Treiber; ein CUDA-Paket gibt es dort nicht). Ein sd-server aus dem PATH (Paketverwaltung, selbst gebaut) geht ebenso."""

from i18n import tr

import base64
import json
import os
import platform
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import downloads
import engines
import llamacpp
import plattform
import rocm_packages
import rocm_runtime
from backend import ManagedServer, _free_port, _local

SERVER_DIR = llamacpp.SERVER_DIR
MODEL_DIR = plattform.DATA_DIR / "modelle" / "bild"
RELEASES_URL = "https://api.github.com/repos/leejet/stable-diffusion.cpp/releases?per_page=10"
HF_URL = "https://huggingface.co/{repo}/resolve/main/{path}"
SERVER_EXE = plattform.exe("sd-server")
_FOLDER_RE = re.compile(r"sd-b(\d+)-(.+)$")          # Ordner in server/: sd-b1060-cuda12, sd-b1060-vulkan …
_TAG_RE = re.compile(r"master-(\d+)-[0-9a-f]+$")      # Releases heißen „master-1060-0b3b98d“
COMPUTE_MIB = 3500  # Grafikspeicher fürs Rechnen eines Bildes mit 1024 × 1024 (zusätzlich zu den Modelldateien)

# Bildmodelle. Jedes besteht aus mehreren Dateien – Bildmodell (diffusion-model), Textverständnis (llm), VAE und
# bei Qwen-Image zum Bearbeiten das Bildverständnis des Textmodells (llm_vision): Rolle (= Startoption von sd-server)
# → (Hugging-Face-Repository, Pfad darin). Fehlende Dateien lädt Monhip vor dem Laden nach (plan/install).
# "gb" = Download in GB, "align" = Bildseiten ein Vielfaches davon, "sigmas" = fester Zeitplan (Turbo-Modelle).
# Bearbeiten (ref_images) können alle: FLUX.2 nimmt das Bild direkt, Qwen-Image auch über sein Bildverständnis.
_FLUX2_VAE = ("vae", "Comfy-Org/Flux-2-Klein-4B", "split_files/vae/flux2-vae.safetensors")
_QWEN21 = "Comfy-Org/Qwen-Image-2.1"
_QWEN3VL = "Qwen/Qwen3-VL-8B-Instruct-GGUF"
MODELS = {  # das erste ist der Standard (DEFAULT_MODEL) und steht oben in der Auswahl
    "qwen-image-2.1-turbo": {
        "label": tr('Qwen-Image 2.1 Turbo – stark bei Text im Bild und beim Bearbeiten (14 GB, ab 16 GB '
                    'Grafikspeicher)'),
        "name": "Qwen-Image 2.1 Turbo",
        "folder": "Qwen-Image-2.1",
        "files": [("diffusion-model", _QWEN21, "diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors"),
                  ("llm", _QWEN3VL, "Qwen3VL-8B-Instruct-Q4_K_M.gguf"),
                  ("llm_vision", _QWEN3VL, "mmproj-Qwen3VL-8B-Instruct-F16.gguf"),
                  ("vae", _QWEN21, "vae/qwen_image_2.1_vae_bf16.safetensors")],
        "steps": 8, "cfg": 1.0, "sampler": "euler", "gb": 14.1, "align": 32,
        # Zeitplan des Turbo-Modells (in sd.cpp: --sigmas qwen-image-2.1-turbo) – bestimmt die 8 Schritte
        "sigmas": [1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0.0],
        # Ohne CUDA (Vulkan für AMD/Intel, ROCm, CPU, Linux-Builds) dieselben Gewichte als GGUF Q8_0: den int8-
        # Rechenweg (convrot) gibt es ausgereift nur unter CUDA – auf AMD-Karten mit Vulkan kamen Bildfetzen heraus
        "portable": {"diffusion-model": ("AtomicChat/Qwen-Image-2.1-Turbo-GGUF", "Qwen-Image-2.1-Turbo-Q8_0.gguf")},
        "license": tr('Qwen Research License – nur für nicht-kommerzielle Zwecke.'),
    },
    "flux2-klein-4b-q8": {
        "label": tr('FLUX.2 [klein] 4B – beste Qualität (8,9 GB, ab 12 GB Grafikspeicher)'),
        "name": "FLUX.2 [klein] 4B",
        "folder": "FLUX.2-klein-4B",
        "files": [("diffusion-model", "leejet/FLUX.2-klein-4B-GGUF", "flux-2-klein-4b-Q8_0.gguf"),
                  ("llm", "unsloth/Qwen3-4B-GGUF", "Qwen3-4B-Q8_0.gguf"), _FLUX2_VAE],
        "steps": 4, "cfg": 1.0, "sampler": "euler", "gb": 8.9, "align": 16,
        "license": tr('Apache 2.0 – die Bilder dürfen auch kommerziell genutzt werden.'),
    },
    "flux2-klein-4b-q4": {
        "label": tr('FLUX.2 [klein] 4B – kleiner (5,3 GB, für Grafikkarten mit 6–8 GB)'),
        "name": "FLUX.2 [klein] 4B (Q4)",
        "folder": "FLUX.2-klein-4B",
        "files": [("diffusion-model", "leejet/FLUX.2-klein-4B-GGUF", "flux-2-klein-4b-Q4_0.gguf"),
                  ("llm", "unsloth/Qwen3-4B-GGUF", "Qwen3-4B-Q4_K_M.gguf"), _FLUX2_VAE],
        "steps": 4, "cfg": 1.0, "sampler": "euler", "gb": 5.3, "align": 16,
        "license": tr('Apache 2.0 – die Bilder dürfen auch kommerziell genutzt werden.'),
    },
}
DEFAULT_MODEL = "qwen-image-2.1-turbo"  # bietet auch der Windows-Installer an (ImageModel.cs)
EDIT_AREA = 1024 * 1024  # Bearbeiten: Ergebnis mit etwa so vielen Pixeln, Seitenverhältnis wie die Vorlage
QWEN_VULKAN_COMPAT_ENV = ("GGML_VK_DISABLE_FUSION", "GGML_VK_DISABLE_COOPMAT", "GGML_VK_DISABLE_COOPMAT2")


class Cancelled(RuntimeError):
    """Der Auftrag wurde abgebrochen („Stopp“)."""


# ---------------------------------------------------------------- Installiert?

def model_key(key: str | None) -> str:
    """Gültiger Schlüssel: der gewählte, sonst der Standard – außer der fehlt noch und ein anderes Bildmodell ist
    schon vollständig da (z. B. FLUX.2 aus v1.5.0, ohne dass je eines gewählt wurde): dann dieses."""
    if key in MODELS:
        return key
    if not _present(DEFAULT_MODEL):
        return next((k for k in MODELS if _present(k)), DEFAULT_MODEL)
    return DEFAULT_MODEL


def _present(key: str) -> bool:
    return _complete(MODELS[key], _files(key))


def _complete(m: dict, files) -> bool:
    return all((MODEL_DIR / m["folder"] / Path(path).name).is_file() for _, _, path in files)


def _files(key: str, kind: str | None = None) -> list[tuple[str, str, str]]:
    """(Rolle, Repository, Pfad) der Dateien eines Bildmodells – passend zur Engine (kind, sonst die installierte). Das
    int8-Format von Qwen-Image (convrot) rechnet ausgereift nur mit CUDA; mit Vulkan kamen auf AMD-Karten Bildfetzen
    heraus. Ohne CUDA daher die Ersatzdateien aus "portable" (GGUF) – mit ROCm das int8-Modell, wenn es schon da ist."""
    m = MODELS[key]
    alt = m.get("portable")
    if not alt:
        return m["files"]
    kind = engine_kind() if kind is None else kind
    if kind.startswith("cuda") or (kind == "rocm" and _complete(m, m["files"])):
        return m["files"]
    return [(role, *alt[role]) if role in alt else (role, repo, path) for role, repo, path in m["files"]]


def engine_kind() -> str:
    """Art der installierten Bild-Engine („cuda12“, „rocm“, „vulkan“, „cpu“); „“ = keine oder unbekannt (z. B.
    sd-server aus dem PATH)."""
    exe = find_server()
    m = _FOLDER_RE.match(exe.parent.name) if exe else None
    return m.group(2) if m else ""


def model_files(key: str, kind: str | None = None) -> list[tuple[str, Path, str]]:
    """[(Rolle, Zieldatei, URL)] eines Bildmodells – für die installierte Engine bzw. die Art kind."""
    key = model_key(key)
    folder = MODEL_DIR / MODELS[key]["folder"]
    return [(role, folder / Path(path).name, HF_URL.format(repo=repo, path=path))
            for role, repo, path in _files(key, kind)]


def model_ready(key: str) -> bool:
    return all(dest.is_file() for _, dest, _ in model_files(key))


def find_server(kind: str | None = None) -> Path | None:
    """sd-server(.exe) – CUDA vor ROCm vor Vulkan vor CPU, neueste zuerst (kind: nur diese Art); ROCm unter Windows nur
    mit vollständiger Laufzeit. Unter Linux sonst der aus dem PATH."""
    return engines.find_program(SERVER_DIR, _FOLDER_RE, SERVER_EXE, kind=kind, usable=_usable)


def _usable(exe: Path, kind: str) -> bool:
    return not (plattform.WINDOWS and kind == "rocm" and rocm_runtime.missing(exe))


def ready(key: str) -> bool:
    return bool(find_server() and model_ready(key))


_kind_label = engines.kind_label


def describe(key: str) -> str:
    """Kurzer Stand für die Einstellungen: Programm und Modell."""
    exe = find_server()
    m = _FOLDER_RE.match(exe.parent.name) if exe else None
    if not exe:
        program = tr('Bild-Engine noch nicht installiert')
    elif m:
        program = f"stable-diffusion.cpp b{m.group(1)} ({_kind_label(m.group(2))})"
    else:
        program = f"sd-server ({exe})"
    model = MODELS[model_key(key)]["name"]
    return program + (tr(' · Modell {0}', model) if model_ready(key) else tr(' · Modell {0} fehlt noch', model))


def size_on_disk(key: str) -> int:
    return sum(dest.stat().st_size for _, dest, _ in model_files(key) if dest.is_file())


def missing_gb(key: str) -> float:
    """Ungefähr noch herunterzuladen (GB) – ohne Netz, aus dem Katalog: der Anteil der fehlenden Dateien."""
    files = model_files(key)
    gone = sum(1 for _, dest, _ in files if not dest.is_file())
    return MODELS[model_key(key)]["gb"] * gone / len(files) if gone else 0.0


def edit_size(width: int, height: int, key: str | None = None, area: int = EDIT_AREA) -> tuple[int, int]:
    """Größe des Ergebnisses beim Bearbeiten: Seitenverhältnis der Vorlage, etwa area Pixel, beide Seiten ein
    Vielfaches von align des Modells (256 bis 2048)."""
    align = MODELS[model_key(key)]["align"]
    f = (area / max(1, width * height)) ** 0.5
    return tuple(min(2048, max(256, round(side * f / align) * align)) for side in (width, height))


# ---------------------------------------------------------------- Herunterladen

def _rocm_available(version: str) -> bool:
    if rocm_runtime.available(version):
        return True
    return any(rocm_runtime.version(exe) == version and not rocm_runtime.missing(exe)
               for exe in SERVER_DIR.glob(f"sd-*-rocm/{SERVER_EXE}"))


def _pick(release: dict, vendor: str, cuda: tuple[int, int] | None,
          linux: bool = not plattform.WINDOWS, gpu: str = "") -> tuple[str, list[dict]]:
    """Windows: NVIDIA mit Treiber für CUDA 12 → CUDA (dazu die Laufzeit cudart), sonst mit Grafikkarte Vulkan, sonst
    Prozessor. RX 9070 XT unter Windows: ROCm; fehlende Laufzeitpakete werden im Download-Plan ergänzt.
    Linux: mit Grafikkarte Vulkan, sonst Prozessor. Die Programme gibt es nur für x64."""
    if platform.machine().lower() not in ("amd64", "x86_64", "x64"):
        return "", []
    names = sorted(a["name"] for a in release.get("assets", []))
    assets = {a["name"]: a for a in release.get("assets", [])}

    def find(pattern: str) -> dict | None:
        return next((assets[n] for n in names if re.fullmatch(pattern, n)), None)

    if linux:
        vulkan = find(r"sd-master-[0-9a-f]+-bin-Linux-Ubuntu-[\d.]+-x86_64-vulkan\.zip")
        cpu = find(r"sd-master-[0-9a-f]+-bin-Linux-Ubuntu-[\d.]+-x86_64\.zip")
    else:
        if vendor == "nvidia" and cuda and cuda >= (12, 0):
            main, runtime = find(r"sd-master-[0-9a-f]+-bin-win-cuda12-x64\.zip"), find(r"cudart-sd-bin-win-cu12-x64\.zip")
            if main and runtime:
                return "cuda12", [main, runtime]
        if vendor == "amd" and re.search(r"\bRX\s*9070\s*XT\b", gpu, re.I):
            rocm = [(tuple(int(v) for v in match.group(1).split(".")), assets[name]) for name in names
                    if (match := re.fullmatch(r"sd-master-[0-9a-f]+-bin-win-rocm-(\d+\.\d+\.\d+)-x64\.zip", name))]
            if rocm:
                return "rocm", [max(rocm, key=lambda item: item[0])[1]]
        vulkan = find(r"sd-master-[0-9a-f]+-bin-win-vulkan-x64\.zip")
        cpu = find(r"sd-master-[0-9a-f]+-bin-win-cpu-x64\.zip")
    if vendor and vulkan:
        return "vulkan", [vulkan]
    return ("cpu", [cpu]) if cpu else ("", [])


def plan(key: str = DEFAULT_MODEL, update: bool = True) -> dict:
    """Was fehlt (Netzwerk – im Thread aufrufen): program = [(name, url, größe)] der Programm-Zips (leer, wenn das
    neueste schon da ist), weights = [(name, url, größe, ziel)] der fehlenden Modelldateien, size = alles zusammen.
    update=False: eine vorhandene Bild-Engine nicht aktualisieren, nur Fehlendes (beim Laden eines Modells)."""
    have = find_server()
    if not update and have:
        weights = [(dest.name, url, downloads.head_size(url), dest) for _, dest, url in model_files(key)
                   if not dest.is_file()]
        return {"tag": "", "kind": "", "gpu": "", "target": None, "program": [], "weights": weights,
                "model": model_key(key), "size": sum(x[2] for x in weights)}
    vendor, gpu, cuda = llamacpp.detect_gpu()
    system = None if plattform.WINDOWS else plattform.which("sd-server")
    tag, kind, target, program, rocm_version = "", "", None, [], None
    try:
        releases = downloads.get_json(RELEASES_URL)
    except (OSError, ValueError):
        if not system:
            raise
        releases = []
    for rel in releases:
        m = _TAG_RE.match(rel.get("tag_name", ""))
        if rel.get("draft") or not m:
            continue
        kind, assets = _pick(rel, vendor, cuda, gpu=gpu)
        if assets:
            tag, target = rel["tag_name"], SERVER_DIR / f"sd-b{m.group(1)}-{kind}"
            if kind == "rocm":
                rocm_version = re.search(r"-rocm-(\d+\.\d+\.\d+)-", assets[0]["name"]).group(1)
            if not (target / SERVER_EXE).is_file():
                program = [(a["name"], a["browser_download_url"], a["size"], downloads.asset_sha256(a)) for a in assets]
            break
    else:
        if not system:
            raise RuntimeError(tr('Auf GitHub wurde keine passende Version von stable-diffusion.cpp gefunden.'))
    weights = [(dest.name, url, downloads.head_size(url), dest) for _, dest, url in model_files(key, kind)
               if not dest.is_file()]
    runtime = rocm_packages.plan(rocm_version) if rocm_version and not _rocm_available(rocm_version) else None
    return {"tag": tag, "kind": _kind_label(kind) if kind else "", "gpu": gpu, "target": target, "program": program,
            "weights": weights, "model": model_key(key), "rocm_version": rocm_version,
            "runtime": runtime,
            "size": sum(x[2] for x in program) + sum(x[2] for x in weights) + (runtime["size"] if runtime else 0)}


def install(p: dict, progress, cancel):
    """Lädt, was plan() aufzählt: bei ROCm erst die passende AMD-Laufzeit, dann das Programm nach
    server/sd-b<build>-<art>/ (ältere derselben Art fliegen raus) und die Modelldateien."""
    done = rocm_packages.install(p["runtime"], lambda d, _n: progress(d, p["size"]), cancel) if p.get("runtime") else 0
    engines.install(p, SERVER_DIR, SERVER_EXE, _FOLDER_RE, progress, cancel, done=done, check=_check_rocm)


def _check_rocm(p: dict):
    """Nach dem Entpacken, bevor ältere Engines weichen: ROCm-Version vermerken und die Laufzeit probeweise laden."""
    if not p.get("rocm_version"):
        return
    (p["target"] / rocm_runtime.VERSION_FILE).write_text(json.dumps({"version": p["rocm_version"]}), encoding="utf-8")
    if plattform.WINDOWS:
        error = rocm_runtime.probe(p["target"] / SERVER_EXE, os.environ)
        if error:
            raise RuntimeError(tr('Die installierte ROCm-Laufzeit ließ sich nicht laden ({0}). Bitte den '
                                  'AMD-Grafiktreiber und die Microsoft-Visual-C++-x64-Laufzeit prüfen.', error))


# ---------------------------------------------------------------- Grafikspeicher

def free_vram_mib() -> int | None:
    """Freier Grafikspeicher der ersten NVIDIA-Karte (nvidia-smi); ohne NVIDIA unbekannt (None)."""
    out = llamacpp._run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"])
    m = re.search(r"\d+", out)
    return int(m.group()) if m else None


def need_vram_mib(key: str) -> int:
    """So viel Grafikspeicher braucht das Bildmodell, damit es ganz auf die Grafikkarte passt."""
    files = sum(dest.stat().st_size for _, dest, _ in model_files(key) if dest.is_file()) // 2 ** 20
    return (files or 9000) + COMPUTE_MIB


# ---------------------------------------------------------------- Server

def _request(url: str, data: dict | None = None, timeout: float = 30) -> dict:
    """JSON holen bzw. schicken. HTTP-Fehler mit der Meldung des Servers als RuntimeError."""
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, method="POST" if data is not None else "GET",
                                 headers={"Content-Type": "application/json"})
    try:  # nie über einen Proxy aus der Umgebung: der bekäme Beschreibungen und Bilder, und 127.0.0.1 erreichte er nicht
        with _local.open(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(text).get("error")
            text = (err.get("message") if isinstance(err, dict) else err) or text
        except (ValueError, AttributeError):
            pass
        raise RuntimeError(f"HTTP {e.code}: {text[:300]}") from None


def compatibility_mode(value) -> str:
    return value if value in ("auto", "normal", "compatible") else "auto"


def _use_compatibility(key: str, exe: Path, mode: str) -> bool:
    """Bestätigter Workaround für Farbrauschen mit Qwen, b1068/Vulkan und RX 9070 XT auf Windows.
    Nur diese Kombination automatisch umstellen; andere Rechner können den Modus gezielt wählen.
    Welcher der abgeschalteten Pfade den Fehler auslöst, ist noch nicht einzeln eingegrenzt."""
    if key != "qwen-image-2.1-turbo" or mode == "normal":
        return False
    if mode == "compatible":
        return True
    if not plattform.WINDOWS:
        return False
    build = _FOLDER_RE.fullmatch(exe.parent.name)
    if not build or build.groups() != ("1068", "vulkan"):
        return False
    vendor, gpu, _ = llamacpp.detect_gpu()
    return vendor == "amd" and bool(re.search(r"\bRX\s*9070\s*XT\b", gpu, re.I))


class ImageServer(ManagedServer):
    """sd-server: lädt das Bildmodell einmal und hält es bis stop() – wie backend.LlamaServer für Sprachmodelle.
    get_compatibility() liefert die Einstellung „Qwen-Image: Rechenmodus“ (auto, normal, compatible)."""

    def __init__(self, log_cb, get_compatibility=None):
        super().__init__(log_cb)
        self.model: str | None = None   # Schlüssel in MODELS, sobald fertig geladen
        self._get_compatibility = get_compatibility or (lambda: "auto")
        self._compatibility_mode = "auto"
        self.compatibility_active = False
        self._reload_required = False

    def _forget(self):
        self.model, self.compatibility_active = None, False

    def ready_for(self, key: str) -> bool:
        key = model_key(key)
        return (self.is_running() and self.model == key and not self._reload_required and
                (key != "qwen-image-2.1-turbo" or self._compatibility_mode ==
                 compatibility_mode(self._get_compatibility())))

    def require_reload(self):
        """Nach einer Engine-Installation erst den nächsten Auftrag mit dem neuen Programm starten."""
        self._reload_required = True

    def start(self, key: str, cancel: threading.Event, timeout: float = 900):
        """Startet sd-server mit dem Modell und blockiert, bis es geladen ist (im Thread aufrufen)."""
        key = model_key(key)
        mode = compatibility_mode(self._get_compatibility())
        # „Kompatibel“ bleibt als bestätigter Vulkan-Rückweg verfügbar, auch nach einer ROCm-Installation.
        exe = (find_server("vulkan") if key == "qwen-image-2.1-turbo" and mode == "compatible" else None) or find_server()
        if not exe or not model_ready(key):
            raise RuntimeError(tr('Bild-Engine oder Bildmodell fehlt – bitte unter Einstellungen → Bilder '
                                  'herunterladen.'))
        m = MODELS[key]
        runtime_problem = None
        is_rocm = exe.parent.name.endswith("-rocm") and plattform.WINDOWS
        if is_rocm:
            runtime_problem = rocm_runtime.probe(exe, os.environ)
            if runtime_problem:
                fallback = find_server("vulkan")
                if not fallback:
                    raise RuntimeError(tr('Die ROCm-Laufzeit ließ sich nicht laden ({0}). Bitte die vollständige '
                                          'passende AMD-ROCm-Laufzeit installieren oder unter Einstellungen → '
                                          'Bilder die Bild-Engine aktualisieren.', runtime_problem))
                exe, is_rocm = fallback, False
        elif plattform.WINDOWS and exe.parent.name.endswith("-vulkan"):
            for native in SERVER_DIR.glob(f"sd-*-rocm/{SERVER_EXE}"):
                absent = rocm_runtime.missing(native)
                if absent:
                    runtime_problem = ", ".join(absent)
                    break
        compatible = _use_compatibility(key, exe, mode)
        if runtime_problem:
            self.log_cb(tr('ROCm-Laufzeit unvollständig ({0}). Verwende die vorhandene Vulkan-Engine.\n', runtime_problem))
            if key == "qwen-image-2.1-turbo":
                vendor, gpu, _ = llamacpp.detect_gpu()
                compatible = compatible or (vendor == "amd" and bool(re.search(r"\bRX\s*9070\s*XT\b", gpu, re.I)))
        with self._start_lock:
            self.stop()
            if cancel.is_set():
                raise Cancelled(tr('Laden abgebrochen.'))
            port = _free_port()
            args = [str(exe), "--listen-ip", "127.0.0.1", "--listen-port", str(port)]
            for role, dest, _ in model_files(key):
                args += [f"--{role}", str(dest)]
            # Standardwerte für Aufträge; die Verteilung auf Grafikkarte und Arbeitsspeicher macht sd-server selbst
            # nach dem freien Speicher („--auto-fit“ ist an). --eager-load: alle Gewichte schon beim Start laden – sonst
            # „rechnet“ das erste Bild 20 s länger und das Laden zeigt keinen eigenen Stand
            args += ["--cfg-scale", str(m["cfg"]), "--steps", str(m["steps"]), "--sampling-method", m["sampler"],
                     "--eager-load"]
            if m.get("sigmas"):
                args += ["--sigmas", ",".join(str(sigma) for sigma in m["sigmas"])]
            env = {}
            if compatible:
                # Exakt der lokal bestätigte Vergleichspfad 03: Entrauschen weiterhin auf der GPU,
                # Decoder auf CPU, ohne die betroffenen Vulkan-Optimierungen und den Prefix-Cache.
                args += ["--backend", "vae=cpu", "--flash-attn", "off", "--conv-direct", "off",
                         "--model-args", "qwen_image_2_1_prefix_cache=false"]
                env = {name: "1" for name in QWEN_VULKAN_COMPAT_ENV}
                self.log_cb(tr('Qwen-Image: Kompatibilitätsmodus aktiv. Die Berechnung dauert länger.\n'))
            proc = self._spawn(args, exe, env, adjust=(lambda e: rocm_runtime.environment(exe, e)) if is_rocm else None)
            with self._lock:
                self.proc, self.port, self.model = proc, port, None
                self._compatibility_mode, self.compatibility_active = mode, compatible
                self._reload_required = False
        self._watch(proc, tr('Hinweis: sd-server konnte nicht an das Programm gebunden werden – nach einem Absturz '
                             'läuft er evtl. weiter (Task-Manager: sd-server).\n'))

        url = f"http://127.0.0.1:{port}/sdcpp/v1/models/status"
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cancel.is_set() or self.proc is not proc:
                self.stop(proc)
                raise Cancelled(tr('Laden abgebrochen.'))
            if proc.poll() is not None:
                raise RuntimeError(tr('Die Bild-Engine hat sich beendet (Code {0}) – Details unter Einstellungen → '
                                      'Server-Log.', proc.returncode))
            try:
                status = _request(url, timeout=3)
            except (OSError, RuntimeError, ValueError):
                status = {}
            if status.get("state") == "ready":
                with self._lock:
                    if self.proc is proc:
                        self.model = key
                        return
            if status.get("state") == "error":
                self.stop(proc)
                raise RuntimeError(tr('Das Bildmodell ließ sich nicht laden: {0}', status.get("error") or "?"))
            time.sleep(0.5)
        self.stop(proc)
        raise RuntimeError(tr('Zeitüberschreitung beim Laden des Bildmodells.'))

    def generate(self, prompt: str, width: int, height: int, count: int, seed: int, stop: threading.Event,
                 on_progress=None, poll: float = 0.25, refs: list[bytes] | None = None) -> list[bytes]:
        """Ein Auftrag mit count Bildern → PNG-Dateien als Bytes. on_progress(erledigt, gesamt, vorschau) mit den
        Schritten über alle Bilder und – wenn es ein neues gibt – einem kleinen Vorschaubild (PNG-Bytes, sonst None).
        refs = Vorlagen zum Bearbeiten (Bilddateien als Bytes), prompt sagt dann, was sich ändern soll.
        stop bricht ab (Cancelled)."""
        m = MODELS[self.model or DEFAULT_MODEL]
        base = self.base_url
        sample = {"sample_steps": m["steps"], "sample_method": m["sampler"], "guidance": {"txt_cfg": m["cfg"]}}
        if m.get("sigmas"):
            sample["custom_sigmas"] = m["sigmas"]
        body = {"prompt": prompt, "negative_prompt": "", "width": width, "height": height, "seed": seed,
                "batch_count": count, "embed_image_metadata": True, "output_format": "png",
                "preview": "proj", "preview_interval": 1, "sample_params": sample}
        if refs:
            body["ref_images"] = [base64.b64encode(r).decode("ascii") for r in refs]
        job = _request(base + "/sdcpp/v1/img_gen", body)
        jid = job.get("id")
        if not jid:
            raise RuntimeError(tr('Die Bild-Engine hat den Auftrag nicht angenommen.'))
        total = max(1, count * m["steps"])
        seen, cancel_sent = None, False
        while True:
            if stop.is_set() and not cancel_sent:
                try:
                    _request(f"{base}/sdcpp/v1/jobs/{jid}/cancel", {})
                except (OSError, RuntimeError):
                    pass
                cancel_sent = True
            if not self.is_running():
                raise RuntimeError(tr('Die Bild-Engine wurde beendet.'))
            st = _request(f"{base}/sdcpp/v1/jobs/{jid}")
            status = st.get("status")
            if status == "completed":
                images = (st.get("result") or {}).get("images") or []
                if not images:
                    raise RuntimeError(tr('Die Bild-Engine hat kein Bild geliefert.'))
                if on_progress:
                    on_progress(total, total, None)
                return [base64.b64decode(img["b64_json"]) for img in sorted(images, key=lambda i: i.get("index", 0))]
            if status == "cancelled" or (cancel_sent and status == "failed"):
                raise Cancelled(tr('Abgebrochen.'))
            if status == "failed":
                err = st.get("error") or {}
                raise RuntimeError(tr('Bild konnte nicht erzeugt werden: {0}', err.get("message") or "?"))
            pv = st.get("preview") or {}
            if on_progress and pv.get("step"):
                done = (max(1, pv.get("pass") or 1) - 1) * m["steps"] + min(pv["step"], pv.get("total_steps") or m["steps"])
                key = (pv.get("pass"), pv.get("step"))
                image = base64.b64decode(pv["b64_json"]) if key != seen and pv.get("b64_json") else None
                seen = key
                on_progress(min(done, total), total, image)
            time.sleep(poll)
