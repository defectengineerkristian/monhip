"""Hörbuch: aus einer PDF nur den Text holen, der vorgelesen werden soll – Werkzeug hoerbuch_erstellen.

Grundlage sind die Zeilen jeder Seite mit ihrer Schriftgröße (pdftext.extract_lines). Daraus wird entfernt, was man
nicht hören will: Kopf- und Fußzeilen (kehren oben bzw. unten auf vielen Seiten wieder, Zahlen zählen dabei nicht),
Seitenzahlen, Inhaltsverzeichnis (Zeilen mit Punkten und Seitenzahl), Bild- und Tabellenunterschriften, Fußnoten
(kleinere Schrift unten auf der Seite, Fußnotenzeichen im Text), Literaturverzeichnis, Register und Anhang am Ende.
Getrennte Wörter am Zeilenende werden zusammengefügt, Zeilen zu Absätzen. Kapitel kommen aus Überschriften (größere
Schrift oder „Kapitel 3 …“); ohne solche wird der Text in gleich lange Teile geschnitten. Abkürzungen wie „z. B.“
werden ausgeschrieben, damit die Stimme sie flüssig liest.

Alles hier ist reine Textverarbeitung ohne Tk, Netz oder Modell – gut testbar."""

import re
from collections import Counter

CHARS_PER_SECOND = 14.5      # so schnell liest eine ruhige Erzählstimme (deutsch) – für die geschätzte Dauer
PART_CHARS = 25_000          # ohne erkennbare Kapitel: etwa so lange Teile (rund eine halbe Stunde)
MAX_CHAPTERS = 80            # mehr „Kapitel“ sind eher Zwischenüberschriften

_PAGE_NO = re.compile(r"^[\s\-–—|·•]*(?:(?:seite|page|s\.)\s*)?(?:\d{1,4}|[ivxlcdm]{1,7})"
                      r"(?:\s*(?:/|von|of)\s*\d{1,4})?[\s\-–—|·•]*$", re.I)
_TOC_LINE = re.compile(r"(?:(?:\.\s?){3,}|…+|_{3,}|\s{3,})\s*\d{1,4}\s*$")
_CAPTION = re.compile(r"^(?:abbildung|abb\.|tabelle|tab\.|figure|fig\.|table|grafik|diagramm|foto)\s*\d", re.I)
_TOC_HEAD = re.compile(r"^(?:inhalt|inhaltsverzeichnis|contents|table of contents)\s*$", re.I)
_END_HEAD = re.compile(r"^(?:\d+\.?\s+)?(?:literatur(?:verzeichnis)?|quellen(?:verzeichnis|angaben)?|"
                       r"bibliogra(?:ph|f)ie|(?:stichwort|personen|sach|orts)?register|index|references|bibliography|"
                       r"anmerkungen|endnoten|abbildungsverzeichnis|tabellenverzeichnis|glossar|anhang|appendix)\s*$",
                       re.I)
