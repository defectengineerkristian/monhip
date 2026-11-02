"""Tests für app/plattform.py und die Linux-Zweige der Module (Downloads, Bilder, PDF, Aufnahme, Zwischenablage).
Unter Windows laufen nur die systemunabhängigen Teile; was ein Linux-Programm braucht (pdftoppm, Pillow, xclip …),
wird übersprungen, wenn es fehlt: python -m unittest tests.test_plattform"""

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import threading
import time
import unittest
import urllib.parse
import zipfile
from pathlib import Path
from unittest import mock

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

import plattform

LINUX = plattform.LINUX


def _alive(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(") ", 1)[1][0] != "Z"  # Zombie zählt als beendet
    except OSError:
        return False


def _wait_dead(pid: int, seconds: float = 5) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


class PlatformBasics(unittest.TestCase):
    def test_exe_and_shell(self):
        self.assertEqual(plattform.exe("llama-server"), "llama-server.exe" if plattform.WINDOWS else "llama-server")
        argv = plattform.shell_argv("echo hallo")
        self.assertEqual(argv[-1].endswith("echo hallo"), True)
        if not plattform.WINDOWS:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=10)
            self.assertEqual(r.stdout.strip(), "hallo")

    def test_data_dir(self):
        """Daten wie bisher neben dem Programm; MONHIP_DATA (Linux-Paket) bzw. ein schreibgeschützter Programmordner
        unter Linux lenken sie in den Benutzerordner."""
        with mock.patch.dict(os.environ, {"MONHIP_DATA": ""}):
            with mock.patch.object(plattform.os, "access", return_value=True):
                self.assertEqual(plattform._data_dir(), plattform.CODE_DIR)
            with mock.patch.object(plattform.os, "access", return_value=False), \
                    mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/tmp/xdg"}):
                self.assertEqual(plattform._data_dir(), plattform.CODE_DIR if plattform.WINDOWS
                                 else Path("/tmp/xdg/monhip"))
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"MONHIP_DATA": d}):
            self.assertEqual(plattform._data_dir(), Path(d).resolve())

    def test_need_names_package(self):
        with mock.patch.object(plattform.shutil, "which", return_value=None):
            with self.assertRaisesRegex(OSError, r"pdftoppm fehlt – bitte installieren \(Paket poppler-utils\)"):
                plattform.need("pdftoppm", package="poppler-utils")

    def test_missing_tool_message_is_translated(self):
        import i18n
        language = i18n._language
        try:
            i18n._language = "en"
            self.assertEqual(i18n.error_text("pdftoppm fehlt – bitte installieren (Paket poppler-utils)."),
                             "pdftoppm is missing – please install it (package poppler-utils).")
        finally:
            i18n._language = language


@unittest.skipUnless(LINUX, "nur Linux")
class LinuxProcesses(unittest.TestCase):
    def test_bound_process_survives_its_thread_and_dies_with_the_app(self):
        """PR_SET_PDEATHSIG hängt am startenden Thread: aus einem kurzen Thread gestartet muss der Prozess weiterlaufen
        (Start-Thread), aber mit dem Programm enden – auch wenn es hart abbricht (os._exit)."""
        script = textwrap.dedent(f"""
            import os, sys, threading, time
            sys.path.insert(0, {str(APP)!r})
            import plattform
            box = {{}}
            t = threading.Thread(target=lambda: box.update(p=plattform.popen(["sleep", "60"], bound=True)))
            t.start(); t.join()
            time.sleep(0.5)  # der Arbeits-Thread ist längst zu Ende
            print(box["p"].pid, box["p"].monhip_bound, box["p"].poll() is None, flush=True)
            os._exit(0)
        """)
        r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
        pid, bound, running = r.stdout.split()
        self.assertEqual((bound, running), ("True", "True"), r.stderr)
        self.assertTrue(_wait_dead(int(pid)), "llama-server & Co. müssen mit Monhip enden")

    def test_kill_tree_reaches_children(self):
        p = plattform.popen(["bash", "-c", "sleep 60 & echo $!; wait"], group=True, stdout=subprocess.PIPE, text=True)
        child = int(p.stdout.readline())
        self.assertTrue(_alive(child))
        plattform.kill_tree(p)
        p.wait(5)
        self.assertTrue(_wait_dead(child), "Unterprozess (z. B. node unter npm) muss mit beendet werden")
        p.stdout.close()

    def test_prozesse_stop_ends_subprocesses(self):
        import prozesse
        with tempfile.TemporaryDirectory() as d:
            p = prozesse.start(plattform.shell_argv("sleep 60 & echo $!; wait"), d, "Test")
            deadline = time.time() + 5
            while not p.read_new() and time.time() < deadline:
                time.sleep(0.05)
            out = "".join(p._buf.decode().split())
            child = int(out)
            p.stop()
            self.assertTrue(_wait_dead(child))


