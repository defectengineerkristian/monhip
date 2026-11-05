"""Jupyter-Notebooks (app/notebook.py und die notebook_-Werkzeuge des Agenten): lesen mit Ausgaben und Abbildungen,
Zellen ändern, anlegen, Schutz vor kaputten Notebooks – ohne Jupyter. Ausführen nur, wenn ein Python mit Jupyter da
ist (nbclient, ipykernel): python -m unittest tests.test_notebook"""

import base64
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import agent  # noqa: E402
import checkpoints  # noqa: E402
import images  # noqa: E402
import notebook  # noqa: E402

_tmp = tempfile.TemporaryDirectory()
_patches = [mock.patch.object(checkpoints, "DIR", Path(_tmp.name) / "checkpoints"),  # nicht in die echten Daten
            mock.patch.object(notebook, "FIGURE_DIR", Path(_tmp.name) / "abbildungen")]


def setUpModule():
    for patch in _patches:
        patch.start()


def tearDownModule():
    for patch in _patches:
        patch.stop()
    _tmp.cleanup()


def png(width: int, height: int, color=(200, 30, 30)) -> bytes:
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    row = b"\x00" + bytes(color) * width
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def sample(figures: int = 1) -> dict:
    """Notebook wie aus Jupyter: Markdown mit Bild, Ausgabe, Tabelle, Abbildungen, Fehler mit Farbcodes."""
    pic = base64.b64encode(png(64, 48)).decode() + "\n"
    plots = [{"output_type": "display_data", "metadata": {},
              "data": {"image/png": base64.b64encode(png(80 + k, 60)).decode(),
                       "text/plain": ["<Figure size 640x480 with 1 Axes>"]}} for k in range(figures)]
    return {"nbformat": 4, "nbformat_minor": 5,
            "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3 (ipykernel)",
                                        "language": "python"}},
            "cells": [
                {"cell_type": "markdown", "id": "a1", "metadata": {}, "source": ["# Auswertung\n", "![bild](attachment:bild.png)"],
                 "attachments": {"bild.png": {"image/png": pic}}},
                {"cell_type": "code", "id": "a2", "metadata": {}, "execution_count": 1,
                 "source": ["import pandas as pd\n", "print('Zeilen:', 3)\n", "df"],
                 "outputs": [{"output_type": "stream", "name": "stdout", "text": ["Zeilen: 3\n"]},
                             {"output_type": "execute_result", "execution_count": 1, "metadata": {},
                              "data": {"text/plain": ["   a  b\n", "0  1  3"], "text/html": ["<table>…</table>"]}}]},
                {"cell_type": "code", "id": "a3", "metadata": {}, "execution_count": 2,
                 "source": "plt.plot([1, 2])", "outputs": plots},
                {"cell_type": "code", "id": "a4", "metadata": {}, "execution_count": 3, "source": ["1/0"],
                 "outputs": [{"output_type": "error", "ename": "ZeroDivisionError", "evalue": "division by zero",
                              "traceback": ["\x1b[0;31m-----\x1b[0m", "\x1b[0;31mZeroDivisionError\x1b[0m: division by zero"]}]},
            ]}


class Format(unittest.TestCase):
    def test_written_like_jupyter(self):
        jupyter = ('{\n "cells": [\n  {\n   "cell_type": "code",\n   "execution_count": null,\n   "id": "1f2e",\n'
                   '   "metadata": {},\n   "outputs": [],\n   "source": [\n    "print(\'Grüße\')\\n",\n    "x = 1"\n'
                   '   ]\n  }\n ],\n "metadata": {},\n "nbformat": 4,\n "nbformat_minor": 5\n}\n')
        self.assertEqual(notebook.dumps(json.loads(jupyter)), jupyter)

    def test_same_as_nbformat(self):
        try:
            import nbformat
        except ImportError:
            self.skipTest("nbformat nicht installiert")
        nb = nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell("print('ä')\nx = 1"),
                                             nbformat.v4.new_markdown_cell("# Titel")])
        written = nbformat.writes(nb) + "\n"  # nbformat.write hängt den Zeilenumbruch an
        self.assertEqual(notebook.dumps(json.loads(written)), written)

    def test_invalid(self):
        for bad in ({"cells": "x"}, {"cells": [], "nbformat": 3}, {"cells": [{"cell_type": "x"}], "nbformat": 4}, []):
            with self.assertRaises(notebook.NotebookError):
                notebook.check(bad)


