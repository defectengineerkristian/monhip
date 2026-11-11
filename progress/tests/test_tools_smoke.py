"""Rauchtest aller lokalen Agent-Werkzeuge – einmal echt ausgeführt, unter Windows (PowerShell, System.Drawing, …)
wie unter Linux (bash, Pillow, …). Ohne Internet und ohne Modell; Gedächtnis, Erinnerungen, Checkpoints und
Papierkorb landen in Temp-Ordnern: python -m unittest discover -s progress/tests -p test_tools_smoke.py"""

import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import agent
import checkpoints
import images
import memory
import plattform
import reminders


def png(path: Path, w: int = 40, h: int = 20):
    """Kleines PNG ohne Pillow (unter Windows ist es nicht installiert)."""
    rows = b"".join(b"\0" + bytes((200, 40, 40)) * w for _ in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    return path


class ToolSmoke(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ws = self.tmp / "arbeit"
        self.ws.mkdir()
        self.patches = [mock.patch.object(memory, "FILE", self.tmp / "gedaechtnis.json"),
                        mock.patch.object(reminders, "FILE", self.tmp / "erinnerungen.json"),
                        mock.patch.object(checkpoints, "DIR", self.tmp / "checkpoints"),
                        mock.patch.object(images, "TEMP_DIR", self.tmp / "temp"),
                        mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.tmp / "share")})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def agent(self, **kw):
        options = dict(files=True, commands=True, workspace=str(self.ws), confirm_actions=False, memory=True,
                       reminders=True, vision=True)
        options.update(kw)
        return agent.Agent(lambda *_: "yes", **options)

    def run_tool(self, worker, tool, /, **args):  # „/“: Werkzeuge haben selbst Argumente namens name
        out = worker.execute(tool, json.dumps(args))
        self.assertTrue(agent.result_ok(out), f"{tool}: {out}")
        return out

    def test_files(self):
        a = self.agent()
        self.run_tool(a, "write_file", path="notizen/a.txt", content="Hallo Welt\nZeile zwei\n")
        self.assertIn("Hallo Welt", self.run_tool(a, "read_file", path="notizen/a.txt"))
        self.run_tool(a, "edit_file", path="notizen/a.txt", old_text="Welt", new_text="Monhip")
        self.assertEqual((self.ws / "notizen" / "a.txt").read_text(encoding="utf-8"), "Hallo Monhip\nZeile zwei\n")
        self.assertIn("a.txt", self.run_tool(a, "list_directory", path="notizen"))
        self.assertIn("a.txt", self.run_tool(a, "search_files", pattern="*.txt", text="Monhip"))
        self.run_tool(a, "create_directory", path="kopien")
        self.run_tool(a, "copy_path", source="notizen/a.txt", destination="kopien/b.txt")
        self.run_tool(a, "move_path", source="kopien/b.txt", destination="kopien/c.txt")
        self.assertTrue((self.ws / "kopien" / "c.txt").is_file())
        self.run_tool(a, "delete_path", path="kopien/c.txt")  # in den Papierkorb
        self.assertFalse((self.ws / "kopien" / "c.txt").exists())
        out = a.execute("read_file", json.dumps({"path": str(self.tmp)}))  # außerhalb der Freigabe
        self.assertFalse(agent.result_ok(out), out)

    def test_office_pdf_and_media(self):
        a = self.agent()
        self.run_tool(a, "create_word_document", path="doku.docx", markdown="# Titel\n\nText mit **fett** – Ä Ö Ü ß")
        self.run_tool(a, "create_excel_workbook", path="tabelle.xlsx",
                      sheets=[{"name": "Daten", "rows": [["A", "B"], [1, 2.5], [True, None]]}])
        self.run_tool(a, "create_presentation", path="folien.pptx", title="Monhip",
                      slides=[{"title": "Eins", "bullets": ["a", "  b"]}])
        self.run_tool(a, "create_pdf", path="bericht.pdf", markdown="# Bericht\n\n" + "Text " * 900)
        for name in ("doku.docx", "tabelle.xlsx", "folien.pptx", "bericht.pdf"):
            self.assertGreater((self.ws / name).stat().st_size, 500, name)
        self.run_tool(a, "pdf_bearbeiten", aktion="seiten", dateien=["bericht.pdf"], ziel="erste.pdf", seiten="1")
        self.assertTrue((self.ws / "erste.pdf").is_file())
        png(self.ws / "bild.png")
        self.run_tool(a, "view_image", path="bild.png")
        out = self.run_tool(a, "bilder_bearbeiten", dateien=["bild.png"], max_kante=20, format="jpg")
        self.assertIn("20×10", out)
        self.assertTrue((self.ws / "bearbeitet" / "bild.jpg").is_file())

    def test_commands_and_processes(self):
        a = self.agent()
        out = self.run_tool(a, "run_command", command="echo hallo-monhip")
        self.assertIn("hallo-monhip", out)
        self.assertIn("Exit-Code 0", out)
        self.assertIn("42", self.run_tool(a, "run_python", code="print(6 * 7)"))
        wait = "Start-Sleep -Seconds 60" if plattform.WINDOWS else "sleep 60"
        out = self.run_tool(a, "prozess_starten", command=f"echo gestartet; {wait}", name="Warten")
        nr = int(re.search(r"\[(\d+)\]", out).group(1))
        self.assertIn("läuft", self.run_tool(a, "prozess_ausgabe", nr=nr))
        self.run_tool(a, "prozess_stoppen", nr=nr)
        self.assertNotIn("läuft seit", self.run_tool(a, "prozess_ausgabe", nr=nr))

    def test_checkpoints_plan_organize_storage_calc(self):
        self.run_tool(self.agent(), "write_file", path="c.txt", content="v1")
        self.run_tool(self.agent(), "edit_file", path="c.txt", old_text="v1", new_text="v2")
        third = self.agent()
        self.assertIn("c.txt", self.run_tool(third, "checkpoints_liste"))
        self.run_tool(third, "checkpoint_zurueck")
        self.assertEqual((self.ws / "c.txt").read_text(encoding="utf-8"), "v1")
        a = self.agent()
        self.run_tool(a, "plan_setzen", schritte=[{"text": "Testen", "status": "in_arbeit"}])
        for name in ("x.txt", "y.txt"):
            (self.ws / name).write_text(name, encoding="utf-8")
        self.run_tool(a, "dateien_ordnen", verschiebungen=[{"von": "x.txt", "nach": "Texte/"},
                                                            {"von": "y.txt", "nach": "Texte/"}])
        self.assertTrue((self.ws / "Texte" / "y.txt").is_file())
        self.run_tool(a, "speicher_analysieren", ordner=".")
        self.assertIn("14", self.run_tool(a, "rechnen", ausdruck="2 + 3 * 4"))

    def test_memory_and_reminders(self):
        a = self.agent()
        self.run_tool(a, "remember", text="Mag kurze Antworten")
        note = memory.load()[0]
        self.run_tool(a, "forget", id=note["id"])
        self.assertEqual(memory.load(), [])
        out = self.run_tool(a, "set_reminder", text="Ofen", in_minutes=20)
        self.assertEqual(len(reminders.load()), 1, out)
        self.run_tool(a, "cancel_reminder", id=reminders.load()[0]["id"])
        self.assertEqual(reminders.load(), [])

    def test_project_template(self):
        a = self.agent()
        self.run_tool(a, "create_project", name="hallo", language="python")
        self.assertTrue(any((self.ws / "hallo").iterdir()))

    @unittest.skipUnless(shutil.which("git"), "git fehlt")
    def test_git_status(self):
        repo = self.ws / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "neu.txt").write_text("x", encoding="utf-8")
        self.assertIn("neu.txt", self.run_tool(self.agent(git=True), "git_status", path="repo"))

    @unittest.skipUnless(plattform.WINDOWS or (os.environ.get("DISPLAY") and shutil.which("xclip")),
                         "braucht Windows oder X11 mit xclip")
    def test_clipboard(self):
        a = self.agent(confirm_actions=True)
        self.run_tool(a, "clipboard_write", text="Grüße aus dem Rauchtest")
        time.sleep(0.3)
        self.assertIn("Grüße aus dem Rauchtest", self.run_tool(a, "clipboard_read"))

    @unittest.skipUnless(plattform.WINDOWS or os.environ.get("DISPLAY"), "braucht einen Bildschirm")
    def test_screenshot(self):
        a = self.agent(screenshot=images.screenshot)
        out = self.run_tool(a, "take_screenshot")
        self.assertRegex(out, r"\d+ × \d+ Pixel")


if __name__ == "__main__":
    unittest.main()
