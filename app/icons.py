"""Einheitliche Icons aus der Icon-Schrift von Windows: Segoe Fluent Icons (Windows 11), sonst Segoe MDL2 Assets.
Unter Linux dieselben Symbole aus Fluent UI System Icons (Microsoft, MIT-Lizenz): app/fonts/MonhipIcons.ttf enthält
genau die Zeichen aus FLUENT (gebaut mit tools/icon_font.py) und wird nur für Monhip bei fontconfig angemeldet.

Ein ttk-Element hat nur eine Schrift – deshalb zwei Wege:
- Textfelder und Zeichenflächen: Zeichen glyph(name) in der Schrift FAMILY (über einen Tag bzw. font=).
- ttk-Knöpfe, -Beschriftungen und Treeview-Zeilen: Bild über opts()/only()/image(), aus derselben Schrift gerendert
  (Windows: GDI, Linux: Pillow; Graustufen-Kantenglättung, Deckung als Alpha). retint() färbt alle Bilder beim
  Designwechsel neu – es bleiben dieselben PhotoImage-Objekte, die Knöpfe zeigen die neue Farbe also sofort.
Ohne Icon-Schrift liefert glyph() das frühere Ersatzzeichen, opts() nichts (nur Text) und only() das Ersatzzeichen
als Text."""

import base64
import ctypes
import ctypes.util
import os
import struct
import sys
import zlib
from ctypes import wintypes
from pathlib import Path

import tkinter as tk

WINDOWS = sys.platform == "win32"
_FONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
FONT_FILE = Path(__file__).resolve().parent / "fonts" / "MonhipIcons.ttf"  # Linux
LINUX_FAMILY = "Monhip Icons"

# Name → (Zeichen der Icon-Schrift, Ersatzzeichen ohne sie)
GLYPHS = {
    "blank": (" ", " "),  # leer – rückt z. B. eine Treeview-Zeile wie die mit Icon ein
    "add": ("\ue710", "+"), "attach": ("\ue723", "📎"), "branch": ("\uf003", "⎇"), "calc": ("\ue8ef", "="),
    "check": ("\ue73e", "✓"), "chev_down": ("\ue70d", "▾"), "chev_left": ("\ue76b", "‹"),
    "chev_right": ("\ue76c", "›"), "clock": ("\ue823", "⏰"), "close": ("\ue711", "✕"), "copy": ("\ue8c8", "⧉"),
    "delete": ("\ue74d", "✕"), "dot": ("\uea3b", "●"), "download": ("\ue896", "⬇"), "edit": ("\ue70f", "✎"),
    "folder": ("\ue8b7", "📁"), "globe": ("\ue774", "🌐"), "help": ("\ue9ce", "?"), "history": ("\ue81c", "≡"),
    "info": ("\ue946", "i"), "join": ("\ue8fa", "→"), "keyboard": ("\ue765", "⌨"),
    "list": ("\ue8fd", "☰"), "mic": ("\ue720", "🎤"),
    "page": ("\ue7c3", "▤"), "paste": ("\ue77f", "📋"),
    "person": ("\ue77b", "●"), "photo": ("\ue91b", "▣"), "pin": ("\ue718", "✦"),
    "play": ("\ue768", "▶"), "refresh": ("\ue72c", "↻"), "reply": ("\ue97a", "↳"), "robot": ("\ue99a", "✦"),
    "search": ("\ue721", "⌕"), "settings": ("\ue713", "⚙"), "shield": ("\uea18", "✓"), "star": ("\ue734", "★"),
    "stop": ("\uee95", "■"), "tasks": ("\ue9d5", "≡"), "terminal": ("\ue756", "❯"), "think": ("\uea80", "✻"),
    "undo": ("\ue7a7", "↶"), "upload": ("\ue898", "⬆"), "warning": ("\ue7ba", "!"), "cross": ("\ue711", "✗"),
}

