"""Text aus am Computer erzeugten PDFs lesen (ohne Zusatzpakete) – nicht aus eingescannten oder verschlüsselten.

extract(daten) -> (Text mit „--- Seite n ---“-Markierungen, Seitenzahl)
"""

import base64
import re
import zlib


class PDFError(Exception):
    pass


class Ref(tuple):
    """Verweis „n g R“ auf ein anderes Objekt."""


class Name(str):
    pass


class Stream:
    def __init__(self, info: dict, raw: bytes):
        self.info, self.raw, self._data = info, raw, None


_TOKEN = re.compile(rb"""
    (?P<ws>(?:[\x00\t\n\x0c\r ]+|%[^\r\n]*)+)
  | (?P<dict><<|>>)
  | (?P<arr>[\[\]])
  | (?P<str>\()
  | (?P<hex><[0-9A-Fa-f\x00\t\n\x0c\r ]*>)
  | (?P<name>/[^\x00\t\n\x0c\r ()<>\[\]{}/%]*)
  | (?P<num>[+-]?(?:\d+\.?\d*|\.\d+))
  | (?P<op>[^\x00\t\n\x0c\r ()<>\[\]{}/%]+)
  | (?P<other>.)
""", re.X | re.S)
_ESC = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}


def _literal(data: bytes, pos: int) -> tuple[bytes, int]:
    """Liest einen (…)-String ab pos (direkt nach der öffnenden Klammer)."""
    out, depth, n = bytearray(), 1, len(data)
    while pos < n:
        c = data[pos]
        if c == 0x5C:  # Backslash
            pos += 1
            if pos >= n:
                break
            e = data[pos:pos + 1]
            if e in _ESC:
                out += _ESC[e]
            elif e in b"01234567":
                m = re.match(rb"[0-7]{1,3}", data[pos:pos + 3])
                out.append(int(m.group(), 8) & 0xFF)
                pos += len(m.group()) - 1
            elif e == b"\r":
                if data[pos + 1:pos + 2] == b"\n":
                    pos += 1
            elif e != b"\n":
                out += e
        elif c == 0x28:
            depth += 1
            out.append(c)
        elif c == 0x29:
            depth -= 1
            if depth == 0:
                return bytes(out), pos + 1
            out.append(c)
        else:
            out.append(c)
        pos += 1
    return bytes(out), pos


def _next(data: bytes, pos: int):
    """Nächstes Token: (art, wert, neue Position); art None am Ende."""
    while True:
        m = _TOKEN.match(data, pos)
        if not m:
            return None, None, len(data)
        kind = m.lastgroup
        if kind == "ws":
            pos = m.end()
            continue
        if kind == "str":
            s, end = _literal(data, m.end())
            return "str", s, end
        if kind == "hex":
            h = re.sub(rb"[^0-9A-Fa-f]", b"", m.group()[1:-1])
            return "str", bytes.fromhex((h + b"0" if len(h) % 2 else h).decode()), m.end()
        if kind == "name":
            raw = re.sub(rb"#([0-9A-Fa-f]{2})", lambda x: bytes([int(x.group(1), 16)]), m.group()[1:])
            return "name", Name(raw.decode("latin-1")), m.end()
        if kind == "num":
            t = m.group()
            return "num", (float(t) if b"." in t else int(t)), m.end()
        return kind, m.group(), m.end()


def _parse(data: bytes, pos: int, depth: int = 0):
    """Liest ein PDF-Objekt (Dictionary, Array, Zahl, Verweis, Name, String …)."""
    kind, val, pos = _next(data, pos)
    if depth > 60:
        return None, pos
    if kind == "dict" and val == b"<<":
        d = {}
        while True:
            k, v, p = _next(data, pos)
            if k is None or (k == "dict" and v == b">>"):
                return d, p
            if k != "name":
                pos = p
                continue
            d[v], pos = _parse(data, p, depth + 1)
    if kind == "arr" and val == b"[":
        arr = []
        while True:
            k, v, p = _next(data, pos)
            if k is None or (k == "arr" and v == b"]"):
                return arr, p
            item, pos = _parse(data, pos, depth + 1)
            arr.append(item)
    if kind == "num" and isinstance(val, int) and val >= 0:
        k2, v2, p2 = _next(data, pos)
        if k2 == "num" and isinstance(v2, int):
            k3, v3, p3 = _next(data, p2)
            if k3 == "op" and v3 == b"R":
                return Ref((val, v2)), p3
        return val, pos
    if kind == "op":
        return {b"true": True, b"false": False, b"null": None}.get(val, val), pos
    return val, pos


