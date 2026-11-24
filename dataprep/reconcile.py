"""2つのファイルの照合（突き合わせ）。

キー列（例：注文番号）で2つの表を結び、次の4つに分ける。
- 一致：両方にあり、比べる列の値も同じ
- 不一致：両方にあるが、比べる列の値が違う
- 「照合元のみ」：照合元にだけある（例：入金されていない注文）
- 「照合先のみ」：照合先にだけある（例：注文の見つからない入金）
同じキーが複数あるときは最初の行だけを使い、使わなかった件数を記録する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

import pandas as pd

from .config import ReconcileSpec

MATCH = "一致"
MISMATCH = "不一致"
RESULT_COL = "照合結果"


@dataclass
class ReconcileResult:
    table: pd.DataFrame
    counts: dict[str, int]
    left_label: str
    right_label: str
    skipped: dict[str, int] = field(default_factory=dict)

    @property
    def left_only(self) -> str:
        return f"{self.left_label}のみ"

    @property
    def right_only(self) -> str:
        return f"{self.right_label}のみ"


def reconcile(left: pd.DataFrame, right: pd.DataFrame, spec: ReconcileSpec) -> ReconcileResult:
    left_only = f"{spec.left_label}のみ"
    right_only = f"{spec.right_label}のみ"
    lkeys, rkeys = list(spec.left_keys), list(spec.right_keys)

    lprep, lskip = _prepare(left, lkeys)
    rprep, rskip = _prepare(right, rkeys)
    key_names = [f"_key{i}" for i in range(len(lkeys))]
    lprep = lprep.rename(columns=dict(zip(lkeys, key_names)))
    rprep = rprep.rename(columns=dict(zip(rkeys, key_names)))

    lcols = [c.left for c in spec.compare]
    rcols = [c.right for c in spec.compare]
    lpart = lprep[key_names + ["_row"] + [c for c in dict.fromkeys(lcols) if c not in key_names]]
    rpart = rprep[key_names + ["_row"] + [c for c in dict.fromkeys(rcols) if c not in key_names]]
    lpart = lpart.add_suffix("__L").rename(columns={f"{k}__L": k for k in key_names})
    rpart = rpart.add_suffix("__R").rename(columns={f"{k}__R": k for k in key_names})

    merged = lpart.merge(rpart, on=key_names, how="outer", indicator=True, sort=False)

    out = pd.DataFrame(index=merged.index)
    out[RESULT_COL] = ""
    for name, key in zip(lkeys, key_names):
        out[name] = merged[key]
    out[f"行番号（{spec.left_label}）"] = merged["_row__L"].map(_row_text)
    out[f"行番号（{spec.right_label}）"] = merged["_row__R"].map(_row_text)

    mismatch_cols: list[list[str]] = [[] for _ in range(len(merged))]
    for cmp in spec.compare:
        lv = merged[f"{cmp.left}__L"].fillna("").astype(str)
        rv = merged[f"{cmp.right}__R"].fillna("").astype(str)
        both = merged["_merge"] == "both"
        lnum, rnum = lv.map(_to_decimal), rv.map(_to_decimal)
        numeric = lnum.notna() & rnum.notna()
        label_l = f"{cmp.left}（{spec.left_label}）"
        label_r = f"{cmp.right}（{spec.right_label}）"
        out[label_l] = lv
        out[label_r] = rv
        diff = pd.Series([""] * len(merged), index=merged.index, dtype=object)
        tol = Decimal(str(cmp.tolerance))
        for i in merged.index:
            if not both[i]:
                continue
            if numeric[i]:
                d = lnum[i] - rnum[i]
                diff[i] = _num_text(d)
                same = abs(d) <= tol
            else:
                same = lv[i] == rv[i]
            if not same:
                mismatch_cols[i].append(cmp.left if cmp.left == cmp.right else f"{cmp.left}／{cmp.right}")
        if numeric[both].any():
            out[f"差額（{cmp.left}）"] = diff

    results = []
    for i, state in merged["_merge"].items():
        if state == "left_only":
            results.append(left_only)
        elif state == "right_only":
            results.append(right_only)
        else:
            results.append(MISMATCH if mismatch_cols[i] else MATCH)
    out[RESULT_COL] = results
    out["違う項目"] = ["・".join(m) for m in mismatch_cols]

    order = {MISMATCH: 0, left_only: 1, right_only: 2, MATCH: 3}
    out["_order"] = out[RESULT_COL].map(order)
    out = out.sort_values(["_order", *lkeys], kind="stable").drop(columns="_order").reset_index(drop=True)

    counts = {label: int((out[RESULT_COL] == label).sum()) for label in (MATCH, MISMATCH, left_only, right_only)}
    skipped = {
        f"{spec.left_label}：キーが空欄": lskip["empty"],
        f"{spec.left_label}：キーの重複（2件目以降）": lskip["dup"],
        f"{spec.right_label}：キーが空欄": rskip["empty"],
        f"{spec.right_label}：キーの重複（2件目以降）": rskip["dup"],
    }
    return ReconcileResult(table=out, counts=counts, left_label=spec.left_label,
                           right_label=spec.right_label, skipped=skipped)


def _prepare(df: pd.DataFrame, keys: list[str]) -> tuple[pd.DataFrame, dict[str, int]]:
    work = df.copy()
    work["_row"] = work.index
    for k in keys:
        work[k] = work[k].fillna("").astype(str)
    empty = (work[keys] == "").any(axis=1)
    work = work[~empty]
    dup = work.duplicated(subset=keys, keep="first")
    return work[~dup].reset_index(drop=True), {"empty": int(empty.sum()), "dup": int(dup.sum())}


def _to_decimal(value: str) -> Decimal | None:
    if value == "":
        return None
    try:
        d = Decimal(value)
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _num_text(d: Decimal) -> str:
    return format(d.quantize(Decimal(1)) if d == d.to_integral() else d.normalize(), "f")


def _row_text(v) -> str:
    if v is None or pd.isna(v):
        return ""
    return str(int(v))
