"""Tkinter のデスクトップ画面（左にメニュー、右にダッシュボードや表）。

処理は別スレッドで動かし、画面の更新はキュー経由で行う（Tk は1つのスレッドからしか触れないため）。
"""

from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pandas as pd

from .. import __version__
from ..aggregate import TOTAL_LABEL
from ..config import Profile, ProfileError, load_profile
from ..fileio import DataFileError, read_csv
from ..history import HistoryStore, get_logger
from ..pipeline import ProcessingError, RunOptions, RunResult, run
from ..reconcile import MATCH, MISMATCH, RESULT_COL
from ..validation import ERROR, WARNING
from . import theme
from .charts import BarChart, GradientCard, HBarChart, fmt_number
from .widgets import DataTable, LabeledPath, NavButton, ScrollableFrame

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENCODING_CHOICES = {"設定ファイルに従う": None, "自動判定": "auto", "UTF-8": "utf-8", "Shift_JIS": "shift_jis"}
ALL = "すべて"
FONT = theme.FONT
DASH = "—"

# (ページの名前, メニューの文字, メニューの記号)
PAGES = [
    ("dashboard", "ダッシュボード", "▦"),
    ("files", "ファイルと実行", "▶"),
    ("data", "データ", "›"),
    ("issues", "エラー一覧", "›"),
    ("duplicates", "重複", "›"),
    ("reconcile", "照合", "›"),
    ("aggregate", "集計", "›"),
    ("history", "処理履歴", "›"),
]


