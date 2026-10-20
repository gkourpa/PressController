"""What may be sent to the controller, and nothing else.

Two kinds of line, both checked by :func:`check` at the one place a byte leaves
(:meth:`~presscontroller.control.link.ControllerLink.send`):

* **Exact lines** (:data:`ALLOWED`) — every one sent by Proteus in the recorded
  sessions: its start-up, the stream on/off, PC mode off, Peak and break
  detection on/off, and the test's fixed commands: ``#B47`` START, ``#B23``
  approach, ``#B22`` start the ramp, ``#B18`` PAUSE/CONTINUE, ``#B26`` (the
  answer to the ramp's end) and ``#B17`` Cancel — the STOP.
* **Four lines built from settings**, each by one function here and accepted at
  the write point only inside its range (docs/motion.md):

  ========================================  ==========================================
  line                                      allowed
  ========================================  ==========================================
  ``#D12<speed>;0;<end>;0;<channel>``       Path (µm/s, µm) or Force (N/s, N) only;
                                            speed within the press file's ``[limits]``;
                                            end within the channel's range
  ``#D09<n>``                               start load, n × 0.01 % of the force range,
                                            n = 1–100
  ``#D05<n>``                               stream interval n × 10 ms, n = 5–100
  ``#D21<n>``                               break threshold n × 0.1 ‰, n = 10–1000
  ========================================  ==========================================

What Proteus' program can send but no recording has shown — ``#B24``, ``#B34``,
``#B38``, ``#B60``, ``#D160``, ``#D161``, Deformation control — is not here
(:data:`NEVER`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from presscontroller.config.press import FORCE, PATH, PressConfig
from presscontroller.config.settings import (
    MAX_BREAK_THRESHOLD,
    MAX_INTERVAL_MS,
    MAX_START_LOAD,
    MIN_BREAK_THRESHOLD,
    MIN_INTERVAL_MS,
    MIN_START_LOAD,
)

#: Proteus' start-up, as sent in all eight recorded sessions, in its four groups.
#: The session waits after each group for what Proteus always got back.
STARTUP_GROUPS: tuple[tuple[str, ...], ...] = (
    ("#B21", "#B20"),
    ("#B50", "#B40"),
    ("#D020", "#B51", "#B52", "#B41", "#B03", "#B09", "#D0510"),
    ("#B37",),
)

#: What the controller answered to each group, every time (the stream for the last).
STARTUP_REPLIES: tuple[tuple[str, ...], ...] = (
    ("#O",),
    ("#D138.6", "#D104000"),
    ("#D140", "#D180"),
    (),
)

STREAM_ON = "#B37"
STREAM_OFF = "#B36"
PC_MODE_OFF = "#B21"
CANCEL = "#B17"
PEAK_OFF, PEAK_ON = "#B30", "#B31"
BREAK_OFF, BREAK_ON = "#B32", "#B33"
START = "#B47"
APPROACH = "#B23"
RAMP_GO = "#B22"
PAUSE_CONTINUE = "#B18"
RAMP_END_ANSWER = "#B26"

#: Leaving PC mode, as Proteus does when it closes: the stream off, then PC mode
#: off. Afterwards the controller's own keypad works again.
DISCONNECT = (STREAM_OFF, PC_MODE_OFF)

ALLOWED: frozenset[str] = frozenset(
    [line for group in STARTUP_GROUPS for line in group]
    + [STREAM_ON, STREAM_OFF, PC_MODE_OFF, CANCEL, PEAK_OFF, PEAK_ON, BREAK_OFF, BREAK_ON,
       START, APPROACH, RAMP_GO, PAUSE_CONTINUE, RAMP_END_ANSWER])

#: In Proteus' program, never seen on the line: never sent. A test checks none
#: of them, nor any line built around them, gets through :func:`check`.
NEVER: frozenset[str] = frozenset(["#B24", "#B34", "#B38", "#B60", "#B04", "#B11",
                                   "#D160", "#D161"])


class NotAllowed(ValueError):
    """A line that may not be sent. Raised before a byte is written."""


@dataclass(frozen=True)
class Limits:
    """What the press file allows a ramp: its two controllable channels, their
    ranges, and the fastest rates (``[limits]``)."""

    force_channel: int
    path_channel: int
    force_range_kn: float
    path_range_mm: float
    max_force_kn_s: float
    max_path_mm_min: float

    @classmethod
    def from_press(cls, press: PressConfig) -> "Limits | None":
        """The press file's limits, or ``None`` when it sets none — and then no
        ramp may be sent at all."""
        force, path = press.by_name(FORCE), press.by_name(PATH)
        if (force is None or path is None or press.max_force_rate_kn_s is None
                or press.max_path_rate_mm_min is None):
            return None
        return cls(force.index, path.index, force.range, path.range,
                   press.max_force_rate_kn_s, press.max_path_rate_mm_min)

    # In the ramp's own numbers: thousandths of the channel unit (per second).
    def max_speed(self, channel: int) -> int:
        if channel == self.path_channel:
            return round(self.max_path_mm_min * 1000 / 60)
        return round(self.max_force_kn_s * 1000)

    def max_end(self, channel: int) -> int:
        return round((self.path_range_mm if channel == self.path_channel
                      else self.force_range_kn) * 1000)


# ---- the four built lines ------------------------------------------------------------

def ramp_line(limits: Limits | None, control: str, speed: float, end: float) -> str:
    """``#D12…`` for a ramp on ``control`` (``path``: mm/min to mm; ``force``: kN/s
    to kN). Raises :class:`NotAllowed`, saying why, for anything outside the limits."""
    if limits is None:
        raise NotAllowed("the press file sets no [limits], so no ramp may be sent")
    if control == "path":
        channel, units, unit_end = limits.path_channel, round(speed * 1000 / 60), round(end * 1000)
        told = f"{speed:g} mm/min (limit {limits.max_path_mm_min:g} mm/min)"
    elif control == "force":
        channel, units, unit_end = limits.force_channel, round(speed * 1000), round(end * 1000)
        told = f"{speed:g} kN/s (limit {limits.max_force_kn_s:g} kN/s)"
    else:
        raise NotAllowed(f"a ramp on {control!r} is not allowed: Path or Force only")
    line = f"#D12{units};0;{unit_end};0;{channel}"
    why = _ramp_problem(limits, units, unit_end, channel)
    if why:
        raise NotAllowed(f"ramp {told} to {end:g}: {why}")
    return line


def start_load_line(percent: float) -> str:
    n = round(percent * 100)
    if not round(MIN_START_LOAD * 100) <= n <= round(MAX_START_LOAD * 100):
        raise NotAllowed(f"start load {percent:g} % is outside {MIN_START_LOAD:g}–"
                         f"{MAX_START_LOAD:g} % of the force range")
    return f"#D09{n}"


def interval_line(ms: int) -> str:
    if ms % 10 or not MIN_INTERVAL_MS <= ms <= MAX_INTERVAL_MS:
        raise NotAllowed(f"measuring interval {ms} ms is not a multiple of 10 ms within "
                         f"{MIN_INTERVAL_MS}–{MAX_INTERVAL_MS} ms")
    return f"#D05{ms // 10}"


def break_threshold_line(per_mil: float) -> str:
    n = round(per_mil * 10)
    if not round(MIN_BREAK_THRESHOLD * 10) <= n <= round(MAX_BREAK_THRESHOLD * 10):
        raise NotAllowed(f"break threshold {per_mil:g} ‰ is outside "
                         f"{MIN_BREAK_THRESHOLD:g}–{MAX_BREAK_THRESHOLD:g} ‰")
    return f"#D21{n}"


# ---- the check at the write point --------------------------------------------------

_RAMP = re.compile(r"#D12([1-9]\d*);0;([1-9]\d*);0;(\d)")
_BUILT = {
    "start load": (re.compile(r"#D09([1-9]\d*)"),
                   round(MIN_START_LOAD * 100), round(MAX_START_LOAD * 100)),
    "interval": (re.compile(r"#D05([1-9]\d*)"), MIN_INTERVAL_MS // 10, MAX_INTERVAL_MS // 10),
    "break threshold": (re.compile(r"#D21([1-9]\d*)"),
                        round(MIN_BREAK_THRESHOLD * 10), round(MAX_BREAK_THRESHOLD * 10)),
}


def _ramp_problem(limits: Limits, speed: int, end: int, channel: int) -> str | None:
    if channel not in (limits.path_channel, limits.force_channel):
        return f"channel {channel} is not Path or Force"
    if speed < 1:
        return "the speed rounds to zero"
    if speed > limits.max_speed(channel):
        return "faster than the press file's [limits]"
    if not 1 <= end <= limits.max_end(channel):
        return "the end is outside the channel's range"
    return None


def check(line: str, limits: Limits | None = None) -> str:
    """``line`` if it may be sent; :class:`NotAllowed` otherwise.

    ``limits`` are the press file's; without them no ramp passes.
    """
    if line in ALLOWED:
        return line
    if m := _RAMP.fullmatch(line):
        if limits is None:
            raise NotAllowed(f"{line!r}: the press file sets no [limits]; nothing was sent")
        why = _ramp_problem(limits, int(m[1]), int(m[2]), int(m[3]))
        if why:
            raise NotAllowed(f"{line!r}: {why}; nothing was sent")
        return line
    for name, (pattern, lo, hi) in _BUILT.items():
        if (m := pattern.fullmatch(line)) and lo <= int(m[1]) <= hi:
            return line
    raise NotAllowed(f"{line!r} is not on the allowlist; nothing was sent")
