"""Tests für app/prozesse.py mit kleinen Python-Programmen statt PowerShell:
python -m unittest discover -s progress/tests -p test_prozesse.py"""
import importlib.util
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))  # prozesse importiert backend (Job-Objekt)
spec = importlib.util.spec_from_file_location("prozesse", Path(__file__).resolve().parents[2] / "app" / "prozesse.py")
pz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pz)
cwd = tempfile.gettempdir()


def py(code):
    return [sys.executable, "-c", code]


class Prozesse(unittest.TestCase):
    def setUp(self):
        self.addCleanup(pz.stop_all)  # nichts läuft nach einem Test weiter
        for name in ("READ_CHARS", "MAX_RUNNING"):  # einzelne Tests verkleinern die Grenzen
            self.addCleanup(setattr, pz, name, getattr(pz, name))

    def test_short_process_output_and_exit_code(self):
        p = pz.start(py("print('hallo'); import sys; sys.exit(3)"), cwd, "kurz")
        p.wait_end(10)
        assert not p.running() and "Exit-Code 3" in p.status(), p.status()
        assert p.read_new() == "hallo"
        assert p.read_new() == "", "schon Gelesenes kommt nicht noch einmal"

    def test_long_process_keeps_running_and_stops(self):
        """Wie ein Webserver: läuft weiter, neue Ausgabe nach und nach, Stoppen; Nummern auch als „#2“ oder „[2]“."""
        code = ("import time\nprint('Server auf http://localhost:8000', flush=True)\nfor i in range(100):\n"
                " time.sleep(0.2); print('anfrage', i, flush=True)")
        s = pz.start(py(code), cwd, "Webserver")
        s.wait_end(1)
        assert s.running() and "läuft seit" in s.status()
        first = s.read_new()
        assert first.startswith("Server auf http://localhost:8000"), first
        t = time.time()
        more = s.read_new(wait=5)
        assert "anfrage" in more and time.time() - t < 4, "wartet nur, bis Neues da ist"
        assert f"[{s.nr}] Webserver" in pz.listing() and "Laufende" in pz.prompt_block()
        assert pz.get(f"#{s.nr}") is s and pz.get(f"[{s.nr}]") is s and pz.get(s.nr) is s
        s.stop()
        assert not s.running()
        assert f"[{s.nr}]" not in pz.prompt_block()

    def test_much_output_only_the_newest(self):
        pz.READ_CHARS = 100
        b = pz.start(py("print('x' * 5000)"), cwd, "viel")
        b.wait_end(10)
        out = b.read_new()
        assert out.startswith("…(ältere Ausgabe ausgelassen)") and len(out) < 200, out[:80]

    def test_at_most_max_running(self):
        pz.MAX_RUNNING = 1
        w = pz.start(py("import time; time.sleep(30)"), cwd, "wartet")
        with self.assertRaises(pz.ProzessError) as cm:
            pz.start(py("pass"), cwd, "zu viel")
        assert "prozess_stoppen" in str(cm.exception)
        w.stop()

    def test_unknown_number_lists_processes(self):
        with self.assertRaises(pz.ProzessError) as cm:
            pz.get(99)
        assert "Hintergrund-Prozesse" in str(cm.exception)

    def test_stop_all_when_the_app_closes(self):
        x = pz.start(py("import time; time.sleep(30)"), cwd, "läuft noch")
        pz.stop_all()
        assert not x.running()


if __name__ == "__main__":
    unittest.main()
