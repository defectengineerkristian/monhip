"""ROCm-Pakete: Indexauswahl, SHA-256, vollständige Host-/GPU-Daten, atomare Installation und Abbruch.
Die kleinen Test-Wheels enthalten Platzhalter, keine ausführbaren AMD-Bibliotheken. Ein nativer
Windows-/GPU-Test und die Prüfung des Live-AMD-Index sind davon unabhängig.
"""

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import rocm_packages as packages
import rocm_runtime as runtime
import sdcpp


def link(package, version="10.1.0", platform="win_amd64", digest="a" * 64, extra=""):
    name = f"{package.replace('-', '_')}-{version}-py3-none-{platform}.whl"
    fragment = f"#sha256={digest}" if digest is not None else ""
    return f'<a href="../../files/{name}{fragment}" {extra}>{name}</a>'


class Index(unittest.TestCase):
    def test_live_amd_index_format_without_hashes_uses_pinned_release_checksums(self):
        # Tatsächliche Linkform des stabilen AMD-Index vom 11.11.2026, einschließlich Weiterleitung.
        sizes = (776978384, 118645973, 314133708)
        def index(req, **_kw):
            project = req.full_url.rstrip("/").rsplit("/", 1)[-1]
            filename = project.replace("-", "_") + "-10.1.0-py3-none-win_amd64.whl"
            response = io.BytesIO(f'<html><body><a href="{filename}">{filename}</a></body></html>'.encode())
            response.geturl = lambda: "https://stable.repo.amd.com/rocm/core/whl-next/" + project + "/"
            return response
        with tempfile.TemporaryDirectory() as d, mock.patch.object(runtime, "MANAGED_DIR", Path(d)), \
                mock.patch.object(packages.urllib.request, "urlopen", side_effect=index), \
                mock.patch.object(packages.downloads, "head_size", side_effect=sizes):
            p = packages.plan("10.1.0")
        self.assertEqual(p["package_version"], "10.1.0")
        self.assertEqual(p["size"], sum(sizes))
        self.assertEqual(len(p["packages"]), 3)
        for item in p["packages"]:
            self.assertEqual(item["sha256"], packages.PINNED_SHA256[item["name"]])
            self.assertEqual(item["url"], "https://stable.repo.amd.com/rocm/core/whl-next/" +
                             item["package"] + "/" + item["name"])

    def test_pinned_fallback_does_not_accept_unknown_unhashed_wheels_or_invalid_explicit_hashes(self):
        for document in (link("rocm-sdk-core", version="10.1.0+unknown", digest=None),
                         link("rocm-sdk-core", digest=""), link("rocm-sdk-core", digest="invalid")):
            with self.subTest(document=document):
                self.assertEqual(packages.candidates("rocm-sdk-core", "10.1.0", document,
                                                     packages.INDEX + "rocm-sdk-core/"), {})
        document = '<a href="rocm_sdk_core-10.1.0-py3-none-win_amd64.whl">core</a>'
        for source in ("https://other.invalid/rocm/core/", "https://stable.repo.amd.com.other.invalid/rocm/core/",
                       "http://stable.repo.amd.com/rocm/core/"):
            self.assertEqual(packages.candidates("rocm-sdk-core", "10.1.0",
                                                document, source), {})

    def test_selects_only_matching_windows_artifacts_with_required_hashes(self):
        project = "rocm-sdk-libraries"
        document = "\n".join([
            link(project), link(project, version="10.2.0"), link(project, platform="linux_x86_64"),
            link("unrelated"), link(project, version="10.1.0+bad", extra='data-yanked=""'),
            link(project, version="10.1.0+nohash", digest=""),
            link(project, version="10.1.0+withdrawn", extra="data-yanked"),
        ])
        choices = packages.candidates(project, "10.1.0", document, packages.INDEX + project + "/")
        self.assertEqual(set(choices), {"10.1.0"})
        self.assertEqual(choices["10.1.0"]["sha256"], "a" * 64)
        self.assertTrue(choices["10.1.0"]["url"].startswith("https://stable.repo.amd.com/"))

    def test_runtime_plan_requires_one_common_package_release(self):
        def index(req, **_kw):
            project = req.full_url.rstrip("/").rsplit("/", 1)[-1]
            text = link(project, version="10.1.0+same")
            if project == packages.PACKAGES[0]:
                text += link(project, version="10.1.0+newer")
            response = io.BytesIO(text.encode())
            response.geturl = lambda: req.full_url
            return response
        with tempfile.TemporaryDirectory() as d, mock.patch.object(runtime, "MANAGED_DIR", Path(d)), \
                mock.patch.object(packages.urllib.request, "urlopen", side_effect=index), \
                mock.patch.object(packages.downloads, "head_size", return_value=100):
            p = packages.plan("10.1.0")
        self.assertEqual(p["package_version"], "10.1.0+same")
        self.assertEqual(p["size"], 300)
        self.assertEqual([v["package"] for v in p["packages"]], list(packages.PACKAGES))
        self.assertTrue(all("+same" in v["name"] for v in p["packages"]))

    def test_relative_artifact_links_use_the_redirect_destination(self):
        def redirected(req, **_kw):
            project = req.full_url.rstrip("/").rsplit("/", 1)[-1]
            response = io.BytesIO(link(project).encode())
            response.geturl = lambda: "https://stable.repo.amd.com/rocm/core/whl-next/" + project + "/"
            return response
        with tempfile.TemporaryDirectory() as d, mock.patch.object(runtime, "MANAGED_DIR", Path(d)), \
                mock.patch.object(packages.urllib.request, "urlopen", side_effect=redirected), \
                mock.patch.object(packages.downloads, "head_size", return_value=100):
            p = packages.plan("10.1.0")
        self.assertTrue(all(v["url"].startswith("https://stable.repo.amd.com/rocm/core/files/")
                            for v in p["packages"]))


