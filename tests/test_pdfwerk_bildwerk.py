"""Tests für app/pdfwerk.py (mit selbst gebauten PDFs) und app/bildwerk.py (ohne PowerShell):
python tests/test_pdfwerk_bildwerk.py"""
import importlib.util
import shutil
import sys
import tempfile
import zlib
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP))  # bildwerk importiert speicher (nur Standardbibliothek)


def load(name):
    spec = importlib.util.spec_from_file_location(name, APP / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


pw, bw = load("pdfwerk"), load("bildwerk")


def stream(data: bytes, extra: bytes = b"", flate=False) -> bytes:
    if flate:
        data, extra = zlib.compress(data), extra + b" /Filter /FlateDecode"
    return b"<</Length %d%s>>\nstream\n" % (len(data), extra) + data + b"\nendstream"


def pdf(objects: dict, trailer: bytes = b"/Root 1 0 R", tail: bytes = b"") -> bytes:
    out, offsets = bytearray(b"%PDF-1.4\n"), {}
    for nr, body in sorted(objects.items()):
        offsets[nr] = len(out)
        out += b"%d 0 obj\n" % nr + body + b"\nendobj\n"
    xref, size = len(out), max(objects) + 1
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    out += b"".join(b"%010d 00000 n \n" % offsets.get(i, 0) for i in range(1, size))
    out += b"trailer\n<</Size %d %s>>\nstartxref\n%d\n%%%%EOF\n" % (size, trailer, xref)
    return bytes(out) + tail


# A: klassisch, verschachtelter Seitenbaum, geerbte Werte, Link von Seite 1 auf Seite 3, knifflige Zeichenketten
A = pdf({
    1: b"<</Type /Catalog /Pages 2 0 R /Outlines 13 0 R>>",
    2: b"<</Type /Pages /Kids [3 0 R 7 0 R] /Count 3 /MediaBox [0 0 595 842] /Rotate 90"
       b" /Resources <</Font <</F1 5 0 R>>>>>>",
    3: b"<</Type /Page /Parent 2 0 R /Contents 4 0 R /Annots [8 0 R]>>",
    4: stream(b"BT /F1 12 Tf 72 720 Td (Seite EINS \\(mit Klammer\\)) Tj ET"),
    5: b"<</Type /Font /Subtype /Type1 /BaseFont /Helvetica>>",
    7: b"<</Type /Pages /Parent 2 0 R /Kids [9 0 R 11 0 R] /Count 2>>",
    8: b"<</Type /Annot /Subtype /Link /Rect [0 0 10 10] /Dest [11 0 R /Fit] /P 3 0 R /NM <48656c6c6f>"
       b" /T (a (b) c) /Q /A#20B /F 0.5>>",
    9: b"<</Type /Page /Parent 7 0 R /Contents 10 0 R /MediaBox [0 0 100 100] /Rotate 0>>",
    10: stream(b"BT (Seite ZWEI) Tj ET", flate=True),
    11: b"<</Type /Page /Parent 7 0 R /Contents 12 0 R>>",
    12: stream(b"BT (Seite DREI) Tj ET"),
    13: b"<</Type /Outlines /First 3 0 R>>",
})

# B: PDF 1.5 – Katalog und Seitenbaum im komprimierten Objekt-Stream, Querverweis-Stream, nachträgliche Änderung
head = b"1 0 2 40 "
objstm = head + b"<</Type /Catalog /Pages 2 0 R>>".ljust(40) + b"<</Type /Pages /Kids [3 0 R] /Count 1>>"
B = pdf({
    3: b"<</Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R>>",
    4: stream(b"BT (ALT) Tj ET", flate=True),
    5: stream(objstm, b" /Type /ObjStm /N 2 /First %d" % len(head), flate=True),
    6: stream(b"", b" /Type /XRef /Root 1 0 R /Size 7"),
}, trailer=b"", tail=b"4 0 obj\n" + stream(b"BT (NEU nach Aenderung) Tj ET") + b"\nendobj\n")

tmp = Path(tempfile.mkdtemp())
try:
    (tmp / "a.pdf").write_bytes(A)
    (tmp / "b.pdf").write_bytes(B)
    a, b = pw.Document(tmp / "a.pdf"), pw.Document(tmp / "b.pdf")
    assert len(a.pages) == 3 and len(b.pages) == 1

    # Seite 1 allein: geerbte Werte übernommen, Link auf nicht übernommene Seite → null, Zeichenketten unverändert
    assert pw.write(tmp / "s1.pdf", [(a, 0, 0)]) == 1
    out = (tmp / "s1.pdf").read_bytes()
    s1 = pw.Document(tmp / "s1.pdf")
    page = s1.pages[0]["dict"]
    assert page[b"Rotate"] == 90 and page[b"MediaBox"] == [0, 0, 595, 842], page
    assert b"/Helvetica" in out and b"Seite EINS \\(mit Klammer\\)" in out
    assert b"(a (b) c)" in out and b"<48656c6c6f>" in out and b"/A#20B" in out and b"0.5" in out
    assert b"/Dest [null /Fit]" in out, "Link auf Seite 3 zeigt ins Leere statt die Seite mitzuziehen"
    assert b"ZWEI" not in out and b"DREI" not in out and b"Outlines" not in out
    annot = s1.get(page[b"Annots"][0])
    assert s1.get(annot[b"P"]) is page or annot[b"P"] == s1.pages[0]["ref"], "Rückverweis auf die neue Seite"

    # Seiten 3 und 1: jetzt zeigt der Link auf die neue Seite 3, Seite 2 behält eigene MediaBox und Rotate 0
    pw.write(tmp / "s31.pdf", [(a, i, 0) for i in pw.auswahl("3,1", 3)])
    d = pw.Document(tmp / "s31.pdf")
    link = d.get(d.get(d.pages[1]["dict"][b"Annots"])[0])
    assert link[b"Dest"][0] == d.pages[0]["ref"], link
    pw.write(tmp / "s2.pdf", [(a, 1, 0)])
    p2 = pw.Document(tmp / "s2.pdf").pages[0]["dict"]
    assert p2[b"MediaBox"] == [0, 0, 100, 100] and p2[b"Rotate"] == 0
    assert b"ZWEI" in zlib.decompress(pw.Document(tmp / "s2.pdf").get(p2[b"Contents"]).raw)

    # Drehen addiert sich zur vorhandenen Drehung
    pw.write(tmp / "dreh.pdf", [(a, 0, 270), (a, 1, 90)])
    rot = [p["dict"][b"Rotate"] for p in pw.Document(tmp / "dreh.pdf").pages]
    assert rot == [0, 90], rot

    # Objekt-Stream, Querverweis-Stream und nachträgliche Änderung: die neue Fassung gilt
    content = b.get(b.pages[0]["dict"][b"Contents"])
    assert content.raw == b"BT (NEU nach Aenderung) Tj ET", content.raw

    # Zusammenfügen zweier Dokumente: getrennte Nummernkreise, nichts vermischt
    assert pw.write(tmp / "alle.pdf", [(a, i, 0) for i in range(3)] + [(b, 0, 0)]) == 4
    m = pw.Document(tmp / "alle.pdf")
    assert len(m.pages) == 4 and m.pages[3]["dict"][b"MediaBox"] == [0, 0, 200, 200]
    raw = (tmp / "alle.pdf").read_bytes()
    assert b"NEU nach Aenderung" in raw and b"EINS" in raw and b"ALT" not in raw

    # Dieselbe Seite zweimal → zwei Seitenobjekte
    pw.write(tmp / "doppelt.pdf", [(a, 0, 0), (a, 0, 0)])
    dd = pw.Document(tmp / "doppelt.pdf")
    assert len(dd.pages) == 2 and dd.pages[0]["ref"] != dd.pages[1]["ref"]

    # Seitenauswahl
    assert pw.auswahl("", 4) == [0, 1, 2, 3] and pw.auswahl("alle", 2) == [0, 1]
    assert pw.auswahl("1-2, 4", 5) == [0, 1, 3] and pw.auswahl("4-", 5) == [3, 4] and pw.auswahl("-2", 5) == [0, 1]
    assert pw.auswahl("3-1", 3) == [2, 1, 0]
    for bad, hint in (("7", "gibt es nicht"), ("a-b", "verstehe ich nicht"), ("0", "gibt es nicht"), (",", "Keine")):
        try:
            pw.auswahl(bad, 5); raise AssertionError(bad)
        except pw.PdfError as e:
            assert hint in str(e), (bad, str(e))

    # Verschlüsselt, keine PDF, kaputt
    (tmp / "enc.pdf").write_bytes(pdf({1: b"<</Type /Catalog /Pages 2 0 R>>", 2: b"<</Type /Pages /Kids [] /Count 0>>"},
                                      trailer=b"/Root 1 0 R /Encrypt 3 0 R"))
    (tmp / "nichtpdf.pdf").write_bytes(b"Hallo")
    (tmp / "leer.pdf").write_bytes(pdf({1: b"<</Type /Catalog /Pages 2 0 R>>", 2: b"<</Type /Pages /Kids [] /Count 0>>"}))
    for name, hint in (("enc.pdf", "verschlüsselt"), ("nichtpdf.pdf", "keine PDF"), ("leer.pdf", "keine Seiten")):
        try:
            pw.Document(tmp / name); raise AssertionError(name)
        except pw.PdfError as e:
            assert hint in str(e), (name, str(e))

    # ---- bildwerk (ohne PowerShell)
    fotos = tmp / "Fotos"
    fotos.mkdir()
    for n in ("a.jpg", "B.JPG", "c.png", "notiz.txt", "o'neil.jpeg"):
        (fotos / n).write_bytes(b"x")
    files = bw.collect([str(fotos)], lambda p: Path(p).resolve())
    assert [f.name for f in files] == ["a.jpg", "B.JPG", "c.png", "o'neil.jpeg"], files
    assert [f.name for f in bw.collect(str(fotos / "*.jpg"), lambda p: Path(p).resolve())] == ["a.jpg", "B.JPG"]
    for bad, hint in (([str(fotos / "notiz.txt")], "kein unterstütztes Bild"), ([str(tmp / "fehlt.jpg")], "gibt es nicht"),
                      ([], "leer")):
        try:
            bw.collect(bad, lambda p: Path(p).resolve()); raise AssertionError(bad)
        except bw.BildError as e:
            assert hint in str(e), (bad, str(e))
    opts = bw.options(max_kante=1920, format="JPG")
    assert opts == {"max": 1920, "fmt": ".jpg", "q": 85, "turn": 0}
    assert "1920 Pixel" in bw.describe(opts) and "JPG" in bw.describe(opts)
    for kw, hint in (({}, "Nichts zu tun"), ({"format": "heic"}, "gibt es nicht"), ({"drehen": 45}, "90, 180"),
                     ({"max_kante": 5}, "zwischen 16"), ({"qualitaet": 0}, "zwischen 1 und 100"), ({"max_kante": "x"}, "Zahlen")):
        try:
            bw.options(**kw); raise AssertionError(kw)
        except bw.BildError as e:
            assert hint in str(e), (kw, str(e))
    target = fotos / "bearbeitet"
    target.mkdir()
    (target / "a.jpg").write_bytes(b"schon da")
    jobs = bw.plan(files, target, bw.options(format="jpg"))
    assert [d.name for _, d in jobs] == ["a (2).jpg", "B.jpg", "c.jpg", "o'neil.jpg"], [d.name for _, d in jobs]
    script = bw.script(jobs, bw.options(max_kante=800, drehen=90))
    assert "o''neil.jpeg" in script and "Edit-Image" in script and " 800 85 90 }" in script
    stdout = f"OK\t{files[0]}\t800\t600\r\nERR\t{files[1]}\tOut of memory.\n"
    done, errors = bw.parse(stdout, "", jobs)
    assert done == [(files[0], jobs[0][1], "800×600")] and errors == ["B.JPG: Out of memory."], (done, errors)
    assert "PowerShell lieferte kein Ergebnis: kaputt" in bw.parse("", "kaputt", jobs)[1][0]
    jobs[0][1].write_bytes(b"y")
    text = bw.summary(done, errors, target)
    assert text.startswith("1 Bilder bearbeitet") and "1 Fehler" in text and "800×600" in text, text
    print("alle pdfwerk- und bildwerk-Tests bestanden")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
