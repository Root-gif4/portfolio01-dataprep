"""処理結果の HTML レポート。値はすべて html.escape してから埋め込む（XSS 対策）。"""

from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING

import pandas as pd

from .reconcile import MATCH, RESULT_COL

if TYPE_CHECKING:
    from .pipeline import DatasetResult, RunResult

MAX_ROWS = 200

_CSS = """
body{font-family:"Yu Gothic UI","Meiryo",sans-serif;margin:0;background:#f5f7fa;color:#1f2933}
header{background:#1e3a5f;color:#fff;padding:20px 32px}
header h1{margin:0;font-size:22px}
header p{margin:6px 0 0;opacity:.85;font-size:13px}
main{max-width:1100px;margin:0 auto;padding:24px 32px 48px}
section{background:#fff;border-radius:10px;padding:20px 24px;margin-bottom:20px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
h2{font-size:17px;margin:0 0 14px;border-left:4px solid #2f80ed;padding-left:10px}
h3{font-size:15px;margin:18px 0 8px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card{border:1px solid #e3e8ef;border-radius:8px;padding:12px 14px}
.card .label{font-size:12px;color:#52606d}
.card .value{font-size:24px;font-weight:700;margin-top:4px}
.card.ok .value{color:#1e8e3e}.card.ng .value{color:#c62828}.card.warn .value{color:#b26a00}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid #e3e8ef;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#eef2f7;font-weight:600}
td.num{text-align:right;font-variant-numeric:tabular-nums}
tr.total td{font-weight:700;background:#fafbfc}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:12px}
.b-err{background:#fde8e8;color:#c62828}.b-warn{background:#fff4e0;color:#b26a00}.b-ok{background:#e6f4ea;color:#1e8e3e}
.note{font-size:12px;color:#52606d}
dl{display:grid;grid-template-columns:max-content 1fr;gap:4px 16px;font-size:13px;margin:0}
dt{color:#52606d}
"""


def _cell(value) -> str:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    return escape(str(value))


def _is_num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def table_html(df: pd.DataFrame, max_rows: int = MAX_ROWS, total_label: str | None = None) -> str:
    if df.empty:
        return '<p class="note">該当するデータはありません。</p>'
    head = "".join(f"<th>{escape(str(c))}</th>" for c in df.columns)
    body = []
    for row in df.head(max_rows).itertuples(index=False, name=None):
        cls = ' class="total"' if total_label is not None and row and row[0] == total_label else ""
        tds = "".join(
            f'<td class="num">{_cell(_fmt_num(v))}</td>' if _is_num(v) else f"<td>{_cell(v)}</td>" for v in row
        )
        body.append(f"<tr{cls}>{tds}</tr>")
    more = ""
    if len(df) > max_rows:
        more = f'<p class="note">先頭の {max_rows} 件だけを表示しています（全 {len(df)} 件は CSV を見てください）。</p>'
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>{more}"


def _fmt_num(v):
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, int):
        return f"{v:,}"
    return f"{v:,.2f}"


def _card(label: str, value, kind: str = "") -> str:
    return (f'<div class="card {kind}"><div class="label">{escape(label)}</div>'
            f'<div class="value">{_cell(_fmt_num(value) if _is_num(value) else value)}</div></div>')


def _dataset_section(title: str, ds: "DatasetResult") -> str:
    s = ds.stats()
    cards = "".join([
        _card("データ行数", s["データ行数"]),
        _card("正常な行数", s["正常な行数"], "ok"),
        _card("エラーのある行数", s["エラーのある行数"], "ng" if s["エラーのある行数"] else "ok"),
        _card("注意", s["注意件数"], "warn" if s["注意件数"] else ""),
        _card("重複（2件目以降）", s["重複（2件目以降）"], "ng" if s["重複（2件目以降）"] else "ok"),
        _card("整形で直した値", s["整形で直した値"]),
    ])
    info = (f"<dl><dt>ファイル</dt><dd>{_cell(s['ファイル'])}</dd>"
            f"<dt>設定</dt><dd>{_cell(s['設定'])}</dd>"
            f"<dt>文字コード</dt><dd>{_cell(s['文字コード'])}</dd>"
            f"<dt>空行（読み飛ばし）</dt><dd>{s['空行（読み飛ばし）']}</dd></dl>")
    by_rule = pd.DataFrame(list(s["チェック別の件数"].items()), columns=["チェック", "件数"])
    return (f"<section><h2>{escape(title)}</h2>{info}<h3>結果</h3><div class=\"cards\">{cards}</div>"
            f"<h3>チェック別の件数</h3>{table_html(by_rule)}</section>")


def render_html(result: "RunResult") -> str:
    parts = [_dataset_section("入力ファイル", result.main)]
    if result.right is not None:
        parts.append(_dataset_section("照合ファイル", result.right))

    issues = result.issues_df
    parts.append(f"<section><h2>エラー・注意の一覧</h2>{table_html(issues)}</section>")

    if result.reconcile is not None:
        rec = result.reconcile
        kinds = {MATCH: "ok"}
        cards = "".join(_card(k, v, kinds.get(k, "ng" if v else "ok")) for k, v in rec.counts.items())
        skipped = pd.DataFrame([(k, v) for k, v in rec.skipped.items() if v], columns=["内容", "件数"])
        not_match = rec.table[rec.table[RESULT_COL] != MATCH]
        parts.append(
            f"<section><h2>照合の結果（{escape(rec.left_label)} × {escape(rec.right_label)}）</h2>"
            f"<div class=\"cards\">{cards}</div>"
            + (f"<h3>照合から外した行</h3>{table_html(skipped)}" if not skipped.empty else "")
            + f"<h3>一致しなかったもの</h3>{table_html(not_match)}</section>"
        )

    if result.aggregates:
        blocks = "".join(f"<h3>{escape(name)}</h3>{table_html(df, total_label='合計')}"
                         for name, df in result.aggregates.items())
        parts.append(f"<section><h2>集計（正常な行のみ）</h2>{blocks}</section>")

    title = f"処理レポート {result.run_id}"
    sub = (f"開始 {result.started_at:%Y-%m-%d %H:%M:%S} ／ 終了 {result.finished_at:%Y-%m-%d %H:%M:%S}")
    return (
        "<!DOCTYPE html><html lang=\"ja\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'\">"
        f"<title>{escape(title)}</title><style>{_CSS}</style></head><body>"
        f"<header><h1>{escape(title)}</h1><p>{escape(sub)}</p></header><main>{''.join(parts)}</main></body></html>"
    )
