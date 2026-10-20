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


def test_limits_are_read_and_checked(tmp_path):
    cfg, problems = load_press(EXAMPLE_PRESS)
    assert (cfg.max_path_rate_mm_min, cfg.max_force_rate_kn_s) == (10.0, 15.0)
    text = EXAMPLE_PRESS.read_text(encoding="utf-8").replace(
        "max_force_rate_kn_s = 15.0", "max_force_rate_kn_s = 0.0\nspeed = 1")
    p = _write(tmp_path, text)
    _, problems = load_press(p)
    assert "limits.max_force_rate_kn_s must be above zero, not 0" in problems
    assert any("unknown key 'speed'" in x for x in problems)


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


def test_the_test_settings_round_trip(_sandboxed_settings):
    from presscontroller.config.settings import TemplateSettings
    s = Settings(control_port="COM7", refresh_hz=1.5,
                 test=TemplateSettings(peak=True, break_detection=False,
                                       break_threshold_per_mil=25.0, start_load_percent=0.2,
                                       ramp_control="force", force_speed_kn_s=5.0,
                                       force_end_kn=300.0, measuring_interval_ms=100))
    save_settings(s)
    assert load_settings() == (s, None)


def test_an_unusable_test_value_falls_back_to_its_own_default_and_is_named(_sandboxed_settings):
    from presscontroller.config.settings import TemplateSettings
    _sandboxed_settings.parent.mkdir(parents=True)
    _sandboxed_settings.write_text('control_port = "COM7"\n[test]\nbreak_detection = 1\n'
                                   'start_load_percent = 5.0\npath_speed_mm_min = 3.0\n'
                                   'measuring_interval_ms = 205\ncolour = "red"\n',
                                   encoding="utf-8")
    settings, problem = load_settings()
    t = settings.test
    assert settings.control_port == "COM7" and t.path_speed_mm_min == 3.0   # the rest counts
    d = TemplateSettings()
    assert (t.break_detection, t.start_load_percent, t.measuring_interval_ms) == (
        d.break_detection, d.start_load_percent, d.measuring_interval_ms)
    for words in ("break_detection must be true or false", "start load 5 %",
                  "measuring interval 205 ms", "unknown key test.colour"):
        assert words in problem


def test_a_settings_file_from_before_the_test_settings_still_loads(_sandboxed_settings):
    from presscontroller.config.settings import TemplateSettings
    _sandboxed_settings.parent.mkdir(parents=True)
    _sandboxed_settings.write_text('press_file = "C:/p.toml"\ndata_dir = "C:/d"\n',
                                   encoding="utf-8")
    settings, problem = load_settings()
    assert problem is None and settings.test == TemplateSettings()
    assert settings.test.break_detection is True                  # operator, 2026-10-19
