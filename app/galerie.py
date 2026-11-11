"""Galerie der erzeugten Bilder: PNG-Dateien in bilder/, dazu bilder/bilder.json mit Beschreibung, Größe, Modell,
Seed und Dauer je Bild (neueste zuerst) und kleine Vorschaubilder in bilder/.vorschau/.

Die PNG-Dateien sind das Maßgebliche: Fehlt eine, verschwindet ihr Eintrag; liegt eine ohne Eintrag im Ordner (von
Hand hineinkopiert, bilder.json gelöscht), kommt sie dazu – mit der Beschreibung aus ihren eingebetteten
Erzeugungsdaten, soweit vorhanden (stable-diffusion.cpp schreibt sie wie die A1111-WebUI in den Text „parameters“).

3D-Modelle (Bereich „Bilder“ → „3D-Modell“) stehen mit ihrem Vorlagebild in der Galerie; die GLB-Datei liegt daneben
unter demselben Namen und steht im Eintrag als „model3d“."""

import json
import re
import shutil
import struct
import threading
import zlib
from datetime import datetime, timedelta
from pathlib import Path

import plattform

DIR = plattform.DATA_DIR / "bilder"
META_MAX = 1024 * 1024  # so viel wird vor den Bilddaten höchstens gelesen (und insgesamt entpackt)
CHUNKS_MAX = 256        # … in höchstens so vielen Blöcken


def _inflate(data: bytes, limit: int) -> bytes:
    """zlib entpacken, aber höchstens limit Bytes: Ein 64 KB großer Block ergäbe sonst bis zu 64 MB, und eine
    präparierte PNG mit vielen davon brächte Monhip schon beim Start (load liest neue Bilder) zum Absturz."""
    if limit <= 0:  # max_length 0 hieße bei zlib „ohne Grenze“
        return b""
    return zlib.decompressobj().decompress(data, limit)


def png_text(path: Path, limit: int = 64 * 1024) -> dict[str, str]:
    """Textfelder (tEXt, zTXt, iTXt) einer PNG-Datei – nur die Blöcke vor den Bilddaten werden gelesen, höchstens
    META_MAX Bytes in CHUNKS_MAX Blöcken, jedes Feld höchstens limit Bytes (auch entpackt)."""
    out: dict[str, str] = {}
    budget = META_MAX
    try:
        with open(path, "rb") as f:
            if f.read(8) != b"\x89PNG\r\n\x1a\n":
                return out
            for _ in range(CHUNKS_MAX):
                head = f.read(8)
                if len(head) < 8:
                    break
                size, kind = struct.unpack(">I4s", head)
                if kind in (b"IDAT", b"IEND") or size > limit or size > budget:
                    break
                budget -= size
                data = f.read(size)
                f.read(4)  # Prüfsumme
                try:
                    if kind == b"tEXt":
                        key, _, value = data.partition(b"\0")
                        out[key.decode("latin-1")] = value.decode("latin-1")
                    elif kind == b"zTXt":
                        key, _, rest = data.partition(b"\0")
                        value = _inflate(rest[1:], min(limit, budget))
                        budget -= len(value)
                        out[key.decode("latin-1")] = value.decode("latin-1")
                    elif kind == b"iTXt":
                        key, _, rest = data.partition(b"\0")
                        compressed, rest = rest[0], rest[2:]
                        _lang, _, rest = rest.partition(b"\0")
                        _tkey, _, value = rest.partition(b"\0")
                        value = _inflate(value, min(limit, budget)) if compressed else value
                        budget -= len(value) if compressed else 0
                        out[key.decode("latin-1")] = value.decode("utf-8", "replace")
                except (ValueError, zlib.error, IndexError):
                    continue
    except OSError:
        pass
    return out


def parse_parameters(text: str) -> dict:
    """A1111-Erzeugungsdaten („Beschreibung\\nNegative prompt: …\\nSteps: 4, …, Seed: 42, Size: 1024x1024“)."""
    lines = (text or "").strip().split("\n")
    prompt, rest = [], []
    for i, line in enumerate(lines):
        if line.startswith(("Negative prompt:", "Steps:")):
            rest = lines[i:]
            break
        prompt.append(line)
    info: dict = {"prompt": "\n".join(prompt).strip()}
    tail = " ".join(rest)
    m = re.search(r"\bSeed: (-?\d+)", tail)
    if m:
        info["seed"] = int(m.group(1))
    m = re.search(r"\bSize: (\d+)x(\d+)", tail)
    if m:
        info["width"], info["height"] = int(m.group(1)), int(m.group(2))
    return info


def _png_size(path: Path) -> tuple[int, int] | None:
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
            return struct.unpack(">II", head[16:24])
    except OSError:
        pass
    return None


