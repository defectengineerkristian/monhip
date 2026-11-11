"""Tests für app/checkpoints.py (in einem temporären Ordner, Papierkorb simuliert):
python -m unittest discover -s progress/tests -p test_checkpoints.py"""
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))  # checkpoints importiert i18n
spec = importlib.util.spec_from_file_location("checkpoints", Path(__file__).resolve().parents[2] / "app" / "checkpoints.py")
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)


class Checkpoints(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for name in ("MAX_SIZE", "KEEP"):  # einzelne Tests verkleinern die Grenzen
            self.addCleanup(setattr, c, name, getattr(c, name))
        self.base, self.work, self.bin = tmp / "checkpoints", tmp / "arbeit", tmp / "papierkorb"
        self.work.mkdir()
        self.bin.mkdir()

    def recycle(self, p: Path):
        shutil.move(str(p), str(self.bin / f"{len(list(self.bin.iterdir()))}_{p.name}"))

    def test_save_restore_and_undo(self):
        base, work, bin_, recycle = self.base, self.work, self.bin, self.recycle
        (work / "a.txt").write_text("alt", encoding="utf-8")
        (work / "ordner").mkdir()
        (work / "ordner" / "x.txt").write_text("x", encoding="utf-8")

        # Antwort 1: Datei ändern, neue Datei anlegen, Ordner löschen, zweimal dieselbe Datei ändern
        cp = c.Checkpoint(base)
        assert cp.nr is None and not base.exists(), "Ordner erst beim ersten Sichern"
        cp.save(work / "a.txt"); (work / "a.txt").write_text("neu 1", encoding="utf-8")
        cp.save(work / "a.txt"); (work / "a.txt").write_text("neu 2", encoding="utf-8")  # zählt nicht doppelt
        cp.save(work / "b.txt"); (work / "b.txt").write_text("b", encoding="utf-8")
        cp.save(work / "ordner"); shutil.rmtree(work / "ordner")
        cp.save(work / "ordner" / "x.txt")  # liegt im schon gesicherten Ordner → nichts Neues
        assert cp.nr == 1 and len(cp.entries) == 3, cp.entries
        assert [e["vorher"] for e in cp.entries] == ["datei", "fehlt", "ordner"]

        data = c.load(1, base)
        assert data["nr"] == 1 and len(data["eintraege"]) == 3
        assert "b.txt (neu)" in c.describe(data) and "(diese Antwort)" in c.describe(data, note=" (diese Antwort)")
        assert [d["nr"] for d in c.recent(base=base)] == [1]

        # Antwort 2 macht Antwort 1 rückgängig und sichert dabei den jetzigen Stand
        cp2 = c.Checkpoint(base)
        lines = c.restore(1, recycle, before=cp2, base=base)
        assert (work / "a.txt").read_text(encoding="utf-8") == "alt"
        assert not (work / "b.txt").exists() and any(p.name.endswith("b.txt") for p in bin_.iterdir())
        assert (work / "ordner" / "x.txt").read_text(encoding="utf-8") == "x"
        assert all(ln.startswith("✓") for ln in lines), lines
        assert cp2.nr == 2

        # …und das Zurücksetzen lässt sich selbst zurücknehmen
        c.restore(2, recycle, base=base)
        assert (work / "a.txt").read_text(encoding="utf-8") == "neu 2"
        assert (work / "b.txt").read_text(encoding="utf-8") == "b"
        assert not (work / "ordner").exists()

    def test_too_large_files_are_noted_not_saved(self):
        base, work, recycle = self.base, self.work, self.recycle
        c.MAX_SIZE = 10
        cp3 = c.Checkpoint(base)
        (work / "gross.bin").write_bytes(b"0" * 100)
        cp3.save(work / "gross.bin")
        assert cp3.entries[-1]["vorher"] == "zu_gross" and "kopie" not in cp3.entries[-1]
        assert c.restore(cp3.nr, recycle, base=base)[0].startswith("✗")

    def test_keeps_newest_but_not_one_being_restored(self):
        base, work = self.base, self.work
        c.KEEP = 3
        for i in range(4):
            x = c.Checkpoint(base); x.save(work / f"n{i}.txt")
        assert len(c.numbers(base)) == 3, c.numbers(base)
        oldest = c.numbers(base)[0]
        c._restoring.add(oldest)
        self.addCleanup(c._restoring.discard, oldest)
        c.Checkpoint(base).save(work / "n9.txt")
        assert oldest in c.numbers(base)

    def test_moves_are_noted_and_moved_back(self):
        """Verschiebungen werden nur vermerkt (keine Kopie) und rückwärts zurückgeschoben – auch das lässt sich
        zurücknehmen."""
        base, work, recycle = self.base, self.work, self.recycle
        (work / "foto.jpg").write_bytes(b"jpg")
        mv = c.Checkpoint(base)
        mv.save(work / "Bilder")                       # neuer Ordner
        mv.save_move(work / "foto.jpg", work / "Bilder" / "foto.jpg")
        (work / "Bilder").mkdir(); shutil.move(str(work / "foto.jpg"), str(work / "Bilder" / "foto.jpg"))
        mv.save(work / "Bilder" / "foto.jpg")          # danach bearbeitet: Inhalt wird trotzdem gesichert
        (work / "Bilder" / "foto.jpg").write_bytes(b"bearbeitet")
        assert [e["vorher"] for e in mv.entries] == ["fehlt", "verschoben", "datei"], mv.entries
        assert "foto.jpg → " in c.describe(c.load(mv.nr, base))
        back = c.Checkpoint(base)
        c.restore(mv.nr, recycle, before=back, base=base)
        assert (work / "foto.jpg").read_bytes() == b"jpg" and not (work / "Bilder").exists()
        c.restore(back.nr, recycle, base=base)          # Zurücksetzen zurücknehmen: wieder verschoben
        assert (work / "Bilder" / "foto.jpg").exists() and not (work / "foto.jpg").exists()
        (work / "Bilder" / "foto.jpg").rename(work / "weg.jpg")
        lines = c.restore(back.nr, recycle, base=base)
        assert any(ln.startswith("✗") and "gibt es nicht mehr" in ln for ln in lines), lines  # Meldung statt Absturz

    def test_unknown_number(self):
        with self.assertRaises(c.CheckpointError) as cm:
            c.load(999, self.base)
        assert "checkpoints_liste" in str(cm.exception)


if __name__ == "__main__":
    unittest.main()
