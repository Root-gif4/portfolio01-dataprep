import pytest

from dataprep.cleaning import clean_code, clean_dataframe, clean_date, clean_email, clean_number, clean_phone, clean_string

from conftest import make_df


@pytest.mark.parametrize("raw, expected", [
    ("１，２００", "1200"),
    ("¥1,200", "1200"),
    ("1,200円", "1200"),
    ("▲500", "-500"),
    ("－３", "-3"),
    (" 12 ", "12"),
    ("", ""),
    ("abc", "abc"),
])
def test_clean_number(raw, expected):
    assert clean_number(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("2026/1/5", "2026-01-05"),
    ("2026-01-05", "2026-01-05"),
    ("2026年1月5日", "2026-01-05"),
    ("２０２６／０１／０５", "2026-01-05"),
    ("20260105", "2026-01-05"),
    ("2026/01/05 13:45", "2026-01-05"),
    ("2026.1.5", "2026-01-05"),
    ("2026/02/30", "2026/02/30"),   # ありえない日付は直さない
    ("来週", "来週"),
])
def test_clean_date(raw, expected):
    assert clean_date(raw) == expected


def test_clean_phone_email_code_string():
    assert clean_phone("０９０ー１２３４ー５６７８") == "090-1234-5678"
    assert clean_phone("03 1234 5678") == "0312345678"
    assert clean_email("  Foo@Example.COM ") == "foo@example.com"
    assert clean_code("ａ－００１", upper=True) == "A-001"
    assert clean_string("　山田　") == "山田"
    assert clean_string("ｽﾃｯｶｰ", use_nfkc=True) == "ステッカー"


def test_clean_dataframe_records_changes(simple_profile):
    df = make_df([
        {"ID": "a-001", "日付": "2026/1/5", "名前": " 山田 ", "数量": "２"},
        {"ID": "A-002", "日付": "2026-01-06", "名前": "佐藤", "数量": "1"},
    ])
    df["その他"] = [" x ", "y"]
    cleaned, changes = clean_dataframe(df, simple_profile)
    assert cleaned.loc[2, "ID"] == "A-001"
    assert cleaned.loc[2, "日付"] == "2026-01-05"
    assert cleaned.loc[2, "名前"] == "山田"
    assert cleaned.loc[2, "数量"] == "2"
    assert cleaned.loc[2, "その他"] == "x"        # 設定にない列も前後の空白は取る
    assert list(changes.index) == [2, 2, 2, 2, 2]  # 変更は2行目だけ
    assert set(changes["列"]) == {"ID", "日付", "名前", "数量", "その他"}
    assert df.loc[2, "ID"] == "a-001"              # 元の表は変えない


def test_clean_dataframe_no_changes(simple_profile):
    df = make_df([{"ID": "A-001", "日付": "2026-01-05"}])
    _, changes = clean_dataframe(df, simple_profile)
    assert changes.empty
