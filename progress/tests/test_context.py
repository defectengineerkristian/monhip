"""Tests für app/context.py (Kontext zählen, ältere Nachrichten zusammenfassen, „Kontext voll“) ohne Server, und dafür,
dass der Anfang des Teamwork-Prompts stabil bleibt (Teilnehmer, Aufgaben und Arbeitsstand stehen vor der neuesten
Nachricht statt im System-Prompt – sonst liest llama.cpp nach jeder Änderung den ganzen Verlauf neu):
python -m unittest discover -s progress/tests -p test_context.py"""

import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import context
import roomui


def chat(rounds: int) -> list[dict]:
    """rounds × (Frage, Antwort) mit gut 300 Zeichen je Nachricht."""
    out = []
    for i in range(rounds):
        out.append({"role": "user", "content": f"Frage {i} " + "x" * 300})
        out.append({"role": "assistant", "content": f"Antwort {i} " + "y" * 300})
    return out


def window(history, n_ctx=1000, auto=True, budget=None):
    events = []
    w = context.Window("http://127.0.0.1:1", "System", history, history, None, n_ctx, 0, 0, threading.Event(),
                       lambda kind, data: events.append((kind, data)), auto, budget)
    return w, events


class Basics(unittest.TestCase):
    def test_limit_keeps_room_for_the_answer(self):
        self.assertEqual(context.limit(10_000, 0), 8000)       # TRIGGER: 80 %
        self.assertEqual(context.limit(10_000, 4000), 7500)    # Antwort höchstens 25 % des Kontexts
        self.assertEqual(context.limit(10_000, 1000), 8000)

    def test_latest_summary_and_system_note(self):
        hist = [{"role": "user", "content": "a"}, {"role": "user", "content": "b", "_summary_before": "alt"},
                {"role": "user", "content": "c", "_summary_before": "neu"}]
        self.assertEqual(context.latest_summary(hist), (2, "neu"))
        self.assertEqual(context.latest_summary(hist[:1]), (0, None))
        self.assertEqual(context.with_summary("Sys", None), "Sys")
        self.assertTrue(context.with_summary("Sys", " neu ").startswith("Sys\n\nZusammenfassung"))
        self.assertIn("neu", context.with_summary("", "neu"))

    def test_measure_without_server_and_with_images(self):
        msgs = [{"role": "user", "content": "x" * 300},
                {"role": "user", "content": "y" * 300, "_image_files": ["a.png", "b.png"]}]
        with mock.patch.object(context, "count_tokens", side_effect=OSError):
            total, per = context.measure("http://127.0.0.1:1", msgs, None, image_tokens=500)
        self.assertEqual(per[0], 100 + context.MSG_OVERHEAD)            # ohne Server: 3 Zeichen je Token
        self.assertEqual(per[1], 100 + context.MSG_OVERHEAD + 2 * 500)  # Bilder zählen extra
        self.assertGreaterEqual(total, sum(per))


class Compress(unittest.TestCase):
    def test_full_history_is_summarized_before_sending(self):
        hist = chat(6)
        w, events = window(hist)
        old = []

        def fake_summarize(base_url, previous, part, n_ctx, stop, prompt):
            old.extend(part)
            return "ZUSAMMENFASSUNG"

        with mock.patch.object(context, "count_tokens", side_effect=OSError), \
                mock.patch.object(context, "summarize", fake_summarize):
            msgs = w.begin()
        kinds = [k for k, _ in events]
        self.assertEqual(kinds, ["compress", "compressed"])
        boundary = events[1][1][0]
        self.assertEqual(hist[boundary]["role"], "user", "geschnitten wird nur vor einer Nutzernachricht")
        self.assertEqual(old, hist[:boundary], "zusammengefasst wird genau das Ältere")
        self.assertIn("ZUSAMMENFASSUNG", msgs[0]["content"])
        self.assertEqual(msgs[1:], hist[boundary:])
        self.assertEqual(msgs[-1], hist[-1], "die neueste Nachricht geht immer vollständig mit")

    def test_short_history_or_switched_off_stays_complete(self):
        for hist, auto in ((chat(1), True), (chat(6), False)):
            w, events = window(hist, auto=auto)
            with mock.patch.object(context, "count_tokens", side_effect=OSError), \
                    mock.patch.object(context, "summarize", side_effect=AssertionError("nicht zusammenfassen")):
                msgs = w.begin()
            self.assertEqual(events, [])
            self.assertEqual(msgs[1:], hist)

    def test_failed_summary_drops_old_messages_with_a_note(self):
        w, events = window(chat(6))
        with mock.patch.object(context, "count_tokens", side_effect=OSError), \
                mock.patch.object(context, "summarize", side_effect=RuntimeError("kaputt")):
            msgs = w.begin()
        self.assertIn(context.FALLBACK, msgs[0]["content"])
        self.assertIn("info", [k for k, _ in events])

    def test_compress_now_keeps_only_the_current_question(self):
        hist = chat(3) + [{"role": "user", "content": "Mach ein Bild"}]
        w, events = window(hist, n_ctx=100_000)
        with mock.patch.object(context, "summarize", return_value="S"):
            self.assertTrue(w.compress_now())
        self.assertEqual(w.start, len(hist) - 1)
        self.assertEqual(w.plain()[1:], hist[-1:])
        w2, _ = window(hist[-1:])
        self.assertFalse(w2.compress_now(), "nichts davor – nichts zu tun")

    def test_overflow_without_older_rounds_shortens_the_newest_tool_result(self):
        hist = [{"role": "user", "content": "Lies die Datei"}]
        w, events = window(hist, n_ctx=1000)
        msgs = w.plain() + [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "1", "type": "function",
                                                               "function": {"name": "read_file", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "1", "content": "z" * 10_000}]
        err = SimpleNamespace(n_ctx=1000, n_prompt=4000)
        send = w.prepare(msgs)
        again = w.overflow(msgs, send, err)
        self.assertIsNotNone(again)
        self.assertLess(len(again[-1]["content"]), 10_000)
        self.assertEqual([k for k, _ in events], ["context_full"])


