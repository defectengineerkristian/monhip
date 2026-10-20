"""Word-, Excel- und PowerPoint-Dateien ohne Zusatzpakete erzeugen (Office Open XML per zipfile)
und Text aus solchen Dateien auslesen.

write_docx(pfad, markdown, titel)   – Markdown → Word (Überschriften, Listen, Tabellen, Code, Links …)
write_xlsx(pfad, blätter)           – [{"name": …, "rows": [[…], …]}] → Excel (Kopfzeile, Formeln, Datumswerte)
write_pptx(pfad, folien, titel, untertitel) – [{"title": …, "bullets": […]}] → PowerPoint (16:9)
read_text(pfad)                     – Text aus .docx/.xlsx/.pptx
"""

import csv
import io
import json
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from markdown_lite import ListLevels, alignment, classify, closes_fence, inline, is_separator_row, split_row

_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _x(s) -> str:
    return escape(_BAD_XML.sub("", str(s)), {'"': "&quot;"})


def _rels(items) -> str:
    """items: [(Id, Typ-Endung, Ziel[, extern])]"""
    out = [XML_HEAD, f'<Relationships xmlns="{REL_NS}">']
    for rid, typ, target, *ext in items:
        typ = typ if typ.startswith("http") else f"{DOC_REL}/{typ}"
        mode = ' TargetMode="External"' if ext and ext[0] else ""
        out.append(f'<Relationship Id="{rid}" Type="{typ}" Target="{_x(target)}"{mode}/>')
    out.append("</Relationships>")
    return "".join(out)


def _content_types(overrides: dict) -> str:
    out = [XML_HEAD, '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
           '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
           '<Default Extension="xml" ContentType="application/xml"/>']
    overrides = {"/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
                 "/docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
                 **overrides}
    for part, ctype in overrides.items():
        out.append(f'<Override PartName="{part}" ContentType="{ctype}"/>')
    out.append("</Types>")
    return "".join(out)


def _doc_props(title: str) -> dict:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core = (XML_HEAD + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/'
            'core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{_x(title)}</dc:title><dc:creator>Monhip</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')
    app = (XML_HEAD + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
           '<Application>Monhip</Application></Properties>')
    return {"docProps/core.xml": core, "docProps/app.xml": app}


def _package_rels(main: str) -> str:
    return _rels([("rId1", "officeDocument", main),
                  ("rId2", "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties",
                   "docProps/core.xml"),
                  ("rId3", "extended-properties", "docProps/app.xml")])


