"""検証：必須項目・データ形式・値の範囲・行のルールをチェックする。"""

from __future__ import annotations

import operator
import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

import pandas as pd

from .config import ColumnRule, Profile, RowRule

ERROR = "エラー"
WARNING = "注意"

RULE_LABELS = {
    "missing_column": "列がない",
    "extra_column": "設定にない列",
    "field_count": "列の数",
    "required": "必須項目",
    "type": "データ形式",
    "pattern": "書き方（パターン）",
    "min": "最小値",
    "max": "最大値",
    "max_length": "文字数",
    "allowed": "使える値",
    "row_rule": "行のルール",
    "duplicate": "重複",
}

ISSUE_COLUMNS = ["ファイル", "行番号", "列", "値", "チェック", "内容", "重要度"]

_TYPE_PATTERNS = {
    "int": re.compile(r"^-?\d+$"),
    "decimal": re.compile(r"^-?\d+(\.\d+)?$"),
    "date": re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    "email": re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$"),
    "phone": re.compile(r"^(0\d{9,10}|0\d{1,4}-\d{1,4}-\d{3,4}|\+\d{1,3}-?\d{1,4}-?\d{1,4}-?\d{3,4})$"),
}
_TYPE_MESSAGES = {
    "int": "整数ではありません",
    "decimal": "数字ではありません",
    "date": "日付として読めません（例：2026-01-05）",
    "email": "メールアドレスの形ではありません",
    "phone": "電話番号の形ではありません（例：03-1234-5678）",
}
_OPS = {"<": operator.lt, "<=": operator.le, "==": operator.eq, "!=": operator.ne, ">=": operator.ge, ">": operator.gt}


@dataclass
class Issue:
    row: int | None
    column: str
    value: str
    rule: str
    message: str
    severity: str = ERROR
    file: str = ""

    def as_row(self) -> dict:
        return {
            "ファイル": self.file,
            "行番号": "" if self.row is None else self.row,
            "列": self.column,
            "値": self.value,
            "チェック": RULE_LABELS.get(self.rule, self.rule),
            "内容": self.message,
            "重要度": self.severity,
        }


def issues_to_dataframe(issues: list[Issue]) -> pd.DataFrame:
    return pd.DataFrame([i.as_row() for i in issues], columns=ISSUE_COLUMNS)


def validate_columns(df: pd.DataFrame, profile: Profile) -> list[Issue]:
    """見出しの列が設定とあっているか。必須の列がないときは処理を続けられない。"""
    issues: list[Issue] = []
    present = set(df.columns)
    for col in profile.columns:
        if col.name not in present:
            if col.required or col.name in profile.keys:
                issues.append(Issue(None, col.name, "", "missing_column", "必須の列がファイルにありません", ERROR))
            else:
                issues.append(Issue(None, col.name, "", "missing_column", "設定にある列がファイルにありません", WARNING))
    if not profile.allow_extra_columns:
        known = set(profile.column_names)
        for col in df.columns:
            if col not in known:
                issues.append(Issue(None, col, "", "extra_column", "設定にない列です", WARNING))
    return issues


def has_fatal_column_issue(issues: list[Issue]) -> bool:
    return any(i.rule == "missing_column" and i.severity == ERROR for i in issues)


def validate_values(df: pd.DataFrame, profile: Profile) -> list[Issue]:
    issues: list[Issue] = []
    for rule in profile.columns:
        if rule.name in df.columns:
            issues.extend(_validate_column(df[rule.name].fillna("").astype(str), rule))
    for row_rule in profile.row_rules:
        if all(c in df.columns for c in row_rule.columns):
            issues.extend(_validate_row_rule(df, row_rule, profile))
    issues.sort(key=lambda i: (i.row if i.row is not None else -1))
    return issues


def type_ok_mask(series: pd.Series, rule: ColumnRule) -> pd.Series:
    """空欄でなく、型としても正しい値なら True。"""
    s = series.fillna("").astype(str)
    nonempty = s != ""
    pattern = _TYPE_PATTERNS.get(rule.type)
    if pattern is None:
        return nonempty
    ok = nonempty & s.map(lambda v: bool(pattern.match(v)))
    if rule.type == "date":
        ok &= s.map(_is_real_date)
    return ok


