"""Expertensuche (experte.Library.search): Füllwörter, Wortformen, zusammengesetzte Wörter, ß/ss und mehrere
Formulierungen mit | – auf einem kleinen Index wie aus einer Auswertung: python -m unittest discover -s progress/tests -p test_experte_suche.py"""

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import experte  # noqa: E402

PAGES = [
    ("Mietvertrag.pdf", 4, "§ 9 Kündigung. Das Mietverhältnis kann von beiden Seiten mit einer Frist von drei Monaten "
                           "zum Monatsende gekündigt werden. Die Kündigung bedarf der Schriftform."),
    ("Mietvertrag.pdf", 2, "§ 2 Mietzeit. Der Vertrag beginnt am 1. Januar 2026 und läuft auf unbestimmte Zeit."),
    ("Arbeitsvertrag.pdf", 7, "Die Kündigungsfrist beträgt für beide Seiten vier Wochen zum Fünfzehnten. Eine fristlose "
                              "Beendigung bleibt unberührt."),
    ("Hausordnung.pdf", 1, "Ruhezeiten sind von 22 bis 6 Uhr einzuhalten. Wie in jedem Haus gilt: Rücksicht nehmen. "
                           "Die Straße ist sauber zu halten."),
    ("Nebenkosten.pdf", 3, "Die Abrechnung der Nebenkosten erfolgt jährlich. Ich bitte um pünktliche Zahlung an den "
                           "Vermieter."),
]


class ExpertSearch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        store = Path(cls.tmp.name) / "store"
        store.mkdir()
        con = experte._db(store / "index.sqlite")
        con.executemany("INSERT INTO seiten (datei, art, nr, text) VALUES (?, 'Seite', ?, ?)", PAGES)
        con.commit()
        con.close()
        (store / "stand.json").write_text(json.dumps({"dateien": {p[0]: {"status": "ok"} for p in PAGES}}),
                                          encoding="utf-8")
        cls.patch = mock.patch.object(experte, "store_for", lambda _source: store)
        cls.patch.start()
        cls.library = experte.Library(Path(cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        cls.tmp.cleanup()

    def hits(self, query):
        out = self.library.search(query)
        return [line.split(": ", 1)[0].split(". ", 1)[1] for line in out.splitlines() if line[:1].isdigit()]

    def test_filler_words_do_not_count(self):
        hits = self.hits("Wie beende ich den Vertrag?")
        self.assertNotIn("Hausordnung.pdf · Seite 1", hits)  # „wie“
        self.assertNotIn("Nebenkosten.pdf · Seite 3", hits)  # „ich“, „den“
        self.assertIn("Arbeitsvertrag.pdf · Seite 7", hits)  # „beende“ → „Beendigung“

    def test_compound_words_both_ways(self):
        self.assertEqual(self.hits("Kündigungsfrist"), ["Arbeitsvertrag.pdf · Seite 7", "Mietvertrag.pdf · Seite 4"])
        self.assertIn("Arbeitsvertrag.pdf · Seite 7", self.hits("Frist"))  # steckt in „Kündigungsfrist“
        self.assertEqual(self.hits("Mietkündigung"), ["Mietvertrag.pdf · Seite 4"])
        self.assertEqual(self.hits("Nebenkostenabrechnung"), ["Nebenkosten.pdf · Seite 3"])

    def test_word_forms_and_spelling(self):
        self.assertEqual(self.hits("Verträge"), ["Mietvertrag.pdf · Seite 2"])
        self.assertEqual(self.hits("Strasse"), ["Hausordnung.pdf · Seite 1"])
        self.assertIn("Mietvertrag.pdf · Seite 4", self.hits("kündigen"))  # „gekündigt“, „Kündigung“

    def test_alternatives(self):
        hits = self.hits("Kündigung | Vertrag beenden | Laufzeit")
        self.assertEqual(hits[0], "Mietvertrag.pdf · Seite 4")
        self.assertIn("Mietvertrag.pdf · Seite 2", hits)
        out = self.library.search("Vertrag beenden")
        self.assertIn("(nur einzelne Suchwörter)", out)
        self.assertIn("Keine Treffer", self.library.search("Photovoltaik"))
        with self.assertRaises(LookupError):
            self.library.search(" | ")


if __name__ == "__main__":
    unittest.main()
