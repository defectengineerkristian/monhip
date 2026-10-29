"""PDF aus Markdown erzeugen (Werkzeug create_pdf) – in reinem Python, ohne Word.

Schriften von Windows (Segoe UI, Consolas; fehlende Zeichen aus Segoe UI Symbol) werden eingebettet, aber nur mit
den benutzten Zeichen (Teilmenge): volle Unicode-Unterstützung bei kleinen Dateien. Ablauf: TrueType lesen (_Font)
→ Markdown in Blöcke (wie office.write_docx) → Zeilen nach echten Zeichenbreiten umbrechen (_Doc) → Seiten →
PDF-Objekte (Type0/CIDFontType2 mit Identity-H, ToUnicode – Text lässt sich kopieren und durchsuchen).
"""

import hashlib
import math
import os
import re
import struct
import urllib.parse
import zlib
from datetime import datetime
from pathlib import Path

from markdown_lite import ListLevels, alignment, classify, closes_fence, inline, is_separator_row, plain, split_row

FONTS_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
FACES = {  # Schnitt → Dateien (erste vorhandene gewinnt)
    "regular": ("segoeui.ttf", "arial.ttf"), "bold": ("segoeuib.ttf", "arialbd.ttf"),
    "italic": ("segoeuii.ttf", "ariali.ttf"), "bolditalic": ("segoeuiz.ttf", "arialbi.ttf"),
    "mono": ("consola.ttf", "cour.ttf"), "symbol": ("seguisym.ttf",),
}
PAGE_W, PAGE_H = 595.28, 841.89          # A4 in Punkt
LEFT, RIGHT, TOP, BOTTOM = 62.4, 62.4, 62.4, 68.0
WIDTH = PAGE_W - LEFT - RIGHT
BODY = 10.5                              # Grundschrift in Punkt
LEAD = 1.42                              # Zeilenhöhe je Schriftgröße
HEADINGS = {1: (18, 14, 6), 2: (14.5, 12, 5), 3: (12.5, 10, 4), 4: (11, 8, 3)}  # Größe, Abstand davor, danach
TEXT, MUTED, LINK, RULE = (0.12, 0.12, 0.14), (0.42, 0.42, 0.46), (0.10, 0.37, 0.71), (0.75, 0.75, 0.78)
CODE_BG, HEAD_BG = (0.95, 0.95, 0.96), (0.87, 0.92, 0.97)
BULLETS = ["•", "◦", "▪"]


class PdfError(Exception):
    pass


# ====================================================================== TrueType lesen und verkleinern

