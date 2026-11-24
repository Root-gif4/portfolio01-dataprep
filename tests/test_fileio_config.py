import json

import pytest

from dataprep.config import ProfileError, load_profile, parse_profile
from dataprep.fileio import DataFileError, read_csv, sanitize_cell, write_csv

from conftest import make_df, write_text


# ---------------------------------------------------------------- 読み込み

def test_read_utf8_and_sjis(tmp_path):
    text = "ID,名前\r\nA-001,山田\r\nA-002,佐藤\r\n"
    for enc, label in (("utf-8", "UTF-8"), ("utf-8-sig", "UTF-8"), ("cp932", "Shift_JIS")):
        t = read_csv(write_text(tmp_path / f"{enc}.csv", text, enc))
        assert t.encoding_label == label
        assert list(t.df.columns) == ["ID", "名前"]
        assert t.df.loc[3, "名前"] == "佐藤"
        assert t.df.index.name == "行番号"


def test_row_numbers_blank_lines_and_field_count(tmp_path):
    text = 'ID,メモ\n1,a\n\n2,"改行\nあり"\n3\n4,x,余分\n'
    t = read_csv(write_text(tmp_path / "a.csv", text))
    assert list(t.df.index) == [2, 4, 6, 7]   # 空行を飛ばし、引用符内の改行も1件として数える
    assert t.blank_lines == 1
    assert [s.row for s in t.structural_issues] == [6, 7]
    assert t.df.loc[6, "メモ"] == ""          # 足りない列は空欄で補う
    assert t.df.loc[4, "メモ"] == "改行\nあり"


def test_tab_delimiter(tmp_path):
    t = read_csv(write_text(tmp_path / "a.tsv", "a\tb\n1\t2\n"), delimiter="\t")
    assert t.df.loc[2, "b"] == "2"


@pytest.mark.parametrize("content, message", [
    ("", "空"),
    ("A,,C\n1,2,3\n", "空欄の列"),
    ("A,A\n1,2\n", "同じ名前"),
])
def test_bad_files(tmp_path, content, message):
    with pytest.raises(DataFileError, match=message):
        read_csv(write_text(tmp_path / "bad.csv", content))


def test_binary_and_size_limit(tmp_path):
    p = tmp_path / "bin.csv"
    p.write_bytes(b"A,B\n\x00\x01,2\n")
    with pytest.raises(DataFileError, match="バイナリ"):
        read_csv(p)
    with pytest.raises(DataFileError, match="大きすぎ"):
        read_csv(write_text(tmp_path / "big.csv", "A\n" + "1\n" * 100), max_bytes=50)
    with pytest.raises(DataFileError, match="見つかりません"):
        read_csv(tmp_path / "none.csv")


def test_wrong_encoding_specified(tmp_path):
    p = write_text(tmp_path / "s.csv", "名前\n山田\n", "cp932")
    with pytest.raises(DataFileError, match="UTF-8"):
        read_csv(p, encoding="utf-8")


# ---------------------------------------------------------------- 書き出し（CSV インジェクション対策）

@pytest.mark.parametrize("value, expected", [
    ("=1+1", "'=1+1"),
    ("+SUM(A1)", "'+SUM(A1)"),
    ("@cmd", "'@cmd"),
    ("-500", "-500"),     # 数字はそのまま
    ("-1.5", "-1.5"),
    ("-abc", "'-abc"),
    ("普通", "普通"),
    ("", ""),
])
def test_sanitize_cell(value, expected):
    assert sanitize_cell(value) == expected


def test_write_csv_is_excel_friendly(tmp_path):
    df = make_df([{"名前": "=HYPERLINK(\"x\")", "数": 3.0}])
    path = write_csv(df, tmp_path / "o.csv", include_index=True)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")               # BOM 付き UTF-8
    text = raw.decode("utf-8-sig")
    assert text.splitlines()[0] == "行番号,名前,数"
    assert "'=HYPERLINK" in text and ",3\r\n" in text


# ---------------------------------------------------------------- 設定ファイル

def test_sample_profiles_load(root):
    prof = load_profile(root / "profiles" / "orders.json")
    assert prof.keys == ("注文番号",)
    assert prof.reconcile and prof.reconcile.right_profile.name == "payments.json"
    assert load_profile(prof.reconcile.right_profile).name == "決済サービス入金データ"


@pytest.mark.parametrize("data, message", [
    ([], "一番外側"),
    ({"columns": [{"name": "A"}]}, "name がありません"),
    ({"name": "x", "columns": []}, "1つ以上"),
    ({"name": "x", "columns": [{"name": "A"}, {"name": "A"}]}, "同じ列名"),
    ({"name": "x", "columns": [{"name": "A", "type": "number"}]}, "type は"),
    ({"name": "x", "columns": [{"name": "A", "pattern": "("}]}, "正規表現"),
    ({"name": "x", "columns": [{"name": "A", "min": 1}]}, "int か decimal"),
    ({"name": "x", "columns": [{"name": "A", "type": "int", "min": 5, "max": 1}]}, "min が max"),
    ({"name": "x", "columns": [{"name": "A", "required": "yes"}]}, "true か false"),
    ({"name": "x", "keys": ["B"], "columns": [{"name": "A"}]}, "columns にない列"),
    ({"name": "x", "columns": [{"name": "A"}], "aggregations": [{"name": "a/b", "metrics": [{"func": "count"}]}]}, "ファイル名に使えない"),
    ({"name": "x", "columns": [{"name": "A"}], "aggregations": [{"name": "a", "group_by": ["A:month"], "metrics": [{"func": "count"}]}]}, "date の列"),
    ({"name": "x", "columns": [{"name": "A"}], "aggregations": [{"name": "a", "metrics": [{"func": "sum", "column": "A"}]}]}, "int か decimal"),
    ({"name": "x", "columns": [{"name": "A"}], "row_rules": [{"type": "eval"}]}, "type は"),
    ({"name": "x", "columns": [{"name": "A"}], "reconcile": {"right_profile": "r.json", "left_keys": ["A"], "right_keys": []}}, "同じ数"),
    ({"name": "x", "columns": [{"name": "A"}], "reconcile": {"right_profile": "r.json", "left_keys": ["A"], "right_keys": ["B"],
                                                           "compare": [{"left": "A", "right": "C"}]}}, "キーの列"),
])
def test_profile_errors(data, message):
    with pytest.raises(ProfileError, match=message):
        parse_profile(data)


def test_load_profile_json_errors(tmp_path):
    p = tmp_path / "p.json"
    p.write_text("{ name: x }", encoding="utf-8")
    with pytest.raises(ProfileError, match="書き方に誤り"):
        load_profile(p)
    with pytest.raises(ProfileError, match="見つかりません"):
        load_profile(tmp_path / "none.json")
    p.write_text(json.dumps({"name": "ok", "columns": [{"name": "A"}]}), encoding="utf-8")
    assert load_profile(p).name == "ok"
