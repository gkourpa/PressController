"""Press files and the global settings."""

from __future__ import annotations

import pytest

from presscontroller.config.parse import ConfigError
from presscontroller.config.press import load_press
from presscontroller.config.settings import Settings, load_settings, save_settings, settings_path
from tests.conftest import EXAMPLE_PRESS


def _write(tmp_path, text):
    p = tmp_path / "press.toml"
    p.write_text(text, encoding="utf-8")
    return p


def test_the_example_loads_without_problems_and_scales_as_proteus_does():
    cfg, problems = load_press(EXAMPLE_PRESS)
    assert problems == []
    force = cfg.by_name("Force")
    # The stream's -1245.4 counts read -8.30 kN, which matched the display.
    assert force.value(-1245, cfg.resolution) == pytest.approx(-8.3, abs=0.01)
    assert cfg.channel(1).value(15863, cfg.resolution) == pytest.approx(2.644, abs=0.001)


def test_every_problem_is_named_at_once(tmp_path):
    p = _write(tmp_path, '''
resolution = 0
colour = "red"
[tap]
pc_port = "COM3"
ctrl_port = "com3"
[[channel]]
index = 0
name = "Load"
unit = "kN"
range = -1.0
decimals = 9
''')
    _, problems = load_press(p)
    text = "\n".join(problems)
    for expected in ("unknown key 'colour'", "resolution must be above zero",
                     "both COM3", "range must be above zero", "decimals must be 0 to 6",
                     "no channel is named 'Force'", "no channel is named 'Path'"):
        assert expected in text


def test_a_wrong_type_is_a_config_error(tmp_path):
    p = _write(tmp_path, 'resolution = "600000"\n')
    with pytest.raises(ConfigError, match="resolution"):
        load_press(p)


def test_unreadable_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError):
        load_press(tmp_path / "missing.toml")


def test_settings_round_trip_into_the_sandbox(_sandboxed_settings):
    assert settings_path() == _sandboxed_settings
    s = Settings(press_file="C:\\x\\press.toml", data_dir="C:\\data")
    save_settings(s)
    assert load_settings() == (s, None)


def test_broken_settings_load_as_defaults_with_the_reason(_sandboxed_settings):
    _sandboxed_settings.parent.mkdir(parents=True)
    _sandboxed_settings.write_text("press_file = [", encoding="utf-8")
    settings, problem = load_settings()
    assert settings == Settings()
    assert "could not be read" in problem