class _Font:
    def __init__(self, path: Path):
        d = self.data = path.read_bytes()
        if d[:4] not in (b"\x00\x01\x00\x00", b"true"):
            raise PdfError(f"{path.name} ist keine TrueType-Schrift.")
        n = struct.unpack(">H", d[4:6])[0]
        self.tables = {d[12 + 16 * i:16 + 16 * i].decode("latin1"): struct.unpack(">II", d[20 + 16 * i:28 + 16 * i])
                       for i in range(n)}
        if "glyf" not in self.tables:
            raise PdfError(f"{path.name}: Schriften mit CFF-Umrissen werden nicht unterstützt.")
        head, hhea, os2 = self._t("head"), self._t("hhea"), self._t("OS/2")
        if os2 and struct.unpack(">H", os2[8:10])[0] & 0x000F == 0x0002:  # fsType: „Restricted License“
            raise PdfError(f"{path.name} darf laut Lizenz nicht eingebettet werden.")
        self.upem = struct.unpack(">H", head[18:20])[0]
        self.bbox = struct.unpack(">hhhh", head[36:44])
        self.long_loca = struct.unpack(">h", head[50:52])[0] == 1
        self.ascent, self.descent = struct.unpack(">hh", hhea[4:8])
        n_metrics = struct.unpack(">H", hhea[34:36])[0]
        self.glyphs = struct.unpack(">H", self._t("maxp")[4:6])[0]
        hmtx = self._t("hmtx")
        adv = [struct.unpack(">H", hmtx[4 * i:4 * i + 2])[0] for i in range(n_metrics)]
        self.advances = adv + [adv[-1]] * (self.glyphs - n_metrics)  # danach gilt die letzte Breite weiter
        version = struct.unpack(">H", os2[0:2])[0] if os2 else 0
        self.cap = struct.unpack(">h", os2[88:90])[0] if version >= 2 and len(os2) >= 90 else round(self.ascent * 0.7)
        post = self._t("post")
        self.italic = struct.unpack(">i", post[4:8])[0] / 65536 if post else 0
        self.fixed = bool(post and struct.unpack(">I", post[12:16])[0])
        self.cmap = self._cmap()
        self.name = re.sub(r"[^A-Za-z0-9-]", "", self._ps_name() or path.stem) or "Font"
        self.used: dict[int, str] = {0: ""}  # Glyph → Zeichen (für ToUnicode)
        self.ref = ""                        # Name in den Seiten-Ressourcen (/F1 …)

    def _t(self, tag: str) -> bytes:
        if tag not in self.tables:
            return b""
        off, length = self.tables[tag]
        return self.data[off:off + length]

    def _cmap(self) -> dict[int, int]:
        """Zeichen → Glyph aus den Unicode-Tabellen (Format 4 für die Grundebene, Format 12 für den Rest)."""
        d, out = self._t("cmap"), {}
        subs = [struct.unpack(">HHI", d[4 + 8 * i:12 + 8 * i]) for i in range(struct.unpack(">H", d[2:4])[0])]
        for pid, eid, off in subs:
            if (pid, eid) not in ((3, 1), (3, 10), (0, 3), (0, 4)):
                continue
            fmt = struct.unpack(">H", d[off:off + 2])[0]
            if fmt == 12:
                for g in range(struct.unpack(">I", d[off + 12:off + 16])[0]):
                    start, end, gid = struct.unpack(">III", d[off + 16 + 12 * g:off + 28 + 12 * g])
                    for c in range(start, end + 1):
                        out.setdefault(c, gid + c - start)
            elif fmt == 4:
                seg = struct.unpack(">H", d[off + 6:off + 8])[0] // 2
                ends = struct.unpack(f">{seg}H", d[off + 14:off + 14 + 2 * seg])
                starts = struct.unpack(f">{seg}H", d[off + 16 + 2 * seg:off + 16 + 4 * seg])
                deltas = struct.unpack(f">{seg}h", d[off + 16 + 4 * seg:off + 16 + 6 * seg])
                ro = off + 16 + 6 * seg
                ranges = struct.unpack(f">{seg}H", d[ro:ro + 2 * seg])
                for i in range(seg):
                    for c in range(starts[i], min(ends[i], 0xFFFE) + 1):
                        if ranges[i]:
                            a = ro + 2 * i + ranges[i] + 2 * (c - starts[i])
                            gid = struct.unpack(">H", d[a:a + 2])[0]
                            gid = (gid + deltas[i]) & 0xFFFF if gid else 0
                        else:
                            gid = (c + deltas[i]) & 0xFFFF
                        if gid:
                            out.setdefault(c, gid)
        return out

    def _ps_name(self) -> str:
        d = self._t("name")
        if not d:
            return ""
        count, strings = struct.unpack(">HH", d[2:6])
        for i in range(count):
            pid, eid, lid, nid, length, off = struct.unpack(">6H", d[6 + 12 * i:18 + 12 * i])
            raw = d[strings + off:strings + off + length]
            if nid == 6:
                return raw.decode("utf-16-be" if pid in (0, 3) else "latin1", "replace")
        return ""

    def width(self, gid: int) -> int:
        """Vorschub in 1/1000 Geviert (PDF-Einheit)."""
        return round(self.advances[gid] * 1000 / self.upem) if gid < len(self.advances) else 0

    def subset(self) -> bytes:
        """Schriftdatei nur mit den benutzten Glyphen (samt Bestandteilen zusammengesetzter): die übrigen bleiben als
        leere Einträge stehen, so gelten die Glyph-Nummern unverändert (CIDToGIDMap /Identity)."""
        loca_raw = self._t("loca")
        loca = (struct.unpack(f">{self.glyphs + 1}I", loca_raw[:4 * (self.glyphs + 1)]) if self.long_loca else
                [2 * v for v in struct.unpack(f">{self.glyphs + 1}H", loca_raw[:2 * (self.glyphs + 1)])])
        glyf = self._t("glyf")
        need, todo = set(), list(self.used)
        while todo:
            g = todo.pop()
            if g in need or g >= self.glyphs:
                continue
            need.add(g)
            data = glyf[loca[g]:loca[g + 1]]
            if len(data) >= 10 and struct.unpack(">h", data[:2])[0] < 0:
                todo += _components(data)
        out, offsets = bytearray(), []
        for g in range(self.glyphs):
            offsets.append(len(out))
            if g in need:
                out += glyf[loca[g]:loca[g + 1]]
                out += b"\0" * (-len(out) % 4)
        offsets.append(len(out))
        head = bytearray(self._t("head"))
        head[8:12] = b"\0\0\0\0"                 # checkSumAdjustment – liest beim Einbetten niemand
        head[50:52] = struct.pack(">h", 1)       # lange loca
        tables = {"head": bytes(head), "hhea": self._t("hhea"), "maxp": self._t("maxp"), "hmtx": self._t("hmtx"),
                  "loca": struct.pack(f">{len(offsets)}I", *offsets), "glyf": bytes(out)}
        for tag in ("cvt ", "fpgm", "prep"):  # Hinting – gehört zu den Glyphen, klein
            if tag in self.tables:
                tables[tag] = self._t(tag)
        return _sfnt(tables)


