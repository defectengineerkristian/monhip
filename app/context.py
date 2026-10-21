"""Kontext im Blick: Verlauf in Tokens zählen und ältere Teile zusammenfassen, bevor er voll ist.

Die Zusammenfassung hängt an der ersten Nachricht, die danach wieder vollständig mitgeht (`_summary_before`,
`_summary_count`). Ans Modell geht dann System-Prompt + Zusammenfassung + Verlauf ab dieser Nachricht; gespeichert
und angezeigt wird weiter alles. Weil sie an der Nachricht hängt, stimmt sie beim Bearbeiten und bei Fassungen von
selbst (wer eine ältere Nachricht bearbeitet, hat wieder den vollen Verlauf).
"""

import json
import re

from agent import cap_tools, compact
from backend import chat_turn, count_tokens

TRIGGER = 0.8          # ab so viel belegtem Kontext wird vor dem Senden zusammengefasst …
ANSWER_SHARE = 0.25    # … oder früher, damit Platz für die Antwort bleibt (max_tokens, höchstens 25 %)
TARGET = 0.5           # danach soll der Verlauf samt System-Prompt etwa so viel vom Grenzwert belegen
SUMMARY_TOKENS = 1200  # höchstens so lang wird die Zusammenfassung (bei kleinem Kontext 15 % davon)
MSG_OVERHEAD = 6       # Tokens der Chat-Vorlage je Nachricht (Rolle, Trennzeichen)
LINE_CHARS = 3000      # je Nachricht geht höchstens so viel Text in die Zusammenfassung ein

SUMMARY_PROMPT = (
    "Du fasst den bisherigen Verlauf eines Chats zwischen einem Nutzer und einem KI-Assistenten zusammen, damit "
    "der Assistent ohne die alten Nachrichten nahtlos weitermachen kann. Schreibe auf Deutsch, sachlich und knapp "
    "in Stichpunkten. Behalte alles, was später noch wichtig sein kann: Ziele, Wünsche und Vorlieben des Nutzers, "
    "Fakten, Zahlen, Namen, Entscheidungen und Ergebnisse, Dateinamen und Pfade, Code-Stände in Kurzform, offene "
    "Fragen und Aufgaben. Lass Höflichkeiten, Wiederholungen und Nebensächliches weg. Höchstens etwa 400 Wörter. "
    "Antworte nur mit der Zusammenfassung.")
SYSTEM_NOTE = ("Zusammenfassung des früheren Teils dieser Unterhaltung – die älteren Nachrichten wurden aus "
               "Platzgründen zusammengefasst. Fehlen dir Einzelheiten daraus, frag kurz nach.\n\n{summary}")
FALLBACK = "(Ältere Nachrichten wurden weggelassen, weil der Kontext voll war; eine Zusammenfassung war nicht möglich.)"
FULL_NOTE = "Kontextfenster an kritischer Grenze. Konversation wird nun komprimiert, um den Chat fortführen zu können."
ROLES = {"user": "Nutzer", "assistant": "Assistent", "tool": "Werkzeug-Ergebnis"}


def limit(n_ctx: int, max_tokens: int) -> int:
    """Ab so vielen Tokens im Verlauf wird zusammengefasst (Platz für die Antwort eingerechnet)."""
    reserve = min(max(0, max_tokens or 0), int(n_ctx * ANSWER_SHARE))
    return int(min(n_ctx * TRIGGER, n_ctx - reserve))


def latest_summary(history: list) -> tuple[int, str | None]:
    """(Index der Nachricht mit der neuesten Zusammenfassung, Text) – (0, None), wenn es keine gibt."""
    for i in range(len(history) - 1, -1, -1):
        if history[i].get("_summary_before"):
            return i, history[i]["_summary_before"]
    return 0, None


def with_summary(system: str, summary: str | None) -> str:
    if not summary:
        return system
    note = SYSTEM_NOTE.format(summary=summary.strip())
    return f"{system}\n\n{note}" if system else note


def _text(m: dict) -> str:
    """Alles, was von einer Nachricht als Text ans Modell geht."""
    parts = [m.get("content") if isinstance(m.get("content"), str) else ""]
    for c in m.get("tool_calls") or []:
        fn = c.get("function") or {}
        parts.append((fn.get("name") or "") + " " + (fn.get("arguments") or ""))
    return "\n".join(p for p in parts if p)


def measure(base_url: str, messages: list, tools: list | None = None, image_tokens: int = 0) -> tuple[int, list[int]]:
    """(Tokens insgesamt, Tokens je Nachricht). Gezählt wird einmal mit dem Tokenizer des Servers; die Anteile
    je Nachricht werden daraus hochgerechnet. Ohne Server: grob 3 Zeichen je Token."""
    texts = [_text(m) for m in messages]
    blob = "\n".join(texts) + ("\n" + json.dumps(tools, ensure_ascii=False) if tools else "")
    try:
        exact = count_tokens(base_url, blob) if blob else 0
    except (OSError, ValueError):
        exact = len(blob) // 3
    ratio = exact / max(1, len(blob))
    per = [round(len(t) * ratio) + MSG_OVERHEAD + len(m.get("_image_files") or []) * image_tokens
           for t, m in zip(texts, messages)]
    tools_part = max(0, exact - round(sum(len(t) for t in texts) * ratio))
    return sum(per) + tools_part + 20, per


