"""Gedächtnis über alle Chats hinweg (Werkzeuge remember/forget), gespeichert in gedaechtnis.json."""

import json
import threading
from datetime import datetime
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "gedaechtnis.json"
MAX_NOTES = 60          # ältere fallen aus dem System-Prompt, damit er nicht ausufert
MAX_CHARS = 300
_lock = threading.Lock()  # Werkzeuge laufen im Hintergrund-Thread, die Einstellungen im Tk-Thread


def load() -> list[dict]:
    """Alle Notizen [{id, text, created}], älteste zuerst."""
    try:
        notes = json.loads(FILE.read_text(encoding="utf-8"))
        return [n for n in notes if isinstance(n, dict) and "id" in n and "text" in n]
    except (OSError, ValueError, TypeError):
        return []


def _save(notes: list[dict]):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(notes, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(FILE)


def add(text: str) -> dict:
    text = " ".join(str(text).split())
    if not text:
        raise ValueError("Leere Notiz.")
    if len(text) > MAX_CHARS:
        raise ValueError(f"Bitte kürzer fassen (höchstens {MAX_CHARS} Zeichen).")
    with _lock:
        notes = load()
        for n in notes:
            if n["text"].casefold() == text.casefold():
                return n
        note = {"id": max((n["id"] for n in notes), default=0) + 1, "text": text,
                "created": datetime.now().strftime("%Y-%m-%d %H:%M")}
        _save(notes + [note])
        return note


def remove(note_id: int) -> bool:
    with _lock:
        notes = load()
        rest = [n for n in notes if n["id"] != note_id]
        if len(rest) == len(notes):
            return False
        _save(rest)
        return True


def clear():
    with _lock:
        _save([])


def prompt_block() -> str:
    notes = load()[-MAX_NOTES:]
    if not notes:
        return "Du hast dir noch nichts über den Nutzer gemerkt."
    return "Das hast du dir über den Nutzer gemerkt:\n" + "\n".join(f"- [{n['id']}] {n['text']}" for n in notes)
