from dataprep.config import parse_profile
from dataprep.validation import ERROR, WARNING, has_fatal_column_issue, issues_to_dataframe, validate_columns, validate_values

from conftest import make_df

GOOD = {"ID": "A-001", "日付": "2026-01-05", "名前": "山田", "メール": "a@example.com", "電話": "03-1234-5678",
        "数量": "2", "単価": "100", "金額": "200", "区分": "通常"}


def rules_of(issues):
    return [(i.row, i.column, i.rule) for i in issues]


def test_good_row_has_no_issue(simple_profile):
    assert validate_values(make_df([GOOD]), simple_profile) == []


def test_required_and_optional_empty(simple_profile):
    row = dict(GOOD, 名前="", メール="", 電話="")
    assert rules_of(validate_values(make_df([row]), simple_profile)) == [(2, "名前", "required")]


def test_type_errors(simple_profile):
    row = dict(GOOD, 日付="2026-02-30", メール="a@b", 電話="12345", 数量="1.5", 単価="abc")
    found = rules_of(validate_values(make_df([row]), simple_profile))
    assert (2, "日付", "type") in found
    assert (2, "メール", "type") in found
    assert (2, "電話", "type") in found
    assert (2, "数量", "type") in found
    assert (2, "単価", "type") in found
    assert not any(r == "row_rule" for _, _, r in found)  # 数字でない値があれば行のルールは見ない


def test_range_length_pattern_allowed(simple_profile):
    row = dict(GOOD, ID="B-001", 名前="とても長い名前", 数量="11", 単価="-1", 金額="-11", 区分="普通")
    found = rules_of(validate_values(make_df([row]), simple_profile))
    assert (2, "ID", "pattern") in found
    assert (2, "名前", "max_length") in found
    assert (2, "数量", "max") in found
    assert (2, "単価", "min") in found
    assert (2, "区分", "allowed") in found


def test_min_boundary(simple_profile):
    ok = dict(GOOD, 数量="1", 単価="0", 金額="0")
    assert validate_values(make_df([ok]), simple_profile) == []
    ng = dict(GOOD, 数量="0", 金額="0")
    assert rules_of(validate_values(make_df([ng]), simple_profile)) == [(2, "数量", "min")]


def test_product_rule(simple_profile):
    row = dict(GOOD, 金額="201")
    issues = validate_values(make_df([row]), simple_profile)
    assert rules_of(issues) == [(2, "金額", "row_rule")]
    assert "計算値 200" in issues[0].message


def test_compare_rule_with_dates():
    prof = parse_profile({
        "name": "期間", "columns": [{"name": "開始", "type": "date"}, {"name": "終了", "type": "date"}],
        "row_rules": [{"type": "compare", "left": "開始", "op": "<=", "right": "終了", "message": "開始が終了より後です"}],
    })
    df = make_df([{"開始": "2026-01-01", "終了": "2026-01-31"}, {"開始": "2026-02-10", "終了": "2026-02-01"},
                  {"開始": "", "終了": "2026-02-01"}])
    issues = validate_values(df, prof)
    assert rules_of(issues) == [(3, "開始", "row_rule")]


def test_validate_columns_missing_and_extra(simple_profile):
    df = make_df([{"ID": "A-001", "名前": "x", "余分": "1"}])
    issues = validate_columns(df, simple_profile)
    by_col = {i.column: i.severity for i in issues}
    assert by_col["日付"] == ERROR        # 必須の列がない
    assert by_col["メール"] == WARNING    # 任意の列がない
    assert "余分" not in by_col           # allow_extra_columns の既定は true
    assert has_fatal_column_issue(issues)


def test_extra_column_warning_when_not_allowed():
    prof = parse_profile({"name": "x", "allow_extra_columns": False, "columns": [{"name": "A"}]})
    issues = validate_columns(make_df([{"A": "1", "B": "2"}]), prof)
    assert [(i.column, i.rule, i.severity) for i in issues] == [("B", "extra_column", WARNING)]


def test_issues_dataframe_columns(simple_profile):
    issues = validate_values(make_df([dict(GOOD, 名前="")]), simple_profile)
    df = issues_to_dataframe(issues)
    assert list(df.columns) == ["ファイル", "行番号", "列", "値", "チェック", "内容", "重要度"]
    assert df.iloc[0]["チェック"] == "必須項目"
