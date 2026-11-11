"""Passende Windows-ROCm-Laufzeit direkt von AMD installieren, ohne pip oder zusätzliche Python-Umgebung.

Core, Mathematikbibliotheken und GPU-Kernel werden als zusammengehörige offizielle Wheels entpackt.
Es wird kein Python-Code aus diesen Paketen ausgeführt. Die vollständige Verzeichnisstruktur bleibt erhalten.
"""

from email.parser import BytesParser
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import urllib.parse
import urllib.request
import zipfile

import downloads
from i18n import tr
import rocm_runtime

INDEX = "https://stable.repo.amd.com/rocm/whl-next/"
PACKAGES = ("rocm-sdk-core", "rocm-sdk-libraries", "rocm-sdk-device-gfx1201")

# Der stabile AMD-Index liefert für diese Wheels keinen SHA-256-Fragmentwert und keine
# separaten Prüfsummendateien. Am 11.11.2026 direkt per HTTPS vom offiziellen Index geladen,
# vollständig gegen die SHA-256-Einträge des Wheel-RECORD geprüft und hier festgehalten.
# Neue Dateien ohne Index-Hash brauchen zuerst eine solche Prüfung; kein Download ohne SHA-256.
PINNED_SHA256 = {
    "rocm_sdk_core-10.1.0-py3-none-win_amd64.whl":
        "b12f1c4cde14ed1cd8864006d17586c6b1e6a4e4695b9597cfe04ed7715e952f",
    "rocm_sdk_libraries-10.1.0-py3-none-win_amd64.whl":
        "0c34bafbb4aa626cc710d8b130bb314f591194c3d79eeb5892b755ea0be06159",
    "rocm_sdk_device_gfx1201-10.1.0-py3-none-win_amd64.whl":
        "56085e8f865b6b96c230fe8d1731074103553d0d958a31be13907d01e558fd0e",
}


def _normalized(name):
    return re.sub(r"[-_.]+", "-", name).lower()


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs = dict(attrs)
            if attrs.get("href"):
                self.links.append((attrs["href"], "data-yanked" in attrs))


def candidates(package: str, version: str, document: str, index_url: str) -> dict:
    """Passende Windows-Wheels mit Index-SHA-256 oder fest hinterlegtem SHA-256 für offizielle AMD-Dateien."""
    parser = _Links()
    parser.feed(document)
    result = {}
    for href, yanked in parser.links:
        if yanked:
            continue
        url, fragment = urllib.parse.urldefrag(urllib.parse.urljoin(index_url, href))
        if urllib.parse.urlsplit(url).scheme != "https":
            continue
        name = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1])
        if not name.endswith(".whl"):
            continue
        parts = name[:-4].split("-")
        if len(parts) not in (5, 6):
            continue
        distribution, release = parts[:2]
        python, abi, platform = parts[-3:]
        if (_normalized(distribution) != package or release.split("+", 1)[0] != version or
                "py3" not in python.split(".") or abi != "none" or "win_amd64" not in platform.split(".")):
            continue
        hashes = urllib.parse.parse_qs(fragment, keep_blank_values=True)
        digest = hashes.get("sha256", [""])[0]
        source = urllib.parse.urlsplit(url)
        if ("sha256" not in hashes and source.hostname == "stable.repo.amd.com" and
                source.path.startswith("/rocm/") and not source.username and not source.password):
            digest = PINNED_SHA256.get(name, "")
        if re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            result[release] = {"package": package, "name": name, "url": url, "sha256": digest.lower()}
    return result


def plan(version: str) -> dict | None:
    if rocm_runtime.managed_dirs(version):
        return None
    choices = []
    for package in PACKAGES:
        url = INDEX + package + "/"
        request = urllib.request.Request(url, headers={**downloads.UA, "Accept": "text/html"})
        with urllib.request.urlopen(request, timeout=30) as response:
            document = response.read(8 * 1024 * 1024 + 1)
            index_url = response.geturl()
        if len(document) > 8 * 1024 * 1024:
            raise RuntimeError(tr('Der AMD-Paketindex ist unerwartet groß.'))
        choices.append(candidates(package, version, document.decode("utf-8"), index_url))
    common = set(choices[0]).intersection(*(set(items) for items in choices[1:]))
    if not common:
        raise RuntimeError(tr('Keine zusammengehörige Windows-ROCm-Laufzeit {0} mit verifizierbaren Prüfsummen '
                              'für diese Grafikkarte gefunden. Bitte Monhip aktualisieren.', version))
    release = max(common, key=lambda v: (v == version, v))
    packages = [items[release] for items in choices]
    for package in packages:
        package["size"] = downloads.head_size(package["url"])
        if package["size"] <= 0:
            raise RuntimeError(tr('Die Größe des AMD-Pakets {0} konnte nicht ermittelt werden.', package["name"]))
    return {"version": version, "package_version": release, "gfx": "gfx1201", "packages": packages,
            "size": sum(p["size"] for p in packages)}