def _line(m: dict) -> str:
    """Eine Nachricht als Zeile für die Zusammenfassung (lange gekürzt, Bilder nur erwähnt)."""
    text = _text(m).strip()
    if len(text) > LINE_CHARS:
        text = text[:2000].rstrip() + "\n…\n" + text[-800:].lstrip()
    if m.get("_image_files"):
        text += f"\n[{len(m['_image_files'])} Bild(er)]"
    who = ROLES.get(m.get("role"), m.get("role") or "?")
    if m.get("role") == "assistant" and m.get("tool_calls"):
        who = "Assistent (ruft Werkzeuge auf)"
    return f"[{who}]: {text}"


def _summarize_once(base_url: str, previous: str | None, part: str, max_out: int, stop) -> str:
    user = ((f"<bisherige_zusammenfassung>\n{previous.strip()}\n</bisherige_zusammenfassung>\n\n" if previous else "")
            + f"<verlauf>\n{part.strip()}\n</verlauf>\n\n"
            + ("Fasse die bisherige Zusammenfassung und den Verlauf zu einer neuen Zusammenfassung zusammen."
               if previous else "Fasse diesen Verlauf zusammen."))
    params = {"max_tokens": max_out, "temperature": 0.2, "chat_template_kwargs": {"enable_thinking": False}}
    text, _calls, _reasoning = chat_turn(base_url, [{"role": "system", "content": SUMMARY_PROMPT},
                                                    {"role": "user", "content": user}],
                                         params, None, stop, lambda kind, data: None)
    text = re.sub(r"(?s)<think>.*?(</think>|$)", "", text).strip()
    if not text and not stop.is_set():
        raise RuntimeError("das Modell hat keine Zusammenfassung geliefert")
    return text


def summarize(base_url: str, previous: str | None, old: list, n_ctx: int, stop) -> str | None:
    """Zusammenfassung von previous + old. Passt old nicht in einen Durchgang, wird stückweise weitergeschrieben
    (jedes Stück mit der Zusammenfassung bis dahin). None = abgebrochen."""
    max_out = max(200, min(SUMMARY_TOKENS, int(n_ctx * 0.15)))
    piece_chars = max(3000, int(n_ctx * 0.35 * 3))  # Verlauf je Durchgang: ~35 % des Kontexts
    pieces, cur = [], ""
    for line in (_line(m) for m in old):
        if cur and len(cur) + len(line) > piece_chars:
            pieces.append(cur)
            cur = ""
        cur += line + "\n\n"
    if cur:
        pieces.append(cur)
    summary = previous
    for part in pieces:
        if stop.is_set():
            return None
        summary = _summarize_once(base_url, summary, part, max_out, stop)
    return None if stop.is_set() else summary


