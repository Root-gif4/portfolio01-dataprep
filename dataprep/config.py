"""処理設定（プロファイル）の読み込みとチェック。

プロファイルは JSON ファイルで、CSV の列ごとの型・必須・形式、重複を判定するキー、
行をまたぐルール、集計、照合の設定を持つ。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

COLUMN_TYPES = ("string", "int", "decimal", "date", "email", "phone", "code")
NUMERIC_TYPES = ("int", "decimal")
AGG_FUNCS = ("sum", "count", "mean", "min", "max", "nunique")
GROUP_SUFFIXES = ("month", "year")
COMPARE_OPS = ("<", "<=", "==", "!=", ">=", ">")
ROW_RULE_TYPES = ("product_equals", "compare")
ENCODINGS = ("auto", "utf-8", "shift_jis")
MAX_PROFILE_BYTES = 1024 * 1024


class ProfileError(ValueError):
    """プロファイルの内容に誤りがあるときのエラー。"""


@dataclass(frozen=True)
class ColumnRule:
    name: str
    type: str = "string"
    required: bool = False
    pattern: str | None = None
    min: float | None = None
    max: float | None = None
    max_length: int | None = None
    allowed: tuple[str, ...] | None = None
    nfkc: bool | None = None
    upper: bool = False

    @property
    def use_nfkc(self) -> bool:
        """全角→半角の正規化を行うか。文字列以外は既定で行う。"""
        if self.nfkc is not None:
            return self.nfkc
        return self.type != "string"


@dataclass(frozen=True)
class RowRule:
    type: str
    message: str
    target: str | None = None
    factors: tuple[str, ...] = ()
    left: str | None = None
    op: str | None = None
    right: str | None = None

    @property
    def columns(self) -> tuple[str, ...]:
        if self.type == "product_equals":
            return (self.target or "", *self.factors)
        return (self.left or "", self.right or "")


@dataclass(frozen=True)
class Metric:
    func: str
    label: str
    column: str | None = None


@dataclass(frozen=True)
class Aggregation:
    name: str
    group_by: tuple[str, ...]
    metrics: tuple[Metric, ...]


@dataclass(frozen=True)
class CompareSpec:
    left: str
    right: str
    tolerance: float = 0.0


@dataclass(frozen=True)
class ReconcileSpec:
    right_profile: Path
    left_keys: tuple[str, ...]
    right_keys: tuple[str, ...]
    compare: tuple[CompareSpec, ...]
    left_label: str = "照合元"
    right_label: str = "照合先"


@dataclass(frozen=True)
class Profile:
    name: str
    columns: tuple[ColumnRule, ...]
    description: str = ""
    encoding: str = "auto"
    delimiter: str = ","
    keys: tuple[str, ...] = ()
    allow_extra_columns: bool = True
    row_rules: tuple[RowRule, ...] = ()
    aggregations: tuple[Aggregation, ...] = ()
    reconcile: ReconcileSpec | None = None
    source_path: Path | None = field(default=None, compare=False)

    def column(self, name: str) -> ColumnRule | None:
        for col in self.columns:
            if col.name == name:
                return col
        return None

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)


# ---------------------------------------------------------------- 読み込み


def load_profile(path: str | Path) -> Profile:
    """JSON ファイルからプロファイルを読み込み、内容をチェックして返す。"""
    path = Path(path)
    if not path.is_file():
        raise ProfileError(f"設定ファイルが見つかりません：{path}")
    if path.stat().st_size > MAX_PROFILE_BYTES:
        raise ProfileError("設定ファイルが大きすぎます（1MBまで）。")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ProfileError(
            f"設定ファイルの書き方に誤りがあります（{exc.lineno}行目 {exc.colno}文字目）：{exc.msg}"
        ) from exc
    except UnicodeDecodeError as exc:
        raise ProfileError("設定ファイルは UTF-8 で保存してください。") from exc
    return parse_profile(data, base_dir=path.parent, source_path=path)


def parse_profile(data: Any, base_dir: Path | None = None, source_path: Path | None = None) -> Profile:
    """辞書からプロファイルを作る（テストでも使う）。"""
    if not isinstance(data, dict):
        raise ProfileError("設定ファイルの一番外側は { } で囲んでください。")

    name = _str(data, "name", "設定", required=True)
    columns = tuple(_parse_column(c, i) for i, c in enumerate(_list(data, "columns", "設定", required=True)))
    if not columns:
        raise ProfileError("columns に列を1つ以上書いてください。")
    names = [c.name for c in columns]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        raise ProfileError(f"columns に同じ列名が2回以上あります：{', '.join(dup)}")

    encoding = _str(data, "encoding", "設定") or "auto"
    if encoding not in ENCODINGS:
        raise ProfileError(f"encoding は {', '.join(ENCODINGS)} のどれかにしてください。")
    delimiter = _str(data, "delimiter", "設定") or ","
    if delimiter == "\\t":
        delimiter = "\t"
    if len(delimiter) != 1:
        raise ProfileError("delimiter（区切り文字）は1文字にしてください。")

    keys = tuple(_str_list(data, "keys", "設定"))
    _check_known(keys, names, "keys")

    row_rules = tuple(_parse_row_rule(r, i, names) for i, r in enumerate(_list(data, "row_rules", "設定")))
    aggregations = tuple(_parse_aggregation(a, i, columns) for i, a in enumerate(_list(data, "aggregations", "設定")))
    agg_names = [a.name for a in aggregations]
    if len(set(agg_names)) != len(agg_names):
        raise ProfileError("aggregations の name が重複しています。")

    reconcile = None
    if data.get("reconcile") is not None:
        reconcile = _parse_reconcile(data["reconcile"], names, base_dir or Path.cwd())

    allow_extra = data.get("allow_extra_columns", True)
    if not isinstance(allow_extra, bool):
        raise ProfileError("allow_extra_columns は true か false にしてください。")

    return Profile(
        name=name,
        description=_str(data, "description", "設定") or "",
        columns=columns,
        encoding=encoding,
        delimiter=delimiter,
        keys=keys,
        allow_extra_columns=allow_extra,
        row_rules=row_rules,
        aggregations=aggregations,
        reconcile=reconcile,
        source_path=source_path,
    )


def _parse_column(raw: Any, index: int) -> ColumnRule:
    where = f"columns の {index + 1} 番目"
    if not isinstance(raw, dict):
        raise ProfileError(f"{where} は {{ }} で書いてください。")
    name = _str(raw, "name", where, required=True)
    where = f"列「{name}」"
    col_type = _str(raw, "type", where) or "string"
    if col_type not in COLUMN_TYPES:
        raise ProfileError(f"{where} の type は {', '.join(COLUMN_TYPES)} のどれかにしてください。")

    pattern = _str(raw, "pattern", where)
    if pattern:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ProfileError(f"{where} の pattern（正規表現）に誤りがあります：{exc}") from exc

    min_v = _num(raw, "min", where)
    max_v = _num(raw, "max", where)
    if (min_v is not None or max_v is not None) and col_type not in NUMERIC_TYPES:
        raise ProfileError(f"{where}：min・max は type が int か decimal の列だけに使えます。")
    if min_v is not None and max_v is not None and min_v > max_v:
        raise ProfileError(f"{where}：min が max より大きくなっています。")

    max_length = raw.get("max_length")
    if max_length is not None and (not isinstance(max_length, int) or isinstance(max_length, bool) or max_length < 1):
        raise ProfileError(f"{where} の max_length は1以上の整数にしてください。")

    allowed = raw.get("allowed")
    if allowed is not None:
        if not isinstance(allowed, list) or not all(isinstance(v, str) for v in allowed) or not allowed:
            raise ProfileError(f"{where} の allowed は文字の一覧（例：[\"A\", \"B\"]）にしてください。")
        allowed = tuple(allowed)

    return ColumnRule(
        name=name,
        type=col_type,
        required=_bool(raw, "required", where, False),
        pattern=pattern,
        min=min_v,
        max=max_v,
        max_length=max_length,
        allowed=allowed,
        nfkc=_bool(raw, "nfkc", where, None),
        upper=_bool(raw, "upper", where, False),
    )


def _parse_row_rule(raw: Any, index: int, names: list[str]) -> RowRule:
    where = f"row_rules の {index + 1} 番目"
    if not isinstance(raw, dict):
        raise ProfileError(f"{where} は {{ }} で書いてください。")
    rule_type = _str(raw, "type", where, required=True)
    if rule_type not in ROW_RULE_TYPES:
        raise ProfileError(f"{where} の type は {', '.join(ROW_RULE_TYPES)} のどれかにしてください。")
    message = _str(raw, "message", where) or ""
    if rule_type == "product_equals":
        target = _str(raw, "target", where, required=True)
        factors = tuple(_str_list(raw, "factors", where))
        if len(factors) < 2:
            raise ProfileError(f"{where} の factors には列を2つ以上書いてください。")
        rule = RowRule(type=rule_type, message=message or f"{target} が {'×'.join(factors)} と合いません", target=target, factors=factors)
    else:
        left = _str(raw, "left", where, required=True)
        right = _str(raw, "right", where, required=True)
        op = _str(raw, "op", where, required=True)
        if op not in COMPARE_OPS:
            raise ProfileError(f"{where} の op は {' '.join(COMPARE_OPS)} のどれかにしてください。")
        rule = RowRule(type=rule_type, message=message or f"{left} {op} {right} になっていません", left=left, op=op, right=right)
    _check_known(rule.columns, names, where)
    return rule


def _parse_aggregation(raw: Any, index: int, columns: tuple[ColumnRule, ...]) -> Aggregation:
    where = f"aggregations の {index + 1} 番目"
    if not isinstance(raw, dict):
        raise ProfileError(f"{where} は {{ }} で書いてください。")
    name = _str(raw, "name", where, required=True)
    if not re.fullmatch(r"[^\\/:*?\"<>|]+", name):
        raise ProfileError(f"{where} の name に ファイル名に使えない文字（\\ / : * ? \" < > |）が入っています。")
    where = f"集計「{name}」"
    by_name = {c.name: c for c in columns}
    group_by = tuple(_str_list(raw, "group_by", where))
    for g in group_by:
        col, _, suffix = g.partition(":")
        if col not in by_name:
            raise ProfileError(f"{where} の group_by に columns にない列「{col}」があります。")
        if suffix:
            if suffix not in GROUP_SUFFIXES:
                raise ProfileError(f"{where}：「{g}」の : の後は month か year にしてください。")
            if by_name[col].type != "date":
                raise ProfileError(f"{where}：「{g}」の :{suffix} は type が date の列だけに使えます。")
    metrics = []
    for j, m in enumerate(_list(raw, "metrics", where, required=True)):
        mwhere = f"{where} の metrics の {j + 1} 番目"
        if not isinstance(m, dict):
            raise ProfileError(f"{mwhere} は {{ }} で書いてください。")
        func = _str(m, "func", mwhere, required=True)
        if func not in AGG_FUNCS:
            raise ProfileError(f"{mwhere} の func は {', '.join(AGG_FUNCS)} のどれかにしてください。")
        column = _str(m, "column", mwhere)
        if func != "count" and not column:
            raise ProfileError(f"{mwhere}：func が {func} のときは column が必要です。")
        if column:
            if column not in by_name:
                raise ProfileError(f"{mwhere} の column に columns にない列「{column}」があります。")
            if func in ("sum", "mean") and by_name[column].type not in NUMERIC_TYPES:
                raise ProfileError(f"{mwhere}：{func} は type が int か decimal の列だけに使えます。")
        label = _str(m, "label", mwhere) or (f"{column}_{func}" if column else "件数")
        metrics.append(Metric(func=func, label=label, column=column))
    if not metrics:
        raise ProfileError(f"{where} の metrics を1つ以上書いてください。")
    labels = [m.label for m in metrics] + list(group_by)
    if len(set(labels)) != len(labels):
        raise ProfileError(f"{where}：metrics の label が group_by や他の label と重なっています。")
    return Aggregation(name=name, group_by=group_by, metrics=tuple(metrics))


def _parse_reconcile(raw: Any, names: list[str], base_dir: Path) -> ReconcileSpec:
    where = "reconcile"
    if not isinstance(raw, dict):
        raise ProfileError("reconcile は { } で書いてください。")
    right_profile = _str(raw, "right_profile", where, required=True)
    left_keys = tuple(_str_list(raw, "left_keys", where))
    right_keys = tuple(_str_list(raw, "right_keys", where))
    if not left_keys or len(left_keys) != len(right_keys):
        raise ProfileError("reconcile の left_keys と right_keys は同じ数（1つ以上）にしてください。")
    _check_known(left_keys, names, "reconcile の left_keys")
    compare = []
    for j, c in enumerate(_list(raw, "compare", where)):
        cwhere = f"reconcile の compare の {j + 1} 番目"
        if not isinstance(c, dict):
            raise ProfileError(f"{cwhere} は {{ }} で書いてください。")
        left = _str(c, "left", cwhere, required=True)
        right = _str(c, "right", cwhere, required=True)
        _check_known((left,), names, cwhere)
        if left in left_keys or right in right_keys:
            raise ProfileError(f"{cwhere}：キーの列は比べる列（compare）に入れられません。")
        tol = _num(c, "tolerance", cwhere) or 0.0
        if tol < 0:
            raise ProfileError(f"{cwhere} の tolerance は0以上にしてください。")
        compare.append(CompareSpec(left=left, right=right, tolerance=tol))
    return ReconcileSpec(
        right_profile=(base_dir / right_profile).resolve(),
        left_keys=left_keys,
        right_keys=right_keys,
        compare=tuple(compare),
        left_label=_str(raw, "left_label", where) or "照合元",
        right_label=_str(raw, "right_label", where) or "照合先",
    )


def check_reconcile_against(spec: ReconcileSpec, right: Profile) -> None:
    """照合先のプロファイルに、照合で使う列があるかを確かめる。"""
    names = list(right.column_names)
    _check_known(spec.right_keys, names, "reconcile の right_keys（照合先の設定）")
    _check_known(tuple(c.right for c in spec.compare), names, "reconcile の compare の right（照合先の設定）")


# ---------------------------------------------------------------- 小さな部品


def _str(raw: dict, key: str, where: str, required: bool = False) -> str | None:
    value = raw.get(key)
    if value is None or value == "":
        if required:
            raise ProfileError(f"{where} に {key} がありません。")
        return None
    if not isinstance(value, str):
        raise ProfileError(f"{where} の {key} は文字（\"〜\"）で書いてください。")
    return value


def _list(raw: dict, key: str, where: str, required: bool = False) -> list:
    value = raw.get(key)
    if value is None:
        if required:
            raise ProfileError(f"{where} に {key} がありません。")
        return []
    if not isinstance(value, list):
        raise ProfileError(f"{where} の {key} は [ ] で書いてください。")
    return value


def _str_list(raw: dict, key: str, where: str) -> list[str]:
    values = _list(raw, key, where)
    if not all(isinstance(v, str) and v for v in values):
        raise ProfileError(f"{where} の {key} は列名の一覧（例：[\"注文番号\"]）にしてください。")
    return values


def _num(raw: dict, key: str, where: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"{where} の {key} は数字で書いてください。")
    return float(value)


def _bool(raw: dict, key: str, where: str, default):
    value = raw.get(key, default)
    if value is not default and not isinstance(value, bool):
        raise ProfileError(f"{where} の {key} は true か false にしてください。")
    return value


def _check_known(cols, names, where: str) -> None:
    unknown = [c for c in cols if c not in names]
    if unknown:
        raise ProfileError(f"{where} に columns にない列があります：{', '.join(unknown)}")