class Gallery:
    """Die Bilder in folder; items = Einträge (dict) neueste zuerst. Lesen und Schreiben sind gesperrt – fertige Bilder
    kommen aus einem Hintergrund-Thread dazu, Löschen geschieht in der Oberfläche."""

    def __init__(self, folder: Path | None = None):
        self.dir = Path(folder or DIR)
        self.index = self.dir / "bilder.json"
        self.thumbs = self.dir / ".vorschau"
        self.items: list[dict] = []
        self._lock = threading.RLock()
        self.load()

    # ------------------------------------------------------------ Lesen / Schreiben

    def load(self):
        with self._lock:
            try:
                saved = json.loads(self.index.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                saved = []
            items, known = [], set()
            for e in saved if isinstance(saved, list) else []:
                name = e.get("file") if isinstance(e, dict) else None
                # nur ein Dateiname in diesem Ordner (Löschen wirft ihn in den Papierkorb – nie etwas daneben)
                if (isinstance(name, str) and name == Path(name).name and name.lower().endswith(".png")
                        and name.lower() not in known and (self.dir / name).is_file()):
                    items.append(e)
                    known.add(name.lower())
            added = False
            for p in sorted(self.dir.glob("*.png")) if self.dir.is_dir() else []:
                if p.name.lower() in known:
                    continue
                info = parse_parameters(png_text(p).get("parameters", ""))
                size = _png_size(p)
                if size and "width" not in info:
                    info["width"], info["height"] = size
                created = datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds")
                items.append({"file": p.name, "created": created, **info})
                added = True
            items.sort(key=lambda e: str(e.get("created", "")), reverse=True)
            self.items = items
            if added:
                self.save()

    def save(self):
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            tmp = self.index.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.items, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.index)

    # ------------------------------------------------------------ Bilder

    def path(self, item: dict) -> Path:
        return self.dir / item["file"]

    def thumb(self, item: dict) -> Path:
        return self.thumbs / item["file"]

    def _free_name(self, when: datetime) -> str:
        base = when.strftime("%Y-%m-%d %H-%M-%S")
        name, n = f"{base}.png", 2
        while (self.dir / name).exists():
            name, n = f"{base} ({n}).png", n + 1
        return name

    def add(self, png: bytes, info: dict) -> dict:
        """Neues Bild speichern und vorn einreihen; info: prompt, width, height, seed, model, seconds …"""
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            now = datetime.now()
            name = self._free_name(now)
            (self.dir / name).write_bytes(png)
            item = {"file": name, "created": now.isoformat(timespec="seconds"), **info}
            self.items.insert(0, item)
            self.save()
            return item

    def add_model(self, png: bytes, glb: Path, info: dict) -> dict:
        """Neues 3D-Modell: sein Vorlagebild als Eintrag (wie ein Bild), die GLB-Datei daneben unter demselben Namen
        (…/2026-11-10 12-00-00.glb) – im Eintrag als „model3d“. glb wird dorthin verschoben."""
        with self._lock:
            self.dir.mkdir(parents=True, exist_ok=True)
            now = datetime.now()
            name = self._free_name(now)
            while (self.dir / Path(name).with_suffix(".glb").name).exists():  # Rest eines gelöschten Eintrags
                now = now.replace(microsecond=0) + timedelta(seconds=1)
                name = self._free_name(now)
            model = Path(name).with_suffix(".glb").name
            shutil.move(str(glb), str(self.dir / model))
            (self.dir / name).write_bytes(png)
            item = {"file": name, "created": now.isoformat(timespec="seconds"), **info, "model3d": model}
            self.items.insert(0, item)
            self.save()
            return item

    def model_path(self, item: dict) -> Path | None:
        """GLB-Datei eines 3D-Modells (None bei einem Bild oder wenn sie fehlt)."""
        name = item.get("model3d")
        if not isinstance(name, str) or name != Path(name).name or not name.lower().endswith(".glb"):
            return None  # nur ein Dateiname in diesem Ordner
        path = self.dir / name
        return path if path.is_file() else None

    def snapshot(self) -> list[dict]:
        """Die Einträge als eigene Liste – zum Durchgehen in der Oberfläche, während ein Thread Bilder hinzufügt."""
        with self._lock:
            return list(self.items)

    def find(self, name: str) -> dict | None:
        with self._lock:
            return next((e for e in self.items if e["file"] == name), None)

    def remove(self, item: dict):
        """Bild (bei einem 3D-Modell auch die GLB-Datei) in den Papierkorb (dort wiederherstellbar), Vorschau löschen, Eintrag entfernen."""
        with self._lock:
            model = self.model_path(item)
            if model:
                plattform.recycle(model)
            p = self.path(item)
            if p.exists():
                plattform.recycle(p)
            self.thumb(item).unlink(missing_ok=True)
            self.items = [e for e in self.items if e["file"] != item["file"]]
            self.save()
