"""Tests für app/ordnen.py (mit checkpoints.py) und app/speicher.py:
python -m unittest discover -s progress/tests -p test_ordnen_speicher.py"""
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
sys.path.insert(0, str(APP))  # ordnen/speicher importieren nur die Standardbibliothek


def load(name):
    spec = importlib.util.spec_from_file_location(name, APP / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ordnen, speicher, checkpoints = load("ordnen"), load("speicher"), load("checkpoints")


class Downloads(unittest.TestCase):
    """Ein unordentlicher Download-Ordner in einem temporären Ordner; Zugriff nur darunter (wie Agent._path)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.dl, self.bin = self.tmp / "Downloads", self.tmp / "papierkorb"
        self.dl.mkdir()
        self.bin.mkdir()
        for name, data in (("IMG_1.jpg", b"1" * 10), ("IMG_2.JPG", b"2" * 20), ("Rechnung.pdf", b"p" * 30),
                           ("setup.exe", b"e" * 2_000_000), ("kopie.exe", b"e" * 2_000_000), ("notiz.txt", b"t")):
            (self.dl / name).write_bytes(data)
        (self.dl / "Alt").mkdir()
        (self.dl / "Alt" / "a.txt").write_text("a", encoding="utf-8")

    def resolve(self, p):
        full = Path(p).resolve()
        if full != self.tmp and self.tmp not in full.parents:
            raise PermissionError(f"Kein Zugriff auf {full}")
        return full


class Ordnen(Downloads):
    def test_plan_all_or_nothing(self):
        tmp, dl, resolve = self.tmp, self.dl, self.resolve
        bad = [{"von": "IMG_1.jpg", "nach": "Bilder/"}, {"von": "gibtsnicht.png", "nach": "Bilder/"},
               {"von": "notiz.txt", "nach": "Rechnung.pdf"}, {"von": "IMG_2.JPG", "nach": "/etc/x.jpg"},
               {"von": "Alt", "nach": "Alt/Unter/"}, {"von": "IMG_1.jpg", "nach": "Fotos/"}, {"nach": "x"}]
        with self.assertRaises(ordnen.OrdnenError) as cm:
            ordnen.plan(dl, bad, resolve, [tmp])
        msg = str(cm.exception)
        for hint in ("gibtsnicht.png: gibt es nicht", "Rechnung.pdf: gibt es schon", "Kein Zugriff", "in sich selbst",
                     "mehrfach", "ohne von/nach", "nichts wurde verschoben"):
            assert hint in msg, (hint, msg)
        assert (dl / "IMG_1.jpg").exists(), "bei Fehlern wird nichts verschoben"
        for moves, roots, hint in (([{"von": "Alt", "nach": "X/"}, {"von": "Alt/a.txt", "nach": "Y/"}], [tmp], "nur eins von beiden"),
                                   ([{"von": "IMG_1.jpg", "nach": "A/"}, {"von": "IMG_1.jpg", "nach": "B/"}], None, "mehrfach")):
            with self.subTest(hint=hint), self.assertRaises(ordnen.OrdnenError) as cm:
                ordnen.plan(dl, moves, resolve, *([roots] if roots else []))
            assert hint in str(cm.exception)
        with self.assertRaises(ordnen.OrdnenError) as cm:
            ordnen.plan(tmp, [{"von": "Downloads", "nach": "D2"}], resolve, [dl])
        assert "freigegebener Ordner" in str(cm.exception)

    def test_spaces_around_path_parts(self):
        """Leerzeichen um Pfadteile im Ziel (so von einem echten Modell geschickt) ergeben keinen Ordner „ Fotos“."""
        spaced = ordnen.plan(self.dl, [{"von": "IMG_1.jpg", "nach": "Fotos / Urlaub /"}], self.resolve, [self.tmp])
        assert spaced[0][1] == self.dl / "Fotos" / "Urlaub" / "IMG_1.jpg", spaced

    def test_execute_with_checkpoint_and_back(self):
        tmp, dl, bin_, resolve = self.tmp, self.dl, self.bin, self.resolve
        sep = "\\" if speicher.os.name == "nt" else "/"  # Windows: auch Backslash am Ende heißt „in diesen Ordner“
        good = [{"von": "IMG_1.jpg", "nach": "Bilder/"}, {"von": "IMG_2.JPG", "nach": "Bilder" + sep},
                {"von": "Rechnung.pdf", "nach": "Dokumente/2026/Rechnung Strom.pdf"}, {"von": "notiz.txt", "nach": "notiz.txt"},
                {"von": "setup.exe", "nach": "Programme/"}]
        moves = ordnen.plan(dl, '[' + ",".join(f'{{"von": "{m["von"]}", "nach": "{m["nach"]}"}}'.replace("\\", "\\\\")
                                               for m in good) + ']', resolve, [tmp])
        assert len(moves) == 4, "notiz.txt bleibt, wo sie ist"
        prev = ordnen.preview(moves, dl)
        assert "→ Bilder  (2)" in prev and "Rechnung.pdf → Rechnung Strom.pdf" in prev, prev

        cp = checkpoints.Checkpoint(tmp / "checkpoints")
        done, errors = ordnen.ausfuehren(moves, before_move=cp.save_move, before_dir=cp.save)
        assert done == 4 and not errors, errors
        assert (dl / "Bilder" / "IMG_2.JPG").exists() and (dl / "Dokumente" / "2026" / "Rechnung Strom.pdf").exists()
        assert [e["vorher"] for e in cp.entries].count("fehlt") == 3, "Bilder, Dokumente, Programme sind neu"
        lines = checkpoints.restore(cp.nr, lambda p: shutil.move(str(p), str(bin_ / p.name)), base=tmp / "checkpoints")
        assert all(ln.startswith("✓") for ln in lines), lines
        for name in ("IMG_1.jpg", "IMG_2.JPG", "Rechnung.pdf", "setup.exe"):
            assert (dl / name).exists(), name
        assert not (dl / "Bilder").exists() and not (dl / "Dokumente").exists(), "neue Ordner wieder weg"


class Speicher(Downloads):
    def test_analyse(self):
        dl = self.dl
        report = speicher.analyse(dl, duplicates=True)
        assert "Speicher in" in report and "7 Dateien" in report, report
        assert "Alt" + speicher.os.sep in report, "Unterordner werden aufgeführt"
        assert "Installer & Abbilder" in report and "setup.exe" in report
        assert "Doppelte Dateien (ab 1 MB): 1 Gruppen" in report and "kopie.exe" in report, report
        assert "Laufwerke:" in report
        assert speicher.size_text(1536) == "1,5 KB" and speicher.size_text(5) == "5 B"

    def test_time_limit_marks_incomplete(self):
        self.addCleanup(setattr, speicher, "TIME_LIMIT", speicher.TIME_LIMIT)
        speicher.TIME_LIMIT = -1
        assert "UNVOLLSTÄNDIG" in speicher.analyse(self.dl)


if __name__ == "__main__":
    unittest.main()