def _write_zip(path: Path, parts: dict):
    """Schreibt erst in eine Hilfsdatei und ersetzt dann – so entsteht nie eine halbe Datei."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    try:
        tmp.replace(path)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        raise PermissionError(f"{path.name} ist vermutlich gerade in einem anderen Programm geöffnet – "
                              "bitte dort schließen und erneut versuchen.") from None


# ====================================================================== Word

W_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        f'xmlns:r="{DOC_REL}"')
TEXT_WIDTH = 9072  # A4 minus 2 × 2,5 cm Rand, in Twips

DOCX_STYLES = XML_HEAD + f"""<w:styles {W_NS}>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Calibri" w:cs="Calibri"/>
<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="de-DE" w:eastAsia="en-US" w:bidi="ar-SA"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont"><w:name w:val="Default Paragraph Font"/>
<w:uiPriority w:val="1"/><w:semiHidden/><w:unhideWhenUsed/></w:style>
<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:uiPriority w:val="99"/>
<w:semiHidden/><w:unhideWhenUsed/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/>
<w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
<w:style w:type="numbering" w:default="1" w:styleId="NoList"><w:name w:val="No List"/><w:uiPriority w:val="99"/>
<w:semiHidden/><w:unhideWhenUsed/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:uiPriority w:val="10"/><w:qFormat/><w:pPr><w:spacing w:after="240" w:line="240" w:lineRule="auto"/><w:contextualSpacing/></w:pPr>
<w:rPr><w:rFonts w:ascii="Calibri Light" w:hAnsi="Calibri Light"/><w:color w:val="1F3864"/><w:kern w:val="28"/>
<w:sz w:val="52"/><w:szCs w:val="52"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:uiPriority w:val="9"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="360" w:after="120"/>
<w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri Light" w:hAnsi="Calibri Light"/><w:color w:val="2F5496"/>
<w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:uiPriority w:val="9"/><w:unhideWhenUsed/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="240" w:after="80"/>
<w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri Light" w:hAnsi="Calibri Light"/><w:color w:val="2F5496"/>
<w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:uiPriority w:val="9"/><w:unhideWhenUsed/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="200" w:after="60"/>
<w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="1F3763"/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 4"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:uiPriority w:val="9"/><w:unhideWhenUsed/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="160" w:after="40"/>
<w:outlineLvl w:val="3"/></w:pPr><w:rPr><w:b/><w:bCs/><w:i/><w:iCs/><w:color w:val="2F5496"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/>
<w:uiPriority w:val="34"/><w:qFormat/><w:pPr><w:spacing w:after="60"/><w:ind w:left="720"/><w:contextualSpacing/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:uiPriority w:val="29"/><w:qFormat/><w:pPr><w:pBdr><w:left w:val="single" w:sz="18" w:space="8" w:color="BFBFBF"/></w:pBdr>
<w:spacing w:before="120" w:after="120"/><w:ind w:left="567" w:right="567"/></w:pPr><w:rPr><w:i/><w:iCs/><w:color w:val="595959"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/><w:qFormat/>
<w:pPr><w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/><w:spacing w:after="0" w:line="240" w:lineRule="auto"/>
<w:ind w:left="113" w:right="113"/></w:pPr><w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/>
<w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="CodeChar"><w:name w:val="Code Char"/><w:basedOn w:val="DefaultParagraphFont"/>
<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/><w:sz w:val="20"/><w:szCs w:val="20"/>
<w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/><w:basedOn w:val="DefaultParagraphFont"/>
<w:uiPriority w:val="99"/><w:unhideWhenUsed/><w:rPr><w:color w:val="0563C1"/><w:u w:val="single"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:basedOn w:val="TableNormal"/><w:uiPriority w:val="39"/>
<w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:tblPr><w:tblBorders>
<w:top w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/><w:left w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
<w:bottom w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/><w:right w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
<w:insideH w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/><w:insideV w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
</w:tblBorders></w:tblPr></w:style>
</w:styles>""".replace("\n", "")

DOCX_SETTINGS = XML_HEAD + (f'<w:settings {W_NS}><w:defaultTabStop w:val="708"/><w:characterSpacingControl '
                            'w:val="doNotCompress"/><w:compat><w:compatSetting w:name="compatibilityMode" '
                            'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>')

BULLET_CHARS = ["•", "◦", "▪"]
NUM_FORMATS = [("decimal", "%1."), ("lowerLetter", "%2)"), ("lowerRoman", "%3.")]


def _numbering(num_lists: list[int]) -> str:
    """Aufzählungszeichen (numId 1) und je nummerierter Liste eine eigene Nummerierung, die neu startet."""
    def levels(bullet: bool) -> str:
        out = []
        for i in range(9):
            left = 720 * (i + 1)
            if bullet:
                fmt, text = "bullet", BULLET_CHARS[i % 3]
                rpr = '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:hint="default"/></w:rPr>'
            else:
                fmt, pattern = NUM_FORMATS[i % 3]
                text, rpr = pattern.replace("%1", f"%{i + 1}").replace("%2", f"%{i + 1}").replace("%3", f"%{i + 1}"), ""
            out.append(f'<w:lvl w:ilvl="{i}"><w:start w:val="1"/><w:numFmt w:val="{fmt}"/><w:lvlText w:val="{text}"/>'
                       f'<w:lvlJc w:val="left"/><w:pPr><w:ind w:left="{left}" w:hanging="360"/></w:pPr>{rpr}</w:lvl>')
        return "".join(out)

    out = [XML_HEAD, f"<w:numbering {W_NS}>",
           f'<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>{levels(True)}</w:abstractNum>',
           f'<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="hybridMultilevel"/>{levels(False)}</w:abstractNum>',
           '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>']
    for i, start in enumerate(num_lists):
        out.append(f'<w:num w:numId="{i + 2}"><w:abstractNumId w:val="1"/><w:lvlOverride w:ilvl="0">'
                   f'<w:startOverride w:val="{start}"/></w:lvlOverride></w:num>')
    out.append("</w:numbering>")
    return "".join(out)


class _DocxBuilder:
    def __init__(self):
        self.body: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.num_lists: list[int] = []     # Startwert je nummerierter Liste

    # ---------------------------------------------------------------- Läufe (Text mit Formatierung)

    def runs(self, text: str, extra: frozenset = frozenset()) -> str:
        out = []
        for seg, styles, url in inline(text):
            styles = styles | extra
            props = []
            if "code" in styles:
                props.append('<w:rStyle w:val="CodeChar"/>')
            elif url:
                props.append('<w:rStyle w:val="Hyperlink"/>')
            if "b" in styles:
                props.append("<w:b/><w:bCs/>")
            if "i" in styles:
                props.append("<w:i/><w:iCs/>")
            if "s" in styles:
                props.append("<w:strike/>")
            rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
            pieces = seg.split("\t")
            run = "<w:tab/>".join(f'<w:t xml:space="preserve">{_x(p)}</w:t>' for p in pieces)
            run = f"<w:r>{rpr}{run}</w:r>"
            if url:
                rid = f"rIdL{len(self.links) + 1}"
                self.links.append((rid, url))
                run = f'<w:hyperlink r:id="{rid}" w:history="1">{run}</w:hyperlink>'
            out.append(run)
        return "".join(out)

    def para(self, content: str, ppr: str = ""):
        self.body.append(f"<w:p>{f'<w:pPr>{ppr}</w:pPr>' if ppr else ''}{content}</w:p>")

    # ---------------------------------------------------------------- Blöcke

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
        ncols = max(len(r) for r in all_rows)
        widths = self._col_widths(all_rows, ncols)
        xml = ['<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="5000" w:type="pct"/>'
               '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" '
               'w:noHBand="0" w:noVBand="1"/></w:tblPr><w:tblGrid>']
        xml += [f'<w:gridCol w:w="{w}"/>' for w in widths]
        xml.append("</w:tblGrid>")
        for ri, row in enumerate(all_rows):
            is_head = header is not None and ri == 0
            xml.append("<w:tr>" + ("<w:trPr><w:tblHeader/></w:trPr>" if is_head else ""))
            for ci in range(ncols):
                text = row[ci] if ci < len(row) else ""
                shd = '<w:shd w:val="clear" w:color="auto" w:fill="DDEBF7"/>' if is_head else ""
                jc = aligns[ci] if ci < len(aligns) else "left"
                jc = f'<w:jc w:val="{"center" if jc == "center" else "right"}"/>' if jc != "left" else ""
                xml.append(f'<w:tc><w:tcPr><w:tcW w:w="{widths[ci]}" w:type="dxa"/>{shd}</w:tcPr>'
                           f'<w:p><w:pPr><w:spacing w:before="40" w:after="40"/>{jc}</w:pPr>'
                           f'{self.runs(text, frozenset({"b"}) if is_head else frozenset())}</w:p></w:tc>')
            xml.append("</w:tr>")
        xml.append("</w:tbl>")
        self.body.append("".join(xml))
        self.para("")  # Abstand nach der Tabelle

    @staticmethod
    def _col_widths(rows, ncols) -> list[int]:
        natural = [max(4, max((len(r[c]) if c < len(r) else 0) for r in rows)) for c in range(ncols)]
        natural = [min(n, 60) for n in natural]
        total = sum(natural)
        widths = [max(700, round(TEXT_WIDTH * n / total)) for n in natural]
        scale = TEXT_WIDTH / sum(widths)
        return [round(w * scale) for w in widths]

    def build(self, markdown: str, title: str = "") -> str:
        if title:
            self.para(self.runs(title), '<w:pStyle w:val="Title"/>')
        lines = markdown.replace("\r\n", "\n").split("\n")
        para: list[str] = []
        table: list[str] = []
        code: dict | None = None
        levels = ListLevels()
        num_id = None          # aktuelle nummerierte Liste
        skip_title = bool(title)

        def flush_para():
            if para:
                self.para('<w:r><w:br/></w:r>'.join(self.runs(p) for p in para))
                para.clear()

        for line in lines:
            if code is not None:
                if closes_fence(line, code["fence"]):
                    code = None
                else:
                    self.para(f'<w:r><w:t xml:space="preserve">{_x(line.expandtabs(4))}</w:t></w:r>',
                              '<w:pStyle w:val="Code"/>')
                continue
            kind, info = classify(line)
            if kind != "table" and table:
                self.table(table)
                table = []
            if kind != "text":
                flush_para()
            if kind not in ("bullet", "number", "blank"):
                levels.reset()
                num_id = None
            if kind == "blank":
                continue
            if kind == "fence":
                code = info
            elif kind == "table":
                table.append(line)
            elif kind == "heading":
                if skip_title and info["level"] == 1 and info["text"].strip().lower() == title.strip().lower():
                    skip_title = False
                    continue
                self.para(self.runs(info["text"]), f'<w:pStyle w:val="Heading{min(info["level"], 4)}"/>')
            elif kind == "hr":
                self.para("", '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="BFBFBF"/></w:pBdr>')
            elif kind == "pagebreak":
                self.para('<w:r><w:br w:type="page"/></w:r>')
            elif kind in ("bullet", "number"):
                lvl = min(levels.level(info["indent"]), 8)
                if kind == "bullet":
                    nid = 1
                else:
                    if num_id is None:
                        self.num_lists.append(int(info["num"]) if lvl == 0 else 1)
                        num_id = len(self.num_lists) + 1
                    nid = num_id
                text = (info.get("task") + " " if info.get("task") else "") + info["text"]
                self.para(self.runs(text), f'<w:pStyle w:val="ListParagraph"/><w:numPr><w:ilvl w:val="{lvl}"/>'
                                           f'<w:numId w:val="{nid}"/></w:numPr>')
            elif kind == "quote":
                self.para(self.runs(info["text"]), '<w:pStyle w:val="Quote"/>')
            else:
                para.append(info["text"])
        flush_para()
        if table:
            self.table(table)
        sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1417" w:right="1417" w:bottom="1134" '
                'w:left="1417" w:header="708" w:footer="708" w:gutter="0"/><w:cols w:space="708"/></w:sectPr>')
        if not self.body:
            self.para("")
        return f'{XML_HEAD}<w:document {W_NS}><w:body>{"".join(self.body)}{sect}</w:body></w:document>'


def write_docx(path, markdown: str, title: str = "") -> Path:
    path = Path(path)
    b = _DocxBuilder()
    document = b.build(markdown or "", title or "")
    rels = [("rId1", "styles", "styles.xml"), ("rId2", "numbering", "numbering.xml"),
            ("rId3", "settings", "settings.xml")] + [(rid, "hyperlink", url, True) for rid, url in b.links]
    wml = "application/vnd.openxmlformats-officedocument.wordprocessingml"
    parts = {
        "[Content_Types].xml": _content_types({
            "/word/document.xml": f"{wml}.document.main+xml", "/word/styles.xml": f"{wml}.styles+xml",
            "/word/numbering.xml": f"{wml}.numbering+xml", "/word/settings.xml": f"{wml}.settings+xml"}),
        "_rels/.rels": _package_rels("word/document.xml"),
        "word/document.xml": document,
        "word/_rels/document.xml.rels": _rels(rels),
        "word/styles.xml": DOCX_STYLES,
        "word/numbering.xml": _numbering(b.num_lists),
        "word/settings.xml": DOCX_SETTINGS,
        **_doc_props(title or path.stem),
    }
    _write_zip(path, parts)
    return path


# ====================================================================== Excel

S_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
XLSX_STYLES = XML_HEAD + f"""<styleSheet {S_NS}>
<fonts count="2"><font><sz val="11"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF305496"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="6"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
<xf numFmtId="14" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="10" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
<xf numFmtId="22" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
<dxfs count="0"/><tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>
</styleSheet>""".replace("\n", "")
ST_HEAD, ST_DATE, ST_PCT, ST_WRAP, ST_DATETIME = 1, 2, 3, 4, 5

_NUM = re.compile(r"-?(?:0|[1-9]\d{0,14})(?:[.,]\d+)?")
_PCT = re.compile(r"(-?\d{1,12}(?:[.,]\d+)?)\s?%")
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?")
_DE_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
GERMAN_FUNCS = {
    "SUMME": "SUM", "MITTELWERT": "AVERAGE", "ANZAHL": "COUNT", "ANZAHL2": "COUNTA", "WENN": "IF",
    "RUNDEN": "ROUND", "ABRUNDEN": "ROUNDDOWN", "AUFRUNDEN": "ROUNDUP", "SVERWEIS": "VLOOKUP",
    "WVERWEIS": "HLOOKUP", "XVERWEIS": "XLOOKUP", "HEUTE": "TODAY", "JETZT": "NOW", "SUMMEWENN": "SUMIF",
    "SUMMEWENNS": "SUMIFS", "ZÄHLENWENN": "COUNTIF", "ZÄHLENWENNS": "COUNTIFS", "MITTELWERTWENN": "AVERAGEIF",
    "WENNFEHLER": "IFERROR", "VERKETTEN": "CONCATENATE", "TEXTKETTE": "CONCAT", "UND": "AND", "ODER": "OR",
    "NICHT": "NOT", "LINKS": "LEFT", "RECHTS": "RIGHT", "TEIL": "MID", "LÄNGE": "LEN", "JAHR": "YEAR",
    "MONAT": "MONTH", "TAG": "DAY", "DATUM": "DATE", "WURZEL": "SQRT", "POTENZ": "POWER", "PRODUKT": "PRODUCT",
    "STABW": "STDEV", "VERGLEICH": "MATCH", "GANZZAHL": "INT", "REST": "MOD", "GROSS": "UPPER", "KLEIN": "LOWER",
}


def _col_letter(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _excel_formula(f: str) -> str:
    """Übersetzt deutsche Schreibweise (SUMME(A1;A2), 0,5) in die Dateischreibweise (SUM(A1,A2), 0.5)."""
    parts = re.split(r'("(?:[^"]|"")*")', f)
    for i in range(0, len(parts), 2):
        seg = parts[i]
        if ";" in seg:
            seg = seg.replace(",", ".").replace(";", ",")
        seg = re.sub(r"\b([A-ZÄÖÜ][A-ZÄÖÜ0-9]*)(?=\s*\()",
                     lambda m: GERMAN_FUNCS.get(m.group(1), m.group(1)), seg)
        parts[i] = seg
    return "".join(parts)


def _serial(d: datetime) -> float:
    delta = d - datetime(1899, 12, 30)
    return delta.days + delta.seconds / 86400


def _cell(ref: str, v, header: bool) -> tuple[str, int]:
    """Gibt (XML der Zelle, Anzeigebreite in Zeichen) zurück."""
    if v is None or v == "":
        return "", 0
    if isinstance(v, bool):
        return f'<c r="{ref}" t="b"><v>{int(v)}</v></c>', 6
    if isinstance(v, (int, float)) and not header:
        if isinstance(v, float) and not math.isfinite(v):
            v = str(v)
        else:
            return f'<c r="{ref}"><v>{v!r}</v></c>', min(len(f"{v:,}"), 20)
    if isinstance(v, (list, dict)):
        v = json.dumps(v, ensure_ascii=False)
    s = str(v)[:32767]
    if header:
        return f'<c r="{ref}" t="inlineStr" s="{ST_HEAD}"><is><t xml:space="preserve">{_x(s)}</t></is></c>', len(s) + 3
    if s.startswith("=") and len(s) > 1:
        return f'<c r="{ref}"><f>{_x(_excel_formula(s[1:]))}</f></c>', 12
    st = s.strip()
    m = _ISO_DATE.fullmatch(st)
    if m:
        try:
            y, mo, d, hh, mm, ss = (int(x) if x else 0 for x in m.groups())
            serial = _serial(datetime(y, mo, d, hh, mm, ss))
            style = ST_DATETIME if m.group(4) else ST_DATE
            return f'<c r="{ref}" s="{style}"><v>{serial!r}</v></c>', 17 if m.group(4) else 11
        except ValueError:
            pass
    m = _DE_DATE.fullmatch(st)
    if m:
        try:
            return f'<c r="{ref}" s="{ST_DATE}"><v>{_serial(datetime(int(m[3]), int(m[2]), int(m[1])))!r}</v></c>', 11
        except ValueError:
            pass
    if _NUM.fullmatch(st):
        num = float(st.replace(",", "."))
        text = str(int(num)) if num.is_integer() and "." not in st and "," not in st else repr(num)
        return f'<c r="{ref}"><v>{text}</v></c>', len(st)
    m = _PCT.fullmatch(st)
    if m:
        return f'<c r="{ref}" s="{ST_PCT}"><v>{float(m.group(1).replace(",", ".")) / 100!r}</v></c>', len(st) + 1
    wrap = f' s="{ST_WRAP}"' if "\n" in s else ""
    width = max(len(x) for x in s.split("\n"))
    return f'<c r="{ref}" t="inlineStr"{wrap}><is><t xml:space="preserve">{_x(s)}</t></is></c>', width


def _sheet_name(name: str, used: set) -> str:
    name = re.sub(r"[\[\]:*?/\\]", "-", str(name)).strip("' ")[:31] or "Tabelle"
    base, n = name, 2
    while name.lower() in used:
        suffix = f" ({n})"
        name = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(name.lower())
    return name


def _rows_from(value) -> list[list]:
    if isinstance(value, str):  # manche Modelle schicken CSV-Text statt einer Liste
        try:
            dialect = csv.Sniffer().sniff(value[:2000], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [row for row in csv.reader(io.StringIO(value), dialect)]
    rows = []
    for r in value or []:
        rows.append(list(r.values()) if isinstance(r, dict) else list(r) if isinstance(r, (list, tuple)) else [r])
    return rows


def write_xlsx(path, sheets) -> Path:
    path = Path(path)
    if isinstance(sheets, str):
        sheets = json.loads(sheets)
    if isinstance(sheets, dict):
        sheets = [sheets]
    used: set = set()
    parts = {}
    sheet_entries, rels, defined, overrides = [], [], [], {}
    sml = "application/vnd.openxmlformats-officedocument.spreadsheetml"
    for i, sh in enumerate(sheets or [{}]):
        sh = sh if isinstance(sh, dict) else {"rows": sh}
        name = _sheet_name(sh.get("name") or f"Tabelle{i + 1}", used)
        rows = _rows_from(sh.get("rows") if "rows" in sh else sh.get("data"))
        # Kopfzeile, wenn die erste Zeile nur aus Text besteht und weitere Zeilen folgen
        header = (len(rows) > 1 and rows[0] and
                  all(isinstance(c, str) and c.strip() and not _NUM.fullmatch(c.strip()) for c in rows[0]))
        ncols = max((len(r) for r in rows), default=0)
        widths = [0] * ncols
        xml_rows = []
        for ri, row in enumerate(rows):
            cells = []
            for ci, v in enumerate(row):
                xml, w = _cell(f"{_col_letter(ci)}{ri + 1}", v, header and ri == 0)
                cells.append(xml)
                widths[ci] = max(widths[ci], w)
            xml_rows.append(f'<row r="{ri + 1}">{"".join(cells)}</row>')
        dim = f"A1:{_col_letter(max(ncols, 1) - 1)}{max(len(rows), 1)}"
        pane = ('<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>') if header else ""
        cols = "".join(f'<col min="{c + 1}" max="{c + 1}" width="{min(60, max(8, w + 2)):.1f}" customWidth="1"/>'
                       for c, w in enumerate(widths))
        cols = f"<cols>{cols}</cols>" if cols else ""
        selected = ' tabSelected="1"' if i == 0 else ""
        autofilter = f'<autoFilter ref="{dim}"/>' if header else ""
        sheet = (f'{XML_HEAD}<worksheet {S_NS} xmlns:r="{DOC_REL}"><dimension ref="{dim}"/>'
                 f'<sheetViews><sheetView workbookViewId="0"{selected}>{pane}</sheetView></sheetViews>'
                 f'<sheetFormatPr defaultRowHeight="15"/>{cols}<sheetData>{"".join(xml_rows)}</sheetData>'
                 f'{autofilter}</worksheet>')
        parts[f"xl/worksheets/sheet{i + 1}.xml"] = sheet
        overrides[f"/xl/worksheets/sheet{i + 1}.xml"] = f"{sml}.worksheet+xml"
        sheet_entries.append(f'<sheet name="{_x(name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>')
        rels.append((f"rId{i + 1}", "worksheet", f"worksheets/sheet{i + 1}.xml"))
        if header:
            quoted = "'" + name.replace("'", "''") + "'"
            ref = re.sub(r"([A-Z]+)(\d+)", r"$\1$\2", dim)
            defined.append(f'<definedName name="_xlnm._FilterDatabase" localSheetId="{i}" hidden="1">'
                           f'{_x(quoted)}!{ref}</definedName>')
    rels.append((f"rId{len(sheet_entries) + 1}", "styles", "styles.xml"))
    defined = f"<definedNames>{''.join(defined)}</definedNames>" if defined else ""
    workbook = (f'{XML_HEAD}<workbook {S_NS} xmlns:r="{DOC_REL}"><bookViews><workbookView xWindow="0" yWindow="0" '
                f'windowWidth="16000" windowHeight="9000"/></bookViews><sheets>{"".join(sheet_entries)}</sheets>'
                f'{defined}<calcPr calcId="191029" fullCalcOnLoad="1"/></workbook>')
    parts = {
        "[Content_Types].xml": _content_types({"/xl/workbook.xml": f"{sml}.sheet.main+xml",
                                               "/xl/styles.xml": f"{sml}.styles+xml", **overrides}),
        "_rels/.rels": _package_rels("xl/workbook.xml"),
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": _rels(rels),
        "xl/styles.xml": XLSX_STYLES,
        **parts,
        **_doc_props(path.stem),
    }
    _write_zip(path, parts)
    return path


# ====================================================================== PowerPoint

P_NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        f'xmlns:r="{DOC_REL}" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
SLIDE_W, SLIDE_H = 12192000, 6858000   # 16:9
INCH = 914400
ACCENT, DARK, TEXT, MUTED = "4F46E5", "1E293B", "334155", "64748B"
GROUP = ('<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr><a:xfrm>'
         '<a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>')

PPTX_THEME = XML_HEAD + """<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="Monhip">
<a:themeElements><a:clrScheme name="Monhip">
<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1><a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>
<a:dk2><a:srgbClr val="1E293B"/></a:dk2><a:lt2><a:srgbClr val="F1F5F9"/></a:lt2>
<a:accent1><a:srgbClr val="4F46E5"/></a:accent1><a:accent2><a:srgbClr val="D97757"/></a:accent2>
<a:accent3><a:srgbClr val="0EA5E9"/></a:accent3><a:accent4><a:srgbClr val="10B981"/></a:accent4>
<a:accent5><a:srgbClr val="F59E0B"/></a:accent5><a:accent6><a:srgbClr val="EF4444"/></a:accent6>
<a:hlink><a:srgbClr val="2563EB"/></a:hlink><a:folHlink><a:srgbClr val="7C3AED"/></a:folHlink></a:clrScheme>
<a:fontScheme name="Monhip"><a:majorFont><a:latin typeface="Segoe UI Semibold"/><a:ea typeface=""/><a:cs typeface=""/>
</a:majorFont><a:minorFont><a:latin typeface="Segoe UI"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont></a:fontScheme>
<a:fmtScheme name="Office"><a:fillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"><a:tint val="50000"/></a:schemeClr></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"><a:shade val="80000"/></a:schemeClr></a:solidFill></a:fillStyleLst>
<a:lnStyleLst><a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
<a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
<a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln></a:lnStyleLst>
<a:effectStyleLst><a:effectStyle><a:effectLst/></a:effectStyle><a:effectStyle><a:effectLst/></a:effectStyle>
<a:effectStyle><a:effectLst/></a:effectStyle></a:effectStyleLst>
<a:bgFillStyleLst><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"><a:tint val="95000"/></a:schemeClr></a:solidFill>
<a:solidFill><a:schemeClr val="phClr"><a:shade val="90000"/></a:schemeClr></a:solidFill></a:bgFillStyleLst></a:fmtScheme>
</a:themeElements><a:objectDefaults/><a:extraClrSchemeLst/></a:theme>""".replace("\n", "")

PPTX_MASTER = XML_HEAD + f"""<p:sldMaster {P_NS}><p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>
<p:spTree>{GROUP}</p:spTree></p:cSld>
<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" accent4="accent4"
 accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>
