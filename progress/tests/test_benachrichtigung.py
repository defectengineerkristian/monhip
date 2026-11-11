"""Benachrichtigung, wenn etwas fertig ist: nur, solange Monhip im Hintergrund liegt, nicht für Kurzes, abschaltbar –
und als gewöhnliche Benachrichtigung statt als Erinnerung (die bleibt stehen, bis man sie wegklickt). Prüft die
Windows- und die Linux-Fassung von reminders.notify und die Stellen, an denen die App meldet (Chat-Antwort, Bild,
Auswertung, Bestätigung): python -m unittest discover -s progress/tests -p test_benachrichtigung.py"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import plattform  # noqa: E402
import reminders  # noqa: E402


class NotifyKinds(unittest.TestCase):
    def test_linux_reminder_stays_done_message_does_not(self):
        calls = []

        def run(args, **_kw):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0)

        with mock.patch.object(plattform, "WINDOWS", False), \
                mock.patch.object(plattform, "which", return_value="/usr/bin/notify-send"), \
                mock.patch.object(reminders.subprocess, "run", side_effect=run):
            self.assertTrue(reminders.notify("Erinnerung", "Ofen"))
            self.assertTrue(reminders.notify("Antwort fertig", "Mein Chat", reminder=False))
        self.assertIn("--urgency=critical", calls[0])
        self.assertIn("--urgency=normal", calls[1])
        self.assertEqual(calls[1][-2:], ["Antwort fertig", "Mein Chat"])

    def test_linux_without_notify_send_stays_quiet(self):
        with mock.patch.object(plattform, "WINDOWS", False), mock.patch.object(plattform, "which", return_value=None):
            self.assertFalse(reminders.notify("Antwort fertig", "x", reminder=False))

    def test_windows_toast_reminder_or_plain(self):
        scripts = []
        with mock.patch.object(plattform, "WINDOWS", True), \
                mock.patch.object(reminders, "powershell", side_effect=lambda s: scripts.append(s) or "ok"):
            self.assertTrue(reminders.notify("Erinnerung", "Ofen"))
            self.assertTrue(reminders.notify("Bild fertig", "Haus <am> See & Berge", reminder=False))
        self.assertIn("scenario=''reminder''", scripts[0])  # in PowerShell-Anführungszeichen verdoppelt
        self.assertNotIn("scenario=", scripts[1])
        self.assertNotIn("<actions>", scripts[1])
        self.assertIn("Haus &lt;am&gt; See &amp; Berge", scripts[1])  # Text sicher im XML


@unittest.skipUnless(os.environ.get("DISPLAY") or sys.platform == "win32", "braucht einen Bildschirm")
class AppNotifies(unittest.TestCase):
    """Startet InApp in einem eigenen Prozess – wie die anderen Tests mit ganzer App: Symbole und Schriften gehören
    zum ersten Tk-Fenster eines Prozesses, ein zweites App-Fenster danach fände sie nicht mehr."""

    def test_in_own_process(self):
        result = subprocess.run([sys.executable, "-m", "unittest", "-v", f"{Path(__file__).stem}.InApp"],
                                cwd=Path(__file__).resolve().parent, capture_output=True, text=True, timeout=120,
                                env={**os.environ, "MONHIP_IN_APP": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Ran 6 tests", result.stderr, result.stderr)
        self.assertNotIn("skipped", result.stderr, result.stderr)  # wirklich gelaufen, nicht übersprungen


@unittest.skipUnless(os.environ.get("MONHIP_IN_APP"), "läuft über AppNotifies im eigenen Prozess")
class InApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import i18n
        cls.dir = tempfile.TemporaryDirectory()
        data = Path(cls.dir.name)
        config_file = data / "config.json"
        config_file.write_text(json.dumps({"ui_language": "de"}), encoding="utf-8")
        initialize = i18n.initialize
        with mock.patch.object(i18n, "initialize", side_effect=lambda _path: initialize(config_file)):
            import monhip
        import chats
        import checkpoints
        import images
        import memory
        import roomui
        import tkinter as tk
        monhip.APP_DIR, monhip.CONFIG_FILE, monhip.MODEL_DIR = data, config_file, data / "modelle"
        chats.CHAT_DIR = data / "chats"
        chats.IMAGE_DIR = chats.CHAT_DIR / "bilder"
        checkpoints.DIR = data / "checkpoints"
        memory.FILE = data / "gedaechtnis.json"
        reminders.FILE = data / "erinnerungen.json"
        images.TEMP_DIR = data / "temp"
        roomui.CACHE_DIR = data / "cache"
        cls.monhip, cls.data = monhip, data
        cls.root = tk.Tk()
        cls.app = monhip.App(cls.root)
        cls.root.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.on_close()
        cls.dir.cleanup()

    def setUp(self):
        self.sent = []
        self.done = threading.Event()

        def notify(title, text, reminder=True):
            self.sent.append((title, text, reminder))
            self.done.set()
            return True

        patches = [mock.patch.object(reminders, "notify", side_effect=notify),
                   mock.patch.object(self.app, "in_front", return_value=False)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.app.notify_var.set(True)

    def wait(self) -> list:
        """Gemeldetes (im eigenen Thread verschickt) – kurz warten, ob etwas kommt."""
        self.done.wait(1.0)
        time.sleep(0.05)
        return self.sent

    def test_only_in_background_not_for_short_things_and_switchable(self):
        app = self.app
        app.notify_done("Schnell", "x", time.monotonic())  # eben erst begonnen
        self.assertEqual(self.wait(), [])
        app.notify_done("Lang", "y", time.monotonic() - 3 * self.monhip.NOTIFY_AFTER)
        self.assertEqual(self.wait(), [("Lang", "y", False)])  # gewöhnliche Benachrichtigung, keine Erinnerung
        self.sent.clear()
        self.done.clear()
        with mock.patch.object(app, "in_front", return_value=True):  # Monhip vorn: nichts
            app.notify_done("Vorn", "z")
        app.notify_var.set(False)  # abgeschaltet: nichts
        app.notify_done("Aus", "z")
        self.assertEqual(self.wait(), [])

    def test_in_front_is_false_when_minimized(self):
        with mock.patch.object(self.root, "state", return_value="iconic"):
            self.assertFalse(self.monhip.App.in_front(self.app))

    def finish_turn(self, messages, t0, stopped=False, failed=False):
        app = self.app
        app.turn = {"step": 1, "think": None, "thinks": [], "tool": None, "tps": None, "t0": t0}
        if failed:
            app.turn["failed"] = True
        app.view.t.mark_set("quellen:start", "end-1c")
        app.stop_event.clear()
        if stopped:
            app.stop_event.set()
        app._finish_turn(messages)

    def test_chat_answer(self):
        long_ago = time.monotonic() - 120
        self.finish_turn([{"role": "assistant", "content": "Hallo"}], long_ago)
        self.assertEqual(self.wait(), [("Antwort fertig", self.app._chat_title, False)])
        self.sent.clear()
        self.done.clear()
        self.finish_turn([], long_ago, failed=True)
        self.assertEqual(self.wait()[0][0], "Antwort mit Fehler beendet")
        self.sent.clear()
        self.done.clear()
        self.finish_turn([{"role": "assistant", "content": "Teil"}], long_ago, stopped=True)  # selbst gestoppt
        self.assertEqual(self.wait(), [])

    def test_expert_analysis(self):
        app = self.app
        job = mock.Mock()
        job.source = Path("Verträge")
        app.expert_job, app._expert_t0 = job, time.monotonic() - 600
        app._expert_event(job, "finished", {"ok": 3, "total": 3})
        sent = self.wait()
        self.assertEqual(sent[0][0], "Auswertung fertig")
        self.assertIn("Verträge", sent[0][1])
        self.assertIsNone(app.expert_job)

    def test_image(self):
        import galerie
        ims = self.app.images
        ims.gallery = galerie.Gallery(self.data / "bilder")
        import tkinter as tk
        pic = tk.PhotoImage(master=self.root, width=8, height=8)
        pic.put("#d97757", to=(0, 0, 8, 8))
        pic.write(str(self.data / "probe.png"), format="png")
        item = ims.gallery.add((self.data / "probe.png").read_bytes(), {"prompt": "Ein Leuchtturm", "width": 8,
                                                                          "height": 8})
        job = {"prompt": "Ein Leuchtturm", "width": 8, "height": 8, "count": 1, "seed": 1, "source": None}
        ims._finished(ims.model_key(), job, [item], None, threading.Event(), time.monotonic() - 60)
        self.assertEqual(self.wait(), [("Bild fertig", "Ein Leuchtturm", False)])

    def test_waiting_for_confirmation(self):
        import dialogs
        with mock.patch.object(dialogs, "present"):  # Dialog nicht wirklich zeigen (würde warten)
            answer = self.app.ask_confirm("Datei schreiben", "a.txt")
        for w in self.root.winfo_children():  # den nicht gezeigten Dialog wieder weg
            if w.winfo_class() == "Toplevel" and w is not self.app.settings_win:  # Einstellungen bleiben
                w.destroy()
        self.assertEqual(answer, "no")
        self.assertEqual(self.wait(), [("Monhip wartet auf deine Bestätigung", "Datei schreiben", False)])


if __name__ == "__main__":
    unittest.main()
