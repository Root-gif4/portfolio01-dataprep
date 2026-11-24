"""CSV・JSON の読み書き。

- 文字コードは UTF-8（BOM あり・なし）と Shift_JIS（cp932）を自動で見分ける
- 列数の合わない行は読み飛ばさず、問題として記録する
- 書き出す CSV は Excel で開いても数式として動かないよう、先頭の = + - @ を無効化する
"""

from __future__ import annotations

import codecs
import csv
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

MAX_FILE_BYTES = 200 * 1024 * 1024  # 200MB
ROW_INDEX_NAME = "行番号"
ENCODING_LABELS = {"utf-8-sig": "UTF-8", "cp932": "Shift_JIS"}
_FORMULA_CHARS = ("=", "+", "-", "@", "\t", "\r")
_NUMBER_RE = re.compile(r"^[+-]?\d+(\.\d+)?$")


class DataFileError(Exception):
    """CSV ファイルが読めないときのエラー（画面にそのまま出せる文にする）。"""


@dataclass
class StructuralIssue:
    row: int
    message: str


@dataclass
class LoadedTable:
    df: pd.DataFrame
    encoding: str
    path: Path
    structural_issues: list[StructuralIssue] = field(default_factory=list)
    blank_lines: int = 0

    @property
    def encoding_label(self) -> str:
        return ENCODING_LABELS.get(self.encoding, self.encoding)


def detect_encoding(raw: bytes) -> str:
    if raw.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    try:
        raw.decode("utf-8")
        return "utf-8-sig"
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("cp932")
        return "cp932"
    except UnicodeDecodeError as exc:
        raise DataFileError(
            "文字コードを判定できませんでした。UTF-8 か Shift_JIS で保存したファイルを選んでください。"
        ) from exc


def _resolve_encoding(raw: bytes, encoding: str) -> str:
    if encoding in ("auto", "", None):
        return detect_encoding(raw)
    if encoding == "utf-8":
        return "utf-8-sig"
    if encoding == "shift_jis":
        return "cp932"
    raise DataFileError(f"文字コードの指定が正しくありません：{encoding}")


def read_csv(path: str | Path, encoding: str = "auto", delimiter: str = ",",
             max_bytes: int = MAX_FILE_BYTES) -> LoadedTable:
    """CSV をすべて文字として読み込む。行の番号（見出し＝1行目）を index にする。"""
    path = Path(path)
    if not path.is_file():
        raise DataFileError(f"ファイルが見つかりません：{path}")
    size = path.stat().st_size
    if size > max_bytes:
        raise DataFileError(f"ファイルが大きすぎます（{size / 1024 / 1024:.1f}MB）。{max_bytes // 1024 // 1024}MB までにしてください。")
    raw = path.read_bytes()
    if not raw.strip():
        raise DataFileError("ファイルが空です。")
    enc = _resolve_encoding(raw, encoding)
    try:
        text = raw.decode(enc)
    except UnicodeDecodeError as exc:
        raise DataFileError(f"指定した文字コード（{ENCODING_LABELS.get(enc, enc)}）では読めませんでした。") from exc
    if "\x00" in text:
        raise DataFileError("CSV ではないファイル（バイナリ）のようです。")

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=False)
    header: list[str] | None = None
    rows: list[list[str]] = []
    line_numbers: list[int] = []
    issues: list[StructuralIssue] = []
    blank = 0
    prev_line = 0
    try:
        for record in reader:
            start_line = prev_line + 1
            prev_line = reader.line_num
            if not any(cell.strip() for cell in record):
                blank += 1
                continue
            if header is None:
                header = [h.strip().lstrip("﻿") for h in record]
                continue
            if len(record) != len(header):
                issues.append(StructuralIssue(
                    row=start_line,
                    message=f"列の数が見出しと違います（見出し {len(header)} 列、この行 {len(record)} 列）",
                ))
                record = (record + [""] * len(header))[: len(header)]
            rows.append(record)
            line_numbers.append(start_line)
    except csv.Error as exc:
        raise DataFileError(f"CSV の形式に誤りがあります（{reader.line_num}行目付近）：{exc}") from exc

    if header is None:
        raise DataFileError("見出しの行がありません。")
    if any(h == "" for h in header):
        raise DataFileError("見出しに空欄の列があります。1行目の見出しをすべて入れてください。")
    dup = sorted({h for h in header if header.count(h) > 1})
    if dup:
        raise DataFileError(f"見出しに同じ名前の列が2つ以上あります：{', '.join(dup)}")

    df = pd.DataFrame(rows, columns=header, dtype=object)
    df.index = pd.Index(line_numbers, name=ROW_INDEX_NAME, dtype="int64")
    return LoadedTable(df=df, encoding=enc, path=path, structural_issues=issues, blank_lines=blank)


def sanitize_cell(value: Any) -> Any:
    """Excel で開いたとき数式として動かないよう、先頭が = + - @ の文字に ' を付ける（数字はそのまま）。"""
    if isinstance(value, str) and value and value.startswith(_FORMULA_CHARS) and not _NUMBER_RE.match(value):
        return "'" + value
    return value


def write_csv(df: pd.DataFrame, path: str | Path, include_index: bool = False,
              encoding: str = "utf-8-sig", sanitize: bool = True) -> Path:
    """CSV を書き出す。既定は Excel で文字化けしない UTF-8（BOM あり）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df.reset_index() if include_index else df
    with path.open("w", encoding=encoding, newline="") as f:
        writer = csv.writer(f, lineterminator="\r\n")
        writer.writerow([sanitize_cell(str(c)) if sanitize else str(c) for c in out.columns])
        for row in out.itertuples(index=False, name=None):
            cells = ["" if _is_missing(v) else (v if isinstance(v, str) else _fmt(v)) for v in row]
            writer.writerow([sanitize_cell(c) for c in cells] if sanitize else cells)
    return path


def write_json(obj: Any, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    return path


def dataframe_records(df: pd.DataFrame, include_index: bool = True) -> list[dict]:
    out = df.reset_index() if include_index else df
    records = []
    for row in out.itertuples(index=False, name=None):
        records.append({str(k): (None if _is_missing(v) else _plain(v)) for k, v in zip(out.columns, row)})
    return records


def _is_missing(v: Any) -> bool:
    try:
        return v is None or bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _fmt(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _plain(v: Any) -> Any:
    if hasattr(v, "item"):
        try:
            return v.item()
        except (ValueError, AttributeError):
            pass
    return v


def _json_default(o: Any) -> Any:
    if isinstance(o, Path):
        return str(o)
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)