def load_settings(home: Path) -> dict:
    try:
        data = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(home: Path, settings: dict) -> None:
    try:
        home.mkdir(parents=True, exist_ok=True)
        (home / "settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        get_logger().warning("画面の設定を保存できませんでした")


class App(ttk.Frame):
    def __init__(self, master: tk.Tk, home: Path):
        super().__init__(master)
        self.master = master
        self.home = home
        self.settings = load_settings(home)
        self.history = HistoryStore(home / "history.jsonl")
        self.result: RunResult | None = None
        self.run_profile: Profile | None = None
        self.events: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None

        self.input_var = tk.StringVar()
        self.profile_var = tk.StringVar()
        self.reconcile_var = tk.StringVar()
        self.out_var = tk.StringVar(value=str(PROJECT_ROOT / "output"))
        self.enc_var = tk.StringVar(value="設定ファイルに従う")
        self.status_var = tk.StringVar(value="「ファイルと実行」で CSV と設定ファイルを選び、「処理を実行」を押してください。")
        self.profile_info = tk.StringVar(value="")
        self.page_title = tk.StringVar()

        self.nav: dict[str, NavButton] = {}
        self.pages: dict[str, ttk.Frame] = {}
        self._build()
        self._load_profile_choices()
        self.refresh_history()
        self.show_dashboard()
        self.show_page("dashboard")
        self.after(100, self._poll_events)

    # ------------------------------------------------------------ 画面づくり

    def _build(self) -> None:
        self.pack(fill="both", expand=True)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self._build_sidebar()

        main = ttk.Frame(self, padding=(28, 18, 28, 14))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        top = ttk.Frame(main)
        top.grid(row=0, column=0, sticky="ew")
        ttk.Label(top, textvariable=self.page_title, style="Title.TLabel").pack(side="left")
        self.run_button = ttk.Button(top, text="処理を実行", command=self.start_run, style="Accent.TButton")
        self.run_button.pack(side="right")
        self.report_button = ttk.Button(top, text="レポートを開く", command=self.open_report, state="disabled")
        self.report_button.pack(side="right", padx=8)
        self.open_dir_button = ttk.Button(top, text="出力フォルダを開く", command=self.open_output, state="disabled")
        self.open_dir_button.pack(side="right")
        self.progress = ttk.Progressbar(top, mode="determinate", maximum=100, length=160)
        self.progress.pack(side="right", padx=12)

        ttk.Label(main, textvariable=self.status_var, style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 12))

        container = ttk.Frame(main)
        container.grid(row=2, column=0, sticky="nsew")
        container.columnconfigure(0, weight=1)
        container.rowconfigure(0, weight=1)
        builders = {
            "dashboard": self._build_dashboard, "files": self._build_files, "data": self._build_data,
            "issues": self._build_issues, "duplicates": self._build_duplicates, "reconcile": self._build_reconcile,
            "aggregate": self._build_aggregate, "history": self._build_history,
        }
        for name, _, _ in PAGES:
            page = ttk.Frame(container)
            page.grid(row=0, column=0, sticky="nsew")
            builders[name](page)
            self.pages[name] = page

    def _build_sidebar(self) -> None:
        side = ttk.Frame(self, style="Side.TFrame", padding=(20, 26, 20, 18), width=250)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        side.columnconfigure(0, weight=1)
        ttk.Label(side, text="業務データ処理ツール", style="SideTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(side, text="CSVの整形・検証・集計", style="SideMuted.TLabel", wraplength=200).grid(row=1, column=0, sticky="w", pady=(2, 0))
        tk_sep = tk.Frame(side, height=1, background=theme.BORDER)
        tk_sep.grid(row=2, column=0, sticky="ew", pady=18)
        theme.on_change(lambda: tk_sep.configure(background=theme.BORDER))
        for i, (name, label, icon) in enumerate(PAGES):
            btn = NavButton(side, label, command=lambda n=name: self.show_page(n), icon=icon)
            btn.grid(row=3 + i, column=0, sticky="ew", pady=4)
            self.nav[name] = btn
        side.rowconfigure(3 + len(PAGES), weight=1)
        bottom = 4 + len(PAGES)
        ttk.Label(side, text="表示モード", style="SideMuted.TLabel").grid(row=bottom, column=0, sticky="w", pady=(0, 4))
        self.mode_button = NavButton(side, "", command=self.toggle_mode, icon="")
        self.mode_button.grid(row=bottom + 1, column=0, sticky="ew")
        self._update_mode_button()
        ttk.Label(side, text=f"v{__version__}", style="SideMuted.TLabel").grid(row=bottom + 2, column=0, sticky="w", pady=(10, 0))

    def _section(self, parent, text: str, row: int, note_var: tk.StringVar | None = None) -> None:
        head = ttk.Frame(parent)
        head.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(6, 10))
        ttk.Label(head, text=text, style="Section.TLabel").pack(side="left")
        if note_var is not None:
            ttk.Label(head, textvariable=note_var, style="Muted.TLabel").pack(side="left", padx=14)

    def _build_dashboard(self, page: ttk.Frame) -> None:
        scroll = ScrollableFrame(page)
        scroll.pack(fill="both", expand=True)
        body = scroll.body
        body.columnconfigure(0, weight=3, uniform="dash")
        body.columnconfigure(1, weight=2, uniform="dash")

        self.dash_note = tk.StringVar()
        self._section(body, "■ 処理結果のまとめ", 0, self.dash_note)
        kpi = ttk.Frame(body)
        kpi.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.kpi_cards: dict[str, GradientCard] = {}
        for i, (key, colors) in enumerate((("rows", theme.CARD_BLUE), ("ok", theme.CARD_GREEN),
                                           ("error", theme.CARD_RED), ("dup", theme.CARD_ORANGE))):
            kpi.columnconfigure(i, weight=1, uniform="kpi")
            card = GradientCard(kpi, colors, height=112)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 8, 0))
            self.kpi_cards[key] = card

        self.best_note = tk.StringVar()
        head = ttk.Frame(body)
        head.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(26, 10))
        ttk.Label(head, text="▲▼ いちばん多い・少ない項目", style="Section.TLabel").pack(side="left")
        self.dash_agg = tk.StringVar()
        self.dash_metric = tk.StringVar()
        self.dash_metric_combo = ttk.Combobox(head, textvariable=self.dash_metric, state="readonly", width=16)
        self.dash_metric_combo.pack(side="right")
        ttk.Label(head, text="比べる値", style="Muted.TLabel").pack(side="right", padx=(12, 6))
        self.dash_agg_combo = ttk.Combobox(head, textvariable=self.dash_agg, state="readonly", width=16)
        self.dash_agg_combo.pack(side="right")
        ttk.Label(head, text="集計", style="Muted.TLabel").pack(side="right", padx=(0, 6))
        self.dash_agg_combo.bind("<<ComboboxSelected>>", lambda e: self._on_dash_agg())
        self.dash_metric_combo.bind("<<ComboboxSelected>>", lambda e: self._draw_dash_aggregate())

        hl = ttk.Frame(body)
        hl.grid(row=3, column=0, columnspan=2, sticky="ew")
        hl.columnconfigure(0, weight=1, uniform="hl")
        hl.columnconfigure(1, weight=1, uniform="hl")
        self.best_card = GradientCard(hl, theme.CARD_BLUE, height=168)
        self.best_card.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.worst_card = GradientCard(hl, theme.CARD_PINK, height=168)
        self.worst_card.grid(row=0, column=1, sticky="ew", padx=(8, 0))

        line = tk.Frame(body, height=1, background=theme.BORDER)
        line.grid(row=4, column=0, columnspan=2, sticky="ew", pady=22)
        theme.on_change(lambda: line.configure(background=theme.BORDER))

        self.agg_chart = BarChart(body, height=360)
        self.agg_chart.grid(row=5, column=0, sticky="nsew", padx=(0, 18))
        self.rule_chart = HBarChart(body, height=360)
        self.rule_chart.grid(row=5, column=1, sticky="nsew")
        self.rec_chart = HBarChart(body, height=250)
        self.rec_chart.grid(row=6, column=0, sticky="nsew", padx=(0, 18), pady=(24, 8))
        self.col_chart = HBarChart(body, height=250)
        self.col_chart.grid(row=6, column=1, sticky="nsew", pady=(24, 8))

    def _build_files(self, page: ttk.Frame) -> None:
        page.columnconfigure(0, weight=1)
        self._section(page, "■ ファイルを選ぶ", 0)
        form = ttk.Frame(page)
        form.grid(row=1, column=0, sticky="ew")
        LabeledPath(form, "処理するCSV", self.input_var, self.choose_input).pack(fill="x", pady=5)

        prof_row = ttk.Frame(form)
        prof_row.pack(fill="x", pady=5)
        ttk.Label(prof_row, text="設定ファイル", width=18, style="Field.TLabel").pack(side="left")
        self.profile_combo = ttk.Combobox(prof_row, textvariable=self.profile_var)
        self.profile_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.profile_combo.bind("<<ComboboxSelected>>", lambda e: self._update_profile_info())
        self.profile_combo.bind("<FocusOut>", lambda e: self._update_profile_info())
        ttk.Button(prof_row, text="参照…", command=self.choose_profile).pack(side="left")
        ttk.Label(form, textvariable=self.profile_info, style="Muted.TLabel").pack(fill="x", padx=(150, 0))

        LabeledPath(form, "照合するCSV（任意）", self.reconcile_var, self.choose_reconcile).pack(fill="x", pady=5)
        LabeledPath(form, "出力先フォルダ", self.out_var, self.choose_out).pack(fill="x", pady=5)

        enc_row = ttk.Frame(form)
        enc_row.pack(fill="x", pady=5)
        ttk.Label(enc_row, text="文字コード", width=18, style="Field.TLabel").pack(side="left")
        ttk.Combobox(enc_row, textvariable=self.enc_var, values=list(ENCODING_CHOICES), state="readonly", width=20).pack(side="left")

        actions = ttk.Frame(page)
        actions.grid(row=2, column=0, sticky="w", pady=(18, 0))
        ttk.Button(actions, text="中身を見る", command=self.preview).pack(side="left")
        ttk.Button(actions, text="処理を実行", command=self.start_run, style="Accent.TButton").pack(side="left", padx=8)

        self._section(page, "■ 使い方", 3)
        steps = ("1. 「処理するCSV」を選ぶと、「データ」に中身が出ます。",
                 "2. 設定ファイルを選びます（受注データなら orders.json）。",
                 "3. 照合したいときは「照合するCSV」も選びます（受注データなら入金の CSV）。",
                 "4. 右上の「処理を実行」を押すと、ダッシュボードに結果が出ます。",
                 "5. 結果は出力先フォルダに CSV・JSON・HTML で保存されます（前の結果は消えません）。")
        ttk.Label(page, text="\n".join(steps), style="Muted.TLabel", justify="left").grid(row=4, column=0, sticky="w")

    def _build_data(self, page: ttk.Frame) -> None:
        self.preview_table = DataTable(page, show_index=True)
        self.preview_table.pack(fill="both", expand=True)

    def _build_issues(self, page: ttk.Frame) -> None:
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Label(bar, text="重要度", style="Field.TLabel").pack(side="left")
        self.issue_sev = tk.StringVar(value=ALL)
        ttk.Combobox(bar, textvariable=self.issue_sev, values=[ALL, ERROR, WARNING], state="readonly",
                     width=8).pack(side="left", padx=(6, 16))
        ttk.Label(bar, text="チェック", style="Field.TLabel").pack(side="left")
        self.issue_rule = tk.StringVar(value=ALL)
        self.issue_rule_combo = ttk.Combobox(bar, textvariable=self.issue_rule, values=[ALL], state="readonly", width=16)
        self.issue_rule_combo.pack(side="left", padx=(6, 16))
        ttk.Label(bar, text="検索", style="Field.TLabel").pack(side="left")
        self.issue_query = tk.StringVar()
        ttk.Entry(bar, textvariable=self.issue_query, width=26).pack(side="left", padx=6)
        for var in (self.issue_sev, self.issue_rule, self.issue_query):
            var.trace_add("write", lambda *a: self.show_issues())
        self.issue_table = DataTable(page)
        self.issue_table.pack(fill="both", expand=True)
        self.issue_table.clear("処理を実行すると、ここにエラーと注意の一覧が出ます。")

    def _build_duplicates(self, page: ttk.Frame) -> None:
        self.dup_table = DataTable(page, show_index=True)
        self.dup_table.pack(fill="both", expand=True)
        self.dup_table.clear("処理を実行すると、ここに重複した行が出ます。")

    def _build_reconcile(self, page: ttk.Frame) -> None:
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Label(bar, text="照合結果", style="Field.TLabel").pack(side="left")
        self.rec_filter = tk.StringVar(value=ALL)
        self.rec_combo = ttk.Combobox(bar, textvariable=self.rec_filter, values=[ALL], state="readonly", width=16)
        self.rec_combo.pack(side="left", padx=6)
        self.rec_filter.trace_add("write", lambda *a: self.show_reconcile())
        self.rec_counts = ttk.Label(bar, text="", style="Muted.TLabel")
        self.rec_counts.pack(side="left", padx=12)
        self.rec_table = DataTable(page)
        self.rec_table.pack(fill="both", expand=True)
        self.rec_table.clear("照合するCSVを選んで実行すると、ここに結果が出ます。")

    def _build_aggregate(self, page: ttk.Frame) -> None:
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Label(bar, text="集計", style="Field.TLabel").pack(side="left")
        self.agg_choice = tk.StringVar()
        self.agg_combo = ttk.Combobox(bar, textvariable=self.agg_choice, state="readonly", width=24)
        self.agg_combo.pack(side="left", padx=6)
        self.agg_choice.trace_add("write", lambda *a: self.show_aggregate())
        ttk.Label(bar, text="※ エラーのない行だけを集計しています", style="Muted.TLabel").pack(side="left", padx=12)
        self.agg_table = DataTable(page)
        self.agg_table.pack(fill="both", expand=True)
        self.agg_table.clear("設定ファイルに集計（aggregations）があると、処理のあとここに出ます。")

    def _build_history(self, page: ttk.Frame) -> None:
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Button(bar, text="最新にする", command=self.refresh_history).pack(side="left")
        ttk.Label(bar, text=f"保存先：{self.history.path}", style="Muted.TLabel").pack(side="left", padx=12)
        self.hist_table = DataTable(page)
        self.hist_table.pack(fill="both", expand=True)

    # ------------------------------------------------------------ ページと表示モード

    def show_page(self, name: str) -> None:
        self.pages[name].tkraise()
        for key, btn in self.nav.items():
            btn.set_active(key == name)
        self.page_title.set(next(label for key, label, _ in PAGES if key == name))

    def toggle_mode(self) -> None:
        theme.set_mode(theme.LIGHT if theme.mode == theme.DARK else theme.DARK)
        theme.apply(self.master)
        self._update_mode_button()
        self.settings["theme"] = theme.mode
        save_settings(self.home, self.settings)

    def _update_mode_button(self) -> None:
        if theme.mode == theme.DARK:
            self.mode_button.configure(text="☀   ライトモードにする")
        else:
            self.mode_button.configure(text="☾   ダークモードにする")

    # ------------------------------------------------------------ ファイル選択

    def _load_profile_choices(self) -> None:
        folder = PROJECT_ROOT / "profiles"
        choices = sorted(str(p) for p in folder.glob("*.json")) if folder.is_dir() else []
        self.profile_combo["values"] = choices
        orders = folder / "orders.json"
        if orders.is_file():
            self.profile_var.set(str(orders))
        elif choices:
            self.profile_var.set(choices[0])
        self._update_profile_info()

    def _update_profile_info(self) -> None:
        path = self.profile_var.get().strip()
        if not path:
            self.profile_info.set("")
            return
        try:
            prof = load_profile(path)
        except ProfileError as exc:
            self.profile_info.set(f"⚠ {exc}")
            return
        parts = [prof.name, f"列 {len(prof.columns)}"]
        if prof.reconcile:
            parts.append(f"照合：{prof.reconcile.left_label}×{prof.reconcile.right_label}")
        if prof.aggregations:
            parts.append("集計：" + "・".join(a.name for a in prof.aggregations))
        self.profile_info.set(" ／ ".join(parts))

    def _ask_csv(self, title: str) -> str:
        return filedialog.askopenfilename(title=title, filetypes=[("CSV ファイル", "*.csv *.tsv *.txt"), ("すべてのファイル", "*.*")])

    def choose_input(self) -> None:
        path = self._ask_csv("処理する CSV を選ぶ")
        if path:
            self.input_var.set(path)
            self.preview()

    def choose_reconcile(self) -> None:
        path = self._ask_csv("照合する CSV を選ぶ")
        if path:
            self.reconcile_var.set(path)

    def choose_profile(self) -> None:
        path = filedialog.askopenfilename(title="設定ファイルを選ぶ", initialdir=PROJECT_ROOT / "profiles",
                                          filetypes=[("設定ファイル（JSON）", "*.json")])
        if path:
            self.profile_var.set(path)
            self._update_profile_info()

    def choose_out(self) -> None:
        path = filedialog.askdirectory(title="出力先フォルダを選ぶ")
        if path:
            self.out_var.set(path)

    # ------------------------------------------------------------ 操作

    def _encoding(self) -> str | None:
        return ENCODING_CHOICES.get(self.enc_var.get())

    def preview(self) -> None:
        path = self.input_var.get().strip()
        if not path:
            messagebox.showinfo("中身を見る", "先に「処理するCSV」を選んでください。", parent=self.master)
            return
        delimiter, encoding = ",", self._encoding() or "auto"
        try:
            prof = load_profile(self.profile_var.get().strip()) if self.profile_var.get().strip() else None
            if prof:
                delimiter = prof.delimiter
                encoding = self._encoding() or prof.encoding
        except ProfileError:
            pass
        try:
            table = read_csv(path, encoding=encoding, delimiter=delimiter)
        except DataFileError as exc:
            messagebox.showerror("読み込めませんでした", str(exc), parent=self.master)
            return
        self.preview_table.show(table.df)
        self.show_page("data")
        msg = f"{Path(path).name}：{len(table.df):,} 行・{len(table.df.columns)} 列（文字コード {table.encoding_label}）"
        if table.structural_issues:
            msg += f"／列の数が合わない行 {len(table.structural_issues)} 件"
        self.status_var.set(msg)

    def start_run(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        input_path = self.input_var.get().strip()
        profile_path = self.profile_var.get().strip()
        out_dir = self.out_var.get().strip()
        missing = [name for name, v in (("処理するCSV", input_path), ("設定ファイル", profile_path), ("出力先フォルダ", out_dir)) if not v]
        if missing:
            self.show_page("files")
            messagebox.showwarning("処理を実行", "次を選んでください：" + "、".join(missing), parent=self.master)
            return
        opts = RunOptions(
            input_path=Path(input_path), profile_path=Path(profile_path), output_dir=Path(out_dir),
            reconcile_path=Path(self.reconcile_var.get().strip()) if self.reconcile_var.get().strip() else None,
            encoding=self._encoding(), reconcile_encoding=self._encoding(),
        )
        self.run_button.configure(state="disabled")
        self.progress["value"] = 0
        self.status_var.set("処理を始めます…")
        self.worker = threading.Thread(target=self._run_worker, args=(opts,), daemon=True)
        self.worker.start()

    def _run_worker(self, opts: RunOptions) -> None:
        try:
            result = run(opts, history=self.history, progress=lambda step, pct: self.events.put(("progress", step, pct)))
            try:
                profile = load_profile(opts.profile_path)
            except ProfileError:
                profile = None
            self.events.put(("done", result, profile))
        except (ProfileError, DataFileError, ProcessingError) as exc:
            self.events.put(("error", str(exc)))
        except Exception:  # pipeline.run が想定外のエラーを ProcessingError にするので、ここは念のため
            get_logger().exception("画面での処理中のエラー")
            self.events.put(("error", "想定外のエラーが起きました。ログファイルを確認してください。"))

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "progress":
                    _, step, pct = event
                    self.progress["value"] = pct
                    self.status_var.set(step)
                elif kind == "done":
                    self._on_done(event[1], event[2])
                elif kind == "error":
                    self.run_button.configure(state="normal")
                    self.progress["value"] = 0
                    self.status_var.set("処理できませんでした。")
                    self.refresh_history()
                    messagebox.showerror("処理できませんでした", event[1], parent=self.master)
        except queue.Empty:
            pass
        self.after(100, self._poll_events)

    def _on_done(self, result: RunResult, profile: Profile | None) -> None:
        self.result = result
        self.run_profile = profile
        self.run_button.configure(state="normal")
        self.open_dir_button.configure(state="normal")
        self.report_button.configure(state="normal")
        s = result.summary["入力ファイル"]
        self.status_var.set(f"完了：{s['データ行数']:,} 行のうち 正常 {s['正常な行数']:,} 行・エラーのある行 {s['エラーのある行数']:,} 行"
                            f"（出力先：{result.out_dir.name if result.out_dir else DASH}）")
        self.preview_table.show(result.main.cleaned)
        rules = sorted(set(result.issues_df["チェック"])) if not result.issues_df.empty else []
        self.issue_rule_combo["values"] = [ALL, *rules]
        self.issue_rule.set(ALL)
        self.show_issues()
        self.dup_table.show(result.main.duplicates, empty_message="重複はありませんでした。")
        if result.reconcile:
            self.rec_combo["values"] = [ALL, *result.reconcile.counts]
            self.rec_counts.configure(text="　".join(f"{k} {v:,}件" for k, v in result.reconcile.counts.items()))
        else:
            self.rec_combo["values"] = [ALL]
            self.rec_counts.configure(text="（照合するCSVを選ぶと照合します）")
        self.rec_filter.set(ALL)
        self.show_reconcile()
        names = list(result.aggregates)
        self.agg_combo["values"] = names
        self.agg_choice.set(names[0] if names else "")
        self.show_aggregate()
        self.refresh_history()
        self.show_dashboard()
        self.show_page("dashboard")

    # ------------------------------------------------------------ ダッシュボード

    def show_dashboard(self) -> None:
        r = self.result
        if r is None:
            self.dash_note.set("まだ処理していません")
            for key, caption in (("rows", "データ行数"), ("ok", "正常な行"), ("error", "エラーのある行"), ("dup", "重複")):
                self.kpi_cards[key].set(caption=caption, title=DASH, subtitle="実行後に表示します")
            for card, caption in ((self.best_card, "▲ いちばん多い"), (self.worst_card, "▼ いちばん少ない")):
                card.set(caption=caption, title=DASH, subtitle="設定ファイルの集計から選びます")
            waiting = "処理を実行すると、ここにグラフが出ます。"
            self.agg_chart.set("集計グラフ", [], empty=waiting)
            self.rule_chart.set("チェック別のエラー件数", [], empty=waiting)
            self.rec_chart.set("照合の結果", [], empty=waiting)
            self.col_chart.set("列ごとのエラー件数", [], empty=waiting)
            return

        s = r.summary["入力ファイル"]
        total = s["データ行数"] or 1
        self.dash_note.set(f"{s['ファイル']}（{s['設定']}・{s['文字コード']}）　処理番号 {r.run_id}")
        self.kpi_cards["rows"].set(caption="データ行数", title=f"{s['データ行数']:,}",
                                   subtitle=f"空行（読み飛ばし） {s['空行（読み飛ばし）']:,} 行")
        self.kpi_cards["ok"].set(caption="正常な行", title=f"{s['正常な行数']:,}",
                                 subtitle=f"全体の {s['正常な行数'] / total:.0%}")
        self.kpi_cards["error"].set(caption="エラーのある行", title=f"{s['エラーのある行数']:,}",
                                    subtitle=f"エラー {s['エラー件数']:,} 件・注意 {s['注意件数']:,} 件")
        self.kpi_cards["dup"].set(caption="重複（2件目以降）", title=f"{s['重複（2件目以降）']:,}",
                                  subtitle=f"整形で直した値 {s['整形で直した値']:,} 件")

        names = list(r.aggregates)
        self.dash_agg_combo["values"] = names
        if self.dash_agg.get() not in names:
            # 商品別などの「いちばん多い・少ない」が意味のある集計を先に選ぶ（月別は2番目以降）
            preferred = [n for n in names if self._group_count(n) and "月" not in n]
            self.dash_agg.set((preferred or names or [""])[0])
        self._on_dash_agg()

        issues = r.issues_df
        if issues.empty:
            self.rule_chart.set("チェック別のエラー件数", [], empty="エラー・注意はありませんでした。")
            self.col_chart.set("列ごとのエラー件数", [], empty="エラー・注意はありませんでした。")
        else:
            by_rule = issues.groupby("チェック").size().sort_values(ascending=False)
            self.rule_chart.set("チェック別のエラー件数", list(by_rule.items()), reverse=True)
            cols = issues.assign(列=issues["列"].replace("", "（行全体）")).groupby("列").size().sort_values(ascending=False)
            self.col_chart.set("列ごとのエラー件数", list(cols.head(6).items()), reverse=True)

        if r.reconcile:
            labels = list(r.reconcile.counts)
            colors = {label: theme.SCALE[2] for label in labels}
            colors[MATCH] = theme.SCALE[4]
            colors[MISMATCH] = theme.SCALE[0]
            title = f"照合の結果（{r.reconcile.left_label} × {r.reconcile.right_label}）"
            self.rec_chart.set(title, list(r.reconcile.counts.items()), fixed_colors=colors)
        else:
            self.rec_chart.set("照合の結果", [], empty="照合するCSVを選ぶと、ここに照合の結果が出ます。")

    def _group_count(self, agg_name: str) -> int:
        """集計の「切り口」の列の数（設定ファイルから。読めなければ文字の列の数）。"""
        if self.run_profile:
            for spec in self.run_profile.aggregations:
                if spec.name == agg_name:
                    return len(spec.group_by)
        df = self.result.aggregates.get(agg_name) if self.result else None
        if df is None:
            return 0
        return sum(1 for c in df.columns if not pd.api.types.is_numeric_dtype(df[c]))

    def _on_dash_agg(self) -> None:
        df = self.result.aggregates.get(self.dash_agg.get()) if self.result else None
        if df is None:
            self.dash_metric_combo["values"] = []
            self.dash_metric.set("")
        else:
            metrics = [c for c in df.columns[self._group_count(self.dash_agg.get()):]
                       if pd.api.types.is_numeric_dtype(df[c])]
            self.dash_metric_combo["values"] = metrics
            if self.dash_metric.get() not in metrics:
                money = [m for m in metrics if "金額" in m or "売上" in m]
                self.dash_metric.set((money or metrics or [""])[0])
        self._draw_dash_aggregate()

    def _draw_dash_aggregate(self) -> None:
        name, metric = self.dash_agg.get(), self.dash_metric.get()
        df = self.result.aggregates.get(name) if self.result else None
        if df is None or not metric or metric not in df.columns:
            self.agg_chart.set("集計グラフ", [], empty="設定ファイルに集計（aggregations）がありません。")
            self.best_card.set(caption="▲ いちばん多い", title=DASH, subtitle="集計がありません")
            self.worst_card.set(caption="▼ いちばん少ない", title=DASH, subtitle="集計がありません")
            return
        n_group = max(1, self._group_count(name))
        group_cols = list(df.columns[:n_group])
        metric_cols = [c for c in df.columns[n_group:]]
        rows = df[df[group_cols[0]].astype(str) != TOTAL_LABEL]
        rows = rows[pd.to_numeric(rows[metric], errors="coerce").notna()]
        label_of = (lambda row: " ".join(str(row[c]) for c in group_cols[-1:])) if len(group_cols) > 1 else \
            (lambda row: str(row[group_cols[0]]))
        data = [(label_of(row), float(row[metric])) for _, row in rows.iterrows()]
        self.agg_chart.set(f"{name}（{metric}）", data, y_label=metric)
        if rows.empty:
            self.best_card.set(caption="▲ いちばん多い", title=DASH, subtitle="集計する行がありません")
            self.worst_card.set(caption="▼ いちばん少ない", title=DASH, subtitle="集計する行がありません")
            return
        values = pd.to_numeric(rows[metric])
        best, worst = rows.loc[values.idxmax()], rows.loc[values.idxmin()]
        for card, row, caption, highlight in ((self.best_card, best, f"▲ {metric}がいちばん多い", "#9ff5c0"),
                                              (self.worst_card, worst, f"▼ {metric}がいちばん少ない", "#ffe066")):
            title = " ".join(str(row[c]) for c in group_cols)
            metrics = [(c, _fmt_cell(row[c]), highlight if c == metric else None) for c in metric_cols[:4]]
            card.set(caption=caption, title=title, metrics=metrics)

    # ------------------------------------------------------------ 表

    def show_issues(self) -> None:
        if not self.result:
            return
        df = self.result.issues_df
        if self.issue_sev.get() != ALL:
            df = df[df["重要度"] == self.issue_sev.get()]
        if self.issue_rule.get() != ALL:
            df = df[df["チェック"] == self.issue_rule.get()]
        q = self.issue_query.get().strip()
        if q:
            mask = df.astype(str).apply(lambda col: col.str.contains(q, regex=False)).any(axis=1)
            df = df[mask]
        sev_idx = list(df.columns).index("重要度")
        self.issue_table.show(df, tagger=lambda row: ("error",) if row[sev_idx] == ERROR else ("warning",),
                              empty_message="エラー・注意はありませんでした。")

    def show_reconcile(self) -> None:
        if not self.result or not self.result.reconcile:
            self.rec_table.clear("照合するCSVを選んで実行すると、ここに結果が出ます。")
            return
        df = self.result.reconcile.table
        if self.rec_filter.get() != ALL:
            df = df[df[RESULT_COL] == self.rec_filter.get()]

        def tag(row):
            return ("ok",) if row[0] == MATCH else ("error",) if row[0] == MISMATCH else ("warning",)

        self.rec_table.show(df, tagger=tag)

    def show_aggregate(self) -> None:
        if not self.result or not self.agg_choice.get():
            self.agg_table.clear("設定ファイルに集計（aggregations）があると、処理のあとここに出ます。")
            return
        df = self.result.aggregates.get(self.agg_choice.get())
        self.agg_table.show(df, tagger=lambda row: ("total",) if row and row[0] == TOTAL_LABEL else ())

    def refresh_history(self) -> None:
        records = self.history.load(limit=200)
        cols = ["開始", "状態", "設定", "入力ファイル", "データ行数", "正常な行数", "エラー件数", "処理時間（秒）", "メッセージ"]
        rows = []
        for r in records:
            row = {c: r.get(c, "") for c in cols}
            row["入力ファイル"] = Path(str(row["入力ファイル"])).name
            rows.append(row)
        df = pd.DataFrame(rows, columns=cols)
        self.hist_table.show(df, tagger=lambda row: ("error",) if row[1] == "失敗" else (),
                             empty_message="処理履歴はまだありません。")

    def open_output(self) -> None:
        if self.result and self.result.out_dir and self.result.out_dir.is_dir():
            _open_path(self.result.out_dir)

    def open_report(self) -> None:
        if self.result and self.result.out_dir:
            report = self.result.out_dir / "report.html"
            if report.is_file():
                # Windows では「file:///…（日本語は %E6…）」の URL を渡すと Edge の空のページが開くことがあるため、
                # ファイルそのものを .html に関連付けられたブラウザで開く
                _open_path(report)


def _fmt_cell(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return DASH
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return fmt_number(v)
    try:
        return fmt_number(float(v))
    except (TypeError, ValueError):
        return str(v)


def _open_path(path: Path) -> None:
    if hasattr(os, "startfile"):
        os.startfile(str(path))  # noqa: S606 - 自分で作った出力フォルダだけを開く
    else:
        webbrowser.open(path.resolve().as_uri())


def setup_root(root: tk.Tk, home: Path) -> None:
    """ウィンドウの大きさと配色（前回のモード）を決める。"""
    root.title("業務データ処理ツール")
    root.geometry("1320x860")
    root.minsize(1040, 660)
    theme.set_mode(load_settings(home).get("theme", theme.DARK))
    theme.apply(root)


def launch(home: Path) -> None:
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # Windows の高解像度画面でぼやけないように
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    setup_root(root, home)
    App(root, home)
    root.mainloop()