@unittest.skipUnless(LINUX, "nur Linux")
class LinuxFiles(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_trash_home_follows_freedesktop(self):
        trash = self.dir / "Trash"
        for name in ("notiz.txt", "notiz.txt"):  # zweimal derselbe Name: der zweite bekommt eine Nummer
            f = self.dir / "daten" / name
            f.parent.mkdir(exist_ok=True)
            f.write_text("inhalt")
            plattform.trash_home(f, trash)
            self.assertFalse(f.exists())
        self.assertEqual(sorted(p.name for p in (trash / "files").iterdir()), ["notiz.2.txt", "notiz.txt"])
        info = (trash / "info" / "notiz.2.txt.trashinfo").read_text()
        self.assertIn("[Trash Info]", info)
        self.assertIn("Path=" + urllib.parse.quote(str(self.dir / "daten" / "notiz.txt")), info)
        self.assertIn("DeletionDate=", info)

    def test_recycle_without_gio_uses_home_trash(self):
        f = self.dir / "weg.txt"
        f.write_text("x")
        with mock.patch.object(plattform, "which", return_value=None), \
                mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(self.dir / "share")}):
            plattform.recycle(f)
        self.assertTrue((self.dir / "share" / "Trash" / "files" / "weg.txt").is_file())

    def test_desktop_dir_from_user_dirs(self):
        (self.dir / "user-dirs.dirs").write_text('# Kommentar\nXDG_DESKTOP_DIR="$HOME/Schreibtisch"\n')
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.dir)}):
            self.assertEqual(plattform.desktop_dir(), Path.home() / "Schreibtisch")
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.dir / "fehlt")}):
            self.assertEqual(plattform.desktop_dir(), Path.home() / "Desktop")

    def test_mark_from_internet_leaves_no_stray_file(self):
        import web
        f = self.dir / "programm.sh"
        f.write_text("echo hi")
        web.mark_from_internet(f, "https://example.com/programm.sh")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["programm.sh"])

    def test_unsafe_root_blocks_system_folders(self):
        import projekt
        self.assertTrue(projekt.unsafe_root(Path("/usr/share")))
        self.assertTrue(projekt.unsafe_root(Path.home() / ".config" / "autostart"))
        self.assertIsNone(projekt.unsafe_root(self.dir))

    def test_font_file_finds_installed_fonts(self):
        import pdfsatz
        found = [name for names in pdfsatz.FACES.values() for name in names if plattform.font_file(name)]
        if not found:
            self.skipTest("keine passende Schrift installiert")
        target = self.dir / "test.pdf"
        pages = pdfsatz.write_pdf(target, "# Überschrift\n\nText mit **fett**, *kursiv* und `code` – Ä Ö Ü ß €.")
        self.assertGreaterEqual(pages, 1)
        self.assertTrue(target.read_bytes().startswith(b"%PDF"))


