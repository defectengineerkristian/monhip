"""Seitenleiste „Quellen & Recherche“ (app/quellen.py): Die Ergebnisse der Werkzeuge (web.search, web.fetch,
experte.Library.search/read) werden zurückgelesen – ändert sich ein Format, schlägt dieser Test an. Dazu die Erkennung
von Quellenangaben in Antworten: python -m unittest discover -s progress/tests -p test_quellen.py"""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import experte  # noqa: E402
import quellen  # noqa: E402
import web  # noqa: E402


class ToolFormats(unittest.TestCase):
    def test_web_search(self):
        found = [{"title": "Kündigungsfrist – Mieterbund", "url": "https://www.mieterbund.de/k", "snippet": "Drei  Monate …"},
                 {"title": "§ 573c BGB", "url": "https://www.gesetze-im-internet.de/bgb/__573c.html", "snippet": ""}]
        with mock.patch.object(web, "search_duckduckgo", return_value=found):
            parsed = quellen.parse_web_search(web.search("Kündigungsfrist"))
        self.assertEqual([(r["title"], r["url"]) for r in parsed], [(r["title"], r["url"]) for r in found])
        self.assertEqual(parsed[0]["snippet"], "Drei Monate …")

    def test_web_page_in_parts(self):
        text = "Erster Absatz.\n" + "Mehr Text. " * 2000
        with mock.patch.object(web, "_page", return_value=("https://example.org/a", "Titel A", text)):
            first = quellen.parse_page(web.fetch("https://example.org/a"))
            whole = quellen.parse_page(web.fetch("https://example.org/a", max_chars=10 ** 6))
        self.assertEqual((first["url"], first["title"], first["start"], first["total"]),
                         ("https://example.org/a", "Titel A", 0, len(text)))
        self.assertTrue(first["text"].startswith("Erster Absatz.") and first["end"] < len(text))
        self.assertNotIn("…(Zeichen", first["text"])
        self.assertEqual((whole["total"], whole["text"]), (None, text))
        self.assertIsNone(quellen.parse_page("Fehler: Zeitüberschreitung"))

    def test_document_search_and_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Path(directory) / "store"
            store.mkdir()
            con = experte._db(store / "index.sqlite")
            con.executemany("INSERT INTO seiten (datei, art, nr, text) VALUES (?, ?, ?, ?)", [
                ("Verträge/Mietvertrag.pdf", "Seite", 4, "§ 9 Kündigung mit einer Frist von drei Monaten."),
                ("Verträge/Mietvertrag.pdf", "Seite", 5, "§ 10 Schönheitsreparaturen."),
                ("Notizen.docx", "Abschnitt", 1, "Kündigung schriftlich schicken.")])
            con.commit()
            con.close()
            (store / "stand.json").write_text(json.dumps({"dateien": {"Verträge/Mietvertrag.pdf": {}, "Notizen.docx": {}}}),
                                              encoding="utf-8")
            with mock.patch.object(experte, "store_for", lambda _s: store):
                library = experte.Library(Path(directory))
                hits = quellen.parse_doc_hits(library.search("Kündigung"))
                pages = quellen.parse_doc_pages(library.read("Mietvertrag", 4, 5))
                sections = quellen.parse_doc_pages(library.read("Notizen.docx"))
        self.assertEqual({(h["file"], h["art"], h["nr"]) for h in hits},
                         {("Verträge/Mietvertrag.pdf", "Seite", 4), ("Notizen.docx", "Abschnitt", 1)})
        self.assertTrue(all("»" in h["snippet"] for h in hits))
        self.assertEqual(pages["file"], "Verträge/Mietvertrag.pdf")
        self.assertEqual([(a, n) for a, n, _ in pages["pages"]], [("Seite", 4), ("Seite", 5)])
        self.assertEqual(pages["pages"][1][2], "§ 10 Schönheitsreparaturen.")
        self.assertEqual(sections["pages"][0][:2], ("Abschnitt", 1))


class Citations(unittest.TestCase):
    def test_file_and_page(self):
        pattern, names = quellen.citation_pattern(["Verträge/Mietvertrag.pdf", "Hausordnung.pdf"])
        text = ("Laut Mietvertrag.pdf, Seite 4 gilt … (siehe Mietvertrag, S. 5). Die Hausordnung.pdf regelt die Ruhezeit; "
                "Mietvertrags-Muster und hausordnung.pdf (page 2).")
        found = [(names[m["name"].lower()], m["nr"]) for m in pattern.finditer(text)]
        self.assertEqual(found, [("Verträge/Mietvertrag.pdf", "4"), ("Verträge/Mietvertrag.pdf", "5"),
                                 ("Hausordnung.pdf", None), ("Hausordnung.pdf", "2")])
        self.assertIsNone(quellen.citation_pattern([]))

    def test_marking_ignores_case_and_umlauts(self):
        pattern = quellen.term_pattern("Kündigung | Frist")
        text = "Die KÜNDIGUNG ist mit einer Kündigungsfrist von drei Monaten möglich."
        marked = [text[m.start():m.end()] for m in pattern.finditer(quellen.fold(text))]
        self.assertEqual(marked, ["KÜNDIGUNG", "Kündigungsfrist"])
        self.assertEqual(len(quellen.fold(text)), len(text))


if __name__ == "__main__":
    unittest.main()