# Linux: Name → Symbol aus Fluent UI System Icons (Größe 20, „regular“ bzw. „filled“). In MonhipIcons.ttf liegen sie in
# dieser Reihenfolge ab U+E000 – Reihenfolge nur am Ende erweitern und die Schrift dann neu bauen (tools/icon_font.py)
FLUENT = {
    "add": "add_20_regular", "attach": "attach_20_regular", "branch": "branch_fork_20_regular",
    "calc": "calculator_20_regular", "check": "checkmark_20_regular", "chev_down": "chevron_down_20_regular",
    "chev_left": "chevron_left_20_regular", "chev_right": "chevron_right_20_regular", "clock": "clock_20_regular",
    "close": "dismiss_20_regular", "copy": "copy_20_regular", "delete": "delete_20_regular",
    "dot": "circle_20_filled", "download": "arrow_download_20_regular", "edit": "edit_20_regular",
    "folder": "folder_20_regular", "globe": "globe_20_regular", "help": "question_circle_20_regular",
    "history": "history_20_regular", "info": "info_20_regular", "join": "person_add_20_regular",
    "keyboard": "keyboard_20_regular", "list": "text_bullet_list_ltr_20_regular", "mic": "mic_20_regular",
    "page": "document_20_regular", "paste": "clipboard_paste_20_regular", "person": "person_20_regular",
    "photo": "image_20_regular", "pin": "pin_20_regular", "play": "play_20_regular",
    "refresh": "arrow_clockwise_20_regular", "reply": "arrow_reply_20_regular", "robot": "bot_20_regular",
    "search": "search_20_regular", "settings": "settings_20_regular", "shield": "shield_20_regular",
    "star": "star_20_regular", "stop": "stop_20_filled", "tasks": "task_list_ltr_20_regular",
    "terminal": "window_console_20_regular", "think": "brain_circuit_20_regular", "undo": "arrow_undo_20_regular",
    "upload": "arrow_upload_20_regular", "warning": "warning_20_regular", "cross": "dismiss_20_regular",
}
_LINUX_CHARS = {name: chr(0xE000 + i) for i, name in enumerate(FLUENT)}


def _register_font(path: Path) -> bool:
    """Linux: Schriftdatei nur für Monhip bei fontconfig anmelden (FcConfigAppFontAddFile) – Tk findet sie dann unter
    ihrem Familiennamen, ohne dass sie im System installiert sein muss."""
    if not path.is_file():
        return False
    try:
        fc = ctypes.CDLL(ctypes.util.find_library("fontconfig") or "libfontconfig.so.1")
        fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        fc.FcConfigAppFontAddFile.restype = ctypes.c_int
        return bool(fc.FcConfigAppFontAddFile(None, os.fsencode(path)))
    except (OSError, AttributeError):
        return False


def _pillow_ok() -> bool:
    """Linux: Pillow mit FreeType da (zeichnet die Bilder) und die Icon-Schrift dabei?"""
    try:
        from PIL import features
        return FONT_FILE.is_file() and bool(features.check("freetype2"))
    except ImportError:
        return False


if WINDOWS:
    FAMILY = ("Segoe Fluent Icons" if (_FONTS / "SegoeIcons.ttf").exists() else
              "Segoe MDL2 Assets" if (_FONTS / "segmdl2.ttf").exists() else None)
    RENDER = FAMILY is not None             # Bilder per GDI aus der Icon-Schrift
else:
    FAMILY = LINUX_FAMILY if _register_font(FONT_FILE) else None  # setup() prüft, ob Tk sie wirklich findet
    RENDER = _pillow_ok()                   # Bilder per Pillow aus MonhipIcons.ttf

# Bildzeichen der Werkzeuge (agent.ICONS – kommen im Teamwork auch von anderen Rechnern, daher Zeichen statt Namen)
# und der aufklappbaren Blöcke → Icon-Name
SYMBOLS = {"🌐": "globe", "⌕": "search", "✎": "edit", "❯": "terminal", "▣": "photo", "✦": "pin", "⏰": "clock",
           "📁": "folder", "⬆": "upload", "⬇": "download", "📎": "attach", "⎇": "branch", "☰": "list", "↶": "undo",
           "=": "calc", "⚙": "settings", "📋": "paste", "▤": "page", "✻": "think", "≡": "history",
           "⌨": "keyboard"}

# Segoe MDL2 Assets (Windows 10) kennt einzelne Zeichen nicht oder anders
_MDL2 = {"stop": "\ue71a"}

_root: tk.Misc | None = None
_scale = 1.0
_colors = {"fg": "#1b1b1b", "muted": "#6b6b6b", "accent": "#0b63c5", "accent_fg": "#1b1b1b",
           "ok": "#26a269", "error": "#c01c28", "warn": "#a15c00"}
