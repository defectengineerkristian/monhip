"""Dokumente als Text lesen – für Anhänge im Chat und das Agenten-Werkzeug read_file.

read(pfad) -> Document. Unterstützt PDF, Word/Excel/PowerPoint (.docx/.xlsx/.pptx), OpenDocument
(.odt/.ods/.odp), RTF sowie Text-, Code- und Datendateien aller Art (erkannt am Inhalt, nicht nur an der Endung).
Neue Formate: Endung in KINDS eintragen und in read() einen Zweig ergänzen.
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

from i18n import tr

import office
import pdftext
import web

MAX_BYTES = 100 * 1024 * 1024
KINDS = {
    ".pdf": "PDF", ".docx": "Word", ".docm": "Word", ".dotx": "Word", ".xlsx": "Excel", ".xlsm": "Excel",
    ".xltx": "Excel", ".pptx": "PowerPoint", ".pptm": "PowerPoint", ".potx": "PowerPoint",
    ".odt": "OpenDocument-Text", ".ods": "OpenDocument-Tabelle", ".odp": "OpenDocument-Präsentation",
    ".rtf": "RTF", ".html": "HTML", ".htm": "HTML", ".csv": "CSV", ".json": "JSON", ".md": "Markdown",
    ".txt": "Text", ".xml": "XML", ".log": "Log",
}
# Formate, die erst umgewandelt werden müssen (read_file des Agenten liest alles andere unverändert)
CONVERTED = {".pdf", ".odt", ".ods", ".odp", ".rtf", *office.OFFICE_SUFFIXES}
NOT_SUPPORTED = {
    ".doc": "das alte Word-Format (.doc) – bitte in Word als .docx speichern",
    ".xls": "das alte Excel-Format (.xls) – bitte in Excel als .xlsx speichern",
    ".ppt": "das alte PowerPoint-Format (.ppt) – bitte als .pptx speichern",
    ".zip": "ein Archiv – bitte zuerst entpacken", ".7z": "ein Archiv – bitte zuerst entpacken",
    ".rar": "ein Archiv – bitte zuerst entpacken", ".exe": "ein Programm", ".msi": "ein Installationspaket",
}
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".heic", ".ico"}
VISION_IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}  # als Anhang ans Modell (images.py), wenn es Bilder kann


@dataclass
class Document:
    path: Path
    kind: str
    text: str
    pages: int | None = None
    unit: str = "Seite"   # bzw. "Folie" (PowerPoint) oder "Blatt" (Excel)
    image: tuple[int, int] | None = None  # Bilder (images.read): Breite, Höhe – dann ohne Text
    thumb: Path | None = None             # Bilder: Vorschaubild (PNG) für die Anzeige
    share_only: bool = False              # Teamwork: nicht lesbar (z. B. Programm) – wird nur zum Herunterladen geteilt

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def info(self) -> str:
        kind = tr("{0}-Datei", self.kind[:-6]) if self.kind.endswith("-Datei") else tr(self.kind)
        if self.share_only:
            try:
                return f"{kind} · {human_size(self.path.stat().st_size)}"
            except OSError:
                return kind
        if self.image:
            return f"{kind} · {self.image[0]} × {self.image[1]}"
        plural = {"Seite": "Seiten", "Folie": "Folien", "Blatt": "Blätter"}
        parts = [kind]
        if self.pages:
            parts.append(f"{self.pages} {tr(self.unit if self.pages == 1 else plural[self.unit])}")
        parts.append(tr("{0:,} Zeichen", len(self.text)).replace(",", "."))
        return " · ".join(parts)


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024
    return ""


def decode_text(data: bytes) -> str:
    """Bytes → Text (UTF-8, UTF-16 mit BOM oder Windows-1252), Zeilenenden einheitlich \\n."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = data.decode("utf-16", "replace")
    else:
        for enc in ("utf-8-sig", "cp1252"):
            try:
                text = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = data.decode("utf-8", "replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def is_binary(data: bytes) -> bool:
    head = data[:8192]
    return b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff"))


def read(path) -> Document:
    path = Path(path)
    suffix = path.suffix.lower()
    if path.is_dir():
        raise ValueError("Das ist ein Ordner, keine Datei.")
    if suffix in VISION_IMAGES:
        raise ValueError("Bilder kann das Modell nur ansehen, wenn sie im Chat angehängt werden.")
    if suffix in IMAGES:
        raise ValueError("Dieses Bildformat wird nicht unterstützt – bitte als PNG oder JPG speichern.")
    if suffix in NOT_SUPPORTED:
        raise ValueError(f"Das ist {NOT_SUPPORTED[suffix]}.")
    size = path.stat().st_size
    if size > MAX_BYTES:
        raise ValueError(f"Die Datei ist zu groß ({size / 1024 ** 2:.0f} MB, höchstens {MAX_BYTES // 1024 ** 2} MB).")
    kind = KINDS.get(suffix, "Text")
    if suffix == ".pdf":
        text, pages = pdftext.extract(path.read_bytes())
        if len(re.sub(r"--- Seite \d+ ---|\s", "", text)) < 20:
            raise ValueError("Die PDF enthält keinen lesbaren Text – vermutlich eingescannte Seiten (nur Bilder).")
        return Document(path, kind, text, pages)
    if suffix in office.OFFICE_SUFFIXES:
        text = office.read_text(path)
        if kind == "PowerPoint":
            return Document(path, kind, text, text.count("## Folie "), "Folie")
        if kind == "Excel":
            return Document(path, kind, text, text.count("## Blatt: "), "Blatt")
        return Document(path, kind, text)
    if suffix in (".odt", ".ods", ".odp"):
        return Document(path, kind, _opendocument_text(path))
    data = path.read_bytes()
    if suffix == ".rtf" or data.startswith(b"{\\rtf"):
        return Document(path, "RTF", _rtf_text(data.decode("latin-1")))
    if is_binary(data):
        raise ValueError(f"Dateityp „{suffix or 'ohne Endung'}“ wird nicht unterstützt (keine Textdatei).")
    text = decode_text(data)
    if suffix in (".html", ".htm") and len(text) > 60_000:  # gespeicherte Webseite: nur der lesbare Text
        title, body = web.html_to_text(text)
        text = (f"Titel: {title}\n\n" if title else "") + body
    return Document(path, kind if suffix in KINDS else _code_kind(suffix), text)


def _code_kind(suffix: str) -> str:
    return f"{suffix[1:].upper()}-Datei" if suffix else "Text"


def _opendocument_text(path: Path) -> str:
    ns_text = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("content.xml"))
    out = []
    for el in root.iter():
        if el.tag in (ns_text + "p", ns_text + "h"):
            out.append("".join(el.itertext()))
    return "\n".join(out).strip()


