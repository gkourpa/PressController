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
    PC_TO_CTRL,
    Command,
    Ramp,
    Sample,
    SetParam,
    Unknown,
    describe,
    parse,
)
from presscontroller.tap.events import TapEvent

#: The span the live rates are taken over. Long enough that a 0.2 s stream
#: gives ten points and the ±7-count noise averages down; short enough that a
#: change of speed shows within it.
RATE_WINDOW_S = 2.0

#: How far the ramp's start may sit from where the piston is before the monitor
#: says so. The controller runs the ramp's planned time over the distance really
#: left (docs/PROTOCOL.md, ramp command), so a start that is off by more than
#: noise changes the speed the specimen is loaded at.
RAMP_START_TOLERANCE_MM = 0.5

#: Log entries kept for the window. A day of tests is a few thousand lines;
#: the capture keeps everything regardless.
MAX_LOG = 5000


class Phase(Enum):
    NONE = "no test"
    ARMED = "START pressed"
    APPROACH = "approach"
    AT_START_LOAD = "start load reached"
    RAMP = "ramp"
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
        loading = {Phase.AT_START_LOAD.value, Phase.RAMP.value, Phase.HELD.value}
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
            self._sample(ev, msg)
            return []
        known = not isinstance(msg, Unknown)
        meaning = describe(ev.direction, msg)
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

    def _sample(self, ev: TapEvent, s: Sample) -> None:
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
            case Command(28):
                return [Notice("Keypad STOP pressed on the controller. In PC mode the "
                               "controller does not act on it; it tells Proteus (#B28).")]
            case Command(43):
                if self.current is not None:
                    self._close("load released")
        return []

    def _ramp(self, ev: TapEvent, ramp: Ramp) -> list[Notice]:
        test = self._ensure_test(ev)
        test.ramp = ramp
        here = self.latest_value(self.path_index)
        test.ramp_from_mm = here
        if here is None or self.path_index is None:
            return []
        if abs(ramp.start_um / 1000.0 - here) <= RAMP_START_TOLERANCE_MM:
            return []
        eff = ramp.effective_mm_min(here)
        if eff is None:
            return []
        text = (f"Proteus sent the ramp's start as {ramp.start_um / 1000:.3f} mm with the "
                f"piston at {here:.3f} mm: the controller will load at about "
                f"{eff:.2f} mm/min, not the {ramp.speed_mm_min:.3g} mm/min set.")
        test.warnings.append(text)
        return [Notice(text, warn=True)]

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