_CHAPTER = re.compile(r"^(?:kapitel|chapter|teil|part|buch|book|prolog|epilog|vorwort|nachwort|einleitung)\b", re.I)
_NUMBERED = re.compile(r"^\d{1,2}(?:\.\d{1,2})*\.?\s+[A-ZÄÖÜ]")  # „3 Die Methode“ – nur in größerer Schrift
_SUPERSCRIPT = re.compile(r"[¹²³⁰⁴-⁹]+")
_REF = re.compile(r"\s?\[\d+(?:\s*[,–-]\s*\d+)*\]")
# Adresse → nur der Name der Seite; Satzzeichen dahinter bleiben stehen
_URL = re.compile(r"(?:https?://(?:www\.)?|www\.)([^/\s?#]*[^/\s?#.,;:!?'\")\]])\S*?(?=[.,;:!?'\")\]]*(?:\s|$))")
_SENTENCE_END = tuple('.!?:;"“”»«)…')
_ABBREVIATIONS = [  # (Muster, ausgeschrieben) – nur deutsch; Qwen3-TTS liest Zahlen selbst richtig
    (r"\bz\.\s?B\.", "zum Beispiel"), (r"\bd\.\s?h\.", "das heißt"), (r"\bu\.\s?a\.", "unter anderem"),
    (r"\bu\.\s?Ä\.", "und Ähnliches"), (r"\bo\.\s?Ä\.", "oder Ähnliches"), (r"\bz\.\s?T\.", "zum Teil"),
    (r"\bs\.\s?o\.", "siehe oben"), (r"\bs\.\s?u\.", "siehe unten"), (r"\bi\.\s?d\.\s?R\.", "in der Regel"),
    (r"\bbzw\.", "beziehungsweise"), (r"\busw\.", "und so weiter"), (r"\betc\.", "et cetera"),
    (r"\bvgl\.", "vergleiche"), (r"\bggf\.", "gegebenenfalls"), (r"\bevtl\.", "eventuell"), (r"\binkl\.", "inklusive"),
    (r"\bzzgl\.", "zuzüglich"), (r"\bca\.", "circa"), (r"\bsog\.", "sogenannte"), (r"\bNr\.(?=\s?\d)", "Nummer"),
    (r"\bS\.(?=\s?\d)", "Seite"), (r"\bAbb\.", "Abbildung"), (r"\bKap\.", "Kapitel"), (r"\bDr\.", "Doktor"),
    (r"\bProf\.", "Professor"), (r"\bJh\.", "Jahrhundert"), (r"\bMio\.", "Millionen"), (r"\bMrd\.", "Milliarden"),
    (r"§§\s?", "Paragrafen "), (r"§\s?", "Paragraf "),
]