class Installation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patch = mock.patch.object(runtime, "MANAGED_DIR", self.root / "installed")
        patch.start()
        self.addCleanup(patch.stop)
        self.stop = threading.Event()
        self.plan = self.build_plan()

    def build_plan(self, wrong_version=False, unsafe=None, kernels=True):
        contents = [
            {f"_rocm_sdk_core/bin/{name}": b"CORE" for name in runtime.REQUIRED[1:4]},
            {f"_rocm_sdk_libraries/bin/{name}": b"BLAS" for name in ("hipblas.dll", "rocblas.dll")},
            {"_rocm_sdk_libraries/bin/.kpack/blas-gfx1201.kpack": b"GPU KERNELS",
             "_rocm_sdk_libraries/lib/rocblas/library/TensileLibrary.dat": b"KERNEL DATABASE"} if kernels else {},
        ]
        result = []
        for i, (project, files) in enumerate(zip(packages.PACKAGES, contents)):
            name = f"{project.replace('-', '_')}-10.1.0-py3-none-win_amd64.whl"
            dest = self.root / name
            with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as z:
                version = "10.2.0" if wrong_version and i == 0 else "10.1.0"
                z.writestr(f"{project.replace('-', '_')}-10.1.0.dist-info/METADATA",
                           f"Metadata-Version: 2.1\nName: {project}\nVersion: {version}\n")
                for path, data in files.items():
                    z.writestr(path, data)
                if unsafe and i == 0:
                    z.writestr(unsafe, b"UNSAFE")
            result.append({"package": project, "name": name, "url": dest.as_uri(), "size": dest.stat().st_size,
                           "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()})
        return {"version": "10.1.0", "package_version": "10.1.0", "gfx": "gfx1201", "packages": result,
                "size": sum(v["size"] for v in result)}

    def test_real_download_hash_verification_and_full_layout_without_running_package_code(self):
        progress = []
        done = packages.install(self.plan, lambda d, n: progress.append((d, n)), self.stop)
        self.assertEqual(done, self.plan["size"])
        self.assertEqual(progress[-1], (done, done))
        folders = runtime.managed_dirs("10.1.0")
        self.assertEqual(len(folders), 2)
        self.assertTrue(runtime.available("10.1.0"))
        target = runtime.managed_root("10.1.0")
        self.assertEqual((target / "site/_rocm_sdk_libraries/bin/.kpack/blas-gfx1201.kpack").read_bytes(), b"GPU KERNELS")
        self.assertEqual((target / "site/_rocm_sdk_libraries/lib/rocblas/library/TensileLibrary.dat").read_bytes(),
                         b"KERNEL DATABASE")
        manifest = json.loads((target / "runtime.json").read_text())
        self.assertEqual(len(manifest["packages"]), 3)
        # Wiederholtes Laden/Einrichten verwendet die vollständige vorhandene Laufzeit.
        with mock.patch.object(packages.downloads, "download", side_effect=AssertionError("no redownload")):
            self.assertEqual(packages.install(self.plan, lambda *_: None, self.stop), 0)
            self.assertIsNone(packages.plan("10.1.0"))

    def test_integrity_failure_preserves_previous_files(self):
        target = runtime.managed_root("10.1.0")
        target.mkdir(parents=True)
        (target / "keep.txt").write_text("preserve")
        self.plan["packages"][1]["sha256"] = "0" * 64
        with self.assertRaises(RuntimeError):
            packages.install(self.plan, lambda *_: None, self.stop)
        self.assertEqual((target / "keep.txt").read_text(), "preserve")
        self.assertFalse(target.with_name(target.name + ".part").exists())
        self.assertFalse(runtime.managed_dirs("10.1.0"))

    def test_cancel_does_not_activate_a_partial_runtime(self):
        with self.assertRaises(RuntimeError):
            packages.install(self.plan, lambda *_: self.stop.set(), self.stop)
        self.assertFalse(runtime.managed_root("10.1.0").exists())
        self.assertFalse(runtime.managed_root("10.1.0").with_name("gfx1201.part").exists())

    def test_package_identity_and_gpu_payload_are_required(self):
        for options in ({"wrong_version": True}, {"kernels": False}):
            with self.subTest(options=options), self.assertRaises(RuntimeError):
                packages.install(self.build_plan(**options), lambda *_: None, self.stop)
            self.assertFalse(runtime.managed_dirs("10.1.0"))

    def test_archive_paths_cannot_escape_the_runtime(self):
        paths = ("../escape.dll", "/absolute.dll", "C:alternate-stream")
        if os.sep != "\\":  # unter Windows macht zipfile selbst aus „\“ ein „/“ – der Eintrag bleibt dann im Ordner
            paths += ("folder\\escape.dll",)
        for path in paths:
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                packages.install(self.build_plan(unsafe=path), lambda *_: None, self.stop)
        self.assertFalse((self.root / "escape.dll").exists())

    def test_native_engine_uses_new_runtime_without_changing_the_parent_environment(self):
        packages.install(self.plan, lambda *_: None, self.stop)
        engine = self.root / "engine/sd-b1068-rocm/sd-server.exe"
        engine.parent.mkdir(parents=True)
        engine.touch()
        for name in runtime.REQUIRED[:4]:
            (engine.parent / name).write_bytes(b"ENGINE")
        self.assertEqual(runtime.missing(engine), [])
        inherited = {"PATH": "original"}
        child = runtime.environment(engine, inherited)
        self.assertIn("_rocm_sdk_libraries", child["PATH"])
        self.assertEqual(inherited, {"PATH": "original"})

    def engine_plan(self):
        archive = self.root / "engine.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for name in (sdcpp.SERVER_EXE, *runtime.REQUIRED[:4]):
                z.writestr(name, b"ENGINE")
        model = self.root / "source-model.bin"
        model.write_bytes(b"MODEL")
        size = archive.stat().st_size
        return {"runtime": self.plan, "rocm_version": "10.1.0", "target": self.root / "server/sd-b1068-rocm",
                "program": [(archive.name, archive.as_uri(), size, hashlib.sha256(archive.read_bytes()).hexdigest())],
                "weights": [("model.bin", model.as_uri(), 5, self.root / "models/model.bin")],
                "size": self.plan["size"] + size + 5}

    def test_engine_runtime_and_models_share_one_progress_total_and_probe_before_success(self):
        p = self.engine_plan()
        progress = []

        def loaded(exe, inherited):
            self.assertEqual(exe, p["target"] / sdcpp.SERVER_EXE)
            self.assertEqual(runtime.missing(exe), [])
            self.assertEqual(runtime.version(exe), "10.1.0")
            self.assertTrue(runtime.managed_dirs("10.1.0"))
            return None  # Nur der native Windows-Lader wird simuliert, Download/Entpacken laufen wirklich.

        with mock.patch.object(sdcpp, "SERVER_DIR", self.root / "server"), \
                mock.patch.object(sdcpp.plattform, "WINDOWS", True), \
                mock.patch.object(runtime, "probe", side_effect=loaded) as probe:
            sdcpp.install(p, lambda d, n: progress.append((d, n)), self.stop)
        probe.assert_called_once()
        self.assertEqual((self.root / "models/model.bin").read_bytes(), b"MODEL")
        self.assertTrue(all(n == p["size"] for _, n in progress))
        self.assertEqual([d for d, _ in progress], sorted(d for d, _ in progress))
        self.assertEqual(progress[-1], (p["size"], p["size"]))

    def test_failed_loader_probe_keeps_previous_engine_and_does_not_download_models(self):
        p = self.engine_plan()
        previous = self.root / "server/sd-b1060-rocm"
        previous.mkdir(parents=True)
        (previous / sdcpp.SERVER_EXE).write_bytes(b"PREVIOUS")
        with mock.patch.object(sdcpp, "SERVER_DIR", self.root / "server"), \
                mock.patch.object(sdcpp.plattform, "WINDOWS", True), \
                mock.patch.object(runtime, "probe", return_value="Windows 126"), \
                self.assertRaisesRegex(RuntimeError, "126"):
            sdcpp.install(p, lambda *_: None, self.stop)
        self.assertEqual((previous / sdcpp.SERVER_EXE).read_bytes(), b"PREVIOUS")
        self.assertFalse((self.root / "models/model.bin").exists())


if __name__ == "__main__":
    unittest.main()
