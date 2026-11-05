"""Jupyter-Notebooks (.ipynb) für den Agenten: notebook_lesen, notebook_anlegen, notebook_zelle, notebook_ausfuehren.

Lesen und Ändern direkt im Dateiformat (nbformat 4, JSON) – geschrieben wie von Jupyter selbst (Einrückung 1,
sortierte Schlüssel, Quelltext als Zeilenliste), damit Änderungen klein bleiben; Monhip braucht dafür kein Jupyter.
Abbildungen (PNG/JPG in den Ausgaben und Bilder in Markdown-Zellen) kommen als Dateien nach FIGURE_DIR – das Modell
bekommt sie wie bei view_image als Bild. Ausführen braucht ein Python mit Jupyter (find_python); dort läuft
notebook_runner.py, das Ergebnis übernimmt erst der Agent (mit Checkpoint).
"""

import base64
import binascii
import hashlib
import html
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import NamedTuple

import images
import plattform

FIGURE_DIR = images.TEMP_DIR / "notebook"
MAX_FIGURES = 4             # so viele Abbildungen je Werkzeug-Ergebnis (jede kostet das Modell Hunderte Tokens)
READ_CHARS = 12_000         # Text je Werkzeug-Ergebnis (weiter mit zellen)
OUTPUT_CHARS = 1_500        # je Ausgabe einer Zelle – Anfang und Ende bleiben
OUTPUT_LINES = (25, 10)     # … ebenso in Zeilen (Anfang, Ende)
TRACE_LINES = 25            # Fehler: die letzten Zeilen des Tracebacks (dort steht die Ursache)
RUNNER = Path(__file__).with_name("notebook_runner.py")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TAG = re.compile(r"<[^>]+>")
IMAGE_TYPES = {"image/png": ("PNG", ".png"), "image/jpeg": ("JPG", ".jpg")}
KINDS = {"code": "Code", "markdown": "Markdown", "raw": "Raw"}
NEEDS = "import nbclient, nbformat, ipykernel"
NO_VISION = ("Abbildungen kannst du nur ansehen, wenn ein Modell mit Bildverständnis geladen ist – gerade siehst "
             "du nur ihre Größe.")
# Python aus dem Notebook-Kernel-Start: -c statt Skriptpfad, damit nicht app/ vorn im sys.path des Nutzer-Pythons steht
BOOT = ("import sys; p = sys.argv[1]; sys.argv = sys.argv[1:]; "
        "exec(compile(open(p, encoding='utf-8').read(), p, 'exec'), {'__name__': '__main__'})")


class NotebookError(Exception):
    """Verständliche Meldung fürs Modell."""


class Figure(NamedTuple):
    label: str      # „Abbildung 3.1“ bzw. „Bild 2.1“ (Markdown)
    cell: int       # Zellennummer ab 1
    path: Path
    info: str       # „PNG 640×480“


# ------------------------------------------------------------------ Datei

def load(path: Path) -> dict:
    try:
        nb = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError:
        raise NotebookError(f"{Path(path).name} ist kein Notebook (keine UTF-8-Textdatei).") from None
    except json.JSONDecodeError as e:
        raise NotebookError(f"{Path(path).name} ist kein gültiges Notebook (kein JSON: {e}).") from None
    check(nb, Path(path).name)
    return nb


def check(nb, name: str = "Das Notebook"):
    if not isinstance(nb, dict) or not isinstance(nb.get("cells"), list):
        raise NotebookError(f"{name} ist kein Jupyter-Notebook (es fehlt die Zellenliste).")
    if nb.get("nbformat") != 4:
        raise NotebookError(f"{name} hat das alte Format nbformat {nb.get('nbformat')} – einmal in Jupyter öffnen und "
                            "speichern, dann geht es.")
    for cell in nb["cells"]:
        if not isinstance(cell, dict) or cell.get("cell_type") not in KINDS:
            raise NotebookError(f"{name} enthält eine ungültige Zelle.")


def dumps(nb: dict) -> str:
    """Wie Jupyter (nbformat.writes): Einrückung 1, sortierte Schlüssel, Umlaute unverändert, Zeilenumbruch am Ende."""
    return json.dumps(nb, indent=1, sort_keys=True, ensure_ascii=False, separators=(",", ": ")) + "\n"


