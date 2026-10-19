"""Follow the link and the test, line by line.

What a test is, as heard on the line (docs/PROTOCOL.md, steps 13–16):

====================  ==========================  ==============================
heard                 means                       phase
====================  ==========================  ==============================
PC ``#B47``           START pressed               a new test, ``ARMED``
PC ``#B23``           approach starts             ``APPROACH``
CTRL ``#B01``         start load reached          ``AT_START_LOAD``
PC ``#D12…``          the ramp's definition       (kept on the test)
PC ``#B22``           ramp starts                 ``RAMP``
CTRL ``#B02``         ramp end reached            ``RAMP_END``
PC ``#B18``           Stop: piston held           ``HELD``
PC ``#B17``           Cancel: pump off            ``CANCELLED``
CTRL ``#B43``         load released               the test is closed
====================  ==========================  ==============================

**A test stays open after Cancel** until the controller's ``#B43``, a new START,
or Proteus leaving PC mode (``#B21``), so the unloading is part of its record:
what the specimen did after the peak is as much the test as the peak.

**The monitor never invents a reading.** A channel the press file does not
name is kept raw and labelled by its number; a line it cannot parse goes to the
log as it arrived and is said out loud (:class:`Notice`).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from presscontroller.config.press import FORCE, PATH, PressConfig
from presscontroller.protocol import (
    CTRL_TO_PC,
    DECODED_RAMP_CHANNELS,
    PC_TO_CTRL,
    Command,
    Ramp,
    Sample,
    SetParam,
    Unknown,
    describe,
    parse,
    rate_text,
)
from presscontroller.tap.events import TapEvent

#: The span the live rates are taken over. Long enough that a 0.2 s stream
#: gives ten points and the ±7-count noise averages down; short enough that a
#: change of speed shows within it.
RATE_WINDOW_S = 2.0

#: Seconds at the start of a ramp left out of its measured rate. They are the
#: servo taking up the load — 5.4 mm/min for a moment in a 3 mm/min ramp, force
#: dipping and then jumping 8 kN at the start of a 2 kN/s ramp (step 21) — and
#: they say nothing about the rate the ramp then holds.
RAMP_SETTLE_S = 3.0

#: Seconds of ramp before its measured rate is judged: the settling above plus
#: seven seconds of fit, which lands well inside the tolerance below on every
#: ramp recorded.
RAMP_JUDGE_AFTER_S = 10.0

#: How far the measured speed may be from the set one before the monitor says so.
#: The ramps seen ran within 5 % of their speed when they ran right, and at a
#: fifth of it when they did not.
RAMP_SPEED_TOLERANCE = 0.2

#: Log entries kept for the window. A day of tests is a few thousand lines;
#: the capture keeps everything regardless.
MAX_LOG = 5000


class Phase(Enum):
    NONE = "no test"
    ARMED = "START pressed"
    APPROACH = "approach"
    AT_START_LOAD = "start load reached"
    RAMP = "ramp"
    RAMP_END = "ramp end reached"
    HELD = "stopped, load held"
    CANCELLED = "cancelled"
    CLOSED = "test over"


@dataclass(frozen=True)
class LogEntry:
    t: float
    wall: datetime
    direction: str
    text: str
    meaning: str
    known: bool
    """False for a line the protocol notes do not cover."""


@dataclass(frozen=True)
class Notice:
    """Something the window should say, not merely log."""

    text: str
    warn: bool = False


@dataclass
class TestRecord:
    """One test, from START until it is closed."""

    number: int
    started: datetime
    t0: float
    """The tap time of START; a test's own time axis starts here."""
    t: list[float] = field(default_factory=list)
    counter: list[int] = field(default_factory=list)
    phase: list[str] = field(default_factory=list)
    raw: dict[int, list[int | None]] = field(default_factory=dict)
    events: list[tuple[float, str]] = field(default_factory=list)
    """``(test time, text)`` for every command and event heard during the test."""
    ramp: Ramp | None = None
    ramp_from_mm: float | None = None
    """Where the piston was when the ramp was sent."""
    warnings: list[str] = field(default_factory=list)
    ramp_judged: bool = False
    """Whether the measured speed has been compared with the set one yet."""
    _fit: list[float] = field(default_factory=lambda: [0.0] * 5)
    """Running sums n, St, Sx, Stt, Stx of position against time over the ramp,
    so its speed is a least-squares fit at any moment without a pass over it."""
    _fit_force: list[float] = field(default_factory=lambda: [0.0] * 5)
    """The same sums for force against time: the measured rate of a force ramp."""
    _ramp_t: list[float] = field(default_factory=lambda: [-1.0, 0.0])
    """Test time of the ramp's first and newest sample (first is -1 before one)."""
    closed: bool = False
    close_reason: str = ""

    def add_sample(self, t: float, counter: int, phase: Phase, raw: dict[int, int]) -> None:
        n = len(self.t)
        for idx in raw:
            if idx not in self.raw:
                self.raw[idx] = [None] * n      # a channel appearing late has a gap before
        self.t.append(t)
        self.counter.append(counter)
        self.phase.append(phase.value)
        for idx, col in self.raw.items():
            col.append(raw.get(idx))            # and one missing from a line is a gap

    def fit_ramp(self, t: float, position_mm: float | None, force_kn: float | None) -> None:
        """Add one ramp sample to the rate fits, once the ramp has settled
        (:data:`RAMP_SETTLE_S`)."""
        if self._ramp_t[0] < 0:
            self._ramp_t[0] = t
        self._ramp_t[1] = t
        if t - self._ramp_t[0] < RAMP_SETTLE_S:
            return
        for s, x in ((self._fit, position_mm), (self._fit_force, force_kn)):
            if x is None:
                continue
            s[0] += 1
            s[1] += t
            s[2] += x
            s[3] += t * t
            s[4] += t * x

    @property
    def ramp_seconds(self) -> float:
        """How long the ramp has run, in seconds (its first
        :data:`RAMP_SETTLE_S` are not in the measured rate)."""
        return max(0.0, self._ramp_t[1] - self._ramp_t[0]) if self._ramp_t[0] >= 0 else 0.0

    @property
    def ramp_mm_min(self) -> float | None:
        """The speed the ramp has really run at so far: the slope of position
        against time, least squares over every ramp sample after the settling,
        in mm/min. ``None`` before there are two samples to fit."""
        slope = _slope(self._fit)
        return None if slope is None else slope * 60.0

    @property
    def ramp_kn_s(self) -> float | None:
        """The rate force has really risen at over the ramp so far, in the force
        channel's unit per second — what a force-controlled ramp is judged by."""
        return _slope(self._fit_force)