def _validate_column(series: pd.Series, rule: ColumnRule) -> list[Issue]:
    issues: list[Issue] = []
    name = rule.name
    empty = series == ""
    if rule.required:
        for row in series.index[empty]:
            issues.append(Issue(int(row), name, "", "required", "必須項目が空欄です"))

    nonempty = ~empty
    ok = type_ok_mask(series, rule)
    if rule.type in _TYPE_PATTERNS:
        for row, value in series[nonempty & ~ok].items():
            issues.append(Issue(int(row), name, value, "type", _TYPE_MESSAGES[rule.type]))

    checked = series[ok]
    if rule.type in ("int", "decimal") and (rule.min is not None or rule.max is not None):
        nums = checked.map(Decimal)
        if rule.min is not None:
            low = Decimal(str(rule.min))
            for row, value in checked[nums < low].items():
                issues.append(Issue(int(row), name, value, "min", f"{_num_text(rule.min)} 以上にしてください"))
        if rule.max is not None:
            high = Decimal(str(rule.max))
            for row, value in checked[nums > high].items():
                issues.append(Issue(int(row), name, value, "max", f"{_num_text(rule.max)} 以下にしてください"))
    if rule.max_length is not None:
        for row, value in checked[checked.str.len() > rule.max_length].items():
            issues.append(Issue(int(row), name, value, "max_length", f"{rule.max_length} 文字以内にしてください（{len(value)} 文字）"))
    if rule.pattern:
        regex = re.compile(rule.pattern)
        for row, value in checked[~checked.map(lambda v: bool(regex.fullmatch(v)))].items():
            issues.append(Issue(int(row), name, value, "pattern", "決められた書き方になっていません"))
    if rule.allowed:
        allowed = set(rule.allowed)
        for row, value in checked[~checked.isin(allowed)].items():
            issues.append(Issue(int(row), name, value, "allowed", "使える値ではありません（" + "・".join(rule.allowed) + "）"))
    return issues


def _validate_row_rule(df: pd.DataFrame, rule: RowRule, profile: Profile) -> list[Issue]:
    issues: list[Issue] = []
    if rule.type == "product_equals":
        cols = [rule.target, *rule.factors]
        for row, values in df[cols].iterrows():
            nums = [_to_decimal(v) for v in values]
            if any(n is None for n in nums):
                continue  # 数字でない値は、列のチェックですでにエラーになっている
            product = Decimal(1)
            for n in nums[1:]:
                product *= n
            if nums[0] != product:
                issues.append(Issue(int(row), rule.target, str(values.iloc[0]), "row_rule",
                                    f"{rule.message}（計算値 {_num_text(product)}）"))
    else:
        left_rule = profile.column(rule.left)
        right_rule = profile.column(rule.right)
        op = _OPS[rule.op]
        for row, (lv, rv) in df[[rule.left, rule.right]].iterrows():
            lval, rval = _comparable(lv, left_rule), _comparable(rv, right_rule)
            if lval is None or rval is None or type(lval) is not type(rval):
                continue
            if not op(lval, rval):
                issues.append(Issue(int(row), rule.left, f"{lv} / {rv}", "row_rule", rule.message))
    return issues


def _comparable(value, rule: ColumnRule | None):
    value = "" if value is None else str(value)
    if value == "":
        return None
    if rule is not None and rule.type == "date":
        return value if _is_real_date(value) else None
    return _to_decimal(value)


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    text = str(value)
    if not _TYPE_PATTERNS["decimal"].match(text):
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _is_real_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _num_text(v) -> str:
    d = Decimal(str(v))
    return format(d.quantize(Decimal(1)) if d == d.to_integral() else d.normalize(), "f")


def issue_dicts(issues: list[Issue]) -> list[dict]:
    return [asdict(i) for i in issues]
