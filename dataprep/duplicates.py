"""重複データの検出。

キー列（例：注文番号）が指定されていればキーで、なければ行全体で重複を判定する。
グループの最初の行は残し、2行目以降を「重複」としてエラーにする。
キーが空欄の行は重複の判定から外す（空欄は必須チェックで見つける）。
"""

from __future__ import annotations

import pandas as pd

from .validation import ERROR, Issue

GROUP_COL = "重複グループ"
KIND_COL = "区分"
FIRST = "最初の行（残す）"
LATER = "重複（エラー）"


def find_duplicates(df: pd.DataFrame, keys: tuple[str, ...] | list[str] = ()) -> tuple[pd.DataFrame, list[Issue]]:
    keys = [k for k in keys if k in df.columns]
    subset = keys or list(df.columns)
    if df.empty or not subset:
        return _empty(df), []

    target = df[subset].fillna("").astype(str)
    if keys:
        target = target[(target != "").all(axis=1)]
    if target.empty:
        return _empty(df), []

    dup_mask = target.duplicated(keep=False)
    if not dup_mask.any():
        return _empty(df), []

    dup_rows = target[dup_mask]
    group_ids = dup_rows.groupby(subset, sort=False, dropna=False).ngroup() + 1
    later_mask = dup_rows.duplicated(keep="first")

    result = df.loc[dup_rows.index].copy()
    result.insert(0, KIND_COL, [LATER if later else FIRST for later in later_mask])
    result.insert(0, GROUP_COL, group_ids.values)
    result = result.sort_values([GROUP_COL], kind="stable")

    first_row = {}
    for row, gid, later in zip(dup_rows.index, group_ids, later_mask):
        if not later:
            first_row[gid] = row
    label = "・".join(keys) if keys else "行全体"
    issues = [
        Issue(int(row), label, " / ".join(dup_rows.loc[row].tolist()) if keys else "", "duplicate",
              f"{first_row[gid]}行目と{label}が同じです", ERROR)
        for row, gid, later in zip(dup_rows.index, group_ids, later_mask) if later
    ]
    return result, issues


def _empty(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(columns=[GROUP_COL, KIND_COL, *df.columns])
    out.index.name = df.index.name
    return out
