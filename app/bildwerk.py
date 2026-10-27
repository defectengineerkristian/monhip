"""Viele Bilder auf einmal bearbeiten (Werkzeug bilder_bearbeiten): verkleinern, umwandeln, drehen – über
PowerShell und System.Drawing wie images.py, also ohne Zusatzpakete. Die Ergebnisse kommen in einen eigenen Ordner,
die Originale bleiben unverändert. Handyfotos werden vorher nach ihrer EXIF-Ausrichtung gedreht, sonst lägen sie
nach dem Verkleinern quer."""

import fnmatch
import os
import subprocess
import tempfile
from pathlib import Path

from i18n import tr
from speicher import size_text

SUFFIXES ={".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff"}
FORMATS = {"jpg": ".jpg", "jpeg": ".jpg", "png": ".png", "bmp": ".bmp", "gif": ".gif", "tif": ".tif",
           "tiff": ".tif"}
MAX_IMAGES = 500
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class BildError(Exception):
    """Fehler, den das Modell als verständlichen Satz bekommt (wie agent.ToolError)."""


def is_image(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in SUFFIXES


def collect(items, resolve) -> list[Path]:
    """Bilder aus Dateien, Ordnern (alle Bilder darin, ohne Unterordner) und Mustern wie 'Urlaub/*.jpg'.
    resolve(pfad) → Path in einem freigegebenen Ordner (Agent._path)."""
    items = [items] if isinstance(items, str) else list(items or [])
    if not items:
        raise BildError("dateien ist leer – Bilder, Ordner oder Muster wie 'Fotos/*.jpg' angeben.")
    found, seen = [], set()
    for item in items:
        raw = str(item).strip().strip('"')
        if any(c in raw for c in "*?["):
            folder, pattern = os.path.split(raw)
            base = resolve(folder or ".")
            hits = [p for p in base.iterdir() if is_image(p) and fnmatch.fnmatch(p.name.lower(), pattern.lower())]
        else:
            p = resolve(raw)
            if p.is_dir():
                hits = [c for c in p.iterdir() if is_image(c)]
            elif is_image(p):
                hits = [p]
            elif p.exists():
                raise BildError(f"{p.name} ist kein unterstütztes Bild (PNG, JPG, BMP, GIF, TIFF; kein HEIC/WebP).")
            else:
                raise BildError(f"{p} gibt es nicht.")
        for h in sorted(hits, key=lambda x: x.name.lower()):
            if os.path.normcase(str(h)) not in seen:
                seen.add(os.path.normcase(str(h)))
                found.append(h)
    if not found:
        raise BildError("Keine Bilder gefunden (unterstützt: PNG, JPG, BMP, GIF, TIFF).")
    if len(found) > MAX_IMAGES:
        raise BildError(f"{len(found)} Bilder – höchstens {MAX_IMAGES} je Aufruf.")
    return found


def options(max_kante=None, format="", qualitaet=None, drehen=None) -> dict:
    """Geprüfte Einstellungen; mindestens eine Änderung muss dabei sein."""
    fmt = str(format or "").strip().lower().lstrip(".")
    if fmt and fmt not in FORMATS:
        raise BildError(f"Format '{format}' gibt es nicht – möglich: jpg, png, bmp, gif, tif.")
    try:
        edge = int(max_kante) if max_kante not in (None, "", 0, "0") else 0
        quality = int(qualitaet) if qualitaet not in (None, "") else 85
        turn = int(drehen) if drehen not in (None, "") else 0
    except (TypeError, ValueError):
        raise BildError("max_kante, qualitaet und drehen müssen Zahlen sein.") from None
    if edge and not 16 <= edge <= 20000:
        raise BildError("max_kante zwischen 16 und 20000 Pixeln.")
    if not 1 <= quality <= 100:
        raise BildError("qualitaet zwischen 1 und 100.")
    if turn % 360 not in (0, 90, 180, 270):
        raise BildError("drehen nur um 90, 180 oder 270 Grad.")
    if not (edge or fmt or turn % 360 or qualitaet not in (None, "")):
        raise BildError("Nichts zu tun – max_kante, format, qualitaet oder drehen angeben.")
    return {"max": edge, "fmt": FORMATS.get(fmt, ""), "q": quality, "turn": turn % 360}


def describe(opts: dict) -> str:
    """Für den Bestätigungsdialog (in der Sprache der Oberfläche)."""
    parts = []
    if opts["max"]:
        parts.append(tr('längste Seite höchstens {0} Pixel', opts['max']))
    if opts["fmt"]:
        parts.append(tr('als {0} speichern', opts['fmt'][1:].upper()))
    if opts["turn"]:
        parts.append(tr('um {0}° im Uhrzeigersinn drehen', opts['turn']))
    parts.append(tr('JPG-Qualität {0}', opts['q']))
    return ", ".join(parts)


def plan(files: list[Path], target: Path, opts: dict) -> list[tuple[Path, Path]]:
    """[(Original, Ergebnis)] – Ergebnisnamen ohne Überschreiben: 'bild.jpg', sonst 'bild (2).jpg' …"""
    jobs, taken = [], set()
    for src in files:
        suffix = opts["fmt"] or (".jpg" if src.suffix.lower() == ".jpeg" else src.suffix.lower())
        n, dst = 1, target / (src.stem + suffix)
        while dst.exists() or os.path.normcase(str(dst)) in taken:
            n += 1
            dst = target / f"{src.stem} ({n}){suffix}"
        taken.add(os.path.normcase(str(dst)))
        jobs.append((src, dst))
    return jobs


def _ps(s) -> str:
    return "'" + str(s).replace("'", "''") + "'"  # PowerShell-Zeichenkette in einfachen Anführungszeichen


SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Drawing
$jpgCodec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq 'image/jpeg' }
$exifFlip = @{ 2 = 'RotateNoneFlipX'; 3 = 'Rotate180FlipNone'; 4 = 'Rotate180FlipX'; 5 = 'Rotate90FlipX';
               6 = 'Rotate90FlipNone'; 7 = 'Rotate270FlipX'; 8 = 'Rotate270FlipNone' }
