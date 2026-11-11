"""Misst, wie flüssig sich Monhip bedienen lässt: wie lange typische Aktionen die Oberfläche blockieren (Moduswechsel
Chat ↔ Teamwork ↔ Bilder, Seitenleiste „Quellen“, Bild in der Galerie wählen) und die längste Pause zwischen zwei
Bildern einer Animation danach (Ruckler). Mit langem Chat und voller Galerie, ohne echte Daten (Temp-Ordner).

    python progress/tools/bench_ui.py                 # Linux ohne Bildschirm: xvfb-run -a python3 progress/tools/bench_ui.py
    python progress/tools/bench_ui.py --profile       # dazu die teuersten Funktionen
"""

import cProfile
import io
import json
import pstats
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parents[2] / "app"
sys.path.insert(0, str(APP))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bench_resize import fill_chat  # noqa: E402

PROMPT = ("A cinematic photo of an old lighthouse on a rocky coast at golden hour, dramatic clouds, volumetric light, "
          "waves crashing against the rocks, seagulls in the sky, warm color palette, shot on 35mm film, ") * 6


def png(width: int, height: int, seed: int) -> bytes:
    """Ein einfaches PNG (Farbverlauf) ohne Pillow."""
    import struct
    import zlib
    rows = b"".join(b"\0" + bytes(v for x in range(width)
                                  for v in ((x * 7 + seed) % 256, (y * 5 + seed) % 256, (x + y + seed) % 256))
                    for y in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 1)) + chunk(b"IEND", b""))


def blocked(root, action) -> float:
    """ms, die action samt anschließendem Zeichnen die Oberfläche blockiert."""
    t0 = time.perf_counter()
    action()
    root.update_idletasks()
    root.winfo_pointerxy()
    return (time.perf_counter() - t0) * 1000


def frames(root, action, duration: float = 0.45) -> dict:
    """action auslösen, dann duration lang die Ereignisschleife laufen lassen und messen: Zeit bis zum ersten Bild
    nach dem Klick, längste Pause zwischen zwei Durchläufen (Ruckler)."""
    stamps = []
    t0 = time.perf_counter()
    action()
    while time.perf_counter() - t0 < duration:
        root.update()
        root.winfo_pointerxy()
        stamps.append(time.perf_counter())
        time.sleep(0.004)
    gaps = [(b - a) * 1000 for a, b in zip([t0] + stamps, stamps)]
    return {"first_ms": round(gaps[0], 1), "max_gap_ms": round(max(gaps), 1),
            "median_gap_ms": round(statistics.median(gaps), 1)}


def main():
    profile = "--profile" in sys.argv
    gallery_size = 150
    import i18n
    with tempfile.TemporaryDirectory() as directory:
        data = Path(directory)
        config_file = data / "config.json"
        config_file.write_text(json.dumps({"ui_language": "de", "room_name": "Bench", "room_ai": "Helfer"}),
                               encoding="utf-8")
        initialize = i18n.initialize
        with mock.patch.object(i18n, "initialize", side_effect=lambda _path: initialize(config_file)):
            import monhip
        import chats
        import checkpoints
        import galerie
        import images
        import memory
        import reminders
        import roomui
        import tkinter as tk
        monhip.APP_DIR = data
        monhip.CONFIG_FILE = config_file
        monhip.MODEL_DIR = data / "modelle"
        chats.CHAT_DIR = data / "chats"
        chats.IMAGE_DIR = chats.CHAT_DIR / "bilder"
        checkpoints.DIR = data / "checkpoints"
        memory.FILE = data / "gedaechtnis.json"
        reminders.FILE = data / "erinnerungen.json"
        images.TEMP_DIR = data / "temp"
        roomui.CACHE_DIR = data / "cache"

        root = tk.Tk()
        app = monhip.App(root)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{min(1280, sw - 40)}x{min(800, sh - 120)}+0+0")
        for _ in range(20):
            root.update()
            time.sleep(0.02)
        fill_chat(app.view, 40)
        root.update()
        # Galerie: viele Bilder mit ausführlicher Beschreibung (wie nach „Beschreibung verbessern“)
        gal = data / "bilder"
        gal.mkdir()
        big = png(1024, 1024, 1)
        items = []
        for i in range(gallery_size):
            name = f"2026-11-08 12-{i // 60:02d}-{i % 60:02d}.png"
            (gal / name).write_bytes(big)
            items.append({"file": name, "created": f"2026-11-08T12:{i // 60:02d}:{i % 60:02d}", "prompt": PROMPT,
                          "width": 1024, "height": 1024, "seed": i, "seconds": 5})
        (gal / "bilder.json").write_text(json.dumps(items[::-1]), encoding="utf-8")
        app.images.gallery = galerie.Gallery(gal)
        # Vorschaubilder einmal anlegen lassen (geschieht sonst beim ersten Öffnen im Hintergrund)
        app.set_mode("images")
        deadline = time.time() + 20  # unter Windows (PowerShell je Vorschau) nicht ewig warten
        while time.time() < deadline and len(list((gal / ".vorschau").glob("*.png"))) < gallery_size:
            root.update()
            time.sleep(0.01)
        app.set_mode("chat")
        root.update()

        result = {"system": sys.platform, "tk": root.tk.call("info", "patchlevel"), "gallery": gallery_size}
        prof = cProfile.Profile() if profile else None
        if prof:
            prof.enable()
        for run in ("mode_switch_first", "mode_switch"):  # der erste Durchlauf füllt Zwischenspeicher
            switches = {}
            for a, b in (("chat", "images"), ("images", "room"), ("room", "chat"), ("chat", "room"),
                         ("room", "images"), ("images", "chat")):
                root.update()
                time.sleep(0.05)
                switches[f"{a}→{b}"] = frames(root, lambda b=b: app.set_mode(b))
            result[run] = {k: f"{v['first_ms']} / {v['max_gap_ms']} ms" for k, v in switches.items()}
        root.update()
        app.set_mode("chat")
        root.update()
        for key in ("sources_open", "sources_close"):
            v = frames(root, app.sources.toggle)
            result[key] = f"{v['first_ms']} / {v['max_gap_ms']} ms"
        app.set_mode("images")
        root.update()
        shown = []
        for item in app.images.gallery.snapshot()[:10]:
            shown.append(blocked(root, lambda item=item: (app.images.tree.selection_set(item["file"]),
                                                          app.images._on_select())))
            root.update()
        result["gallery_select_ms"] = {"median": round(statistics.median(shown), 1), "max": round(max(shown), 1)}
        again = []  # Hin- und Herblättern zwischen den letzten Bildern
        for item in app.images.gallery.snapshot()[8:10] * 4:
            again.append(blocked(root, lambda item=item: (app.images.tree.selection_set(item["file"]),
                                                          app.images._on_select())))
            root.update()
        result["gallery_reselect_ms"] = {"median": round(statistics.median(again), 1), "max": round(max(again), 1)}
        result["gallery_refresh_ms"] = round(blocked(root, app.images.refresh_list), 1)
        if prof:
            prof.disable()
        print(json.dumps(result, ensure_ascii=False, indent=1))
        if prof:
            out = io.StringIO()
            pstats.Stats(prof, stream=out).sort_stats("cumulative").print_stats(35)
            print(out.getvalue())
        app.on_close()


if __name__ == "__main__":
    main()
