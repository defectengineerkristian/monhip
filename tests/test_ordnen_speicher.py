"""Tests für app/ordnen.py (mit checkpoints.py) und app/speicher.py: python tests/test_ordnen_speicher.py"""
import importlib.util
import shutil
import sys
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))  # ordnen/speicher importieren nur die Standardbibliothek


def load(name):
    spec = importlib.util.spec_from_file_location(name, APP / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ordnen, speicher, checkpoints = load("ordnen"), load("speicher"), load("checkpoints")

tmp = Path(tempfile.mkdtemp()).resolve()
try:
    dl, bin_ = tmp / "Downloads", tmp / "papierkorb"
    dl.mkdir(); bin_.mkdir()
    for name, data in (("IMG_1.jpg", b"1" * 10), ("IMG_2.JPG", b"2" * 20), ("Rechnung.pdf", b"p" * 30),
                       ("setup.exe", b"e" * 2_000_000), ("kopie.exe", b"e" * 2_000_000), ("notiz.txt", b"t")):
        (dl / name).write_bytes(data)
    (dl / "Alt").mkdir()
    (dl / "Alt" / "a.txt").write_text("a", encoding="utf-8")

    def resolve(p):  # wie Agent._path: nur unter tmp
        full = Path(p).resolve()
        if full != tmp and tmp not in full.parents:
            raise PermissionError(f"Kein Zugriff auf {full}")
        return full

    # ---- Plan prüfen: alles oder nichts
    bad = [{"von": "IMG_1.jpg", "nach": "Bilder/"}, {"von": "gibtsnicht.png", "nach": "Bilder/"},
           {"von": "notiz.txt", "nach": "Rechnung.pdf"}, {"von": "IMG_2.JPG", "nach": "/etc/x.jpg"},
           {"von": "Alt", "nach": "Alt/Unter/"}, {"von": "IMG_1.jpg", "nach": "Fotos/"}, {"nach": "x"}]
    try:
        ordnen.plan(dl, bad, resolve, [tmp]); raise AssertionError
    except ordnen.OrdnenError as e:
        msg = str(e)
        for hint in ("gibtsnicht.png: gibt es nicht", "Rechnung.pdf: gibt es schon", "Kein Zugriff", "in sich selbst",
                     "mehrfach", "ohne von/nach", "nichts wurde verschoben"):
            assert hint in msg, (hint, msg)
    assert (dl / "IMG_1.jpg").exists(), "bei Fehlern wird nichts verschoben"
    try:
        ordnen.plan(dl, [{"von": "Alt", "nach": "X/"}, {"von": "Alt/a.txt", "nach": "Y/"}], resolve, [tmp]); raise AssertionError
    except ordnen.OrdnenError as e:
        assert "nur eins von beiden" in str(e)
    try:
        ordnen.plan(dl, [{"von": "IMG_1.jpg", "nach": "A/"}, {"von": "IMG_1.jpg", "nach": "B/"}], resolve); raise AssertionError
    except ordnen.OrdnenError as e:
        assert "mehrfach" in str(e)
    try:
        ordnen.plan(tmp, [{"von": "Downloads", "nach": "D2"}], resolve, [dl]); raise AssertionError
    except ordnen.OrdnenError as e:
        assert "freigegebener Ordner" in str(e)

    # Leerzeichen um Pfadteile im Ziel (so von einem echten Modell geschickt) ergeben keinen Ordner „ Fotos“
    spaced = ordnen.plan(dl, [{"von": "IMG_1.jpg", "nach": "Fotos / Urlaub /"}], resolve, [tmp])
    assert spaced[0][1] == dl / "Fotos" / "Urlaub" / "IMG_1.jpg", spaced

    sep = "\\" if speicher.os.name == "nt" else "/"  # Windows: auch Backslash am Ende heißt „in diesen Ordner“
    good = [{"von": "IMG_1.jpg", "nach": "Bilder/"}, {"von": "IMG_2.JPG", "nach": "Bilder" + sep},
            {"von": "Rechnung.pdf", "nach": "Dokumente/2026/Rechnung Strom.pdf"}, {"von": "notiz.txt", "nach": "notiz.txt"},
            {"von": "setup.exe", "nach": "Programme/"}]
    moves = ordnen.plan(dl, '[' + ",".join(f'{{"von": "{m["von"]}", "nach": "{m["nach"]}"}}'.replace("\\", "\\\\")
                                           for m in good) + ']', resolve, [tmp])
    assert len(moves) == 4, "notiz.txt bleibt, wo sie ist"
    prev = ordnen.preview(moves, dl)
    assert "→ Bilder  (2)" in prev and "Rechnung.pdf → Rechnung Strom.pdf" in prev, prev

    # ---- Ausführen mit Checkpoint, dann zurück
    cp = checkpoints.Checkpoint(tmp / "checkpoints")

    def before_dir(folder):
        cp.save(folder)
    done, errors = ordnen.ausfuehren(moves, before_move=cp.save_move, before_dir=before_dir)
    assert done == 4 and not errors, errors
    assert (dl / "Bilder" / "IMG_2.JPG").exists() and (dl / "Dokumente" / "2026" / "Rechnung Strom.pdf").exists()
    assert [e["vorher"] for e in cp.entries].count("fehlt") == 3, "Bilder, Dokumente, Programme sind neu"
    lines = checkpoints.restore(cp.nr, lambda p: shutil.move(str(p), str(bin_ / p.name)), base=tmp / "checkpoints")
    assert all(ln.startswith("✓") for ln in lines), lines
    for name in ("IMG_1.jpg", "IMG_2.JPG", "Rechnung.pdf", "setup.exe"):
        assert (dl / name).exists(), name
    assert not (dl / "Bilder").exists() and not (dl / "Dokumente").exists(), "neue Ordner wieder weg"
    shutil.rmtree(tmp / "checkpoints")

    # ---- Speicher
    report = speicher.analyse(dl, duplicates=True)
    assert "Speicher in" in report and "7 Dateien" in report, report
    assert "Alt" + speicher.os.sep in report, "Unterordner werden aufgeführt"
    assert "Installer & Abbilder" in report and "setup.exe" in report
    assert "Doppelte Dateien (ab 1 MB): 1 Gruppen" in report and "kopie.exe" in report, report
    assert "Laufwerke:" in report
    assert speicher.size_text(1536) == "1,5 KB" and speicher.size_text(5) == "5 B"
    speicher.TIME_LIMIT = -1
    assert "UNVOLLSTÄNDIG" in speicher.analyse(dl)
    print("alle ordnen- und speicher-Tests bestanden")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
