"""画面の部品のうち、ウィンドウを開かずに確かめられるもの（配色・設定の保存・グラフの目盛り）。"""

import json

import pytest

from dataprep.gui import app, charts, theme


@pytest.fixture(autouse=True)
def reset_mode():
    yield
    theme.set_mode(theme.DARK)


def test_set_mode_switches_palette():
    theme.set_mode(theme.LIGHT)
    assert theme.mode == theme.LIGHT
    assert theme.BG == theme.PALETTES[theme.LIGHT]["BG"]
    theme.set_mode(theme.DARK)
    assert theme.BG == theme.PALETTES[theme.DARK]["BG"]


@pytest.mark.parametrize("value", ["<script>", None, ["light"], {"a": 1}, 1])
def test_unknown_mode_falls_back_to_dark(value):
    theme.set_mode(theme.LIGHT)
    theme.set_mode(value)  # 設定ファイルが書き換えられていても落ちない
    assert theme.mode == theme.DARK


def test_palettes_have_same_keys():
    assert set(theme.PALETTES[theme.DARK]) == set(theme.PALETTES[theme.LIGHT])


def test_mix_and_scale_color():
    assert theme.mix("#000000", "#ffffff", 0) == "#000000"
    assert theme.mix("#000000", "#ffffff", 1) == "#ffffff"
    assert theme.scale_color(0) == theme.SCALE[0]
    assert theme.scale_color(1) == theme.SCALE[-1]
    assert theme.scale_color(-5) == theme.SCALE[0]  # 範囲外は端の色


def test_settings_round_trip(tmp_path):
    app.save_settings(tmp_path, {"theme": "light"})
    assert app.load_settings(tmp_path) == {"theme": "light"}


@pytest.mark.parametrize("content", ["{壊れた", "[1, 2]", ""])
def test_broken_settings_are_ignored(tmp_path, content):
    (tmp_path / "settings.json").write_text(content, encoding="utf-8")
    assert app.load_settings(tmp_path) == {}


def test_missing_settings(tmp_path):
    assert app.load_settings(tmp_path / "ない") == {}


def test_settings_file_is_json(tmp_path):
    app.save_settings(tmp_path / "new", {"theme": "dark"})
    assert json.loads((tmp_path / "new" / "settings.json").read_text(encoding="utf-8"))["theme"] == "dark"


@pytest.mark.parametrize("vmax, top", [(59600, 60000), (36, 40), (4, 4), (0.7, 0.8), (0, 1)])
def test_nice_ticks(vmax, top):
    ticks = charts.nice_ticks(vmax)
    assert ticks[0] == 0
    assert ticks[-1] == pytest.approx(top)
    assert ticks[-1] >= vmax


def test_fmt_number():
    assert charts.fmt_number(59600) == "59,600"
    assert charts.fmt_number(7450.0) == "7,450"
    assert charts.fmt_number(1375.25) == "1,375.2"
