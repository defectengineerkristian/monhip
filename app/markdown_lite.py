"""Kleiner Markdown-Leser für die Chatanzeige und den Word-Export (was Sprachmodelle üblicherweise schreiben)."""

import re

_INLINE = re.compile(
    r"(?P<code>`+)(?P<code_t>.+?)(?P=code)"
    r"|\*\*\*(?P<bi>\S(?:.*?\S)?)\*\*\*"
    r"|\*\*(?P<b>\S(?:.*?\S)?)\*\*"
    r"|(?<!\w)__(?P<b2>\S(?:.*?\S)?)__(?!\w)"
    r"|(?<![\w*])\*(?P<i>[^*\s](?:[^*]*?[^*\s])?)\*(?![\w*])"
    r"|(?<![\w_])_(?P<i2>[^_\s](?:[^_]*?[^_\s])?)_(?![\w_])"
    r"|~~(?P<s>\S(?:.*?\S)?)~~"
    r"|\[(?P<lt>[^\]]+)\]\((?P<lu>[^)\s]+)(?:\s+\"[^\"]*\")?\)"
    r"|<(?P<au>https?://[^>\s]+)>"
    r"|(?P<url>https?://[^\s<>()\[\]]*[^\s<>()\[\].,;:!?'\"*_])"
)
_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|~>])")

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([^`\s]*)")
_FENCE_CLOSE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*$")
_HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_HR = re.compile(r"^\s{0,3}(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$")
_BULLET = re.compile(r"^(\s*)[-*+•]\s+(.*)$")
_NUMBER = re.compile(r"^(\s*)(\d{1,4})[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_TASK = re.compile(r"^\[([ xX])\]\s+(.*)$")
_SEP_CELL = re.compile(r":?-+:?")


def _is_web(url: str) -> bool:
    return url.lower().startswith(("http://", "https://", "mailto:"))


def _add(out: list, text: str, styles: frozenset, url):
    if not text:
        return
    if out and out[-1][1] == styles and out[-1][2] == url:
        out[-1] = (out[-1][0] + text, styles, url)
    else:
        out.append((text, styles, url))


def inline(text: str, styles: frozenset = frozenset(), url: str | None = None) -> list[tuple]:
    """Zerlegt eine Zeile in (Text, Stile, Link)-Stücke. Stile: "b", "i", "s", "code"."""
    # Mit \ geschützte Zeichen vorübergehend durch Zeichen aus dem privaten Unicode-Bereich ersetzen
    protected = _ESCAPED.sub(lambda m: chr(0xE000 + ord(m.group(1))), text)
    return [(_unprotect(s), st, _unprotect(u) if u else u) for s, st, u in _inline(protected, styles, url)]


def _unprotect(text: str) -> str:
    return re.sub("[-]", lambda m: chr(ord(m.group(0)) - 0xE000), text)


def _inline(text: str, styles: frozenset, url: str | None) -> list[tuple]:
    out: list[tuple] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            _add(out, text[pos:m.start()], styles, url)
        g = m.groupdict()
        if g["code_t"] is not None:
            _add(out, g["code_t"].strip() or g["code_t"], styles | {"code"}, url)
        elif g["bi"] is not None:
            out += _inline(g["bi"], styles | {"b", "i"}, url)
        elif g["b"] is not None or g["b2"] is not None:
            out += _inline(g["b"] or g["b2"], styles | {"b"}, url)
        elif g["i"] is not None or g["i2"] is not None:
            out += _inline(g["i"] or g["i2"], styles | {"i"}, url)
        elif g["s"] is not None:
            out += _inline(g["s"], styles | {"s"}, url)
        elif g["lt"] is not None:
            out += _inline(g["lt"], styles, g["lu"] if _is_web(g["lu"]) else url)
        else:
            link = g["au"] or g["url"]
            _add(out, link, styles, link)
        pos = m.end()
    if pos < len(text):
        _add(out, text[pos:], styles, url)
    return out


def plain(text: str) -> str:
    """Text ohne Markdown-Zeichen (z. B. für Tabellenzellen)."""
    return "".join(seg for seg, _, _ in inline(text))


def classify(line: str) -> tuple[str, dict]:
    """Ordnet eine Zeile ein: blank, fence, heading, hr, table, bullet, number, quote, pagebreak oder text."""
    if not line.strip():
        return "blank", {}
    m = _FENCE.match(line)
    if m:
        return "fence", {"fence": m.group(1), "lang": m.group(2).lower()}
    m = _HEAD.match(line)
    if m:
        return "heading", {"level": len(m.group(1)), "text": m.group(2)}
    if _HR.match(line):
        return "hr", {}
    s = line.strip()
    if s.startswith("|") and s.count("|") >= 2:
        return "table", {}
    m = _BULLET.match(line)
    if m:
        info = {"indent": len(m.group(1).expandtabs(4)), "text": m.group(2), "task": None}
        t = _TASK.match(m.group(2))
        if t:
            info["task"] = "☐" if t.group(1) == " " else "☑"
            info["text"] = t.group(2)
        return "bullet", info
    m = _NUMBER.match(line)
    if m:
        return "number", {"indent": len(m.group(1).expandtabs(4)), "num": m.group(2), "text": m.group(3)}
    m = _QUOTE.match(line)
    if m:
        return "quote", {"text": m.group(1)}
    if s in ("\\newpage", "\\pagebreak"):
        return "pagebreak", {}
    return "text", {"text": s}


def closes_fence(line: str, fence: str) -> bool:
    m = _FENCE_CLOSE.match(line)
    return bool(m) and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence)


def split_row(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def is_separator_row(cells: list[str]) -> bool:
    cells = [c.replace(" ", "") for c in cells]
    return any(cells) and all(_SEP_CELL.fullmatch(c) for c in cells if c)


def alignment(cell: str) -> str:
    c = cell.strip()
    if c.startswith(":") and c.endswith(":"):
        return "center"
    return "right" if c.endswith(":") else "left"


class ListLevels:
    """Merkt sich die Einrückungen einer Liste und macht daraus Ebenen (0, 1, 2 …)."""

    def __init__(self):
        self.stack: list[int] = []

    def level(self, indent: int) -> int:
        while self.stack and indent < self.stack[-1]:
            self.stack.pop()
        if not self.stack or indent > self.stack[-1]:
            self.stack.append(indent)
        return len(self.stack) - 1

    def reset(self):
        self.stack.clear()