def _components(glyph: bytes) -> list[int]:
    """Glyphen, aus denen eine zusammengesetzte Glyphe besteht (z. B. „ä“ = „a“ + Punkte)."""
    out, pos = [], 10
    while pos + 4 <= len(glyph):
        flags, gid = struct.unpack(">HH", glyph[pos:pos + 4])
        out.append(gid)
        pos += 4 + (4 if flags & 0x0001 else 2)
        pos += 2 if flags & 0x0008 else 4 if flags & 0x0040 else 8 if flags & 0x0080 else 0
        if not flags & 0x0020:
            break
    return out


def _sfnt(tables: dict[str, bytes]) -> bytes:
    tags = sorted(tables)
    sel = int(math.log2(len(tags)))
    head = struct.pack(">IHHHH", 0x00010000, len(tags), 16 << sel, sel, 16 * len(tags) - (16 << sel))
    directory, body, offset = b"", b"", 12 + 16 * len(tags)
    for tag in tags:
        data = tables[tag]
        padded = data + b"\0" * (-len(data) % 4)
        checksum = sum(struct.unpack(f">{len(padded) // 4}I", padded)) & 0xFFFFFFFF
        directory += struct.pack(">4sIII", tag.encode("latin1"), checksum, offset + len(body), len(data))
        body += padded
    return head + directory + body


# ====================================================================== Satz

