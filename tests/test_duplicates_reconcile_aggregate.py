from pathlib import Path

from dataprep.aggregate import TOTAL_LABEL, UNKNOWN_LABEL, aggregate
from dataprep.config import parse_profile
from dataprep.duplicates import FIRST, GROUP_COL, KIND_COL, LATER, find_duplicates
from dataprep.reconcile import MATCH, MISMATCH, RESULT_COL, reconcile

from conftest import make_df


# ---------------------------------------------------------------- 重複

def test_duplicates_by_key():
    df = make_df([{"ID": "A", "v": "1"}, {"ID": "B", "v": "2"}, {"ID": "A", "v": "3"}, {"ID": "A", "v": "4"}, {"ID": "", "v": "5"}, {"ID": "", "v": "6"}])
    table, issues = find_duplicates(df, ["ID"])
    assert list(table.index) == [2, 4, 5]
    assert list(table[KIND_COL]) == [FIRST, LATER, LATER]
    assert set(table[GROUP_COL]) == {1}
    assert [i.row for i in issues] == [4, 5]          # 空欄のキーは重複にしない
    assert "2行目" in issues[0].message


def test_duplicates_whole_row_when_no_key():
    df = make_df([{"a": "1", "b": "x"}, {"a": "1", "b": "y"}, {"a": "1", "b": "x"}])
    table, issues = find_duplicates(df, [])
    assert [i.row for i in issues] == [4]
    assert issues[0].column == "行全体"


def test_no_duplicates():
    table, issues = find_duplicates(make_df([{"ID": "A"}, {"ID": "B"}]), ["ID"])
    assert table.empty and issues == []


# ---------------------------------------------------------------- 照合

def _spec(tolerance=0):
    prof = parse_profile({
        "name": "L", "columns": [{"name": "注文"}, {"name": "金額", "type": "int"}],
        "reconcile": {"right_profile": "r.json", "left_label": "受注", "right_label": "入金",
                      "left_keys": ["注文"], "right_keys": ["注番"],
                      "compare": [{"left": "金額", "right": "入金額", "tolerance": tolerance}]},
    }, base_dir=Path("."))
    return prof.reconcile


def test_reconcile_four_categories():
    left = make_df([{"注文": "1", "金額": "100"}, {"注文": "2", "金額": "200"}, {"注文": "3", "金額": "300"}])
    right = make_df([{"注番": "1", "入金額": "100"}, {"注番": "2", "入金額": "150"}, {"注番": "9", "入金額": "50"}])
    res = reconcile(left, right, _spec())
    assert res.counts == {MATCH: 1, MISMATCH: 1, "受注のみ": 1, "入金のみ": 1}
    row = res.table[res.table[RESULT_COL] == MISMATCH].iloc[0]
    assert row["注文"] == "2" and row["差額（金額）"] == "50"
    assert row["行番号（受注）"] == "3" and row["行番号（入金）"] == "3"
    assert res.table.iloc[0][RESULT_COL] == MISMATCH   # 不一致が先頭に来る


def test_reconcile_tolerance_and_skips():
    left = make_df([{"注文": "1", "金額": "100"}, {"注文": "1", "金額": "999"}, {"注文": "", "金額": "5"}])
    right = make_df([{"注番": "1", "入金額": "99"}])
    res = reconcile(left, right, _spec(tolerance=1))
    assert res.counts[MATCH] == 1                      # 差 1 は許容
    assert res.skipped["受注：キーの重複（2件目以降）"] == 1
    assert res.skipped["受注：キーが空欄"] == 1


def test_reconcile_text_compare():
    left = make_df([{"注文": "1", "金額": "abc"}])
    right = make_df([{"注番": "1", "入金額": "abd"}])
    assert reconcile(left, right, _spec()).counts[MISMATCH] == 1


# ---------------------------------------------------------------- 集計

AGG_PROFILE = {
    "name": "集計", "columns": [{"name": "日", "type": "date"}, {"name": "品", "type": "code"}, {"name": "額", "type": "int"}, {"name": "客"}],
    "aggregations": [
        {"name": "月別", "group_by": ["日:month"], "metrics": [{"func": "count", "label": "件数"}, {"func": "sum", "column": "額", "label": "合計額"}]},
        {"name": "品別", "group_by": ["品"], "metrics": [{"func": "mean", "column": "額", "label": "平均"}, {"func": "max", "column": "額", "label": "最大"},
                                                         {"func": "min", "column": "額", "label": "最小"}, {"func": "nunique", "column": "客", "label": "客数"}]},
    ],
}


def test_aggregate_month_with_total():
    prof = parse_profile(AGG_PROFILE)
    df = make_df([{"日": "2026-01-05", "品": "A", "額": "100", "客": "x"}, {"日": "2026-01-20", "品": "B", "額": "250", "客": "y"},
                  {"日": "2026-02-01", "品": "A", "額": "50", "客": "x"}, {"日": "", "品": "A", "額": "1", "客": ""}])
    out = aggregate(df, prof.aggregations[0])
    assert list(out.columns) == ["日（月）", "件数", "合計額"]
    rows = {r["日（月）"]: (r["件数"], r["合計額"]) for _, r in out.iterrows()}
    assert rows["2026-01"] == (2, 350)
    assert rows["2026-02"] == (1, 50)
    assert rows[UNKNOWN_LABEL] == (1, 1)
    assert rows[TOTAL_LABEL] == (4, 401)
    assert out.iloc[-1]["日（月）"] == TOTAL_LABEL


def test_aggregate_mean_max_min_nunique():
    prof = parse_profile(AGG_PROFILE)
    df = make_df([{"日": "2026-01-05", "品": "A", "額": "100", "客": "x"}, {"日": "2026-01-06", "品": "A", "額": "300", "客": "x"},
                  {"日": "2026-01-07", "品": "A", "額": "", "客": "y"}])
    out = aggregate(df, prof.aggregations[1], add_total=False)
    r = out.iloc[0]
    assert (r["平均"], r["最大"], r["最小"], r["客数"]) == (200.0, 300, 100, 2)


def test_aggregate_empty_dataframe():
    prof = parse_profile(AGG_PROFILE)
    out = aggregate(make_df([{"日": "", "品": "", "額": "", "客": ""}]).iloc[0:0], prof.aggregations[0])
    assert list(out[ "件数"]) == [0]
