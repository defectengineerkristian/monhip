"""Internetzugriff: Websuche (DuckDuckGo ohne Schlüssel, optional Brave-API) und Seitenabruf als Text."""

import gzip
import ipaddress
import json
import re
import socket
import threading
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_public(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect)


def _get(url: str, data: bytes | None = None, headers: dict | None = None, timeout=20):
    h = {"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9,en;q=0.8", "Accept-Encoding": "gzip"}
    h.update(headers or {})
    with _opener.open(urllib.request.Request(url, data=data, headers=h), timeout=timeout) as r:
        raw = r.read(5 * 1024 * 1024)
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        charset = r.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, "replace"), r.headers.get_content_type(), r.geturl()


# ---------------------------------------------------------------- Suche

class _DDGParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results, self._field = [], None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "a" and "result__a" in cls:
            self.results.append({"title": "", "url": _unwrap(a.get("href", "")), "snippet": ""})
            self._field = "title"
        elif "result__snippet" in cls and self.results:
            self._field = "snippet"

    def handle_endtag(self, tag):
        if tag in ("a", "div", "td"):
            self._field = None

    def handle_data(self, data):
        if self._field and self.results:
            self.results[-1][self._field] += data


def _unwrap(href: str) -> str:
    if "uddg=" in href:
        return urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(href).query)["uddg"][0])
    return "https:" + href if href.startswith("//") else href


def search_duckduckgo(query: str, n: int = 8) -> list[dict]:
    html, _, _ = _get("https://html.duckduckgo.com/html/",
                      data=urllib.parse.urlencode({"q": query, "kl": "de-de"}).encode())
    p = _DDGParser()
    p.feed(html)
    out = [r for r in p.results if r["url"].startswith("http") and "duckduckgo.com/y.js" not in r["url"]]
    if not out and ("anomaly" in html.lower() or "captcha" in html.lower()):
        raise RuntimeError("DuckDuckGo blockiert gerade automatische Anfragen. Später erneut versuchen "
                           "oder einen Brave-Search-API-Schlüssel eintragen.")
    return out[:n]


def search_brave(query: str, api_key: str, n: int = 8) -> list[dict]:
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": n, "search_lang": "de"})
    body, _, _ = _get(url, headers={"Accept": "application/json", "X-Subscription-Token": api_key})
    items = json.loads(body).get("web", {}).get("results", [])
    return [{"title": i.get("title", ""), "url": i.get("url", ""),
             "snippet": re.sub(r"<[^>]+>", "", i.get("description", ""))} for i in items[:n]]


def search(query: str, brave_key: str = "", n: int = 8) -> str:
    results = search_brave(query, brave_key, n) if brave_key else search_duckduckgo(query, n)
    if not results:
        return "Keine Treffer."
    return "\n\n".join(f"[{i}] {r['title'].strip()}\n{r['url']}\n{' '.join(r['snippet'].split())}"
                       for i, r in enumerate(results, 1))


# ---------------------------------------------------------------- Seitenabruf

class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside", "iframe"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "table"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip, self.title, self._in_title = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")
        if tag in ("h1", "h2", "h3"):
            self.parts.append("## ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip:
            self.parts.append(data)


def _check_public(url: str):
    """Verhindert, dass Webseiten das Modell auf Geräte im eigenen Netzwerk lenken."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Nur http(s)-Adressen sind erlaubt.")
    for info in socket.getaddrinfo(parsed.hostname, None):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise PermissionError(f"Zugriff auf lokale/private Adresse blockiert: {parsed.hostname}")


def html_to_text(html: str) -> tuple[str, str]:
    """(Titel, lesbarer Text) einer HTML-Seite – ohne Skripte, Menüs und Fußzeilen."""
    p = _TextExtractor()
    p.feed(html)
    return " ".join(p.title.split()), tidy("".join(p.parts))


def tidy(text: str) -> str:
    lines = [" ".join(l.split()) for l in text.splitlines()]
    lines = [l for l in lines if l != "##"]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


CACHE_SECS, CACHE_MAX = 600, 8
_pages: dict[str, tuple[float, str, str, str]] = {}  # URL → (Zeit, Quelle, Titel, Text): Weiterlesen ohne Neuladen
_pages_lock = threading.Lock()                       # Chat und eigene KI im Raum können gleichzeitig abrufen


def _page(url: str) -> tuple[str, str, str]:
    """(Quelle nach Weiterleitungen, Titel, Text) einer Seite – 10 Minuten zwischengespeichert."""
    with _pages_lock:
        hit = _pages.get(url)
    if hit and time.time() - hit[0] < CACHE_SECS:
        return hit[1:]
    _check_public(url)
    body, ctype, final = _get(url)
    if "html" in ctype:
        title, text = html_to_text(body)
    elif ctype.startswith("text/") or "json" in ctype or "xml" in ctype:
        text, title = tidy(body), ""
    else:
        raise ValueError(f"Inhaltstyp {ctype} kann nicht als Text gelesen werden.")
    with _pages_lock:
        _pages[url] = (time.time(), final, title, text)
        while len(_pages) > CACHE_MAX:
            _pages.pop(next(iter(_pages)))
    return final, title, text


def fetch(url: str, max_chars: int = 8000, start: int = 0) -> str:
    """Text einer Seite ab Zeichen start, höchstens max_chars – geschnitten an einem Zeilen- bzw. Wortende; der
    Hinweis am Ende nennt den nächsten start."""
    final, title, text = _page(url)
    total = len(text)
    start = max(0, min(int(start), total))
    end = min(total, start + max_chars)
    if end < total:
        cut = text.rfind("\n", start + max_chars // 2, end)
        if cut < 0:
            cut = text.rfind(" ", start + max_chars // 2, end)
        if cut > 0:
            end = cut + 1
    head = f"Quelle: {final}\nTitel: {title}\n\n"
    if start == 0 and end == total:
        return head + text
    more = f" – weiter mit start={end}" if end < total else " – Ende der Seite"
    return head + text[start:end].rstrip() + f"\n…(Zeichen {start}–{end} von {total}{more})"