# ---------------------------------------------------------------- Zeichenkodierung

GLYPHS = {
    "space": " ", "exclam": "!", "quotedbl": '"', "numbersign": "#", "dollar": "$", "percent": "%",
    "ampersand": "&", "quotesingle": "'", "quoteright": "’", "quoteleft": "‘", "parenleft": "(", "parenright": ")",
    "asterisk": "*", "plus": "+", "comma": ",", "hyphen": "-", "minus": "−", "period": ".", "slash": "/",
    "colon": ":", "semicolon": ";", "less": "<", "equal": "=", "greater": ">", "question": "?", "at": "@",
    "bracketleft": "[", "backslash": "\\", "bracketright": "]", "asciicircum": "^", "underscore": "_",
    "grave": "`", "braceleft": "{", "bar": "|", "braceright": "}", "asciitilde": "~", "zero": "0", "one": "1",
    "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "quotedblleft": "“", "quotedblright": "”", "quotedblbase": "„", "quotesinglbase": "‚", "endash": "–",
    "emdash": "—", "bullet": "•", "ellipsis": "…", "Euro": "€", "adieresis": "ä", "odieresis": "ö",
    "udieresis": "ü", "Adieresis": "Ä", "Odieresis": "Ö", "Udieresis": "Ü", "germandbls": "ß", "eacute": "é",
    "egrave": "è", "ecircumflex": "ê", "aacute": "á", "agrave": "à", "acircumflex": "â", "ccedilla": "ç",
    "oacute": "ó", "uacute": "ú", "iacute": "í", "ntilde": "ñ", "Eacute": "É", "section": "§", "degree": "°",
    "copyright": "©", "registered": "®", "trademark": "™", "fi": "fi", "fl": "fl", "ff": "ff", "ffi": "ffi",
    "ffl": "ffl", "multiply": "×", "divide": "÷", "plusminus": "±", "paragraph": "¶", "periodcentered": "·",
    "guillemotleft": "«", "guillemotright": "»", "guilsinglleft": "‹", "guilsinglright": "›", "dagger": "†",
    "nbspace": " ", "sterling": "£", "yen": "¥", "cent": "¢", "mu": "µ",
}


def _glyph_char(name: str) -> str:
    if name in GLYPHS:
        return GLYPHS[name]
    m = re.fullmatch(r"uni([0-9A-Fa-f]{4})+", name)
    if m:
        return "".join(chr(int(name[i:i + 4], 16)) for i in range(3, len(name), 4))
    m = re.fullmatch(r"u([0-9A-Fa-f]{4,6})", name)
    if m:
        return chr(int(m.group(1), 16))
    base = name.split(".")[0].split("_")[0]
    return base if len(base) == 1 else GLYPHS.get(base, "")


