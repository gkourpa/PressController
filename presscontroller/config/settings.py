"""The global settings: what belongs to this installation, not to a press.

Which press file was opened last and where the monitor keeps what it records.
Stored at ``%APPDATA%\\PressController\\settings.toml``; ``$PRESSCONTROLLER_SETTINGS``
names another file instead, which is how the tests keep away from the operator's.

As in DAqReader, **a broken settings file is not fatal**: it loads as defaults,
with the reason beside them. Losing a remembered path costs a click.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from presscontroller.config.parse import ConfigError, get_str
from presscontroller.config.toml import toml_value, write_atomic

APP_DIRNAME = "PressController"
SETTINGS_ENV = "PRESSCONTROLLER_SETTINGS"


@dataclass(frozen=True)
class Settings:
    press_file: str = ""
    """The press file opened last. Blank until the operator picks one."""

    data_dir: str = ""
    """Where the monitor writes: ``captures/`` (every byte heard) and ``tests/``
    (one CSV per test). Blank until the operator picks one."""

    def to_toml(self) -> str:
        return "\n".join([
            "# PressController global settings. The press itself is described in its own file.",
            f"press_file = {toml_value(self.press_file)}",
            f"data_dir = {toml_value(self.data_dir)}",
        ]) + "\n"


def settings_path() -> Path:
    """The settings file: ``$PRESSCONTROLLER_SETTINGS``, else under ``%APPDATA%``."""
    env = os.environ.get(SETTINGS_ENV)
    if env:
        return Path(env)
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / APP_DIRNAME / "settings.toml"


def load_settings(path: str | Path | None = None) -> tuple[Settings, str | None]:
    """The settings, and why they are defaults if the file was unusable."""
    path = Path(path) if path is not None else settings_path()
    if not path.is_file():
        return Settings(), None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return Settings(press_file=get_str(data, "press_file", "", path.name),
                        data_dir=get_str(data, "data_dir", "", path.name)), None
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, ConfigError) as exc:
        return Settings(), f"the settings in {path} could not be read ({exc}); using defaults"


def save_settings(settings: Settings, path: str | Path | None = None) -> Path:
    return write_atomic(Path(path) if path is not None else settings_path(),
                        settings.to_toml())
