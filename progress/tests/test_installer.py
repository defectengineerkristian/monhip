"""Installer: Im Repository liegen nur die fertigen Dateien (installer/Monhip-Setup.exe, installer/monhip_<Version>_all.deb)
– passen sie zu VERSION? Mit den Quellen der Installer (nur auf dem Entwicklungsrechner): das Linux-Paket bauen
(installer/linux/build_deb.py) und prüfen, und ob der Windows-Installer alle Daten von Monhip kennt. Dazu: alle
Datenordner stehen in .gitignore. python -m unittest discover -s progress/tests -p test_installer.py"""

import importlib.util
import io
import re
import shutil
import stat
import tarfile
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INSTALLER = REPO / "installer"
VERSION = re.search(r'^VERSION = "([^"]+)"', (REPO / "app" / "monhip.py").read_text(encoding="utf-8"), re.M).group(1)


def read_deb(path: Path) -> tuple[str, dict[str, str]]:
    """(control, {Pfad: Rechte als Text}) eines .deb – ar-Archiv mit control.tar.xz und data.tar.xz."""
    data, pos, members = path.read_bytes(), 8, {}
    assert data[:8] == b"!<arch>\n", "kein ar-Archiv"
    while pos < len(data):
        head = data[pos:pos + 60]
        size = int(head[48:58])
        members[head[:16].decode("ascii").strip().rstrip("/")] = data[pos + 60:pos + 60 + size]
        pos += 60 + size + (size & 1)
    with tarfile.open(fileobj=io.BytesIO(members["control.tar.xz"]), mode="r:xz") as t:
        control = t.extractfile("./control").read().decode("utf-8")
    with tarfile.open(fileobj=io.BytesIO(members["data.tar.xz"]), mode="r:xz") as t:
        files = {i.name[1:] + ("/" if i.isdir() else ""): stat.filemode(i.mode | (0o40000 if i.isdir() else 0o100000))
                 for i in t.getmembers() if i.name != "."}
    return control, files


class ReleaseFiles(unittest.TestCase):
    """installer/ enthält genau die fertigen Installer zur aktuellen Version (läuft auch auf GitHub)."""

    def test_windows_installer(self):
        exe = INSTALLER / "Monhip-Setup.exe"
        self.assertTrue(exe.is_file(), "installer/Monhip-Setup.exe fehlt")
        self.assertEqual(exe.read_bytes()[:2], b"MZ")

    def test_linux_package_matches_version(self):
        debs = sorted(p.name for p in INSTALLER.glob("monhip_*_all.deb"))
        self.assertEqual(debs, [f"monhip_{VERSION}_all.deb"], "genau ein .deb, passend zu VERSION in app/monhip.py")
        control, files = read_deb(INSTALLER / debs[0])
        self.assertIn(f"Version: {VERSION}\n", control)
        self.assertIn("/opt/monhip/Monhip.pyw", files)


@unittest.skipUnless((INSTALLER / "linux" / "build_deb.py").is_file(), "Quellen der Installer nur auf dem Entwicklungsrechner")
class DebPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("build_deb", INSTALLER / "linux" / "build_deb.py")
        build_deb = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build_deb)
        cls.dir = Path(tempfile.mkdtemp())
        cls.deb = build_deb.build(cls.dir, "Test & Co <test@example.invalid>")
        cls.control, cls.files = read_deb(cls.deb)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_version_and_name(self):
        self.assertEqual(self.deb.name, f"monhip_{VERSION}_all.deb")
        self.assertIn(f"Version: {VERSION}\n", self.control)
        self.assertIn("Maintainer: Test & Co <test@example.invalid>\n", self.control)
        self.assertRegex(self.control, r"Installed-Size: \d+\n")

    def test_every_module_and_nothing_else(self):
        shipped = {p for p in self.files if p.startswith("/opt/monhip/app/") and not p.endswith("/")}
        expected = ({f"/opt/monhip/app/{p.name}" for p in (REPO / "app").glob("*.py")} | {"/opt/monhip/app/monhip.ico"}
                    | {f"/opt/monhip/app/fonts/{p.name}" for p in (REPO / "app" / "fonts").iterdir()})
        self.assertEqual(shipped, expected)  # neue Module kommen von selbst mit, Caches und Tests nie
        self.assertIn("/opt/monhip/Monhip.pyw", self.files)
        self.assertFalse(any("__pycache__" in p or "/tests/" in p or p.endswith(".json") for p in self.files))

    def test_starter_menu_entry_and_icon(self):
        self.assertTrue(self.files["/usr/bin/monhip"].startswith("-rwxr-xr-x"))
        self.assertIn("/usr/share/applications/monhip.desktop", self.files)
        self.assertIn("/usr/share/icons/hicolor/256x256/apps/monhip.png", self.files)
        desktop = (INSTALLER / "linux" / "monhip.desktop").read_text(encoding="utf-8")
        for line in ("Exec=monhip", "Icon=monhip", "StartupWMClass=Monhip", "Type=Application"):
            self.assertIn(line + "\n", desktop)
        starter = (INSTALLER / "linux" / "monhip.sh").read_text(encoding="utf-8")
        self.assertIn("MONHIP_DATA", starter)
        self.assertIn("/opt/monhip/Monhip.pyw", starter)


def app_data_names() -> set[str]:
    """Was Monhip in seinem Datenordner anlegt – aus dem Code gelesen (DATA_DIR / "x", APP_DIR / "x", app_dir / "x")."""
    names = set()
    for path in (REPO / "app").glob("*.py"):
        names |= set(re.findall(r'(?:DATA_DIR|APP_DIR|app_dir)\s*/\s*"([^"]+)"', path.read_text(encoding="utf-8")))
    return names


class DataNames(unittest.TestCase):
    def test_names_found_in_app(self):
        self.assertTrue({"config.json", "chats", "checkpoints", "modelle", "server"} <= app_data_names())

    def test_every_data_name_is_ignored_by_git(self):
        ignored = (REPO / ".gitignore").read_text(encoding="utf-8").split()
        self.assertEqual({n for n in app_data_names() if f"/{n}" not in ignored and f"/{n}/" not in ignored}, set())


@unittest.skipUnless((INSTALLER / "windows" / "src").is_dir(), "Quellen der Installer nur auf dem Entwicklungsrechner")
class WindowsInstallerData(unittest.TestCase):
    """Neue Datenordner von Monhip muss auch der Windows-Installer kennen: sonst ersetzt ein Update sie womöglich
    (Schutzliste) oder die Deinstallation lässt sie stehen (Bereiche)."""

    def setUp(self):
        src = INSTALLER / "windows" / "src"
        const = (src / "Const.cs").read_text(encoding="utf-8")
        self.protected = set(re.findall(r'"([^"]+)"', re.search(r"Protected = new string\[\]\s*\{(.*?)\}", const,
                                                                re.S).group(1)))
        uninstall = (src / "Uninstall.cs").read_text(encoding="utf-8")
        self.parts = set(re.findall(r'"([^"]+)"', " ".join(re.findall(r"Data\((.*?)\)\);", uninstall))))

    def test_every_data_name_is_protected(self):
        self.assertEqual(app_data_names() - self.protected, set())

    def test_every_data_name_can_be_uninstalled(self):
        self.assertEqual(app_data_names() - self.parts, set())


if __name__ == "__main__":
    unittest.main()
