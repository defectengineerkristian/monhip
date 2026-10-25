"""Experten-Modus: einen Ordner mit vielen Dokumenten auswerten, damit die KI darin Bescheid weiß.

Job: jede Datei einzeln – eine frische Anfrage ans geladene Modell, also ohne die vorherigen im Kontext – zu einer
kurzen Markdown-Zusammenfassung; lange Dateien stückweise (Notizen je Teil, dann zusammengefasst), eingescannte PDFs
seitenweise über das Bildverständnis (die Seitenbilder rendert Windows selbst, Windows.Data.Pdf). Dazu ein
Volltext-Index (SQLite FTS5) Seite für Seite, eine Übersicht und am Ende ein Gesamtüberblick. Fortsetzbar: fertige
Dateien werden übersprungen, geänderte neu ausgewertet, gelöschte entfernt.
Ablage: chats/experten/<Ordnername>-<Kennung>/ – der Datenordner selbst bleibt unverändert.
Library: lesender Zugriff für die Werkzeuge der KI (suchen, Zusammenfassung, Seiten lesen, Liste).
"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import urllib.error
from datetime import datetime
from pathlib import Path

import chats
import documents
from backend import ContextFull, chat_turn

DOC_SUFFIXES = set(documents.KINDS)       # PDF, Office, OpenDocument, RTF, HTML, CSV, JSON, Markdown, Text, XML, Log
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "$RECYCLE.BIN", "System Volume Information"}
MAX_FILES = 5000
SCAN_PAGES = 30                           # eingescannte PDFs: so viele Seiten werden gelesen
SUMMARY_TOKENS = 1200
NOTE_TOKENS = 700
OCR_TOKENS = 2000
SECTION_CHARS = 3000                      # Dateien ohne Seiten (Word, Text …): Abschnitte dieser Größe im Index
LIST_PAGE = 60                            # experte_liste: so viele Dateien je Seite
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SUMMARY_PROMPT = (
    "Du wertest Dokumente für einen Wissensspeicher aus. Schreibe auf Deutsch eine sachliche, knappe Zusammenfassung "
    "in genau diesem Markdown-Aufbau:\n\n## Kurzfassung\n(3 bis 5 Sätze: worum es geht, wer beteiligt ist, Ergebnis)\n\n"
    "## Kernpunkte\n(Stichpunkte)\n\n## Zahlen, Daten, Namen\n(Stichpunkte: Beträge, Fristen, Daten, Personen, Firmen, "
    "Aktenzeichen – oder „–“)\n\n{focus}## Schlagwörter\n(5 bis 10 Begriffe, durch Kommas getrennt)\n\n"
    "Nenne Seitenzahlen, wo sie erkennbar sind (z. B. „S. 3“). Erfinde nichts, was nicht im Dokument steht. Antworte "
    "nur mit diesem Markdown.")
FOCUS_PART = "## Schwerpunkt: {focus}\n(Was das Dokument dazu sagt, mit Seitenangaben – oder „Nichts dazu.“)\n\n"
NOTES_PROMPT = (
    "Du wertest einen Teil eines langen Dokuments aus. Fasse diesen Teil auf Deutsch in Stichpunkten zusammen: alle "
    "wichtigen Aussagen, Fakten, Zahlen, Fristen, Namen{focus}, jeweils mit Seitenangabe, wo erkennbar. Nur die "
    "Stichpunkte, ohne Einleitung.")
OCR_PROMPT = (
    "Schreibe den gesamten Text dieser Dokumentseite genau ab – Überschriften, Absätze, Listen, Tabellen (als "
    "Markdown-Tabelle). Nur den Text der Seite, ohne Kommentar. Ist die Seite leer oder ohne Text, antworte „(leer)“.")
OVERVIEW_PROMPT = (
    "Du bekommst Zusammenfassungen vieler Dokumente eines Ordners. Schreibe auf Deutsch einen Gesamtüberblick in "
    "Markdown: die Hauptthemen, Gemeinsamkeiten und Unterschiede, die wichtigsten Fakten, Zahlen und Fristen{focus} – "
    "bei wichtigen Punkten mit Dateinamen. Knapp und gut gegliedert, höchstens etwa 600 Wörter.")


def store_for(source: Path) -> Path:
    """Ablage einer Auswertung: chats/experten/<Ordnername>-<Kennung des vollen Pfads>/."""
    source = Path(source).resolve()
    key = hashlib.sha1(str(source).lower().encode("utf-8")).hexdigest()[:8]
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", source.name or "Laufwerk").strip(" .")[:60] or "Ordner"
    return chats.CHAT_DIR / "experten" / f"{name}-{key}"


def find_documents(source: Path) -> list[Path]:
    """Alle lesbaren Dokumente unter source (ohne versteckte und Programm-Ordner), sortiert."""
    found = []
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(filenames):
            if Path(name).suffix.lower() in DOC_SUFFIXES and not name.startswith("~$"):  # ~$ = Word-Sperrdatei
                found.append(Path(dirpath) / name)
                if len(found) >= MAX_FILES:
                    return found
    return found


def split_pages(text: str) -> list[tuple[str, int, str]]:
    """[(Art, Nummer, Text)] – PDF-Text mit „--- Seite n ---“ seitenweise, sonst in Abschnitten von ~3000 Zeichen."""
    if "--- Seite " in text:
        parts = re.split(r"--- Seite (\d+) ---\n?", text)
        return [("Seite", int(parts[i]), parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)
                if parts[i + 1].strip()]
    out, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        if cur and len(cur) + len(para) > SECTION_CHARS:
            out.append(cur)
            cur = ""
        cur += para.strip() + "\n\n"
    if cur.strip():
        out.append(cur)
    return [("Abschnitt", i, t.strip()) for i, t in enumerate(out, 1)]


def short_summary(md: str, limit: int = 220) -> str:
    """Erster Satz der Kurzfassung einer Zusammenfassung (für Übersicht und Liste)."""
    m = re.search(r"## Kurzfassung\s*\n+(.+?)(?:\n\s*\n|\n##|$)", md, re.S)
    text = " ".join((m.group(1) if m else md).split())
    first = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    return first if len(first) <= limit else first[:limit - 1].rstrip() + "…"


def _db(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=30)
    con.execute("PRAGMA journal_mode=WAL")  # die KI liest, während die Auswertung schreibt
    con.execute('CREATE VIRTUAL TABLE IF NOT EXISTS seiten USING fts5(datei UNINDEXED, art UNINDEXED, '
                'nr UNINDEXED, text, tokenize="unicode61 remove_diacritics 2")')
    return con


def _md_path(store: Path, rel: str) -> Path:
    return store / "zusammenfassungen" / (rel + ".md")


# ---------------------------------------------------------------- Seitenbilder (eingescannte PDFs)

RENDER_SCRIPT = r"""
param([string]$Pdf, [string]$Out, [int]$Max, [int]$Width)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$ext = [System.WindowsRuntimeSystemExtensions].GetMethods()
$asTask = ($ext | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
$asAction = ($ext | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncAction' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait(-1) | Out-Null; $task.Result }
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Pdf.PdfDocument, Windows.Data.Pdf, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime] | Out-Null
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Pdf)) ([Windows.Storage.StorageFile])
$doc = Await ([Windows.Data.Pdf.PdfDocument]::LoadFromFileAsync($file)) ([Windows.Data.Pdf.PdfDocument])
"SEITEN $($doc.PageCount)"
$n = [Math]::Min([int]$doc.PageCount, $Max)
for ($i = 0; $i -lt $n; $i++) {
  $page = $doc.GetPage($i)
  $opts = New-Object Windows.Data.Pdf.PdfPageRenderOptions
  $opts.DestinationWidth = $Width
  $mem = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
  $asAction.Invoke($null, @($page.RenderToStreamAsync($mem, $opts))).Wait(-1) | Out-Null
  $png = Join-Path $Out ("seite-{0:D4}.png" -f ($i + 1))
  $src = [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($mem.GetInputStreamAt(0))
  $fs = [System.IO.File]::Create($png); $src.CopyTo($fs); $fs.Close(); $page.Dispose()
  "BILD $png"
}
"""


def render_pdf(pdf: Path, out: Path, max_pages: int = SCAN_PAGES, width: int = 1400) -> tuple[list[Path], int]:
    """PDF-Seiten als PNG (Windows rendert selbst, ohne Zusatzprogramme) → ([Bilder], Seitenzahl insgesamt)."""
    out.mkdir(parents=True, exist_ok=True)
    script = out / "seiten.ps1"
    script.write_text(RENDER_SCRIPT, encoding="utf-8-sig")
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                        "-Pdf", str(pdf), "-Out", str(out), "-Max", str(max_pages), "-Width", str(width)],
                       capture_output=True, encoding="oem", errors="replace", timeout=600, creationflags=_NO_WINDOW)
    total = next((int(ln.split()[1]) for ln in r.stdout.splitlines() if ln.startswith("SEITEN ")), 0)
    pngs = [Path(ln[5:].strip()) for ln in r.stdout.splitlines() if ln.startswith("BILD ")]
    if not pngs:
        raise RuntimeError("Die Seiten ließen sich nicht als Bild darstellen" + (f": {r.stderr.strip()[:200]}"
                                                                                  if r.stderr.strip() else "."))
    return [p for p in pngs if p.is_file()], total


# ---------------------------------------------------------------- Auswertung

class ServerGone(Exception):
    """Das Modell antwortet nicht mehr (entladen, Server beendet) – die Auswertung hält an."""


class Stopped(Exception):
    """„Stoppen“ – mitten in einer Datei; sie wird beim nächsten Mal neu ausgewertet."""


class Job(threading.Thread):
    """Wertet einen Ordner im Hintergrund aus. report(art, daten) kommt aus diesem Thread – der Aufrufer leitet es in den
    Tk-Thread weiter. Arten: start, file, paused, resumed, finished, stopped, fatal."""

    def __init__(self, source: Path, base_url: str, n_ctx: int, vision: bool, focus: str, report):
        super().__init__(daemon=True)
        self.source, self.base_url, self.vision = Path(source).resolve(), base_url, vision
        self.n_ctx, self.focus, self.report = max(2048, int(n_ctx or 8192)), (focus or "").strip(), report
        self.store = store_for(self.source)
        self.stop_event = threading.Event()
        self.pause_user = threading.Event()   # „Pausieren“
        self.pause_chat = threading.Event()   # während einer Antwort im Chat (beide teilen sich das Modell)
        self._paused_for = 0.0

    # ------------------------------------------------------------ Ablauf

    def run(self):
        try:
            self._run()
        except ServerGone as e:
            self.report("fatal", f"Verbindung zum Modell verloren ({e}) – die Auswertung ist angehalten und lässt sich "
                                 "nach dem Laden fortsetzen.")
        except Exception as e:  # unerwartet: anhalten statt abstürzen
            self.report("fatal", f"Auswertung angehalten: {type(e).__name__}: {e}")

    def _run(self):
        if not self.source.is_dir():
            raise FileNotFoundError("Den Ordner gibt es nicht (mehr).")
        self.store.mkdir(parents=True, exist_ok=True)
        info = self._load_info()
        files = find_documents(self.source)
        rels = {p.relative_to(self.source).as_posix(): p for p in files}
        con = _db(self.store / "index.sqlite")
        try:
            for gone in [r for r in info["dateien"] if r not in rels]:  # inzwischen gelöscht
                self._forget(con, info, gone)
            todo = []
            for rel, p in rels.items():
                st = p.stat()
                entry = info["dateien"].get(rel)
                changed = not entry or entry.get("size") != st.st_size or entry.get("mtime") != int(st.st_mtime)
                retry_scan = entry and entry.get("status") == "scan" and self.vision
                if changed or retry_scan or (entry or {}).get("schwerpunkt", "") != self.focus:
                    todo.append(rel)
            info["schwerpunkt"], info["fertig"] = self.focus, False
            self._save_info(info)
            self.report("start", {"name": self.source.name, "total": len(rels), "todo": len(todo)})
            durations = []
            try:
                for k, rel in enumerate(todo):
                    self._wait()
                    done = len(rels) - len(todo) + k
                    eta = (sum(durations[-20:]) / len(durations[-20:]) * (len(todo) - k)) if durations else None
                    self.report("file", {"done": done, "total": len(rels), "rel": rel, "eta": eta})
                    t0, self._paused_for = time.monotonic(), 0.0
                    self._process(con, info, rel, rels[rel])
                    durations.append(max(0.0, time.monotonic() - t0 - self._paused_for))
                    self._save_info(info)
                    if k % 10 == 9:
                        self._write_overview(info)
                self._write_overview(info)
                if todo or not (self.store / "Gesamtüberblick.md").is_file():
                    self._wait()
                    self.report("file", {"done": len(rels), "total": len(rels), "rel": "", "eta": None})
                    self._write_summary_of_all(info)
            except Stopped:
                self._write_overview(info)
                self._save_info(info)
                self.report("stopped", self._stats(info, len(rels)))
                return
            info["fertig"] = True
            self._save_info(info)
            self.report("finished", self._stats(info, len(rels)))
        finally:
            con.close()

    def _wait(self):
        """Vor jeder Anfrage: Stoppen beachten, bei „Pausieren“ oder einer laufenden Chat-Antwort warten."""
        if self.stop_event.is_set():
            raise Stopped()
        if not (self.pause_user.is_set() or self.pause_chat.is_set()):
            return
        t0 = time.monotonic()
        user = self.pause_user.is_set()
        if user:
            self.report("paused", None)
        while (self.pause_user.is_set() or self.pause_chat.is_set()) and not self.stop_event.is_set():
            time.sleep(0.2)
        self._paused_for += time.monotonic() - t0
        if self.stop_event.is_set():
            raise Stopped()
        if user:
            self.report("resumed", None)

    # ------------------------------------------------------------ Eine Datei

    def _process(self, con, info: dict, rel: str, path: Path):
        """Eine Datei lesen und zusammenfassen; Index, Zusammenfassung und Stand werden erst am Ende in einem Zug
        ersetzt – ein Stopp mittendrin lässt den bisherigen Stand dieser Datei unverändert."""
        st = path.stat()
        entry = {"size": st.st_size, "mtime": int(st.st_mtime), "schwerpunkt": self.focus,
                 "art": documents.KINDS.get(path.suffix.lower(), "Text"),
                 "ausgewertet": datetime.now().strftime("%Y-%m-%d %H:%M")}
        parts, md_text = [], None
        try:
            text, pages, scan = self._read(path, rel)
        except (ServerGone, Stopped):
            raise
        except Exception as e:  # unlesbar, beschädigt, verschlüsselt …
            text, pages, scan = "", 0, False
            entry.update(status="fehler", fehler=str(e)[:300])
        if "status" in entry:  # Fehler beim Lesen
            pass
        elif text is None:  # Scan, aber kein Bildverständnis
            entry.update(status="scan", seiten=pages)
        else:
            parts = split_pages(text)
            if not "".join(t for _, _, t in parts).strip():
                entry.update(status="leer", seiten=pages)
            else:
                body = self._summarize(rel, entry["art"], pages, parts)
                unit = f"{pages} Seiten" if pages else f"{len(parts)} Abschnitt{'e' if len(parts) != 1 else ''}"
                md_text = (f"# {Path(rel).stem}\n\nDatei: {rel} · {entry['art']}"
                           f"{' (Scan, abgeschrieben)' if scan else ''} · {unit} · ausgewertet am "
                           f"{datetime.now():%d.%m.%Y}\n\n{body.strip()}\n")
                entry.update(status="ok", seiten=pages or None, scan=scan or None, kurz=short_summary(body))
        con.execute("DELETE FROM seiten WHERE datei = ?", (rel,))
        con.executemany("INSERT INTO seiten (datei, art, nr, text) VALUES (?, ?, ?, ?)",
                        [(rel, art, nr, t) for art, nr, t in parts])
        con.commit()
        md = _md_path(self.store, rel)
        if md_text:
            md.parent.mkdir(parents=True, exist_ok=True)
            md.write_text(md_text, encoding="utf-8")
        else:
            md.unlink(missing_ok=True)
        info["dateien"][rel] = entry

    def _read(self, path: Path, rel: str) -> tuple[str | None, int, bool]:
        """(Text, Seitenzahl, Scan?) – Text None: Scan ohne Bildverständnis."""
        try:
            doc = documents.read(path)
            return doc.text, doc.pages or 0, False
        except ValueError as e:
            if path.suffix.lower() != ".pdf" or "eingescannt" not in str(e):
                raise
        if not self.vision:
            return None, 0, True
        tmp = Path(tempfile.mkdtemp(prefix="experte-"))
        try:
            pngs, total = render_pdf(path, tmp)
            texts = []
            for i, png in enumerate(pngs, 1):
                self._wait()
                page = self._ask([{"role": "user", "content": OCR_PROMPT, "_image_files": [str(png)]}], OCR_TOKENS)
                if page.strip() and page.strip() != "(leer)":
                    texts.append(f"--- Seite {i} ---\n{page.strip()}")
            if total > len(pngs):
                texts.append(f"--- Seite {len(pngs)} ---\n(Nur die ersten {len(pngs)} von {total} Seiten gelesen.)")
            return "\n".join(texts), total, True
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _summarize(self, rel: str, kind: str, pages: int, parts: list) -> str:
        focus = FOCUS_PART.format(focus=self.focus) if self.focus else ""
        system = SUMMARY_PROMPT.format(focus=focus)
        budget = max(6000, int(self.n_ctx * 3 * 0.45))  # Zeichen je Anfrage (~45 % des Kontexts)
        for _attempt in range(3):
            chunks = self._chunks(parts, budget)
            try:
                if len(chunks) == 1:
                    content = chunks[0]
                else:  # zu lang für eine Anfrage: erst Notizen je Teil, dann daraus die Zusammenfassung
                    notes_system = NOTES_PROMPT.format(focus=f" und alles zu „{self.focus}“" if self.focus else "")
                    notes = []
                    for k, chunk in enumerate(chunks, 1):
                        self._wait()
                        notes.append(f"### Teil {k} von {len(chunks)}\n" + self._ask(
                            [{"role": "system", "content": notes_system},
                             {"role": "user", "content": f"<teil datei=\"{rel}\">\n{chunk}\n</teil>"}], NOTE_TOKENS))
                    content = "Notizen zu den Teilen des Dokuments:\n\n" + "\n\n".join(notes)
                    if len(content) > budget:
                        content = content[:budget] + "\n…"
                user = f'<dokument name="{rel}" art="{kind}"{f" seiten={pages}" if pages else ""}>\n{content}\n</dokument>'
                return self._ask([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                 SUMMARY_TOKENS)
            except ContextFull:
                budget //= 2  # Kontext kleiner als gedacht: kleinere Stücke
        raise RuntimeError("Das Dokument passt auch in kleinen Stücken nicht in den Kontext.")

    @staticmethod
    def _chunks(parts: list, budget: int) -> list[str]:
        chunks, cur = [], ""
        for art, nr, text in parts:
            block = f"[{art} {nr}]\n{text}\n\n"
            while len(block) > budget:  # einzelne Riesenseite
                if cur:
                    chunks.append(cur)
                    cur = ""
                chunks.append(block[:budget])
                block = block[budget:]
            if cur and len(cur) + len(block) > budget:
                chunks.append(cur)
                cur = ""
            cur += block
        if cur:
            chunks.append(cur)
        return chunks or [""]

    def _ask(self, messages: list, max_tokens: int) -> str:
        params = {"max_tokens": max_tokens, "temperature": 0.2, "chat_template_kwargs": {"enable_thinking": False}}
        try:
            text, _calls, _reasoning = chat_turn(self.base_url, messages, params, None, self.stop_event,
                                                 lambda kind, data: None)
        except ContextFull:
            raise
        except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
            raise ServerGone(type(e).__name__) from None
        if self.stop_event.is_set():
            raise Stopped()
        return re.sub(r"(?s)<think>.*?(</think>|$)", "", text).strip()

    # ------------------------------------------------------------ Übersicht, Gesamtüberblick, Ablage

    def _forget(self, con, info: dict, rel: str):
        con.execute("DELETE FROM seiten WHERE datei = ?", (rel,))
        con.commit()
        info["dateien"].pop(rel, None)
        _md_path(self.store, rel).unlink(missing_ok=True)

    def _write_overview(self, info: dict):
        files = info["dateien"]
        ok = sum(1 for e in files.values() if e.get("status") == "ok")
        lines = [f"# Übersicht: {self.source.name}", "",
                 f"{ok} von {len(files)} Dokumenten ausgewertet · Stand {datetime.now():%d.%m.%Y %H:%M}"
                 + (f" · Schwerpunkt: {self.focus}" if self.focus else ""), ""]
        for rel in sorted(files, key=str.lower):
            lines.append(f"- {rel} · {_describe(files[rel])}")
        (self.store / "Übersicht.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_summary_of_all(self, info: dict):
        """Gesamtüberblick in Stufen: je so viele Zusammenfassungen, wie in eine Anfrage passen, dann daraus weiter."""
        items = []
        for rel in sorted(info["dateien"], key=str.lower):
            if info["dateien"][rel].get("status") != "ok":
                continue
            md = _md_path(self.store, rel)
            text = md.read_text(encoding="utf-8") if md.is_file() else ""
            keep = re.findall(r"(## (?:Kurzfassung|Schwerpunkt[^\n]*)\n.*?)(?=\n## |\Z)", text, re.S)
            items.append(f"### {rel}\n" + ("\n".join(keep) if keep else short_summary(text)))
        if not items:
            return
        focus = f" und alles zu „{self.focus}“" if self.focus else ""
        system = OVERVIEW_PROMPT.format(focus=focus)
        budget = max(6000, int(self.n_ctx * 3 * 0.45))
        while True:
            groups, cur = [], ""
            for item in items:
                if cur and len(cur) + len(item) > budget:
                    groups.append(cur)
                    cur = ""
                cur += item[:budget] + "\n\n"
            groups.append(cur)
            results = []
            for group in groups:
                self._wait()
                results.append(self._ask([{"role": "system", "content": system},
                                          {"role": "user", "content": f"<zusammenfassungen>\n{group}\n</zusammenfassungen>"}],
                                         SUMMARY_TOKENS))
            if len(results) == 1:
                break
            items = [f"### Teilüberblick {k}\n{r}" for k, r in enumerate(results, 1)]
        head = (f"# Gesamtüberblick: {self.source.name}\n\n{len(info['dateien'])} Dokumente · erstellt am "
                f"{datetime.now():%d.%m.%Y}\n\n")
        (self.store / "Gesamtüberblick.md").write_text(head + results[0].strip() + "\n", encoding="utf-8")

    def _load_info(self) -> dict:
        path = self.store / "stand.json"
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(info.get("dateien"), dict):
                raise ValueError
        except (OSError, ValueError, AttributeError):
            info = {"dateien": {}}
        info.update(quelle=str(self.source), name=self.source.name)
        return info

    def _save_info(self, info: dict):
        info["geaendert"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tmp = self.store / "stand.tmp"
        tmp.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.store / "stand.json")

    @staticmethod
    def _stats(info: dict, total: int) -> dict:
        count = lambda s: sum(1 for e in info["dateien"].values() if e.get("status") == s)
        return {"total": total, "ok": count("ok"), "scan": count("scan"), "fehler": count("fehler"),
                "leer": count("leer")}


def _describe(e: dict) -> str:
    status = e.get("status")
    unit = f"{e['seiten']} Seiten" if e.get("seiten") else ""
    kind = ", ".join(p for p in (e.get("art", ""), unit) if p)
    if status == "ok":
        return f"{kind}{' (Scan)' if e.get('scan') else ''} – {e.get('kurz', '')}"
    if status == "scan":
        return f"{kind} – eingescannt, nicht gelesen (das geladene Modell hat kein Bildverständnis)"
    if status == "leer":
        return f"{kind} – kein Text"
    return f"{kind} – nicht lesbar: {e.get('fehler', '')}"


def status_of(source: Path) -> dict | None:
    """Stand einer Auswertung (aus stand.json) oder None, wenn es noch keine gibt."""
    try:
        info = json.loads((store_for(source) / "stand.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    files = info.get("dateien") or {}
    return {"fertig": bool(info.get("fertig")), "dateien": len(files), "schwerpunkt": info.get("schwerpunkt", ""),
            "ok": sum(1 for e in files.values() if e.get("status") == "ok")}


# ---------------------------------------------------------------- Lesen (Werkzeuge der KI)

class Library:
    """Lesender Zugriff auf eine Auswertung – nur auf deren Ablage, nie auf andere Dateien."""

    def __init__(self, source: Path):
        self.source = Path(source)
        self.store = store_for(source)

    @property
    def info(self) -> dict:
        try:
            return json.loads((self.store / "stand.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"dateien": {}}

    def _file(self, name: str) -> str:
        """Datei der Auswertung zu einer Angabe der KI (genauer Pfad, Dateiname oder eindeutiger Teil davon)."""
        files = list(self.info.get("dateien", {}))
        want = str(name or "").replace("\\", "/").strip().strip('"').lower()
        if not want:
            raise LookupError("Bitte eine Datei angeben (Name wie in experte_liste).")
        for test in (lambda r: r.lower() == want, lambda r: Path(r).name.lower() == want,
                     lambda r: Path(r).stem.lower() == want, lambda r: want in r.lower()):
            hits = [r for r in files if test(r)]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                raise LookupError("Mehrere Dateien passen: " + ", ".join(hits[:10]) + " – bitte genauer angeben.")
        raise LookupError(f"Keine Datei „{name}“ in der Auswertung – siehe experte_liste.")

    def search(self, query: str, file: str = "", limit: int = 8) -> str:
        words = re.findall(r"\w+", str(query or "").lower())
        if not words:
            raise LookupError("Bitte Suchbegriffe angeben.")
        terms = [f'"{w}"*' if len(w) >= 4 else f'"{w}"' for w in words[:12]]
        rel = self._file(file) if file else None
        path = self.store / "index.sqlite"
        if not path.is_file():
            return "Der Ordner ist noch nicht ausgewertet."
        con = _db(path)
        try:
            rows = []
            for joiner in (" ", " OR "):  # erst alle Begriffe, sonst irgendeiner
                sql = ("SELECT datei, art, nr, snippet(seiten, 3, '»', '«', ' … ', 28) FROM seiten WHERE seiten MATCH ?"
                       + (" AND datei = ?" if rel else "") + " ORDER BY rank LIMIT ?")
                rows = con.execute(sql, (joiner.join(terms), *([rel] if rel else []), limit)).fetchall()
                if rows or len(terms) == 1:
                    break
        finally:
            con.close()
        if not rows:
            return f"Keine Treffer für „{query}“" + (f" in {rel}" if rel else "") + "."
        out = [f"{i}. {d} · {art} {nr}: {' '.join(s.split())}" for i, (d, art, nr, s) in enumerate(rows, 1)]
        return "\n".join(out) + "\n(Mit experte_lesen die Seite im Wortlaut lesen.)"

    def summary(self, file: str) -> str:
        rel = self._file(file)
        md = _md_path(self.store, rel)
        if md.is_file():
            return md.read_text(encoding="utf-8")
        return f"{rel}: {_describe(self.info['dateien'].get(rel, {}))}"

    def read(self, file: str, start=1, end=None, max_chars: int = 12_000) -> str:
        rel = self._file(file)
        con = _db(self.store / "index.sqlite")
        try:
            rows = con.execute("SELECT art, nr, text FROM seiten WHERE datei = ? ORDER BY rowid", (rel,)).fetchall()
        finally:
            con.close()
        if not rows:
            return f"Von {rel} gibt es keinen Text im Index ({_describe(self.info['dateien'].get(rel, {}))})."
        start = max(1, int(start or 1))
        end = int(end) if end else start + 4
        out, used, last = [], 0, None
        for art, nr, text in rows:
            if not start <= int(nr) <= end:
                continue
            if used and used + len(text) > max_chars:
                break
            out.append(f"--- {art} {nr} ---\n{text}")
            used += len(text)
            last = int(nr)
        if not out:
            return f"{rel} hat {len(rows)} {rows[0][0]}{'n' if rows[0][0] == 'Seite' else 'e'} – {start} gibt es nicht."
        more = f"\n…(weiter mit von={last + 1})" if last is not None and last < int(rows[-1][1]) else ""
        return f"{rel}:\n" + "\n\n".join(out) + more

    def listing(self, page=1, filter: str = "") -> str:
        files = self.info.get("dateien", {})
        names = sorted((r for r in files if not filter or str(filter).lower() in r.lower()), key=str.lower)
        page = max(1, int(page or 1))
        part = names[(page - 1) * LIST_PAGE:page * LIST_PAGE]
        if not part:
            return "Keine (weiteren) Dateien." if names else "Keine passenden Dateien."
        pages = -(-len(names) // LIST_PAGE)
        out = [f"{r} · {_describe(files[r])}" for r in part]
        return (f"Dokumente {(page - 1) * LIST_PAGE + 1}–{(page - 1) * LIST_PAGE + len(part)} von {len(names)}:\n"
                + "\n".join(out) + (f"\n…(weiter mit seite={page + 1})" if page < pages else ""))

    def prompt_block(self, max_chars: int = 4000) -> str:
        """Grundwissen für den System-Prompt: Gesamtüberblick (gekürzt) bzw. der Anfang der Übersicht."""
        for name in ("Gesamtüberblick.md", "Übersicht.md"):
            p = self.store / name
            if p.is_file():
                text = p.read_text(encoding="utf-8").strip()
                return text if len(text) <= max_chars else text[:max_chars].rstrip() + "\n…(gekürzt – mehr mit experte_liste)"
        return "(Noch keine Auswertung vorhanden.)"
