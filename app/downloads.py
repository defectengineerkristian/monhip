"""Gemeinsame Download-Hilfen (llama.cpp, Spracherkennung, Modelle)."""

import json
import re
import shutil
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


def install_zips(assets: list[tuple[str, str, int]], target: Path, required: str, progress, cancel,
                 done: int = 0, total: int = 0) -> int:
    """Zips [(name, url, größe)] nach target entpacken: erst in target.part, dann umbenennen – ein abgebrochener
    Download hinterlässt so keine halbe Installation. Ein einzelner Unterordner (z. B. Release/) wird
    flachgezogen. required: Datei, die danach da sein muss."""
    tmp = target.with_name(target.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        for name, url, _ in assets:
            done = download(url, tmp / name, progress, cancel, done, total)
            with zipfile.ZipFile(tmp / name) as z:
                z.extractall(tmp)
            (tmp / name).unlink()
        inner = [p for p in tmp.iterdir() if p.is_dir()]
        if not (tmp / required).is_file() and len(inner) == 1 and (inner[0] / required).is_file():
            for f in inner[0].iterdir():
                f.rename(tmp / f.name)
            inner[0].rmdir()
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
