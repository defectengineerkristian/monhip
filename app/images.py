"""Bilder für Modelle mit Bildverständnis: prüfen, Vorschau, data-URL, Zwischenablage, Bildschirmfoto.
Vorschau und Zwischenablage unter Windows über PowerShell/System.Drawing, weil Tk kein JPG kann; unter Linux über
Pillow (Paket python3-pil) bzw. ImageMagick, Bildschirmfotos mit dem, was der Desktop mitbringt (grim,
gnome-screenshot, spectacle, scrot, ImageMagick).
"""

import base64
import struct
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import plattform
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
                           encoding=plattform.CONSOLE_ENCODING, errors="replace", timeout=60, creationflags=_NO_WINDOW)
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
    if not plattform.WINDOWS:
        w, h = _thumbnail(path, thumb, size)
        kind = "Bild (" + {".jpeg": "JPG"}.get(path.suffix.lower(), path.suffix[1:].upper()) + ")"
        return Document(path, kind, "", image=(w, h), thumb=thumb)
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


def pillow():
    """PIL.Image, wenn Pillow installiert ist (unter Linux für Vorschau und Bildbearbeitung), sonst None."""
    try:
        from PIL import Image
        return Image
    except ImportError:
        return None


def _thumbnail(path: Path, thumb: Path, size: int) -> tuple[int, int]:
    """Linux: PNG-Vorschau (höchstens size × size, nie vergrößert) mit Pillow, sonst ImageMagick → (Breite, Höhe)."""
    image = pillow()
    if image:
        try:
            with image.open(path) as img:
                w, h = img.size
                small = img.convert("RGBA") if img.mode not in ("RGB", "RGBA", "L", "LA") else img.copy()
            small.thumbnail((size, size), getattr(image, "Resampling", image).LANCZOS)
            small.save(thumb, "PNG")
            return w, h
        except (OSError, ValueError, image.DecompressionBombError):
            raise ValueError("Das Bild lässt sich nicht öffnen – Datei beschädigt?") from None
    magick = plattform.which("magick", "convert")
    if not magick:
        raise ValueError("Für Bilder braucht Monhip unter Linux Pillow (Paket python3-pil) oder ImageMagick.")
    try:
        r = subprocess.run([magick, f"{path}[0]", "-format", "%w %h\n", "-write", "info:-", "-thumbnail",
                            f"{size}x{size}>", f"png:{thumb}"], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
        w, h = (int(x) for x in r.stdout.split()[:2])
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ValueError("Das Bild lässt sich nicht öffnen – Datei beschädigt?") from None
    if not thumb.is_file():
        raise ValueError("Das Bild lässt sich nicht öffnen – Datei beschädigt?")
    return w, h


def png_size(path: Path) -> tuple[int, int]:
    """Breite und Höhe aus dem Kopf einer PNG-Datei (IHDR) – ohne sie ganz zu lesen."""
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise ValueError("kein PNG")
    return struct.unpack(">II", head[16:24])


def cleanup_temp(max_age_hours: float = 24):
    """Alte Vorschaubilder/Screenshots aus TEMP_DIR entfernen (gesendete Bilder liegen längst im Chat)."""
    limit = time.time() - max_age_hours * 3600
    for f in TEMP_DIR.rglob("*") if TEMP_DIR.is_dir() else []:  # auch teamwork/ (geteilte Bilder)
        try:
            if f.is_file() and f.stat().st_mtime < limit:
                f.unlink()
        except OSError:
            pass


_urls: dict[tuple, str] = {}  # (Pfad, Änderungszeit, Größe) → data-URL
_urls_lock = threading.Lock()   # Chat und eigene KI im Raum senden evtl. gleichzeitig
URL_CACHE_CHARS = 64 * 1024 * 1024


def data_url(path: Path) -> str:
    """Bild als data-URL für die OpenAI-kompatible Schnittstelle von llama-server (image_url). Zwischengespeichert:
    Jeder Schritt einer Antwort schickt alle Bilder des Verlaufs erneut (ein Bildschirmfoto kodieren ~12 ms)."""
    st = path.stat()
    key = (str(path), st.st_mtime_ns, st.st_size)
    with _urls_lock:
        url = _urls.get(key)
    if url is None:
        mime = SUFFIXES.get(path.suffix.lower(), "image/png")
        url = f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        with _urls_lock:
            _urls[key] = url
            while len(_urls) > 1 and sum(len(u) for u in _urls.values()) > URL_CACHE_CHARS:
                _urls.pop(next(iter(_urls)))  # die ältesten zuerst
    return url


def screenshot() -> tuple[Path, int, int]:
    """Bildschirmfoto des Hauptbildschirms als PNG in TEMP_DIR. Ergebnis: (Pfad, Breite, Höhe).
    SetProcessDPIAware, sonst nimmt PowerShell bei Windows-Skalierung nur einen Ausschnitt auf."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    target = TEMP_DIR / datetime.now().strftime("Bildschirmfoto %Y-%m-%d %H-%M-%S.png")
    if not plattform.WINDOWS:
        return _screenshot_linux(target)
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


# Linux: Programme für Bildschirmfotos (Name, Argumente vor der Zieldatei) – Wayland erlaubt nur die des Desktops
_SHOT_WAYLAND = (("grim", ()), ("gnome-screenshot", ("-f",)), ("spectacle", ("-b", "-n", "-o")))
_SHOT_X11 = (("import", ("-window", "root")), ("scrot", ("-o",)), ("maim", ()), ("gnome-screenshot", ("-f",)),
             ("spectacle", ("-b", "-n", "-o")))


def _screenshot_linux(target: Path) -> tuple[Path, int, int]:
    """Ganzer Bildschirm als PNG. X11: Pillow (ImageGrab) oder ein Programm, Wayland: grim, GNOME oder KDE."""
    image = None if plattform.WAYLAND else pillow()
    if image:
        try:
            from PIL import ImageGrab
            shot = ImageGrab.grab()
            shot.save(target, "PNG")
            return target, shot.width, shot.height
        except (OSError, ImportError):
            pass
    tools = _SHOT_WAYLAND if plattform.WAYLAND else _SHOT_X11
    for name, args in tools:
        exe = plattform.which(name)
        if not exe:
            continue
        try:
            subprocess.run([exe, *args, str(target)], capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
            w, h = png_size(target)
            return target, w, h
        except (OSError, subprocess.SubprocessError, ValueError):
            target.unlink(missing_ok=True)
    names = ", ".join(name for name, _ in tools)
    raise RuntimeError(f"Das Bildschirmfoto konnte nicht aufgenommen werden – dafür braucht es eines dieser "
                       f"Programme: {names}.")


def save_clipboard() -> Path | None:
    """Bild aus der Zwischenablage (z. B. Screenshot mit Win+Umschalt+S) als PNG speichern."""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    target = TEMP_DIR / datetime.now().strftime("Screenshot %Y-%m-%d %H-%M-%S.png")
    if not plattform.WINDOWS:
        import filedrop
        data = filedrop.clipboard_image_png()
        if not data:
            return None
        target.write_bytes(data)
        return target
    out = powershell(f"""
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
$img = [System.Windows.Forms.Clipboard]::GetImage()
if ($img) {{ $img.Save({_ps_str(target)}, [System.Drawing.Imaging.ImageFormat]::Png); $img.Dispose(); 'ok' }}""")
    return target if out.endswith("ok") and target.is_file() else None
