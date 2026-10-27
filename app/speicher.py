"""Speicherplatz analysieren (Werkzeug speicher_analysieren): Was belegt in einem Ordner bzw. auf einem Laufwerk
Platz? Liest nur Namen und Größen – Inhalte nur für die Suche nach doppelten Dateien (Prüfsummen)."""

import hashlib
import heapq
import os
import shutil
import string
import time
from pathlib import Path

TIME_LIMIT = 60            # Sekunden fürs Durchsuchen, danach Ergebnis als unvollständig markiert
DUP_TIME_LIMIT = 60
DUP_MIN = 1024 * 1024      # doppelte Dateien erst ab 1 MB (kleine lohnen nicht)
TOP = 15
KINDS = {
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".mpg", ".mpeg"},
    "Bilder": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".heic", ".webp", ".tif", ".tiff", ".raw", ".cr2", ".nef",
               ".psd"},
    "Musik & Audio": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma"},
    "Archive": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Installer & Abbilder": {".exe", ".msi", ".msix", ".iso", ".img", ".appx"},
    "Dokumente": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".txt", ".csv", ".epub"},
    "KI-Modelle": {".gguf", ".safetensors", ".bin", ".pt", ".onnx", ".ckpt"},
}
_KIND = {ext: kind for kind, exts in KINDS.items() for ext in exts}


def size_text(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return ""


def drives() -> list[str]:
    """Belegung aller Laufwerke (Windows: A:–Z:)."""
    roots = [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")] if os.name == "nt" else ["/"]
    out = []
    for r in roots:
        try:
            u = shutil.disk_usage(r)
        except OSError:
            continue
        out.append(f"{r}  {size_text(u.used)} von {size_text(u.total)} belegt ({u.used * 100 // max(u.total, 1)} %), "
                   f"frei: {size_text(u.free)}")
    return out


def _is_link(entry: os.DirEntry) -> bool:
    try:  # Verknüpfungen und Windows-Junctions nicht verfolgen (sonst doppelt gezählt oder endlos)
        return entry.is_symlink() or bool(getattr(entry, "is_junction", lambda: False)())
    except OSError:
        return True


def analyse(root: Path, duplicates: bool = False) -> str:
    root = Path(root)
    start = time.monotonic()
    per_child: dict[str, int] = {}
    kinds: dict[str, int] = {}
    largest: list[tuple[int, str]] = []
    by_size: dict[int, list[str]] = {}
    files = total = skipped = 0
    complete = True
    top_files = 0
    stack: list[tuple[str, str]] = [(str(root), "")]  # (Ordner, oberster Unterordner von root)
    while stack:
        if time.monotonic() - start > TIME_LIMIT:
            complete = False
            break
        folder, child = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except OSError:
            skipped += 1
            continue
        for e in entries:
            if _is_link(e):
                continue
            top = child or e.name
            try:
                if e.is_dir(follow_symlinks=False):
                    stack.append((e.path, top))
                    per_child.setdefault(top, 0)
                    continue
                size = e.stat(follow_symlinks=False).st_size
            except OSError:
                skipped += 1
                continue
            files += 1
            total += size
            if child:
                per_child[top] = per_child.get(top, 0) + size
            else:
                top_files += size
            kind = _KIND.get(os.path.splitext(e.name)[1].lower(), "Sonstiges")
            kinds[kind] = kinds.get(kind, 0) + size
            if len(largest) < TOP:
                heapq.heappush(largest, (size, e.path))
            elif size > largest[0][0]:
                heapq.heapreplace(largest, (size, e.path))
            if duplicates and size >= DUP_MIN:
                by_size.setdefault(size, []).append(e.path)

    lines = [f"Speicher in {root}: {size_text(total)} in {files} Dateien"
             + ("" if complete else f" – nach {TIME_LIMIT} s abgebrochen, Ergebnis UNVOLLSTÄNDIG (für Genaueres einen "
                                    "Unterordner analysieren)")]
    if skipped:
        lines.append(f"({skipped} Ordner bzw. Dateien ohne Zugriff übersprungen)")
    disks = drives()
    if disks:
        lines += ["", "Laufwerke:"] + [f"  {d}" for d in disks]
    if per_child:
        lines += ["", "Größte Unterordner:"]
        for name, size in sorted(per_child.items(), key=lambda kv: -kv[1])[:TOP]:
            lines.append(f"  {size_text(size):>9}  {name}{os.sep}")
        if top_files:
            lines.append(f"  {size_text(top_files):>9}  (Dateien direkt in {root.name or root})")
    if largest:
        lines += ["", "Größte Dateien:"]
        for size, path in sorted(largest, reverse=True):
            lines.append(f"  {size_text(size):>9}  {path}")
    if kinds:
        lines += ["", "Nach Art:"]
        for kind, size in sorted(kinds.items(), key=lambda kv: -kv[1])[:8]:
            lines.append(f"  {size_text(size):>9}  {kind}")
    if duplicates:
        lines += [""] + _duplicates(by_size)
    lines += ["", "Hinweis: Nur Namen und Größen gelesen, nichts gelöscht. Löschen nur nach Rückfrage beim Nutzer."]
    return "\n".join(lines)


def _digest(path: str, limit: int | None) -> str | None:
    h = hashlib.sha1()
    try:
        with open(path, "rb") as f:
            remaining = limit
            while remaining is None or remaining > 0:
                chunk = f.read(1024 * 1024 if remaining is None else min(remaining, 1024 * 1024))
                if not chunk:
                    break
                h.update(chunk)
                if remaining is not None:
                    remaining -= len(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _duplicates(by_size: dict[int, list[str]]) -> list[str]:
    """Gleich große Dateien erst am Anfang (64 KB), dann ganz vergleichen."""
    start, groups, complete = time.monotonic(), [], True
    for size, paths in sorted(by_size.items(), reverse=True):
        if len(paths) < 2:
            continue
        if time.monotonic() - start > DUP_TIME_LIMIT:
            complete = False
            break
        for limit in (64 * 1024, None):
            buckets: dict[str, list[str]] = {}
            for p in paths:
                d = _digest(p, limit)
                if d:
                    buckets.setdefault(d, []).append(p)
            paths = [p for same in buckets.values() if len(same) > 1 for p in same]
            if limit is None:
                groups += [(size, same) for same in buckets.values() if len(same) > 1]
    if not groups:
        return ["Doppelte Dateien (ab 1 MB): keine gefunden" + ("" if complete else " (Suche abgebrochen)")]
    waste = sum(size * (len(same) - 1) for size, same in groups)
    lines = [f"Doppelte Dateien (ab 1 MB): {len(groups)} Gruppen, {size_text(waste)} ließen sich sparen"
             + ("" if complete else " (Suche nach 60 s abgebrochen)")]
    for size, same in groups[:10]:
        lines.append(f"  {size_text(size)} × {len(same)}:")
        lines += [f"     {p}" for p in same[:5]]
    if len(groups) > 10:
        lines.append(f"  …und {len(groups) - 10} weitere Gruppen")
    return lines
