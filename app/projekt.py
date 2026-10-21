"""Teamwork: gemeinsamer Projektordner beim Gastgeber.

ProjectFolder führt die Dateiaktionen aller KIs im Raum aus (RoomServer → /api/project, Werkzeuge projekt_* in
agent.py): nur innerhalb des Ordners, mit Grenzen, der alten Fassung jeder geänderten oder gelöschten Datei im
Versionsordner und Konflikterkennung (eine vorhandene Datei überschreibt nur, wer ihren aktuellen Stand gelesen hat).
Befehle gibt es hier bewusst nicht – Gäste führen auf dem Rechner des Gastgebers nichts aus. Fehlermeldungen nennen
nur Pfade relativ zum Projektordner (der volle Pfad verriete z. B. den Benutzernamen des Gastgebers).
"""

import hashlib
import os
import shutil
import stat
import threading
from datetime import datetime
from pathlib import Path

import documents
from agent import EXEC_SUFFIXES, ToolError, _numbered, _read_text_file, list_directory, match_edit, search_files

READ_MAX = 20 * 1024 * 1024         # größere Dateien liest projekt_read nicht
WRITE_MAX = 2 * 1024 * 1024         # Zeichen je projekt_write/edit (eine Anfrage an den Gastgeber hat höchstens 4 MB)
ADDED_MAX = 500 * 1024 * 1024       # so viel dürfen die KIs seit der Freigabe insgesamt hinzufügen
KEEP_VERSIONS = 300                 # so viele alte Fassungen bleiben im Versionsordner
WRITE_OPS = {"write", "edit", "mkdir", "delete"}
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
MONHIP_DIR = Path(__file__).resolve().parent.parent
# Programme/Skripte (und Office mit Makros): beim Herunterladen warnen, von Gästen geschrieben markieren
RISKY_SUFFIXES = EXEC_SUFFIXES | {".msi", ".dll", ".sys", ".psm1", ".appx", ".msix", ".docm", ".xlsm", ".pptm"}


class ProjectError(Exception):
    """Verständlicher Fehler für die KI; code = HTTP-Status beim Gastgeber."""
    code = 400


class Denied(ProjectError):
    code = 403


class Missing(ProjectError):
    code = 404


class Conflict(ProjectError):
    """Die Datei hat sich seit dem letzten Lesen geändert."""
    code = 409


def mark_from_internet(path: Path):
    """Windows-Markierung „aus dem Internet“ (Zone.Identifier): SmartScreen und Office warnen dann beim Öffnen –
    wie bei Downloads aus dem Browser. Auf FAT/exFAT-Laufwerken nicht möglich (dann ohne)."""
    try:
        with open(f"{path}:Zone.Identifier", "wb") as f:
            f.write(b"[ZoneTransfer]\r\nZoneId=3\r\n")
    except OSError:
        pass


def remove_tree(path: Path):
    """Ordner samt Inhalt löschen – auch schreibgeschützte Dateien (shutil.rmtree scheitert unter Windows daran;
    alte Fassungen übernehmen den Schreibschutz der Originale)."""
    def unlock(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onexc=unlock)


def unsafe_root(root: Path, *also: Path) -> str | None:
    """Warum dieser Ordner nicht freigegeben werden darf – sonst None. Gesperrt sind Laufwerke, der Benutzerordner
    und alles darüber, Windows-, Programm- und AppData-Ordner (dort ließe sich Code ablegen, der von selbst startet)
    und Monhip selbst (Programmcode und Daten; also: weitere solche Ordner, z. B. der Datenordner in Tests)."""
    root = Path(root).resolve()

    def within(a: Path, b: Path) -> bool:  # a liegt in b (oder ist b)
        return a == b or b in a.parents

    if root.parent == root:
        return "ein ganzes Laufwerk"
    if within(Path.home().resolve(), root):
        return "dein Benutzerordner oder ein Ordner darüber"
    for name in ("APPDATA", "LOCALAPPDATA", "ProgramData", "ProgramFiles", "ProgramFiles(x86)", "SystemRoot"):
        value = os.environ.get(name)
        if value and within(root, Path(value).resolve()):
            return "ein Windows-, Programm- oder AppData-Ordner"
    for monhip in (MONHIP_DIR, *also):
        monhip = Path(monhip).resolve()
        if within(root, monhip) or within(monhip, root):
            return "der Ordner von Monhip (oder enthält ihn)"
    return None