_cover: dict[tuple[str, int], bytes] = {}            # (Name, Pixel) → Deckung je Pixel
_images: dict[tuple, tk.PhotoImage] = {}  # (Name, Farbrolle, Pixel, Einzug, Rand oben) → Bild


def setup(root: tk.Misc, scale: float):
    """Einmal beim Start (ThemeManager): Wurzelfenster für die Bilder und Windows-Skalierung. Linux: Findet Tk die
    angemeldete Icon-Schrift nicht, gibt es in Textfeldern die Ersatzzeichen statt leerer Kästchen."""
    global _root, _scale, FAMILY
    _root, _scale = root, scale
    if not WINDOWS and FAMILY:
        from tkinter import font as tkfont
        try:
            if FAMILY not in tkfont.families(root):
                FAMILY = None
        except tk.TclError:
            FAMILY = None


def _char(name: str) -> str:
    if not WINDOWS:
        return _LINUX_CHARS.get(name, " ")  # „blank“: Leerzeichen
    return _MDL2.get(name, GLYPHS[name][0]) if FAMILY == "Segoe MDL2 Assets" else GLYPHS[name][0]


def glyph(name: str) -> str:
    """Zeichen für Textfelder/Zeichenflächen – mit der Schrift FAMILY (ohne Icon-Schrift: das Ersatzzeichen)."""
    return _char(name) if FAMILY else GLYPHS[name][1]


def symbol(char: str) -> tuple[str, bool]:
    """Werkzeug-/Block-Bildzeichen → (Zeichen, ist Icon). Unbekannte Zeichen bleiben, wie sie sind."""
    name = SYMBOLS.get(char)
    return (_char(name), True) if name and FAMILY else (char, False)


def image(name: str, role: str = "fg", size: int = 16, indent: int = 0, lower: float = 0) -> tk.PhotoImage | None:
    """Icon als Bild (size bei 100 % Skalierung) in der Farbe der Rolle (fg, muted, accent, accent_fg, ok, …).
    indent: durchsichtiger Rand links (Pixel bei 100 %) – rückt z. B. eine Treeview-Zeile ein.
    lower: Icon so viele Pixel (bei 100 %) tiefer, über einen durchsichtigen Rand oben. Tk zentriert Bild und
    Textzeile gegeneinander; bei Text ab 10 pt ist die Zeile höher als das Icon, und die Buchstaben sitzen unter
    ihrer Mitte – ohne lower stünde das Icon dann zu hoch (Seitenleiste: 1,5 px)."""
    if not RENDER or _root is None:
        return None
    px = max(8, round(size * _scale))
    pad, top = round(indent * _scale), round(2 * lower * _scale)
    key = (name, role, px, pad, top)
    img = _images.get(key)
    if img is None:
        img = _images[key] = tk.PhotoImage(master=_root, data=_png(name, px, _colors[role], pad, top),
                                           format="png")
    return img


def spec(name: str, role: str = "fg", size: int = 16, disabled: str | None = "muted", active: str | None = None,
         lower: float = 0):
    """Bild-Angabe für ttk (-image): normal, gesperrt und ggf. beim Darüberfahren in eigener Farbe."""
    img = image(name, role, size, lower=lower)
    if img is None:
        return None
    states = []
    if disabled and disabled != role:
        states += ["disabled", image(name, disabled, size, lower=lower)]
    if active and active != role:
        states += ["active", image(name, active, size, lower=lower)]
    return (img, *states) if states else img


def opts(name: str, role: str = "fg", size: int = 16, **kw) -> dict:
    """Optionen für einen ttk-Knopf/-Label mit Icon links vom Text (ohne Icon-Schrift: nur Text)."""
    s = spec(name, role, size, **kw)
    return {"image": s, "compound": "left"} if s else {}


def only(name: str, role: str = "fg", size: int = 16, **kw) -> dict:
    """Optionen für einen ttk-Knopf nur mit Icon (ohne Icon-Schrift: das Ersatzzeichen als Text)."""
    s = spec(name, role, size, **kw)
    return {"image": s, "compound": "image", "text": ""} if s else {"text": GLYPHS[name][1], "image": ""}