class _Doc:
    def __init__(self):
        self.fonts: dict[str, _Font | None] = {}
        self.pages: list[list[str]] = []
        self.links: list[list[tuple]] = []
        self.y = 0.0
        self.new_page()

    # ---------------------------------------------------------------- Schriften und Breiten

    def font(self, face: str) -> _Font | None:
        if face not in self.fonts:
            self.fonts[face] = None
            for name in FACES[face]:
                if (FONTS_DIR / name).is_file():
                    self.fonts[face] = _Font(FONTS_DIR / name)
                    break
            if self.fonts[face] is None and face != "symbol" and face != "regular":
                self.fonts[face] = self.font("regular")
            if self.fonts[face] is None and face == "regular":
                raise PdfError("Keine passende Schrift gefunden (Segoe UI oder Arial).")
        return self.fonts[face]

    def shape(self, text: str, face: str) -> list[tuple[_Font, list[int], int]]:
        """Text → [(Schrift, Glyphen, Breite in 1/1000)]; fehlende Zeichen aus Segoe UI Symbol, sonst „?“."""
        main, out = self.font(face), []
        for ch in text:
            font, gid = main, main.cmap.get(ord(ch))
            if gid is None:
                sym = self.font("symbol")
                gid = sym.cmap.get(ord(ch)) if sym else None
                font = sym if gid is not None else main
                if gid is None:
                    ch, gid = "?", main.cmap.get(ord("?"), 0)
            font.used.setdefault(gid, ch)
            if out and out[-1][0] is font:
                out[-1][1].append(gid)
                out[-1] = (font, out[-1][1], out[-1][2] + font.width(gid))
            else:
                out.append((font, [gid], font.width(gid)))
        return out

    def measure(self, text: str, face: str, size: float) -> float:
        return sum(w for _, _, w in self.shape(text, face)) * size / 1000

    # ---------------------------------------------------------------- Seiten und Zeichnen

    def new_page(self):
        self.pages.append([])
        self.links.append([])
        self.y = PAGE_H - TOP

    def room(self, height: float):
        """Neue Seite, wenn height nicht mehr passt (nicht auf einer leeren Seite)."""
        if self.y - height < BOTTOM and self.y < PAGE_H - TOP - 1:
            self.new_page()

    def text(self, x: float, baseline: float, text: str, face: str, size: float, color=TEXT, ops=None) -> float:
        ops, x0 = self.pages[-1] if ops is None else ops, x
        for font, gids, w in self.shape(text, face):
            ops.append(f"BT /{self._ref(font)} {size:.2f} Tf {_rgb(color)} rg {x:.2f} {baseline:.2f} Td "
                       f"<{''.join(f'{g:04X}' for g in gids)}> Tj ET")
            x += w * size / 1000
        return x - x0

    def _ref(self, font: _Font) -> str:
        if not font.ref:
            font.ref = f"F{sum(1 for f in set(self.fonts.values()) if f and f.ref) + 1}"
        return font.ref

    def rect(self, x, y, w, h, color):
        self.pages[-1].append(f"{_rgb(color)} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")

    def line(self, x0, y0, x1, y1, color=RULE, width=0.6):
        self.pages[-1].append(f"{_rgb(color)} RG {width:.2f} w {x0:.2f} {y0:.2f} m {x1:.2f} {y1:.2f} l S")

    # ---------------------------------------------------------------- Absätze

    def runs(self, text: str, face: str, size: float, color=TEXT, extra=frozenset()) -> list[dict]:
        """Markdown-Zeile → Stücke {text, face, size, color, url, strike, code}."""
        out = []
        for seg, styles, url in inline(_clean(text)):
            styles = styles | extra
            code = "code" in styles
            bold = "b" in styles or face in ("bold", "bolditalic")
            italic = "i" in styles or face in ("italic", "bolditalic")
            f = ("mono" if code else "bolditalic" if bold and italic else "bold" if bold else "italic" if italic
                 else "regular")
            out.append({"text": seg, "face": f, "size": size * 0.92 if code else size, "color": LINK if url else color,
                        "url": url, "strike": "s" in styles, "code": code})
        return out

    def wrap(self, runs: list[dict], width: float) -> list[list[dict]]:
        """Stücke in Zeilen umbrechen (an Leerzeichen; zu lange Wörter zeichenweise)."""
        lines, cur, used = [], [], 0.0

        def push(piece, w):
            nonlocal used
            if cur and cur[-1]["style"] is piece["style"]:
                cur[-1]["text"] += piece["text"]
                cur[-1]["w"] += w
            else:
                cur.append({**piece, "w": w})
            used += w

        for run in runs:
            for token in re.split(r"(\s+)", run["text"]):
                if not token:
                    continue
                piece = {"text": token, "style": run}
                w = self.measure(token, run["face"], run["size"])
                if token.isspace():
                    if cur:
                        push({"text": " ", "style": run}, self.measure(" ", run["face"], run["size"]))
                    continue
                if used + w > width and cur:
                    while cur and cur[-1]["text"].isspace():
                        used -= cur.pop()["w"]
                    lines.append(cur)
                    cur, used = [], 0.0
                while w > width:  # Wort länger als die Zeile: zeichenweise teilen
                    cut = len(token)
                    while cut > 1 and self.measure(token[:cut], run["face"], run["size"]) > width - used:
                        cut -= 1
                    push({"text": token[:cut], "style": run}, self.measure(token[:cut], run["face"], run["size"]))
                    lines.append(cur)
                    cur, used = [], 0.0
                    token = token[cut:]
                    w = self.measure(token, run["face"], run["size"])
                    piece = {"text": token, "style": run}
                if token:
                    push(piece, w)
        while cur and cur[-1]["text"].isspace():
            used -= cur.pop()["w"]
        if cur or not lines:
            lines.append(cur)
        return lines

    def paragraph(self, runs: list[dict], x: float, width: float, before=0.0, after=0.0, bar=None, keep=0.0,
                  align="left", first=None) -> None:
        """Absatz setzen; bar: senkrechte Linie links (Zitat); keep: so viel Platz muss danach noch sein (Überschrift);
        first: (Text, Schnitt, Größe, Farbe) vor der ersten Zeile – Aufzählungszeichen/Nummer links von x."""
        size = max((r["size"] for r in runs), default=BODY)
        lh = size * LEAD
        lines = self.wrap(runs, width)
        self.y -= before
        self.room(lh * min(len(lines), 2) + keep)
        for i, line in enumerate(lines):
            if i:
                self.room(lh)
            base = self.y - size * 1.12
            if first and i == 0:
                label, face, fsize, color = first
                self.text(x - self.measure(label, face, fsize) - 5, base, label, face, fsize, color)
            w = sum(p["w"] for p in line)
            cx = x + (width - w if align == "right" else (width - w) / 2 if align == "center" else 0)
            for p in line:
                st = p["style"]
                if st["code"] and p["text"].strip():
                    self.rect(cx - 1, base - st["size"] * 0.25, p["w"] + 2, st["size"] * 1.2, CODE_BG)
                self.text(cx, base, p["text"], st["face"], st["size"], st["color"])
                if st["url"] and p["text"].strip():
                    self.line(cx, base - 1.2, cx + p["w"], base - 1.2, LINK, 0.5)
                    self.links[-1].append((cx, base - st["size"] * 0.25, cx + p["w"], base + st["size"] * 0.9,
                                           st["url"]))
                if st["strike"]:
                    self.line(cx, base + st["size"] * 0.3, cx + p["w"], base + st["size"] * 0.3, st["color"], 0.6)
                cx += p["w"]
            if bar:
                self.rect(bar, self.y - lh, 2.2, lh, RULE)
            self.y -= lh
        self.y -= after

    # ---------------------------------------------------------------- Blöcke

    def code_block(self, lines: list[str]):
        size, pad = 8.8, 6.0
        lh = size * 1.35
        rows = []
        for line in lines or [""]:
            line = _clean(line.expandtabs(4)).rstrip()
            if not line:
                rows.append("")
            while line:  # zu lange Zeilen zeichenweise umbrechen
                cut = len(line)
                while cut > 1 and self.measure(line[:cut], "mono", size) > WIDTH - 2 * pad:
                    cut -= 1
                rows.append(line[:cut])
                line = line[cut:]
        self.y -= 4
        self.room(lh * min(len(rows), 3) + 2 * pad)
        start, top = 0, self.y
        self.y -= pad
        for i, row in enumerate(rows):
            if self.y - lh < BOTTOM:  # Seite voll: bisherigen Teil mit Hintergrund setzen, auf der nächsten weiter
                self._code_part(rows[start:i], top, size, pad, lh)
                self.new_page()
                start, top = i, self.y
                self.y -= pad
            self.y -= lh
        self._code_part(rows[start:], top, size, pad, lh)
        self.y = top - pad - lh * len(rows[start:]) - pad - 8

    def _code_part(self, rows: list[str], top: float, size: float, pad: float, lh: float):
        bottom = top - 2 * pad - lh * len(rows)
        self.rect(LEFT, bottom, WIDTH, top - bottom, CODE_BG)
        for i, row in enumerate(rows):
            self.text(LEFT + pad, top - pad - lh * i - size * 1.05, row, "mono", size)

    def table(self, rows: list[str]):
        cells = [split_row(r) for r in rows]
        header, aligns, body = None, [], cells
        if len(cells) >= 2 and is_separator_row(cells[1]):
            header, aligns, body = cells[0], [alignment(c) for c in cells[1]], cells[2:]
        else:
            body = [c for c in cells if not is_separator_row(c)]
        all_rows = ([header] if header else []) + body
        if not all_rows:
            return
        n = max(len(r) for r in all_rows)
        size, pad = 9.5, 4.5
        natural = [max(self.measure(plain(r[c]) if c < len(r) else "", "bold", size) for r in all_rows) + 2 * pad
                   for c in range(n)]
        widths = [max(36.0, w) for w in natural]
        if sum(widths) > WIDTH:  # zu breit: breite Spalten schrumpfen, schmale behalten ihre Breite
            fair = WIDTH / n
            small = sum(w for w in widths if w <= fair)
            big = [w for w in widths if w > fair]
            k = (WIDTH - small) / sum(big) if big else 1
            widths = [w if w <= fair else max(36.0, w * k) for w in widths]
        scale = WIDTH / sum(widths) if sum(widths) > WIDTH else 1
        widths = [w * scale for w in widths]
        total = sum(widths)
        self.y -= 4

        def draw_row(row, head):
            wrapped = [self.wrap(self.runs(row[c] if c < len(row) else "", "bold" if head else "regular", size),
                                 widths[c] - 2 * pad) for c in range(n)]
            lh = size * LEAD
            height = max(len(w) for w in wrapped) * lh + 2 * pad
            if self.y - height < BOTTOM and self.y < PAGE_H - TOP - 1:
                self.line(LEFT, self.y, LEFT + total, self.y)
                self.new_page()
                if header and not head:
                    draw_row(header, True)
            top = self.y
            if head:
                self.rect(LEFT, top - height, total, height, HEAD_BG)
            x = LEFT
            for c in range(n):
                y = top - pad
                for line in wrapped[c]:
                    base = y - size * 1.12
                    w = sum(p["w"] for p in line)
                    a = aligns[c] if c < len(aligns) else "left"
                    cx = x + pad + (widths[c] - 2 * pad - w if a == "right" else
                                    (widths[c] - 2 * pad - w) / 2 if a == "center" else 0)
                    for p in line:
                        self.text(cx, base, p["text"], p["style"]["face"], p["style"]["size"], p["style"]["color"])
                        cx += p["w"]
                    y -= lh
                x += widths[c]
            self.line(LEFT, top, LEFT + total, top)
            x = LEFT
            for w in [0] + widths:
                x += w
                self.line(x, top, x, top - height)
            self.y = top - height
            self.line(LEFT, self.y, LEFT + total, self.y)

        for i, row in enumerate(all_rows):
            draw_row(row, header is not None and i == 0)
        self.y -= 10