class Window:
    """Was vom Verlauf ans Modell geht – für eine Antwort (eine Nutzernachricht, ggf. mit vielen Werkzeugschritten).
    begin(): vor dem Senden; liegt der Verlauf über limit(), wird der ältere Teil zusammengefasst.
    prepare(messages): vor jedem Schritt der Antwort (System + Zusammenfassung + Verlauf + neue Schritte, gekürzt).
    overflow(...): meldet der Server mitten in der Antwort „Kontext voll“, werden ältere Runden zusammengefasst bzw.
    – wenn es keine gibt – die Werkzeug-Ergebnisse stärker gekürzt (gilt dann für alle weiteren Schritte), und
    run_conversation wiederholt den Schritt. api_msgs[i] gehört zu history[i].
    report(art, daten): "compress" (fängt an), "compressed" (Index der ersten vollständigen Nachricht, Text,
    Anzahl), "context_full" (n_prompt, n_ctx – einmal je Antwort), "info" (Hinweis)."""

    def __init__(self, base_url: str, system: str, history: list, api_msgs: list, tools: list | None,
                 n_ctx: int | None, max_tokens: int, image_tokens: int, stop, report, auto: bool = True,
                 budget: int | None = None):
        self.base_url, self.system, self.history, self.api_msgs = base_url, system, history, api_msgs
        self.tools, self.n_ctx, self.max_tokens, self.image_tokens = tools, n_ctx, max_tokens, image_tokens
        self.stop, self.report, self.auto, self.budget = stop, report, auto, budget
        self.start, self.summary = latest_summary(history)
        self.head = 0             # so viele Nachrichten am Anfang von messages stammen aus dem Verlauf (samt System)
        self.newest_cap = None    # nach „Kontext voll“: höchstens so viele Zeichen für das neueste Werkzeug-Ergebnis
        self.warned = False

    def _head(self) -> list:
        return [{"role": "system", "content": with_summary(self.system, self.summary)}] + self.api_msgs[self.start:]

    def plain(self) -> list:
        """Startliste ohne Prüfung (falls begin() scheitert)."""
        msgs = self._head()
        self.head = len(msgs)
        return msgs

    def begin(self) -> list:
        """Startliste für run_conversation (gespeichert wird, was danach dazukommt). Bei Abbruch (stop) prüft der
        Aufrufer stop."""
        msgs = self._head()
        if self.auto and self.n_ctx and len(self.history) - self.start >= 2:
            total, per = measure(self.base_url, msgs, self.tools, self.image_tokens)
            lim = limit(self.n_ctx, self.max_tokens)
            if total > lim:
                boundary = self._boundary(msgs, total, per, lim)
                if boundary and self._compress(boundary):
                    msgs = self._head()
        self.head = len(msgs)
        return msgs

    def _boundary(self, msgs: list, total: int, per: list, lim: int) -> int | None:
        """Ab welcher Nachricht bleibt alles vollständig? Von hinten so viele, wie neben System, Werkzeugen und
        Zusammenfassung passen – mindestens die letzte Nutzernachricht. Geschnitten wird nur vor einer
        Nutzernachricht (sonst würden Werkzeug-Aufruf und -Ergebnis getrennt)."""
        fixed = total - sum(per[1:]) - per[0] + round(len(self.system) * (per[0] / max(1, len(msgs[0]["content"]))))
        keep_budget = int(lim * TARGET) - fixed - min(SUMMARY_TOKENS, int(self.n_ctx * 0.15))
        boundary, kept = None, 0
        for i in range(len(self.history) - 1, self.start, -1):
            kept += per[1 + i - self.start]
            if self.history[i].get("role") == "user":
                if boundary is None or kept <= keep_budget:
                    boundary = i
                if kept > keep_budget:
                    break
        return boundary if boundary and boundary > self.start else None

    def _compress(self, boundary: int) -> bool:
        """history[start:boundary] (mit der bisherigen Zusammenfassung) zusammenfassen. False = abgebrochen."""
        self.report("compress", None)
        try:
            new = summarize(self.base_url, self.summary, self.api_msgs[self.start:boundary], self.n_ctx or 4096,
                            self.stop)
        except Exception as e:  # Zusammenfassen nicht möglich → die ältesten Nachrichten fallen weg
            self.report("info", f"Zusammenfassen nicht möglich ({e}) – die älteren Nachrichten werden weggelassen.")
            new = (self.summary.strip() + "\n\n" if self.summary else "") + FALLBACK
        if new is None:
            return False
        self.start, self.summary = boundary, new
        self.report("compressed", (boundary, new, boundary))
        return True

    def prepare(self, messages: list) -> list:
        send = self._head() + messages[self.head:]
        if self.budget:
            send = compact(send, self.budget)
        if self.newest_cap:
            send = cap_tools(send, self.newest_cap)
        return send

    def overflow(self, messages: list, send: list, err) -> list | None:
        if self.stop.is_set():
            return None
        current = len(self.history) - 1  # die Nutzernachricht dieser Antwort
        if self.auto and current > self.start:  # ältere Runden vorhanden → zusammenfassen
            self._warn(err)
            return self.prepare(messages) if self._compress(current) else None
        # Sonst die Werkzeug-Ergebnisse dieser Antwort stärker kürzen (ältere auf 300 Zeichen, das neueste so weit
        # wie nötig – geschätzt aus den Zahlen des Servers, mit Reserve bis 70 % des Kontexts)
        n_ctx = err.n_ctx or self.n_ctx or 4096
        n_prompt = err.n_prompt or int(n_ctx * 1.2)
        chars = sum(len(_text(m)) for m in send)
        need = (n_prompt - int(n_ctx * 0.7)) * chars / max(1, n_prompt)
        newest = next((len(m.get("content") or "") for m in reversed(send) if m.get("role") == "tool"), 0)
        saved = chars - sum(len(_text(m)) for m in cap_tools(send, None))
        cap = max(800, int(newest - max(0, need - saved)))
        if self.newest_cap:
            cap = max(800, min(cap, self.newest_cap // 2))
        if not newest or (cap >= self.newest_cap if self.newest_cap else cap >= newest and saved <= 0):
            return None  # nichts mehr zu kürzen – dann bleibt es bei der Meldung „Kontextfenster voll“
        self._warn(err)
        self.newest_cap = cap
        return self.prepare(messages)

    def _warn(self, err):
        """Hinweis „Kontextfenster an kritischer Grenze …“ – einmal je Antwort und nur, wenn komprimiert wird."""
        if not self.warned:
            self.warned = True
            self.report("context_full", (err.n_prompt, err.n_ctx))