def save(path: Path, nb: dict):
    write_bytes(path, dumps(nb).encode("utf-8"))


def write_bytes(path: Path, data: bytes):
    """Erst daneben schreiben, dann ersetzen – Jupyter (oder ein Absturz) sieht nie eine halbe Datei."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.monhip-tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)
        path.write_bytes(data)


def text(value) -> str:
    """Quelltext bzw. Ausgabe: im Format als Zeilenliste oder als eine Zeichenkette."""
    return "".join(map(str, value)) if isinstance(value, list) else str(value or "")


def lines(content: str) -> list[str]:
    return str(content).splitlines(keepends=True)


def new_cell(nb: dict, kind: str, content: str) -> dict:
    cell = {"cell_type": kind, "metadata": {}, "source": lines(content)}
    if kind == "code":
        cell.update(execution_count=None, outputs=[])
    if nb.get("nbformat_minor", 0) >= 5:  # ab 4.5 hat jede Zelle eine eindeutige id
        used = {c.get("id") for c in nb["cells"]}
        cid = uuid.uuid4().hex[:8]
        while cid in used:
            cid = uuid.uuid4().hex[:8]
        cell["id"] = cid
    return cell


def new_notebook(cells: list[tuple[str, str]]) -> dict:
    nb = {"cells": [], "metadata": {"kernelspec": {"display_name": "Python 3 (ipykernel)", "language": "python",
                                                   "name": "python3"},
                                    "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5}
    for kind, content in cells:
        nb["cells"].append(new_cell(nb, kind, content))
    return nb


def cell_specs(raw) -> list[tuple[str, str]]:
    """Zellen für notebook_anlegen: [{"typ", "inhalt"}] – nachsichtig bei Schlüsselnamen und bloßen Zeichenketten."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = [raw]
    if not isinstance(raw, list) or not raw:
        raise NotebookError("zellen muss eine Liste sein, z. B. [{\"typ\": \"code\", \"inhalt\": \"print(1)\"}].")
    out = []
    for item in raw:
        if isinstance(item, str):
            out.append(("code", item))
            continue
        if not isinstance(item, dict):
            raise NotebookError("Jede Zelle braucht typ und inhalt.")
        kind = str(item.get("typ") or item.get("type") or item.get("cell_type") or "code").strip().lower()
        content = item.get("inhalt", item.get("content", item.get("source")))
        if kind not in ("code", "markdown"):
            raise NotebookError(f"Zellentyp '{kind}' gibt es nicht – nur code oder markdown.")
        if content is None:
            raise NotebookError("Eine Zelle hat keinen inhalt.")
        out.append((kind, text(content)))
    return out


# ------------------------------------------------------------------ Ändern

ACTIONS = {"ersetzen": "ersetzen", "aendern": "ersetzen", "ändern": "ersetzen", "einfuegen": "einfuegen",
           "einfügen": "einfuegen", "hinzufuegen": "einfuegen", "hinzufügen": "einfuegen", "loeschen": "loeschen",
           "löschen": "loeschen", "entfernen": "loeschen"}


