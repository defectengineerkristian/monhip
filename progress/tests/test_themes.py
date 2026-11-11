"""Design-Bilder: Die schnelle Fassung von themes._rounded_png (Form zwischengespeichert, Farben je Abdeckung nur
einmal gemischt) liefert genau dieselben Bytes wie das einfache Rechnen Pixel für Pixel: python -m unittest
tests.test_themes"""

import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import themes  # noqa: E402


def reference_png(r, mid, fill, border, under, bw, wide=None):
    """Die frühere Fassung: jedes Pixel einzeln aus Abstand und Farben."""
    wide = wide or mid
    fill_c, border_c, under_c = themes._rgb(fill), themes._rgb(border), themes._rgb(under)
    k = r + 1
    half = k + 0.5

    def color(x, y):
        qx, qy = abs(x - half) - (half - r), abs(y - half) - (half - r)
        d = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r
        outer = max(0.0, min(1.0, 0.5 - d))
        if not outer:
            return under_c
        inner = max(0.0, min(1.0, 0.5 - (d + bw)))
        return themes._mix(under_c, themes._mix(border_c, fill_c, inner / outer), outer)

    small = themes._pixels(2 * k + 1, 2 * k + 1, color)
    rows = [row[:3 * k] + row[3 * k:3 * k + 3] * wide + row[3 * k + 3:] for row in small]
    rows = rows[:k] + rows[k:k + 1] * mid + rows[k + 1:]
    return themes._png(2 * k + wide, 2 * k + mid, rows)


class RoundedImages(unittest.TestCase):
    def test_same_bytes_as_pixel_by_pixel(self):
        colors = [("#2b2a28", "#d97757", "#1f1e1d"), ("#ffffff", "#c8c4bb", "#f5f4ef"), ("#383733", "#383733", "#000000")]
        for r in (2, 5, 7, 9, 14, 21):
            for bw in (1, 2, 3):
                for fill, border, under in colors:
                    with self.subTest(r=r, bw=bw, fill=fill):
                        args = (r, 64, fill, border, under, bw)
                        self.assertEqual(themes._rounded_png(*args, wide=512), reference_png(*args, wide=512))
        self.assertEqual(themes._rounded_png(6, 3, "#ffffff", "#000000", "#808080", 1.5),
                         reference_png(6, 3, "#ffffff", "#000000", "#808080", 1.5))

    def test_cached(self):
        args = (8, 64, "#101010", "#202020", "#303030", 1)
        self.assertIs(themes._rounded_png(*args, wide=512), themes._rounded_png(*args, wide=512))


if __name__ == "__main__":
    unittest.main()
