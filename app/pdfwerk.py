"""PDFs zusammenfügen, Seiten herausziehen, aufteilen und drehen (Werkzeug pdf_bearbeiten) – ohne Zusatzpakete.

Liest alle Objekte einer PDF (auch aus komprimierten Objekt-Streams und nach nachträglichen Änderungen), übernimmt
die gewünschten Seiten samt allem, was sie brauchen (Schriften, Bilder, Anmerkungen), und schreibt eine neue,
schlichte PDF. Werte werden dabei Byte für Byte übernommen, nicht neu kodiert. Verloren gehen Lesezeichen,
Formularfelder und Verweise auf nicht übernommene Seiten; verschlüsselte PDFs werden abgelehnt.
pdftext.py hat einen eigenen Parser, der Werte für die Textausgabe umwandelt – für das Schreiben taugt er nicht."""

import re
import zlib
from pathlib import Path

MAX_BYTES = 500 * 1024 * 1024
WS = b" \t\r\n\x0c\x00"
DELIM = b"()<>[]{}/%"
_OBJ = re.compile(rb"(\d+)\s+(\d+)\s+obj\b")
_INT = re.compile(rb"[+-]?\d+$")


class PdfError(Exception):
    """Fehler, den das Modell als verständlichen Satz bekommt (wie agent.ToolError)."""


class Name(bytes):
    """/Name – roh, ohne den Schrägstrich (#xx-Kodierung bleibt erhalten)."""


class Raw(bytes):
    """Unverändert zu übernehmen: Kommazahlen, Zeichenketten samt Klammern, true/false/null."""


class Ref(tuple):
    """Verweis „n g R“."""


class Stream:
    def __init__(self, info: dict, raw: bytes):
        self.info, self.raw = info, raw


NULL = Raw(b"null")


# ---------------------------------------------------------------- Lesen

class _Parser:
    def __init__(self, data: bytes, pos: int = 0):
        self.data, self.pos = data, pos

    def ws(self):
        d, n = self.data, len(self.data)
        while self.pos < n:
            c = d[self.pos]
            if c in WS:
                self.pos += 1
            elif c == 0x25:  # % Kommentar bis Zeilenende
                while self.pos < n and d[self.pos] not in b"\r\n":
                    self.pos += 1
            else:
                break

    def word(self) -> bytes:
        start, d = self.pos, self.data
        while self.pos < len(d) and d[self.pos] not in WS and d[self.pos] not in DELIM:
            self.pos += 1
        return d[start:self.pos]

    def value(self, depth: int = 0):
        if depth > 100:
            raise PdfError("Die PDF ist zu tief verschachtelt.")
        self.ws()
        d = self.data
        if self.pos >= len(d):
            raise PdfError("Die PDF endet unerwartet.")
        c = d[self.pos:self.pos + 1]
        if c == b"/":
            self.pos += 1
            return Name(self.word())
        if c == b"(":
            return self._literal()
        if d.startswith(b"<<", self.pos):
            self.pos += 2
            out = {}
            while True:
                self.ws()
                if d.startswith(b">>", self.pos):
                    self.pos += 2
                    return out
                key = self.value(depth + 1)
                if not isinstance(key, Name):
                    raise PdfError("Ungültiges Wörterbuch in der PDF.")
                out[bytes(key)] = self.value(depth + 1)
        if c == b"<":
            end = d.find(b">", self.pos)
            if end < 0:
                raise PdfError("Ungültige Zeichenkette in der PDF.")
            token, self.pos = Raw(d[self.pos:end + 1]), end + 1
            return token
        if c == b"[":
            self.pos += 1
            out = []
            while True:
                self.ws()
                if d.startswith(b"]", self.pos):
                    self.pos += 1
                    return out
                out.append(self.value(depth + 1))
        token = self.word()
        if not token:
            raise PdfError(f"Unerwartetes Zeichen {c!r} in der PDF.")
        if _INT.match(token):
            save = self.pos  # „n g R“?
            self.ws()
            gen = self.word()
            if _INT.match(gen or b"-"):
                self.ws()
                if d.startswith(b"R", self.pos) and (self.pos + 1 >= len(d) or d[self.pos + 1] in WS + DELIM):
                    self.pos += 1
                    return Ref((int(token), int(gen)))
            self.pos = save
            return int(token)
        return Raw(token)

    def _literal(self) -> Raw:
        d, start, depth = self.data, self.pos, 0
        while self.pos < len(d):
            c = d[self.pos]
            if c == 0x5C:  # Backslash: nächstes Zeichen gehört dazu
                self.pos += 2
                continue
            if c == 0x28:
                depth += 1
            elif c == 0x29:
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    return Raw(d[start:self.pos])
            self.pos += 1
        raise PdfError("Nicht abgeschlossene Zeichenkette in der PDF.")


