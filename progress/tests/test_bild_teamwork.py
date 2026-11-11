"""Tests für Bilder im Teamwork ohne echte Modelle: Werkzeuge bild_erzeugen/bild_bearbeiten der KI, Antwortschleife mit
wechselnder Server-Adresse, Zusammenfassen vor dem Entladen, Neuladen des Sprachmodells mit denselben Einstellungen,
der Ablauf in ImageMode.ai_image (zusammenfassen, Sprachmodell entladen, Bild, Bildmodell entladen, Sprachmodell wieder
laden – auch nach Abbruch) und das Finden geteilter Bilder im Raum:
python -m unittest discover -s progress/tests -p test_bild_teamwork.py"""

import json
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import agent
import backend
import bilder
import context
import galerie
import roomui
import sdcpp


def make_agent(images="FLUX.2 [klein] 4B", answer="yes", always_ask=False):
    asked = []

    def confirm(title, text):
        asked.append(title)
        return answer

    a = agent.Agent(confirm, always_ask=always_ask, images=images)
    calls = []
    a.image_fn = lambda *args: calls.append(args) or "fertig"
    return a, calls, asked


class ImageTools(unittest.TestCase):
    def test_tools_only_with_an_image_model(self):
        names = {t["function"]["name"] for t in agent.Agent(lambda *a: "yes").tools}
        self.assertFalse({"bild_erzeugen", "bild_bearbeiten"} & names)
        a, _, _ = make_agent()
        self.assertTrue({"bild_erzeugen", "bild_bearbeiten"} <= a._allowed)
        self.assertIn("bild_erzeugen", a.system_prompt())
        self.assertIn("FLUX.2 [klein] 4B", a.system_prompt())

    def test_create_maps_format_and_limits_count(self):
        a, calls, asked = make_agent()
        out = a.execute("bild_erzeugen", json.dumps({"beschreibung": " a red fox ", "format": "Hochformat",
                                                     "anzahl": 9}))
        self.assertEqual(out, "fertig")
        self.assertEqual(calls, [("create", "a red fox", 4, "portrait", None)])
        self.assertEqual(asked, [])  # „Alles erlauben“: keine Rückfrage

    def test_edit_and_permission(self):
        a, calls, asked = make_agent(answer="no", always_ask=True)  # „Eingeschränkt“: Besitzer lehnt ab
        out = a.execute("bild_bearbeiten", json.dumps({"anweisung": "make it snow", "bild": "haus.jpg"}))
        self.assertEqual(out, "Vom Nutzer abgelehnt.")
        self.assertEqual((calls, len(asked)), ([], 1))
        a, calls, asked = make_agent(answer="yes", always_ask=True)
        a.execute("bild_bearbeiten", json.dumps({"anweisung": "make it snow"}))
        self.assertEqual(calls, [("edit", "make it snow", 1, None, "")])

    def test_errors_and_description(self):
        a, _, _ = make_agent()
        self.assertIn("leer", a.execute("bild_erzeugen", json.dumps({"beschreibung": "  "})))
        a.image_fn = None
        self.assertIn("keine laufende Antwort", a.execute("bild_erzeugen", json.dumps({"beschreibung": "x"})))
        icon, label, detail = agent.describe_call("bild_bearbeiten", json.dumps({"anweisung": "blue roof",
                                                                                  "bild": "haus.jpg"}))
        self.assertEqual((label, detail), ("Bild bearbeiten", "haus.jpg: blue roof"))


class ConversationUrl(unittest.TestCase):
    def test_base_url_is_asked_at_every_step(self):
        """Nach bild_erzeugen ist das Sprachmodell neu geladen (anderer Port) – der nächste Schritt geht dorthin."""
        url = {"base": "http://alt"}
        seen = []
        a, _, _ = make_agent()

        def image_fn(*_args):
            url["base"] = "http://neu"
            return "Bild geteilt"

        a.image_fn = image_fn

        def fake_turn(base, send, params, tools, stop, on_event):
            seen.append(base)
            if len(seen) == 1:
                return "", [{"id": "1", "function": {"name": "bild_erzeugen",
                                                     "arguments": json.dumps({"beschreibung": "a fox"})}}], ""
            return "Hier ist der Fuchs.", [], ""

        messages = [{"role": "user", "content": "Mal mir einen Fuchs"}]
        with mock.patch.object(agent, "chat_turn", side_effect=fake_turn):
            agent.run_conversation(lambda: url["base"], messages, {}, a, threading.Event(), lambda *e: None)
        self.assertEqual(seen, ["http://alt", "http://neu"])
        self.assertEqual(messages[-1]["content"], "Hier ist der Fuchs.")
        self.assertEqual(messages[-2], {"role": "tool", "tool_call_id": "1", "content": "Bild geteilt"})


