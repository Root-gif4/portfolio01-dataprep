"""画面の配色とフォント（ダッシュボード風）。ダークモードとライトモードを切り替えられる。

色はこのモジュールの変数（theme.BG など）を、描くときに毎回読む。
set_mode() で変数を入れ替え、apply() で ttk のスタイルを作り直し、
on_change() で登録した部品に描き直してもらう。
"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Callable

FAMILY = "Yu Gothic UI"
FONT = (FAMILY, 10)
FONT_BOLD = (FAMILY, 10, "bold")
FONT_SMALL = (FAMILY, 9)
FONT_TITLE = (FAMILY, 17, "bold")
FONT_SECTION = (FAMILY, 13, "bold")

DARK = "dark"
LIGHT = "light"
MODE_LABELS = {DARK: "ダーク", LIGHT: "ライト"}

PALETTES: dict[str, dict[str, str]] = {
    DARK: {
        "BG": "#0e1117",          # 画面の地
        "SIDEBAR": "#151922",     # 左のメニュー
        "PANEL": "#1a1f2b",       # 入力欄・表の地
        "PANEL_HOVER": "#252c3b",
        "HEADING": "#232a38",     # 表の見出し
        "GRID": "#232a38",        # グラフの目盛り線
        "BORDER": "#2b3242",
        "TEXT": "#e6e8ee",
        "MUTED": "#8b93a7",
        "DISABLED": "#555d70",
        "SELECTED": "#2a4f86",
        "TEAL": "#4ecdc4",
        "BAR": "#97e3d8",
        "ROW_ERROR": "#4a2027",
        "ROW_WARNING": "#4a3d17",
        "ROW_OK": "#173d2c",
    },
    LIGHT: {
        "BG": "#f5f7fb",
        "SIDEBAR": "#ffffff",
        "PANEL": "#ffffff",
        "PANEL_HOVER": "#eef2f8",
        "HEADING": "#e9edf4",
        "GRID": "#e3e7ee",
        "BORDER": "#d5dbe5",
        "TEXT": "#1f2533",
        "MUTED": "#5f6b7f",
        "DISABLED": "#a6aebb",
        "SELECTED": "#cfe3ff",
        "TEAL": "#178f87",
        "BAR": "#4ecdc4",
        "ROW_ERROR": "#fde4e6",
        "ROW_WARNING": "#fff3d6",
        "ROW_OK": "#e2f5e9",
    },
}

ACCENT = "#1f8bff"      # 選んでいるメニュー・主なボタン（どちらのモードも同じ）
ACCENT_HOVER = "#4aa3ff"

# カードのグラデーション（左 → 右）。文字は白なので、どちらのモードも同じ色
CARD_BLUE = ("#5b6fd8", "#7b4fb0")
CARD_PINK = ("#e97ad6", "#f2557a")
CARD_TEAL = ("#1fa2a0", "#2f6fb5")
CARD_GREEN = ("#2aa86a", "#1d7f8c")
CARD_RED = ("#e2525f", "#a8366b")
CARD_ORANGE = ("#f0a03c", "#d2573a")

# グラフの色（赤 → 黄 → 緑）
SCALE = ("#ef5b63", "#f6a04d", "#f3d34a", "#a7d65b", "#5fc777")

mode = DARK
BG = SIDEBAR = PANEL = PANEL_HOVER = HEADING = GRID = BORDER = TEXT = MUTED = DISABLED = SELECTED = ""
TEAL = BAR = ROW_ERROR = ROW_WARNING = ROW_OK = ""

_listeners: list[Callable[[], None]] = []


def set_mode(new_mode: str) -> None:
    """配色を入れ替える（画面への反映は apply()）。知らない値ならダークにする。"""
    global mode
    mode = new_mode if isinstance(new_mode, str) and new_mode in PALETTES else DARK
    globals().update(PALETTES[mode])


set_mode(DARK)


def on_change(callback: Callable[[], None]) -> None:
    """モードが変わったときに呼んでほしい処理を登録する（自分で色を持つ部品用）。"""
    _listeners.append(callback)


def mix(c1: str, c2: str, t: float) -> str:
    """2色の間の色（t=0 で c1、t=1 で c2）。"""
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def scale_color(t: float) -> str:
    """0〜1 の値を 赤 → 緑 の色にする。"""
    t = min(1.0, max(0.0, t))
    pos = t * (len(SCALE) - 1)
    i = min(int(pos), len(SCALE) - 2)
    return mix(SCALE[i], SCALE[i + 1], pos - i)


def apply(root: tk.Tk) -> ttk.Style:
    """いまの配色で ttk のスタイルを作り、登録した部品を描き直す。"""
    root.configure(background=BG)
    # 「*Font」で全部に指定すると ttk のスタイルの文字の大きさが効かなくなるので、標準のフォントを変える
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(name).configure(family=FAMILY, size=FONT[1])
    # コンボボックスの一覧（ttk ではなく Tk の Listbox。次に開いたときから効く）
    root.option_add("*TCombobox*Listbox.background", PANEL)
    root.option_add("*TCombobox*Listbox.foreground", TEXT)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", FONT)

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL, bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, troughcolor=PANEL, focuscolor=ACCENT,
                    selectbackground=ACCENT, selectforeground="#ffffff", insertcolor=TEXT, font=FONT)
    style.configure("TFrame", background=BG)
    style.configure("Side.TFrame", background=SIDEBAR)
    style.configure("TLabel", background=BG, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED)
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=FONT_TITLE)
    style.configure("Section.TLabel", background=BG, foreground=TEXT, font=FONT_SECTION)
    style.configure("Field.TLabel", background=BG, foreground=MUTED, font=FONT_BOLD)
    style.configure("Side.TLabel", background=SIDEBAR, foreground=TEXT)
    style.configure("SideMuted.TLabel", background=SIDEBAR, foreground=MUTED, font=FONT_SMALL)
    style.configure("SideTitle.TLabel", background=SIDEBAR, foreground=TEXT, font=(FAMILY, 12, "bold"))

    style.configure("TButton", background=PANEL, foreground=TEXT, bordercolor=BORDER, padding=(12, 6), relief="flat")
    style.map("TButton", background=[("disabled", BG), ("active", PANEL_HOVER)],
              foreground=[("disabled", DISABLED)], bordercolor=[("active", ACCENT)])
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", bordercolor=ACCENT, font=FONT_BOLD)
    style.map("Accent.TButton", background=[("disabled", mix(ACCENT, BG, 0.55)), ("active", ACCENT_HOVER)],
              foreground=[("disabled", mix("#ffffff", BG, 0.3))])

    style.configure("TEntry", fieldbackground=PANEL, foreground=TEXT, padding=5)
    style.map("TEntry", bordercolor=[("focus", ACCENT)])
    style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=TEXT, arrowcolor=TEXT, padding=4)
    style.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", TEXT)],
              selectbackground=[("readonly", PANEL)], selectforeground=[("readonly", TEXT)],
              bordercolor=[("focus", ACCENT)])

    style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=26,
                    bordercolor=BORDER, font=FONT)
    style.map("Treeview", background=[("selected", SELECTED)],
              foreground=[("selected", "#ffffff" if mode == DARK else TEXT)])
    style.configure("Treeview.Heading", background=HEADING, foreground=TEXT, font=FONT_BOLD,
                    relief="flat", padding=(6, 5))
    style.map("Treeview.Heading", background=[("active", PANEL_HOVER)])

    for orient in ("Vertical", "Horizontal"):
        style.configure(f"{orient}.TScrollbar", background=BORDER, troughcolor=BG, bordercolor=BG,
                        arrowcolor=MUTED, gripcount=0)
        style.map(f"{orient}.TScrollbar", background=[("active", mix(BORDER, TEXT, 0.25))])
    style.configure("Horizontal.TProgressbar", background=TEAL, troughcolor=PANEL, bordercolor=BORDER,
                    lightcolor=TEAL, darkcolor=TEAL)
    style.configure("TSeparator", background=BORDER)

    for callback in list(_listeners):
        try:
            callback()
        except tk.TclError:  # 閉じた部品は飛ばす
            pass
    return style