def _inflate(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except zlib.error:
        return zlib.decompressobj().decompress(data)  # beschädigtes Ende: so viel wie möglich


class Document:
    """Alle Objekte einer PDF: objects[nr] = Wert (bei mehrfacher Definition gilt die spätere)."""

    def __init__(self, path):
        self.path = Path(path)
        try:
            data = self.path.read_bytes() if self.path.stat().st_size <= MAX_BYTES else None
        except OSError as e:
            raise PdfError(f"{self.path} lässt sich nicht lesen ({e}).") from None
        if data is None:
            raise PdfError(f"{self.path.name} ist größer als {MAX_BYTES // 1024 // 1024} MB.")
        if not data.lstrip(WS).startswith(b"%PDF"):
            raise PdfError(f"{self.path.name} ist keine PDF-Datei.")
        self.data = data
        self.objects: dict[int, object] = {}
        self._where: dict[int, int] = {}  # Fundstelle – bei mehrfacher Definition gewinnt die spätere
        self.trailer: dict = {}
        self._scan()
        if b"Encrypt" in self.trailer:
            raise PdfError(f"{self.path.name} ist verschlüsselt und kann nicht bearbeitet werden.")
        self.pages = self._pages()
        if not self.pages:
            raise PdfError(f"In {self.path.name} wurden keine Seiten gefunden.")

    def _keep(self, nr: int, value, where: int):
        if where >= self._where.get(nr, -1):
            self.objects[nr], self._where[nr] = value, where

    def _scan(self):
        d, pos, streams = self.data, 0, []
        while True:
            m = _OBJ.search(d, pos)
            if not m:
                break
            p = _Parser(d, m.end())
            try:
                value = p.value()
                p.ws()
                if d.startswith(b"stream", p.pos) and isinstance(value, dict):
                    value, p.pos = self._stream(value, p.pos + 6)
                    streams.append(value)
            except PdfError:
                pos = m.end()  # kein echtes Objekt (z. B. Text im Inhalt) – weitersuchen
                continue
            self._keep(int(m.group(1)), value, m.start())
            if isinstance(value, Stream) and value.info.get(b"Type") == b"XRef":
                self.trailer = {**self.trailer, **value.info}
            pos = p.pos
        for m in re.finditer(rb"trailer\s*<<", d):
            try:
                self.trailer = {**self.trailer, **_Parser(d, m.end() - 2).value()}
            except PdfError:
                continue
        for s in streams:  # komprimierte Objekt-Streams (PDF 1.5+)
            if s.info.get(b"Type") == b"ObjStm":
                self._objstm(s)
        if b"Root" not in self.trailer:
            root = next((nr for nr, v in self.objects.items()
                         if isinstance(v, dict) and v.get(b"Type") == b"Catalog"), None)
            if root is None:
                raise PdfError(f"{self.path.name} ist beschädigt (kein Katalog gefunden).")
            self.trailer[b"Root"] = Ref((root, 0))

    def _stream(self, info: dict, pos: int) -> tuple[Stream, int]:
        d = self.data
        if d.startswith(b"\r\n", pos):
            pos += 2
        elif d[pos:pos + 1] in (b"\n", b"\r"):
            pos += 1
        length = info.get(b"Length")
        if isinstance(length, int) and d.startswith(b"endstream", self._after_ws(pos + length)):
            end = pos + length
        else:  # Länge als Verweis oder falsch: bis „endstream“
            end = d.find(b"endstream", pos)
            if end < 0:
                raise PdfError("Stream ohne Ende.")
            if d[end - 2:end] == b"\r\n":
                end -= 2
            elif d[end - 1:end] in (b"\n", b"\r"):
                end -= 1
        after = d.find(b"endstream", end)
        if after < 0:
            raise PdfError("Stream ohne Ende.")
        return Stream(info, d[pos:end]), after + 9

    def _after_ws(self, pos: int) -> int:
        while pos < len(self.data) and self.data[pos] in WS:
            pos += 1
        return pos

    def _objstm(self, s: Stream):
        filters = s.info.get(b"Filter")
        filters = filters if isinstance(filters, list) else [filters] if filters else []
        if any(f != b"FlateDecode" for f in filters):
            return
        data = _inflate(s.raw) if filters else s.raw
        try:
            n, first = int(s.info[b"N"]), int(s.info[b"First"])
            head = _Parser(data)
            pairs = [(head.value(), head.value()) for _ in range(n)]
        except (KeyError, PdfError, ValueError, TypeError):
            return
        where = self._where_of(s)
        for nr, offset in pairs:
            try:
                self._keep(int(nr), _Parser(data, first + int(offset)).value(), where)
            except (PdfError, ValueError, TypeError):
                continue

    def _where_of(self, s: Stream) -> int:
        return next((self._where[nr] for nr, v in self.objects.items() if v is s), 0)

    def get(self, v):
        """Verweise auflösen (fehlende Objekte gelten als null)."""
        seen = 0
        while isinstance(v, Ref) and seen < 32:
            v, seen = self.objects.get(v[0], NULL), seen + 1
        return v

    def _pages(self) -> list[dict]:
        """Alle Seiten in Reihenfolge: {"ref", "dict", "erbt"} – erbt = von übergeordneten Knoten geerbte Werte."""
        pages, seen = [], set()
        catalog = self.get(self.trailer[b"Root"])
        if not isinstance(catalog, dict):
            raise PdfError(f"{self.path.name} ist beschädigt (Katalog unlesbar).")
        stack = [(catalog.get(b"Pages"), {})]
        while stack:
            ref, inherited = stack.pop()
            node = self.get(ref)
            key = ref[0] if isinstance(ref, Ref) else id(node)
            if not isinstance(node, dict) or key in seen:
                continue
            seen.add(key)
            here = {**inherited, **{k: node[k] for k in (b"Resources", b"MediaBox", b"CropBox", b"Rotate")
                                    if k in node}}
            kids = self.get(node.get(b"Kids"))
            if node.get(b"Type") == b"Pages" or isinstance(kids, list):
                stack.extend((k, here) for k in reversed(kids or []))
            elif isinstance(ref, Ref):
                pages.append({"ref": ref, "dict": node, "erbt": here})
        return pages


# ---------------------------------------------------------------- Seitenauswahl

def auswahl(spec, count: int) -> list[int]:
    """'1-3,5,8-' → [0, 1, 2, 4, 7, …] (0-basiert). Leer oder 'alle' = alle Seiten; '5-3' rückwärts."""
    spec = str(spec or "").strip().lower().replace(" ", "")
    if spec in ("", "alle", "all", "*"):
        return list(range(count))
    out = []
    for part in spec.replace(";", ",").split(","):
        if not part:
            continue
        m = re.fullmatch(r"(\d*)-(\d*)", part)
        if m:
            a, b = int(m.group(1) or 1), int(m.group(2) or count)
        elif part.isdigit():
            a = b = int(part)
        else:
            raise PdfError(f"Seitenangabe „{part}“ verstehe ich nicht – Beispiel: '1-3,5,8-'.")
        if not (1 <= a <= count and 1 <= b <= count):
            raise PdfError(f"Seite {a if not 1 <= a <= count else b} gibt es nicht – die PDF hat {count} Seiten.")
        out += list(range(a - 1, b)) if a <= b else list(range(a - 1, b - 2, -1))
    if not out:
        raise PdfError("Keine Seiten ausgewählt.")
    return out


# ---------------------------------------------------------------- Schreiben

def _ser(v, ref) -> bytes:
    if isinstance(v, Ref):
        return ref(v)
    if isinstance(v, Name):
        return b"/" + v
    if isinstance(v, (Raw, bytes)):
        return bytes(v)
    if isinstance(v, bool):
        return b"true" if v else b"false"
    if isinstance(v, int):
        return str(v).encode()
    if isinstance(v, dict):
        return b"<<" + b"".join(b"/" + k + b" " + _ser(x, ref) for k, x in v.items()) + b">>"
    if isinstance(v, list):
        return b"[" + b" ".join(_ser(x, ref) for x in v) + b"]"
    if isinstance(v, Stream):
        info = {**v.info, b"Length": len(v.raw)}
        return _ser(info, ref) + b"\nstream\n" + v.raw + b"\nendstream"
    return b"null"


class _Writer:
    def __init__(self):
        self.bodies: list[bytes | None] = []

    def reserve(self) -> int:
        self.bodies.append(None)
        return len(self.bodies)

    def put(self, nr: int, body: bytes):
        self.bodies[nr - 1] = body

    def build(self, root: int) -> bytes:
        out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for nr, body in enumerate(self.bodies, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % nr + (body if body is not None else b"null") + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(self.bodies) + 1)
        out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
        out += b"trailer\n<</Size %d /Root %d 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(self.bodies) + 1, root, xref)
        return bytes(out)


def write(target, items: list[tuple["Document", int, int]]) -> int:
    """Neue PDF aus Seiten: items = [(Dokument, Seitenindex, zusätzliche Drehung in Grad)]. → Seitenzahl"""
    w = _Writer()
    root, pages_nr = w.reserve(), w.reserve()
    kids = []
    maps: dict[int, dict[int, int]] = {}            # je Dokument: alte Objektnummer → neue
    chosen: dict[int, set[int]] = {}                # je Dokument: übernommene Seiten (alte Nummern)
    for doc, i, _ in items:
        chosen.setdefault(id(doc), set()).add(doc.pages[i]["ref"][0])
    queue = []

    def mapper(doc):
        m = maps.setdefault(id(doc), {})
        is_page = {p["ref"][0] for p in doc.pages}

        def ref(r: Ref) -> bytes:
            nr = r[0]
            if nr in m:
                return b"%d 0 R" % m[nr]
            target_obj = doc.objects.get(nr)
            if target_obj is None or (nr in is_page and nr not in chosen[id(doc)]):
                return b"null"  # fehlt oder Seite, die nicht mitkommt (z. B. Link auf Seite 7)
            if isinstance(target_obj, dict) and target_obj.get(b"Type") == b"Pages":
                return b"%d 0 R" % pages_nr  # alter Seitenbaum → der neue
            m[nr] = w.reserve()
            if nr not in is_page:  # übernommene Seiten schreibt die Schleife unten (mit Erbe und Drehung)
                queue.append((doc, nr))
            return b"%d 0 R" % m[nr]
        return ref

    refs = {}
    for doc, i, turn in items:
        page = doc.pages[i]
        ref = refs.setdefault(id(doc), mapper(doc))
        nr = page["ref"][0]
        m = maps[id(doc)]
        if nr in m and w.bodies[m[nr] - 1] is not None:
            new = w.reserve()  # dieselbe Seite noch einmal: eigenes Seitenobjekt
        else:
            new = m.setdefault(nr, w.reserve())
        d = {k: v for k, v in page["dict"].items() if k != b"Parent"}
        for k, v in page["erbt"].items():
            d.setdefault(k, v)
        rotate = doc.get(d.get(b"Rotate", 0))
        rotate = (int(rotate) if isinstance(rotate, int) else 0) + int(turn or 0)
        d[b"Rotate"] = rotate % 360
        d[b"Parent"] = Ref((0, 0))  # Platzhalter, unten ersetzt
        body = _ser(d, lambda r: b"%d 0 R" % pages_nr if r == (0, 0) else ref(r))
        w.put(new, body)
        kids.append(new)
        while queue:
            qdoc, qnr = queue.pop()
            w.put(maps[id(qdoc)][qnr], _ser(qdoc.objects[qnr], refs[id(qdoc)]))
    w.put(pages_nr, b"<</Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids)
          + b"] /Count %d>>" % len(kids))
    w.put(root, b"<</Type /Catalog /Pages %d 0 R>>" % pages_nr)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(w.build(root))
    tmp.replace(target)
    return len(kids)
