"""Speichert Chats als JSON-Dateien im Ordner chats/ neben Monhip.pyw."""

import json
import re
import secrets
import shutil
from datetime import datetime, timedelta
from pathlib import Path

CHAT_DIR = Path(__file__).resolve().parent.parent / "chats"
IMAGE_DIR = CHAT_DIR / "bilder"  # angehängte Bilder: bilder/<chat-id>/<datei> (+ <datei>.vorschau.png)


def new_chat() -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    return {"id": datetime.now().strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(2),
            "title": "Neuer Chat", "created": now, "updated": now, "messages": []}


def make_title(text: str, limit: int = 38) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[:limit - 1].rstrip() + "…"


def _file(chat_id: str) -> Path:
    return CHAT_DIR / f"{chat_id}.json"


def save(chat: dict, touch: bool = True):
    """touch=False (z.B. beim Umbenennen): Zeitstempel und damit die Sortierung bleiben gleich."""
    CHAT_DIR.mkdir(exist_ok=True)
    if touch:
        chat["updated"] = datetime.now().isoformat(timespec="seconds")
    # Nachrichten immer zuletzt: die Chatliste liest nur den Dateianfang (_meta) – dort muss z. B. „experte“ stehen
    data = {k: v for k, v in chat.items() if k != "messages"}
    data["messages"] = chat.get("messages", [])
    tmp = _file(chat["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(_file(chat["id"]))


def load(chat_id: str) -> dict | None:
    try:
        return json.loads(_file(chat_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def delete(chat_id: str):
    _file(chat_id).unlink(missing_ok=True)
    shutil.rmtree(IMAGE_DIR / chat_id, ignore_errors=True)


def store_image(chat_id: str, src: Path, thumb: Path | None = None) -> str:
    """Kopiert ein angehängtes Bild (und sein Vorschaubild) zum Chat, damit es auch dann noch ans Modell
    geht, wenn das Original gelöscht wird. Gibt den Pfad relativ zu IMAGE_DIR zurück."""
    folder = IMAGE_DIR / chat_id
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{secrets.token_hex(3)}-{src.name}"
    shutil.copy2(src, target)
    if thumb and thumb.is_file():
        shutil.copy2(thumb, thumb_path(target))
    return f"{chat_id}/{target.name}"


def image_path(rel: str) -> Path:
    return IMAGE_DIR / rel


def thumb_path(image: Path) -> Path:
    return image.with_name(image.name + ".vorschau.png")


def exists(chat_id: str) -> bool:
    return _file(chat_id).is_file()


_index: dict[str, tuple] = {}  # Datei → ((mtime, größe), Eintrag): nur geänderte Chats neu lesen
_HEAD = re.compile(r'"(id|title|updated)": ("(?:[^"\\]|\\.)*")')


def _meta(f: Path) -> dict:
    """id/title/updated stehen am Dateianfang (vor den Nachrichten) – meist reichen die ersten 2 KB."""
    with open(f, "rb") as fh:
        head = fh.read(2048).decode("utf-8", "ignore").split('"messages"')[0]
    found = {k: json.loads(v) for k, v in _HEAD.findall(head)}
    expert = '"experte":' in head  # Experten-Chat (Experten-Modus)
    if "id" not in found or "updated" not in found:
        c = json.loads(f.read_text(encoding="utf-8"))
        found = {k: c.get(k, "") for k in ("id", "title", "updated")}
        expert = bool(c.get("experte"))
    return {"id": found["id"], "title": found.get("title") or "Chat", "updated": found.get("updated", ""),
            "expert": expert}


def list_all() -> list[dict]:
    """Alle Chats (id, title, updated), neueste zuerst."""
    out, seen = [], set()
    for f in CHAT_DIR.glob("*.json") if CHAT_DIR.is_dir() else []:
        try:
            st = f.stat()
            stamp = (st.st_mtime_ns, st.st_size)
            cached = _index.get(f.name)
            if not cached or cached[0] != stamp:
                cached = _index[f.name] = (stamp, _meta(f))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        seen.add(f.name)
        out.append(cached[1])
    for gone in set(_index) - seen:
        del _index[gone]
    return sorted(out, key=lambda c: c["updated"], reverse=True)


def group_label(updated: str) -> str:
    try:
        day = datetime.fromisoformat(updated).date()
    except ValueError:
        return "Älter"
    today = datetime.now().date()
    if day == today:
        return "Heute"
    if day == today - timedelta(days=1):
        return "Gestern"
    if day > today - timedelta(days=7):
        return "Letzte 7 Tage"
    if day > today - timedelta(days=30):
        return "Letzte 30 Tage"
    return "Älter"
