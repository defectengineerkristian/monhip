"""Gestreamte Antworten: Die angefangene Zeile wird nur noch ab dem ersten geänderten Stück neu gesetzt (schnell auch
bei langen Absätzen). Prüft Zeichen für Zeichen, dass Text und Formatierung genau so aussehen wie beim früheren
vollständigen Neusetzen – und am Ende wie beim Darstellen auf einmal: python -m unittest tests.test_chat_stream"""

import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

SAMPLES = [
    "Ein Absatz mit **fett**, *kursiv*, ***beides***, `code` und ~~durch~~ – Ä Ö Ü ß € 😀 und mehr Text.",
    "Offen **fett ohne Ende und `code ohne Ende",
    "Link [Monhip](https://github.com/defectengineerkristian/monhip) und https://example.org/pfad?x=1 im Satz.",
    "# Titel\n\n## Unter **titel** 😀\n\nText nach der Überschrift.\n",
    "- Punkt *eins*\n- Punkt **zwei**\n  - eingerückt `x`\n    - tiefer\n1. erstens\n2. zweitens\n- [ ] offen\n- [x] erledigt\n",
    "> Zitat mit **fett**\n> zweite Zeile\n\nNormal.",
    "Vorher\n\n```python\ndef f(x):\n    return x * 2  # Kommentar 😀\n```\n\nNachher mit `code`.",
    "| A | B |\n|---|---|\n| 1 | **zwei** |\n| 3 | vier |\n\nDanach Text.",
    "Text\n\n---\n\nNach der Linie.\n\n***\n",
    "Emoji 😀😀 am **Anfang 😀** und *Ende 🎉*",
    "Ein langer Absatz " + "mit **Wechseln** zwischen *Stilen* und `Code` " * 8,
]


def dump(view):
    return view.t.dump("1.0", "end", text=True, tag=True)


@unittest.skipUnless(os.environ.get("DISPLAY") or sys.platform == "win32", "braucht einen Bildschirm")
class StreamingEqualsFullRedraw(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def views(self, n):
        import tkinter as tk
        from chatview import ChatView
        out = []
        for _ in range(n):
            text = tk.Text(self.root, width=60, height=20)
            out.append(ChatView(text, 1.0))
        return out

    def test_every_step_matches_the_old_full_redraw(self):
        for sample in SAMPLES:
            for size in (1, 3, 7):
                with self.subTest(sample=sample[:30], size=size):
                    new, old, whole = self.views(3)
                    old.incremental = False
                    for v in (new, old, whole):
                        v.user("Frage")
                    for i in range(0, len(sample), size):
                        new.md_append(sample[i:i + size])
                        old.md_append(sample[i:i + size])
                        self.assertEqual(dump(new), dump(old), f"nach {i + size} Zeichen")
                    new.md_finish()
                    old.md_finish()
                    whole.markdown(sample)
                    self.assertEqual(dump(new), dump(old))
                    self.assertEqual(dump(new), dump(whole))
                    for v in (new, old, whole):
                        v.t.destroy()

    def test_long_paragraph_needs_few_inserts(self):
        """2 000 Zeichen in Häppchen wie beim Streamen: früher setzte jedes Häppchen den ganzen Absatz neu (über
        20 000 Einfügungen ins Textfeld), jetzt kommt fast nur das Neue dazu."""
        counts = {}
        for incremental in (False, True):
            view, = self.views(1)
            view.incremental = incremental
            calls = [0]
            insert = view.t.insert

            def counting(*args, _insert=insert, _calls=calls):
                _calls[0] += 1
                return _insert(*args)

            view.t.insert = counting
            text = "Ein Satz mit **fett** und `code`. " * 60
            for i in range(0, len(text), 12):
                view.md_append(text[i:i + 12])
            view.md_finish()
            counts[incremental] = calls[0]
            self.assertIn("Ein Satz mit fett und code.", view.t.get("1.0", "end"))
            view.t.destroy()
        self.assertGreater(counts[False], 15_000)
        self.assertLess(counts[True], counts[False] / 15, counts)


if __name__ == "__main__":
    unittest.main()
