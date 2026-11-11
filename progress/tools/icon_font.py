"""Baut app/fonts/MonhipIcons.ttf: genau die Symbole aus icons.FLUENT, aus Fluent UI System Icons (Microsoft,
MIT-Lizenz), ab U+E000 in der Reihenfolge von FLUENT. Monhip nutzt die Schrift unter Linux (unter Windows: Segoe).

    python3 progress/tools/icon_font.py FluentSystemIcons-Regular.ttf FluentSystemIcons-Filled.ttf

Die beiden Schriften und ihre .json-Dateien (Name → Zeichen) kommen aus
https://github.com/microsoft/fluentui-system-icons/tree/main/fonts – die .json muss neben der .ttf liegen.
Braucht fontTools (Debian/Ubuntu: python3-fonttools); Monhip selbst braucht es nicht.
"""

import json
import sys
from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app"))
from icons import FLUENT, LINUX_FAMILY  # noqa: E402

OUT = REPO / "app" / "fonts" / "MonhipIcons.ttf"
EM = 500  # wie die Fluent-Schriften
# So viele Einheiten tiefer als im Original: Fluent-Symbole stehen ganz über der Grundlinie und säßen in Textfeldern
# über der Mitte der Großbuchstaben (die Bilder in Knöpfen zentriert icons.py ohnehin nach dem Umriss)
SHIFT = 75


def source(path: str):
    font = TTFont(path)
    names = json.loads(Path(path).with_suffix(".json").read_text(encoding="utf-8"))
    return font, font.getGlyphSet(), font.getBestCmap(), names


def main(regular: str, filled: str):
    sources = {"regular": source(regular), "filled": source(filled)}
    glyphs, metrics, cmap = {}, {}, {0x20: "space"}
    empty = TTGlyphPen(None).glyph()
    for gname in (".notdef", "space"):
        glyphs[gname], metrics[gname] = empty, (EM, 0)
    for i, (name, fluent) in enumerate(FLUENT.items()):
        style = fluent.rsplit("_", 1)[1]
        font, glyph_set, font_cmap, names = sources[style]
        codepoint = names[f"ic_fluent_{fluent}"]
        src = glyph_set[font_cmap[codepoint]]
        pen = TTGlyphPen(glyph_set)  # Komponenten werden dabei aufgelöst
        src.draw(TransformPen(pen, (1, 0, 0, 1, 0, -SHIFT)))
        bounds = BoundsPen(glyph_set)
        src.draw(bounds)
        glyphs[name] = pen.glyph()
        metrics[name] = (src.width, round(bounds.bounds[0]) if bounds.bounds else 0)
        cmap[0xE000 + i] = name

    fb = FontBuilder(EM, isTTF=True)
    fb.setupGlyphOrder(list(glyphs))
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=EM - SHIFT, descent=-SHIFT)
    fb.setupNameTable({
        "familyName": LINUX_FAMILY, "styleName": "Regular", "uniqueFontIdentifier": "MonhipIcons-Regular",
        "fullName": f"{LINUX_FAMILY} Regular", "psName": "MonhipIcons-Regular", "version": "Version 1.0",
        "copyright": "Copyright (c) 2020 Microsoft Corporation (Fluent UI System Icons)",
        "licenseDescription": "MIT License – see LICENSE-FluentSystemIcons.txt",
    })
    fb.setupOS2(sTypoAscender=EM - SHIFT, sTypoDescender=-SHIFT, sTypoLineGap=0, usWinAscent=EM - SHIFT,
                usWinDescent=SHIFT, fsType=0)
    fb.setupPost()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fb.save(OUT)
    print(f"{OUT.relative_to(REPO)}: {len(FLUENT)} Symbole, {OUT.stat().st_size} Bytes")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
