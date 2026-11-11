"""Windows-ROCm: vollständige, passende Laufzeit finden und DLLs ohne Systemdialog prüfen.

Die sd.cpp-ZIPs enthalten nicht sämtliche BLAS-Bibliotheken. Keine einzelnen DLLs aus anderen Versionen
zusammenkopieren: ein vollständiges SDK bleibt an seinem Ort, einschließlich seiner GPU-Kerneldateien.
"""

import json
import os
import re
import subprocess
from pathlib import Path

import plattform

REQUIRED = ("stable-diffusion.dll", "amdhip64_7.dll", "amd_comgr.dll", "rocm_kpack.dll", "hipblas.dll", "rocblas.dll")
VERSION_FILE = "monhip-rocm.json"
MANAGED_DIR = plattform.DATA_DIR / "server" / "rocm-runtime"


def managed_root(required_version: str) -> Path:
    if not re.fullmatch(r"\d+\.\d+\.\d+", required_version):
        raise ValueError("Invalid ROCm version")
    return MANAGED_DIR / required_version / "gfx1201"


def managed_dirs(required_version: str) -> list[Path]:
    root = managed_root(required_version)
    try:
        info = json.loads((root / "runtime.json").read_text(encoding="utf-8"))
        if info["version"] != required_version or info["gfx"] != "gfx1201" or not info["device_files"]:
            return []
        folders = [root / name for name in info["dll_dirs"]]
        kernels = [root / name for name in info["device_files"]]
        if any(not path.resolve().is_relative_to(root.resolve()) for path in folders + kernels):
            return []
        if not all(path.is_file() and path.stat().st_size for path in kernels):
            return []
        if not all(any((folder / name).is_file() for folder in folders) for name in REQUIRED[1:]):
            return []
        return folders
    except (OSError, ValueError, KeyError, TypeError):
        return []


def version(exe: Path) -> str:
    try:
        value = json.loads((exe.parent / VERSION_FILE).read_text(encoding="utf-8"))["version"]
        if isinstance(value, str) and re.fullmatch(r"\d+\.\d+\.\d+", value):
            return value
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # Bereits installierte Builds aus dem bisherigen Updater, noch ohne Versionsdatei.
    return "10.1.0"


def sdk_dirs(required_version: str) -> list[Path]:
    expected = tuple(int(v) for v in required_version.split("."))
    roots = [Path(v) for k, v in os.environ.items() if v and
             (k.upper() in ("HIP_PATH", "ROCM_PATH") or k.upper().startswith("HIP_PATH_"))]
    program_files = os.environ.get("ProgramFiles")
    if program_files:
        base = Path(program_files) / "AMD" / "ROCm"
        try:
            if base.is_dir():
                roots.extend(base.iterdir())
        except OSError:
            pass
    result = managed_dirs(required_version)
    for root in roots:
        if root.name.lower() == "bin":
            root = root.parent
        if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", root.name):
            continue
        actual = tuple(int(v) for v in root.name.split("."))
        if actual + (0,) * (3 - len(actual)) != expected:
            continue
        folder = root / "bin"
        if folder.is_dir() and folder not in result:
            result.append(folder)
    return result


def available(required_version: str) -> bool:
    folders = sdk_dirs(required_version)
    return all(any((folder / name).is_file() for folder in folders) for name in REQUIRED[1:])


def missing(exe: Path) -> list[str]:
    folders = [exe.parent, *sdk_dirs(version(exe))]
    return [name for name in REQUIRED if not any((folder / name).is_file() for folder in folders)]


def environment(exe: Path, inherited: dict) -> dict:
    result = inherited.copy()
    folders = sdk_dirs(version(exe))
    result["PATH"] = os.pathsep.join([str(exe.parent), *(str(p) for p in folders), inherited.get("PATH", "")])
    if folders:
        result["HIP_PATH"] = result["ROCM_PATH"] = str(folders[0].parent)
    return result


# Separater Prozess: keine Engine-DLLs im GUI-Prozess und kein modaler Windows-Fehlerdialog bei fehlenden
# transitiven Bibliotheken. Der Dateiname kommt über die Umgebung, nicht als PowerShell-Programmtext.
_PROBE = r'''
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class MonhipDllProbe {
    [DllImport("kernel32.dll")] public static extern uint SetErrorMode(uint mode);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern IntPtr LoadLibraryEx(string path, IntPtr file, uint flags);
    [DllImport("kernel32.dll")] public static extern bool FreeLibrary(IntPtr handle);
}
'@
[MonhipDllProbe]::SetErrorMode(0x8003) | Out-Null
$handle = [MonhipDllProbe]::LoadLibraryEx($env:MONHIP_ROCM_PROBE_DLL, [IntPtr]::Zero, 8)
if ($handle -eq [IntPtr]::Zero) {
    Write-Output ([Runtime.InteropServices.Marshal]::GetLastWin32Error())
    exit 1
}
[MonhipDllProbe]::FreeLibrary($handle) | Out-Null
exit 0
'''


def probe(exe: Path, inherited: dict) -> str | None:
    absent = missing(exe)
    if absent:
        return ", ".join(absent)
    powershell = plattform.which("powershell")
    if not powershell:
        return "PowerShell"
    env = environment(exe, inherited)
    env["MONHIP_ROCM_PROBE_DLL"] = str(exe.parent / "stable-diffusion.dll")
    try:
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", _PROBE], env=env,
                                cwd=str(exe.parent), capture_output=True, text=True, timeout=30,
                                creationflags=plattform.NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as error:
        return type(error).__name__
    if result.returncode:
        code = result.stdout.strip()
        return f"Windows {code}" if code.isdigit() else f"DLL-Prüfung ({result.returncode})"
    return None
