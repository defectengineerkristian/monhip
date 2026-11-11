"""Gemeinsam für die Programme, die Monhip selbst nach server/ lädt (llama.cpp, stable-diffusion.cpp, trellis.cpp,
whisper.cpp): Art einordnen und benennen (CUDA, ROCm, Vulkan, CPU …), die beste installierte Fassung finden und
Programm samt Modelldateien herunterladen. Was je Programm anders ist (Releases, Dateinamen, Modelle), bleibt in
dessen Modul."""

import re
from pathlib import Path

import downloads
import plattform

_LABELS = {"cuda": "CUDA", "rocm": "ROCm", "vulkan": "Vulkan", "cpu": "CPU", "sycl": "SYCL", "openvino": "OpenVINO"}


def kind_rank(kind: str) -> int:
    """Reihenfolge der Arten: CUDA vor ROCm vor Vulkan vor Sonstigen vor CPU."""
    for rank, key in enumerate(("cuda", "rocm", "vulkan")):
        if key in kind:
            return rank
    return 4 if "cpu" in kind else 3


def kind_label(kind: str) -> str:
    """„cuda12“ → „CUDA 12“, „cuda-13.4“ → „CUDA 13.4“, „vulkan“ → „Vulkan“, „cpu“ → „CPU“."""
    m = re.match(r"([a-z]+)-?(.*)$", kind)
    name, version = (m.group(1), m.group(2)) if m else (kind, "")
    return f"{_LABELS.get(name, name)} {version}".strip()


def newest_build(m: re.Match) -> int:
    """Sortierschlüssel für Ordner mit Build-Nummer in Gruppe 1 („sd-b1060-cuda12“): neueste zuerst."""
    return -int(m.group(1))


def find_program(base: Path, folder_re: re.Pattern, exe: str, order=newest_build, kind: str | None = None,
                 usable=None) -> Path | None:
    """exe in base/<Ordner>/ – die beste Art (kind_rank, Art in Gruppe 2 von folder_re), darin die neueste Fassung
    (order). Ordner, die gerade entstehen oder weggeräumt werden (.part, .alt), zählen nicht; kind: nur diese Art;
    usable(exe, art) → False überspringt eine Fassung (z. B. ohne ihre Laufzeit). Ohne Treffer unter Linux das
    Programm aus dem PATH (Paketverwaltung, selbst gebaut) – nicht, wenn eine bestimmte Art gesucht ist."""
    found = []
    for path in base.glob(f"*/{exe}") if base.is_dir() else []:
        folder = path.parent.name
        m = folder_re.match(folder)
        if not m or folder.endswith((".part", ".alt")) or kind not in (None, m.group(2)):
            continue
        if usable is None or usable(path, m.group(2)):
            found.append((kind_rank(m.group(2)), order(m), str(path)))
    if found:
        return Path(min(found)[2])
    system = None if plattform.WINDOWS or kind else plattform.which(Path(exe).stem)
    return Path(system) if system else None


def install(p: dict, base: Path, exe: str, folder_re: re.Pattern, progress, cancel, done: int = 0,
            check=None) -> int:
    """Lädt, was ein plan() aufzählt: die Programm-Zips p["program"] nach p["target"] (ältere derselben Art fliegen
    raus), dann die Modelldateien p["weights"] = [(name, url, größe, ziel)] einzeln über .part-Dateien (nach einem
    Verbindungsabbruch geht es dort weiter). done = schon geladene Bytes (Fortschritt über alles); check(p) prüft das
    entpackte Programm, bevor ältere weichen (Fehler: abbrechen, die alte Fassung bleibt). → bis dahin geladene Bytes."""
    total = p["size"]
    if p.get("program"):
        base.mkdir(parents=True, exist_ok=True)
        downloads.clean_leftovers(base)
        done = downloads.install_zips(p["program"], p["target"], exe, progress, cancel, done=done, total=total)
    if check:
        check(p)
    if p.get("program"):
        downloads.remove_older(p["target"], folder_re)
    for _name, url, _size, dest in p.get("weights") or []:
        done = downloads.fetch_one(url, dest, progress, cancel, done, total)
    return done
