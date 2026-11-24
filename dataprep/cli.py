"""コマンドラインから使う入口。

    python -m dataprep                 → 画面（GUI）を開く
    python -m dataprep run --input samples/orders.csv --profile profiles/orders.json \
        --reconcile samples/payments.csv --out output
    python -m dataprep history         → 処理履歴を表示
    python -m dataprep check-profile profiles/orders.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import ProfileError, load_profile
from .fileio import DataFileError
from .history import HistoryStore, default_home, setup_logging
from .pipeline import ProcessingError, RunOptions, run

ENC_CHOICES = ["auto", "utf-8", "shift_jis"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dataprep", description="業務データ処理ツール（CSV の整形・検証・照合・集計）")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--home", type=Path, help="履歴とログの置き場所（既定：プロジェクトの data フォルダ）")
    sub = p.add_subparsers(dest="command")

    r = sub.add_parser("run", help="CSV を処理する")
    r.add_argument("--input", "-i", type=Path, required=True, help="処理する CSV")
    r.add_argument("--profile", "-p", type=Path, required=True, help="設定ファイル（JSON）")
    r.add_argument("--reconcile", "-r", type=Path, help="照合する CSV（設定に reconcile があるとき）")
    r.add_argument("--out", "-o", type=Path, default=Path("output"), help="出力先フォルダ（既定：output）")
    r.add_argument("--encoding", choices=ENC_CHOICES, help="入力 CSV の文字コード（既定：設定ファイルの値）")
    r.add_argument("--reconcile-encoding", choices=ENC_CHOICES, help="照合 CSV の文字コード")
    r.add_argument("--fail-on-error", action="store_true", help="エラーが1件でもあれば終了コード 1 を返す")

    h = sub.add_parser("history", help="処理履歴を表示する")
    h.add_argument("--limit", type=int, default=20)

    c = sub.add_parser("check-profile", help="設定ファイルの書き方を確かめる")
    c.add_argument("profile", type=Path)

    sub.add_parser("gui", help="画面を開く")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    home: Path = args.home or default_home()
    setup_logging(home / "logs")
    history = HistoryStore(home / "history.jsonl")

    if args.command in (None, "gui"):
        from .gui import launch
        launch(home=home)
        return 0

    if args.command == "check-profile":
        try:
            prof = load_profile(args.profile)
            if prof.reconcile:
                load_profile(prof.reconcile.right_profile)
        except ProfileError as exc:
            print(f"設定ファイルに誤りがあります：{exc}", file=sys.stderr)
            return 2
        print(f"OK：{prof.name}（列 {len(prof.columns)}・集計 {len(prof.aggregations)}・照合 {'あり' if prof.reconcile else 'なし'}）")
        return 0

    if args.command == "history":
        records = history.load(limit=args.limit)
        if not records:
            print("処理履歴はまだありません。")
        for rec in records:
            print(f"{rec.get('開始', '')}  {rec.get('状態', ''):<3}  行 {rec.get('データ行数', '-')}  "
                  f"エラー {rec.get('エラー件数', '-')}  {Path(rec.get('入力ファイル', '')).name}  {rec.get('メッセージ', '')}")
        return 0

    opts = RunOptions(
        input_path=args.input, profile_path=args.profile, output_dir=args.out,
        reconcile_path=args.reconcile, encoding=args.encoding, reconcile_encoding=args.reconcile_encoding,
    )
    try:
        result = run(opts, history=history, progress=lambda step, pct: print(f"[{pct:3d}%] {step}"))
    except (ProfileError, DataFileError, ProcessingError) as exc:
        print(f"処理できませんでした：{exc}", file=sys.stderr)
        return 2

    s = result.summary["入力ファイル"]
    print(f"\nデータ {s['データ行数']} 行：正常 {s['正常な行数']} 行／エラーのある行 {s['エラーのある行数']} 行／注意 {s['注意件数']} 件")
    if result.reconcile:
        print("照合：" + "／".join(f"{k} {v}件" for k, v in result.reconcile.counts.items()))
    print(f"出力先：{result.out_dir}")
    errors = s["エラー件数"] + (result.summary["照合ファイル"]["エラー件数"] if result.right else 0)
    return 1 if (args.fail_on_error and errors) else 0