class Downloads(unittest.TestCase):
    """llama.cpp: die richtigen Dateien je System und das Entpacken der Linux-Archive."""

    def release(self, tag="b100"):
        names = [f"llama-{tag}-bin-win-cpu-x64.zip", f"llama-{tag}-bin-win-vulkan-x64.zip",
                 f"llama-{tag}-bin-win-cuda-12.4-x64.zip", f"llama-{tag}-bin-win-cuda-13.4-x64.zip",
                 "cudart-llama-bin-win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-13.4-x64.zip",
                 f"llama-{tag}-bin-ubuntu-x64.tar.gz", f"llama-{tag}-bin-ubuntu-vulkan-x64.tar.gz",
                 f"llama-{tag}-bin-ubuntu-cuda-12.8-x64.tar.gz", f"llama-{tag}-bin-ubuntu-cuda-13.4-x64.tar.gz",
                 f"cudart-llama-{tag}-bin-ubuntu-cuda-12.8-x64.tar.gz",
                 f"cudart-llama-{tag}-bin-ubuntu-cuda-13.4-x64.tar.gz"]
        return {"tag_name": tag, "assets": [{"name": n, "size": 1, "browser_download_url": n} for n in names]}

    def pick(self, vendor, cuda, linux):
        import llamacpp
        with mock.patch.object(llamacpp.platform, "machine", return_value="x86_64"):
            kind, assets = llamacpp._pick_assets(self.release(), vendor, cuda, linux=linux)
        return kind, [a["name"] for a in assets]

    def test_windows_choice_unchanged(self):
        self.assertEqual(self.pick("nvidia", (13, 5), False),
                         ("CUDA 13.4", ["llama-b100-bin-win-cuda-13.4-x64.zip", "cudart-llama-bin-win-cuda-13.4-x64.zip"]))
        self.assertEqual(self.pick("amd", None, False), ("Vulkan", ["llama-b100-bin-win-vulkan-x64.zip"]))
        self.assertEqual(self.pick("", None, False), ("CPU", ["llama-b100-bin-win-cpu-x64.zip"]))

    def test_linux_choice(self):
        self.assertEqual(self.pick("nvidia", (13, 0), True),
                         ("CUDA 12.8", ["llama-b100-bin-ubuntu-cuda-12.8-x64.tar.gz",
                                        "cudart-llama-b100-bin-ubuntu-cuda-12.8-x64.tar.gz"]))
        self.assertEqual(self.pick("intel", None, True), ("Vulkan", ["llama-b100-bin-ubuntu-vulkan-x64.tar.gz"]))
        self.assertEqual(self.pick("", None, True), ("CPU", ["llama-b100-bin-ubuntu-x64.tar.gz"]))

    def test_folder_names_keep_the_kind(self):
        import llamacpp
        for asset, kind in (("llama-b100-bin-ubuntu-x64.tar.gz", "cpu"),
                            ("llama-b100-bin-ubuntu-vulkan-x64.tar.gz", "vulkan"),
                            ("llama-b100-bin-win-cuda-12.4-x64.zip", "cuda-12.4")):
            m = llamacpp._FOLDER_RE.match(llamacpp._folder(asset))
            self.assertIsNotNone(m, asset)
            self.assertEqual((m.group(1), m.group(2)), ("100", kind))

    def test_tar_gz_with_nested_folder_and_executable(self):
        import downloads
        exe = plattform.exe("llama-server")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as t:
                for name, mode, data in ((f"build/bin/{exe}", 0o755, b"#!/bin/sh\necho ok\n"),
                                         ("build/bin/libllama.so", 0o644, b"lib")):
                    info = tarfile.TarInfo(name)
                    info.size, info.mode = len(data), mode
                    t.addfile(info, io.BytesIO(data))
            archive = buf.getvalue()

            def fake_download(url, dest, progress, cancel, done=0, total=0):
                dest.write_bytes(archive)
                return done + len(archive)

            with mock.patch.object(downloads, "download", fake_download):
                downloads.install_zips([("llama-b1-bin-ubuntu-x64.tar.gz", "url", 1)], d / "llama-b1-bin-ubuntu-cpu-x64",
                                       exe, lambda *_: None, threading.Event())
            target = d / "llama-b1-bin-ubuntu-cpu-x64"
            self.assertTrue((target / exe).is_file())
            self.assertTrue((target / "libllama.so").is_file())
            if not plattform.WINDOWS:
                self.assertTrue(os.access(target / exe, os.X_OK))

    def test_zip_gets_executable_bit(self):
        import downloads
        if plattform.WINDOWS:
            self.skipTest("nur ohne Windows")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("Release/whisper-cli", "#!/bin/sh\n")
            data = buf.getvalue()
            with mock.patch.object(downloads, "download",
                                   lambda url, dest, *a, **k: dest.write_bytes(data) or len(data)):
                downloads.install_zips([("w.zip", "url", 1)], d / "w", "whisper-cli", lambda *_: None,
                                       threading.Event())
            self.assertTrue(os.access(d / "w" / "whisper-cli", os.X_OK))