class CompressNow(unittest.TestCase):
    def test_everything_before_the_current_message_is_summarized(self):
        history = [{"role": "user", "content": "[Anna]: Hallo"}, {"role": "assistant", "content": "Hallo Anna"},
                   {"role": "user", "content": "[Ben]: Wir planen ein Logo"},
                   {"role": "user", "content": "[Anna]: Mach ein Bild davon"}]
        events = []
        w = context.Window("http://x", "SYSTEM", history, history, None, 8192, 512, 0, threading.Event(),
                           lambda kind, data: events.append(kind))
        start = w.begin()
        with mock.patch.object(context, "summarize", return_value="- Anna und Ben planen ein Logo") as summ:
            self.assertTrue(w.compress_now())
        self.assertEqual(summ.call_args[0][2], history[:3])  # alles vor der aktuellen Nachricht
        self.assertEqual((w.start, events), (3, ["compress", "compressed"]))
        send = w.prepare(start + [{"role": "assistant", "content": "", "tool_calls": []}])
        self.assertIn("Anna und Ben planen ein Logo", send[0]["content"])
        self.assertEqual([m["content"] for m in send[1:]], ["[Anna]: Mach ein Bild davon", ""])
        self.assertFalse(w.compress_now())  # nichts mehr übrig

    def test_short_history_is_left_alone(self):
        history = [{"role": "user", "content": "[Anna]: Mach ein Bild"}]
        w = context.Window("http://x", "S", history, history, None, 8192, 512, 0, threading.Event(), lambda *a: None)
        with mock.patch.object(context, "summarize") as summ:
            self.assertFalse(w.compress_now())
        summ.assert_not_called()


class Restart(unittest.TestCase):
    def test_restart_uses_the_last_settings(self):
        srv = backend.LlamaServer(lambda t: None)
        with self.assertRaises(RuntimeError):
            srv.restart(threading.Event())
        srv.last = {"server": {"exe": "llama-server"}, "model": Path("m.gguf"), "ctx": 32768, "ngl": "auto",
                    "extra": "", "mmproj": Path("mmproj.gguf"), "image_tokens": 1024}
        with mock.patch.object(srv, "start") as start:
            srv.restart(threading.Event())
        args, kw = start.call_args
        self.assertEqual(args[:5], ({"exe": "llama-server"}, Path("m.gguf"), 32768, "auto", ""))
        self.assertEqual(kw, {"mmproj": Path("mmproj.gguf"), "image_tokens": 1024})


class FakeLlm:
    def __init__(self, log):
        self.log, self.model, self.running = log, Path("Qwen.gguf"), True
        self.last = {"model": self.model}

    def is_running(self):
        return self.running

    def stop(self):
        self.log.append("llm.stop")
        self.running = False

    def restart(self, cancel, last):
        self.log.append(("llm.restart", last["model"].name))
        self.running = True


class FakeImageServer:
    def __init__(self, log, fail=None):
        self.log, self.model, self.fail = log, None, fail
        self.refs = None

    def ready_for(self, key):
        return self.model == key

    def start(self, key, stop):
        self.log.append("bild.start")
        self.model = key

    def stop(self):
        self.log.append("bild.stop")
        self.model = None

    def generate(self, prompt, width, height, count, seed, stop, on_progress=None, refs=None):
        self.log.append(("bild.generate", width, height, count))
        self.refs = refs
        if self.fail:
            raise self.fail
        return [b"\x89PNG bild%d" % i for i in range(count)]


