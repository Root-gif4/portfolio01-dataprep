from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dataprep.config import parse_profile  # noqa: E402


@pytest.fixture
def root() -> Path:
    return ROOT


def make_df(rows: list[dict], start: int = 2) -> pd.DataFrame:
    """テスト用の表。行番号は CSV と同じく 2 から始める。"""
    df = pd.DataFrame(rows, dtype=object)
    df.index = pd.Index(range(start, start + len(df)), name="行番号")
    return df


@pytest.fixture
def simple_profile():
    return parse_profile({
        "name": "テスト",
        "keys": ["ID"],
        "columns": [
            {"name": "ID", "type": "code", "required": True, "upper": True, "pattern": "^A-\\d{3}$"},
            {"name": "日付", "type": "date", "required": True},
            {"name": "名前", "type": "string", "required": True, "max_length": 5},
            {"name": "メール", "type": "email"},
            {"name": "電話", "type": "phone"},
            {"name": "数量", "type": "int", "min": 1, "max": 10},
            {"name": "単価", "type": "int", "min": 0},
            {"name": "金額", "type": "int"},
            {"name": "区分", "type": "string", "allowed": ["通常", "特急"]},
        ],
        "row_rules": [{"type": "product_equals", "target": "金額", "factors": ["数量", "単価"]}],
    })


def write_text(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_bytes(text.encode(encoding))
    return path