class _CMap:
    """ToUnicode-Tabelle einer Schrift: Zeichencode (Bytes) → Text."""

    def __init__(self, data: bytes):
        self.single: dict[bytes, str] = {}
        self.ranges: list[tuple[bytes, bytes, object]] = []
        lengths = set()
        for block in re.findall(rb"begincodespacerange(.*?)endcodespacerange", data, re.S):
            for lo, _hi in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                lengths.add(len(lo) // 2)
        for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
            for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
                self.single[bytes.fromhex(src.decode())] = self._u(dst)
                lengths.add(len(src) // 2)
        for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
            for lo, hi, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]*>|\[[^\]]*\])", block):
                target = ([self._u(x) for x in re.findall(rb"<([0-9A-Fa-f]*)>", dst)] if dst.startswith(b"[")
                          else self._u(dst[1:-1]))
                self.ranges.append((bytes.fromhex(lo.decode()), bytes.fromhex(hi.decode()), target))
                lengths.add(len(lo) // 2)
        self.lengths = sorted(lengths or {1}, reverse=True)

    @staticmethod
    def _u(hexstr: bytes) -> str:
        raw = bytes.fromhex(hexstr.decode()) if hexstr else b""
        if len(raw) % 2:
            raw = b"\x00" + raw
        return raw.decode("utf-16-be", "replace")

    def lookup(self, code: bytes):
        if code in self.single:
            return self.single[code]
        for lo, hi, target in self.ranges:
            if len(code) == len(lo) and lo <= code <= hi:
                off = int.from_bytes(code, "big") - int.from_bytes(lo, "big")
                if isinstance(target, list):
                    return target[off] if off < len(target) else None
                if not target:
                    return None
                return target[:-1] + chr(ord(target[-1]) + off)
        return None

    def decode(self, data: bytes) -> str:
        out, i = [], 0
        while i < len(data):
            for n in self.lengths:
                ch = self.lookup(data[i:i + n]) if i + n <= len(data) else None
                if ch is not None:
                    out.append(ch)
                    i += n
                    break
            else:
                i += self.lengths[-1]
        return "".join(out)


class _SimpleFont:
    def __init__(self, table: dict[int, str], base: str):
        self.table, self.base = table, base

    def decode(self, data: bytes) -> str:
        out = []
        for b in data:
            ch = self.table.get(b)
            if ch is None:
                ch = bytes([b]).decode(self.base, "replace") if b >= 32 else ""
            out.append(ch)
        return "".join(out).replace("�", "")


class _Unreadable:
    @staticmethod
    def decode(_data: bytes) -> str:
        return ""


class _Font:
    """Schrift einer Seite: Text dekodieren und die Laufweite (in Geviert) berechnen."""

    def __init__(self, decoder, widths: dict[int, float] | None = None, default: float = 500.0, code_len: int = 1):
        self.decoder, self.widths, self.default, self.code_len = decoder, widths or {}, default, code_len

    def show(self, data: bytes) -> tuple[str, float]:
        n = self.code_len
        w = sum(self.widths.get(int.from_bytes(data[i:i + n], "big"), self.default)
                for i in range(0, len(data) - n + 1, n))
        return self.decoder.decode(data), w / 1000.0


NO_FONT = _Font(_Unreadable())


# ---------------------------------------------------------------- Dokument

class _Doc:
    def __init__(self, data: bytes):
        if not data.startswith(b"%PDF") and b"%PDF" not in data[:1024]:
            raise PDFError("Das ist keine PDF-Datei.")
        if re.search(rb"/Encrypt\s+(\d+\s+\d+\s+R|<<)", data):
            raise PDFError("Die PDF ist verschlüsselt bzw. geschützt – ihr Text kann nicht gelesen werden.")
        self.data = data
        self.offsets: dict[int, int] = {}
        for m in re.finditer(rb"(?<![0-9])(\d+)\s+(\d+)\s+obj\b", data):
            self.offsets[int(m.group(1))] = m.end()  # spätere Fassung (Änderungen am Dateiende) gewinnt
        self.cache: dict[int, object] = {}
        self.in_streams: dict[int, tuple[int, int]] = {}
        self._index_object_streams()
        self.fonts: dict = {}

    def _index_object_streams(self):
        for num in list(self.offsets):
            if b"/ObjStm" not in self.data[self.offsets[num]:self.offsets[num] + 300]:
                continue
            st = self.get(num)
            if not isinstance(st, Stream) or st.info.get("Type") != "ObjStm":
                continue
            raw = self.stream_data(st)
            n, first = self.resolve(st.info.get("N", 0)), self.resolve(st.info.get("First", 0))
            nums = [int(x) for x in raw[:first].split()]
            for i in range(0, min(len(nums), 2 * n) - 1, 2):
                objnum, off = nums[i], nums[i + 1]
                if objnum not in self.offsets:
                    self.in_streams[objnum] = (num, first + off)

    def get(self, num: int):
        if num in self.cache:
            return self.cache[num]
        self.cache[num] = None  # Schutz vor Endlosschleifen
        obj = None
        if num in self.offsets:
            obj, pos = _parse(self.data, self.offsets[num])
            if isinstance(obj, dict):
                m = re.compile(rb"[\x00\t\n\x0c\r ]*stream(\r\n|\n|\r)?").match(self.data, pos)
                if m:
                    obj = Stream(obj, self._stream_raw(obj, m.end()))
        elif num in self.in_streams:
            container, off = self.in_streams[num]
            st = self.get(container)
            if isinstance(st, Stream):
                obj, _ = _parse(self.stream_data(st), off)
        self.cache[num] = obj
        return obj

    def _stream_raw(self, info: dict, start: int) -> bytes:
        length = self.resolve(info.get("Length"))
        if isinstance(length, int) and 0 <= length and b"endstream" in self.data[start + length:start + length + 40]:
            return self.data[start:start + length]
        end = self.data.find(b"endstream", start)
        return self.data[start:end if end >= 0 else len(self.data)].rstrip(b"\r\n")

    def resolve(self, obj, depth=0):
        while isinstance(obj, Ref) and depth < 20:
            obj = self.get(obj[0])
            depth += 1
        return obj

    def stream_data(self, st: Stream) -> bytes:
        if st._data is not None:
            return st._data
        data = st.raw
        filters = self.resolve(st.info.get("Filter"))
        filters = filters if isinstance(filters, list) else [filters] if filters else []
        for f in filters:
            f = self.resolve(f)
            if f in ("FlateDecode", "Fl"):
                data = _inflate(data)
            elif f in ("ASCIIHexDecode", "AHx"):
                h = re.sub(rb"[^0-9A-Fa-f]", b"", data.split(b">")[0])
                data = bytes.fromhex((h + b"0" if len(h) % 2 else h).decode())
            elif f in ("ASCII85Decode", "A85"):
                body = re.sub(rb"\s", b"", data).removeprefix(b"<~").split(b"~>")[0]
                try:
                    data = base64.a85decode(body)
                except ValueError:
                    data = b""
            elif f in ("LZWDecode", "LZW"):
                data = _lzw(data)
            else:  # Bildformate (DCT, JBIG2, CCITT …) enthalten keinen Text
                data = b""
                break
        parms = self.resolve(st.info.get("DecodeParms"))
        if isinstance(parms, list):
            parms = self.resolve(parms[0]) if parms else None
        if isinstance(parms, dict) and (self.resolve(parms.get("Predictor")) or 1) >= 10:
            data = _png_unpredict(data, self.resolve(parms.get("Columns")) or 1)
        st._data = data
        return data

    # ------------------------------------------------------------ Seiten

    def pages(self) -> list[tuple[dict, dict]]:
        """[(Seiten-Dictionary, Ressourcen)] in Lesereihenfolge."""
        roots = re.findall(rb"/Root\s+(\d+)\s+(\d+)\s+R", self.data)
        out: list = []
        if roots:
            catalog = self.resolve(Ref((int(roots[-1][0]), int(roots[-1][1]))))
            if isinstance(catalog, Stream):
                catalog = catalog.info
            if isinstance(catalog, dict):
                self._walk(self.resolve(catalog.get("Pages")), {}, out, set())
        if not out:  # Notlösung: alle Seitenobjekte in Dateireihenfolge
            for num in sorted(set(self.offsets) | set(self.in_streams)):
                obj = self.get(num)
                if isinstance(obj, dict) and obj.get("Type") == "Page":
                    out.append((obj, self.resolve(obj.get("Resources")) or {}))
        return out

    def _walk(self, node, inherited, out, seen):
        if not isinstance(node, dict) or id(node) in seen or len(out) > 5000:
            return
        seen.add(id(node))
        res = self.resolve(node.get("Resources")) or inherited
        if node.get("Type") == "Pages" or "Kids" in node:
            for kid in self.resolve(node.get("Kids")) or []:
                self._walk(self.resolve(kid), res, out, seen)
        else:
            out.append((node, res))

    def page_text(self, page: dict, resources: dict) -> str:
        contents = self.resolve(page.get("Contents"))
        parts = contents if isinstance(contents, list) else [contents]
        data = b"\n".join(self.stream_data(s) for s in (self.resolve(p) for p in parts) if isinstance(s, Stream))
        return _tidy(self._run(data, resources, 0))

    # ------------------------------------------------------------ Schriften

    def font(self, ref) -> _Font:
        key = ref if isinstance(ref, Ref) else id(ref)
        if key in self.fonts:
            return self.fonts[key]
        f = self.resolve(ref)
        font = NO_FONT
        if isinstance(f, dict):
            dec: object = _Unreadable()
            tu = self.resolve(f.get("ToUnicode"))
            if isinstance(tu, Stream):
                cmap = _CMap(self.stream_data(tu))
                if cmap.single or cmap.ranges:
                    dec = cmap
            if f.get("Subtype") == "Type0":
                enc = str(self.resolve(f.get("Encoding")) or "")
                if isinstance(dec, _Unreadable) and ("UCS2" in enc or "UTF16" in enc):
                    dec = _Utf16()
                widths, default = self._cid_widths(f)
                font = _Font(dec, widths, default, code_len=2)
            else:
                if isinstance(dec, _Unreadable):
                    dec = self._simple_font(f)
                first = self.resolve(f.get("FirstChar"))
                ws = self.resolve(f.get("Widths"))
                widths = ({first + i: float(self.resolve(w) or 0) for i, w in enumerate(ws)}
                          if isinstance(first, int) and isinstance(ws, list) else {})
                desc = self.resolve(f.get("FontDescriptor"))
                missing = self.resolve(desc.get("MissingWidth")) if isinstance(desc, dict) else None
                font = _Font(dec, widths, float(missing) if missing else 500.0, code_len=1)
        self.fonts[key] = font
        return font

    def _cid_widths(self, f: dict) -> tuple[dict[int, float], float]:
        """Breiten einer zusammengesetzten Schrift aus /W: [c [w1 w2 …]] oder [c_erst c_letzt w]."""
        kids = self.resolve(f.get("DescendantFonts"))
        cid = self.resolve(kids[0]) if isinstance(kids, list) and kids else None
        if not isinstance(cid, dict):
            return {}, 1000.0
        default = float(self.resolve(cid.get("DW")) or 1000)
        w = [self.resolve(x) for x in (self.resolve(cid.get("W")) or [])]
        widths, i = {}, 0
        while i + 1 < len(w) and len(widths) < 70000:
            if isinstance(w[i + 1], list):
                for j, v in enumerate(w[i + 1]):
                    widths[int(w[i]) + j] = float(self.resolve(v) or 0)
                i += 2
            elif i + 2 < len(w) and all(isinstance(v, (int, float)) for v in w[i:i + 3]):
                for c in range(int(w[i]), min(int(w[i + 1]), int(w[i]) + 70000) + 1):
                    widths[c] = float(w[i + 2])
                i += 3
            else:
                break
        return widths, default

    def _simple_font(self, f: dict) -> _SimpleFont:
        enc = self.resolve(f.get("Encoding"))
        base, table = "cp1252", {}
        if isinstance(enc, dict):
            if self.resolve(enc.get("BaseEncoding")) == "MacRomanEncoding":
                base = "mac_roman"
            code = 0
            for item in self.resolve(enc.get("Differences")) or []:
                item = self.resolve(item)
                if isinstance(item, int):
                    code = item
                elif isinstance(item, str):
                    ch = _glyph_char(item)
                    if ch:
                        table[code] = ch
                    code += 1
        elif enc == "MacRomanEncoding":
            base = "mac_roman"
        return _SimpleFont(table, base)

    # ------------------------------------------------------------ Inhaltsströme

    def _run(self, data: bytes, resources: dict, depth: int) -> str:
        """Liest die Textbefehle eines Inhaltsstroms. Zeilenumbrüche/Leerzeichen werden aus den
        Positionsbefehlen abgeleitet (nur so gut, wie es die PDF hergibt)."""
        fonts = self.resolve(resources.get("Font")) if isinstance(resources, dict) else None
        fonts = fonts if isinstance(fonts, dict) else {}
        xobjects = self.resolve(resources.get("XObject")) if isinstance(resources, dict) else None
        xobjects = xobjects if isinstance(xobjects, dict) else {}
        out: list[str] = []
        font = NO_FONT
        stack: list = []
        size = 10.0                   # Schriftgröße (Tf)
        a = d = 1.0                   # Skalierung der Textmatrix (x, y)
        line_x = line_y = 0.0         # Anfang der aktuellen Textzeile (Td/Tm)
        leading = 0.0                 # Zeilenabstand für T* (TL/TD)
        end_x = 0.0                   # Position hinter dem zuletzt gezeigten Text
        last_y = None                 # y der zuletzt gezeigten Zeile
        pos, n = 0, len(data)

        def show(s: bytes):
            nonlocal end_x
            text, advance = font.show(s)
            if text:
                out.append(text)
            end_x += advance * size * abs(a)

        def newline():
            if out and not out[-1].endswith("\n"):
                out.append("\n")

        def space():
            if out and not out[-1].endswith((" ", "\n")):
                out.append(" ")

        def move(x: float, y: float):
            """Neue Textposition: andere Zeile → Umbruch; gleiche Zeile mit Lücke → Leerzeichen.
            Ohne Lücke (Formatwechsel mitten im Wort, einzeln gesetzte Buchstaben) bleibt der Text zusammen."""
            nonlocal end_x, last_y
            em = size * abs(d) or 1.0
            if last_y is not None and abs(y - last_y) > 0.4 * em:
                newline()
            elif last_y is not None:
                gap = x - end_x
                if gap > 0.15 * em or gap < -1.0 * em:
                    space()
            last_y, end_x = y, x

        while pos < n:
            kind, val, pos = _next(data, pos)
            if kind is None:
                break
            if kind == "op":
                op = val
                nums = [v for v in stack if isinstance(v, (int, float))]
                if op == b"Tf" and len(stack) >= 2:
                    name = stack[-2]
                    font = self.font(fonts.get(name)) if isinstance(name, str) and name in fonts else NO_FONT
                    if isinstance(stack[-1], (int, float)) and stack[-1]:
                        size = abs(stack[-1])
                elif op == b"Tj" and stack:
                    if isinstance(stack[-1], bytes):
                        show(stack[-1])
                elif op == b"TJ" and stack and isinstance(stack[-1], list):
                    for item in stack[-1]:
                        if isinstance(item, bytes):
                            show(item)
                        elif isinstance(item, (int, float)):
                            end_x -= item / 1000 * size * abs(a)
                            if item < -200:  # großer Abstand innerhalb einer Zeile = Wortzwischenraum
                                space()
                elif op == b"BT":
                    a = d = 1.0
                    line_x = line_y = 0.0
                elif op == b"TL" and nums:
                    leading = nums[-1]
                elif op in (b"Td", b"TD") and len(nums) >= 2:
                    if op == b"TD":
                        leading = -nums[-1]
                    line_x, line_y = line_x + nums[-2] * a, line_y + nums[-1] * d
                    move(line_x, line_y)
                elif op == b"Tm" and len(nums) >= 6:
                    a, d = (nums[-6] or 1.0), (nums[-3] or 1.0)
                    line_x, line_y = nums[-2], nums[-1]
                    move(line_x, line_y)
                elif op in (b"T*", b"'", b'"'):
                    line_y -= (leading or size * 1.2) * d
                    newline()
                    end_x, last_y = line_x, line_y
                    if op != b"T*" and stack and isinstance(stack[-1], bytes):
                        show(stack[-1])
                elif op == b"Do" and stack and depth < 5:
                    xo = self.resolve(xobjects.get(stack[-1])) if isinstance(stack[-1], str) else None
                    if isinstance(xo, Stream) and xo.info.get("Subtype") == "Form":
                        sub_res = self.resolve(xo.info.get("Resources")) or resources
                        out.append(self._run(self.stream_data(xo), sub_res, depth + 1))
                elif op == b"ID":  # Inline-Bild: Binärdaten bis „EI“ überspringen
                    m = re.compile(rb"[\x00\t\n\x0c\r ]EI(?=[\x00\t\n\x0c\r ]|$)").search(data, pos)
                    pos = m.end() if m else n
                stack.clear()
            elif kind == "arr" and val == b"[":
                arr, pos = _parse(data, pos - 1)
                stack.append(arr)
            elif kind == "dict" and val == b"<<":
                d, pos = _parse(data, pos - 2)
                stack.append(d)
            elif kind in ("str", "num", "name"):
                stack.append(val)
            if len(stack) > 200:
                stack.clear()
        return "".join(out)


class _Utf16:
    @staticmethod
    def decode(data: bytes) -> str:
        return data[:len(data) // 2 * 2].decode("utf-16-be", "replace").replace("�", "")


def _inflate(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except zlib.error:
        try:
            return zlib.decompressobj().decompress(data)  # beschädigt/abgeschnitten: so viel wie möglich
        except zlib.error:
            return b""


def _lzw(data: bytes) -> bytes:
    out, table, bits, buf, nbits, prev = bytearray(), [bytes([i]) for i in range(256)] + [b"", b""], 9, 0, 0, None
    for byte in data:
        buf, nbits = (buf << 8) | byte, nbits + 8
        while nbits >= bits:
            nbits -= bits
            code = (buf >> nbits) & ((1 << bits) - 1)
            if code == 256:
                table, bits, prev = table[:258], 9, None
                continue
            if code == 257:
                return bytes(out)
            if prev is None:
                entry = table[code] if code < len(table) else b""
            else:
                entry = table[code] if code < len(table) else prev + prev[:1]
                table.append(prev + entry[:1])
            out += entry
            prev = entry
            if len(table) + 1 >= (1 << bits) and bits < 12:
                bits += 1
    return bytes(out)


def _png_unpredict(data: bytes, columns: int) -> bytes:
    row_len, out, prev = columns + 1, bytearray(), bytearray(columns)
    for i in range(0, len(data) - columns, row_len):
        ftype, row = data[i], bytearray(data[i + 1:i + row_len])
        for j in range(len(row)):
            left = row[j - 1] if j else 0
            up, ul = prev[j], prev[j - 1] if j else 0
            if ftype == 1:
                row[j] = (row[j] + left) & 0xFF
            elif ftype == 2:
                row[j] = (row[j] + up) & 0xFF
            elif ftype == 3:
                row[j] = (row[j] + (left + up) // 2) & 0xFF
            elif ftype == 4:
                p = left + up - ul
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - ul)
                row[j] = (row[j] + (left if pa <= pb and pa <= pc else up if pb <= pc else ul)) & 0xFF
        out += row
        prev = row
    return bytes(out)


def _tidy(text: str) -> str:
    lines = [re.sub(r"[ \t ]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def extract(data: bytes, max_pages: int = 2000) -> tuple[str, int]:
    doc = _Doc(data)
    pages = doc.pages()
    if not pages:
        raise PDFError("In der PDF wurden keine Seiten gefunden (Datei beschädigt?).")
    parts = []
    for i, (page, res) in enumerate(pages[:max_pages], start=1):
        try:
            text = doc.page_text(page, res)
        except Exception:
            text = ""
        parts.append(f"--- Seite {i} ---\n{text}")
    return "\n\n".join(parts), len(pages)
