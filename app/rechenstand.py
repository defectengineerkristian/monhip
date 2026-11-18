"""Rechenstand langer Chats auf der Platte: Ein Chat lässt sich nach einem Neustart oder Modellwechsel fortsetzen,
ohne dass das Modell den ganzen Verlauf neu einlesen muss.

llama-server legt den Stand eines Platzes (Slot) mit --slot-save-path als Datei ab (POST /slots/0?action=save) und
lädt ihn wieder (action=restore) – samt der Zwischenstände („context checkpoints“), die Modelle mit gemischter
Aufmerksamkeit (z. B. Qwen3.6-35B-A3B) brauchen. Gemessen mit Qwen3.6-35B-A3B und einem Chat mit 19 600 Tokens:
Folgefrage nach einem Neustart 47 s ohne, 7 s mit wiederhergestelltem Stand; Speichern 0,5 s, Laden 0,4 s, Datei
635 MB.

Der Chat im Hauptfenster läuft deshalb fest auf Platz SLOT (Anfrage-Parameter "id_slot"). Gespeichert wird beim
Verlassen eines langen Chats (anderer Chat, Modell entladen oder wechseln, Programm beenden), wiederhergestellt beim
Öffnen bzw. nach dem Laden des Modells – nur mit demselben Modell und Kontext. Je Chat <id>.bin (schreibt der Server)
und <id>.json (womit gespeichert). Zusammen höchstens MAX_BYTES; die ältesten Stände fallen zuerst weg.
Alles hier blockiert (Netz, Platte) – im Hintergrund aufrufen."""

import json
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import plattform

DIR = plattform.DATA_DIR / "rechenstand"
SLOT = 0
MIN_TOKENS = 4000          # kürzere Chats liest das Modell auch so in wenigen Sekunden neu ein
MAX_BYTES = 30 * 2 ** 30   # alle gespeicherten Stände zusammen
_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def files(chat_id: str) -> tuple[Path, Path]:
    return DIR / f"{chat_id}.bin", DIR / f"{chat_id}.json"


def signature(last: dict | None) -> dict:
    """Womit der Server gestartet wurde – ein Stand passt nur zu genau diesem Modell und Kontext."""
    if not last:
        return {}
    return {"model": str(last.get("model") or ""), "ctx": int(last.get("ctx") or 0),
            "mmproj": str(last.get("mmproj") or ""), "extra": str(last.get("extra") or "")}


def _slot_action(base_url: str, auth_headers: dict, action: str, chat_id: str, timeout: float = 120) -> dict:
    import backend  # erst hier: backend importiert viel, die Tests brauchen es nicht
    req = urllib.request.Request(f"{base_url}/slots/{SLOT}?action={action}",
                                 data=json.dumps({"filename": f"{chat_id}.bin"}).encode("utf-8"), method="POST",
                                 headers={**auth_headers, "Content-Type": "application/json"})
    with backend._local.open(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def save(server, chat_id: str, tokens: int) -> int:
    """Stand von Platz SLOT als Rechenstand des Chats speichern, wenn er lang genug ist. tokens: so lang ist der Chat
    laut Anzeige – hält der Platz deutlich weniger (z. B. inzwischen eine andere Anfrage), wird nichts behalten.
    → gespeicherte Tokens (0 = nichts gespeichert)."""
    import backend
    if not _ID.match(chat_id or "") or tokens < MIN_TOKENS or not server.is_running() or not server.last:
        return 0
    DIR.mkdir(parents=True, exist_ok=True)
    try:
        res = _slot_action(server.base_url, backend._auth(), "save", chat_id)
    except (OSError, ValueError, urllib.error.URLError):
        erase(chat_id)
        return 0
    n = int(res.get("n_saved") or 0)
    if n < tokens // 2:  # auf dem Platz lag nicht (mehr) dieser Chat
        erase(chat_id)
        return 0
    files(chat_id)[1].write_text(json.dumps({**signature(server.last), "tokens": n,
                                             "saved": datetime.now().isoformat(timespec="seconds")}),
                                 encoding="utf-8")
    prune()
    return n


def restore(server, chat_id: str) -> int:
    """Gespeicherten Stand des Chats auf Platz SLOT laden – nur, wenn er zum laufenden Modell passt.
    → wiederhergestellte Tokens (0 = keiner da, passt nicht oder Fehler; ein unlesbarer Stand wird gelöscht)."""
    import backend
    if not _ID.match(chat_id or "") or not server.is_running() or not server.last:
        return 0
    data, meta = files(chat_id)
    if not data.is_file() or not meta.is_file():
        return 0
    try:
        info = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        erase(chat_id)
        return 0
    if {k: info.get(k) for k in signature(server.last)} != signature(server.last):
        return 0  # anderes Modell oder anderer Kontext – bleibt liegen, falls es wieder geladen wird
    try:
        res = _slot_action(server.base_url, backend._auth(), "restore", chat_id)
    except urllib.error.HTTPError:
        erase(chat_id)  # z. B. von einer anderen llama.cpp-Fassung – nicht mehr lesbar
        return 0
    except (OSError, ValueError, urllib.error.URLError):
        return 0
    data.touch()  # zuletzt benutzt: fällt beim Aufräumen später weg
    return int(res.get("n_restored") or 0)


def erase(chat_id: str):
    if _ID.match(chat_id or ""):
        for f in files(chat_id):
            f.unlink(missing_ok=True)


def prune(max_bytes: int = MAX_BYTES):
    """Höchstens max_bytes behalten (die zuletzt benutzten); halbe Paare (nur .bin oder nur .json) wegräumen."""
    if not DIR.is_dir():
        return
    states = []
    for data in DIR.glob("*.bin"):
        meta = data.with_suffix(".json")
        if not meta.is_file():
            data.unlink(missing_ok=True)
            continue
        try:
            st = data.stat()
        except OSError:
            continue
        states.append((st.st_mtime, st.st_size, data.stem))
    for meta in DIR.glob("*.json"):
        if not meta.with_suffix(".bin").is_file():
            meta.unlink(missing_ok=True)
    total = sum(size for _, size, _ in states)
    for _, size, chat_id in sorted(states):
        if total <= max_bytes:
            break
        erase(chat_id)
        total -= size
