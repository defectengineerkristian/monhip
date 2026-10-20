"""Eigener llama.cpp (unabhängig von LM Studio): installierte Versionen in server/ finden, Grafikkarte
erkennen, passende llama-server-Version von github.com/ggml-org/llama.cpp laden."""

import platform
import re
import subprocess
from pathlib import Path

import downloads

SERVER_DIR = Path(__file__).resolve().parent.parent / "server"
RELEASES_URL = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=10"
_FOLDER_RE = re.compile(r"llama-b(\d+)-bin-win-(.+)-(?:x64|arm64)$")  # Ordnername = Name der Zip-Datei
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------- Installierte Server

def _kind_rank(kind: str) -> int:
    for rank, key in enumerate(("cuda", "rocm", "vulkan")):
        if key in kind:
            return rank
    return 4 if "cpu" in kind else 3


def _kind_label(kind: str) -> str:
    name, _, ver = kind.partition("-")
    name = {"cuda": "CUDA", "rocm": "ROCm", "vulkan": "Vulkan", "cpu": "CPU", "sycl": "SYCL",
            "openvino": "OpenVINO"}.get(name, name)
    return f"{name} {ver}" if ver else name


def find_llama_servers() -> list[dict]:
    """Alle server/*/llama-server.exe – CUDA > ROCm > Vulkan > Sonstige > CPU, neueste zuerst."""
    found = []
    for exe in SERVER_DIR.glob("*/llama-server.exe") if SERVER_DIR.is_dir() else []:
        folder = exe.parent.name
        if folder.endswith((".part", ".alt")):
            continue
        m = _FOLDER_RE.match(folder)
        if m:
            build, kind, label = int(m.group(1)), m.group(2), f"b{m.group(1)} · {_kind_label(m.group(2))}"
        else:  # von Hand abgelegt
            build, kind, label = 0, folder.lower(), folder
        found.append(((_kind_rank(kind), -build), {"label": label, "exe": str(exe)}))
    return [s for _, s in sorted(found, key=lambda x: x[0])]


# ---------------------------------------------------------------- Grafikkarte

def _run(args: list[str]) -> str:
    try:
        return subprocess.run(args, capture_output=True, encoding="oem", errors="replace", timeout=20,
                              creationflags=_NO_WINDOW).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def detect_gpu() -> tuple[str, str, tuple[int, int] | None]:
    """(Hersteller „nvidia“/„amd“/„intel“/„“, Name, höchste vom NVIDIA-Treiber unterstützte CUDA-Version)."""
    names = [n.strip() for n in _run(["powershell", "-NoProfile", "-Command",
                                      "(Get-CimInstance Win32_VideoController).Name"]).splitlines() if n.strip()]
    m = re.search(r"CUDA (?:UMD )?Version:\s*(\d+)\.(\d+)", _run(["nvidia-smi"]))  # alte/neue Treiber
    cuda = (int(m.group(1)), int(m.group(2))) if m else None
    # NVIDIA vor AMD vor Intel: die eigene Grafikkarte gewinnt gegen die im Prozessor
    for vendor, keys in (("nvidia", ("nvidia",)), ("amd", ("amd", "radeon")), ("intel", ("intel",))):
        for name in names:
            if any(k in name.lower() for k in keys):
                return vendor, name, cuda
    return "", (names[0] if names else "unbekannt"), cuda


# ---------------------------------------------------------------- Herunterladen

def _pick_assets(release: dict, vendor: str, cuda: tuple[int, int] | None) -> tuple[str, list[dict]]:
    """CUDA (höchste vom Treiber unterstützte, dazu die cudart-Zip), sonst Vulkan, sonst CPU."""
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
    tag = release["tag_name"]
    assets = {a["name"]: a for a in release.get("assets", [])}

    def main(kind):
        return assets.get(f"llama-{tag}-bin-win-{kind}-{arch}.zip")

    if vendor == "nvidia":
        pat = re.compile(rf"llama-{re.escape(tag)}-bin-win-cuda-(\d+)\.(\d+)-{arch}\.zip$")
        versions = sorted((int(m.group(1)), int(m.group(2))) for n in assets if (m := pat.match(n)))
        usable = [v for v in versions if v <= cuda] if cuda else versions[:1]  # ohne nvidia-smi: älteste
        if usable:
            ver = "%d.%d" % usable[-1]
            runtime = assets.get(f"cudart-llama-bin-win-cuda-{ver}-{arch}.zip")
            return f"CUDA {ver}", [main(f"cuda-{ver}")] + ([runtime] if runtime else [])
    if vendor and main("vulkan"):
        return "Vulkan", [main("vulkan")]
    if main("cpu"):
        return "CPU", [main("cpu")]
    return "", []


def plan() -> dict:
    """Neuestes passendes Release (Netzwerk – im Thread aufrufen): tag, kind, gpu, assets, size, target,
    installed. Die fertigen Builds heißen „b12345“ und sind auf GitHub als Vorabversion markiert."""
    vendor, gpu, cuda = detect_gpu()
    for rel in downloads.get_json(RELEASES_URL):
        if rel.get("draft") or not re.fullmatch(r"b\d+", rel.get("tag_name", "")):
            continue
        kind, assets = _pick_assets(rel, vendor, cuda)
        if assets:
            target = SERVER_DIR / assets[0]["name"].removesuffix(".zip")
            return {"tag": rel["tag_name"], "kind": kind, "gpu": gpu, "target": target,
                    "assets": [(a["name"], a["browser_download_url"], a["size"]) for a in assets],
                    "size": sum(a["size"] for a in assets), "installed": (target / "llama-server.exe").is_file()}
    raise RuntimeError("Auf GitHub wurde keine passende llama.cpp-Version für Windows gefunden.")


def install(p: dict, progress, cancel) -> Path:
    """Lädt und entpackt plan() nach server/<Version>/; gibt die llama-server.exe zurück."""
    SERVER_DIR.mkdir(exist_ok=True)
    downloads.clean_leftovers(SERVER_DIR)
    downloads.install_zips(p["assets"], p["target"], "llama-server.exe", progress, cancel, total=p["size"])
    downloads.remove_older(p["target"], _FOLDER_RE)
    return p["target"] / "llama-server.exe"
