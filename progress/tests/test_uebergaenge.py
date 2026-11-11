"""Weiche Übergänge ohne Kosten für die Leistung: Bilder springen nicht mehr in der Größe (bilder.fit_photo),
Fortschritt gleitet (widgets.Glide), die Seitenleiste „Quellen“ gleitet auf und zu und landet immer im richtigen
Zustand – auch bei schnellem Hin und Her: python -m unittest discover -s progress/tests -p test_uebergaenge.py"""

import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import tkinter as tk  # noqa: E402
from tkinter import ttk  # noqa: E402


def pump(root, seconds: float):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        time.sleep(0.005)


class Pictures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_fit_photo_fills_the_box_without_overflow(self):
        import bilder
        for sw, sh, bw, bh in ((1024, 1024, 700, 640), (1216, 832, 700, 500), (832, 1216, 500, 700),
                               (1024, 1024, 300, 300), (128, 128, 700, 640), (64, 40, 900, 600), (5000, 300, 200, 200)):
            out = bilder.fit_photo(tk.PhotoImage(master=self.root, width=sw, height=sh), bw, bh, self.root)
            with self.subTest(src=(sw, sh), box=(bw, bh)):
                self.assertLessEqual(out.width(), bw)
                self.assertLessEqual(out.height(), bh)
                scale = min(bw / sw, bh / sh)
                if 1 / 8 <= scale:  # sonst ganzzahlig verkleinert wie früher
                    self.assertGreaterEqual(out.width(), 0.9 * sw * scale)  # vorher oft nur gut die Hälfte

    def test_glide_reaches_the_target_and_resets_at_once(self):
        import widgets
        bar = ttk.Progressbar(self.root, maximum=100)
        g = widgets.Glide(bar)
        g.set(0, maximum=8, animate=False)
        g.set(3)
        self.assertLess(float(bar.cget("value")), 3)  # gleitet …
        pump(self.root, 0.35)
        self.assertAlmostEqual(float(bar.cget("value")), 3)  # … und kommt an
        g.set(0)  # neuer Auftrag: sofort zurück
        self.assertEqual(float(bar.cget("value")), 0)
        g.set(50, maximum=100)  # anderer Maßstab: sofort
        self.assertEqual(float(bar.cget("value")), 50)
        bar.destroy()
        g.set(60)  # Fenster schon zu: kein Fehler
        pump(self.root, 0.05)


class SourcePanelSlides(unittest.TestCase):
    def test_open_close_and_fast_toggling(self):
        import i18n
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            config_file = data / "config.json"
            config_file.write_text(json.dumps({"ui_language": "de"}), encoding="utf-8")
            initialize = i18n.initialize
            with mock.patch.object(i18n, "initialize", side_effect=lambda _path: initialize(config_file)):
                import monhip
            import chats
            import images
            import roomui
            monhip.APP_DIR, monhip.CONFIG_FILE, monhip.MODEL_DIR = data, config_file, data / "modelle"
            chats.CHAT_DIR = data / "chats"
            images.TEMP_DIR = data / "temp"
            roomui.CACHE_DIR = data / "cache"
            root = tk.Tk()
            app = monhip.App(root)
            try:
                root.geometry("1200x700+0+0")
                pump(root, 0.3)
                panel = app.sources
                full = panel._width
                panel.toggle()  # auf
                self.assertTrue(panel.visible)
                widths, end = [], time.monotonic() + 0.4
                while time.monotonic() < end:
                    root.update()
                    widths.append(panel.outer.winfo_width())
                    time.sleep(0.005)
                # gleitet nur auf, nie über das Ziel hinaus (auf einem langsamen Rechner darf es auch gleich springen)
                self.assertEqual(widths, sorted(widths))
                self.assertLessEqual(max(widths), full)
                self.assertTrue(panel.outer.winfo_ismapped())
                self.assertEqual(panel.outer.winfo_width(), full)
                self.assertEqual(panel.frame.winfo_width(), full)  # Inhalt immer in voller Breite
                panel.toggle()  # zu
                self.assertFalse(panel.visible)
                pump(root, 0.4)
                self.assertFalse(panel.outer.winfo_ismapped())
                for _ in range(3):  # schnell hin und her: am Ende offen
                    panel.toggle()
                    pump(root, 0.03)
                    panel.toggle()
                    pump(root, 0.02)
                panel.toggle()
                pump(root, 0.4)
                self.assertTrue(panel.visible and panel.outer.winfo_ismapped())
                self.assertEqual(panel.outer.winfo_width(), full)
                app.set_mode("room")  # Moduswechsel: sofort weg, ohne Gleiten
                root.update()
                self.assertFalse(panel.outer.winfo_ismapped())
                app.set_mode("chat")  # und sofort wieder da
                root.update()
                self.assertTrue(panel.outer.winfo_ismapped())
                self.assertEqual(panel.outer.winfo_width(), full)

                # Galerie: zuletzt gezeigte Bilder bleiben dekodiert, eine geänderte Datei wird neu gelesen
                import galerie
                ims = app.images
                ims.gallery = galerie.Gallery(data / "bilder")
                pic = tk.PhotoImage(master=root, width=64, height=48)
                pic.put("#d97757", to=(0, 0, 64, 48))
                pic.write(str(data / "probe.png"), format="png")
                a = ims.gallery.add((data / "probe.png").read_bytes(), {"prompt": "a", "width": 64, "height": 48})
                b = ims.gallery.add((data / "probe.png").read_bytes(), {"prompt": "b", "width": 64, "height": 48})
                app.set_mode("images")
                root.update()
                ims.show_image(a)
                first = ims._full
                ims.show_image(b)
                ims.show_image(a)
                self.assertIs(ims._full, first)  # nicht neu dekodiert
                pic.put("#3b82f6", to=(0, 0, 64, 48))
                pic.write(str(ims.gallery.path(a)), format="png")
                ims.show_image(b)
                ims.show_image(a)
                self.assertIsNot(ims._full, first)  # Datei geändert: neu gelesen
                for i in range(8):  # höchstens PHOTO_CACHE Bilder bleiben
                    ims.show_image(ims.gallery.add((data / "probe.png").read_bytes(), {"prompt": str(i)}))
                import bilder
                self.assertLessEqual(len(ims._photos), bilder.PHOTO_CACHE)
            finally:
                app.on_close()


if __name__ == "__main__":
    unittest.main()