def retint(colors: dict):
    """Neue Farben je Rolle (Designwechsel): alle bisher erzeugten Bilder neu malen."""
    _colors.update(colors)
    for (name, role, px, pad, top), img in _images.items():
        img.configure(data=_png(name, px, _colors[role], pad, top), format="png")


def _png(name: str, px: int, color: str, pad: int = 0, top: int = 0) -> str:
    """PNG (RGBA, base64): Farbe überall, Deckung als Alpha; pad Pixel links und top Pixel oben durchsichtig."""
    cover = _cover.get((name, px))
    if cover is None:
        cover = _cover[(name, px)] = (_render if WINDOWS else _render_pillow)(_char(name), px)
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    rows = (b"\0" + bytes(4 * (pad + px))) * top + b"".join(
        b"\0" + bytes(4 * pad) + b"".join(bytes((r, g, b, a)) for a in cover[y * px:(y + 1) * px]) for y in range(px))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", pad + px, top + px, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
    return base64.b64encode(data).decode("ascii")


_gdi = None


def _gdi32():
    global _gdi
    if _gdi is None:
        g = ctypes.windll.gdi32
        g.CreateCompatibleDC.restype = ctypes.c_void_p
        g.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
        g.CreateFontW.restype = ctypes.c_void_p
        g.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
        g.SelectObject.restype = ctypes.c_void_p
        g.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        g.CreateDIBSection.restype = ctypes.c_void_p
        g.CreateDIBSection.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, wintypes.DWORD]
        g.GetTextExtentPoint32W.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int,
                                            ctypes.POINTER(wintypes.SIZE)]
        g.TextOutW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
        g.SetTextColor.argtypes = [ctypes.c_void_p, wintypes.DWORD]
        g.SetBkMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        g.DeleteObject.argtypes = [ctypes.c_void_p]
        g.DeleteDC.argtypes = [ctypes.c_void_p]
        _gdi = g
    return _gdi


def _render(char: str, px: int) -> bytes:
    """Deckung 0–255 je Pixel (px × px, Zeichen mittig): weiß auf schwarz gezeichnet, Rotkanal = Deckung.
    Graustufen statt ClearType – die Farbsäume von ClearType passen nur auf eine feste Hintergrundfarbe."""
    g = _gdi32()
    dc = g.CreateCompatibleDC(None)
    bits = ctypes.c_void_p()
    header = ctypes.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, px, -px, 1, 32, 0, 0, 0, 0, 0, 0))
    bmp = g.CreateDIBSection(dc, header, 0, ctypes.byref(bits), None, 0)
    font = g.CreateFontW(-px, 0, 0, 0, 400, 0, 0, 0, 1, 0, 0, 4, 0, FAMILY)  # 4 = ANTIALIASED_QUALITY
    try:
        old_bmp, old_font = g.SelectObject(dc, bmp), g.SelectObject(dc, font)
        ctypes.memset(bits, 0, px * px * 4)
        size = wintypes.SIZE()
        g.GetTextExtentPoint32W(dc, char, len(char), ctypes.byref(size))
        g.SetBkMode(dc, 1)  # TRANSPARENT
        g.SetTextColor(dc, 0xFFFFFF)
        g.TextOutW(dc, (px - size.cx) // 2, (px - size.cy) // 2, char, len(char))
        ctypes.windll.gdi32.GdiFlush()
        data = ctypes.string_at(bits, px * px * 4)
        g.SelectObject(dc, old_font)
        g.SelectObject(dc, old_bmp)
    finally:
        g.DeleteObject(font)
        g.DeleteObject(bmp)
        g.DeleteDC(dc)
    return data[2::4]


_pil_fonts: dict = {}


def _render_pillow(char: str, px: int) -> bytes:
    """Linux: wie _render, aber mit Pillow (FreeType) aus MonhipIcons.ttf – Zeichen mittig nach seinem Umriss."""
    from PIL import Image, ImageDraw, ImageFont
    font = _pil_fonts.get(px)
    if font is None:
        font = _pil_fonts[px] = ImageFont.truetype(str(FONT_FILE), px)
    img = Image.new("L", (px, px), 0)
    if char.strip():
        left, top, right, bottom = font.getbbox(char)
        ImageDraw.Draw(img).text((round((px - (right - left)) / 2 - left), round((px - (bottom - top)) / 2 - top)),
                                 char, font=font, fill=255)
    return img.tobytes()
