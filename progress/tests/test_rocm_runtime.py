"""Windows-ROCm-Laufzeit und Regression des unvollständigen offiziellen b1068-ZIPs, ohne GPU oder Downloads."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import backend
import rocm_runtime
import sdcpp


class Runtime(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.servers = self.root / "server"
        self.native = self.servers / "sd-b1068-rocm" / sdcpp.SERVER_EXE
        self.native.parent.mkdir(parents=True)
        self.native.touch()
        # Tatsächlicher Inhalt des offiziellen, anhand der GitHub-SHA-256 geprüften b1068-ZIPs:
        for name in ("stable-diffusion.dll", "amdhip64_7.dll", "amd_comgr.dll", "rocm_kpack.dll"):
            (self.native.parent / name).touch()
        patches = [mock.patch.dict(os.environ, {"ProgramFiles": str(self.root / "Program Files")}, clear=True),
                   mock.patch.object(rocm_runtime, "MANAGED_DIR", self.root / "runtime"),
                   mock.patch.object(sdcpp, "SERVER_DIR", self.servers),
                   mock.patch.object(sdcpp.plattform, "WINDOWS", True),
                   # Windows liest die Architektur aus der (hier geleerten) Umgebung und merkt sie sich dann
                   mock.patch.object(sdcpp.platform, "machine", return_value="AMD64")]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def sdk(self, version):
        folder = Path(os.environ["ProgramFiles"]) / "AMD" / "ROCm" / version / "bin"
        folder.mkdir(parents=True)
        for name in rocm_runtime.REQUIRED[1:]:
            (folder / name).touch()
        return folder

    def test_official_zip_alone_is_not_a_ready_rocm_installation(self):
        self.assertEqual(rocm_runtime.missing(self.native), ["hipblas.dll", "rocblas.dll"])
        self.assertIsNone(sdcpp.find_server())
        with mock.patch.object(rocm_runtime.subprocess, "run") as run:
            self.assertIn("hipblas.dll", rocm_runtime.probe(self.native, os.environ))
        run.assert_not_called()  # kein fehlerhafter EXE-/DLL-Start und damit kein Windows-Systemdialog

    def test_matching_sdk_is_used_without_copying_or_mixing_versions(self):
        wrong = self.sdk("7.1.1")
        with mock.patch.dict(os.environ, {"HIP_PATH": str(wrong.parent)}):
            self.assertFalse(rocm_runtime.available("10.1.0"))
            self.assertIn("hipblas.dll", rocm_runtime.missing(self.native))
        correct = self.sdk("10.1.0")
        self.assertEqual(rocm_runtime.missing(self.native), [])
        self.assertEqual(sdcpp.find_server(), self.native)
        self.assertTrue(rocm_runtime.available("10.1.0"))
        inherited = {"PATH": "existing", "OTHER": "kept"}
        env = rocm_runtime.environment(self.native, inherited)
        self.assertEqual(env["PATH"].split(os.pathsep), [str(self.native.parent), str(correct), "existing"])
        self.assertEqual(env["HIP_PATH"], str(correct.parent))
        self.assertEqual(inherited, {"PATH": "existing", "OTHER": "kept"})
        self.assertFalse((self.native.parent / "hipblas.dll").exists())

    def test_engine_version_metadata_controls_sdk_selection(self):
        self.sdk("10.1.0")
        (self.native.parent / rocm_runtime.VERSION_FILE).write_text(json.dumps({"version": "10.2.0"}))
        self.assertIn("hipblas.dll", rocm_runtime.missing(self.native))
        self.sdk("10.2.0")
        self.assertEqual(rocm_runtime.missing(self.native), [])

    def test_engine_update_plans_runtime_repair_without_redownloading_the_engine_or_models(self):
        pick = sdcpp._pick
        release = {"tag_name": "master-1068-fc350be", "assets": [
            {"name": "sd-master-fc350be-bin-win-rocm-10.1.0-x64.zip", "browser_download_url": "https://example.invalid/rocm.zip", "size": 10},
            {"name": "sd-master-fc350be-bin-win-vulkan-x64.zip", "browser_download_url": "https://example.invalid/vulkan.zip", "size": 20},
        ]}
        with mock.patch.object(sdcpp, "MODEL_DIR", self.root / "models"), \
                mock.patch.object(sdcpp.rocm_packages, "plan", return_value={"size": 30}) as runtime_plan, \
                mock.patch.object(sdcpp, "_pick", side_effect=lambda r, v, c, **kw: pick(r, v, c, linux=False, **kw)), \
                mock.patch.object(sdcpp.llamacpp, "detect_gpu", return_value=("amd", "AMD Radeon RX 9070 XT", None)), \
                mock.patch.object(sdcpp.downloads, "get_json", return_value=[release]), \
                mock.patch.object(sdcpp.downloads, "head_size", side_effect=AssertionError("existing models")):
            for _, dest, _ in sdcpp.model_files("qwen-image-2.1-turbo"):
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(b"model")
            plan = sdcpp.plan("qwen-image-2.1-turbo", update=False)
        self.assertEqual(plan["target"], self.servers / "sd-b1068-rocm")
        self.assertEqual(plan["weights"], [])
        self.assertEqual(plan["program"], [])
        self.assertEqual(plan["runtime"], {"size": 30})
        self.assertEqual(plan["size"], 30)
        runtime_plan.assert_called_once_with("10.1.0")

    def test_transitive_dll_failure_is_reported_by_an_isolated_loader_probe(self):
        self.sdk("10.1.0")
        with mock.patch.object(rocm_runtime.plattform, "which", return_value="powershell"), \
                mock.patch.object(rocm_runtime.subprocess, "run", return_value=
                                  subprocess.CompletedProcess([], 1, "126\n", "")) as run:
            self.assertEqual(rocm_runtime.probe(self.native, os.environ), "Windows 126")
        args, opts = run.call_args.args[0], run.call_args.kwargs
        self.assertIn("SetErrorMode(0x8003)", args[-1])
        self.assertLess(args[-1].index("::SetErrorMode"), args[-1].index("::LoadLibraryEx"))
        self.assertNotIn(str(self.native.parent), args[-1])
        self.assertEqual(opts["env"]["MONHIP_ROCM_PROBE_DLL"], str(self.native.parent / "stable-diffusion.dll"))
        self.assertNotIn("MONHIP_ROCM_PROBE_DLL", os.environ)
        self.assertEqual(opts["timeout"], 30)

    def test_missing_runtime_selects_vulkan_and_qwen_uses_the_confirmed_workaround(self):
        vulkan = self.servers / "sd-b1068-vulkan" / sdcpp.SERVER_EXE
        vulkan.parent.mkdir()
        vulkan.touch()
        self.assertEqual(sdcpp.find_server(), vulkan)
        logs = []
        server = sdcpp.ImageServer(logs.append, lambda: "normal")
        proc = mock.Mock()
        proc.poll.return_value, proc.stdout = None, []
        with mock.patch.object(sdcpp, "model_ready", return_value=True), \
                mock.patch.object(sdcpp, "_free_port", return_value=54416), \
                mock.patch.object(sdcpp, "_request", return_value={"state": "ready"}), \
                mock.patch.object(backend, "_end_with_app", return_value=True), \
                mock.patch.object(sdcpp.llamacpp, "detect_gpu", return_value=("amd", "AMD Radeon RX 9070 XT", None)), \
                mock.patch.object(sdcpp.plattform, "popen", return_value=proc) as popen, \
                mock.patch.object(rocm_runtime, "probe") as probe:
            server.start("qwen-image-2.1-turbo", threading.Event())
        probe.assert_not_called()
        args = popen.call_args.args[0]
        self.assertEqual(args[0], str(vulkan))
        self.assertEqual(args[args.index("--backend") + 1], "vae=cpu")
        self.assertTrue(server.compatibility_active)
        self.assertTrue(server.ready_for("qwen-image-2.1-turbo"))
        self.assertTrue(any("hipblas.dll" in line for line in logs))

    def test_loader_failure_uses_vulkan_without_starting_the_broken_native_executable(self):
        self.sdk("10.1.0")
        vulkan = self.servers / "sd-b1068-vulkan" / sdcpp.SERVER_EXE
        vulkan.parent.mkdir()
        vulkan.touch()
        proc = mock.Mock()
        proc.poll.return_value, proc.stdout = None, []
        server = sdcpp.ImageServer(lambda _line: None)
        with mock.patch.object(sdcpp, "model_ready", return_value=True), \
                mock.patch.object(sdcpp, "_free_port", return_value=54416), \
                mock.patch.object(sdcpp, "_request", return_value={"state": "ready"}), \
                mock.patch.object(backend, "_end_with_app", return_value=True), \
                mock.patch.object(sdcpp.llamacpp, "detect_gpu", return_value=("amd", "AMD Radeon RX 9070 XT", None)), \
                mock.patch.object(sdcpp.plattform, "popen", return_value=proc) as popen, \
                mock.patch.object(rocm_runtime, "probe", return_value="Windows 126"):
            server.start("qwen-image-2.1-turbo", threading.Event())
        self.assertEqual(popen.call_count, 1)
        self.assertEqual(popen.call_args.args[0][0], str(vulkan))


if __name__ == "__main__":
    unittest.main()
