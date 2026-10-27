"""Checkpoints: Bevor der Agent eine Datei oder einen Ordner ändert, wird der alte Stand gesichert – ein Checkpoint
je Antwort. checkpoint_zurueck stellt alles wieder her, was in einer Antwort geändert wurde.

Gespeichert in checkpoints/<nr>/ neben der App: stand.json und Kopien (0000, 0001 …); Verschiebungen werden nur
vermerkt (save_move), nicht kopiert – zurück geht es mit derselben Bewegung rückwärts. Nicht erfasst: Befehle
(run_command, run_python, Hintergrund-Prozesse), Git (hat seine eigene Geschichte) und der Teamwork-Projektordner."""

import json
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path

from i18n import tr

DIR =Path(__file__).resolve().parent.parent / "checkpoints"  # erst beim Aufruf gelesen – Tests biegen ihn um
KEEP = 30                       # so viele Checkpoints bleiben, ältere werden gelöscht
MAX_SIZE = 50 * 1024 * 1024     # größere Dateien bzw. Ordner werden nicht gesichert (steht im Checkpoint)
_lock = threading.Lock()
_restoring: set[int] = set()    # wird gerade wiederhergestellt – nicht als alt löschen


class CheckpointError(Exception):
    """Fehler, den das Modell als verständlichen Satz bekommt (wie agent.ToolError)."""


def _too_big(p: Path) -> bool:
    if p.is_file():
        return p.stat().st_size > MAX_SIZE
    total = 0
    for dirpath, _, filenames in os.walk(p):
        for fn in filenames:
            try:
                total += (Path(dirpath) / fn).stat().st_size
            except OSError:
                continue
            if total > MAX_SIZE:
                return True
    return False


def numbers(base: Path | None = None) -> list[int]:
    base = base or DIR
    try:
        return sorted(int(d.name) for d in base.iterdir() if d.is_dir() and d.name.isdigit())
    except OSError:
        return []


