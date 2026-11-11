"""Tests für app/engines.py (gemeinsam für llama.cpp, stable-diffusion.cpp, trellis.cpp, whisper.cpp): Arten benennen
und ordnen, beste installierte Fassung finden: python -m unittest discover -s progress/tests -p test_engines.py"""

import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import engines


class Kinds(unittest.TestCase):
    def test_labels(self):
        self.assertEqual([engines.kind_label(k) for k in ("cuda12", "cuda-13.4", "cuda", "vulkan", "cpu", "rocm-10.1.0")],
                         ["CUDA 12", "CUDA 13.4", "CUDA", "Vulkan", "CPU", "ROCm 10.1.0"])

    def test_order(self):
        kinds = ["cpu", "vulkan", "sycl", "rocm", "cuda12"]
        self.assertEqual(sorted(kinds, key=engines.kind_rank), ["cuda12", "rocm", "vulkan", "sycl", "cpu"])


class FindProgram(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def make(self, folder, exe="sd-server.exe"):
        (self.dir / folder).mkdir()
        (self.dir / folder / exe).write_bytes(b"")

    def test_best_kind_then_newest_and_no_unfinished(self):
        folder_re = re.compile(r"sd-b(\d+)-(.+)$")
        for folder in ("sd-b1060-vulkan", "sd-b1066-vulkan", "sd-b1050-cuda12", "sd-b1070-cuda12.part"):
            self.make(folder)
        found = engines.find_program(self.dir, folder_re, "sd-server.exe")
        self.assertEqual(found, self.dir / "sd-b1050-cuda12" / "sd-server.exe")  # CUDA vor Vulkan, .part zählt nicht
        shutil.rmtree(self.dir / "sd-b1050-cuda12")
        self.assertEqual(engines.find_program(self.dir, folder_re, "sd-server.exe").parent.name, "sd-b1066-vulkan")

    def test_version_order_and_system_fallback(self):
        folder_re = re.compile(r"trellis-([\d.]+)-(cuda12|cuda|vulkan)$")
        for folder in ("trellis-0.8.1-vulkan", "trellis-0.10.0-vulkan", "trellis-0.9.2-vulkan"):
            self.make(folder, "trellis-cli")
        found = engines.find_program(self.dir, folder_re, "trellis-cli",
                                     order=lambda m: tuple(-int(x) for x in m.group(1).split(".")))
        self.assertEqual(found.parent.name, "trellis-0.10.0-vulkan")  # 0.10 ist neuer als 0.9 (nicht nach Text)
        with mock.patch.object(engines.plattform, "WINDOWS", False), \
                mock.patch.object(engines.plattform, "which", return_value="/usr/bin/trellis-cli"):
            self.assertEqual(engines.find_program(self.dir / "fehlt", folder_re, "trellis-cli"),
                             Path("/usr/bin/trellis-cli"))


if __name__ == "__main__":
    unittest.main()
