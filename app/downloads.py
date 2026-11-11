"""Gemeinsame Download-Hilfen (llama.cpp, Spracherkennung, Modelle)."""

from i18n import tr

import hashlib
import http.client
import json
import os
import re
import shutil
import tarfile
import time
import urllib.error
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


def asset_sha256(asset: dict) -> str | None:
    """SHA-256 einer Datei aus einem GitHub-Release laut API („digest": "sha256:…", seit 2025) – sonst None."""
    digest = asset.get("digest")
    if isinstance(digest, str) and re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        return digest[7:].lower()
    return None


def _range_start(value: str | None) -> int | None:
    """Anfang aus „Content-Range: bytes 100-999/1000“ (Antwort 206 auf eine Range-Anfrage)."""
    m = re.match(r"bytes (\d+)-", value or "")
    return int(m.group(1)) if m else None


def download(url: str, dest: Path, progress, cancel, done: int = 0, total: int = 0, sha256: str | None = None,
             resume: bool = False) -> int:
    """Lädt url nach dest. progress(erledigt, gesamt) höchstens alle 0,2 s (sonst flutet ein großer Download die
    Ereignisschleife); done/total zählen über mehrere Dateien weiter. Gibt den neuen Stand von done zurück.
    sha256: erwartete Prüfsumme – wird beim Laden mitgerechnet; passt sie nicht, RuntimeError (beschädigt oder
    unterwegs verändert; das Programm wird danach ausgeführt).
    Fehlen am Ende Bytes (Verbindung abgerissen), ConnectionError: http.client meldet das selbst nicht, die Datei
    sähe sonst fertig aus – ein abgeschnittenes Modell bliebe für immer kaputt, weil vorhandene Dateien beim nächsten
    Mal übersprungen werden. resume: Liegt dest (eine .part-Datei) schon teilweise da, geht es dort weiter (HTTP-Range;
    lehnt der Server das ab, von vorn) – bei großen Modellen begann ein Abriss kurz vor Schluss sonst wieder bei null."""
    last = 0.0
    have = dest.stat().st_size if resume and dest.is_file() else 0
    headers = {**UA, "Range": f"bytes={have}-"} if have else UA
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)
    except urllib.error.HTTPError as e:
        if not (have and e.code == 416):  # 416: der Teil passt nicht (mehr) zur Datei – von vorn
            raise
        e.close()
        dest.unlink(missing_ok=True)
        return download(url, dest, progress, cancel, done, total, sha256)
    with r:
        start = have if have and r.status == 206 and _range_start(r.headers.get("Content-Range")) == have else 0
        length = r.headers.get("Content-Length")
        expected = int(length) if length and length.isdigit() and not r.headers.get("Content-Encoding") else None
        total = total or (start + expected if expected is not None else 0)
        check = hashlib.sha256() if sha256 else None
        if check and start:  # den schon geladenen Teil mitrechnen
            with open(dest, "rb") as f:
                while chunk := f.read(1 << 20):
                    check.update(chunk)
        done += start
        received = 0
        with open(dest, "ab" if start else "wb") as f:
            while chunk := r.read(1024 * 1024):
                if cancel.is_set():
                    raise RuntimeError("abgebrochen")
                f.write(chunk)
                if check:
                    check.update(chunk)
                received += len(chunk)
                done += len(chunk)
                if time.monotonic() - last >= 0.2:
                    last = time.monotonic()
                    progress(done, total)
    if expected is not None and received != expected:
        raise ConnectionError(tr('Der Download von {0} brach nach {1} von {2} MB ab – bitte erneut versuchen (es geht '
                                 'dort weiter).', dest.name.removesuffix(".part"), (start + received) // 2 ** 20,
                                 (start + expected) // 2 ** 20))
    if check and check.hexdigest() != sha256:
        raise RuntimeError(f"Die Prüfsumme von {dest.name} stimmt nicht – die Datei ist beschädigt oder wurde "
                           "verändert. Bitte erneut herunterladen.")
    progress(done, total)
    return done


def fetch_one(url: str, dest: Path, progress, cancel, done: int = 0, total: int = 0) -> int:
    """Eine große Datei (Modell) über <dest>.part laden und erst fertig umbenennen. Bricht die Verbindung ab, bleibt
    der Teil liegen und der nächste Versuch macht dort weiter; nach „Abbrechen“ (cancel) oder einem anderen Fehler
    bleibt nichts liegen. Gibt den neuen Stand von done zurück."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    try:
        done = download(url, part, progress, cancel, done, total, resume=True)
        part.replace(dest)
    except BaseException as e:
        broken = isinstance(e, (OSError, http.client.HTTPException)) and not cancel.is_set()
        if not (broken and part.is_file() and part.stat().st_size):
            part.unlink(missing_ok=True)
        raise
    return done


def partial_size(dest: Path) -> int:
    """So viel einer Datei liegt schon als <dest>.part da (zum Weitermachen)."""
    try:
        return dest.with_name(dest.name + ".part").stat().st_size
    except OSError:
        return 0


def fetch_files(files: list[tuple[str, Path]], progress, cancel) -> int:
    """Lädt die fehlenden Dateien von [(URL, Ziel)] nacheinander, jede über eine .part-Datei (ein Abbruch hinterlässt
    keine halbe Datei unter richtigem Namen; nach einem Verbindungsabbruch geht es beim nächsten Mal dort weiter,
    siehe fetch_one); vorhandene bleiben. Prüft vorher den freien Platz (+ 1 GB Reserve, schon geladene Teile
    zählen mit). progress(erledigt, gesamt) zählt über alle Dateien. Gibt die geladenen Bytes zurück."""
    missing = [(url, dest) for url, dest in files if not dest.is_file()]
    if not missing:
        return 0
    total = sum(head_size(url) for url, _ in missing)
    need = max(0, total - sum(partial_size(dest) for _, dest in missing)) + 2 ** 30
    folder = missing[0][1].parent
    folder.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(folder).free
    if need > free:
        raise RuntimeError(tr('Zu wenig Speicherplatz: {0:.1f} GB nötig, {1:.1f} GB frei.',
                              need / 1024 ** 3, free / 1024 ** 3))
    done = 0
    for url, dest in missing:
        done = fetch_one(url, dest, progress, cancel, done, total)
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


def install_zips(assets: list[tuple], target: Path, required: str, progress, cancel,
                 done: int = 0, total: int = 0) -> int:
    """Zips bzw. tar.gz [(name, url, größe)] nach target entpacken: erst in target.part, dann umbenennen – ein
    abgebrochener Download hinterlässt so keine halbe Installation. Jedes Archiv für sich: hat es nur einen
    Hauptordner (z. B. Release/, unter Linux „llama-b1/“ und „cudart-llama-…/“), kommt dessen Inhalt nach oben –
    sonst lägen die CUDA-Bibliotheken in einem Unterordner, wo llama-server sie nicht findet. Liegt required noch
    tiefer (z. B. build/bin/), wird dieser Ordner hochgezogen. required: Datei, die danach da sein muss (unter Linux
    ausführbar). Ein viertes Element je Archiv ist die erwartete SHA-256 (asset_sha256) oder None."""
    tmp = target.with_name(target.name + ".part")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        for i, (name, url, _size, *digest) in enumerate(assets):
            check = {"sha256": digest[0]} if digest and digest[0] else {}
            done = download(url, tmp / name, progress, cancel, done, total, **check)
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
