"""一連の処理（読み込み → 整形 → 検証 → 重複 → 照合 → 集計 → 出力 → 履歴）をまとめて行う。"""

from __future__ import annotations

import hashlib
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from . import __version__
from .aggregate import aggregate
from .cleaning import clean_dataframe
from .config import Profile, ProfileError, check_reconcile_against, load_profile
from .duplicates import find_duplicates
from .fileio import DataFileError, LoadedTable, dataframe_records, read_csv, write_csv, write_json
from .history import HistoryStore, get_logger
from .reconcile import ReconcileResult, reconcile
from .report import render_html
from .validation import (ERROR, WARNING, Issue, RULE_LABELS, has_fatal_column_issue, issues_to_dataframe,
                         validate_columns, validate_values)

Progress = Callable[[str, int], None]

OUTPUT_NAMES = {
    "cleaned": "01_整形済みデータ.csv",
    "valid": "02_正常データ.csv",
    "valid_json": "02_正常データ.json",
    "issues": "03_エラー一覧.csv",
    "duplicates": "04_重複一覧.csv",
    "changes": "05_整形の変更記録.csv",
    "reconcile": "06_照合結果.csv",
    "summary": "summary.json",
    "report": "report.html",
}


class ProcessingError(Exception):
    """処理を続けられないエラー（画面にそのまま出せる文）。"""


@dataclass
class RunOptions:
    input_path: Path
    profile_path: Path
    output_dir: Path
    reconcile_path: Path | None = None
    encoding: str | None = None            # None なら設定ファイルの encoding
    reconcile_encoding: str | None = None
    write_outputs: bool = True


@dataclass
class DatasetResult:
    label: str
    table: LoadedTable
    profile: Profile
    cleaned: pd.DataFrame
    changes: pd.DataFrame
    issues: list[Issue]
    duplicates: pd.DataFrame
    valid: pd.DataFrame

    @property
    def error_rows(self) -> set[int]:
        return {i.row for i in self.issues if i.severity == ERROR and i.row is not None}

    def stats(self) -> dict:
        errors = [i for i in self.issues if i.severity == ERROR]
        by_rule: dict[str, int] = {}
        for i in self.issues:
            label = RULE_LABELS.get(i.rule, i.rule)
            by_rule[label] = by_rule.get(label, 0) + 1
        return {
            "ファイル": self.table.path.name,
            "設定": self.profile.name,
            "文字コード": self.table.encoding_label,
            "データ行数": len(self.cleaned),
            "正常な行数": len(self.valid),
            "エラーのある行数": len(self.error_rows),
            "エラー件数": len(errors),
            "注意件数": sum(1 for i in self.issues if i.severity == WARNING),
            "重複（2件目以降）": sum(1 for i in self.issues if i.rule == "duplicate"),
            "整形で直した値": len(self.changes),
            "空行（読み飛ばし）": self.table.blank_lines,
            "チェック別の件数": by_rule,
        }


@dataclass
class RunResult:
    run_id: str
    started_at: datetime
    finished_at: datetime
    out_dir: Path | None
    main: DatasetResult
    right: DatasetResult | None
    reconcile: ReconcileResult | None
    aggregates: dict[str, pd.DataFrame]
    summary: dict
    outputs: list[Path] = field(default_factory=list)

    @property
    def issues_df(self) -> pd.DataFrame:
        issues = list(self.main.issues) + (list(self.right.issues) if self.right else [])
        return issues_to_dataframe(issues)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def process_dataset(path: Path, profile: Profile, encoding: str | None, label: str) -> DatasetResult:
    table = read_csv(path, encoding=encoding or profile.encoding, delimiter=profile.delimiter)
    col_issues = validate_columns(table.df, profile)
    if has_fatal_column_issue(col_issues):
        missing = [i.column for i in col_issues if i.rule == "missing_column" and i.severity == ERROR]
        raise ProcessingError(
            f"{label}のファイル「{table.path.name}」に必須の列がありません：{'、'.join(missing)}。"
            f"設定「{profile.name}」に合ったファイルか確かめてください。"
        )
    issues = list(col_issues)
    issues += [Issue(s.row, "", "", "field_count", s.message, ERROR) for s in table.structural_issues]
    cleaned, changes = clean_dataframe(table.df, profile)
    issues += validate_values(cleaned, profile)
    duplicates, dup_issues = find_duplicates(cleaned, profile.keys)
    issues += dup_issues
    for i in issues:
        i.file = label
    issues.sort(key=lambda i: (i.row if i.row is not None else -1))
    error_rows = {i.row for i in issues if i.severity == ERROR and i.row is not None}
    valid = cleaned[~cleaned.index.isin(error_rows)]
    return DatasetResult(label, table, profile, cleaned, changes, issues, duplicates, valid)