<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz="4000"/></a:lvl1pPr></p:titleStyle>
<p:bodyStyle><a:lvl1pPr><a:defRPr sz="2400"/></a:lvl1pPr></p:bodyStyle>
<p:otherStyle><a:lvl1pPr><a:defRPr sz="1800"/></a:lvl1pPr></p:otherStyle></p:txStyles></p:sldMaster>""".replace("\n", "")

PPTX_LAYOUT = XML_HEAD + (f'<p:sldLayout {P_NS} type="blank" preserve="1"><p:cSld name="Leer"><p:spTree>{GROUP}'
                          '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>')


def _shape(sid: int, name: str, x, y, w, h, fill: str | None = None, body: str = "", textbox=True) -> str:
    sp_pr = (f'<a:xfrm><a:off x="{round(x)}" y="{round(y)}"/><a:ext cx="{round(w)}" cy="{round(h)}"/></a:xfrm>'
             '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
             + (f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill else "<a:noFill/>")
             + "<a:ln><a:noFill/></a:ln>")
    tb = ' txBox="1"' if textbox else ""
    return (f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{_x(name)}"/><p:cNvSpPr{tb}/><p:nvPr/></p:nvSpPr>'
            f"<p:spPr>{sp_pr}</p:spPr>{body}</p:sp>")


def _text_body(paragraphs: list[str], anchor="t", autofit=True) -> str:
    fit = "<a:normAutofit/>" if autofit else ""
    return (f'<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" rtlCol="0" anchor="{anchor}">{fit}'
            f'</a:bodyPr><a:lstStyle/>{"".join(paragraphs) or "<a:p/>"}</p:txBody>')


def _pptx_runs(text: str, size: float, color: str, bold=False, font="Segoe UI") -> str:
    out = []
    for seg, styles, _url in inline(text):
        b = ' b="1"' if bold or "b" in styles else ""
        i = ' i="1"' if "i" in styles else ""
        face = "Consolas" if "code" in styles else font
        out.append(f'<a:r><a:rPr lang="de-DE" sz="{round(size * 100)}"{b}{i} dirty="0"><a:solidFill>'
                   f'<a:srgbClr val="{color}"/></a:solidFill><a:latin typeface="{face}"/></a:rPr>'
                   f"<a:t>{_x(seg)}</a:t></a:r>")
    return "".join(out)


def _para(text: str, size: float, color: str, bold=False, font="Segoe UI", align="l", bullet=False, level=0,
          space_before=0) -> str:
    ppr = f' algn="{align}"'
    inner = f'<a:spcBef><a:spcPts val="{space_before * 100}"/></a:spcBef>' if space_before else ""
    if bullet:
        indent = round(size * 12700 * 1.1)
        ppr += f' marL="{indent * (level + 1) + level * 120000}" indent="-{indent}"'
        inner += (f'<a:buClr><a:srgbClr val="{ACCENT}"/></a:buClr><a:buFont typeface="Arial"/>'
                  f'<a:buChar char="{"•" if level == 0 else "–"}"/>')
    else:
        ppr += ' marL="0" indent="0"'
        inner += "<a:buNone/>"
    return f"<a:p><a:pPr{ppr}>{inner}</a:pPr>{_pptx_runs(text, size, color, bold, font)}</a:p>"


def _slide_items(slide: dict) -> list[tuple[str, int, bool]]:
    """(Text, Ebene, Aufzählung?) aus bullets und/oder text einer Folie."""
    items = []
    bullets = slide.get("bullets") or slide.get("points") or []
    if isinstance(bullets, str):
        bullets = bullets.split("\n")
    for b in bullets:
        if isinstance(b, dict):
            b = b.get("text", "")
        raw = str(b)
        if not raw.strip():
            continue
        level = 1 if raw.startswith(("  ", "\t")) else 0
        items.append((re.sub(r"^\s*(?:[-*•–]|\d+[.)])\s+", "", raw).strip(), level, True))
    for line in str(slide.get("text") or slide.get("content") or "").split("\n"):
        if not line.strip():
            continue
        kind, info = classify(line)
        if kind in ("bullet", "number"):
            items.append((info["text"], 1 if info["indent"] >= 2 else 0, True))
        else:
            items.append((info.get("text", line.strip()), 0, False))
    return items


def _slide_xml(shapes: list[str], bg: str | None = None) -> str:
    bg_xml = (f'<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{bg}"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>'
              if bg else "")
    return (f'{XML_HEAD}<p:sld {P_NS}><p:cSld>{bg_xml}<p:spTree>{GROUP}{"".join(shapes)}</p:spTree></p:cSld>'
            '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


def _title_slide(title: str, subtitle: str) -> str:
    x, w = 0.9 * INCH, SLIDE_W - 1.8 * INCH
    shapes = [_shape(2, "Akzent", x, 2.35 * INCH, 1.1 * INCH, 0.09 * INCH, fill=ACCENT, textbox=False),
              _shape(3, "Titel", x, 2.6 * INCH, w, 1.6 * INCH,
                     body=_text_body([_para(title, 44, "FFFFFF", bold=True, font="Segoe UI Semibold")], "t"))]
    if subtitle:
        shapes.append(_shape(4, "Untertitel", x, 4.3 * INCH, w, 1.2 * INCH,
                             body=_text_body([_para(subtitle, 22, "CBD5E1")], "t")))
    return _slide_xml(shapes, bg=DARK)


def _content_slide(slide: dict, number: int) -> str:
    title = str(slide.get("title") or "")
    items = _slide_items(slide)
    chars = sum(len(t) for t, _, _ in items)
    size = 24 if len(items) <= 5 and chars < 350 else 20 if len(items) <= 8 and chars < 650 else 16
    x, w = 0.85 * INCH, SLIDE_W - 1.7 * INCH
    paras = [_para(t, size - 2 * lvl, TEXT, bullet=b, level=lvl, space_before=10 if i else 0)
             for i, (t, lvl, b) in enumerate(items)]
    shapes = [_shape(2, "Akzent", 0.6 * INCH, 0.55 * INCH, 0.09 * INCH, 0.75 * INCH, fill=ACCENT, textbox=False),
              _shape(3, "Titel", x, 0.45 * INCH, w, 0.95 * INCH,
                     body=_text_body([_para(title, 32, DARK, bold=True, font="Segoe UI Semibold")], "ctr")),
              _shape(4, "Inhalt", x, 1.7 * INCH, w, SLIDE_H - 2.5 * INCH, body=_text_body(paras, "t")),
              _shape(5, "Foliennummer", SLIDE_W - 1.6 * INCH, SLIDE_H - 0.6 * INCH, 1.0 * INCH, 0.35 * INCH,
                     body=_text_body([_para(str(number), 12, MUTED, align="r")], "b", autofit=False))]
    return _slide_xml(shapes)


def write_pptx(path, slides, title: str = "", subtitle: str = "") -> Path:
    path = Path(path)
    if isinstance(slides, str):
        slides = json.loads(slides)
    slides = [s if isinstance(s, dict) else {"title": str(s)} for s in (slides or [])]
    xml_slides = []
    if title:
        xml_slides.append(_title_slide(title, subtitle))
    for s in slides:
        xml_slides.append(_content_slide(s, len(xml_slides) + 1))
    if not xml_slides:
        xml_slides.append(_title_slide(path.stem, ""))
    pml = "application/vnd.openxmlformats-officedocument.presentationml"
    overrides = {"/ppt/presentation.xml": f"{pml}.presentation.main+xml",
                 "/ppt/slideMasters/slideMaster1.xml": f"{pml}.slideMaster+xml",
                 "/ppt/slideLayouts/slideLayout1.xml": f"{pml}.slideLayout+xml",
                 "/ppt/theme/theme1.xml": "application/vnd.openxmlformats-officedocument.theme+xml"}
    parts, pres_rels, sld_ids = {}, [("rId1", "slideMaster", "slideMasters/slideMaster1.xml"),
                                     ("rId2", "theme", "theme/theme1.xml")], []
    for i, xml in enumerate(xml_slides, start=1):
        parts[f"ppt/slides/slide{i}.xml"] = xml
        parts[f"ppt/slides/_rels/slide{i}.xml.rels"] = _rels([("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml")])
        overrides[f"/ppt/slides/slide{i}.xml"] = f"{pml}.slide+xml"
        pres_rels.append((f"rId{i + 2}", "slide", f"slides/slide{i}.xml"))
        sld_ids.append(f'<p:sldId id="{255 + i}" r:id="rId{i + 2}"/>')
    presentation = (f'{XML_HEAD}<p:presentation {P_NS} saveSubsetFonts="1"><p:sldMasterIdLst>'
                    '<p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
                    f'<p:sldIdLst>{"".join(sld_ids)}</p:sldIdLst><p:sldSz cx="{SLIDE_W}" cy="{SLIDE_H}"/>'
                    '<p:notesSz cx="6858000" cy="9144000"/></p:presentation>')
    parts = {
        "[Content_Types].xml": _content_types(overrides),
        "_rels/.rels": _package_rels("ppt/presentation.xml"),
        "ppt/presentation.xml": presentation,
        "ppt/_rels/presentation.xml.rels": _rels(pres_rels),
        "ppt/slideMasters/slideMaster1.xml": PPTX_MASTER,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": _rels([("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"),
                                                               ("rId2", "theme", "../theme/theme1.xml")]),
        "ppt/slideLayouts/slideLayout1.xml": PPTX_LAYOUT,
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": _rels([("rId1", "slideMaster", "../slideMasters/slideMaster1.xml")]),
        "ppt/theme/theme1.xml": PPTX_THEME,
        **parts,
        **_doc_props(title or path.stem),
    }
    _write_zip(path, parts)
    return path


# ====================================================================== Lesen

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
      "r": DOC_REL}


def _q(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


def _docx_text(z: zipfile.ZipFile) -> str:
    root = ET.fromstring(z.read("word/document.xml"))
    body = root.find("w:body", NS)
    out = []

    def para_text(p) -> str:
        parts = []
        for el in p.iter():
            if el.tag == _q("w", "t"):
                parts.append(el.text or "")
            elif el.tag == _q("w", "tab"):
                parts.append("\t")
            elif el.tag in (_q("w", "br"), _q("w", "cr")):
                parts.append("\n")
        return "".join(parts)

    for el in body:
        if el.tag == _q("w", "p"):
            text = para_text(el)
            style = el.find("w:pPr/w:pStyle", NS)
            style = style.get(_q("w", "val"), "") if style is not None else ""
            if style.startswith("Heading") and style[-1:].isdigit():
                text = "#" * int(style[-1]) + " " + text
            elif style == "Title":
                text = "# " + text
            elif el.find("w:pPr/w:numPr", NS) is not None:
                text = "- " + text
            out.append(text)
        elif el.tag == _q("w", "tbl"):
            for tr in el.findall("w:tr", NS):
                cells = [" ".join(para_text(p) for p in tc.findall(".//w:p", NS)) for tc in tr.findall("w:tc", NS)]
                out.append("| " + " | ".join(cells) + " |")
            out.append("")
    return "\n".join(out).strip()


def _xlsx_text(z: zipfile.ZipFile, max_rows=500) -> str:
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("s:si", NS):
            shared.append("".join(t.text or "" for t in si.iter(_q("s", "t"))))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels}
    out = []
    for sh in wb.find("s:sheets", NS):
        target = targets.get(sh.get(_q("r", "id")), "")
        target = target.lstrip("/")
        target = target if target.startswith("xl/") else "xl/" + target
        out.append(f"## Blatt: {sh.get('name')}")
        try:
            root = ET.fromstring(z.read(target))
        except KeyError:
            continue
        for n, row in enumerate(root.iter(_q("s", "row"))):
            if n >= max_rows:
                out.append("…(weitere Zeilen gekürzt)")
                break
            values = {}
            for c in row.findall("s:c", NS):
                ref = re.match(r"([A-Z]+)", c.get("r", "A"))
                col = sum((ord(ch) - 64) * 26 ** i for i, ch in enumerate(reversed(ref.group(1)))) - 1 if ref else len(values)
                t, v, f = c.get("t"), c.find("s:v", NS), c.find("s:f", NS)
                if t == "s" and v is not None:
                    val = shared[int(v.text)] if int(v.text) < len(shared) else ""
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter(_q("s", "t")))
                elif t == "b" and v is not None:
                    val = "WAHR" if v.text == "1" else "FALSCH"
                else:
                    val = v.text if v is not None and v.text is not None else ""
                if f is not None and f.text:
                    val = f"={f.text}" + (f" → {val}" if val else "")
                values[col] = val
            if values:
                out.append(" | ".join(values.get(i, "") for i in range(max(values) + 1)))
        out.append("")
    return "\n".join(out).strip()


def _pptx_text(z: zipfile.ZipFile) -> str:
    names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                   key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    out = []
    for i, name in enumerate(names, start=1):
        out.append(f"## Folie {i}")
        root = ET.fromstring(z.read(name))
        for p in root.iter(_q("a", "p")):
            text = "".join(t.text or "" for t in p.iter(_q("a", "t")))
            if text.strip():
                out.append(text)
        out.append("")
    return "\n".join(out).strip()


def read_text(path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    with zipfile.ZipFile(path) as z:
        if suffix in (".docx", ".docm", ".dotx"):
            return _docx_text(z)
        if suffix in (".xlsx", ".xlsm", ".xltx"):
            return _xlsx_text(z)
        if suffix in (".pptx", ".pptm", ".potx"):
            return _pptx_text(z)
    raise ValueError(f"Unbekanntes Office-Format: {suffix}")


OFFICE_SUFFIXES = (".docx", ".docm", ".dotx", ".xlsx", ".xlsm", ".xltx", ".pptx", ".pptm", ".potx")