def _slope(sums: list[float]) -> float | None:
    """Least-squares slope from running sums n, St, Sx, Stt, Stx."""
    n, st, sx, stt, stx = sums
    den = n * stt - st * st
    if n < 2 or den <= 0:
        return None
    return (n * stx - st * sx) / den


@dataclass(frozen=True)
class ForceDisplacement:
    displacement: list[float | None]
    force: list[float | None]
    peak: tuple[float, float] | None
    """``(displacement, force)`` at the test's highest force."""
    origin: float | None
    """The position displacement is counted from: where the start load was
    reached. ``None`` while the approach is still under way."""


class Monitor:
    """Everything the window shows, made from the lines fed to :meth:`feed`."""

    def __init__(self, press: PressConfig):
        self.press = press
        self.proteus = False
        """Whether Proteus has the controller in PC mode (``#B20`` … ``#B21``)."""
        self.streaming = False
        self.interval_ms: int | None = None
        self.phase = Phase.NONE
        self.latest: dict[int, int] = {}
        self.latest_t: float | None = None
        self.latest_counter: int | None = None
        self.tests: list[TestRecord] = []
        self.log: deque[LogEntry] = deque(maxlen=MAX_LOG)
        self.log_total = 0
        """Entries ever logged; the log keeps only the newest :data:`MAX_LOG`."""
        self._recent: deque[tuple[float, dict[int, int]]] = deque()
        self._closed: list[TestRecord] = []
        self.unknown_lines = 0
        self._units = {c.index: c.unit for c in press.channels}
        f, p = press.by_name(FORCE), press.by_name(PATH)
        self.force_index = f.index if f else None
        self.path_index = p.index if p else None

    # ---- what is shown -----------------------------------------------------

    @property
    def current(self) -> TestRecord | None:
        """The test being run or unloaded, if any."""
        return self.tests[-1] if self.tests and not self.tests[-1].closed else None

    @property
    def last(self) -> TestRecord | None:
        """The newest test, open or closed: what the plots show."""
        return self.tests[-1] if self.tests else None

    def value(self, index: int, raw: int) -> float:
        ch = self.press.channel(index)
        return ch.value(raw, self.press.resolution) if ch else float(raw)

    def latest_value(self, index: int | None) -> float | None:
        if index is None or index not in self.latest:
            return None
        return self.value(index, self.latest[index])

    def series(self, test: TestRecord, index: int | None) -> list[float | None]:
        """One channel of ``test`` in engineering units, gaps kept as ``None``."""
        if index is None or index not in test.raw:
            return []
        return [None if r is None else self.value(index, r) for r in test.raw[index]]

    def peak(self, test: TestRecord | None) -> tuple[float, float, float | None] | None:
        """``(force, test time, path)`` at ``test``'s highest force."""
        if test is None:
            return None
        forces = self.series(test, self.force_index)
        best = None
        for i, f in enumerate(forces):
            if f is not None and (best is None or f > forces[best]):
                best = i
        if best is None:
            return None
        paths = self.series(test, self.path_index)
        return forces[best], test.t[best], paths[best] if paths else None

    def loading_start(self, test: TestRecord | None) -> int | None:
        """The first sample of ``test`` at or after the start load was reached.

        Where loading begins: everything before is the approach, tens of
        millimetres of travel at no load, which flattens a force–path curve into
        a vertical line if it is drawn too.
        """
        if test is None:
            return None
        loading = {Phase.AT_START_LOAD.value, Phase.RAMP.value, Phase.RAMP_END.value,
                   Phase.HELD.value}
        return next((i for i, ph in enumerate(test.phase) if ph in loading), None)

    def force_displacement(self, test: TestRecord | None) -> ForceDisplacement:
        """``test``'s force against displacement, as the monitor plots it.

        Displacement is the position channel (*Path*) counted from where it was
        when the start load was reached (:meth:`loading_start`): the approach
        before it is tens of millimetres at no load, which would flatten the
        loading curve into a vertical line. Until the start load is reached the
        approach is given against position as it stands, so the plot is never
        blank while the piston moves; ``origin`` is then ``None``.
        """
        if test is None:
            return ForceDisplacement([], [], None, None)
        forces = self.series(test, self.force_index)
        paths = self.series(test, self.path_index)
        i0 = self.loading_start(test)
        if i0 is None or not paths or paths[i0] is None:
            return ForceDisplacement(paths, forces, None, None)
        origin = paths[i0]
        xs = [None if p is None else p - origin for p in paths[i0:]]
        peak = self.peak(test)
        at = None
        if peak is not None and peak[2] is not None:
            at = (peak[2] - origin, peak[0])
        return ForceDisplacement(xs, forces[i0:], at, origin)

    def ramp_decoded(self, test: TestRecord | None) -> bool:
        """Whether ``test``'s ramp is on a channel whose units are confirmed and
        that this monitor measures (force or path) — the only ramps judged."""
        return (test is not None and test.ramp is not None
                and test.ramp.channel in DECODED_RAMP_CHANNELS
                and test.ramp.channel in (self.force_index, self.path_index)
                and self.press.channel(test.ramp.channel) is not None)

    def ramp_measured(self, test: TestRecord | None) -> float | None:
        """The controlled channel's measured rate over the ramp, in its unit per
        second — comparable with :attr:`Ramp.rate`."""
        if not self.ramp_decoded(test):
            return None
        if test.ramp.channel == self.path_index:
            mm_min = test.ramp_mm_min
            return None if mm_min is None else mm_min / 60.0
        return test.ramp_kn_s

    def rate(self, index: int | None) -> float | None:
        """Units per second over the last :data:`RATE_WINDOW_S`, or ``None``."""
        if index is None or len(self._recent) < 2:
            return None
        (t_a, a), (t_b, b) = self._recent[0], self._recent[-1]
        if t_b - t_a < RATE_WINDOW_S / 2 or index not in a or index not in b:
            return None
        return (self.value(index, b[index]) - self.value(index, a[index])) / (t_b - t_a)

    def pop_closed(self) -> list[TestRecord]:
        """Tests closed since the last call — the ones to save."""
        out, self._closed = self._closed, []
        return out

    # ---- feeding -----------------------------------------------------------

    def feed(self, ev: TapEvent) -> list[Notice]:
        msg = parse(ev.direction, ev.text)
        if isinstance(msg, Sample):
            return self._sample(ev, msg)
        known = not isinstance(msg, Unknown)
        meaning = describe(ev.direction, msg, self._units)
        who = "PC" if ev.direction == PC_TO_CTRL else "controller"
        self.log.append(LogEntry(ev.t, ev.wall, ev.direction, ev.text, meaning, known))
        self.log_total += 1
        before = self.current
        if not known:
            self.unknown_lines += 1
            notices = [Notice(f"A line the protocol notes do not cover: {ev.text!r} "
                              f"({who}). It is in the log and the capture.", warn=True)]
        elif ev.direction == PC_TO_CTRL:
            notices = self._from_pc(ev, msg)
        else:
            notices = self._from_controller(ev, msg)
        # The line belongs to the test it opened (START) or, failing that, to
        # the one it was heard in — including the one it closed.
        after = self.current
        test = after if after is not None and after is not before else before
        if test is not None:
            test.events.append((ev.t - test.t0, f"{who} {ev.text}: {meaning}"))
        return notices

    def _sample(self, ev: TapEvent, s: Sample) -> list[Notice]:
        self.streaming = True
        self.latest = dict(s.raw)
        self.latest_t = ev.t
        self.latest_counter = s.counter
        self._recent.append((ev.t, dict(s.raw)))
        while self._recent and ev.t - self._recent[0][0] > RATE_WINDOW_S:
            self._recent.popleft()
        test = self.current
        if test is not None:
            test.add_sample(ev.t - test.t0, s.counter, self.phase, s.raw)
            if self.phase is Phase.RAMP:
                test.fit_ramp(ev.t - test.t0,
                              self._raw_value(self.path_index, s.raw),
                              self._raw_value(self.force_index, s.raw))
                return self._judge_ramp(test)
        return []

    def _raw_value(self, index: int | None, raw: dict[int, int]) -> float | None:
        return None if index is None or index not in raw else self.value(index, raw[index])

    def _judge_ramp(self, test: TestRecord) -> list[Notice]:
        """Once, after :data:`RAMP_JUDGE_AFTER_S` of ramp (its first
        :data:`RAMP_SETTLE_S` left out of the fit): say so if the press is not
        loading at the rate that was set.

        Path and force ramps are judged, each against its own channel: position
        in mm/min, force in kN/s. A ramp on a channel whose units are not
        confirmed is not — comparing a number in an unknown unit would be a
        false alarm.
        """
        if (test.ramp_judged or not self.ramp_decoded(test)
                or test.ramp_seconds < RAMP_JUDGE_AFTER_S):
            return []
        test.ramp_judged = True
        measured, wanted = self.ramp_measured(test), test.ramp.rate
        if measured is None or wanted <= 0:
            return []
        if abs(measured - wanted) <= RAMP_SPEED_TOLERANCE * wanted:
            return []
        unit = self.press.channel(test.ramp.channel).unit
        text = (f"The ramp is running at {rate_text(measured, unit)}, not the "
                f"{rate_text(wanted, unit)} set (measured from {RAMP_SETTLE_S:.0f} to "
                f"{test.ramp_seconds:.0f} s into it).")
        test.warnings.append(text)
        return [Notice(text, warn=True)]

    def _from_pc(self, ev: TapEvent, msg) -> list[Notice]:
        notices: list[Notice] = []
        match msg:
            case Command(20):
                self.proteus = True
            case Command(21):
                self.proteus = False
                self.streaming = False
                self.interval_ms = None
                self._close("Proteus left PC mode")
                self.phase = Phase.NONE
            case Command(37):
                self.streaming = True
            case Command(36):
                self.streaming = False
            case Command(47):
                self._close("a new START")
                self.tests.append(TestRecord(number=len(self.tests) + 1, started=ev.wall,
                                             t0=ev.t))
                self.phase = Phase.ARMED
            case Command(23):
                self._ensure_test(ev)
                self.phase = Phase.APPROACH
            case Command(22):
                self._ensure_test(ev)
                self.phase = Phase.RAMP
            case Command(18):
                self.phase = Phase.HELD
            case Command(17):
                self.phase = Phase.CANCELLED
            case SetParam(5, value):
                self.interval_ms = value * 10
            case Ramp():
                notices += self._ramp(ev, msg)
        return notices

    def _from_controller(self, ev: TapEvent, msg) -> list[Notice]:
        match msg:
            case Command(1):
                self._ensure_test(ev)
                self.phase = Phase.AT_START_LOAD
            case Command(2):
                if self.current is not None:
                    self.phase = Phase.RAMP_END
            case Command(28):
                return [Notice("Keypad STOP pressed on the controller. In PC mode the "
                               "controller does not act on it; it tells Proteus (#B28).")]
            case Command(43):
                if self.current is not None:
                    self._close("load released")
        return []

    def _ramp(self, ev: TapEvent, ramp: Ramp) -> list[Notice]:
        """Keep the ramp, and where the piston was when it was sent.

        **The start it carries is noted, not warned about** (operator,
        2026-10-19). Proteus has sent 0, 1 and 2 times the piston position, and
        ramps with a start far from the piston ran at their set speed (steps 17
        and 18): warning on every such ramp alarmed the operator about nothing
        and taught them to ignore the colour. What the press really does is
        measured instead, and :meth:`_judge_ramp` is the warning that matters.
        """
        test = self._ensure_test(ev)
        test.ramp = ramp
        test.ramp_from_mm = self.latest_value(self.path_index)
        return []

    def _ensure_test(self, ev: TapEvent) -> TestRecord:
        """The open test, or one opened now for a test already running when the
        monitor started listening."""
        if self.current is None:
            self.tests.append(TestRecord(number=len(self.tests) + 1, started=ev.wall,
                                         t0=ev.t))
            self.current.events.append((0.0, "monitor: test already under way when heard"))
        return self.current

    def _close(self, reason: str) -> None:
        test = self.current
        if test is None:
            return
        test.closed = True
        test.close_reason = reason
        self._closed.append(test)
        self.phase = Phase.CLOSED
