"""試用データ（samples/trial）が説明どおりの結果になるか。"""

from pathlib import Path

import pytest

from dataprep.pipeline import RunOptions, run

ROOT = Path(__file__).resolve().parents[1]
TRIAL = ROOT / "samples" / "trial"


def _run(tmp_path, orders, payments):
    return run(RunOptions(input_path=TRIAL / orders, profile_path=ROOT / "profiles" / "orders.json",
                          output_dir=tmp_path, reconcile_path=TRIAL / payments))


@pytest.mark.parametrize("name", ["受注_10-11月.csv", "入金_10-11月.csv", "受注_きれい.csv", "入金_きれい.csv"])
def test_trial_files_exist(name):
    assert (TRIAL / name).is_file()


def test_trial_with_problems(tmp_path):
    r = _run(tmp_path, "受注_10-11月.csv", "入金_10-11月.csv")
    s = r.summary["入力ファイル"]
    assert (s["データ行数"], s["正常な行数"], s["エラーのある行数"], s["重複（2件目以降）"]) == (122, 114, 8, 2)
    assert s["文字コード"] == "Shift_JIS"
    assert r.summary["照合ファイル"]["エラー件数"] == 0
    assert r.reconcile.counts == {"一致": 113, "不一致": 2, "受注のみ": 5, "入金のみ": 1}
    assert list(r.aggregates["月別売上"]["注文日（月）"][:2]) == ["2026-10", "2026-11"]


def test_trial_clean(tmp_path):
    r = _run(tmp_path, "受注_きれい.csv", "入金_きれい.csv")
    s = r.summary["入力ファイル"]
    assert (s["データ行数"], s["正常な行数"], s["エラー件数"]) == (50, 50, 0)
    assert r.reconcile.counts["一致"] == 50
    assert sum(r.reconcile.counts.values()) == 50