def change(nb: dict, action: str, nr, content=None, kind: str = "") -> tuple[str, str, str]:
    """Zelle ersetzen, einfügen (nach Zelle nr, 0 = ganz oben) oder löschen – im Notebook im Speicher.
    Ergebnis: (Meldung fürs Modell, alter Inhalt, neuer Inhalt) – die beiden für die Rückfrage."""
    cells = nb["cells"]
    count = len(cells)
    act = ACTIONS.get(str(action or "").strip().lower())
    if not act:
        raise NotebookError(f"aktion '{action}' gibt es nicht – nur ersetzen, einfuegen oder loeschen.")
    try:
        nr = int(nr)
    except (TypeError, ValueError):
        raise NotebookError("nr muss eine Zellennummer sein (aus notebook_lesen).") from None
    kind = str(kind or "").strip().lower()
    if kind and kind not in ("code", "markdown"):
        raise NotebookError(f"Zellentyp '{kind}' gibt es nicht – nur code oder markdown.")
    if act != "loeschen" and content is None:
        raise NotebookError("inhalt fehlt.")
    lowest = 0 if act == "einfuegen" else 1
    if not lowest <= nr <= count:
        where = "0 (ganz oben) bis" if act == "einfuegen" else "1 bis"
        raise NotebookError(f"Zelle {nr} gibt es nicht – möglich ist {where} {count}.")
    if act == "einfuegen":
        cell = new_cell(nb, kind or "code", text(content))
        cells.insert(nr, cell)
        return (f"Neue {KINDS[cell['cell_type']]}-Zelle {nr + 1} eingefügt; das Notebook hat jetzt {count + 1} Zellen "
                f"(die folgenden rücken eine Nummer weiter).", "", text(content))
    cell = cells[nr - 1]
    old = text(cell.get("source"))
    if act == "loeschen":
        del cells[nr - 1]
        return (f"Zelle {nr} gelöscht; das Notebook hat jetzt {count - 1} Zellen (die folgenden rücken eine Nummer "
                f"vor).", old, "")
    target = kind or cell["cell_type"]
    if target != cell["cell_type"]:
        for key in ("outputs", "execution_count", "attachments"):
            cell.pop(key, None)
        cell["cell_type"] = target
    cell["source"] = lines(content)
    note = ""
    if target == "code":
        if cell.get("outputs"):
            note = " Die alten Ausgaben sind entfernt – mit notebook_ausfuehren neu erzeugen."
        cell["outputs"], cell["execution_count"] = [], None
    return f"Zelle {nr} ersetzt ({KINDS[target]}, {len(cell['source'])} Zeilen).{note}", old, text(content)


# ------------------------------------------------------------------ Darstellen fürs Modell

def select(spec, count: int) -> list[int]:
    """'3', '2-5', '7-', '-4', '1,3,8-9' → Zellennummern ab 1 (leer: alle)."""
    spec = str(spec if spec is not None else "").replace(" ", "")
    if not spec:
        return list(range(1, count + 1))
    out = []
    for part in spec.split(","):
        m = re.fullmatch(r"(\d*)(-?)(\d*)", part)
        if not m or not (m[1] or m[3]):
            raise NotebookError(f"Zellenangabe '{part}' nicht verstanden – z. B. '3', '2-5' oder '7-'.")
        a = int(m[1]) if m[1] else 1
        b = (int(m[3]) if m[3] else count) if m[2] else a
        if not 1 <= a <= count:
            raise NotebookError(f"Zelle {a} gibt es nicht – das Notebook hat {count} Zellen.")
        out += [i for i in range(a, min(b, count) + 1) if i not in out]
    return out


