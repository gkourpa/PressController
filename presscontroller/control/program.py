"""A test's program, planned before a byte is sent: every step's lines, its
expected time, whether break detection is on during it, and what is wrong with
it, in words.

What a program sends (docs/motion.md, "Programs"; steps 35–41):

* **START**: Peak as the switch stands, then break detection — **on** with its
  threshold (``#B33 #D21…``) when the first step has it on, as Proteus does
  when its template's break identification comes first (step 26), **off**
  (``#B32``) otherwise, always: the controller keeps break detection's last
  state across tests and Proteus restarts (step 37), so a program never leaves
  it to chance. Then the start load and the approach.
* **A ramp**: the measuring interval and ``#D12…`` (then ``#B22`` on the
  controller's ``#B35``), as Proteus sends before every ramp, on its own
  channel: **Force** (0) or **Path** (1), mixed in one test (step 41). Up or
  down — a ramp down is the same line with an end below (steps 36, 41). The
  ramp that switches break detection on is preceded by ``#B33 #D21…``, in the
  same burst (steps 36, 38, 41).
* **A Path ramp "by" a distance** is sent with its end worked out as Proteus
  does (steps 39–41): from the previous ramp's *set* end when that ramp was a
  Path ramp, else from the piston's position when it is sent — so its line is
  built then, by the session (:attr:`PlannedStep.path_by`).
* **A ramp's end** (``#B02``, when the ramp's *target* reaches its end — the
  reading may lag, step 40): ``#B26`` alone, and the controller holds the force
  or the position; ``#B26 #B17`` after the last step.
* **A hold**: nothing is sent; the program times it, as Proteus does
  (10.0 s between ``#B26`` and the next ramp, steps 36–41). A hold as the last
  step ends with ``#B17``.

**Checked here, per step**: a ramp's speed against the press file's
``[limits]`` and its end against the range, a Force ramp that would not move
or would end below the start load, and **an unload break detection would read
as a break**: the controller reports ``#B27`` once the force has fallen by the
threshold from its peak since ``#B33`` (39.9 kN at 10 ‰, steps 35 and 37). A
Force ramp down is checked where the forces are known; after a Path step they
are not, and a Path ramp down with break detection on is refused outright (its
load fell 123 kN in step 41).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from presscontroller.config.settings import ProgramStep, TemplateSettings, steps_problems
from presscontroller.control import commands as cmd
from presscontroller.control.commands import Limits, NotAllowed

#: A Force ramp whose end is closer than this to where the step before ended
#: would not move: the controller's answer to it was never recorded.
MIN_RAMP_KN = 0.5

#: Where a Path ramp "by" a distance starts from.
FROM_PISTON = "the piston"
FROM_PREVIOUS = "the previous ramp's end"


@dataclass(frozen=True)
class PlannedStep:
    number: int
    """1-based, as the operator counts."""
    kind: str
    """``ramp`` or ``hold``."""
    control: str
    """A ramp's ``force`` or ``path``; a hold's is the ramp's before it."""
    told: str
    """In words: ``Force ↑ to 200 kN at 2 kN/s``, ``Path ↓ by 1 mm at 2 mm/min``,
    ``Hold 10 s at 200 kN``."""
    lines: tuple[str, ...]
    """What starts it (a ramp): break detection on if it is this step's, the
    interval, and the ramp — unless :attr:`path_by` is set, when the session
    builds the ramp as it sends it. ``#B22`` follows on the controller's ``#B35``."""
    seconds: float | None
    """How long it should take, ``None`` when that depends on where the step
    before left the press."""
    from_value: float | None
    to_value: float | None
    """In the step's own unit (kN, or mm for Path), as planned; ``None`` where
    only the press will know."""
    speed: float = 0.0
    """A ramp's speed: kN/s, or mm/min."""
    path_by: float | None = None
    """A Path ramp "by" a distance whose end is worked out when it is sent."""
    path_from: str = ""
    """Where that distance is counted from: :data:`FROM_PISTON` or
    :data:`FROM_PREVIOUS`."""
    hold_s: float = 0.0
    break_on: bool = False
    """Break detection on during this step."""
    switches_break_on: bool = False
    """This step switches break detection on (at START if it is step 1)."""
    problem: str | None = None

    @property
    def unit(self) -> str:
        return "mm" if self.control == "path" else "kN"


