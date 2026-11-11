"""Arbeitsplan (Werkzeug plan_setzen): Das Modell schreibt die Schritte einer längeren Aufgabe auf und hakt sie ab
– so verliert auch ein kleines Modell über viele Werkzeug-Schritte nicht den Faden. Gespeichert wird nichts: Der
Plan steht im Verlauf (agent.compact() lässt das neueste Werkzeug-Ergebnis immer vollständig)."""

import json

MAX_STEPS, MAX_CHARS = 20, 200
MARKS = {"offen": "☐", "in_arbeit": "▶", "erledigt": "☑"}
ALIASES = {"open": "offen", "pending": "offen", "todo": "offen", "in_progress": "in_arbeit", "in arbeit": "in_arbeit",
           "in-arbeit": "in_arbeit", "aktiv": "in_arbeit", "läuft": "in_arbeit", "done": "erledigt",
           "completed": "erledigt", "fertig": "erledigt", "erledigt": "erledigt"}


class PlanError(Exception):
    """Fehler, den das Modell als verständlichen Satz bekommt (wie agent.ToolError)."""


def normalize(schritte) -> list[dict]:
    """[{"text", "status"}] aus dem, was das Modell schickt – auch als JSON-Text oder als bloße Liste von Texten."""
    if isinstance(schritte, str):
        try:
            schritte = json.loads(schritte)
        except ValueError:
            schritte = [ln.strip(" -*\t") for ln in schritte.splitlines() if ln.strip(" -*\t")]
    if not isinstance(schritte, list) or not schritte:
        raise PlanError("schritte muss eine Liste mit mindestens einem Schritt sein.")
    if len(schritte) > MAX_STEPS:
        raise PlanError(f"Höchstens {MAX_STEPS} Schritte – fasse kleinere Schritte zusammen.")
    steps = []
    for s in schritte:
        text, status = (s.get("text"), s.get("status")) if isinstance(s, dict) else (s, "offen")
        text = " ".join(str(text or "").split())[:MAX_CHARS]
        status = str(status or "offen").strip().lower()
        if not text:
            raise PlanError("Jeder Schritt braucht einen Text.")
        if status not in MARKS:
            status = ALIASES.get(status)
            if not status:
                raise PlanError(f"Unbekannter Status bei „{text}“ – erlaubt: offen, in_arbeit, erledigt.")
        steps.append({"text": text, "status": status})
    if sum(s["status"] == "in_arbeit" for s in steps) > 1:
        raise PlanError("Nur ein Schritt darf in_arbeit sein – die anderen auf offen oder erledigt setzen.")
    return steps


def render(steps: list[dict]) -> str:
    done = sum(s["status"] == "erledigt" for s in steps)
    lines = [f"Arbeitsplan ({done}/{len(steps)} erledigt):"]
    lines += [f"{MARKS[s['status']]} {i}. {s['text']}" for i, s in enumerate(steps, 1)]
    nxt = next((s for s in steps if s["status"] == "in_arbeit"), None) or next(
        (s for s in steps if s["status"] == "offen"), None)
    lines.append(f"Jetzt: {nxt['text']}" if nxt else "Alles erledigt – fasse dem Nutzer das Ergebnis zusammen.")
    return "\n".join(lines)


def current(steps) -> str:
    """Der Schritt in Arbeit (für die Kopfzeile im Chat)."""
    try:
        steps = normalize(steps)
    except PlanError:
        return ""
    return next((s["text"] for s in steps if s["status"] == "in_arbeit"), "")
