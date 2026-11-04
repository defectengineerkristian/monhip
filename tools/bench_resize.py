"""Misst, wie flüssig sich das Monhip-Fenster ziehen lässt: langer Chat (Markdown, Code, Tabellen, Werkzeuge), dann
die Fenstergröße in kleinen Schritten ändern – wie beim Ziehen am Rand mit der Maus – und die Zeit je Schritt messen
(Ereignisse verarbeiten und neu zeichnen). Ohne echte Daten (Temp-Ordner).

    python tools/bench_resize.py              # Linux ohne Bildschirm: xvfb-run -a python3 tools/bench_resize.py
    python tools/bench_resize.py --profile    # dazu die teuersten Funktionen beim Breiterziehen
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

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))


def fill_chat(view, rounds: int):
    """Langer Chat wie beim Öffnen eines gespeicherten (view.batch: erst am Ende einmal ans Ende scrollen)."""
    code = "\n".join(f"    wert_{i} = berechne({i}, faktor=2)  # Zeile {i}" for i in range(18))
    with view.batch():
        for i in range(rounds):
            view.user(f"Frage {i}: Wie geht das mit **Monhip** und langen Antworten? " + "Mehr Kontext. " * 6)
            n = view.tool_begin("Websuche", f"suche {i}", '{"query": "monhip"}', icon="🌐")
            view.tool_end(n, "Ergebnis " * 40, True)
            view.markdown(
                f"## Antwort {i}\n\n" + "Ein längerer Absatz mit *kursiv*, **fett** und `Code`. " * 12 + "\n\n"
                "- Punkt eins mit etwas Text\n- Punkt zwei mit noch mehr Text\n  - eingerückt\n\n"
                f"```python\ndef beispiel_{i}():\n{code}\n```\n\n"
                "| Spalte A | Spalte B | Spalte C |\n|---|---|---|\n" + "| 1 | zwei | drei |\n" * 6)
            view.footer("{}", 23.5)


def measure(root, steps, settle=0.0):
    """ms je Schritt: Größe setzen, alle Ereignisse verarbeiten und neu zeichnen – mit einer Rückfrage an den
    Bildschirm-Server am Ende (winfo_pointerxy), damit auch dessen Zeichenarbeit mitzählt (X11 zeichnet sonst
    nachträglich, unbemerkt von der Messung)."""
    times = []
    for w, h in steps:
        t0 = time.perf_counter()
        root.geometry(f"{w}x{h}")
        root.update()
        root.winfo_pointerxy()
        times.append((time.perf_counter() - t0) * 1000)
        if settle:
            time.sleep(settle)
    return times


def count_widgets(widget) -> int:
    return 1 + sum(count_widgets(c) for c in widget.winfo_children())


def stats(times):
    times = sorted(times)
    return {"median_ms": round(statistics.median(times), 2), "p90_ms": round(times[int(len(times) * 0.9) - 1], 2),
            "max_ms": round(times[-1], 2), "steps": len(times)}


def main():
    profile = "--profile" in sys.argv
    rounds = 40
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
        import chatview
        import checkpoints
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
        # Größen nach dem Bildschirm (GitHub-Windows-Rechner: 1024 × 768 – größer wird das Fenster dort nicht)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.minsize(500, 400)
        hi_w, base_h = min(1700, sw - 40), min(800, sh - 120)
        start_w = min(1100, hi_w - 100)
        root.geometry(f"{start_w}x{base_h}+0+0")
        for _ in range(20):
            root.update()
            time.sleep(0.02)
        t0 = time.perf_counter()
        fill_chat(app.view, rounds)
        root.update()
        fill_ms = (time.perf_counter() - t0) * 1000
        app.view.scroll_end()
        root.update()

        widen = [(w, base_h) for w in range(start_w, hi_w, 8)]
        # schmaler als die Chat-Spalte (um 900 px Fensterbreite): hier bricht Tk den Text um
        narrow = [(w, base_h) for w in range(min(1000, sw - 40), 700, -6)]
        taller = [(start_w, h) for h in range(base_h - 200, min(base_h + 200, sh - 60), 5)]
        result = {"system": sys.platform, "tk": root.tk.call("info", "patchlevel"), "screen": f"{sw}x{sh}",
                  "chat_rounds": rounds, "fill_ms": round(fill_ms)}
        prof = cProfile.Profile() if profile else None
        if prof:
            prof.enable()
        result["widen"] = stats(measure(root, widen))
        if prof:
            prof.disable()
        root.geometry(f"{narrow[0][0]}x{base_h}")
        root.update()
        result["narrow"] = stats(measure(root, narrow))
        root.geometry(f"{start_w}x{base_h - 200}")
        root.update()
        result["taller"] = stats(measure(root, taller))
        root.geometry(f"{start_w}x{base_h}")
        root.update()
        app.set_mode("room")
        root.update()
        result["room_narrow"] = stats(measure(root, narrow))
        app.set_mode("chat")
        root.update()
        result["widgets"] = count_widgets(root)
        # Varianten (nur zum Vergleichen): Spalte linksbündig – kostet das Verschieben der Spalte etwas?
        view = app.view
        centered = view._place_column

        def left(e=None):
            frame = view.t.master
            sb = view._sb.winfo_reqwidth() if view._sb else 0
            avail = max(1, (e.width if e else frame.winfo_width()) - sb)
            width = min(avail, view._s(chatview.MAX_COLUMN) + 2 * view._padx)
            view.t.place(x=0, y=0, width=width, height=e.height if e else frame.winfo_height())

        view._place_column = left
        view.t.master.bind("<Configure>", left)
        root.geometry(f"{start_w}x{base_h}")
        root.update()
        result["variant_left_column"] = stats(measure(root, widen))
        view._place_column = centered
        view.t.master.bind("<Configure>", centered)
        view.clear()
        root.geometry(f"{narrow[0][0]}x{base_h}")
        root.update()
        result["variant_empty_chat_narrow"] = stats(measure(root, narrow))
        print(json.dumps(result, ensure_ascii=False))
        if prof:
            out = io.StringIO()
            pstats.Stats(prof, stream=out).sort_stats("cumulative").print_stats(30)
            print(out.getvalue())
        app.on_close()


if __name__ == "__main__":
    main()