@dataclass(frozen=True)
class Program:
    steps: tuple[PlannedStep, ...]
    start_switches: tuple[str, ...]
    """Sent at START, after the controller's ``#O``: Peak, break detection."""
    start_load: str
    problems: tuple[str, ...]
    """Everything that stops the program being run, ``step n: …`` where a step's."""
    start_kn: float
    """The start load in kN: where the first Force ramp starts from."""

    @property
    def ok(self) -> bool:
        return not self.problems

    @property
    def controls(self) -> set[str]:
        return {s.control for s in self.steps if s.kind == "ramp"}

    @property
    def total_s(self) -> float | None:
        """The program's planned length after the start load, ``None`` when a
        step's length cannot be known beforehand."""
        if any(s.seconds is None for s in self.steps):
            return None
        return sum(s.seconds for s in self.steps)

    @property
    def force_profile_known(self) -> bool:
        """Whether force against time can be drawn: Force steps only, every
        length known."""
        return self.controls <= {"force"} and self.total_s is not None

    @property
    def break_from(self) -> int | None:
        """The step from which break detection is on, ``None`` if never."""
        return next((s.number for s in self.steps if s.break_on), None)

    def told(self) -> str:
        """The program in one line, as the control window shows it."""
        if not self.steps:
            return "no steps"
        if len(self.steps) == 1:
            s = self.steps[0]
            # " · " parts: the control window puts each on its own line.
            bd = " · break detection on" if s.break_on else " · break detection off"
            if s.control == "path":
                if s.path_by is not None:
                    return (f"Path {_num(s.speed)} mm/min by {s.path_by:+g} mm{bd}")
                return f"Path {_num(s.speed)} mm/min to {_num(s.to_value)} mm{bd}"
            return f"Force {_num(s.speed)} kN/s to {_num(s.to_value)} kN{bd}"
        ramps = sum(1 for s in self.steps if s.kind == "ramp")
        holds = len(self.steps) - ramps
        out = f"{len(self.steps)} steps ({ramps} ramps, {holds} holds)"
        if (total := self.total_s) is not None:
            out += f" · about {duration_text(total)}"
        bd = self.break_from
        out += (f" · break detection from step {bd}" if bd is not None
                else " · break detection off")
        return out


def duration_text(seconds: float) -> str:
    s = round(seconds)
    if s < 60:
        return f"{s} s"
    return f"{s // 60} min {s % 60:02d} s"


def _num(v: float | None) -> str:
    return "?" if v is None else f"{v:g}"


def plan_program(t: TemplateSettings, limits: Limits | None, *, peak: bool) -> Program:
    """``t``'s program, every line built that can be and every step checked;
    never raises."""
    problems: list[str] = []
    peak_line = cmd.PEAK_ON if peak else cmd.PEAK_OFF
    try:
        start_load = cmd.start_load_line(t.start_load_percent)
    except NotAllowed as exc:
        start_load = ""
        problems.append(str(exc))
    try:
        interval = (cmd.interval_line(t.measuring_interval_ms),)
    except NotAllowed as exc:
        interval = ()
        problems.append(str(exc))
    try:
        break_lines = (cmd.BREAK_ON, cmd.break_threshold_line(t.break_threshold_per_mil))
    except NotAllowed as exc:
        break_lines = (cmd.BREAK_ON,)
        problems.append(str(exc))
    force_range = limits.force_range_kn if limits is not None else 0.0
    start_kn = t.start_load_percent / 100.0 * force_range
    problems += steps_problems(t.steps)
    threshold_kn = t.break_threshold_per_mil / 1000.0 * force_range
    first_on = next((i for i, s in enumerate(t.steps) if s.kind == "ramp" and s.break_on), None)
    at_start = first_on == 0

    planned: list[PlannedStep] = []
    force: float | None = start_kn       # the force where the step before left it
    path_end: float | None = None         # the previous Path ramp's set end, if known
    last_control = "force"
    prev_was_path = False
    peak_since_on: float | None = None
    for i, s in enumerate(t.steps):
        n = i + 1
        on = first_on is not None and i >= first_on
        if on and i == first_on:
            peak_since_on = force
        if s.kind == "hold":
            why = "; ".join(s.problems()) or ("a program must start with a ramp"
                                               if i == 0 else None)
            if last_control == "force":
                where = f"{_num(force)} kN" if force is not None else "the force reached"
            else:
                where = f"{_num(path_end)} mm" if path_end is not None else "the position reached"
            here = force if last_control == "force" else path_end
            planned.append(PlannedStep(n, "hold", last_control, f"Hold {_num(s.hold_s)} s at {where}",
                                       (), s.hold_s, here, here, hold_s=s.hold_s, break_on=on,
                                       problem=why))
            continue
        switch = break_lines if (on and i == first_on and not at_start) else ()
        prefix = switch + interval
        if s.control == "path":
            step, path_end, why = _path_step(n, s, limits, prefix, path_end, prev_was_path, on)
            force = None
            if on:
                peak_since_on = None          # what the force did is not known
            prev_was_path = True
        else:
            step, why = _force_step(n, s, limits, prefix, force, start_kn, on,
                                    peak_since_on, threshold_kn)
            force = s.end_kn
            if on and peak_since_on is not None:
                peak_since_on = max(peak_since_on, force)
            prev_was_path = False
        last_control = s.control
        why = why or ("; ".join(s.problems()) or None)
        planned.append(_with(step, break_on=on, switches_break_on=on and i == first_on,
                             problem=why))
        if why:
            problems.append(f"step {n}: {why}")
    switches = (peak_line,) + (break_lines if at_start else (cmd.BREAK_OFF,))
    return Program(tuple(planned), switches, start_load, tuple(problems), start_kn)