def run(options: RunOptions, history: HistoryStore | None = None, progress: Progress | None = None) -> RunResult:
    logger = get_logger()
    progress = progress or (lambda step, pct: None)
    started = datetime.now()
    t0 = time.perf_counter()
    run_id = started.strftime("%Y%m%d-%H%M%S-") + f"{started.microsecond // 1000:03d}"
    record = {
        "run_id": run_id,
        "開始": started.isoformat(timespec="seconds"),
        "入力ファイル": str(options.input_path),
        "照合ファイル": str(options.reconcile_path) if options.reconcile_path else "",
        "設定ファイル": str(options.profile_path),
        "状態": "失敗",
    }
    logger.info("処理開始 run_id=%s input=%s", run_id, options.input_path)
    try:
        progress("設定を読み込んでいます", 5)
        profile = load_profile(options.profile_path)
        record["設定"] = profile.name
        record["入力ファイルのSHA256"] = file_sha256(Path(options.input_path)) if Path(options.input_path).is_file() else ""

        progress("読み込み・整形・検証をしています", 15)
        left_label = profile.reconcile.left_label if (profile.reconcile and options.reconcile_path) else "入力"
        main = process_dataset(Path(options.input_path), profile, options.encoding, left_label)

        right = rec = None
        if options.reconcile_path:
            if profile.reconcile is None:
                raise ProcessingError(f"設定「{profile.name}」には照合（reconcile）の設定がありません。照合ファイルを外すか、照合の設定がある設定ファイルを選んでください。")
            progress("照合先のファイルを確かめています", 45)
            right_profile = load_profile(profile.reconcile.right_profile)
            check_reconcile_against(profile.reconcile, right_profile)
            right = process_dataset(Path(options.reconcile_path), right_profile, options.reconcile_encoding,
                                    profile.reconcile.right_label)
            progress("照合しています", 60)
            rec = reconcile(main.cleaned, right.cleaned, profile.reconcile)

        progress("集計しています", 75)
        aggregates = {a.name: aggregate(main.valid, a) for a in profile.aggregations}

        finished = datetime.now()
        summary = build_summary(run_id, started, finished, main, right, rec, aggregates)
        result = RunResult(run_id, started, finished, None, main, right, rec, aggregates, summary)

        if options.write_outputs:
            progress("ファイルに書き出しています", 85)
            result.out_dir = _make_out_dir(Path(options.output_dir), run_id, Path(options.input_path).stem)
            result.outputs = write_outputs(result)
            summary["出力先"] = str(result.out_dir)

        record.update({
            "状態": "成功",
            "データ行数": len(main.cleaned),
            "正常な行数": len(main.valid),
            "エラー件数": summary["入力ファイル"]["エラー件数"] + (summary["照合ファイル"]["エラー件数"] if right else 0),
            "注意件数": summary["入力ファイル"]["注意件数"] + (summary["照合ファイル"]["注意件数"] if right else 0),
            "照合": rec.counts if rec else {},
            "出力先": str(result.out_dir) if result.out_dir else "",
        })
        progress("完了しました", 100)
        logger.info("処理完了 run_id=%s rows=%d errors=%d", run_id, len(main.cleaned), record["エラー件数"])
        return result
    except (ProfileError, DataFileError, ProcessingError) as exc:
        record["メッセージ"] = str(exc)
        logger.warning("処理中止 run_id=%s %s", run_id, exc)
        raise
    except Exception as exc:  # 想定外：画面には内部の情報を出さず、ログに詳細を残す
        record["メッセージ"] = "想定外のエラー（詳しくはログを確認）"
        logger.error("想定外のエラー run_id=%s\n%s", run_id, traceback.format_exc())
        raise ProcessingError(f"想定外のエラーが起きました（受付番号 {run_id}）。ログファイルに詳しい内容を記録しました。") from exc
    finally:
        record["処理時間（秒）"] = round(time.perf_counter() - t0, 3)
        if history is not None:
            try:
                history.append(record)
            except OSError:
                logger.error("履歴を保存できませんでした\n%s", traceback.format_exc())


def build_summary(run_id, started, finished, main: DatasetResult, right: DatasetResult | None,
                  rec: ReconcileResult | None, aggregates: dict[str, pd.DataFrame]) -> dict:
    summary = {
        "run_id": run_id,
        "ツールの版": __version__,
        "開始": started.isoformat(timespec="seconds"),
        "終了": finished.isoformat(timespec="seconds"),
        "入力ファイル": main.stats(),
    }
    if right:
        summary["照合ファイル"] = right.stats()
    if rec:
        summary["照合"] = {"件数": rec.counts, "照合から外した行": rec.skipped,
                         "名前": {"照合元": rec.left_label, "照合先": rec.right_label}}
    summary["集計"] = list(aggregates)
    return summary


def _make_out_dir(base: Path, run_id: str, stem: str) -> Path:
    safe_stem = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in stem)[:40]
    out = base / f"{run_id}_{safe_stem}"
    out.mkdir(parents=True, exist_ok=False)
    return out


def write_outputs(result: RunResult) -> list[Path]:
    out = result.out_dir
    assert out is not None
    main = result.main
    paths = [
        write_csv(main.cleaned, out / OUTPUT_NAMES["cleaned"], include_index=True),
        write_csv(main.valid, out / OUTPUT_NAMES["valid"], include_index=False),
        write_json(dataframe_records(main.valid, include_index=False), out / OUTPUT_NAMES["valid_json"]),
        write_csv(result.issues_df, out / OUTPUT_NAMES["issues"]),
        write_csv(main.duplicates, out / OUTPUT_NAMES["duplicates"], include_index=True),
        write_csv(main.changes, out / OUTPUT_NAMES["changes"], include_index=True),
    ]
    if result.reconcile is not None:
        paths.append(write_csv(result.reconcile.table, out / OUTPUT_NAMES["reconcile"]))
    for i, (name, table) in enumerate(result.aggregates.items(), start=1):
        paths.append(write_csv(table, out / f"07-{i}_集計_{name}.csv"))
    paths.append(write_json(result.summary | {"出力ファイル": [p.name for p in paths]}, out / OUTPUT_NAMES["summary"]))
    report = out / OUTPUT_NAMES["report"]
    report.write_text(render_html(result), encoding="utf-8")
    paths.append(report)
    return paths