class Reading(unittest.TestCase):
    def test_cells_outputs_and_figures(self):
        text, figures = notebook.render(sample(), "test.ipynb")
        self.assertIn("4 Zellen (3 Code, 1 Markdown), Kernel: Python 3 (ipykernel) (python3)", text)
        self.assertIn("── Zelle 2 · Code [1] ──\nimport pandas as pd", text)
        self.assertIn("│ Zeilen: 3", text)
        self.assertIn("│ Ergebnis [1]:\n│    a  b\n│ 0  1  3", text)
        self.assertNotIn("<Figure size", text)
        self.assertIn("[Abbildung 3.1: PNG 80×60]", text)
        self.assertIn("[Bild 1.1 (bild.png): PNG 64×48]", text)
        self.assertIn("Fehler ZeroDivisionError: division by zero", text)
        self.assertNotIn("\x1b", text)
        self.assertEqual([f.label for f in figures], ["Bild 1.1 (bild.png)", "Abbildung 3.1"])
        self.assertEqual(figures[1].path.read_bytes(), png(80, 60))
        self.assertTrue(figures[1].path.is_relative_to(notebook.FIGURE_DIR))

    def test_interactive_output(self):
        nb = sample()
        nb["cells"][2]["outputs"] = [{"output_type": "display_data", "metadata": {}, "data": {
            "text/html": ["<div id='plot'></div><script>Plotly.newPlot()</script>"],
            "application/vnd.plotly.v1+json": {"data": []}}}]
        text, figures = notebook.render(nb, "plotly.ipynb", "3")
        self.assertIn("interaktive Ausgabe (application/vnd.plotly.v1+json) – als Bild nicht verfügbar", text)
        self.assertNotIn("Plotly.newPlot", text)
        self.assertEqual(figures, [])

    def test_selection_and_limits(self):
        self.assertEqual(notebook.select("", 5), [1, 2, 3, 4, 5])
        self.assertEqual(notebook.select("2-3, 5", 5), [2, 3, 5])
        self.assertEqual(notebook.select("4-", 5), [4, 5])
        self.assertEqual(notebook.select(3, 5), [3])
        for bad in ("9", "a", "0"):
            with self.assertRaises(notebook.NotebookError):
                notebook.select(bad, 5)
        text, figures = notebook.render(sample(), "test.ipynb", "3")
        self.assertIn("gezeigt: Zellen 3", text)
        self.assertNotIn("Zelle 2", text)
        self.assertEqual(len(figures), 1)
        long = "\n".join(f"Zeile {i}" for i in range(500))
        clipped = notebook.clip(long)
        self.assertIn("Zeile 0", clipped)
        self.assertIn("Zeile 499", clipped)
        self.assertIn("Zeilen ausgelassen", clipped)
        self.assertEqual(notebook.clip("10%\r50%\r100%\nfertig"), "100%\nfertig")

    def test_too_long_continues(self):
        nb = sample()
        nb["cells"] += [notebook.new_cell(nb, "code", "x = 1\n" * 400) for _ in range(10)]
        text, _ = notebook.render(nb, "lang.ipynb")
        self.assertLess(len(text), notebook.READ_CHARS + 2000)
        self.assertIn("weiter mit zellen=", text)

    def test_figures_for_the_model(self):
        _, figures = notebook.render(sample(figures=6), "test.ipynb")
        paths, note = notebook.pick_figures(figures, vision=False)
        self.assertEqual(paths, [])
        self.assertIn("Bildverständnis", note)
        paths, note = notebook.pick_figures(figures, vision=True)
        self.assertEqual(len(paths), notebook.MAX_FIGURES)
        self.assertIn("Nicht angehängt", note)
        newest, _ = notebook.pick_figures(figures, vision=True, newest=True)
        self.assertEqual(newest[-1], figures[-1].path)
        for p in paths:
            images.check(p)


