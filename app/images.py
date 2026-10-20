"""Bilder für Modelle mit Bildverständnis: prüfen, Vorschau, data-URL, Zwischenablage, Bildschirmfoto.
Vorschau und Zwischenablage über PowerShell/System.Drawing, weil Tk kein JPG kann.
"""

import base64
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from documents import Document

SUFFIXES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".bmp": "image/bmp",
            ".gif": "image/gif"}
_MAGIC = (b"\x89PNG", b"\xff\xd8", b"BM", b"GIF8")
MAX_BYTES = 30 * 1024 * 1024
TEMP_DIR = Path(tempfile.gettempdir()) / "Monhip"  # Vorschaubilder/Screenshots vor dem Senden
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_image(path) -> bool:
    return Path(path).suffix.lower() in SUFFIXES


def _ps_str(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"  # PowerShell-Zeichenkette in einfachen Anführungszeichen


def powershell(script: str) -> str:
    """PowerShell-Skript ausführen (ohne Fenster) und die Ausgabe zurückgeben; bei Fehlern leer."""
    try:
        # PowerShell schreibt in der OEM-Codepage (Umlaute in Fehlermeldungen)
        r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True,
                           encoding="oem", errors="replace", timeout=60, creationflags=_NO_WINDOW)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def check(path: Path):
    """Bild, das llama.cpp lesen kann (Endung, Größe, Dateikopf)? Sonst ValueError mit verständlichem Text."""
    if not path.is_file():
        raise ValueError(f"{path} ist keine Datei.")
    if not is_image(path):
        raise ValueError("Nur PNG-, JPG-, BMP- und GIF-Bilder können angesehen werden.")
    nbytes = path.stat().st_size
    if nbytes > MAX_BYTES:
        raise ValueError(f"Das Bild ist zu groß ({nbytes / 1024 ** 2:.0f} MB, höchstens "
                         f"{MAX_BYTES // 1024 ** 2} MB).")
    with open(path, "rb") as f:
        if not f.read(4).startswith(_MAGIC):
            raise ValueError("Die Datei ist kein lesbares PNG-, JPG-, BMP- oder GIF-Bild.")


def read(path, thumb: Path, size: int) -> Document:
    """Prüft ein Bild und legt unter thumb ein PNG-Vorschaubild (höchstens size × size Pixel) an.
    Ergebnis: Document ohne Text, mit image = (Breite, Höhe)."""
    path = Path(path)
    check(path)
    thumb.parent.mkdir(parents=True, exist_ok=True)
    out = powershell(f"""
Add-Type -AssemblyName System.Drawing
$img = [System.Drawing.Image]::FromFile({_ps_str(path)})
try {{
  $w = $img.Width; $h = $img.Height
  $f = [Math]::Min(1.0, [Math]::Min({size} / $w, {size} / $h))
  $tw = [Math]::Max(1, [int]($w * $f)); $th = [Math]::Max(1, [int]($h * $f))
  $bmp = New-Object System.Drawing.Bitmap $tw, $th
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.DrawImage($img, 0, 0, $tw, $th)
  $bmp.Save({_ps_str(thumb)}, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  "$w $h"
}} finally {{ $img.Dispose() }}""")
    try:
        w, h = (int(x) for x in out.split()[-2:])
    except ValueError:
        raise ValueError("Das Bild lässt sich nicht öffnen – Datei beschädigt?") from None
    kind = "Bild (" + {".jpeg": "JPG"}.get(path.suffix.lower(), path.suffix[1:].upper()) + ")"
    return Document(path, kind, "", image=(w, h), thumb=thumb)


def cleanup_temp(max_age_hours: float = 24):
    """Alte Vorschaubilder/Screenshots aus TEMP_DIR entfernen (gesendete Bilder liegen längst im Chat)."""
    limit = time.time() - max_age_hours * 3600
    for f in TEMP_DIR.glob("*") if TEMP_DIR.is_dir() else []:
        try:
            if f.is_file() and f.stat().st_mtime < limit:
                f.unlink()
        except OSError:
            pass


def data_url(path: Path) -> str:
    """Bild als data-URL für die OpenAI-kompatible Schnittstelle von llama-server (image_url)."""
    mime = SUFFIXES.get(path.suffix.lower(), "image/png")
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def screenshot() -> tuple[Path, int, int]:
    """Bildschirmfoto des Hauptbildschirms als PNG in TEMP_DIR. Ergebnis: (Pfad, Breite, Höhe).
    SetProcessDPIAware, sonst nimmt PowerShell bei Windows-Skalierung nur einen Ausschnitt auf."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    target = TEMP_DIR / datetime.now().strftime("Bildschirmfoto %Y-%m-%d %H-%M-%S.png")
    out = powershell(f"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type 'using System.Runtime.InteropServices; public class Dpi {{ [DllImport("user32.dll")] public static extern bool SetProcessDPIAware(); }}'
[Dpi]::SetProcessDPIAware() | Out-Null
$r = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$b = New-Object System.Drawing.Bitmap $r.Width, $r.Height
$g = [System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen($r.Left, $r.Top, 0, 0, $b.Size)
$b.Save({_ps_str(target)}, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $b.Dispose()
"$($r.Width) $($r.Height)\"""")
    try:
        w, h = (int(x) for x in out.split()[-2:])
    except ValueError:
        raise RuntimeError("Das Bildschirmfoto konnte nicht aufgenommen werden.") from None
    return target, w, h


def save_clipboard() -> Path | None:
    """Bild aus der Zwischenablage (z. B. Screenshot mit Win+Umschalt+S) als PNG speichern."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    target = TEMP_DIR / datetime.now().strftime("Screenshot %Y-%m-%d %H-%M-%S.png")
    out = powershell(f"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$img = [System.Windows.Forms.Clipboard]::GetImage()
if ($img) {{ $img.Save({_ps_str(target)}, [System.Drawing.Imaging.ImageFormat]::Png); $img.Dispose(); 'ok' }}""")
    return target if out.endswith("ok") and target.is_file() else None
