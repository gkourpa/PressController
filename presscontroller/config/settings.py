"""The global settings: what belongs to this installation, not to a press.

Which press file was opened last, where the monitor keeps what it records, how
fast the window redraws — and the **test settings**: what Proteus kept in its
test template (Peak, break identification and its threshold, the start load,
the ramp and its measuring interval; docs/motion.md), which control mode sends
at START. Stored at ``%APPDATA%\\PressController\\settings.toml``;
``$PRESSCONTROLLER_SETTINGS`` names another file instead, which is how the tests
keep away from the operator's.

As in DAqReader, **a broken settings file is not fatal**: it loads as defaults,
with the reason beside them. One unusable value — out of its range, or a typo —
falls back to its own default and is named; the rest of the file still counts.

The ranges here are what the settings dialog accepts and what a settings file
may hold. Control mode checks every value again, against the press file, at the
one place a line is built (:mod:`presscontroller.control.commands`).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from presscontroller.config.parse import ConfigError, get_bool, get_float, get_int, get_str
from presscontroller.config.toml import toml_value, write_atomic

APP_DIRNAME = "PressController"
SETTINGS_ENV = "PRESSCONTROLLER_SETTINGS"

#: The window's redraw ceiling, in hertz, and what is accepted (DAqReader's).
DEFAULT_REFRESH_HZ = 2.0
MIN_REFRESH_HZ = 0.2
MAX_REFRESH_HZ = 20.0

#: The ramp's controlled channel, as the settings file names it.
RAMP_CONTROLS = ("path", "force")
RAMP_CONTROL_LABELS = {"path": "Path", "force": "Force"}

#: Break threshold, per mil, as Proteus' template takes it; sent as tenths.
MIN_BREAK_THRESHOLD, MAX_BREAK_THRESHOLD = 1.0, 100.0
#: Start load, in % of the force range; sent as hundredths of a percent.
MIN_START_LOAD, MAX_START_LOAD = 0.01, 1.0
#: Measuring interval during the ramp, ms; sent in 10 ms steps.
MIN_INTERVAL_MS, MAX_INTERVAL_MS = 50, 1000


def clamp_refresh_hz(hz: float) -> float:
    """``hz`` brought inside the accepted range: zero would stop the window
    redrawing, and the way back would be hand-editing this file."""
    return min(MAX_REFRESH_HZ, max(MIN_REFRESH_HZ, float(hz)))


@dataclass(frozen=True)
class TemplateSettings:
    """What Proteus' test template held, as this program's defaults.

    The lab's template's values are the defaults (operator's video,
    2026-10-20), except **break detection, on** (operator, 2026-10-19).
    """

    peak: bool = False
    """Peak detection (``#B31``/``#B30``) — the control window's Peak switch."""

    break_detection: bool = True
    """Break detection (``#B33``/``#B32``) — the Break detection switch."""

    break_threshold_per_mil: float = 10.0
    """Sent as ``#D21<× 10>`` right after break detection on (step 26)."""

    start_load_percent: float = 0.10
    """Of the force range; sent as ``#D09<× 100>`` (``#D0910`` = 0.10 % = 4 kN)."""

    ramp_control: str = "path"
    """``path`` or ``force`` — the ramp's controlled channel."""

    path_speed_mm_min: float = 2.0
    path_end_mm: float = 100.0
    force_speed_kn_s: float = 2.0
    force_end_kn: float = 100.0

    measuring_interval_ms: int = 200
    """The stream's interval during the ramp; sent as ``#D05<÷ 10>``."""

    def problems(self) -> list[str]:
        """Every value outside what may be sent, said in words."""
        out = []
        if not MIN_BREAK_THRESHOLD <= self.break_threshold_per_mil <= MAX_BREAK_THRESHOLD:
            out.append(f"break threshold {self.break_threshold_per_mil:g} ‰ is outside "
                       f"{MIN_BREAK_THRESHOLD:g}–{MAX_BREAK_THRESHOLD:g} ‰")
        if not MIN_START_LOAD <= self.start_load_percent <= MAX_START_LOAD:
            out.append(f"start load {self.start_load_percent:g} % is outside "
                       f"{MIN_START_LOAD:g}–{MAX_START_LOAD:g} % of the force range")
        if self.ramp_control not in RAMP_CONTROLS:
            out.append(f"ramp control {self.ramp_control!r} is not one of "
                       f"{', '.join(RAMP_CONTROLS)}")
        for name, value in (("path speed", self.path_speed_mm_min),
                            ("path end", self.path_end_mm),
                            ("force speed", self.force_speed_kn_s),
                            ("force end", self.force_end_kn)):
            if value <= 0:
                out.append(f"{name} must be above zero, not {value:g}")
        if (not MIN_INTERVAL_MS <= self.measuring_interval_ms <= MAX_INTERVAL_MS
                or self.measuring_interval_ms % 10):
            out.append(f"measuring interval {self.measuring_interval_ms} ms is not a "
                       f"multiple of 10 ms within {MIN_INTERVAL_MS}–{MAX_INTERVAL_MS} ms")
        return out


@dataclass(frozen=True)
class Settings:
    press_file: str = ""
    """The press file opened last. Blank until the operator picks one."""

    data_dir: str = ""
    """Where the monitor writes: ``captures/`` (every byte heard) and ``tests/``
    (one CSV per test). Blank until the operator picks one."""

    control_port: str = ""
    """The serial port the controller cable is plugged into in control mode
    (``COM7`` in the lab). It belongs to this computer and its adapters, not to
    the press, so it is kept here; blank until set, and then the press file's
    ``[control] port`` is used and remembered here."""

    refresh_hz: float = DEFAULT_REFRESH_HZ
    """The window's redraw ceiling (operator, 2026-10-19: no faster than 2 Hz).
    A ceiling, not a target: every line is taken in whatever the screen shows."""

    test: TemplateSettings = field(default_factory=TemplateSettings)

    def to_toml(self) -> str:
        t = self.test
        return "\n".join([
            "# PressController global settings. The press itself is described in its own file.",
            f"press_file = {toml_value(self.press_file)}",
            f"data_dir = {toml_value(self.data_dir)}",
            f"control_port = {toml_value(self.control_port)}",
            f"refresh_hz = {toml_value(self.refresh_hz)}",
            "",
            "# What control mode sends at START: Proteus' test template, as defaults.",
            "[test]",
            f"peak = {toml_value(t.peak)}",
            f"break_detection = {toml_value(t.break_detection)}",
            f"break_threshold_per_mil = {toml_value(t.break_threshold_per_mil)}",
            f"start_load_percent = {toml_value(t.start_load_percent)}",
            f"ramp_control = {toml_value(t.ramp_control)}",
            f"path_speed_mm_min = {toml_value(t.path_speed_mm_min)}",
            f"path_end_mm = {toml_value(t.path_end_mm)}",
            f"force_speed_kn_s = {toml_value(t.force_speed_kn_s)}",
            f"force_end_kn = {toml_value(t.force_end_kn)}",
            f"measuring_interval_ms = {toml_value(t.measuring_interval_ms)}",
        ]) + "\n"


def settings_path() -> Path:
    """The settings file: ``$PRESSCONTROLLER_SETTINGS``, else under ``%APPDATA%``."""
    env = os.environ.get(SETTINGS_ENV)
    if env:
        return Path(env)
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_DIRNAME / "settings.toml"


_TEST_KEYS = {f.name for f in fields(TemplateSettings)}


def _read_test(data: dict, where: str) -> tuple[TemplateSettings, list[str]]:
    """The ``[test]`` table, each unusable value replaced by its default and named."""
    table = data.get("test", {})
    if not isinstance(table, dict):
        return TemplateSettings(), [f"{where}: [test] must be a table; using the defaults"]
    defaults = TemplateSettings()
    values, notes = {}, []
    for key in sorted(set(table) - _TEST_KEYS):
        notes.append(f"{where}: unknown key test.{key} ignored")
    for f in fields(TemplateSettings):
        default = getattr(defaults, f.name)
        try:
            if isinstance(default, bool):
                v = get_bool(table, f.name, default, where)
            elif isinstance(default, int):
                v = get_int(table, f.name, default, where)
            elif isinstance(default, float):
                v = get_float(table, f.name, default, where)
            else:
                v = get_str(table, f.name, default, where)
        except ConfigError as exc:
            notes.append(f"{exc}; using {default!r}")
            v = default
        values[f.name] = v
    test = TemplateSettings(**values)
    # A value outside its range falls back to its own default, not the file.
    for problem in test.problems():
        notes.append(f"{where}: {problem}; using the default")
    for f in fields(TemplateSettings):
        one = replace(defaults, **{f.name: values[f.name]})
        if one.problems():
            test = replace(test, **{f.name: getattr(defaults, f.name)})
    return test, notes


def load_settings(path: str | Path | None = None) -> tuple[Settings, str | None]:
    """The settings, and what was wrong with the file if anything was.

    A missing file is the first launch, not a problem: defaults, no reason.
    """
    path = Path(path) if path is not None else settings_path()
    if not path.is_file():
        return Settings(), None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        where = path.name
        test, notes = _read_test(data, where)
        settings = Settings(press_file=get_str(data, "press_file", "", where),
                            data_dir=get_str(data, "data_dir", "", where),
                            control_port=get_str(data, "control_port", "", where).strip(),
                            refresh_hz=clamp_refresh_hz(
                                get_float(data, "refresh_hz", DEFAULT_REFRESH_HZ, where)),
                            test=test)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ConfigError) as exc:
        return Settings(), f"the settings in {path} could not be read ({exc}); using defaults"
    if notes:
        return settings, f"some settings in {path} were not usable:\n" + "\n".join(notes)
    return settings, None


def save_settings(settings: Settings, path: str | Path | None = None) -> Path:
    return write_atomic(Path(path) if path is not None else settings_path(),
                        settings.to_toml())
