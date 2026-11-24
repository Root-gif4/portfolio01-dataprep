"""色つきカードと棒グラフ（追加のライブラリを使わず tk.Canvas で描く）。

どれも大きさが変わるたびに描き直す。
"""

from __future__ import annotations

import math
import tkinter as tk
import tkinter.font as tkfont
from typing import Callable, Sequence

from . import theme

Number = float | int


def fmt_number(v: Number) -> str:
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.1f}"
    return f"{int(v):,}"


def nice_ticks(vmax: float, count: int = 5) -> list[float]:
    """0 から vmax までの、きりのよい目盛り。"""
    if vmax <= 0:
        return [0, 1]
    raw = vmax / count
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    n = math.ceil(vmax / step - 1e-9)
    return [step * i for i in range(n + 1)]


def _fit(text: str, font: tkfont.Font, width: int) -> str:
    """幅に入らない文字は「…」で切る。"""
    if font.measure(text) <= width:
        return text
    while text and font.measure(text + "…") > width:
        text = text[:-1]
    return text + "…"


class _CanvasBox(tk.Canvas):
    def __init__(self, master, height: int, **kw):
        super().__init__(master, height=height, background=theme.BG, highlightthickness=0, borderwidth=0, **kw)
        self.bind("<Configure>", lambda e: self.redraw())
        self.after_idle(self.redraw)
        theme.on_change(self._recolor)

    def _recolor(self) -> None:
        self.configure(background=theme.BG)
        self.redraw()

    def redraw(self) -> None:  # 子クラスで描く
        raise NotImplementedError


class GradientCard(_CanvasBox):
    """角の丸いグラデーションのカード。見出し・大きな文字・項目（2列）を出す。"""

    def __init__(self, master, colors: tuple[str, str], height: int = 120, radius: int = 14, **kw):
        super().__init__(master, height=height, **kw)
        self.colors = colors
        self.radius = radius
        self.caption = ""
        self.title = ""
        self.subtitle = ""
        self.metrics: list[tuple[str, str, str | None]] = []
        self.f_caption = tkfont.Font(family=theme.FAMILY, size=9, weight="bold")
        self.f_title = tkfont.Font(family=theme.FAMILY, size=16, weight="bold")
        self.f_label = tkfont.Font(family=theme.FAMILY, size=8)
        self.f_value = tkfont.Font(family=theme.FAMILY, size=13, weight="bold")
        self.f_sub = tkfont.Font(family=theme.FAMILY, size=9)

    def set(self, caption: str = "", title: str = "", subtitle: str = "",
            metrics: Sequence[tuple[str, str, str | None]] = (), colors: tuple[str, str] | None = None) -> None:
        """metrics は (見出し, 値, 値の色 or None) の並び。2列で並べる。"""
        self.caption, self.title, self.subtitle = caption, title, subtitle
        self.metrics = list(metrics)
        if colors:
            self.colors = colors
        self.redraw()

    def _needed_height(self) -> int:
        """中身が入る高さ（フォントの大きさから計算する。画面の拡大率が違っても重ならないように）。"""
        ls = lambda f: f.metrics("linespace")
        h = 16
        if self.caption:
            h += ls(self.f_caption) + 4
        if self.title:
            h += ls(self.f_title) + 2
        if self.subtitle:
            h += ls(self.f_sub) + 2
        rows = (len(self.metrics) + 1) // 2
        if rows:
            h += 8 + rows * (ls(self.f_label) + ls(self.f_value) + 4) + (rows - 1) * 14
        return h + 16

    def redraw(self) -> None:
        needed = self._needed_height()
        if int(self.cget("height")) != needed:
            self.configure(height=needed)  # 大きさが変わると <Configure> でもう一度呼ばれる
        self.delete("all")
        w, h, r = self.winfo_width(), self.winfo_height(), self.radius
        if w < 20 or h < 20:
            return
        c1, c2 = self.colors
        for x in range(w):
            # 角を丸くするため、端の近くは上下を少し縮めて線を引く
            dx = min(x, w - 1 - x)
            inset = r - math.sqrt(max(0.0, r * r - (r - dx) ** 2)) if dx < r else 0
            self.create_line(x, inset, x, h - inset, fill=theme.mix(c1, c2, x / max(1, w - 1)))
        pad = 20
        inner = w - pad * 2
        y = 16
        for text, font, color, gap in ((self.caption, self.f_caption, "#ffffff", 4),
                                       (self.title, self.f_title, "#ffffff", 2),
                                       (self.subtitle, self.f_sub, "#f1f1f7", 2)):
            if text:
                self.create_text(pad, y, text=_fit(text, font, inner), anchor="nw", fill=color, font=font)
                y += font.metrics("linespace") + gap
        if not self.metrics:
            return
        y += 8
        col_w = inner / 2
        row_h = self.f_label.metrics("linespace") + self.f_value.metrics("linespace") + 4
        for i, (label, value, color) in enumerate(self.metrics):
            row, col = divmod(i, 2)
            if col == 0 and row > 0:
                y += row_h + 14
                self.create_line(pad, y - 8, w - pad, y - 8, fill=theme.mix(c1, "#ffffff", 0.35))
            x = pad + col * col_w
            self.create_text(x, y, text=label, anchor="nw", fill="#f1f1f7", font=self.f_label)
            self.create_text(x, y + self.f_label.metrics("linespace") + 2,
                             text=_fit(value, self.f_value, int(col_w) - 8), anchor="nw",
                             fill=color or "#ffffff", font=self.f_value)