function Edit-Image($src, $dst, $max, $quality, $turn) {
    $img = [System.Drawing.Image]::FromFile($src)
    try {
        if ($img.PropertyIdList -contains 0x0112) {
            $flip = $exifFlip[[int]$img.GetPropertyItem(0x0112).Value[0]]
            if ($flip) { $img.RotateFlip([System.Drawing.RotateFlipType]$flip) }
        }
        if ($turn) { $img.RotateFlip([System.Drawing.RotateFlipType]"Rotate$($turn)FlipNone") }
        $w = $img.Width; $h = $img.Height
        if ($max -gt 0 -and [Math]::Max($w, $h) -gt $max) {
            $scale = $max / [Math]::Max($w, $h)
            $w = [Math]::Max(1, [int][Math]::Round($w * $scale)); $h = [Math]::Max(1, [int][Math]::Round($h * $scale))
        }
        $bmp = New-Object System.Drawing.Bitmap $w, $h
        try {
            $g = [System.Drawing.Graphics]::FromImage($bmp)
            $g.InterpolationMode = 'HighQualityBicubic'; $g.SmoothingMode = 'HighQuality'; $g.PixelOffsetMode = 'HighQuality'
            $ext = [System.IO.Path]::GetExtension($dst).ToLower()
            if ($ext -eq '.jpg' -or $ext -eq '.bmp') { $g.Clear([System.Drawing.Color]::White) }  # Transparenz → Weiß
            $g.DrawImage($img, 0, 0, $w, $h)
            $g.Dispose()
            switch ($ext) {
                '.jpg' {
                    $params = New-Object System.Drawing.Imaging.EncoderParameters 1
                    $params.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter ([System.Drawing.Imaging.Encoder]::Quality), ([long]$quality)
                    $bmp.Save($dst, $jpgCodec, $params) }
                '.png' { $bmp.Save($dst, [System.Drawing.Imaging.ImageFormat]::Png) }
                '.bmp' { $bmp.Save($dst, [System.Drawing.Imaging.ImageFormat]::Bmp) }
                '.gif' { $bmp.Save($dst, [System.Drawing.Imaging.ImageFormat]::Gif) }
                default { $bmp.Save($dst, [System.Drawing.Imaging.ImageFormat]::Tiff) }
            }
        } finally { $bmp.Dispose() }
        "OK`t$src`t$w`t$h"
    } finally { $img.Dispose() }
}
"""


def script(jobs, opts: dict) -> str:
    calls = [f"try {{ Edit-Image {_ps(s)} {_ps(d)} {opts['max']} {opts['q']} {opts['turn']} }} "
             f"catch {{ \"ERR`t\" + {_ps(s)} + \"`t\" + $_.Exception.Message }}" for s, d in jobs]
    return SCRIPT + "\n".join(calls) + "\n"


def run(jobs, opts: dict) -> tuple[list[tuple[Path, Path, str]], list[str]]:
    """Führt das Skript aus (eine PowerShell für alle Bilder). → ([(Original, Ergebnis, 'B×H')], Fehler)"""
    if not jobs:
        return [], []
    jobs[0][1].parent.mkdir(parents=True, exist_ok=True)
    # als Datei mit BOM, damit Windows PowerShell 5.1 Umlaute in Pfaden richtig liest (Befehlszeile wäre zu kurz)
    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8-sig") as f:
        f.write(script(jobs, opts))
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
                            f.name], capture_output=True, timeout=min(1800, 30 + 3 * len(jobs)),
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    finally:
        Path(f.name).unlink(missing_ok=True)
    return parse(r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace"), jobs)


def parse(stdout: str, stderr: str, jobs) -> tuple[list[tuple[Path, Path, str]], list[str]]:
    target = {os.path.normcase(str(s)): d for s, d in jobs}
    done, errors = [], []
    for line in stdout.replace("\r\n", "\n").splitlines():
        parts = line.lstrip("﻿").split("\t")
        if parts[0] == "OK" and len(parts) == 4 and os.path.normcase(parts[1]) in target:
            done.append((Path(parts[1]), target[os.path.normcase(parts[1])], f"{parts[2]}×{parts[3]}"))
        elif parts[0] == "ERR" and len(parts) >= 3:
            errors.append(f"{Path(parts[1]).name}: {' '.join(parts[2:]).strip()}")
    if not done and not errors:
        errors.append("PowerShell lieferte kein Ergebnis: " + (stderr.strip()[:300] or "(keine Meldung)"))
    return done, errors


def summary(done, errors, target: Path) -> str:
    def size(paths):
        return sum(p.stat().st_size for p in paths if p.exists())
    before, after = size(s for s, _, _ in done), size(d for _, d, _ in done)
    lines = [f"{len(done)} Bilder bearbeitet → {target}"]
    if done:
        lines[0] += f" (vorher {size_text(before)}, jetzt {size_text(after)})"
        lines += [f"  {d.name}  {dims}" for _, d, dims in done[:10]]
        if len(done) > 10:
            lines.append(f"  …und {len(done) - 10} weitere")
    if errors:
        lines.append(f"{len(errors)} Fehler:")
        lines += [f"  {e}" for e in errors[:10]]
    return "\n".join(lines)