def _key(text: str) -> str:
    """Zeile zum Vergleichen über Seiten hinweg: klein, Zahlen gleich, ohne Satzzeichen am Rand."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", text.lower())).strip(" .-–—|·•")


def body_size(pages: list[list[tuple[str, float]]]) -> float:
    """Schriftgröße des Fließtexts: die, in der die meisten Zeichen stehen."""
    count: Counter = Counter()
    for lines in pages:
        for text, size in lines:
            count[round(size or 0, 1)] += len(text)
    count.pop(0.0, None)
    return count.most_common(1)[0][0] if count else 10.0


def running_lines(pages: list[list[tuple[str, float]]], edge: int = 2) -> set[str]:
    """Kopf- und Fußzeilen: Zeilen, die oben oder unten (die ersten bzw. letzten edge Zeilen) auf vielen Seiten
    wiederkehren – Seitenzahlen darin zählen nicht (Buchtitel, Kapitelname, „Seite 3 von 90“)."""
    filled = [lines for lines in pages if len(lines) >= 3]
    seen: Counter = Counter()
    for lines in filled:
        seen.update({_key(t) for t, _ in lines[:edge] + lines[-edge:] if _key(t)})
    need = max(3, int(0.3 * len(filled)))
    return {k for k, n in seen.items() if n >= need}


def _is_toc_page(lines: list[tuple[str, float]]) -> bool:
    hits = sum(1 for t, _ in lines if _TOC_LINE.search(t))
    return any(_TOC_HEAD.match(t) for t, _ in lines[:4]) or (hits >= 4 and hits >= 0.4 * len(lines))


def clean_line(text: str, language: str = "de") -> str:
    """Eine Zeile Fließtext vorlesbar machen: Fußnotenzeichen, Verweise wie [3], weiche Trennstriche weg; Adressen nur
    als Name der Seite; deutsche Abkürzungen ausgeschrieben."""
    t = text.replace("­", "").replace("ﬁ", "fi").replace("ﬂ", "fl")
    if language == "de":  # Einheiten vor dem Entfernen hochgestellter Fußnotenzeichen retten
        t = re.sub(r"\b(k|c|d)?m²", lambda m: " Quadrat" + {"k": "kilo", "c": "zenti", "d": "dezi"}.get(m.group(1), "")
                   + "meter", t)
        t = re.sub(r"\b(k|c|d)?m³", lambda m: " Kubik" + {"k": "kilo", "c": "zenti", "d": "dezi"}.get(m.group(1), "")
                   + "meter", t)
    t = _SUPERSCRIPT.sub("", t)
    t = _REF.sub("", t)
    t = _URL.sub(lambda m: m.group(1), t)
    if language == "de":
        for pattern, full in _ABBREVIATIONS:
            t = re.sub(pattern, full, t)
    return re.sub(r"\s+", " ", t).strip()


def _join(paragraph: str, line: str) -> str:
    """Zeile an den Absatz hängen – mit Trennstrich am Ende: „Ver-“ + „ständnis“ → „Verständnis“, aber „E-“ + „Mail“
    → „E-Mail“ und „Nord-“ + „und Süd“ → „Nord- und Süd“."""
    if not paragraph:
        return line
    if re.search(r"\w-$", paragraph):
        first = line.split(" ", 1)[0]
        if first[:1].islower() and first.rstrip(",.") not in ("und", "oder", "bzw", "sowie", "bis"):
            return paragraph[:-1] + line
        if first[:1].isupper() or first[:1].isdigit():
            return paragraph + line
    return paragraph + " " + line


def prepare(pages: list[list[tuple[str, float]]], language: str = "de", title: str = "",
            first_page: int = 1) -> dict:
    """Seiten (je [(Zeile, Schriftgröße)]) → {"title", "chapters": [{"title", "paragraphs", "pages"}], "removed":
    {Art: Anzahl}, "chars"}. first_page: Nummer der ersten übergebenen Seite (bei einer Auswahl)."""
    body = body_size(pages)
    running = running_lines(pages)
    removed: Counter = Counter()
    # typische Länge einer vollen Zeile (übers ganze Buch – eine Seite mit wenig Text verzerrt sonst)
    lengths = sorted(len(t) for lines in pages for t, s in lines if abs(s - body) < 0.6 and len(t) > 20)
    typical = lengths[int(len(lengths) * 0.7)] if lengths else 60
    if not title:  # Buchtitel: größte Schrift auf den ersten beiden Seiten mit Text
        front = [(s, t) for lines in [p for p in pages if p][:2] for t, s in lines if len(t) <= 120]
        if front and max(front)[0] >= 1.3 * body:
            title = max(front, key=lambda st: st[0])[1]
    blocks = []  # (Art, Text, Seite): "head1" Kapitel, "head2" Zwischenüberschrift, "text" Zeile, "par" Absatzende
    filled = [i for i, lines in enumerate(pages) if lines]
    for index, lines in enumerate(pages):
        page_no = first_page + index
        if not lines:
            continue
        if _is_toc_page(lines):
            removed["Inhaltsverzeichnis (Seiten)"] += 1
            continue
        # Fußnoten: kleinere Schrift unter der letzten Zeile in Textgröße
        last_body = max((i for i, (_, s) in enumerate(lines) if s >= 0.92 * body), default=len(lines) - 1)
        late = filled and index >= filled[int(len(filled) * 0.5)]
        stop = False
        for i, (text, size) in enumerate(lines):
            edge = i < 2 or i >= len(lines) - 2
            if edge and _key(text) in running:
                removed["Kopf- und Fußzeilen"] += 1
                continue
            if _PAGE_NO.match(text) and (edge or len(text) <= 8):
                removed["Seitenzahlen"] += 1
                continue
            if _TOC_LINE.search(text) and len(text) < 120:
                removed["Inhaltsverzeichnis (Zeilen)"] += 1
                continue
            if _CAPTION.match(text):
                removed["Bild- und Tabellenunterschriften"] += 1
                continue
            if size and size < 0.85 * body and (i > last_body or (size < 0.75 * body and text[:1].isdigit())):
                removed["Fußnoten"] += 1
                continue
            big = size >= 1.15 * body and len(text) <= 120
            named = (_CHAPTER.match(text) or (_NUMBERED.match(text) and size >= 1.05 * body)) and len(text) <= 80 \
                and not text.rstrip().endswith(_SENTENCE_END[:3])
            if big or named:
                if late and _END_HEAD.match(text.strip()):
                    removed["Literatur, Register, Anhang (Seiten ab hier)"] += len(pages) - index
                    stop = True
                    break
                level = "head1" if size >= 1.3 * body or _CHAPTER.match(text) else "head2"
                blocks.append((level, text, page_no))
                continue
            blocks.append(("text", text, page_no))
            # kurze Zeile mit Satzende: der Absatz ist zu Ende
            if text.rstrip().endswith(_SENTENCE_END) and len(text) < 0.75 * typical:
                blocks.append(("par", "", page_no))
        if stop:
            break
    chapters = _chapters(blocks, language)
    if len(chapters) > 1 and not chapters[0]["title"]:  # kurze Titelei vor dem ersten Kapitel (Untertitel, Widmung)
        removed["Titelei vor dem ersten Kapitel"] += 1
        chapters.pop(0)
    chars = sum(len(p) for c in chapters for p in c["paragraphs"])
    return {"title": clean_line(title, language), "chapters": chapters, "removed": dict(removed), "chars": chars}


def _chapters(blocks: list, language: str) -> list[dict]:
    """Blöcke → Kapitel mit Absätzen. Zu viele „Kapitel“ (Zwischenüberschriften) → nur die großen; gar keine →
    gleich lange Teile."""
    heads = [b for b in blocks if b[0] == "head1"]
    if len(heads) > MAX_CHAPTERS:  # dann zählen nur ausdrückliche „Kapitel …“
        blocks = [("head1" if k == "head1" and _CHAPTER.match(t) else ("head2" if k == "head1" else k), t, p)
                  for k, t, p in blocks]
    chapters: list[dict] = []
    current = {"title": "", "paragraphs": [], "pages": None}
    paragraph = ""

    def flush():
        nonlocal paragraph
        text = clean_line(paragraph, language)
        if text and any(c.isalnum() for c in text):
            current["paragraphs"].append(text)
        paragraph = ""

    def note_page(page):
        first = current["pages"][0] if current["pages"] else page
        current["pages"] = (first, page)

    for kind, text, page in blocks:
        if kind == "head1":
            flush()
            if current["paragraphs"]:
                chapters.append(current)
            elif current["title"]:  # Kapitelüberschrift ohne Text darunter (z. B. „Teil 1“ vor „Kapitel 1“)
                text = current["title"] + ": " + text
            current = {"title": clean_line(text, language), "paragraphs": [], "pages": (page, page)}
        elif kind == "head2":
            flush()
            current["paragraphs"].append(clean_line(text, language).rstrip(".") + ".")
            note_page(page)
        elif kind == "par":
            flush()
        else:
            paragraph = _join(paragraph, text)
            note_page(page)
    flush()
    if current["paragraphs"]:
        chapters.append(current)
    if len(chapters) == 1 and not chapters[0]["title"]:
        chapters = _split_parts(chapters[0])
    # langer Text vor dem ersten Kapitel (Vorbemerkung o. Ä.) bekommt einen Namen; kurzer fällt in prepare weg
    if len(chapters) > 1 and not chapters[0]["title"] and sum(len(p) for p in chapters[0]["paragraphs"]) >= 600:
        chapters[0]["title"] = "Vorab" if language == "de" else "Front matter"
    return chapters


def _split_parts(chapter: dict) -> list[dict]:
    parts, current, size = [], [], 0
    paragraphs = []
    for p in chapter["paragraphs"]:  # ein riesiger „Absatz“ (keine Absätze erkannt): an Satzenden teilen
        if len(p) <= PART_CHARS:
            paragraphs.append(p)
            continue
        piece = ""
        for sentence in re.split(r"(?<=[.!?…])\s+", p):
            if piece and len(piece) + len(sentence) > PART_CHARS // 2:
                paragraphs.append(piece)
                piece = ""
            piece = f"{piece} {sentence}".strip()
        if piece:
            paragraphs.append(piece)
    for p in paragraphs:
        current.append(p)
        size += len(p)
        if size >= PART_CHARS:
            parts.append(current)
            current, size = [], 0
    if current:
        if parts and size < PART_CHARS // 4:
            parts[-1].extend(current)
        else:
            parts.append(current)
    if len(parts) <= 1:
        return [{"title": "", "paragraphs": paragraphs, "pages": chapter["pages"]}]
    return [{"title": f"Teil {i}", "paragraphs": ps, "pages": None} for i, ps in enumerate(parts, 1)]


def select(chapters: list[dict], spec: str) -> list[int]:
    """Kapitelauswahl wie „1-3,5,8-“ (Nummern ab 1) → Indizes; leer = alle."""
    n = len(chapters)
    spec = (spec or "").replace(" ", "")
    if not spec:
        return list(range(n))
    out = []
    for part in spec.split(","):
        m = re.fullmatch(r"(\d*)-(\d*)|(\d+)", part)
        if not m:
            raise ValueError(f"Kapitelauswahl „{spec}“ nicht verstanden (Beispiel: 1-3,5,8-).")
        if m.group(3):
            a = b = int(m.group(3))
        else:
            a, b = int(m.group(1) or 1), int(m.group(2) or n)
        for k in range(max(1, a), min(n, b) + 1):
            if k - 1 not in out:
                out.append(k - 1)
    if not out:
        raise ValueError(f"Die Auswahl „{spec}“ trifft keines der {n} Kapitel.")
    return out


_DE_WORDS = {"der", "die", "das", "und", "ist", "nicht", "mit", "sich", "ein", "eine", "auf", "für", "dem", "den",
             "ich", "sie", "es", "zu", "von", "im", "auch", "wie", "aber", "noch"}
_EN_WORDS = {"the", "and", "is", "not", "with", "of", "to", "a", "in", "that", "it", "for", "on", "you", "he", "she",
             "was", "are", "but", "as", "his", "her", "they", "this"}


def detect_language(pages: list[list[tuple[str, float]]]) -> str:
    """„de“ oder „en“ – nach häufigen kleinen Wörtern im Text (die Stimme liest dann in dieser Sprache)."""
    de = en = 0
    for lines in pages[:40]:
        for text, _ in lines:
            for word in re.findall(r"[a-zäöüß]+", text.lower()):
                de += word in _DE_WORDS
                en += word in _EN_WORDS
    return "en" if en > de * 1.5 else "de"


def duration_text(chars: int, language: str = "de") -> str:
    """Geschätzte Hördauer, z. B. „etwa 3 h 20 min“."""
    minutes = max(1, round(chars / CHARS_PER_SECOND / 60))
    hours, minutes = divmod(minutes, 60)
    return ("etwa " if language == "de" else "about ") + (f"{hours} h {minutes} min" if hours else f"{minutes} min")


def overview(book: dict, chosen: list[int] | None = None, language: str = "de") -> str:
    """Kurzfassung fürs Sprachmodell: Titel, Kapitel mit Länge, was entfernt wurde, eine Leseprobe."""
    chapters = book["chapters"]
    chosen = list(range(len(chapters))) if chosen is None else chosen
    lines = [f"Titel: {book['title'] or '(unbekannt)'}",
             f"{len(chapters)} Kapitel, zusammen {duration_text(book['chars'], language)} Hördauer."]
    for i, c in enumerate(chapters):
        chars = sum(len(p) for p in c["paragraphs"])
        mark = "" if i in chosen else " (nicht ausgewählt)"
        pages = f", Seiten {c['pages'][0]}–{c['pages'][1]}" if c.get("pages") else ""
        lines.append(f"  {i + 1}. {c['title'] or '(ohne Überschrift)'} – {duration_text(chars, language)}{pages}{mark}")
        if len(lines) > 60:
            lines.append(f"  … und {len(chapters) - i - 1} weitere")
            break
    if book["removed"]:
        lines.append("Weggelassen: " + ", ".join(f"{k} ({v})" for k, v in book["removed"].items()) + ".")
    sample = next((p for i in chosen for p in chapters[i]["paragraphs"] if len(p) > 80), "")
    if sample:
        lines.append("Leseprobe: " + sample[:400] + ("…" if len(sample) > 400 else ""))
    return "\n".join(lines)
