"""Baut das Linux-Paket (installer/linux/build-deb.sh) und prüft Inhalt und Steuerdaten – nur, wo dpkg-deb da ist:
python -m unittest tests.test_installer"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which("dpkg-deb") and shutil.which("sh"), "braucht dpkg-deb (Debian/Ubuntu)")
class DebPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        env = dict(os.environ, OUT=str(cls.dir), MONHIP_MAINTAINER="Test & Co <test@example.invalid>")
        r = subprocess.run(["sh", str(REPO / "installer" / "linux" / "build-deb.sh")], capture_output=True,
                           text=True, env=env, timeout=120)
        if r.returncode:
            raise AssertionError(r.stderr)
        cls.deb = Path(r.stdout.strip().splitlines()[-1])
        listing = subprocess.run(["dpkg-deb", "-c", str(cls.deb)], capture_output=True, text=True).stdout
        cls.files = {line.split()[-1].removeprefix("."): line.split()[0] for line in listing.splitlines()}
        cls.control = subprocess.run(["dpkg-deb", "-f", str(cls.deb)], capture_output=True, text=True).stdout

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_version_and_name(self):
        version = re.search(r'^VERSION = "([^"]+)"', (REPO / "app" / "monhip.py").read_text(encoding="utf-8"),
                            re.M).group(1)
        self.assertEqual(self.deb.name, f"monhip_{version}_all.deb")
        self.assertIn(f"Version: {version}\n", self.control)
        self.assertIn("Maintainer: Test & Co <test@example.invalid>\n", self.control)
        self.assertRegex(self.control, r"Installed-Size: \d+\n")

    def test_every_module_and_nothing_else(self):
        shipped = {p for p in self.files if p.startswith("/opt/monhip/app/") and not p.endswith("/")}
        expected = {f"/opt/monhip/app/{p.name}" for p in (REPO / "app").glob("*.py")} | {"/opt/monhip/app/monhip.ico"}
        self.assertEqual(shipped, expected)  # neue Module kommen von selbst mit, Caches und Tests nie
        self.assertIn("/opt/monhip/Monhip.pyw", self.files)
        self.assertFalse(any("__pycache__" in p or "/tests/" in p or p.endswith(".json") for p in self.files))

    def test_starter_menu_entry_and_icon(self):
        self.assertTrue(self.files["/usr/bin/monhip"].startswith("-rwxr-xr-x"))
        self.assertIn("/usr/share/applications/monhip.desktop", self.files)
        self.assertIn("/usr/share/icons/hicolor/256x256/apps/monhip.png", self.files)
        desktop = (REPO / "installer" / "linux" / "monhip.desktop").read_text(encoding="utf-8")
        for line in ("Exec=monhip", "Icon=monhip", "StartupWMClass=Monhip", "Type=Application"):
            self.assertIn(line + "\n", desktop)
        starter = (REPO / "installer" / "linux" / "monhip.sh").read_text(encoding="utf-8")
        self.assertIn("MONHIP_DATA", starter)
        self.assertIn("/opt/monhip/Monhip.pyw", starter)


if __name__ == "__main__":
    unittest.main()
