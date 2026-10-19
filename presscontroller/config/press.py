"""A press file: how this press's controller is reached, and what its channels mean.

Everything installation-specific lives here and nowhere in source: the two
serial ports of the tap, the controller's resolution and each channel's range.
The ranges and the resolution are the ones Proteus holds in its Hardware
Configuration (*Machine* → ``DIGIMAXXResolution``; *Channels* → ``Bereich1``), and
the stream reports raw counts that only mean something through them::

    value = raw × range / resolution        (docs/PROTOCOL.md, confirmed)

A minimal file::

    name = "FORM+TEST 4000 kN"
    resolution = 600000

    [tap]
    pc_port = "COM7"      # hears the PC: line pin 3
    ctrl_port = "COM6"    # hears the controller: line pin 2

    [control]             # only for control mode, the old PC unplugged
    port = "COM6"         # the adapter the controller cable plugs into

    [[channel]]
    index = 0
    name = "Force"
    unit = "kN"
    range = 4000.0
    decimals = 2

Like DAqReader's experiment files, a wrong *type* is a :class:`ConfigError` and
an unusable value is a problem from :meth:`PressConfig.problems`, so every one
is named at once.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from presscontroller.config.parse import ConfigError, get_float, get_int, get_opt_float, get_str

#: Keys a press file may carry, per table. Anything else is named as a problem:
#: a misspelt key silently ignored is a setting the operator believes is in force.
_TOP_KEYS = {"name", "resolution", "tap", "control", "limits", "channel"}
_TAP_KEYS = {"pc_port", "ctrl_port"}
_CONTROL_KEYS = {"port"}
_LIMIT_KEYS = {"max_path_rate_mm_min", "max_force_rate_kn_s"}
_CHANNEL_KEYS = {"index", "name", "unit", "range", "decimals"}

#: The channel the plots draw force from, and position from, by name. The stream
#: numbers channels; the press file names them, and these names are how the
#: monitor finds the two it plots against each other.
FORCE = "Force"
PATH = "Path"


@dataclass(frozen=True)
class Channel:
    index: int
    """The number the controller gives the channel in the stream (``0;…;1;…``)."""
    name: str
    unit: str
    range: float
    """Full scale in ``unit``, as Proteus' channel table holds it."""
    decimals: int = 3
    """How many decimals the monitor shows. Display only; the CSV keeps every count."""

    def value(self, raw: int, resolution: int) -> float:
        return raw * self.range / resolution


@dataclass(frozen=True)
class PressConfig:
    name: str
    resolution: int
    pc_port: str
    ctrl_port: str
    channels: tuple[Channel, ...]
    control_port: str = ""
    """The port the controller cable is plugged into when this program is in
    charge (``[control] port``). Blank where control mode is not used."""
    max_path_rate_mm_min: float | None = None
    """The fastest path ramp this press is to be run at (``[limits]``). Above
    what the hydraulics can follow, the ramp's target runs ahead of the piston,
    and PAUSE — which freezes the target — no longer holds it (step 22)."""
    max_force_rate_kn_s: float | None = None
    """The fastest force ramp this press is to be run at (``[limits]``)."""

    def channel(self, index: int) -> Channel | None:
        return next((c for c in self.channels if c.index == index), None)

    def by_name(self, name: str) -> Channel | None:
        return next((c for c in self.channels if c.name == name), None)

    def problems(self) -> list[str]:
        out = []
        if self.resolution <= 0:
            out.append(f"resolution must be above zero, not {self.resolution}")
        if not self.pc_port.strip():
            out.append("tap.pc_port is blank: name the port that hears the PC")
        if not self.ctrl_port.strip():
            out.append("tap.ctrl_port is blank: name the port that hears the controller")
        if self.pc_port.strip() and self.pc_port.strip().upper() == self.ctrl_port.strip().upper():
            out.append(f"tap.pc_port and tap.ctrl_port are both {self.pc_port}: "
                       "each direction needs its own adapter")
        if not self.channels:
            out.append("no [[channel]] is defined")
        seen_i, seen_n = set(), set()
        for c in self.channels:
            if c.index in seen_i:
                out.append(f"channel index {c.index} is defined twice")
            if c.name in seen_n:
                out.append(f"channel name {c.name!r} is used twice")
            seen_i.add(c.index)
            seen_n.add(c.name)
            if not c.name.strip():
                out.append(f"channel {c.index} has no name")
            if c.range <= 0:
                out.append(f"channel {c.name or c.index}: range must be above zero")
            if not 0 <= c.decimals <= 6:
                out.append(f"channel {c.name or c.index}: decimals must be 0 to 6")
        for key, v in (("max_path_rate_mm_min", self.max_path_rate_mm_min),
                       ("max_force_rate_kn_s", self.max_force_rate_kn_s)):
            if v is not None and v <= 0:
                out.append(f"limits.{key} must be above zero, not {v:g}")
        for needed in (FORCE, PATH):
            if needed not in seen_n:
                out.append(f"no channel is named {needed!r}; the plots need one")
        return out


def _unknown(table: dict, allowed: set[str], where: str) -> list[str]:
    return [f"{where}: unknown key {k!r}" for k in table if k not in allowed]


def load_press(path: str | Path) -> tuple[PressConfig, list[str]]:
    """The press file at ``path``, and every problem it has.

    Raises :class:`ConfigError` where the file cannot be read as a press file at
    all; returns problems where it can be read but not used.
    """
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path} could not be read: {exc}") from exc
    where = path.name
    problems = _unknown(data, _TOP_KEYS, where)
    tap = data.get("tap", {})
    if not isinstance(tap, dict):
        raise ConfigError(f"{where}: [tap] must be a table")
    problems += _unknown(tap, _TAP_KEYS, f"{where} [tap]")
    control = data.get("control", {})
    if not isinstance(control, dict):
        raise ConfigError(f"{where}: [control] must be a table")
    problems += _unknown(control, _CONTROL_KEYS, f"{where} [control]")
    limits = data.get("limits", {})
    if not isinstance(limits, dict):
        raise ConfigError(f"{where}: [limits] must be a table")
    problems += _unknown(limits, _LIMIT_KEYS, f"{where} [limits]")
    rows = data.get("channel", [])
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ConfigError(f"{where}: channels must be [[channel]] tables")
    channels = []
    for i, row in enumerate(rows, 1):
        w = f"{where} channel {i}"
        problems += _unknown(row, _CHANNEL_KEYS, w)
        channels.append(Channel(index=get_int(row, "index", -1, w),
                                name=get_str(row, "name", "", w),
                                unit=get_str(row, "unit", "", w),
                                range=get_float(row, "range", 0.0, w),
                                decimals=get_int(row, "decimals", 3, w)))
    cfg = PressConfig(name=get_str(data, "name", path.stem, where),
                      resolution=get_int(data, "resolution", 0, where),
                      pc_port=get_str(tap, "pc_port", "", f"{where} [tap]"),
                      ctrl_port=get_str(tap, "ctrl_port", "", f"{where} [tap]"),
                      channels=tuple(channels),
                      control_port=get_str(control, "port", "", f"{where} [control]"),
                      max_path_rate_mm_min=get_opt_float(limits, "max_path_rate_mm_min",
                                                         f"{where} [limits]"),
                      max_force_rate_kn_s=get_opt_float(limits, "max_force_rate_kn_s",
                                                        f"{where} [limits]"))
    return cfg, problems + cfg.problems()
