"""画面の部品：表（Treeview）・入力欄・左のメニュー・スクロールできる枠。"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

import pandas as pd

from . import theme

DISPLAY_LIMIT = 1000


class DataTable(ttk.Frame):
    """pandas の表を Treeview に出す。多すぎるときは先頭 DISPLAY_LIMIT 行だけ出す。"""

    def __init__(self, master, show_index: bool = False, index_label: str = "行番号", **kw):
        super().__init__(master, **kw)
        self.show_index = show_index
        self.index_label = index_label
        self.tree = ttk.Treeview(self, show="headings", selectmode="extended")
        ys = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.note = ttk.Label(self, text="", style="Muted.TLabel")
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.note.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self._recolor()
        theme.on_change(self._recolor)

    def _recolor(self) -> None:
        self.tree.tag_configure("error", background=theme.ROW_ERROR)
        self.tree.tag_configure("warning", background=theme.ROW_WARNING)
        self.tree.tag_configure("ok", background=theme.ROW_OK)
        self.tree.tag_configure("total", font=theme.FONT_BOLD, background=theme.HEADING)

    def clear(self, message: str = "") -> None:
        self.tree.delete(*self.tree.get_children())
        self.tree["columns"] = ()
        self.note.configure(text=message)

    def show(self, df: pd.DataFrame | None, tagger=None, empty_message: str = "該当するデータはありません。") -> None:
        self.tree.delete(*self.tree.get_children())
        if df is None:
            self.clear("")
            return
        data = df.reset_index() if self.show_index else df
        if self.show_index and data.columns[0] == "index":
            data = data.rename(columns={"index": self.index_label})
        columns = [str(c) for c in data.columns]
        self.tree["columns"] = columns
        shown = data.head(DISPLAY_LIMIT)
        body_font = tkfont.Font(family=theme.FAMILY, size=10)
        head_font = tkfont.Font(family=theme.FAMILY, size=10, weight="bold")
        sample = shown.head(60)
        for i, col in enumerate(columns):
            self.tree.heading(col, text=col, anchor="w")
            texts = ["" if _missing(v) else _fmt(v) for v in sample.iloc[:, i]]
            width = max([head_font.measure(col)] + [body_font.measure(t) for t in texts]) + 28
            self.tree.column(col, width=max(60, min(420, width)), minwidth=50, stretch=False, anchor="w")
        for row in shown.itertuples(index=False, name=None):
            values = ["" if _missing(v) else _fmt(v) for v in row]
            tags = tagger(row) if tagger else ()
            self.tree.insert("", "end", values=values, tags=tags)
        if data.empty:
            self.note.configure(text=empty_message)
        elif len(data) > DISPLAY_LIMIT:
            self.note.configure(text=f"全 {len(data):,} 件のうち先頭 {DISPLAY_LIMIT:,} 件を表示しています（すべては出力した CSV で見られます）。")
        else:
            self.note.configure(text=f"{len(data):,} 件")


def _missing(v) -> bool:
    try:
        return v is None or bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{int(v):,}" if v.is_integer() else f"{v:,.2f}"
    if isinstance(v, int) and not isinstance(v, bool):
        return f"{v:,}"
    return str(v)


class LabeledPath(ttk.Frame):
    """「見出し ［入力欄］ ［参照…］」の1行。"""

    def __init__(self, master, label: str, variable: tk.StringVar, command, button_text: str = "参照…", **kw):
        super().__init__(master, **kw)
        ttk.Label(self, text=label, width=18, style="Field.TLabel").pack(side="left")
        self.entry = ttk.Entry(self, textvariable=variable)
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        ttk.Button(self, text=button_text, command=command).pack(side="left")


class NavButton(tk.Label):
    """左のメニューのボタン。選んでいるものは青く塗る。"""

    def __init__(self, master, text: str, command, icon: str = "›"):
        super().__init__(master, text=f"{icon}   {text}", anchor="w", padx=16, pady=9, cursor="hand2",
                         font=theme.FONT, background=theme.SIDEBAR, foreground=theme.TEXT,
                         highlightthickness=1, highlightbackground=theme.BORDER, highlightcolor=theme.BORDER)
        self.command = command
        self.active = False
        self.bind("<Button-1>", lambda e: self.command())
        self.bind("<Enter>", lambda e: self._paint(hover=True))
        self.bind("<Leave>", lambda e: self._paint())
        theme.on_change(self._paint)

    def set_active(self, active: bool) -> None:
        self.active = active
        self._paint()

    def _paint(self, hover: bool = False) -> None:
        if self.active:
            self.configure(background=theme.ACCENT, foreground="#ffffff", font=theme.FONT_BOLD,
                           highlightbackground=theme.ACCENT)
        else:
            self.configure(background=theme.PANEL_HOVER if hover else theme.SIDEBAR, foreground=theme.TEXT,
                           font=theme.FONT, highlightbackground=theme.BORDER)


class ScrollableFrame(ttk.Frame):
    """縦にスクロールできる枠。中身は self.body に置く。"""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, background=theme.BG, highlightthickness=0, borderwidth=0)
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.body = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        theme.on_change(lambda: self.canvas.configure(background=theme.BG))
        # マウスが上にあるときだけホイールでスクロールする
        self.bind_all("<MouseWheel>", self._on_wheel, add="+")

    def _on_wheel(self, event) -> None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self:
                if self.winfo_ismapped():
                    self.canvas.yview_scroll(int(-event.delta / 120), "units")
                return
            if isinstance(widget, ttk.Treeview):
                return
            widget = widget.master