class RoomPrompt(unittest.TestCase):
    """Teamwork: Was sich im Raum laufend ändert, steht vor der neuesten Nachricht – der System-Prompt bleibt gleich."""

    def make_mode(self):
        mode = object.__new__(roomui.RoomMode)
        mode.client = SimpleNamespace(profile={"name": "Kim", "ai": "Kim-KI"})  # RoomMode.me
        mode.info = {"room": "Projekt", "is_host": True}
        mode.main = {"text": "Webseite bauen"}
        mode.members = {"1": {"name": "Kim", "ai": "Kim-KI", "ai_ready": True, "model": "Qwen", "online": True},
                        "2": {"name": "Alex", "ai": "Alex-KI", "ai_ready": False, "online": True}}
        mode.tasks = [{"nr": 1, "text": "Startseite", "status": "offen"}]
        mode.notes = ""
        mode.app = SimpleNamespace(sys_text=SimpleNamespace(get=lambda *a: "Eigene Regeln\n"))
        return mode

    def test_system_prompt_does_not_change_with_members_tasks_and_notes(self):
        mode = self.make_mode()
        before = mode._system_prompt(None)
        self.assertIn("Webseite bauen", before, "der Hauptauftrag bleibt im System-Prompt (ändert sich selten)")
        mode.members["2"].update(ai_ready=True, model="Gemma", status="schreibt Texte", online=False)
        mode.tasks.append({"nr": 2, "text": "Impressum", "status": "in Arbeit", "owner": "Alex-KI"})
        mode.notes = "Startseite fast fertig"
        self.assertEqual(mode._system_prompt(None), before)
        for text in ("Gemma", "Impressum", "fast fertig", "Alex"):
            self.assertNotIn(text, before)

    def test_state_goes_in_front_of_the_newest_message_only(self):
        mode = self.make_mode()
        mode.notes = "Logo fehlt noch"
        hist = [{"role": "user", "content": "[Alex]: Hallo", "_ids": ["a"]},
                {"role": "assistant", "content": "Hallo!", "_ids": ["b"]},
                {"role": "user", "content": "[Alex]: @Kim-KI Wie weit bist du?", "_ids": ["c"]}]
        out = mode._with_state(hist)
        self.assertEqual(len(out), len(hist), "gleich viele Nachrichten (context.Window rechnet mit der letzten)")
        self.assertEqual(out[:2], hist[:2])
        last = out[-1]["content"]
        self.assertTrue(last.startswith("[Stand im Raum"))
        self.assertTrue(last.endswith("[Alex]: @Kim-KI Wie weit bist du?"))
        for text in ("Alex (Mensch)", "kein Modell geladen", "#1 [", "Startseite", "Logo fehlt noch"):
            self.assertIn(text, last)
        self.assertEqual(out[-1]["_ids"], ["c"])
        self.assertEqual(hist[-1]["content"], "[Alex]: @Kim-KI Wie weit bist du?", "der Verlauf selbst bleibt gleich")
        self.assertEqual(mode._with_state(hist[:2]), hist[:2], "endet mit der eigenen Antwort: nichts einfügen")
        self.assertEqual(mode._with_state([]), [])


if __name__ == "__main__":
    unittest.main()