def _rtf_text(rtf: str) -> str:
    """Sehr einfacher RTF-Leser: Formatierungsbefehle weg, Absätze, Sonderzeichen und Unicode bleiben."""
    rtf = re.sub(r"\{\\\*[^{}]*(\{[^{}]*\}[^{}]*)*\}", "", rtf)               # unsichtbare Zusatzgruppen
    rtf = re.sub(r"\{\\(fonttbl|colortbl|stylesheet|info)[^{}]*(\{[^{}]*\}[^{}]*)*\}", "", rtf)
    rtf = re.sub(r"\\(par|line)\b ?", "\n", rtf)
    rtf = re.sub(r"\\tab\b ?", "\t", rtf)
    # \uN = Unicode-Zeichen, danach folgt ein Ersatzzeichen für alte Programme, das übersprungen wird
    rtf = re.sub(r"\\u(-?\d+) ?(?:\\'[0-9a-fA-F]{2}|\?)?", lambda m: chr(int(m.group(1)) % 65536), rtf)
    rtf = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("cp1252", "replace"), rtf)
    rtf = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", rtf)
    rtf = re.sub(r"\\([{}\\])", r"\1", rtf).replace("{", "").replace("}", "")
    return re.sub(r"\n{3,}", "\n\n", rtf).strip()
