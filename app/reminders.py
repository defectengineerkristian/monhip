"""Erinnerungen des Modells (Werkzeuge set_reminder/cancel_reminder), gespeichert in erinnerungen.json.
Die App fragt regelmäßig due() ab und meldet fällige per notify() als Windows-Benachrichtigung.
"""

import json
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from xml.sax.saxutils import escape

from images import powershell

FILE = Path(__file__).resolve().parent.parent / "erinnerungen.json"
_lock = threading.Lock()
_FORMATS = ("%d.%m.%Y %H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%d.%m. %H:%M", "%H:%M")
# AppID von Windows PowerShell: damit dürfen Benachrichtigungen ohne eigene App-Registrierung erscheinen
_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def load() -> list[dict]:
    """Offene Erinnerungen [{id, due (JJJJ-MM-TT HH:MM), text}], früheste zuerst."""
    try:
        items = json.loads(FILE.read_text(encoding="utf-8"))
        items = [r for r in items if isinstance(r, dict) and {"id", "due", "text"} <= r.keys()]
    except (OSError, ValueError, TypeError):
        items = []
    return sorted(items, key=lambda r: r["due"])


def _save(items: list[dict]):
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(FILE)


def parse_time(at: str | None, in_minutes, now: datetime | None = None) -> datetime:
    """Zeitpunkt aus „in X Minuten“ oder einer Uhrzeit/einem Datum (z. B. 18:30, 15.10.2026 08:00)."""
    now = now or datetime.now()
    if in_minutes not in (None, ""):
        minutes = float(in_minutes)
        if minutes <= 0:
            raise ValueError("in_minutes muss größer als 0 sein.")
        return now + timedelta(minutes=minutes)
    raw = re.sub(r"\s*uhr\s*$", "", str(at or "").strip(), flags=re.I)
    if not raw:
        raise ValueError("Bitte in_minutes oder at angeben.")
    for fmt in _FORMATS:
        try:
            t = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if fmt == "%H:%M":  # nur Uhrzeit: heute, sonst morgen
            t = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
            return t if t > now else t + timedelta(days=1)
        if fmt == "%d.%m. %H:%M":
            t = t.replace(year=now.year)
            return t if t > now else t.replace(year=now.year + 1)
        return t
    raise ValueError(f"Zeit „{at}“ nicht erkannt – z. B. 18:30 oder 15.10.2026 08:00 angeben.")


def add(text: str, due: datetime) -> dict:
    text = " ".join(str(text).split())
    if not text:
        raise ValueError("Leerer Erinnerungstext.")
    if due <= datetime.now():
        raise ValueError("Der Zeitpunkt liegt in der Vergangenheit.")
    if due > datetime.now() + timedelta(days=366):
        raise ValueError("Höchstens ein Jahr im Voraus.")
    with _lock:
        items = load()
        item = {"id": max((r["id"] for r in items), default=0) + 1, "due": due.strftime("%Y-%m-%d %H:%M"),
                "text": text[:300]}
        _save(items + [item])
        return item


def remove(item_id: int) -> bool:
    with _lock:
        items = load()
        rest = [r for r in items if r["id"] != item_id]
        if len(rest) == len(items):
            return False
        _save(rest)
        return True


def due(now: datetime | None = None) -> list[dict]:
    """Fällige Erinnerungen herausnehmen (und aus der Datei entfernen)."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d %H:%M")
    with _lock:
        items = load()
        ready = [r for r in items if r["due"] <= stamp]
        if ready:
            _save([r for r in items if r["due"] > stamp])
        return ready


def describe(item: dict) -> str:
    t = datetime.strptime(item["due"], "%Y-%m-%d %H:%M")
    day = {0: "Mo", 1: "Di", 2: "Mi", 3: "Do", 4: "Fr", 5: "Sa", 6: "So"}[t.weekday()]
    return f"{day}, {t:%d.%m.%Y %H:%M} – {item['text']}"


def prompt_block() -> str:
    items = load()
    if not items:
        return "Es gibt keine offenen Erinnerungen."
    return "Offene Erinnerungen:\n" + "\n".join(f"- [{r['id']}] {describe(r)}" for r in items[:30])


def notify(title: str, text: str) -> bool:
    """Windows-Benachrichtigung (unten rechts, mit Erinnerungston). Blockiert ~1 s – im Thread aufrufen."""
    xml = (f"<toast scenario='reminder'><visual><binding template='ToastGeneric'><text>{escape(title)}</text>"
           f"<text>{escape(text)}</text></binding></visual>"
           "<actions><action content='OK' arguments='ok' activationType='system'/></actions>"
           "<audio src='ms-winsoundevent:Notification.Reminder'/></toast>")
    out = powershell(f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('{xml.replace("'", "''")}')
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_APP_ID}').Show(
    [Windows.UI.Notifications.ToastNotification]::new($xml))
'ok'""")
    return out.endswith("ok")