class Changing(unittest.TestCase):
    def test_replace_insert_delete(self):
        nb = sample()
        message, old, new = notebook.change(nb, "ersetzen", 2, "print(2)\nprint(3)")
        self.assertIn("alten Ausgaben sind entfernt", message)
        self.assertEqual(old, "import pandas as pd\nprint('Zeilen:', 3)\ndf")
        cell = nb["cells"][1]
        self.assertEqual((cell["source"], cell["outputs"], cell["execution_count"]), (["print(2)\n", "print(3)"], [], None))
        notebook.change(nb, "einfuegen", 0, "# Oben", "markdown")
        notebook.change(nb, "einfügen", 5, "print('Ende')")
        self.assertEqual(nb["cells"][0]["cell_type"], "markdown")
        self.assertEqual(nb["cells"][-1]["source"], ["print('Ende')"])
        self.assertEqual(len({c["id"] for c in nb["cells"]}), 6)
        notebook.change(nb, "loeschen", 1)
        self.assertEqual(len(nb["cells"]), 5)
        notebook.change(nb, "ersetzen", 1, "Text", "markdown")  # Code → Markdown
        self.assertNotIn("outputs", nb["cells"][0])
        notebook.check(json.loads(notebook.dumps(nb)))
        for args in (("ersetzen", 9, "x"), ("einfuegen", -1, "x"), ("loeschen", 0), ("drehen", 1, "x"),
                     ("ersetzen", 1, None), ("ersetzen", 1, "x", "python")):
            with self.subTest(args=args), self.assertRaises(notebook.NotebookError):
                notebook.change(nb, *args)


class AgentTools(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.asked = []

    def tearDown(self):
        self.dir.cleanup()

    def agent(self, **kw):
        options = dict(files=True, workspace=str(self.root), vision=True)
        options.update(kw)
        return agent.Agent(lambda title, text: self.asked.append(title) or "yes", **options)

    def test_tools_only_with_their_permissions(self):
        names = lambda a: {t["function"]["name"] for t in a.tools}  # noqa: E731
        self.assertTrue({"notebook_lesen", "notebook_zelle", "notebook_anlegen"} <= names(self.agent()))
        self.assertNotIn("notebook_ausfuehren", names(self.agent()))
        self.assertIn("notebook_ausfuehren", names(self.agent(commands=True)))
        self.assertFalse(any(n.startswith("notebook_") for n in names(self.agent(groups={"notebooks": False}))))
        self.assertIn("notebook_lesen", self.agent().system_prompt())
        self.assertIn("notebook_ausfuehren", self.agent(commands=True).system_prompt())

    def test_create_read_change(self):
        a = self.agent()
        cells = json.dumps({"path": "analyse", "zellen": [{"typ": "markdown", "inhalt": "# Analyse"},
                                                           {"typ": "code", "inhalt": "x = 1\nprint(x)"}]})
        self.assertIn("mit 2 Zellen angelegt", a.execute("notebook_anlegen", cells))
        path = self.root / "analyse.ipynb"
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["metadata"]["kernelspec"]["name"], "python3")
        self.assertIn("gibt es schon", a.execute("notebook_anlegen", cells))
        out = a.execute("notebook_zelle", json.dumps({"path": "analyse.ipynb", "aktion": "einfuegen", "nr": 2,
                                                      "inhalt": "print('neu')"}))
        self.assertIn("Neue Code-Zelle 3", out)
        self.assertIn("Notebook ändern?", self.asked)
        text = a.execute("notebook_lesen", '{"path": "analyse.ipynb"}')
        self.assertIn("── Zelle 3 · Code [ ] ──\nprint('neu')", text)
        self.assertEqual(a.execute("read_file", '{"path": "analyse.ipynb"}').splitlines()[0],
                         "(Jupyter-Notebook – gezeigt wie mit notebook_lesen; ändern mit notebook_zelle)")
        self.assertTrue(agent.result_ok(out))
        saved = json.dumps(checkpoints.recent(1), ensure_ascii=False)
        self.assertIn("analyse.ipynb", saved)  # alter Stand vor der Änderung gesichert

    def test_figures_go_to_the_model(self):
        path = self.root / "bilder.ipynb"
        notebook.save(path, sample(figures=2))
        a = self.agent()
        text = a.execute("notebook_lesen", '{"path": "bilder.ipynb"}')
        self.assertIn("Als Bild angehängt: Bild 1.1 (bild.png), Abbildung 3.1, Abbildung 3.2.", text)
        shown = a.pop_images()
        self.assertEqual(len(shown), 3)
        self.assertEqual(shown[1].read_bytes(), png(80, 60))
        blind = self.agent(vision=False)
        self.assertIn("Bildverständnis", blind.execute("notebook_lesen", '{"path": "bilder.ipynb"}'))
        self.assertEqual(blind.pop_images(), [])

    def test_no_broken_notebooks(self):
        path = self.root / "heil.ipynb"
        notebook.save(path, sample())
        a = self.agent()
        out = a.execute("edit_file", json.dumps({"path": "heil.ipynb", "old_text": '"nbformat": 4,', "new_text": ""}))
        self.assertTrue(out.startswith("Fehler") and "notebook_zelle" in out, out)
        out = a.execute("write_file", '{"path": "neu.ipynb", "content": "print(1)"}')
        self.assertTrue(out.startswith("Fehler") and "notebook_anlegen" in out, out)
        self.assertFalse((self.root / "neu.ipynb").exists())
        self.assertIn("kein Jupyter-Notebook", a.execute("notebook_lesen", '{"path": "x.txt"}'))
        notebook.check(json.loads(path.read_text(encoding="utf-8")))

    def test_call_description(self):
        _, label, detail = agent.describe_call("notebook_zelle", '{"path": "a.ipynb", "aktion": "loeschen", "nr": 4}')
        self.assertEqual((label, detail), ("Notebook ändern", "a.ipynb  ·  Zelle 4 löschen"))


