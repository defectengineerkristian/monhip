"""GUI-Prüfungen in getrennten Prozessen, ohne echte Konfiguration oder Nutzerdaten."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


def gui_worker(language):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
    import i18n
    with tempfile.TemporaryDirectory() as directory:
        data = Path(directory)
        config_file = data / "config.json"
        config_file.write_text(json.dumps({"ui_language": language, "speech_language": "de",
                                           "system_prompt": "Mein unveränderter Prompt {test}"}), encoding="utf-8")
        initialize = i18n.initialize
        with mock.patch.object(i18n, "initialize", side_effect=lambda _path: initialize(config_file)):
            import monhip
        import chats
        import dialogs
        import documents
        import images
        import memory
        import office
        import reminders
        import roomui
        import speech
        import tkinter as tk

        monhip.APP_DIR = data
        monhip.CONFIG_FILE = config_file
        monhip.MODEL_DIR = data / "modelle"
        chats.CHAT_DIR = data / "chats"
        chats.IMAGE_DIR = chats.CHAT_DIR / "bilder"
        memory.FILE = data / "gedaechtnis.json"
        reminders.FILE = data / "erinnerungen.json"
        images.TEMP_DIR = data / "temp"
        roomui.CACHE_DIR = data / "cache"
        root = tk.Tk()
        errors = []
        root.report_callback_exception = lambda *args: errors.append(args)
        app = monhip.App(root)

        def check():
            try:
                assert i18n.get_language() == language
                assert app.send_btn.cget("text") == ("Send" if language == "en" else "Senden")
                assert app.status_var.get() == ("No model loaded" if language == "en" else "Kein Modell geladen")
                app.open_settings("look")
                root.update()
                assert app.ui_language_combo.winfo_ismapped()
                assert tuple(app.ui_language_combo.cget("values")) == ("Deutsch", "English")
                assert app.ui_language_var.get() == ("English" if language == "en" else "Deutsch")
                assert app.theme_var.get() == ("Dark (gray/orange)" if language == "en" else "Dunkel (Grau/Orange)")
                app.new_chat()
                app.set_theme("light", save=False)
                app.set_theme("dark", save=False)
                app.set_mode("room")
                app.set_mode("chat")

                # Bestehende deutsche Protokollwerte bleiben erhalten; nur die Anzeige wird übersetzt.
                client = mock.Mock()
                client.profile = {"name": "Person", "ai": "Assistant"}
                app.room.client = client
                app.room.tasks = [{"nr": 1, "text": "Eigener Text bleibt deutsch", "status": "offen",
                                   "owner": "", "note": ""},
                                  {"nr": 2, "text": "Done task", "status": "erledigt", "owner": "", "note": ""}]
                app.room.open_tasks()
                root.update()
                rows = app.room._tasks_list.get(0, tk.END)
                assert "Eigener Text bleibt deutsch" in rows[0]
                assert ("[open]" if language == "en" else "[offen]") in rows[0]
                assert ("[done]" if language == "en" else "[erledigt]") in rows[1]
                assert app.room.tasks[1]["status"] == "erledigt"
                assert app.room._tasks_combo.get() == ("unassigned" if language == "en" else "niemand")
                app.room._tasks_win.destroy()

                # Ein übersetztes "nur lesen" darf keinesfalls Schreibrechte erteilen.
                project = data / "project"
                project.mkdir()
                server = mock.Mock()
                app.room.server = server
                app.room.info = {"is_host": True}
                with mock.patch.object(roomui.filedialog, "askdirectory", return_value=str(project)), \
                        mock.patch.object(roomui.projekt, "unsafe_root", return_value=None), \
                        mock.patch.object(app.room, "_form", return_value={"rights": i18n.tr("nur lesen")}):
                    app.room.share_project()
                assert server.set_project.call_args.args[1] is False
                app.room.server = None
                app.room.client = None
                app.room.info = None

                # Dokumentstruktur und Inhalte bleiben trotz übersetzter Metadaten lesbar.
                path = office.write_docx(data / "sample.docx", "# Test\n\nUnveränderter Dokumenttext")
                doc = documents.read(path)
                assert "Unveränderter Dokumenttext" in doc.text
                assert ("characters" if language == "en" else "Zeichen") in doc.info

                # Spracherkennung nur Deutsch oder Englisch (ohne „Automatisch erkennen“)
                assert app.speech_lang_var.get() in ("Deutsch", "German")
                assert list(speech.LANGUAGES.values()) == ["de", "en"]

                # Nur die Oberflächensprache ändern: nicht Prompt, Spracherkennung oder die laufende Sitzung.
                # Danach startet Monhip neu – der Hinweis kommt schon in der neuen Sprache.
                next_language = "de" if language == "en" else "en"
                app.ui_language_var.set("Deutsch" if next_language == "de" else "English")
                with mock.patch.object(dialogs, "showinfo") as notice, \
                        mock.patch.object(app, "restart") as restart:
                    app._change_ui_language()
                    assert notice.call_count == 1
                    assert ("restart" if next_language == "en" else "startet") in notice.call_args.args[1]
                    assert restart.call_count == 1
                stored = json.loads(config_file.read_text(encoding="utf-8"))
                assert stored["ui_language"] == next_language
                assert stored["speech_language"] == "de"
                assert stored["system_prompt"] == "Mein unveränderter Prompt {test}"
                assert i18n.get_language() == language
                assert initialize(config_file) == next_language
            except BaseException as error:
                errors.append(error)
            finally:
                app.room.server = app.room.client = None
                app.on_close()

        root.after(700, check)
        root.mainloop()
        if errors:
            raise AssertionError(errors)


@unittest.skipUnless(os.environ.get("DISPLAY") or sys.platform == "win32", "GUI benötigt einen Bildschirm")
class InterfaceTests(unittest.TestCase):
    def run_language(self, language):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--gui-worker", language],
                                text=True, capture_output=True, timeout=30,
                                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_german_interface_and_language_change(self):
        self.run_language("de")

    def test_english_interface_and_language_change(self):
        self.run_language("en")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--gui-worker":
        gui_worker(sys.argv[2])
    else:
        unittest.main()
