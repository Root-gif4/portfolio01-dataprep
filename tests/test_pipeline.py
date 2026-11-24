"""結合テスト：見本データで一連の処理を最後まで動かす。"""

import json

import pytest

from dataprep.cli import main as cli_main
from dataprep.history import HistoryStore
from dataprep.pipeline import OUTPUT_NAMES, ProcessingError, RunOptions, run
from dataprep.reconcile import MATCH, MISMATCH

from conftest import write_text


@pytest.fixture
def sample_run(root, tmp_path):
    history = HistoryStore(tmp_path / "history.jsonl")
    steps = []
    result = run(RunOptions(
        input_path=root / "samples" / "orders.csv",
        profile_path=root / "profiles" / "orders.json",
        output_dir=tmp_path / "out",
        reconcile_path=root / "samples" / "payments.csv",
    ), history=history, progress=lambda s, p: steps.append(p))
    return result, history, steps


def test_sample_counts(sample_run):
    result, _, steps = sample_run
    s = result.summary["入力ファイル"]
    assert s["文字コード"] == "Shift_JIS"
    assert s["データ行数"] == 42
    assert s["エラーのある行数"] == 12
    assert s["正常な行数"] == 30
    assert s["重複（2件目以降）"] == 2
    assert s["空行（読み飛ばし）"] == 1
    assert result.summary["照合ファイル"]["文字コード"] == "UTF-8"
    assert result.reconcile.counts == {MATCH: 36, MISMATCH: 1, "受注のみ": 3, "入金のみ": 1}
    assert steps[-1] == 100 and steps == sorted(steps)


def test_sample_cleaning_fixed_values(sample_run):
    result, _, _ = sample_run
    c = result.main.cleaned
    assert c.loc[3, "注文日"] == "2026-09-03"            # 2026年9月3日
    assert c.loc[6, "注文番号"] == "ORD-260005"          # 小文字
    assert c.loc[7, "電話番号"] == "090-0000-0006"       # 全角
    assert c.loc[9, "商品コード"] == "MG-010"            # 全角
    assert c.loc[10, "商品名"] == "ステッカー 5枚セット"  # 半角カナ


def test_valid_rows_exclude_errors(sample_run):
    result, _, _ = sample_run
    error_rows = result.main.error_rows
    assert error_rows.isdisjoint(set(result.main.valid.index))
    assert len(result.main.valid) + len(error_rows) == len(result.main.cleaned)
    monthly = result.aggregates["月別売上"]
    assert monthly.iloc[-1]["注文件数"] == len(result.main.valid)


def test_output_files(sample_run):
    result, _, _ = sample_run
    names = {p.name for p in result.outputs}
    for key in ("cleaned", "valid", "valid_json", "issues", "duplicates", "changes", "reconcile", "summary", "report"):
        assert OUTPUT_NAMES[key] in names
    assert {"07-1_集計_月別売上.csv", "07-2_集計_商品別売上.csv", "07-3_集計_支払方法別.csv"} <= names
    records = json.loads((result.out_dir / OUTPUT_NAMES["valid_json"]).read_text(encoding="utf-8"))
    assert len(records) == 30 and "注文番号" in records[0]
    summary = json.loads((result.out_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["入力ファイル"]["データ行数"] == 42
    html = (result.out_dir / "report.html").read_text(encoding="utf-8")
    assert "<script" not in html and "照合の結果" in html


def test_history_written(sample_run):
    result, history, _ = sample_run
    rec = history.load()[0]
    assert rec["状態"] == "成功" and rec["run_id"] == result.run_id
    assert rec["データ行数"] == 42 and len(rec["入力ファイルのSHA256"]) == 64


def test_report_escapes_html(root, tmp_path):
    csv = write_text(tmp_path / "x.csv", "ID,名前\nA-001,<script>alert(1)</script>\n")
    prof = tmp_path / "p.json"
    prof.write_text(json.dumps({"name": "x", "columns": [{"name": "ID"}, {"name": "名前", "max_length": 3}]}), encoding="utf-8")
    result = run(RunOptions(input_path=csv, profile_path=prof, output_dir=tmp_path / "out"))
    html = (result.out_dir / "report.html").read_text(encoding="utf-8")
    assert "<script>alert" not in html and "&lt;script&gt;" in html


def test_missing_required_column_stops(root, tmp_path):
    csv = write_text(tmp_path / "x.csv", "注文番号,顧客名\nORD-000001,a\n")
    history = HistoryStore(tmp_path / "h.jsonl")
    with pytest.raises(ProcessingError, match="必須の列がありません"):
        run(RunOptions(input_path=csv, profile_path=root / "profiles" / "orders.json", output_dir=tmp_path / "out"), history=history)
    assert history.load()[0]["状態"] == "失敗"
    assert not (tmp_path / "out").exists()


def test_reconcile_without_setting_is_error(root, tmp_path):
    csv = write_text(tmp_path / "x.csv", "A\n1\n")
    prof = tmp_path / "p.json"
    prof.write_text(json.dumps({"name": "x", "columns": [{"name": "A"}]}), encoding="utf-8")
    with pytest.raises(ProcessingError, match="照合（reconcile）の設定がありません"):
        run(RunOptions(input_path=csv, profile_path=prof, output_dir=tmp_path, reconcile_path=csv))


def test_unexpected_error_hides_details(root, tmp_path, monkeypatch):
    import dataprep.pipeline as pl

    def boom(*a, **k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(pl, "clean_dataframe", boom)
    with pytest.raises(ProcessingError) as info:
        run(RunOptions(input_path=root / "samples" / "orders.csv", profile_path=root / "profiles" / "orders.json",
                       output_dir=tmp_path))
    assert "secret" not in str(info.value) and "受付番号" in str(info.value)


def test_history_skips_broken_lines(tmp_path):
    h = HistoryStore(tmp_path / "h.jsonl")
    h.append({"run_id": "1"})
    with h.path.open("a", encoding="utf-8") as f:
        f.write("{壊れた行\n")
    h.append({"run_id": "2"})
    assert [r["run_id"] for r in h.load()] == ["2", "1"]


def test_cli_run_and_history(root, tmp_path, capsys):
    args = ["--home", str(tmp_path / "home"), "run", "-i", str(root / "samples" / "orders.csv"),
            "-p", str(root / "profiles" / "orders.json"), "-r", str(root / "samples" / "payments.csv"), "-o", str(tmp_path / "out")]
    assert cli_main(args) == 0
    assert cli_main(args + ["--fail-on-error"]) == 1
    assert cli_main(["--home", str(tmp_path / "home"), "history"]) == 0
    assert "成功" in capsys.readouterr().out
    assert cli_main(["check-profile", str(root / "profiles" / "orders.json")]) == 0
    assert cli_main(["--home", str(tmp_path / "home"), "run", "-i", str(tmp_path / "none.csv"),
                     "-p", str(root / "profiles" / "orders.json")]) == 2