def _rgb(c) -> str:
    return " ".join(f"{v:.3f}" for v in c)


def _clean(text: str) -> str:
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f\xad]", "", text.replace("\t", "    "))


def _roman(n: int) -> str:
    out = ""
    for v, s in ((10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out, n = out + s, n - v
    return out


def _label(level: int, n: int) -> str:
    return f"{n}." if level % 3 == 0 else f"{chr(96 + (n - 1) % 26 + 1)})" if level % 3 == 1 else f"{_roman(n)}."


# ====================================================================== Markdown → Seiten

def _build(doc: _Doc, markdown: str, title: str):
    if title:
        doc.paragraph(doc.runs(title, "bold", 22), LEFT, WIDTH, after=10)
    lines = markdown.replace("\r\n", "\n").split("\n")
    table, code, para = [], None, []
    levels, counters = ListLevels(), {}
    skip_title = bool(title)

    def flush_para():
        if para:
            for i, text in enumerate(para):  # jede Zeile eigene Zeile (wie im Word-Export)
                doc.paragraph(doc.runs(text, "regular", BODY), LEFT, WIDTH, after=5 if i == len(para) - 1 else 0)
            para.clear()

    for line in lines:
        if code is not None:
            if closes_fence(line, code["fence"]):
                doc.code_block(code["lines"])
                code = None
            else:
                code["lines"].append(line)
            continue
        kind, info = classify(line)
        if kind != "table" and table:
            doc.table(table)
            table = []
        if kind != "text":
            flush_para()
        if kind not in ("bullet", "number", "blank"):
            levels.reset()
            counters.clear()
        if kind == "blank":
            continue
        if kind == "fence":
            code = {**info, "lines": []}
        elif kind == "table":
            table.append(line)
        elif kind == "heading":
            if skip_title and info["level"] == 1 and info["text"].strip().lower() == title.strip().lower():
                skip_title = False
                continue
            size, before, after = HEADINGS[min(info["level"], 4)]
            doc.paragraph(doc.runs(info["text"], "bold", size), LEFT, WIDTH, before=before, after=after,
                          keep=BODY * LEAD * 2)
        elif kind == "hr":
            doc.y -= 6
            doc.room(8)
            doc.line(LEFT, doc.y, LEFT + WIDTH, doc.y)
            doc.y -= 8
        elif kind == "pagebreak":
            doc.new_page()
        elif kind in ("bullet", "number"):
            lvl = min(levels.level(info["indent"]), 6)
            for deeper in [k for k in counters if k > lvl]:
                del counters[deeper]
            if kind == "bullet":
                label = BULLETS[lvl % len(BULLETS)]
            else:
                counters[lvl] = counters.get(lvl, int(info["num"]) if lvl == 0 else 1) + (1 if lvl in counters else 0)
                label = _label(lvl, counters[lvl])
            text = (info.get("task") + " " if info.get("task") else "") + info["text"]
            x = LEFT + 16 + 16 * lvl
            doc.paragraph(doc.runs(text, "regular", BODY), x, WIDTH - (x - LEFT), after=2.5,
                          first=(label, "regular", BODY, MUTED if kind == "bullet" else TEXT))
        elif kind == "quote":
            doc.paragraph(doc.runs(info["text"], "italic", BODY, MUTED), LEFT + 14, WIDTH - 14, after=3,
                          bar=LEFT + 2)
        else:
            para.append(info["text"])
    flush_para()
    if code is not None:
        doc.code_block(code["lines"])
    if table:
        doc.table(table)


# ====================================================================== PDF schreiben

def write_pdf(path, markdown: str, title: str = "") -> int:
    """Schreibt das PDF und gibt die Seitenzahl zurück."""
    path = Path(path)
    doc = _Doc()
    _build(doc, markdown or "", (title or "").strip())
    while len(doc.pages) > 1 and not doc.pages[-1]:  # leere Seite am Ende (z. B. nach \newpage)
        doc.pages.pop()
        doc.links.pop()
    total = len(doc.pages)
    for i, ops in enumerate(doc.pages):  # Seitenzahlen unten in der Mitte
        label = f"{i + 1} / {total}"
        doc.text((PAGE_W - doc.measure(label, "regular", 8.5)) / 2, BOTTOM / 2 - 3, label, "regular", 8.5, MUTED,
                 ops=ops)
    path.write_bytes(_pdf(doc, title or path.stem))
    return total


def _pdf(doc: _Doc, title: str) -> bytes:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    def stream(data: bytes, extra: str = "") -> int:
        z = zlib.compress(data, 9)
        return add(f"<< /Length {len(z)} /Filter /FlateDecode{extra} >>\nstream\n".encode() + z + b"\nendstream")

    fonts = []
    for font in {id(f): f for f in doc.fonts.values() if f and f.ref}.values():
        tag = "".join(chr(65 + b % 26) for b in hashlib.md5((font.name + str(sorted(font.used))).encode()).digest()[:6])
        name = f"{tag}+{font.name}"
        k = 1000 / font.upem
        data = font.subset()
        file_ref = stream(data, f" /Length1 {len(data)}")
        flags = (1 if font.fixed else 0) | (4 if font.name.lower().startswith("segoeuisymbol") else 32) | (
            64 if font.italic else 0)
        desc = add(f"<< /Type /FontDescriptor /FontName /{name} /Flags {flags} /FontBBox "
                   f"[{' '.join(str(round(v * k)) for v in font.bbox)}] /ItalicAngle {font.italic:.1f} "
                   f"/Ascent {round(font.ascent * k)} /Descent {round(font.descent * k)} /CapHeight "
                   f"{round(font.cap * k)} /StemV 80 /FontFile2 {file_ref} 0 R >>".encode())
        cid = add(f"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /{name} /CIDSystemInfo << /Registry (Adobe) "
                  f"/Ordering (Identity) /Supplement 0 >> /FontDescriptor {desc} 0 R /DW 1000 "
                  f"/W [{_widths(font)}] /CIDToGIDMap /Identity >>".encode())
        cmap = stream(_to_unicode(font))
        fonts.append((font.ref, add(f"<< /Type /Font /Subtype /Type0 /BaseFont /{name} /Encoding /Identity-H "
                                    f"/DescendantFonts [{cid} 0 R] /ToUnicode {cmap} 0 R >>".encode())))
    resources = "<< /Font << " + " ".join(f"/{ref} {num} 0 R" for ref, num in fonts) + " >> >>"
    pages_num = len(objects) + 2 * len(doc.pages) + sum(len(l) for l in doc.links) + 1  # Nummer des Seitenbaums
    kids = []
    for ops, links in zip(doc.pages, doc.links):
        content = stream("\n".join(ops).encode("latin1"))
        annots = [add(f"<< /Type /Annot /Subtype /Link /Rect [{x0:.2f} {y0:.2f} {x1:.2f} {y1:.2f}] /Border [0 0 0] "
                      f"/A << /S /URI /URI <{_uri(url).hex()}> >> >>".encode()) for x0, y0, x1, y1, url in links]
        kids.append(add((f"<< /Type /Page /Parent {pages_num} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] /Resources "
                         f"{resources} /Contents {content} 0 R"
                         + (f" /Annots [{' '.join(f'{a} 0 R' for a in annots)}]" if annots else "") + " >>").encode()))
    assert add(f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()) \
        == pages_num
    info = add(f"<< /Title <FEFF{title.encode('utf-16-be').hex()}> /Producer (Monhip) "
               f"/CreationDate (D:{datetime.now():%Y%m%d%H%M%S}) >>".encode())
    root = add(f"<< /Type /Catalog /Pages {pages_num} 0 R >>".encode())
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root {root} 0 R /Info {info} 0 R >>\nstartxref\n{xref}\n%%EOF\n" \
        .encode()
    return bytes(out)


def _widths(font: _Font) -> str:
    """Breiten der benutzten Glyphen: „gid [w1 w2 …]“ je Folge aufeinanderfolgender Nummern."""
    parts, run, start = [], [], None
    for g in sorted(font.used):
        if run and g == start + len(run):
            run.append(font.width(g))
        else:
            if run:
                parts.append(f"{start} [{' '.join(map(str, run))}]")
            start, run = g, [font.width(g)]
    if run:
        parts.append(f"{start} [{' '.join(map(str, run))}]")
    return " ".join(parts)


def _to_unicode(font: _Font) -> bytes:
    """ToUnicode-CMap: Glyph → Zeichen (zum Kopieren und Durchsuchen des Texts)."""
    pairs = [(g, ch) for g, ch in sorted(font.used.items()) if ch]
    blocks = []
    for i in range(0, len(pairs), 100):
        chunk = pairs[i:i + 100]
        blocks.append(f"{len(chunk)} beginbfchar\n" + "\n".join(f"<{g:04X}> <{ch.encode('utf-16-be').hex().upper()}>"
                                                                  for g, ch in chunk) + "\nendbfchar")
    return ("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n/CIDSystemInfo << /Registry (Adobe) "
            "/Ordering (UCS) /Supplement 0 >> def\n/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
            "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n" + "\n".join(blocks)
            + "\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend").encode()


def _uri(url: str) -> bytes:
    return urllib.parse.quote(url, safe=":/?#[]@!$&'()*+,;=%~").encode("ascii")