class BarChart(_CanvasBox):
    """縦の棒グラフ。棒の上に値、下に項目名（長いときは斜め）。"""

    def __init__(self, master, height: int = 340, **kw):
        super().__init__(master, height=height, **kw)
        self.title = ""
        self.y_label = ""
        self.data: list[tuple[str, Number]] = []
        self.color: Callable[[int, float], str] = lambda i, t: theme.BAR
        self.empty = "表示するデータがありません。"
        self.f_title = tkfont.Font(family=theme.FAMILY, size=12, weight="bold")
        self.f_axis = tkfont.Font(family=theme.FAMILY, size=9)
        self.f_value = tkfont.Font(family=theme.FAMILY, size=9, weight="bold")

    def set(self, title: str, data: Sequence[tuple[str, Number]], y_label: str = "",
            color: Callable[[int, float], str] | None = None, empty: str | None = None) -> None:
        self.title, self.y_label, self.data = title, y_label, list(data)
        if color:
            self.color = color
        if empty:
            self.empty = empty
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 60 or h < 60:
            return
        self.create_text(4, 4, text=self.title, anchor="nw", fill=theme.TEXT, font=self.f_title)
        if not self.data:
            self.create_text(w / 2, h / 2, text=self.empty, fill=theme.MUTED, font=self.f_axis)
            return
        labels = [str(lbl) for lbl, _ in self.data]
        values = [float(v) for _, v in self.data]
        vmax = max(max(values), 0)
        vmin = min(min(values), 0)
        ticks = nice_ticks(vmax if vmax > 0 else 1)
        top_v = ticks[-1]
        left = max(self.f_axis.measure(fmt_number(t)) for t in ticks) + self.f_axis.metrics("linespace") + 22
        n = len(self.data)
        slot_guess = (w - left - 16) / n
        widest = max(self.f_axis.measure(lbl) for lbl in labels)
        slanted = widest > slot_guess - 6
        bottom_space = 28 if not slanted else min(int(widest * 0.6) + 26, 130)
        top = self.f_title.metrics("linespace") + self.f_value.metrics("linespace") + 14
        right, bottom = w - 16, h - bottom_space
        if bottom - top < 40:
            return
        span = top_v - vmin if top_v - vmin > 0 else 1

        def y_of(v: float) -> float:
            return bottom - (v - vmin) / span * (bottom - top)

        for t in ticks:
            y = y_of(t)
            self.create_line(left, y, right, y, fill=theme.GRID)
            self.create_text(left - 8, y, text=fmt_number(t), anchor="e", fill=theme.TEAL, font=self.f_axis)
        if self.y_label:
            self.create_text(6 + self.f_axis.metrics("linespace") / 2, (top + bottom) / 2, text=self.y_label, angle=90, fill=theme.TEAL, font=self.f_axis)
        slot = (right - left) / n
        bar_w = max(6, min(90, slot * 0.78))
        zero = y_of(0)
        for i, (label, v) in enumerate(zip(labels, values)):
            cx = left + slot * (i + 0.5)
            t = (v / vmax) if vmax > 0 else 0
            y = y_of(v)
            self.create_rectangle(cx - bar_w / 2, min(y, zero), cx + bar_w / 2, max(y, zero),
                                  fill=self.color(i, t), outline="")
            self.create_text(cx, min(y, zero) - 4, text=fmt_number(v), anchor="s", fill=theme.TEXT, font=self.f_value)
            if slanted:
                self.create_text(cx + 4, bottom + 8, text=_fit(label, self.f_axis, 160), anchor="ne", angle=35,
                                 fill=theme.TEXT, font=self.f_axis)
            else:
                self.create_text(cx, bottom + 8, text=_fit(label, self.f_axis, int(slot) - 4), anchor="n",
                                 fill=theme.TEXT, font=self.f_axis)