class ProjectFolder:
    def __init__(self, root: Path, write: bool, versions: Path | None):
        self.root, self.write, self.versions = Path(root).resolve(), bool(write), versions
        self._lock = threading.Lock()                     # eine Aktion nach der anderen
        self._seen: dict[tuple[str, str], str] = {}       # (Teilnehmer, Pfad) → zuletzt gelesene/geschriebene Fassung
        self._changed: dict[str, str] = {}                # Pfad → KI, die zuletzt geändert hat
        self._added = 0                                   # Bytes, die seit der Freigabe dazugekommen sind

    def info(self) -> dict:
        """Was die anderen sehen: nur der Ordnername, nie der volle Pfad."""
        return {"name": self.root.name, "write": self.write}

    def run(self, op: str, args: dict, member: str, who: str, host: bool) -> dict:
        """Eine Aktion eines Teilnehmers (who = Name seiner KI) → {"text": …}; Fehler als ProjectError."""
        fn = {"list": self._list, "read": self._read, "search": self._search, "write": self._write,
              "edit": self._edit, "mkdir": self._mkdir, "delete": self._delete}.get(op)
        if not fn:
            raise ProjectError(f"Unbekannte Aktion „{op}“.")
        if op in WRITE_OPS and not (self.write or host):
            raise Denied("Der Gastgeber hat den Projektordner nur zum Lesen freigegeben.")
        if not isinstance(args, dict):
            raise ProjectError("Ungültige Angaben.")
        with self._lock:
            if not self.root.is_dir():
                raise Missing("Den Projektordner gibt es beim Gastgeber nicht mehr.")
            try:
                return fn(args, member, who, host)
            except ProjectError:
                raise
            except ToolError as e:
                raise ProjectError(str(e)) from None
            except OSError as e:  # ohne Dateinamen – der volle Pfad verriete den Ordner des Gastgebers
                raise ProjectError(f"Dateifehler: {e.strerror or type(e).__name__}") from None
            except ValueError as e:  # z. B. Binärdatei, unlesbares Dokument (Meldungen ohne Pfad)
                raise ProjectError(str(e)) from None

    # ------------------------------------------------------------ Pfade, Fassungen

    def _path(self, raw) -> tuple[Path, str]:
        """(voller Pfad, Pfad relativ zum Projektordner) – nur innerhalb des Ordners."""
        text = str(raw if raw not in (None, "") else ".").replace("\\", "/").strip().strip('"')
        parts = [p for p in text.split("/") if p not in ("", ".")]
        if text.startswith("/") or ".." in parts or any(":" in p for p in parts):
            raise Denied("Nur Pfade innerhalb des Projektordners (relativ, ohne „..“ und Laufwerk).")
        for p in parts:
            if p.split(".")[0].upper() in RESERVED or p != p.rstrip(" ."):
                raise ProjectError(f"Ungültiger Name „{p}“.")
        full = self.root.joinpath(*parts).resolve()
        if full != self.root and self.root not in full.parents:  # z. B. über eine Verknüpfung nach draußen
            raise Denied("Der Pfad führt aus dem Projektordner hinaus.")
        return full, "/".join(parts) or "."

    @staticmethod
    def _writable(full: Path, rel: str):
        if ".git" in rel.lower().split("/"):
            raise Denied("Den Ordner .git (Versionsverwaltung des Gastgebers) ändern die KIs nicht.")
        if full.suffix.lower() in documents.CONVERTED:  # Text hineinzuschreiben machte die Datei kaputt
            raise ProjectError(f"„{rel}“ (PDF, Office, OpenDocument, RTF) lässt sich hier nur lesen.")

    @staticmethod
    def _version(data: bytes) -> str:
        return hashlib.sha1(data).hexdigest()[:16]

    def _keep_old(self, full: Path, rel: str, who: str, move: bool = False):
        """Alte Fassung (bzw. Gelöschtes) in den Versionsordner: <Zeit bis auf Mikrosekunden>-<KI>/<Pfad> – so sortiert
        der Name genau nach Alter (die ältesten fallen weg)."""
        if not self.versions:
            if move:
                remove_tree(full) if full.is_dir() else full.unlink()
            return
        target = self.versions / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{who}" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if move:
            shutil.move(str(full), str(target))
        elif full.is_dir():
            shutil.copytree(full, target)
        else:
            shutil.copy2(full, target)
        old = sorted(self.versions.iterdir())
        for d in old[:max(0, len(old) - KEEP_VERSIONS)]:
            try:
                remove_tree(d)
            except OSError:
                pass  # z. B. gerade vom Virenscanner geöffnet – dann beim nächsten Mal

    def _grow(self, delta: int):
        if delta > 0 and self._added + delta > ADDED_MAX:
            raise ProjectError("Im Projektordner ist kein Platz mehr (seit der Freigabe höchstens 500 MB neu).")

    def _written(self, full: Path, rel: str, data: bytes, delta: int, member: str, who: str, host: bool):
        self._added += delta
        self._seen[(member, rel.lower())] = self._version(data)
        self._changed[rel.lower()] = who
        if not host and full.suffix.lower() in RISKY_SUFFIXES:
            mark_from_internet(full)  # von einem Gast geschriebenes Programm/Skript: Windows warnt beim Öffnen

    def _existing_text(self, full: Path, rel: str) -> tuple[bytes, str]:
        if not full.is_file():
            raise Missing(f"Die Datei „{rel}“ gibt es im Projektordner nicht.")
        if full.stat().st_size > READ_MAX:
            raise ProjectError(f"„{rel}“ ist zu groß (höchstens {READ_MAX // 1024 ** 2} MB).")
        data = full.read_bytes()
        text = documents.read(full).text if full.suffix.lower() in documents.CONVERTED else _read_text_file(full)
        return data, text

    # ------------------------------------------------------------ Aktionen

    def _list(self, a, member, who, host):
        full, rel = self._path(a.get("path"))
        if not full.is_dir():
            raise Missing(f"„{rel}“ ist kein Ordner im Projektordner.")
        title = f"Projektordner „{self.root.name}“" + ("" if rel == "." else f" / {rel}")
        return {"text": list_directory(full, a.get("depth") or 2, title)}

    def _search(self, a, member, who, host):
        full, rel = self._path(a.get("path"))
        if not full.is_dir():
            raise Missing(f"„{rel}“ ist kein Ordner im Projektordner.")
        title = f"Projektordner „{self.root.name}“" + ("" if rel == "." else f" / {rel}")
        return {"text": search_files(full, a.get("pattern") or "*", a.get("text") or "", title)}

    def _read(self, a, member, who, host):
        full, rel = self._path(a.get("path"))
        data, text = self._existing_text(full, rel)
        version = self._version(data)
        self._seen[(member, rel.lower())] = version
        return {"text": _numbered(text, a.get("start_line") or 1, a.get("end_line")), "version": version}

    def _write(self, a, member, who, host):
        content = a.get("content")
        if not isinstance(content, str):
            raise ProjectError("content fehlt.")
        if len(content) > WRITE_MAX:
            raise ProjectError(f"Zu viel auf einmal (höchstens {WRITE_MAX // 1024 ** 2} Mio. Zeichen je Datei).")
        full, rel = self._path(a.get("path"))
        self._writable(full, rel)
        if rel == "." or full.is_dir():
            raise ProjectError(f"„{rel}“ ist ein Ordner.")
        data, delta = content.encode("utf-8"), 0
        if full.exists():
            old = full.read_bytes()
            seen = self._seen.get((member, rel.lower()))
            if seen != self._version(old):
                by = self._changed.get(rel.lower())
                raise Conflict(
                    f"„{rel}“ wurde seit deinem letzten Lesen geändert{f' (zuletzt von {by})' if by else ''} – "
                    "erst mit projekt_read neu lesen." if seen else
                    f"„{rel}“ gibt es schon – erst mit projekt_read lesen (oder projekt_edit nutzen), damit nichts "
                    "verloren geht, was andere geschrieben haben.")
            delta = len(data) - len(old)
            self._grow(delta)
            self._keep_old(full, rel, who)
        else:
            delta = len(data)
            self._grow(delta)
            full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)
        self._written(full, rel, data, delta, member, who, host)
        return {"text": f"{len(content)} Zeichen nach {rel} geschrieben."}

    def _edit(self, a, member, who, host):
        full, rel = self._path(a.get("path"))
        self._writable(full, rel)
        old, text = self._existing_text(full, rel)
        try:
            old_text, new_text = match_edit(text, str(a.get("old_text") or ""), str(a.get("new_text") or ""))
        except ToolError as e:
            raise ProjectError(str(e).replace("read_file", "projekt_read")) from None
        data = text.replace(old_text, new_text, 1).encode("utf-8")
        if len(data) > WRITE_MAX * 2:
            raise ProjectError("Die Datei würde zu groß.")
        self._grow(len(data) - len(old))
        self._keep_old(full, rel, who)
        full.write_bytes(data)
        self._written(full, rel, data, len(data) - len(old), member, who, host)
        return {"text": f"{rel} geändert."}

    def _mkdir(self, a, member, who, host):
        full, rel = self._path(a.get("path"))
        self._writable(full, rel)
        if full.is_file():
            raise ProjectError(f"„{rel}“ ist eine Datei.")
        full.mkdir(parents=True, exist_ok=True)
        return {"text": f"Ordner {rel} ist vorhanden."}

    def _delete(self, a, member, who, host):
        full, rel = self._path(a.get("path"))
        if ".git" in rel.lower().split("/"):
            raise Denied("Den Ordner .git (Versionsverwaltung des Gastgebers) ändern die KIs nicht.")
        if rel == ".":
            raise Denied("Den Projektordner selbst kann niemand löschen.")
        if not full.exists():
            raise Missing(f"„{rel}“ gibt es im Projektordner nicht.")
        self._keep_old(full, rel, who, move=True)
        self._changed[rel.lower()] = who
        return {"text": f"{rel} gelöscht (der Gastgeber kann es aus den alten Fassungen wiederherstellen)."}
