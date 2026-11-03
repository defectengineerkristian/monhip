"""Rauchtest der Oberfläche unter Windows und Linux, in einem eigenen Prozess ohne echte Daten: alle Seiten der
Einstellungen, alle Designs, ein Chat mit Markdown, Code und Werkzeug-Blöcken, ein Teamwork-Raum als Gastgeber (echter
Server auf 127.0.0.1) – jede Tk-Fehlermeldung zählt als Fehler. Prüft auch, dass die Knöpfe Symbole haben, wo es eine
Icon-Schrift gibt (Windows: Segoe, Linux: app/fonts/MonhipIcons.ttf mit Pillow): python -m unittest tests.test_gui_smoke
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

APP = Path(__file__).resolve().parents[1] / "app"


def images_in(widget) -> int:
    """So viele ttk-Knöpfe/-Beschriftungen unter widget zeigen ein Bild (Symbol)."""
    count = 0
    for child in widget.winfo_children():
        try:
            count += bool(str(child.cget("image")))
        except Exception:  # Widget ohne image-Option
            pass
        count += images_in(child)
    return count


def gui_worker():
    sys.path.insert(0, str(APP))
    import i18n
    with tempfile.TemporaryDirectory() as directory:
        data = Path(directory)
        config_file = data / "config.json"
        config_file.write_text(json.dumps({"ui_language": "de", "room_name": "Tester", "room_ai": "Helfer"}),
                               encoding="utf-8")
        initialize = i18n.initialize
        with mock.patch.object(i18n, "initialize", side_effect=lambda _path: initialize(config_file)):
            import monhip
        import chats
        import checkpoints
        import dialogs
        import icons
        import images
        import memory
        import reminders
        import room
        import roomui
        import themes
        import tkinter as tk

        monhip.APP_DIR = data
        monhip.CONFIG_FILE = config_file
        monhip.MODEL_DIR = data / "modelle"
        chats.CHAT_DIR = data / "chats"
        chats.IMAGE_DIR = chats.CHAT_DIR / "bilder"
        checkpoints.DIR = data / "checkpoints"
        memory.FILE = data / "gedaechtnis.json"
        reminders.FILE = data / "erinnerungen.json"
        images.TEMP_DIR = data / "temp"
        roomui.CACHE_DIR = data / "cache"
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *args: errors.append(args[1])
        app = monhip.App(root)
        app.app_dir = data
        report = {}

        def steps():
            # Einstellungen: jede Seite einmal
            for tab in app.settings_tabs:
                app.open_settings(tab)
                yield
            app.close_settings()
            # Designs: alle, zuletzt wieder dunkel
            for key in themes.THEMES:
                app.set_theme(key, save=False)
                yield
            app.set_theme("dark", save=False)
            # Chat: Markdown, Code, Werkzeuge, Gedankengang
            v = app.view
            v.clear()
            v.user("Hallo **Monhip**")
            v.markdown("# Titel\n\n- Punkt *eins*\n- Punkt `zwei`\n\n```python\nprint('hi')\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |")
            n = v.tool_begin("Websuche", "monhip", '{"query": "monhip"}', icon="🌐")
            v.tool_end(n, "Ergebnis", True)
            v.tool_static("Datei lesen", "a.txt", '{"path": "a.txt"}', "Inhalt", False, icon="✎")
            t = v.think_begin()
            v.think_append(t, "Ich überlege …")
            v.think_end(t)
            v.footer("{}", 12.5)
            yield
            # Mausrad: unter Linux (Tk 8.6) als Taste 5, sonst <MouseWheel> – der Chat muss weich nach unten scrollen
            v.markdown("\n\n".join(f"Absatz {i}: " + "Text " * 30 for i in range(80)))
            yield
            v.t.yview_moveto(0)
            v._stick = False
            yield
            for _ in range(3):
                if sys.platform == "win32":
                    v.t.event_generate("<MouseWheel>", delta=-120, x=20, y=20)
                else:
                    v.t.event_generate("<Button-5>", x=20, y=20)
            for _ in range(8):  # ~0,15 s weiches Scrollen
                yield
            report["wheel_scrolled"] = v.t.yview()[0] > 0
            # Teamwork: Raum als Gastgeber auf 127.0.0.1, Seitenleiste mit Symbolen
            app.set_mode("room")
            with mock.patch.object(app.room, "show_invite"):
                app.room.create("Testraum", "127.0.0.1", 0, room.new_key())
                deadline = time.time() + 15
                while not app.room.connected and time.time() < deadline:
                    yield
            report["connected"] = app.room.connected
            report["state"] = app.room.state
            yield
            report["room_icons"] = images_in(app.room_side)
            app.room.open_tasks()
            yield
            app.room._tasks_win.destroy()
            with mock.patch.object(dialogs, "askyesno", return_value=True):
                app.room.leave()
            yield
            app.set_mode("chat")
            report["chat_icons"] = images_in(app.root)
            report["render"] = bool(icons.RENDER)
            report["family"] = icons.FAMILY

        it = steps()

        def tick():
            try:
                next(it)
                root.after(80, tick)
            except StopIteration:
                finish()
            except BaseException as error:
                errors.append(error)
                finish()

        def finish():
            report["errors"] = [f"{type(e).__name__}: {e}" for e in errors]
            print("REPORT " + json.dumps(report, ensure_ascii=False))
            app.room.server = app.room.client = None
            app.on_close()

        root.after(600, tick)
        root.mainloop()


@unittest.skipUnless(os.environ.get("DISPLAY") or sys.platform == "win32", "GUI benötigt einen Bildschirm")
class GuiSmoke(unittest.TestCase):
    def test_settings_themes_chat_and_room(self):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--gui-worker"], text=True,
                                capture_output=True, timeout=120, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        lines = [ln for ln in result.stdout.splitlines() if ln.startswith("REPORT ")]
        self.assertTrue(lines, result.stdout + result.stderr)
        report = json.loads(lines[-1][7:])
        self.assertEqual(report["errors"], [], result.stderr)
        self.assertTrue(report["connected"], report)
        self.assertTrue(report["wheel_scrolled"], "Mausrad scrollt den Chat nicht")
        if report["render"]:  # Icon-Schrift da: Seitenleiste des Raums mit Symbolen (wie unter Windows)
            self.assertGreaterEqual(report["room_icons"], 5, report)
        if sys.platform.startswith("linux") and importable("PIL"):
            self.assertTrue(report["render"], "Linux mit Pillow: Symbole müssen gezeichnet werden")
            self.assertEqual(report["family"], "Monhip Icons")


def importable(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


if __name__ == "__main__":
    if sys.argv[1:] == ["--gui-worker"]:
        gui_worker()
    else:
        unittest.main()