@unittest.skipUnless(LINUX, "nur Linux")
class LinuxMedia(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def photo(self, name="foto.jpg", size=(800, 400), orientation=None):
        from PIL import Image
        img = Image.new("RGB", size, (200, 30, 30))
        exif = Image.Exif()
        if orientation:
            exif[0x0112] = orientation
        img.save(self.dir / name, exif=exif.tobytes())
        return self.dir / name

    def test_thumbnail_and_size(self):
        if not importlib.util.find_spec("PIL"):
            self.skipTest("Pillow fehlt")
        import images
        doc = images.read(self.photo(), self.dir / "vorschau.png", 100)
        self.assertEqual(doc.image, (800, 400))
        self.assertEqual(images.png_size(self.dir / "vorschau.png"), (100, 50))

    def test_bildwerk_with_pillow(self):
        if not importlib.util.find_spec("PIL"):
            self.skipTest("Pillow fehlt")
        import bildwerk
        src = self.photo(orientation=6)  # Handy hochkant: 800×400 gespeichert, 400×800 gemeint
        opts = bildwerk.options(max_kante=200, format="png", drehen=90)
        jobs = bildwerk.plan([src], self.dir / "bearbeitet", opts)
        done, errors = bildwerk.run(jobs, opts)
        self.assertEqual(errors, [])
        self.assertEqual(done[0][2], "200×100")  # erst EXIF (hochkant), dann 90° gedreht → wieder quer
        self.assertTrue((self.dir / "bearbeitet" / "foto.png").is_file())

    def test_render_pdf_pages_with_poppler(self):
        if not (shutil.which("pdftoppm") and shutil.which("pdfinfo")):
            self.skipTest("poppler-utils fehlt")
        import experte
        import pdfsatz
        if not plattform.font_file(pdfsatz.FACES["regular"][0]) and not any(
                plattform.font_file(n) for n in pdfsatz.FACES["regular"]):
            self.skipTest("keine Schrift für das Test-PDF")
        pdf = self.dir / "scan.pdf"
        pdfsatz.write_pdf(pdf, "\n\n".join(f"# Seite {i}\n\n" + "Text " * 1500 for i in range(1, 4)))
        pngs, total = experte.render_pdf(pdf, self.dir / "seiten", first=2, count=5, width=300)
        self.assertGreaterEqual(total, 3)
        self.assertEqual([nr for nr, _ in pngs], list(range(2, total + 1)))
        self.assertTrue(all(p.name == f"seite-{nr:04d}.png" and p.is_file() for nr, p in pngs))

    def test_recorder_stops_cleanly_with_sigint(self):
        """Statt eines Mikrofons ein Ersatz-„arecord“: schreibt erst beim SIGINT die Datei fertig – wie die echten."""
        import speech
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "arecord"
        fake.write_text(textwrap.dedent(f"""\
            #!{sys.executable}
            import signal, sys, time
            path = sys.argv[-1]
            def done(*_):
                open(path, "wb").write(b"RIFF" + bytes(40) + bytes(3200))
                sys.exit(0)
            signal.signal(signal.SIGINT, done)
            while True:
                time.sleep(0.05)
        """))
        fake.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": str(bin_dir)}), \
                mock.patch.object(speech, "TEMP_DIR", self.dir / "tmp"):
            rec = speech.Recorder()
            self.assertIsInstance(rec, speech.LinuxRecorder)
            rec.start()
            self.assertTrue(rec.active)
            time.sleep(0.3)
            path = rec.stop()
        self.assertFalse(rec.active)
        self.assertTrue(path.name.startswith("Diktat ") and path.stat().st_size > 44)

    def test_recorder_without_program(self):
        import speech
        with mock.patch.object(plattform, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "pw-record, parecord oder arecord"):
                speech.Recorder().start()


@unittest.skipUnless(LINUX and os.environ.get("DISPLAY") and shutil.which("xclip"), "braucht X11 und xclip")
class LinuxClipboard(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        self.root.destroy()
        shutil.rmtree(self.dir, ignore_errors=True)
        subprocess.run(["xclip", "-selection", "clipboard", "-i"], input=b"", timeout=5)

    def offer(self, data: bytes, target: str):
        subprocess.run(["xclip", "-selection", "clipboard", "-t", target, "-i"], input=data, timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.2)

    def test_copied_files_from_file_manager(self):
        import filedrop
        f = self.dir / "Bericht 1.pdf"
        f.write_bytes(b"%PDF")
        self.offer(f"copy\n{f.as_uri()}".encode(), "x-special/gnome-copied-files")
        self.assertEqual(filedrop.clipboard_files(self.root), [str(f)])  # Tk-Thread: über Tk selbst
        self.assertEqual(filedrop.clipboard_files(), [str(f)])           # Werkzeug-Thread: über xclip

    def test_image_and_text(self):
        import filedrop
        from images import save_clipboard
        png = (b"\x89PNG\r\n\x1a\n" + bytes(8) + b"IHDR" + (5).to_bytes(4, "big") + (3).to_bytes(4, "big")
               + bytes(20))
        self.offer(png, "image/png")
        self.assertTrue(filedrop.clipboard_has_image(self.root))
        self.assertTrue(filedrop.clipboard_has_image())
        with mock.patch("images.TEMP_DIR", self.dir):
            saved = save_clipboard()
        self.assertEqual(saved.read_bytes(), png)
        filedrop.set_clipboard_text("Grüße aus Monhip")
        time.sleep(0.2)
        self.assertEqual(filedrop.clipboard_text(), "Grüße aus Monhip")
        self.assertFalse(filedrop.clipboard_has_image(self.root))


class Prompts(unittest.TestCase):
    def test_system_prompt_names_the_system_and_shell(self):
        import agent
        with tempfile.TemporaryDirectory() as d:
            text = agent.Agent(lambda *_: "no", files=True, commands=True, workspace=d).system_prompt()
        self.assertIn(f"auf dem {plattform.NAME}-PC", text)
        self.assertIn("Windows PowerShell 5.1" if plattform.WINDOWS else "bash unter Linux", text)

    def test_off_hint_without_window_control(self):
        import agent
        self.assertEqual(agent.off_hint(True, False, True, can_control=False), "")
        self.assertNotIn("Programme bedienen", agent.off_hint(False, False, True, can_control=False))
        self.assertIn("Programme bedienen", agent.off_hint(True, False, True, can_control=True))

    @unittest.skipUnless(LINUX, "nur Linux")
    def test_run_command_uses_bash_and_stops_children(self):
        import agent
        with tempfile.TemporaryDirectory() as d:
            worker = agent.Agent(lambda *_: "yes", commands=True, workspace=d, confirm_actions=False)
            out = worker.execute("run_command", json.dumps({"command": "echo $((6*7)) && echo ok"}))
        self.assertIn("42", out)
        self.assertIn("ok", out)


if __name__ == "__main__":
    unittest.main()
