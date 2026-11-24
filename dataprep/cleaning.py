"""データの整形（表記ゆれの統一）。

整形では値を「直せる範囲」で直すだけで、直せない値はそのまま残す。
正しいかどうかの判定は validation（検証）で行う。
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

import pandas as pd

from .config import ColumnRule, Profile

# 電話番号などで「-」の代わりに使われがちな文字
_DASHES = "‐‑‒–—―ーｰ−－"
_DASH_TABLE = str.maketrans({c: "-" for c in _DASHES})
_DATE_PATTERNS = (
    re.compile(r"^(\d{4})[/\-.年](\d{1,2})[/\-.月](\d{1,2})日?(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?$"),
    re.compile(r"^(\d{4})(\d{2})(\d{2})$"),
)
_SPACES = re.compile(r"\s+")


def nfkc(value: str) -> str:
    """全角英数字・記号を半角に、半角カナを全角にそろえる。"""
    return unicodedata.normalize("NFKC", value)


def clean_string(value: str, use_nfkc: bool = False) -> str:
    value = value.strip()
    if use_nfkc:
        value = nfkc(value).strip()
    return value


def clean_number(value: str) -> str:
    """「１，２００円」「¥1,200」「▲500」などを「1200」「-500」にする。"""
    v = nfkc(value).strip()
    if not v:
        return v
    v = v.translate(_DASH_TABLE)
    negative = v.startswith(("▲", "△"))
    if negative:
        v = v[1:]
    v = v.replace(",", "").replace("円", "").replace("¥", "").replace("\\", "")
    v = _SPACES.sub("", v)
    if negative and v and not v.startswith("-"):
        v = "-" + v
    return v


def clean_date(value: str) -> str:
    """「2026/1/5」「2026年1月5日」「20260105」などを「2026-01-05」にする。"""
    v = nfkc(value).strip()
    for pattern in _DATE_PATTERNS:
        m = pattern.match(v)
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            except ValueError:
                return v  # 2月30日など、ありえない日付はそのまま（検証でエラーにする）
    return v


def clean_phone(value: str) -> str:
    v = nfkc(value).strip().translate(_DASH_TABLE)
    return _SPACES.sub("", v)


def clean_email(value: str) -> str:
    return nfkc(value).strip().lower()


def clean_code(value: str, upper: bool = False) -> str:
    v = nfkc(value).strip().translate(_DASH_TABLE)
    return v.upper() if upper else v


def clean_value(value: str, rule: ColumnRule) -> str:
    if value is None:
        return ""
    value = str(value)
    if rule.type in ("int", "decimal"):
        return clean_number(value)
    if rule.type == "date":
        return clean_date(value)
    if rule.type == "phone":
        return clean_phone(value)
    if rule.type == "email":
        return clean_email(value)
    if rule.type == "code":
        return clean_code(value, rule.upper)
    v = clean_string(value, rule.use_nfkc)
    return v.upper() if rule.upper else v


def clean_dataframe(df: pd.DataFrame, profile: Profile) -> tuple[pd.DataFrame, pd.DataFrame]:
    """設定に沿ってすべての列を整形する。

    戻り値：(整形後の表, 変更の記録［行番号・列・変更前・変更後］)
    """
    cleaned = df.copy()
    changes: list[pd.DataFrame] = []
    for col in df.columns:
        rule = profile.column(col)
        before = df[col].fillna("").astype(str)
        if rule is None:
            after = before.map(str.strip)
        else:
            after = before.map(lambda v, r=rule: clean_value(v, r))
        cleaned[col] = after
        diff = before != after
        if diff.any():
            changes.append(pd.DataFrame({
                "列": col,
                "変更前": before[diff],
                "変更後": after[diff],
            }))
    if changes:
        change_df = pd.concat(changes).sort_index(kind="stable")
    else:
        change_df = pd.DataFrame(columns=["列", "変更前", "変更後"])
        change_df.index.name = df.index.name
    return cleaned, change_df