class AiImage(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.log = []
        mode = object.__new__(bilder.ImageMode)  # ohne Oberfläche: nur der Ablauf
        mode.app = SimpleNamespace(server=FakeLlm(self.log), ui=lambda *a: None, _set_status=None, _loaded=None,
                                   cfg={"image_model": "flux2-klein-4b-q8"})
        mode.server = FakeImageServer(self.log)
        mode.gallery = galerie.Gallery(self.dir / "bilder")
        mode.busy = mode._checking = False
        mode.stop_event = None
        self.mode = mode
        for patch in (mock.patch.object(sdcpp, "ready", return_value=True),
                      mock.patch.object(sdcpp, "need_vram_mib", return_value=12000)):
            patch.start()
            self.addCleanup(patch.stop)

    def compress(self):
        self.log.append("compress")
        return True

    def run_image(self, free, **kw):
        with mock.patch.object(sdcpp, "free_vram_mib", return_value=free):
            return self.mode.ai_image("a fox", (832, 1216), 2, threading.Event(), compress=self.compress,
                                      phase=lambda p: self.log.append("phase " + p), **kw)

    def test_swap_order(self):
        res = self.run_image(4000)  # zu wenig frei: tauschen
        self.assertEqual(self.log, ["compress", "phase unload", "llm.stop", "phase load", "bild.start", "phase run",
                                    ("bild.generate", 832, 1216, 2), "bild.stop", "phase reload",
                                    ("llm.restart", "Qwen.gguf")])
        self.assertEqual((res["swapped"], res["compressed"], res["reload_error"]), (True, True, None))
        self.assertEqual(len(res["items"]), 2)
        self.assertEqual(self.mode.gallery.path(res["items"][0]).read_bytes(), b"\x89PNG bild0")

    def test_no_swap_when_both_fit(self):
        res = self.run_image(15000)
        self.assertNotIn("llm.stop", self.log)
        self.assertNotIn("compress", self.log)
        self.assertEqual(self.mode.server.model, "flux2-klein-4b-q8")  # bleibt geladen
        self.assertFalse(res["swapped"])

    def test_language_model_comes_back_after_a_cancel(self):
        self.mode.server.fail = sdcpp.Cancelled("Abgebrochen.")
        with self.assertRaises(sdcpp.Cancelled):
            self.run_image(4000)
        self.assertEqual(self.log[-3:], ["bild.stop", "phase reload", ("llm.restart", "Qwen.gguf")])

    def test_edit_uses_the_reference_and_its_aspect(self):
        def fit(src, target, w, h):
            Path(target).write_bytes(b"\x89PNG vorlage")
            return 1600, 900

        with mock.patch.object(bilder.images, "fit", side_effect=fit), \
                mock.patch.object(bilder.images, "TEMP_DIR", self.dir):
            res = self.mode.ai_image("blue roof", None, 1, threading.Event(), ref=self.dir / "haus.jpg",
                                     source="haus.jpg")
        self.assertEqual(self.mode.server.refs, [b"\x89PNG vorlage"])
        self.assertIn(("bild.generate", 1360, 768, 1), self.log)
        self.assertEqual(res["items"][0]["source"], "haus.jpg")

    def test_not_set_up_or_busy(self):
        with mock.patch.object(sdcpp, "ready", return_value=False), self.assertRaises(RuntimeError):
            self.run_image(4000)
        self.mode.busy = True
        with self.assertRaisesRegex(RuntimeError, "gerade schon"):
            self.run_image(4000)
        self.assertEqual(self.log, [])


class RoomImages(unittest.TestCase):
    def test_find_shared_images(self):
        one, two, three = "1" * 24, "2" * 24, "3" * 24  # Datei-IDs, wie sie der Gastgeber vergibt
        mode = object.__new__(roomui.RoomMode)
        mode.order = ["a", "b", "c", "d"]
        mode.messages = {
            "a": {"files": [{"name": "Haus.JPG", "id": one, "image": True}]},
            "b": {"files": [{"name": "plan.pdf", "id": two, "image": False}]},
            "c": {"files": [{"name": "logo-entwurf.png", "id": three, "image": True}]},
            # von einem fremden Gastgeber: die ID würde zu einem Pfad außerhalb des Zwischenspeichers
            "d": {"files": [{"name": "falle.png", "id": "../../Startup/x", "image": True}]},
        }
        self.assertEqual([f["id"] for f in mode._room_images()], [three, one])
        self.assertEqual(mode._room_image("")["id"], three)      # ohne Namen: das zuletzt (gültig) geteilte
        self.assertEqual(mode._room_image("haus.jpg")["id"], one)
        self.assertEqual(mode._room_image("logo")["id"], three)  # Teil des Namens
        self.assertIsNone(mode._room_image("plan.pdf"))
        self.assertIsNone(mode._room_image("falle.png"))


if __name__ == "__main__":
    unittest.main()