def _unpack(archive: Path, site: Path, package: dict, release: str, cancel) -> list[str]:
    with zipfile.ZipFile(archive) as wheel:
        entries = wheel.infolist()
        metadata = [item for item in entries if item.filename.endswith(".dist-info/METADATA")]
        if len(metadata) != 1 or metadata[0].file_size > 1024 * 1024:
            raise RuntimeError(tr('Ungültige AMD-Paketmetadaten: {0}', package["name"]))
        info = BytesParser().parsebytes(wheel.read(metadata[0]))
        if _normalized(info.get("Name", "")) != package["package"] or info.get("Version") != release:
            raise RuntimeError(tr('Das AMD-Paket {0} hat nicht die erwartete Version.', package["name"]))
        for item in entries:
            path = PurePosixPath(item.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in item.filename or ":" in item.filename or
                    stat.S_ISLNK(item.external_attr >> 16)):
                raise RuntimeError(tr('Ungültiger Pfad im AMD-Paket {0}.', package["name"]))
        need = sum(item.file_size for item in entries) + 256 * 1024 ** 2
        if need > shutil.disk_usage(site).free:
            raise RuntimeError(tr('Zu wenig Speicherplatz zum Entpacken der ROCm-Laufzeit.'))
        kernels = []
        for item in entries:
            if cancel.is_set():
                raise RuntimeError(tr('Abgebrochen.'))
            target = site / Path(*PurePosixPath(item.filename).parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with wheel.open(item) as source, target.open("wb") as dest:
                while chunk := source.read(1024 * 1024):
                    if cancel.is_set():
                        raise RuntimeError(tr('Abgebrochen.'))
                    dest.write(chunk)
            if (package["package"].startswith("rocm-sdk-device-") and item.file_size and
                    target.suffix.lower() in (".kpack", ".co", ".hsaco", ".dat")):
                kernels.append(target.relative_to(site.parent).as_posix())
        return kernels


def install(p: dict, progress, cancel) -> int:
    """Erst komplett prüfen und entpacken, dann atomar aktivieren. Eine vorhandene Laufzeit bleibt bei Fehlern erhalten."""
    if rocm_runtime.managed_dirs(p["version"]):
        return 0
    target = rocm_runtime.managed_root(p["version"])
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".part")
    if staging.exists():
        shutil.rmtree(staging)
    site = staging / "site"
    site.mkdir(parents=True)
    done, kernels = 0, []
    try:
        if p["size"] + 1024 ** 3 > shutil.disk_usage(staging).free:
            raise RuntimeError(tr('Zu wenig Speicherplatz für die ROCm-Laufzeit.'))
        for package in p["packages"]:
            if cancel.is_set():
                raise RuntimeError(tr('Abgebrochen.'))
            archive = staging / package["name"]
            done = downloads.download(package["url"], archive, progress, cancel, done, p["size"],
                                      sha256=package["sha256"])
            kernels.extend(_unpack(archive, site, package, p["package_version"], cancel))
            archive.unlink()
        folders = sorted({file.parent for file in site.rglob("*.dll")})
        missing = [name for name in rocm_runtime.REQUIRED[1:] if not any((folder / name).is_file() for folder in folders)]
        if missing or not kernels:
            raise RuntimeError(tr('Die heruntergeladene ROCm-Laufzeit ist unvollständig: {0}',
                                  ", ".join(missing) if missing else "gfx1201"))
        manifest = {"version": p["version"], "package_version": p["package_version"], "gfx": p["gfx"],
                    "dll_dirs": [folder.relative_to(staging).as_posix() for folder in folders],
                    "device_files": kernels,
                    "packages": [{k: package[k] for k in ("name", "sha256")} for package in p["packages"]]}
        (staging / "runtime.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        old = target.with_name(target.name + ".old")
        if old.exists():
            shutil.rmtree(old)
        if target.exists():
            target.rename(old)
        try:
            staging.rename(target)
        except BaseException:
            if old.exists():
                old.rename(target)
            raise
        if old.exists():
            shutil.rmtree(old)
        return done
    finally:
        if staging.exists():
            shutil.rmtree(staging)
