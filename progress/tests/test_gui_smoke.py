"""Rauchtest der Oberfläche unter Windows und Linux, in einem eigenen Prozess ohne echte Daten: alle Seiten der
Einstellungen, alle Designs, ein Chat mit Markdown, Code und Werkzeug-Blöcken, ein Teamwork-Raum als Gastgeber (echter
Server auf 127.0.0.1) – jede Tk-Fehlermeldung zählt als Fehler. Prüft auch, dass die Knöpfe Symbole haben, wo es eine
Icon-Schrift gibt (Windows: Segoe, Linux: app/fonts/MonhipIcons.ttf mit Pillow): python -m unittest discover -s progress/tests -p test_gui_smoke.py
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

APP = Path(__file__).resolve().parents[2] / "app"


def images_in(widget) -> int:
    """So viele ttk-Knöpfe/-Beschriftungen unter widget zeigen ein Bild (Symbol)."""
    count = 0
    for child in widget.winfo_children():
        try:
            count += bool(str(child.cget("image")))
        except Exception:  # Widget ohne image-Option
            pass
        count += images_in(child)
    return count


def gui_worker():
    sys.path.insert(0, str(APP))
    import i18n
    with tempfile.TemporaryDirectory() as directory:
        data = Path(directory)
        config_file = data / "config.json"
        config_file.write_text(json.dumps({"ui_language": "de", "room_name": "Tester", "room_ai": "Helfer"}),
                               encoding="utf-8")
        initialize = i18n.initialize
        with mock.patch.object(i18n, "initialize", side_effect=lambda _path: initialize(config_file)):
            import monhip
        import chats
        import chatview
        import checkpoints
        import dialogs
        import galerie
        import icons
        import images
        import bilder
        import memory
        import reminders
        import room
        import roomui
        import themes
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
        errors = []
        root.report_callback_exception = lambda *args: errors.append(args[1])
        app = monhip.App(root)
        app.app_dir = data
        report = {}

        def steps():
            # Einstellungen: jede Seite einmal
            for tab in app.settings_tabs:
                app.open_settings(tab)
                yield
            # Designs: alle, zuletzt wieder dunkel. Das offene Einstellungsfenster passt seine Breite jeweils an: jede
            # Seite hat Platz, und der letzte Reiter endet bündig mit dem Rahmen darunter (außer bei nativ gezeichneten
            # Reitern wie „Windows-Standard“ – die stehen links wie in Windows-Dialogen)
            nb, last = app.settings_nb, len(app.settings_nb.tabs()) - 1

            def tab_at(x):
                try:
                    return int(nb.index(f"@{x},8"))
                except (tk.TclError, ValueError):
                    return -1

            flush = report["tabs_flush"] = {}
            for key in themes.THEMES:
                app.set_theme(key, save=False)
                yield
                yield
                end = nb.winfo_width() + 20  # erstes Pixel rechts vom letzten Reiter
                while end > 0 and tab_at(end - 1) != last:
                    end -= 1
                pane = nb.nametowidget(nb.select()).winfo_width()
                flush[key] = {"end": end, "width": nb.winfo_width(),
                              "native": not app._pixels(app.theme.style.lookup("TNotebook.Tab", "padding")),
                              "fits": max(f.winfo_reqwidth() for f in app.settings_tabs.values()) <= pane}
            app.close_settings()
            app.set_theme("dark", save=False)
            # Chat: Markdown, Code, Werkzeuge, Gedankengang
            v = app.view
            v.clear()
            v.user("Hallo **Monhip**")
            v.markdown("# Titel\n\n- Punkt *eins*\n- Punkt `zwei`\n\n```python\nprint('hi')\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |")
            n = v.tool_begin("Websuche", "monhip", '{"query": "monhip"}', icon="🌐")
            v.tool_end(n, "Ergebnis", True)
            v.tool_static("Datei lesen", "a.txt", '{"path": "a.txt"}', "Inhalt", False, icon="✎")
            t = v.think_begin()
            v.think_append(t, "Ich überlege …")
            v.think_end(t)
            v.footer("{}", 12.5)
            yield
            # Mausrad: unter Linux (Tk 8.6) als Taste 5, sonst <MouseWheel> – der Chat muss weich nach unten scrollen
            v.markdown("\n\n".join(f"Absatz {i}: " + "Text " * 30 for i in range(80)))
            yield
            v.t.yview_moveto(0)
            v._stick = False
            yield
            for _ in range(3):
                if sys.platform == "win32":
                    v.t.event_generate("<MouseWheel>", delta=-120, x=20, y=20)
                else:
                    v.t.event_generate("<Button-5>", x=20, y=20)
            for _ in range(8):  # ~0,15 s weiches Scrollen
                yield
            report["wheel_scrolled"] = v.t.yview()[0] > 0
            # Ziehen in einem schmalen Fenster: Spaltenbreite bleibt beim Ziehen, danach kommt die passende;
            # ein einzelner Sprung (Maximieren, Andocken) gilt sofort
            root.minsize(400, 300)
            root.geometry("820x700")
            for _ in range(5):
                yield
            time.sleep(0.25)
            yield
            frame = v.t.master

            def expect():
                return min(frame.winfo_width() - v._sb.winfo_width(), v._s(chatview.MAX_COLUMN) + 2 * v._padx)

            root.geometry("790x700")  # erster Schritt nach einer Pause: sofort
            root.update()
            jump = {"width": v.t.winfo_width(), "expect": expect()}
            before = v.t.winfo_width()
            root.geometry("760x700")  # gleich danach: Ziehen
            root.update()
            during = v.t.winfo_width()
            time.sleep(0.25)
            yield
            yield
            report["column"] = {"before": before, "during": during, "after": v.t.winfo_width(), "expect": expect(),
                                "jump": jump}
            # Teamwork: Raum als Gastgeber auf 127.0.0.1, Seitenleiste mit Symbolen
            app.set_mode("room")
            with mock.patch.object(app.room, "show_invite"):
                app.room.create("Testraum", "127.0.0.1", 0, room.new_key())
                deadline = time.time() + 15
                while not app.room.connected and time.time() < deadline:
                    yield
            report["connected"] = app.room.connected
            report["state"] = app.room.state
            yield
            report["room_icons"] = images_in(app.room_side)
            app.room.open_tasks()
            yield
            app.room._tasks_win.destroy()
            with mock.patch.object(dialogs, "askyesno", return_value=True):
                app.room.leave()
            yield
            # Bilder: Galerie mit einem Bild, große Vorschau, Platzhalter, zurück in den Chat
            probe = tk.PhotoImage(master=root, width=64, height=48)
            probe.put("#3366aa", to=(0, 0, 64, 48))
            probe.write(str(data / "probe.png"), format="png")
            app.images.gallery = galerie.Gallery(data / "bilder")
            item = app.images.gallery.add((data / "probe.png").read_bytes(),
                                          {"prompt": "Ein blaues Rechteck", "width": 64, "height": 48, "seed": 1})
            app.set_mode("images")
            yield
            app.images.show_image(item)
            yield
            report["images"] = {"listed": len(app.images.tree.get_children()), "shown": app.images.shown is item,
                                "icons": images_in(app.images.page), "page": app.images.page.winfo_ismapped()}
            # Unterbereiche: „Bild bearbeiten“ markiert, ohne Formatwahl, mit Zeile für die Vorlage
            ims = app.images
            report["images"]["create_selected"] = ims.create_btn.instate(["selected"])
            ims.set_mode("edit")
            yield
            report["images"]["edit"] = {
                "selected": ims.edit_btn.instate(["selected"]) and not ims.create_btn.instate(["selected"]),
                "format_hidden": not ims.format_combo.winfo_manager(), "row": bool(ims.source_row.winfo_manager())}
            with mock.patch.object(dialogs, "showerror"):  # Linux ohne Pillow/ImageMagick: Vorlage geht nicht
                ims.edit_item(item)  # Galerie-Bild weiterbearbeiten
                deadline = time.time() + 30
                while ims.source is None and time.time() < deadline:
                    yield
            report["images"]["edit"]["source"] = ims.source is not None and ims.mode == "edit"
            # „Modell laden“ mit fehlender Datei: nachfragen, herunterladen (nachgestellt), danach laden
            key = ims.model_key()
            state = {"ready": False, "installed": 0, "progress": []}
            plan = {"program": [], "weights": [("teil.gguf", "http://example.invalid/teil.gguf", 2000,
                                                data / "teil.gguf")], "size": 2000, "tag": "", "kind": ""}

            def fake_install(_plan, progress, _cancel):
                for done in (1000, 2000):
                    progress(done, 2000)
                    state["progress"].append(done)
                state["ready"] = True
                state["installed"] += 1

            with mock.patch.object(bilder.sdcpp, "ready", lambda _k: state["ready"]), \
                    mock.patch.object(bilder.sdcpp, "plan", return_value=plan), \
                    mock.patch.object(bilder.sdcpp, "install", side_effect=fake_install), \
                    mock.patch.object(dialogs, "askyesno", return_value=True), \
                    mock.patch.object(ims.server, "start", side_effect=lambda k, _c: setattr(ims.server, "model", k)), \
                    mock.patch.object(ims.server, "is_running", lambda: ims.server.model is not None):
                ims.load()
                deadline = time.time() + 30
                while (ims.busy or ims._checking or ims.server.model != key) and time.time() < deadline:
                    yield
                yield
                report["images"]["load"] = {"installed": state["installed"], "progress": state["progress"],
                                            "loaded": ims.server.model == key, "engine": ims.engine_var.get()}
            ims.server.model = None
            app.images.new_image()
            yield
            report["images"]["back_to_create"] = ims.mode == "create" and ims.create_btn.instate(["selected"])
            # Unterbereich „3D-Modell“: keine Beschreibung, dafür Feinheit und Vorlage; ein fertiges Modell in der
            # Galerie zeigt seine eigenen Aktionen (Ansehen, STL, GLB)
            ims.set_mode("3d")
            yield
            glb = data / "modell.glb"
            glb.write_bytes(b"glTF")  # Inhalt egal – hier geht es nur um die Oberfläche
            model = ims.gallery.add_model((data / "probe.png").read_bytes(), glb, {"prompt": "Ein Würfel",
                                                                                   "width": 64, "height": 48})
            ims.refresh_list(select=model["file"])
            ims.show_image(model)
            yield
            report["images"]["3d"] = {
                "selected": ims.model3d_btn.instate(["selected"]), "button": ims.gen_btn.cget("text"),
                "no_prompt": not ims._inp.winfo_manager(), "detail": bool(ims.res_combo.winfo_manager()),
                "source_row": bool(ims.source_row.winfo_manager()), "variants": len(ims.pick.cget("values")),
                "actions3d": bool(ims.actions3d.winfo_manager()) and not ims.actions.winfo_manager()}
            ims.set_mode("create")
            yield
            report["images"]["3d"]["back"] = bool(ims._inp.winfo_manager()) and not ims.res_combo.winfo_manager()
            # 3D-Modell aus einer Beschreibung: Bildmodell laden, Bild erzeugen, Bildmodell beenden, dann TRELLIS.2 –
            # Bild und 3D-Modell landen in der Galerie (Bildmodell und trellis-cli nachgestellt)
            ims.set_mode("3d")
            ims.from_var.set("text")
            ims._on_from()
            yield
            text_ui = {"prompt": bool(ims._inp.winfo_manager()), "no_source": not ims.source_row.winfo_manager(),
                       "improve": bool(ims.improve_btn.winfo_manager())}
            calls, before = [], len(ims.gallery.snapshot())
            import trellis

            def fake_start(key, _stop):
                calls.append("laden")
                ims.server.model = key

            def fake_generate(prompt, w, h, count, seed, stop, on_progress=None, **_kw):
                calls.append(("bild", prompt, w, h))
                if on_progress:
                    on_progress(1, 1, None)
                return [(data / "probe.png").read_bytes()]

            def fake_trellis(variant, image, out, res, seed, stop, on_progress=None, log=None):
                calls.append(("3d", Path(image).is_file(), res))
                if on_progress:
                    on_progress({"stage": 4, "step": 3, "steps": 12, "eta": None})
                out.write_bytes(b"glTF")
                return out

            with mock.patch.object(bilder.sdcpp, "ready", return_value=True), \
                    mock.patch.object(trellis, "ready", return_value=True), \
                    mock.patch.object(ims.server, "ready_for", side_effect=lambda k: ims.server.model == k), \
                    mock.patch.object(ims.server, "start", side_effect=fake_start), \
                    mock.patch.object(ims.server, "generate", side_effect=fake_generate), \
                    mock.patch.object(ims.server, "stop", side_effect=lambda *a: calls.append("beenden")), \
                    mock.patch.object(trellis, "generate", side_effect=fake_trellis):
                ims.server.model = None
                ims.prompt.delete("1.0", "end")
                ims.prompt.insert("1.0", "eine Teekanne aus Porzellan")
                ims.generate()
                deadline = time.time() + 20
                while (ims.busy or not calls or calls[-1][0] != "3d") and time.time() < deadline:
                    yield
                for _ in range(5):
                    yield
            items = ims.gallery.snapshot()
            report["images"]["text3d"] = {
                "ui": text_ui, "order": [c if isinstance(c, str) else c[0] for c in calls],
                "hint": bool(calls) and len(calls) > 1 and calls[1][1].startswith("eine Teekanne aus Porzellan")
                and calls[1][1].endswith(bilder.OBJECT_HINT),
                "new_items": len(items) - before, "model_first": bool(items and items[0].get("model3d")),
                "image_linked": bool(items and items[0].get("image") == items[1]["file"]),
                "shown": ims.shown is items[0] if items else False, "busy": ims.busy}
            ims.server.model = None
            ims.from_var.set("image")
            ims._on_from()
            ims.set_mode("create")
            yield
            app.set_mode("chat")
            report["images"]["hidden"] = not app.images.page.winfo_ismapped()
            report["chat_icons"] = images_in(app.root)
            report["render"] = bool(icons.RENDER)
            report["family"] = icons.FAMILY

        it = steps()

        def tick():
            try:
                next(it)
                root.after(80, tick)
            except StopIteration:
                finish()
            except BaseException as error:
                errors.append(error)
                finish()

        def finish():
            report["errors"] = [f"{type(e).__name__}: {e}" for e in errors]
            print("REPORT " + json.dumps(report, ensure_ascii=False))
            app.room.server = app.room.client = None
            app.on_close()

        root.after(600, tick)
        root.mainloop()


@unittest.skipUnless(os.environ.get("DISPLAY") or sys.platform == "win32", "GUI benötigt einen Bildschirm")
class GuiSmoke(unittest.TestCase):
    def test_settings_themes_chat_and_room(self):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--gui-worker"], text=True,
                                capture_output=True, timeout=120, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        lines = [ln for ln in result.stdout.splitlines() if ln.startswith("REPORT ")]
        self.assertTrue(lines, result.stdout + result.stderr)
        report = json.loads(lines[-1][7:])
        self.assertEqual(report["errors"], [], result.stderr)
        self.assertTrue(report["connected"], report)
        self.assertTrue(report["wheel_scrolled"], "Mausrad scrollt den Chat nicht")
        self.assertEqual({k: v for k, v in report["tabs_flush"].items()
                          if not v["fits"] or (v["end"] != v["width"] and not v["native"])}, {},
                         "Einstellungen: Seite passt nicht ins Fenster oder Reiter enden nicht bündig mit dem Rahmen")
        img = report["images"]
        self.assertEqual((img["listed"], img["shown"], img["page"], img["hidden"]), (1, True, True, True), img)
        # Bereich Bilder: Unterbereiche, Vorlage aus der Galerie, fehlende Datei laden und danach das Modell laden
        self.assertTrue(img["create_selected"] and img["back_to_create"], img)
        self.assertEqual((img["edit"]["selected"], img["edit"]["format_hidden"], img["edit"]["row"]),
                         (True, True, True), img)
        if sys.platform == "win32" or importable("PIL"):
            self.assertTrue(img["edit"]["source"], img)
        self.assertEqual((img["load"]["installed"], img["load"]["progress"], img["load"]["loaded"]),
                         (1, [1000, 2000], True), img)
        self.assertIn("Qwen-Image 2.1", img["load"]["engine"])  # Standard-Bildmodell, „Geladen: …“
        self.assertEqual(img["3d"], {"selected": True, "button": "3D-Modell erzeugen", "no_prompt": True, "detail": True,
                                     "source_row": True, "variants": 3, "actions3d": True, "back": True}, img)
        self.assertEqual(img["text3d"], {
            "ui": {"prompt": True, "no_source": True, "improve": True},
            "order": ["laden", "bild", "beenden", "3d"],  # Bildmodell aus dem Grafikspeicher, bevor TRELLIS.2 rechnet
            "hint": True, "new_items": 2, "model_first": True, "image_linked": True, "shown": True, "busy": False}, img)
        col = report["column"]
        self.assertEqual(col["during"], col["before"], f"Spalte ändert beim Ziehen ihre Breite: {col}")
        self.assertLessEqual(abs(col["after"] - col["expect"]), 2, f"Spalte hat danach nicht die richtige Breite: {col}")
        self.assertLessEqual(abs(col["jump"]["width"] - col["jump"]["expect"]), 2,
                             f"einzelner Größensprung wartet unnötig: {col}")
        if report["render"]:  # Icon-Schrift da: Seitenleiste des Raums mit Symbolen (wie unter Windows)
            self.assertGreaterEqual(report["room_icons"], 5, report)
        if sys.platform.startswith("linux") and importable("PIL"):
            self.assertTrue(report["render"], "Linux mit Pillow: Symbole müssen gezeichnet werden")
            self.assertEqual(report["family"], "Monhip Icons")


def importable(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


if __name__ == "__main__":
    if sys.argv[1:] == ["--gui-worker"]:
        gui_worker()
    else:
        unittest.main()
