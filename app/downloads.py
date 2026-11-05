"""Gemeinsame Download-Hilfen (llama.cpp, Spracherkennung, Modelle)."""

import json
import os
import re
import shutil
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

UA = {"User-Agent": "Monhip"}


def get_json(url: str, timeout: float = 30):
    req = urllib.request.Request(url, headers={**UA, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def head_size(url: str) -> int:
    """Dateigröße per HEAD (Hugging Face meldet sie bei Weiterleitungen in x-linked-size)."""
    req = urllib.request.Request(url, method="HEAD", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return int(r.headers.get("x-linked-size") or r.headers.get("Content-Length") or 0)


def download(url: str, dest: Path, progress, cancel, done: int = 0, total: int = 0) -> int:
    """Lädt url nach dest. progress(erledigt, gesamt) höchstens alle 0,2 s (sonst flutet ein großer Download die
    Ereignisschleife); done/total zählen über mehrere Dateien weiter. Gibt den neuen Stand von done zurück."""
    last = 0.0
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r, open(dest, "wb") as f:
        total = total or int(r.headers.get("Content-Length") or 0)
        while chunk := r.read(1024 * 1024):
            if cancel.is_set():
                raise RuntimeError("abgebrochen")
            f.write(chunk)
            done += len(chunk)
            if time.monotonic() - last >= 0.2:
                last = time.monotonic()
                progress(done, total)
    progress(done, total)
    return done


def extract(archive: Path, dest: Path):
    """Zip oder tar.gz (Linux-Builds) nach dest entpacken. tar behält Ausführrechte und Bibliotheks-Verknüpfungen;
    der Filter „data“ lässt nichts außerhalb von dest schreiben."""
    if archive.name.endswith((".tar.gz", ".tgz", ".tar.xz")):
        with tarfile.open(archive) as t:
            if hasattr(tarfile, "data_filter"):
                t.extractall(dest, filter="data")
            else:  # Python vor 3.11.4
                t.extractall(dest)
    else:
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)


def _merge(src: Path, dst: Path):
    """Inhalt von src nach dst verschieben: gleichnamige Ordner zusammenführen, Dateien ersetzen (wie extractall)."""
    for f in list(src.iterdir()):
        to = dst / f.name
        if f.is_dir() and not f.is_symlink() and to.is_dir() and not to.is_symlink():
            _merge(f, to)
            f.rmdir()
            continue
        if to.is_symlink() or to.is_file():
            to.unlink()
        elif to.is_dir():
            shutil.rmtree(to)
        f.rename(to)


def install_zips(assets: list[tuple[str, str, int]], target: Path, required: str, progress, cancel,
                 done: int = 0, total: int = 0) -> int:
    """Zips bzw. tar.gz [(name, url, größe)] nach target entpacken: erst in target.part, dann umbenennen – ein
    abgebrochener Download hinterlässt so keine halbe Installation. Jedes Archiv für sich: hat es nur einen
    Hauptordner (z. B. Release/, unter Linux „llama-b1/“ und „cudart-llama-…/“), kommt dessen Inhalt nach oben –
    sonst lägen die CUDA-Bibliotheken in einem Unterordner, wo llama-server sie nicht findet. Liegt required noch
    tiefer (z. B. build/bin/), wird dieser Ordner hochgezogen. required: Datei, die danach da sein muss (unter Linux
    ausführbar)."""
    tmp = target.with_name(target.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        for i, (name, url, _) in enumerate(assets):
            done = download(url, tmp / name, progress, cancel, done, total)
            unpacked = tmp / f".entpackt-{i}"
            extract(tmp / name, unpacked)
            (tmp / name).unlink()
            entries = list(unpacked.iterdir())
            single = len(entries) == 1 and entries[0].is_dir() and not entries[0].is_symlink()
            _merge(entries[0] if single else unpacked, tmp)
            shutil.rmtree(unpacked)
        if not (tmp / required).is_file():
            hits = sorted(tmp.rglob(required), key=lambda p: len(p.parts))
            if hits:
                for f in list(hits[0].parent.iterdir()):
                    if not (tmp / f.name).exists():
                        f.rename(tmp / f.name)
        if (tmp / required).is_file() and os.name != "nt":  # Zip-Dateien kennen keine Ausführrechte
            (tmp / required).chmod((tmp / required).stat().st_mode | 0o755)
        if not (tmp / required).is_file():
            raise RuntimeError(f"In der heruntergeladenen Datei fehlt {required}.")
        if target.exists():
            shutil.rmtree(target)
        tmp.rename(target)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return done


def remove_older(target: Path, pattern: re.Pattern, family=lambda m: m.group(2).split("-")[0]):
    """Ältere Versionen derselben Art neben target löschen (Ordnernamen nach pattern). Eine laufende Version
    lässt sich nicht umbenennen und bleibt bis zum nächsten Mal liegen."""
    new = pattern.match(target.name)
    for old in target.parent.iterdir():
        m = pattern.match(old.name)
        if old == target or not m or not old.is_dir() or (new and family(m) != family(new)):
            continue
        try:
            shutil.rmtree(old.rename(old.with_name(old.name + ".alt")), ignore_errors=True)
        except OSError:
            pass


def clean_leftovers(folder: Path):
    """Reste abgebrochener Downloads (*.part, *.alt) entfernen."""
    for left in [*folder.glob("*.part"), *folder.glob("*.alt")] if folder.is_dir() else []:
        if left.is_dir():
            shutil.rmtree(left, ignore_errors=True)
        else:
            left.unlink(missing_ok=True)