class HBarChart(_CanvasBox):
    """横の棒グラフ。値の大きさで 赤 → 緑 に色を変える（reverse で逆）。"""

    def __init__(self, master, height: int = 340, **kw):
        super().__init__(master, height=height, **kw)
        self.title = ""
        self.data: list[tuple[str, Number]] = []
        self.reverse = False
        self.fixed: dict[str, str] = {}
        self.empty = "表示するデータがありません。"
        self.f_title = tkfont.Font(family=theme.FAMILY, size=12, weight="bold")
        self.f_axis = tkfont.Font(family=theme.FAMILY, size=9)
        self.f_value = tkfont.Font(family=theme.FAMILY, size=9, weight="bold")

    def set(self, title: str, data: Sequence[tuple[str, Number]], reverse: bool = False,
            fixed_colors: dict[str, str] | None = None, empty: str | None = None) -> None:
        """reverse=True なら大きいほど赤（エラー件数など）。fixed_colors で項目ごとの色を決められる。"""
        self.title, self.data, self.reverse = title, list(data), reverse
        self.fixed = fixed_colors or {}
        if empty:
            self.empty = empty
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 60 or h < 60:
            return
        self.create_text(4, 4, text=self.title, anchor="nw", fill=theme.TEXT, font=self.f_title)
        if not self.data:
            self.create_text(w / 2, h / 2, text=self.empty, fill=theme.MUTED, font=self.f_axis)
            return
        labels = [str(lbl) for lbl, _ in self.data]
        values = [float(v) for _, v in self.data]
        vmax = max(max(values), 1)
        label_w = min(max(self.f_axis.measure(lbl) for lbl in labels) + 12, int(w * 0.42))
        left, right, bottom = label_w + 8, w - 56, h - 10
        top = self.f_title.metrics("linespace") + 14
        row_h = min(40, (bottom - top) / len(values))
        bar_h = max(8, row_h * 0.68)
        for i, (label, v) in enumerate(zip(labels, values)):
            cy = top + row_h * (i + 0.5)
            t = v / vmax
            color = self.fixed.get(label) or theme.scale_color(1 - t if self.reverse else t)
            x2 = left + (right - left) * t
            self.create_text(left - 8, cy, text=_fit(label, self.f_axis, label_w - 4), anchor="e",
                             fill=theme.TEXT, font=self.f_axis)
            self.create_rectangle(left, cy - bar_h / 2, max(left + 2, x2), cy + bar_h / 2, fill=color, outline="")
            self.create_text(max(left + 2, x2) + 6, cy, text=fmt_number(v), anchor="w", fill=theme.TEXT,
                             font=self.f_value)
