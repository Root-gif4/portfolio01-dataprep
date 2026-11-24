"""集計：設定に書いた切り口（月別・商品別など）で合計・件数などを出す。

最後の行に全体の「合計」を付ける。
"""

from __future__ import annotations

from decimal import Decimal

import pandas as pd

from .config import Aggregation, Metric

TOTAL_LABEL = "合計"
UNKNOWN_LABEL = "（不明）"


def group_label(spec: str) -> str:
    col, _, suffix = spec.partition(":")
    return {"month": f"{col}（月）", "year": f"{col}（年）"}.get(suffix, col)


def _group_series(df: pd.DataFrame, spec: str) -> pd.Series:
    col, _, suffix = spec.partition(":")
    s = df[col].fillna("").astype(str)
    if suffix == "month":
        s = s.where(s.str.match(r"^\d{4}-\d{2}-\d{2}$"), "").str[:7]
    elif suffix == "year":
        s = s.where(s.str.match(r"^\d{4}-\d{2}-\d{2}$"), "").str[:4]
    return s.replace("", UNKNOWN_LABEL)


def _metric_value(frame: pd.DataFrame, metric: Metric):
    if metric.func == "count":
        return len(frame)
    values = frame[metric.column].fillna("").astype(str)
    if metric.func == "nunique":
        return int(values[values != ""].nunique())
    nums = pd.to_numeric(values.where(values != ""), errors="coerce").dropna()
    if nums.empty:
        return None
    if metric.func == "sum":
        return _tidy(sum(Decimal(str(v)) for v in values[nums.index]))
    if metric.func == "mean":
        return round(float(nums.mean()), 2)
    if metric.func == "min":
        return _tidy(Decimal(str(values[nums.idxmin()])))
    if metric.func == "max":
        return _tidy(Decimal(str(values[nums.idxmax()])))
    raise ValueError(metric.func)


def _tidy(d: Decimal):
    return int(d) if d == d.to_integral() else float(d)


def aggregate(df: pd.DataFrame, spec: Aggregation, add_total: bool = True) -> pd.DataFrame:
    labels = [group_label(g) for g in spec.group_by]
    columns = labels + [m.label for m in spec.metrics]
    if not spec.group_by:
        row = {m.label: _metric_value(df, m) for m in spec.metrics}
        return pd.DataFrame([row], columns=columns)

    keys = pd.DataFrame({label: _group_series(df, g) for label, g in zip(labels, spec.group_by)}, index=df.index)
    rows = []
    if not df.empty:
        for key, idx in keys.groupby(labels if len(labels) > 1 else labels[0], sort=True).groups.items():
            key = key if isinstance(key, tuple) else (key,)
            part = df.loc[idx]
            rows.append({**dict(zip(labels, key)), **{m.label: _metric_value(part, m) for m in spec.metrics}})
    result = pd.DataFrame(rows, columns=columns)
    if add_total:
        total = {label: "" for label in labels}
        total[labels[0]] = TOTAL_LABEL
        total.update({m.label: _metric_value(df, m) if not df.empty else (0 if m.func in ("count", "nunique") else None)
                      for m in spec.metrics})
        result = pd.concat([result, pd.DataFrame([total], columns=columns)], ignore_index=True)
    return result