def jupyter_python():
    try:
        return notebook.find_python([])
    except notebook.NotebookError:
        return None


@unittest.skipUnless(os.environ.get("MONHIP_NOTEBOOK_RUN", "1") == "1" and jupyter_python(), "kein Python mit Jupyter")
class Running(unittest.TestCase):
    def test_run_fix_and_run_again(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            a = agent.Agent(lambda *_: "yes", files=True, commands=True, workspace=directory, vision=True)
            plot = ("import matplotlib.pyplot as plt\nplt.plot([1, 3, 2])\nplt.show()" if _has_matplotlib()
                    else "print('kein Bild')")
            cells = [{"typ": "markdown", "inhalt": "# Lauf"}, {"typ": "code", "inhalt": "x = 21\nprint('x =', x)"},
                     {"typ": "code", "inhalt": plot}, {"typ": "code", "inhalt": "y = x / 0"},
                     {"typ": "code", "inhalt": "print('Ende', y)"}]
            a.execute("notebook_anlegen", json.dumps({"path": "lauf.ipynb", "zellen": cells}))
            out = a.execute("notebook_ausfuehren", '{"path": "lauf.ipynb", "timeout_seconds": 120}')
            self.assertIn("Abbruch in Zelle 4 von 5", out)
            self.assertIn("│ x = 21", out)
            self.assertIn("ZeroDivisionError", out)
            self.assertIn("Die Ausgaben sind im Notebook gespeichert.", out)
            saved = notebook.load(root / "lauf.ipynb")
            self.assertEqual(saved["cells"][1]["outputs"][0]["text"], ["x = 21\n"])
            if "matplotlib" in plot:
                self.assertIn("Als Bild angehängt: Abbildung 3.1", out)
                self.assertEqual(len(a.pop_images()), 1)
            a.execute("notebook_zelle", json.dumps({"path": "lauf.ipynb", "aktion": "ersetzen", "nr": 4,
                                                    "inhalt": "y = x * 2"}))
            out = a.execute("notebook_ausfuehren", '{"path": "lauf.ipynb", "timeout_seconds": 120}')
            self.assertIn("ausgeführt: Zellen 1–5 von 5", out)
            self.assertIn("│ Ende 42", out)
            out = a.execute("notebook_ausfuehren", '{"path": "lauf.ipynb", "bis_zelle": 2}')
            self.assertIn("Zellen 1–2 von 5", out)


def _has_matplotlib() -> bool:
    import subprocess
    return subprocess.run(jupyter_python() + ["-c", "import matplotlib"], capture_output=True).returncode == 0


if __name__ == "__main__":
    unittest.main()
