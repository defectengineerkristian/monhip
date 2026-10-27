"""Projekt-Anweisungen: MONHIP.md, AGENTS.md oder CLAUDE.md in einem freigegebenen Ordner kommen in den
System-Prompt – so kennt das Modell die Regeln eines Projekts, ohne danach suchen zu müssen."""

from pathlib import Path

NAMES = ("MONHIP.md", "AGENTS.md", "CLAUDE.md")  # je Ordner gilt die erste vorhandene
MAX_CHARS = 6000                                  # je Datei, der Rest bleibt mit read_file lesbar
TOTAL_CHARS = 12_000                              # alle Dateien zusammen (kleine Modelle haben wenig Kontext)

HINT = ("Projekt-Anweisungen: Arbeitest du in einem Unterordner (z. B. einem Repository), lies dort vorhandene "
        "MONHIP.md, AGENTS.md oder CLAUDE.md mit read_file, bevor du etwas änderst, und halte dich daran.")


def find(folder: Path) -> Path | None:
    for name in NAMES:
        p = Path(folder) / name
        if p.is_file():
            return p
    return None


def prompt_block(folders) -> str:
    """Abschnitt für den System-Prompt – leer, wenn kein freigegebener Ordner Anweisungen hat."""
    parts, used = [], 0
    for folder in folders:
        p = find(folder)
        if not p:
            continue
        try:
            text = p.read_text(encoding="utf-8-sig", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS].rstrip()
            text += f"\n…(gekürzt – weiter mit read_file, start_line={text.count(chr(10)) + 1})"
        if used + len(text) > TOTAL_CHARS:
            parts.append(f"(Weitere Anweisungen in {p} – bei Bedarf mit read_file lesen.)")
            continue
        used += len(text)
        parts.append(f"### {p}\n{text}")
    if not parts:
        return ""
    return "Anweisungen für die Projekte in den freigegebenen Ordnern – halte dich daran:\n\n" + "\n\n".join(parts)