def load(nr: int, base: Path | None = None) -> dict:
    base = base or DIR
    try:
        return json.loads((base / str(int(nr)) / "stand.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CheckpointError(f"Einen Checkpoint [{nr}] gibt es nicht – siehe checkpoints_liste.") from None


def recent(count: int = 10, base: Path | None = None) -> list[dict]:
    """Die neuesten Checkpoints zuerst (nur solche, in denen etwas gesichert wurde)."""
    base = base or DIR
    found = []
    for nr in reversed(numbers(base)):
        try:
            data = load(nr, base)
        except CheckpointError:
            continue
        if data.get("eintraege"):
            found.append(data)
        if len(found) >= count:
            break
    return found


def describe(data: dict, max_paths: int = 6, note: str = "", ui: bool = False) -> str:
    """ui: für den Bestätigungsdialog (in der Sprache der Oberfläche), sonst fürs Modell (deutsch)."""
    t = tr if ui else (lambda text, *args: text.format(*args))
    entries = data.get("eintraege", [])
    paths = [f"{e['von']} → {e['pfad']}" if e["vorher"] == "verschoben" else
             e["pfad"] + (t(" (neu)") if e["vorher"] == "fehlt" else "") for e in entries[:max_paths]]
    more = "\n    " + t("…und {0} weitere", len(entries) - max_paths) if len(entries) > max_paths else ""
    return t("[{0}] {1} – {2} Pfad(e){3}", data['nr'], data.get('zeit', '?'), len(entries), note) + "\n" + "\n".join(
        f"    {p}" for p in paths) + more


class Checkpoint:
    """Ein Checkpoint (eine Antwort des Modells). Der Ordner entsteht erst, wenn wirklich etwas gesichert wird."""

    def __init__(self, base: Path | None = None):
        self.base = base or DIR
        self.nr: int | None = None
        self.entries: list[dict] = []
        self.time = ""

    @property
    def folder(self) -> Path:
        return self.base / str(self.nr)

    def _create(self):
        with _lock:
            self.base.mkdir(parents=True, exist_ok=True)
            old = numbers(self.base)
            self.nr = max(old, default=0) + 1
            self.folder.mkdir()
            for nr in old[:max(0, len(old) + 1 - KEEP)]:  # unsere eigenen Sicherungen, keine Nutzerdaten
                if nr not in _restoring:
                    shutil.rmtree(self.base / str(nr), ignore_errors=True)
        self.time = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    def _covered(self, path: Path) -> bool:
        """Schon gesichert – der Pfad selbst oder ein Ordner darüber, dessen ganzer Inhalt gesichert ist. Was erst in
        dieser Antwort hineinverschoben wurde, deckt der Ordner nicht ab: dessen Inhalt kommt von woanders."""
        key = str(path).casefold()  # Windows: Groß-/Kleinschreibung egal

        def inside(p: str) -> bool:
            p = p.casefold()
            return key == p or key.startswith(p.rstrip("\\/") + os.sep)

        moved_in = any(e["vorher"] == "verschoben" and inside(e["pfad"]) for e in self.entries)
        for e in self.entries:
            if e["vorher"] == "verschoben":  # vermerkt nur den Ort, nicht den Inhalt
                continue
            if key == e["pfad"].casefold():
                return True
            if e["vorher"] in ("ordner", "fehlt") and inside(e["pfad"]) and not moved_in:
                return True
        return False

    def save(self, path: Path):
        """Den jetzigen Stand von path sichern – je Checkpoint nur beim ersten Mal (es zählt der Anfangsstand)."""
        path = Path(path)
        if self._covered(path):
            return
        if self.nr is None:
            self._create()
        entry = {"pfad": str(path)}
        try:
            if not path.exists():
                entry["vorher"] = "fehlt"
            elif _too_big(path):
                entry["vorher"] = "zu_gross"
            else:
                entry["kopie"] = f"{len(self.entries):04d}"
                if path.is_dir():
                    shutil.copytree(path, self.folder / entry["kopie"], symlinks=True)
                    entry["vorher"] = "ordner"
                else:
                    shutil.copy2(path, self.folder / entry["kopie"])
                    entry["vorher"] = "datei"
        except OSError as e:
            raise CheckpointError(f"Konnte den alten Stand von {path} nicht sichern ({e}) – nichts geändert.") from None
        self._add(entry)

    def save_move(self, src: Path, dst: Path):
        """Eine Verschiebung vermerken – ohne Kopie, zurück geht es mit derselben Bewegung rückwärts."""
        if self.nr is None:
            self._create()
        self._add({"pfad": str(dst), "vorher": "verschoben", "von": str(src)})

    def _add(self, entry: dict):
        self.entries.append(entry)
        tmp = self.folder / "stand.tmp"
        tmp.write_text(json.dumps({"nr": self.nr, "zeit": self.time, "eintraege": self.entries}, indent=1,
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.folder / "stand.json")


def restore(nr: int, recycle, before: "Checkpoint | None" = None, base: Path | None = None) -> list[str]:
    """Stellt den Stand vor Checkpoint nr wieder her – in umgekehrter Reihenfolge, damit bei mehreren Änderungen am
    selben Ort der Anfangsstand gewinnt. recycle(pfad) räumt den jetzigen Stand weg (Papierkorb), before sichert
    ihn vorher (der Checkpoint der laufenden Antwort – so lässt sich auch das Zurücksetzen zurücknehmen).
    → Zeilen fürs Ergebnis."""
    base = base or DIR
    data = load(nr, base)
    folder = base / str(int(nr))
    _restoring.add(int(nr))
    try:
        return _restore(data, folder, recycle, before)
    finally:
        _restoring.discard(int(nr))


def _restore(data: dict, folder: Path, recycle, before) -> list[str]:
    lines = []
    for e in reversed(data.get("eintraege", [])):
        p, kind = Path(e["pfad"]), e["vorher"]
        if kind == "zu_gross":
            lines.append(f"✗ {p} – war zu groß zum Sichern, nicht wiederhergestellt")
            continue
        if kind == "verschoben":
            back = Path(e["von"])
            if not p.exists():
                lines.append(f"✗ {p} gibt es nicht mehr – nicht zurück nach {back}")
            elif back.exists() and os.path.normcase(str(back)) != os.path.normcase(str(p)):
                lines.append(f"✗ {back} ist inzwischen belegt – {p} bleibt, wo es ist")
            else:
                if before:
                    before.save_move(p, back)
                back.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(back))
                lines.append(f"✓ {p.name} zurück nach {back.parent}")
            continue
        if before:
            before.save(p)
        if kind == "fehlt":
            if p.exists():
                recycle(p)
                lines.append(f"✓ {p} entfernt (gab es vorher nicht; liegt im Papierkorb)")
            continue
        src = folder / e["kopie"]
        if p.exists() and (kind == "ordner" or p.is_dir()):
            recycle(p)  # Ordner werden ersetzt, nicht gemischt
        p.parent.mkdir(parents=True, exist_ok=True)
        if kind == "ordner":
            shutil.copytree(src, p, symlinks=True)
        else:
            shutil.copy2(src, p)
        lines.append(f"✓ {p} wiederhergestellt")
    return lines or ["Nichts zu tun."]
