"""Eigene Bedienelemente: Felder mit einfärbbarem Scrollbalken, abgerundete Rechtecke, ModeSwitch."""

import math
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from themes import mix_hex


def scrolled(parent, widget=tk.Text, **kw):
    """Text- oder Listenfeld mit ttk-Scrollbalken (der native lässt sich nicht einfärben) → (Rahmen, Feld)."""
    frame = ttk.Frame(parent)
    w = widget(frame, **kw)
    sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=w.yview)
    w.configure(yscrollcommand=sb.set)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    w.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    return frame, w


def _corners(master, cache: dict, r: int, fill: str, under: str) -> list:
    """Kantengeglättete Viertelkreise (oben links, oben rechts, unten links, unten rechts)."""
    key = (r, fill, under)
    if key not in cache:
        imgs = []
        for cx, cy in ((r, r), (0, r), (r, 0), (0, 0)):
            img = tk.PhotoImage(master=master, width=r, height=r)
            rows = []
            for y in range(r):
                row = [mix_hex(under, fill, r - math.hypot(x + 0.5 - cx, y + 0.5 - cy) + 0.5) for x in range(r)]
                rows.append("{" + " ".join(row) + "}")
            img.put(" ".join(rows))
            imgs.append(img)
        cache[key] = imgs
    return cache[key]


def rounded(canvas: tk.Canvas, cache: dict, x: float, y: float, w: float, h: float, r: int, fill: str, under: str,
            tags=()):
    """Abgerundetes Rechteck mit glatten Ecken auf einem Canvas."""
    x, y, w, h = round(x), round(y), round(w), round(h)
    r = max(1, min(r, w // 2, h // 2))
    canvas.create_rectangle(x + r, y, x + w - r, y + h, fill=fill, outline="", tags=tags)
    canvas.create_rectangle(x, y + r, x + w, y + h - r, fill=fill, outline="", tags=tags)
    nw, ne, sw, se = _corners(canvas, cache, r, fill, under)
    canvas.create_image(x, y, image=nw, anchor="nw", tags=tags)
    canvas.create_image(x + w - r, y, image=ne, anchor="nw", tags=tags)
    canvas.create_image(x, y + h - r, image=sw, anchor="nw", tags=tags)
    canvas.create_image(x + w - r, y + h - r, image=se, anchor="nw", tags=tags)


class ModeSwitch(tk.Canvas):
    """Umschalter: Segmente nebeneinander, die Markierung gleitet beim Wechsel weich zur Auswahl."""

    DURATION = 0.18  # Sekunden für das Gleiten

    def __init__(self, master, items: list[tuple[str, str]], command, scale: float = 1.0):
        self.s = scale
        super().__init__(master, height=round(30 * scale), highlightthickness=0, borderwidth=0, cursor="hand2")
        self.items, self.command = items, command
        self.value: str | None = None
        self.hover: str | None = None
        self.col = {"bg": "#1f1e1d", "track": "#2b2a28", "pill": "#383733", "border": "#d97757",
                    "fg": "#ece9e1", "muted": "#9d998e"}
        self.f_on = tkfont.Font(root=self, family="Segoe UI", size=9, weight="bold")
        self.f_off = tkfont.Font(root=self, family="Segoe UI", size=9)
        self._pill: tuple[float, float] | None = None   # aktuelle Position (x, Breite) der Markierung
        self._anim = None
        self._cache: dict = {}
        self.bind("<Configure>", lambda e: self._redraw(snap=True))
        self.bind("<Button-1>", self._on_click)
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda e: self._set_hover(None))

    # ------------------------------------------------------------ Außen

    def set_colors(self, **colors):
        self.col.update(colors)
        self._cache.clear()
        self.configure(background=self.col["bg"])
        self._redraw()

    def select(self, value: str, animate: bool = True):
        if value == self.value and self._pill:
            return
        self.value = value
        target = self._target()
        if not animate or not self._pill or not target or not self.winfo_ismapped():
            self._pill = target
            self._redraw()
            return
        start, t0 = self._pill, time.monotonic()
        if self._anim:
            self.after_cancel(self._anim)

        def step():
            t = min(1.0, (time.monotonic() - t0) / self.DURATION)
            k = 1 - (1 - t) ** 3  # sanft abbremsen
            goal = self._target() or start
            self._pill = (start[0] + (goal[0] - start[0]) * k, start[1] + (goal[1] - start[1]) * k)
            self._redraw()
            self._anim = self.after(12, step) if t < 1 else None

        step()

    # ------------------------------------------------------------ Aufteilung & Zeichnen

    def _segments(self) -> list[tuple[str, float, float]]:
        """[(Schlüssel, x, Breite)] – Breite nach Textlänge, zusammen so breit wie das Canvas."""
        w = self.winfo_width()
        if w <= 1:
            return []
        pad = 3 * self.s
        natural = [self.f_on.measure(label) + 20 * self.s for _, label in self.items]
        factor = (w - 2 * pad) / sum(natural)
        out, x = [], pad
        for (key, _), n in zip(self.items, natural):
            out.append((key, x, n * factor))
            x += n * factor
        return out

    def _target(self) -> tuple[float, float] | None:
        for key, x, w in self._segments():
            if key == self.value:
                return x, w
        return None

    def _redraw(self, snap: bool = False):
        if snap and not self._anim:
            self._pill = self._target() or self._pill
        self.delete("all")
        w, h, c, s = self.winfo_width(), self.winfo_height(), self.col, self.s
        if w <= 1:
            return
        rounded(self, self._cache, 0, 0, w, h, round(9 * s), c["track"], c["bg"])
        if self._pill:
            x, pw = self._pill
            inset = 3 * s
            rounded(self, self._cache, x, inset, pw, h - 2 * inset, round(7 * s), c["border"], c["track"])
            rounded(self, self._cache, x + 1, inset + 1, pw - 2, h - 2 * inset - 2, round(6 * s), c["pill"],
                    c["border"])
        for key, x, sw in self._segments():
            label = dict(self.items)[key]
            on = key == self.value
            color = c["fg"] if on or key == self.hover else mix_hex(c["muted"], c["fg"], 0.15)
            self.create_text(x + sw / 2, h / 2, text=label, fill=color, font=self.f_on if on else self.f_off)

    # ------------------------------------------------------------ Maus

    def _key_at(self, x: float) -> str | None:
        for key, sx, sw in self._segments():
            if sx <= x < sx + sw:
                return key
        return None

    def _on_click(self, e):
        key = self._key_at(e.x)
        if key and key != self.value:
            self.command(key)

    def _on_motion(self, e):
        self._set_hover(self._key_at(e.x))

    def _set_hover(self, key):
        if key != self.hover:
            self.hover = key
            self._redraw()
