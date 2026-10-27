"""Viele Dateien auf einmal ordnen (Werkzeug dateien_ordnen): Das Modell schickt einen ganzen Plan („von → nach“),
der Nutzer bestätigt ihn in einem einzigen Dialog, dann wird alles verschoben bzw. umbenannt. Rückgängig über den
Checkpoint der Antwort – Verschiebungen werden dort nur vermerkt, nicht kopiert (Checkpoint.save_move)."""

import json
import os
import shutil
from pathlib import Path

from i18n import tr

MAX_MOVES = 1000
PREVIEW_LINES = 40


class OrdnenError(Exception):
    """Fehler, den das Modell als verständlichen Satz bekommt (wie agent.ToolError)."""


def _key(p: Path) -> str:
    return os.path.normcase(str(p))  # Windows: Groß-/Kleinschreibung egal


def _ziel(text: str) -> str:
    """Leerzeichen um die Teile des Ziels weg ('Downloads/ PDFs/' → 'Downloads/PDFs/'): Ein echtes Modell schrieb
    das so, und Windows legte einen Ordner „ PDFs“ an. Quellen bleiben, wie sie sind – Dateien können so heißen."""
    text = text.strip().strip('"')
    if os.name == "nt":
        text = text.replace("\\", "/")
    return "/".join(part.strip() for part in text.split("/"))


def plan(base: Path, verschiebungen, resolve, roots=()) -> list[tuple[Path, Path]]:
    """[(von, nach)] – vorher vollständig geprüft: Es wird entweder der ganze Plan ausgeführt oder nichts.
    resolve(pfad) → Path in einem freigegebenen Ordner (Agent._path, wirft PermissionError)."""
    if isinstance(verschiebungen, str):
        try:
            verschiebungen = json.loads(verschiebungen)
        except ValueError:
            raise OrdnenError("verschiebungen muss eine Liste wie [{\"von\": \"a.jpg\", \"nach\": \"Bilder/\"}] "
                              "sein.") from None
    if not isinstance(verschiebungen, list) or not verschiebungen:
        raise OrdnenError("verschiebungen ist leer.")
    if len(verschiebungen) > MAX_MOVES:
        raise OrdnenError(f"Höchstens {MAX_MOVES} Einträge je Aufruf – den Rest in einem zweiten Aufruf.")
    roots = {_key(Path(r)) for r in roots}
    moves, problems, sources, targets = [], [], {}, {}
    for item in verschiebungen:
        if not isinstance(item, dict) or not item.get("von") or not item.get("nach"):
            problems.append(f"Eintrag ohne von/nach: {json.dumps(item, ensure_ascii=False)[:80]}")
            continue
        von, nach = str(item["von"]).strip().strip('"'), _ziel(str(item["nach"]))
        try:
            src = resolve(str(base / von))
            into = nach.endswith(("/", "\\")) or resolve(str(base / nach)).is_dir()
            dst = resolve(str(base / nach / src.name)) if into else resolve(str(base / nach))
        except PermissionError as e:
            problems.append(str(e))
            continue
        if not src.exists():
            problems.append(f"{von}: gibt es nicht")
        elif _key(src) in roots:
            problems.append(f"{von}: ein freigegebener Ordner selbst wird nicht verschoben")
        elif _key(dst) == _key(src) and str(dst) == str(src):
            continue  # liegt schon da
        elif _key(src) in sources:
            problems.append(f"{von}: steht mehrfach im Plan")
        elif _key(dst) in targets:
            problems.append(f"{nach}: Ziel für {targets[_key(dst)]} und {src.name}")
        elif dst.exists() and _key(dst) != _key(src):  # nur Groß-/Kleinschreibung ändern ist erlaubt
            problems.append(f"{nach}: gibt es schon (anderen Namen wählen)")
        elif src.is_dir() and (dst == src or src in dst.parents):
            problems.append(f"{von}: ein Ordner kann nicht in sich selbst verschoben werden")
        else:
            sources[_key(src)] = von
            targets[_key(dst)] = src.name
            moves.append((src, dst))
    folders = [s for s, _ in moves if s.is_dir()]
    for src, _ in moves:
        inside = next((f for f in folders if f in src.parents), None)
        if inside:
            problems.append(f"{src.name}: liegt in {inside.name}, der auch verschoben wird – nur eins von beiden")
    if problems:
        shown = "\n".join(f"- {p}" for p in problems[:15])
        more = f"\n…und {len(problems) - 15} weitere" if len(problems) > 15 else ""
        raise OrdnenError(f"Der Plan wurde nicht ausgeführt, nichts wurde verschoben:\n{shown}{more}\n"
                          "Korrigiere diese Einträge und schicke den ganzen Plan noch einmal.")
    return moves


def _rel(p: Path, base: Path) -> str:
    try:
        return str(p.relative_to(base)) or "."
    except ValueError:
        return str(p)


def preview(moves: list[tuple[Path, Path]], base: Path) -> str:
    """Für den Bestätigungsdialog: nach Zielordner gruppiert, umbenannte Dateien mit altem Namen."""
    groups: dict[Path, list[str]] = {}
    for src, dst in moves:
        name = dst.name if dst.name == src.name else f"{src.name} → {dst.name}"
        if src.parent != dst.parent and src.parent != base:
            name += tr('  (aus {0})', _rel(src.parent, base))
        groups.setdefault(dst.parent, []).append(name)
    lines, shown = [tr('Basisordner: {0}', base), ""], 0
    for folder, names in groups.items():
        lines.append(f"→ {_rel(folder, base)}  ({len(names)})")
        for n in names[:8]:
            lines.append(f"     {n}")
            shown += 1
        if len(names) > 8:
            lines.append("     " + tr('…und {0} weitere', len(names) - 8))
        if len(lines) > PREVIEW_LINES:
            lines.append(tr('…(insgesamt {0} Einträge in {1} Ordnern)', len(moves), len(groups)))
            break
    return "\n".join(lines)


def ausfuehren(moves, before_move=None, before_dir=None) -> tuple[int, list[str]]:
    """Verschiebt alles. before_dir(ordner) vermerkt einen neu angelegten Ordner, before_move(von, nach) die
    Verschiebung – beides für den Checkpoint. → (Anzahl erledigt, Fehler)"""
    done, errors = 0, []
    for src, dst in moves:
        try:
            top, folder = None, dst.parent
            while not folder.exists() and folder.parent != folder:
                top, folder = folder, folder.parent
            if top and before_dir:
                before_dir(top)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if before_move:
                before_move(src, dst)
            shutil.move(str(src), str(dst))
            done += 1
        except OSError as e:
            errors.append(f"{src.name}: {e.strerror or e}")
    return done, errors