def _with(step: PlannedStep, **change) -> PlannedStep:
    return replace(step, **change)


def _force_step(n: int, s: ProgramStep, limits: Limits | None, prefix: tuple[str, ...],
                force: float | None, start_kn: float, on: bool, peak_since_on: float | None,
                threshold_kn: float) -> tuple[PlannedStep, str | None]:
    up = None if force is None else s.end_kn >= force
    arrow = {True: "↑ ", False: "↓ ", None: ""}[up]
    told = f"Force {arrow}to {_num(s.end_kn)} kN at {_num(s.speed_kn_s)} kN/s"
    why = None
    lines: tuple[str, ...] = ()
    try:
        lines = prefix + (cmd.ramp_line(limits, "force", s.speed_kn_s, s.end_kn),)
    except NotAllowed as exc:
        why = str(exc)
    if why is None:
        if force is not None and abs(s.end_kn - force) < MIN_RAMP_KN:
            why = f"already at {_num(force)} kN: this ramp would not move"
        elif s.end_kn < start_kn:
            why = f"its end is below the start load ({start_kn:.3g} kN)"
        elif (on and up is False and peak_since_on is not None
              and peak_since_on - s.end_kn >= threshold_kn):
            why = (f"break detection is on: unloading {peak_since_on - s.end_kn:.0f} kN "
                   f"from {_num(peak_since_on)} kN would read as a break (threshold "
                   f"{threshold_kn:.0f} kN)")
    seconds = (abs(s.end_kn - force) / s.speed_kn_s
               if force is not None and s.speed_kn_s > 0 else None)
    return PlannedStep(n, "ramp", "force", told, lines, seconds, force, s.end_kn,
                       speed=s.speed_kn_s), why


def _path_step(n: int, s: ProgramStep, limits: Limits | None, prefix: tuple[str, ...],
               path_end: float | None, prev_was_path: bool,
               on: bool) -> tuple[PlannedStep, float | None, str | None]:
    """The Path ramp, the set end it leaves (``None`` if only known when it is
    sent), and what is wrong with it."""
    speed = s.speed_mm_min
    if limits is None:
        why: str | None = "the press file sets no [limits], so no ramp may be sent"
    else:
        why = limits.speed_problem("path", speed)
    seconds = abs(s.path_mm) / (speed / 60.0) if s.path_relative and speed > 0 else None
    if not s.path_relative:
        down = None if path_end is None else s.path_mm < path_end
        arrow = {True: "↓ ", False: "↑ ", None: ""}[down]
        told = f"Path {arrow}to {_num(s.path_mm)} mm at {_num(speed)} mm/min"
        lines: tuple[str, ...] = ()
        if why is None:
            try:
                lines = prefix + (cmd.ramp_line(limits, "path", speed, s.path_mm),)
            except NotAllowed as exc:
                why = str(exc)
        if why is None and on and down:
            why = _PATH_DOWN_UNDER_BREAK
        if path_end is not None and speed > 0:
            seconds = abs(s.path_mm - path_end) / (speed / 60.0)
        return (PlannedStep(n, "ramp", "path", told, lines, seconds, path_end, s.path_mm,
                            speed=speed), s.path_mm, why)
    d = s.path_mm
    base = FROM_PREVIOUS if prev_was_path else FROM_PISTON
    told = (f"Path {'↑' if d > 0 else '↓'} by {abs(d):g} mm from {base} "
            f"at {_num(speed)} mm/min")
    if why is None and on and d < 0:
        why = _PATH_DOWN_UNDER_BREAK
    end = path_end + d if (base == FROM_PREVIOUS and path_end is not None) else None
    if why is None and end is not None and limits is not None:
        try:
            cmd.ramp_line(limits, "path", speed, end)
        except NotAllowed as exc:
            why = str(exc)
    return (PlannedStep(n, "ramp", "path", told, prefix, seconds, path_end, end, speed=speed,
                        path_by=d, path_from=base), end, why)


_PATH_DOWN_UNDER_BREAK = ("break detection is on: a Path ramp down unloads the specimen, which "
                          "reads as a break — switch it on after this step")