def clip(value: str, limit: int = OUTPUT_CHARS) -> str:
    """Ausgabe lesbar und kurz: Farbcodes weg, Fortschrittsbalken (\\r) nur mit ihrem letzten Stand, von langen
    Ausgaben Anfang und Ende."""
    s = ANSI.sub("", value).replace("\r\n", "\n")
    rows = [row.rsplit("\r", 1)[-1] for row in s.rstrip("\n").split("\n")]
    head, tail = OUTPUT_LINES
    if len(rows) > head + tail + 1:
        rows = rows[:head] + [f"… ({len(rows) - head - tail} Zeilen ausgelassen) …"] + rows[-tail:]
    s = "\n".join(rows)
    if len(s) > limit:
        s = s[:limit * 2 // 3] + f"\n… ({len(s) - limit} Zeichen ausgelassen) …\n" + s[-(limit // 3):]
    return s


def _html_text(value: str) -> str:
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", value)
    s = TAG.sub(" ", re.sub(r"(?i)<br\s*/?>|</(tr|p|div|li|h\d)>", "\n", s))
    return "\n".join(" ".join(row.split()) for row in html.unescape(s).splitlines() if row.strip())


def image_info(raw: bytes, kind: str) -> str:
    if raw[:8] == b"\x89PNG\r\n\x1a\n" and raw[12:16] == b"IHDR":
        w, h = struct.unpack(">II", raw[16:24])
        return f"{kind} {w}×{h}"
    if raw[:2] == b"\xff\xd8":  # JPEG: Größe aus dem ersten SOF-Block
        i = 2
        while i + 9 < len(raw) and raw[i] == 0xFF:
            marker, size = raw[i + 1], int.from_bytes(raw[i + 2:i + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                h, w = struct.unpack(">HH", raw[i + 5:i + 9])
                return f"{kind} {w}×{h}"
            i += 2 + size
    return kind


def store_figure(raw: bytes, suffix: str) -> Path:
    """Unter ihrem Inhalt abgelegt: dieselbe Abbildung bleibt dieselbe Datei, eine neue überschreibt nie eine schon
    gezeigte (der Chat kopiert die gezeigten erst am Ende der Antwort)."""
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURE_DIR / f"{hashlib.sha1(raw).hexdigest()[:20]}{suffix}"
    if not path.exists():
        path.write_bytes(raw)
    return path


def _picture(bundle: dict, label: str, no: int, figures: list) -> str | None:
    """Bild aus einem Ausgabe- bzw. Anhang-Bündel {MIME-Typ: base64} ablegen → Zeile für den Text (oder None)."""
    for mime, (kind, suffix) in IMAGE_TYPES.items():
        if mime in bundle:
            try:
                raw = base64.b64decode(text(bundle[mime]))
            except (binascii.Error, ValueError):
                return f"[{label}: {kind} – beschädigt]"
            fig = Figure(label, no, store_figure(raw, suffix), image_info(raw, kind))
            figures.append(fig)
            return f"[{label}: {fig.info}]"
    if "image/svg+xml" in bundle:
        return f"[{label}: SVG – als Bild nicht verfügbar (z. B. mit %config InlineBackend.figure_format = 'png')]"
    return None


def outputs(cell: dict, no: int, figures: list) -> list[str]:
    """Ausgaben einer Code-Zelle als Textzeilen; Abbildungen landen in figures."""
    out, k = [], 0
    for o in cell.get("outputs") or []:
        kind = o.get("output_type")
        if kind == "stream":
            label = "Ausgabe (stderr)" if o.get("name") == "stderr" else "Ausgabe"
            out.append(f"{label}:\n{clip(text(o.get('text')))}")
        elif kind in ("display_data", "execute_result"):
            data = o.get("data") or {}
            if any(m in data for m in (*IMAGE_TYPES, "image/svg+xml")):
                k += 1
                out.append(_picture(data, f"Abbildung {no}.{k}", no, figures))
                continue  # text/plain daneben ist nur „<Figure size 640x480 with 1 Axes>“
            label = f"Ergebnis [{o.get('execution_count')}]" if kind == "execute_result" else "Anzeige"
            shown = ""
            if "text/plain" in data:
                shown = clip(text(data["text/plain"]))
            elif "text/markdown" in data:
                shown = clip(text(data["text/markdown"]))
            elif "text/html" in data:
                shown = clip(_html_text(text(data["text/html"])))
            if shown.strip():
                out.append(f"{label}:\n{shown}")
            # plotly, Widgets & Co.: zeichnet erst der Browser – kein Bild in der Datei
            live = sorted(m for m in data if m.startswith("application/vnd.") or m == "application/javascript")
            if live or (data and not shown.strip()):
                out.append(f"[{label}: interaktive Ausgabe ({', '.join(live or sorted(data))}) – als Bild nicht "
                           "verfügbar; ein statisches Diagramm (z. B. matplotlib) könntest du sehen]")
        elif kind == "error":
            trace = ANSI.sub("", "\n".join(map(str, o.get("traceback") or []))).splitlines()
            if len(trace) > TRACE_LINES:
                trace = [f"… ({len(trace) - TRACE_LINES} Zeilen ausgelassen) …"] + trace[-TRACE_LINES:]
            out.append(f"Fehler {o.get('ename', '')}: {ANSI.sub('', str(o.get('evalue', '')))}\n"
                       + clip("\n".join(trace), 3000))
    return out


def cell_block(cell: dict, no: int, figures: list, source: bool = True) -> str:
    kind = cell["cell_type"]
    head = f"── Zelle {no} · {KINDS[kind]}"
    if kind == "code":
        count = cell.get("execution_count")
        head += f" [{count if count is not None else ' '}]"
    parts = [head + " ──"]
    src = text(cell.get("source"))
    if source:
        parts.append(src.rstrip("\n") if src.strip() else "(leer)")
    else:  # nach dem Ausführen: nur die erste Zeile zur Orientierung
        first = next((row for row in src.splitlines() if row.strip()), "(leer)")
        parts.append(first + (" …" if src.strip().count("\n") else ""))
    if kind == "code":
        parts += ["│ " + row for item in outputs(cell, no, figures) for row in item.split("\n")]
    for k, (name, bundle) in enumerate(sorted((cell.get("attachments") or {}).items()), 1):
        line = _picture(bundle if isinstance(bundle, dict) else {}, f"Bild {no}.{k} ({name})", no, figures)
        if line:
            parts.append(line)
    return "\n".join(parts)


def kernel_name(nb: dict) -> str:
    spec = nb.get("metadata", {}).get("kernelspec") or {}
    name, shown = spec.get("name") or "", spec.get("display_name") or ""
    return f"{shown} ({name})" if shown and name and shown != name else shown or name or "nicht angegeben"


def _join(blocks: list[tuple[int, str]], limit: int, more: str) -> tuple[str, set[int]]:
    """Blöcke bis zur Grenze; was nicht mehr passt, nennt der Hinweis (more mit {nr} = erste fehlende Zelle).
    Ergebnis: (Text, Nummern der gezeigten Zellen)."""
    out, shown, size = [], set(), 0
    for no, block in blocks:
        if size + len(block) > limit and out:
            out.append(more.format(nr=no))
            break
        if len(block) > limit:
            block = block[:limit] + f"\n… (Zelle {no} gekürzt – einzeln lesen mit zellen='{no}')"
        out.append(block)
        shown.add(no)
        size += len(block) + 2
    return "\n\n".join(out), shown


def render(nb: dict, name: str, cells="", limit: int = READ_CHARS) -> tuple[str, list[Figure]]:
    """Zellen mit Nummer, Typ, Inhalt und Ausgaben (gekürzt) – dazu die Abbildungen der gezeigten Zellen."""
    all_cells = nb["cells"]
    chosen = select(cells, len(all_cells))
    count = {k: sum(1 for c in all_cells if c["cell_type"] == k) for k in KINDS}
    kinds = ", ".join(f"{n} {KINDS[k]}" for k, n in count.items() if n)
    head = f"Notebook {name}: {len(all_cells)} Zellen ({kinds or 'keine'}), Kernel: {kernel_name(nb)}"
    if len(chosen) < len(all_cells):
        head += f" – gezeigt: Zellen {_ranges(chosen)}"
    figures: list[Figure] = []
    blocks = [(no, cell_block(all_cells[no - 1], no, figures)) for no in chosen]
    body, shown = _join(blocks, limit, "… weitere Zellen passen nicht mehr in eine Antwort – weiter mit zellen='{nr}-'.")
    return f"{head}\n\n{body}" if body else head, [f for f in figures if f.cell in shown]


def render_run(nb: dict, name: str, status: dict, seconds: float, saved: bool,
               limit: int = READ_CHARS) -> tuple[str, list[Figure]]:
    """Ergebnis von notebook_ausfuehren: was lief, Ausgaben der ausgeführten Code-Zellen (nur erste Codezeile,
    die Zelle mit dem Fehler ganz) und deren Abbildungen."""
    cells = nb["cells"]
    executed = min(int(status.get("executed") or 0), len(cells))
    bad = status.get("error_cell")
    lines_out = []
    if status.get("ok"):
        lines_out.append(f"Notebook {name} ausgeführt: Zellen 1–{executed} von {len(cells)} in {seconds:.1f} s "
                         f"(Kernel {status.get('kernel') or '?'}).")
    elif bad:
        lines_out.append(f"Notebook {name}: Abbruch in Zelle {bad} von {len(cells)} nach {seconds:.1f} s – "
                         f"{status.get('error') or 'Fehler, siehe unten'}. Spätere Zellen sind nicht gelaufen.")
    else:
        lines_out.append(f"Notebook {name} nicht ausgeführt: {status.get('error') or 'unbekannter Fehler'}")
    if status.get("note"):
        lines_out.append(f"Hinweis: {status['note']}")
    lines_out.append("Die Ausgaben sind im Notebook gespeichert." if saved else
                     "Das Notebook wurde während der Ausführung geändert (in Jupyter gespeichert?) – das Ergebnis ist "
                     "deshalb NICHT gespeichert. Die Ausgaben unten stammen aus dem Lauf.")
    figures: list[Figure] = []
    blocks, quiet = [], 0
    for no in range(1, executed + 1):
        cell = cells[no - 1]
        if cell["cell_type"] != "code":
            continue
        if not cell.get("outputs") and no != bad:
            quiet += 1
            continue
        blocks.append((no, cell_block(cell, no, figures, source=no == bad)))
    if quiet:
        lines_out.append(f"{quiet} Code-Zellen ohne Ausgabe.")
    body, shown = _join(blocks, limit, "… weitere Ausgaben passen nicht mehr in eine Antwort – mit notebook_lesen und "
                                       "zellen='{nr}-' ansehen.")
    return "\n".join(lines_out) + ("\n\n" + body if body else ""), [f for f in figures if f.cell in shown]


def _ranges(numbers: list[int]) -> str:
    out, start, prev = [], None, None
    for n in numbers + [None]:
        if start is not None and n == prev + 1:
            prev = n
            continue
        if start is not None:
            out.append(str(start) if start == prev else f"{start}–{prev}")
        start = prev = n
    return ", ".join(out)


def pick_figures(figures: list[Figure], vision: bool, newest: bool = False) -> tuple[list[Path], str]:
    """Welche Abbildungen das Modell als Bild bekommt (höchstens MAX_FIGURES – beim Ausführen die neuesten) und der
    Hinweis dazu für das Werkzeug-Ergebnis."""
    if not figures:
        return [], ""
    if not vision:
        return [], NO_VISION
    chosen = figures[-MAX_FIGURES:] if newest else figures[:MAX_FIGURES]
    paths, labels = [], []
    for fig in chosen:
        try:
            images.check(fig.path)
        except ValueError:
            continue
        paths.append(fig.path)
        labels.append(fig.label)
    note = f"Als Bild angehängt: {', '.join(labels)}." if labels else ""
    rest = [f for f in figures if f not in chosen]
    if rest:
        cells = sorted({f.cell for f in rest})
        note += (f" Nicht angehängt (höchstens {MAX_FIGURES} je Aufruf): {', '.join(f.label for f in rest)} – mit "
                 f"notebook_lesen und zellen='{cells[0]}' ansehen.")
    return paths, note.strip()


# ------------------------------------------------------------------ Ausführen (Jupyter des Nutzers)

_ready: set[tuple] = set()  # Pythons, in denen Jupyter schon gefunden wurde


def _venv_python(folder: Path) -> Path:
    return folder / "Scripts" / "python.exe" if plattform.WINDOWS else folder / "bin" / "python"


def _shebang(script: str) -> list[str]:
    try:
        with open(script, "rb") as f:
            first = f.readline(300).decode("utf-8", "replace").strip()
    except OSError:
        return []
    if not first.startswith("#!"):
        return []
    parts = first[2:].split()
    if parts and Path(parts[0]).name == "env" and len(parts) > 1:
        found = shutil.which(parts[1])
        return [found] if found else []
    return parts[:1]


def candidates(near: list[Path]) -> list[list[str]]:
    """Pythons, die Jupyter haben könnten – das nächstliegende zuerst: virtuelle Umgebung beim Notebook bzw.
    darüber, Anaconda/Miniconda, das Python hinter `jupyter`, der Python-Launcher, Monhips eigenes, python3/python."""
    out: list[list[str]] = []
    for folder in near:
        for name in (".venv", "venv", "env"):
            p = _venv_python(folder / name)
            if p.is_file():
                out.append([str(p)])
    home = Path.home()
    for name in ("anaconda3", "miniconda3", "miniforge3", "mambaforge"):
        p = home / name / "python.exe" if plattform.WINDOWS else home / name / "bin" / "python"
        if p.is_file():
            out.append([str(p)])
    jupyter = shutil.which("jupyter")
    if jupyter:
        if plattform.WINDOWS:  # …\Scripts\jupyter.exe → …\python.exe
            p = Path(jupyter).parent.parent / "python.exe"
            if p.is_file():
                out.append([str(p)])
        else:
            out.append(_shebang(jupyter))
    if plattform.WINDOWS and shutil.which("py"):
        out.append(["py", "-3"])
    own = Path(sys.executable)
    if own.name.lower() == "pythonw.exe" and own.with_name("python.exe").is_file():
        own = own.with_name("python.exe")
    out.append([str(own)])
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found and "WindowsApps" not in found:  # Platzhalter, der zum Microsoft Store schickt
            out.append([found])
    unique, seen = [], set()
    for argv in out:
        key = tuple(os.path.normcase(a) for a in argv)
        if argv and key not in seen:
            seen.add(key)
            unique.append(argv)
    return unique


def has_jupyter(argv: list[str]) -> bool:
    if tuple(argv) in _ready:
        return True
    try:
        r = subprocess.run(argv + ["-c", NEEDS], capture_output=True, timeout=60, stdin=subprocess.DEVNULL,
                           creationflags=plattform.NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return False
    if r.returncode == 0:
        _ready.add(tuple(argv))
    return r.returncode == 0


def find_python(near: list[Path], explicit: str = "") -> list[str]:
    if explicit:
        exe = os.path.expandvars(os.path.expanduser(str(explicit).strip().strip('"')))
        p = Path(exe)
        if p.is_dir():  # Ordner einer Umgebung
            p = _venv_python(p) if _venv_python(p).is_file() else p / ("python.exe" if plattform.WINDOWS else "bin/python")
        argv = [str(p)] if p.is_file() else [shutil.which(exe) or exe]
        if not has_jupyter(argv):
            raise NotebookError(f"Unter {argv[0]} fehlt Jupyter (nbclient und ipykernel). " + install_hint())
        return argv
    for argv in candidates(near):
        if has_jupyter(argv):
            return argv
    raise NotebookError("Kein Python mit Jupyter gefunden (gesucht: .venv/venv beim Notebook, Anaconda/Miniconda, "
                        "jupyter, " + ("py, " if plattform.WINDOWS else "") + "python3/python). " + install_hint())


def install_hint() -> str:
    if plattform.WINDOWS:
        return ("Installieren in PowerShell: py -m pip install notebook (bringt Jupyter mit allem Nötigen) – oder in "
                "einer virtuellen Umgebung .venv neben dem Notebook. Sag das dem Nutzer.")
    return ("Installieren: sudo apt install python3-nbclient python3-ipykernel (Debian/Ubuntu, für die Oberfläche "
            "dazu jupyter-notebook) – oder pip install notebook in einer virtuellen Umgebung .venv neben dem "
            "Notebook. Sag das dem Nutzer (sudo kannst du nicht selbst ausführen).")


def execute(python: list[str], path: Path, until: int, timeout: int, run) -> tuple[dict, bytes]:
    """Notebook mit dem Jupyter von python ausführen (notebook_runner.py) → (Status, Inhalt der ausgeführten Fassung).
    run(argv, cwd, timeout, env) → CompletedProcess (Agent._run: „Stopp“ beendet Kernel und alles darunter). Die
    Datei selbst bleibt unverändert – übernehmen ist Sache des Aufrufers."""
    work = Path(tempfile.mkdtemp(prefix="monhip-nb-"))
    try:
        target = work / "ergebnis.ipynb"
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        env.pop("MPLBACKEND", None)  # sonst zeichnet matplotlib nicht in die Ausgabe der Zelle
        argv = python + ["-c", BOOT, str(RUNNER), str(path), str(target), str(until), str(timeout)]
        r = run(argv, work, timeout + 90, env)  # Zeitlimit gilt je Zelle; dazu Start und Ende des Kernels
        out = r.stdout.decode("utf-8", "replace") if isinstance(r.stdout, bytes) else str(r.stdout or "")
        err = r.stderr.decode("utf-8", "replace") if isinstance(r.stderr, bytes) else str(r.stderr or "")
        status = None
        for row in reversed(out.strip().splitlines()):
            if row.startswith("{"):
                try:
                    status = json.loads(row)
                except ValueError:
                    pass
                break
        if status is None or not target.is_file():
            tail = "\n".join(ANSI.sub("", err).strip().splitlines()[-15:])
            raise NotebookError(f"Ausführen fehlgeschlagen (Exit-Code {r.returncode}).\n{tail or out.strip()[-1500:]}")
        return status, target.read_bytes()
    finally:
        shutil.rmtree(work, ignore_errors=True)
