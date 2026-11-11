"""Tests für Sprachmodelle ohne Netz: aufgeteilte Modelle (nur der erste Teil in der Liste, Name und Größe über alle
Teile), empfohlene Modelle (gleich wie im Windows-Installer), Direktlinks und der Download mehrerer Dateien über einen
lokalen HTTP-Server (vorhandene bleiben, Abbruch ohne Reste, zu wenig Platz): python -m unittest discover -s progress/tests -p test_modelle.py"""

import functools
import http.server
import re
import shutil
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "app"))
INSTALLER_SRC = REPO / "installer" / "windows" / "src"  # Quellen der Installer: nur auf dem Entwicklungsrechner

import backend
import downloads


class SplitModels(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        sub = self.dir / "Qwen3.8-Flash-Next"
        sub.mkdir()
        for i, size in ((1, 10), (2, 300), (3, 200)):
            (sub / f"Qwen3.8-Flash-Next-UD-IQ1_S-0000{i}-of-00003.gguf").write_bytes(b"x" * size)
        (sub / "mmproj-F16.gguf").write_bytes(b"m")
        (self.dir / "Klein.gguf").write_bytes(b"k" * 5)
        (self.dir / "Halb.gguf.part").write_bytes(b"p")

    def test_only_first_part_listed(self):
        names = [p.name for p in backend.find_models([str(self.dir)])]
        self.assertEqual(names, ["Klein.gguf", "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf"])

    def test_name_size_and_parts(self):
        first = self.dir / "Qwen3.8-Flash-Next" / "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf"
        self.assertEqual(backend.model_name(first), "Qwen3.8-Flash-Next-UD-IQ1_S")
        self.assertEqual(backend.model_size(first), 510)
        self.assertEqual([p.name for p in backend.shard_parts(first)],
                         [f"Qwen3.8-Flash-Next-UD-IQ1_S-0000{i}-of-00003.gguf" for i in (1, 2, 3)])
        self.assertEqual(backend.find_mmproj(first).name, "mmproj-F16.gguf")
        klein = self.dir / "Klein.gguf"
        self.assertEqual((backend.model_name(klein), backend.model_size(klein)), ("Klein", 5))
        self.assertEqual(backend.shard_parts(klein), [klein])

    def test_missing_part_counts_what_is_there(self):
        first = self.dir / "Qwen3.8-Flash-Next" / "Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf"
        (first.parent / "Qwen3.8-Flash-Next-UD-IQ1_S-00003-of-00003.gguf").unlink()
        self.assertEqual(backend.model_size(first), 310)


class Catalog(unittest.TestCase):
    def test_files_flat_in_folder_model_first(self):
        files = backend.catalog_files("qwen3.8-flash-next", Path("modelle"))
        self.assertEqual([d.as_posix() for _, d in files],
                         [f"modelle/Qwen3.8-Flash-Next/Qwen3.8-Flash-Next-UD-IQ1_S-0000{i}-of-00003.gguf"
                          for i in (1, 2, 3)] + ["modelle/Qwen3.8-Flash-Next/mmproj-F16.gguf"])
        self.assertEqual(files[0][0], "https://huggingface.co/unsloth/Qwen3.8-Flash-Next-GGUF/resolve/main/"
                                      "UD-IQ1_S/Qwen3.8-Flash-Next-UD-IQ1_S-00001-of-00003.gguf")

    @unittest.skipUnless(INSTALLER_SRC.is_dir(), "Quellen der Installer nur auf dem Entwicklungsrechner")
    def test_same_as_windows_installer(self):
        """Der Installer (Model.cs) und Monhip (backend.CATALOG) bieten dieselben Modelle mit denselben Dateien an."""
        cs = (INSTALLER_SRC / "Model.cs").read_text(encoding="utf-8")
        installer = {}
        for block in re.findall(r"new Model\s*\{(.*?)\n\t\t\t\}", cs, re.S):
            repo = re.search(r'Repo = "([^"]+)"', block).group(1)
            folder = re.search(r'Folder = "([^"]+)"', block).group(1)
            files = re.findall(r'"([^"]+\.gguf)"', re.search(r"Files = new string\[\d+\](.*?)\}", block, re.S).group(1))
            need = float(re.search(r"NeedGb = ([\d.]+)", block).group(1))
            installer[repo] = (folder, tuple(files), need)
        monhip = {e["repo"]: (e["folder"], tuple(e["files"]), float(e["need_gb"])) for e in backend.CATALOG.values()}
        self.assertEqual(len(installer), 2)
        self.assertEqual(installer, monhip)

    @unittest.skipUnless(INSTALLER_SRC.is_dir(), "Quellen der Installer nur auf dem Entwicklungsrechner")
    def test_image_model_same_as_windows_installer(self):
        """Der Installer (ImageModel.cs) bietet das Standard-Bildmodell von Monhip (sdcpp.DEFAULT_MODEL) an."""
        import sdcpp
        cs = (INSTALLER_SRC / "ImageModel.cs").read_text(encoding="utf-8")
        folder = re.search(r'Folder = "([^"]+)"', cs).group(1)
        block = re.search(r"Files = new string\[\d+\]\[\]\s*\{(.*?)\n\t\t\t\},", cs, re.S).group(1)
        files = re.findall(r'new string\[2\] \{ "([^"]+)", "([^"]+)" \}', block)
        m = sdcpp.MODELS[sdcpp.DEFAULT_MODEL]
        self.assertEqual(re.search(r'Name = "([^"]+)"', cs).group(1), m["name"])
        self.assertEqual(folder, m["folder"])
        self.assertEqual(files, [(repo, path) for _role, repo, path in m["files"]])
        portable = re.search(r'Portable = new string\[2\] \{ "([^"]+)", "([^"]+)" \}', cs).groups()
        self.assertEqual(portable, m["portable"]["diffusion-model"])  # ohne CUDA: dasselbe als GGUF


class Links(unittest.TestCase):
    def test_single_file(self):
        files = backend.link_files("https://huggingface.co/a/b/blob/main/Modell-Q4.gguf?download=true", Path("m"))
        self.assertEqual(files, [("https://huggingface.co/a/b/resolve/main/Modell-Q4.gguf?download=true",
                                  Path("m") / "Modell-Q4.gguf")])

    def test_any_part_brings_all_parts(self):
        files = backend.link_files("https://huggingface.co/a/b/resolve/main/Q/X-00002-of-00003.gguf", Path("m"))
        self.assertEqual([u.rsplit("/", 1)[-1] for u, _ in files],
                         ["X-00001-of-00003.gguf", "X-00002-of-00003.gguf", "X-00003-of-00003.gguf"])
        self.assertTrue(all(u.startswith("https://huggingface.co/a/b/resolve/main/Q/") for u, _ in files))
        self.assertEqual(files[0][1], Path("m") / "X-00001-of-00003.gguf")

    def test_not_a_model(self):
        self.assertIsNone(backend.link_files("https://example.invalid/datei.zip", Path("m")))
        self.assertIsNone(backend.link_files("Modell.gguf", Path("m")))


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class FetchFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path(tempfile.mkdtemp())
        for name, size in (("a.gguf", 3000), ("b.gguf", 5000), ("mmproj-F16.gguf", 700)):
            (cls.src / name).write_bytes(bytes(range(256)) * (size // 256) + b"!" * (size % 256))
        handler = functools.partial(QuietHandler, directory=str(cls.src))
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}/"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.src, ignore_errors=True)

    def setUp(self):
        self.dest = Path(tempfile.mkdtemp()) / "Modell"
        self.addCleanup(shutil.rmtree, self.dest.parent, ignore_errors=True)
        self.files = [(self.base + n, self.dest / n) for n in ("a.gguf", "b.gguf", "mmproj-F16.gguf")]

    def test_downloads_all_with_total_progress(self):
        seen = []
        done = downloads.fetch_files(self.files, lambda d, n: seen.append((d, n)), threading.Event())
        self.assertEqual(done, 8700)
        for _, dest in self.files:
            self.assertEqual(dest.read_bytes(), (self.src / dest.name).read_bytes())
        self.assertEqual(seen[-1], (8700, 8700))
        self.assertTrue(all(n == 8700 for _, n in seen))
        self.assertEqual(list(self.dest.glob("*.part")), [])

    def test_existing_files_are_kept(self):
        self.dest.mkdir(parents=True)
        (self.dest / "a.gguf").write_bytes(b"schon da")
        done = downloads.fetch_files(self.files, lambda d, n: None, threading.Event())
        self.assertEqual(done, 5700)
        self.assertEqual((self.dest / "a.gguf").read_bytes(), b"schon da")
        self.assertEqual(downloads.fetch_files(self.files, lambda d, n: None, threading.Event()), 0)

    def test_cancel_leaves_no_parts(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(RuntimeError):
            downloads.fetch_files(self.files, lambda d, n: None, cancel)
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), [])

    def test_not_enough_space(self):
        with mock.patch.object(downloads.shutil, "disk_usage", return_value=mock.Mock(free=1000)):
            with self.assertRaises(RuntimeError) as cm:
                downloads.fetch_files(self.files, lambda d, n: None, threading.Event())
        self.assertIn("1.0", str(cm.exception))
        self.assertFalse(any(self.dest.iterdir()))


if __name__ == "__main__":
    unittest.main()
