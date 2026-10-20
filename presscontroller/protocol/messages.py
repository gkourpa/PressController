"""One protocol line into one message, and what that message is believed to mean.

The grammar (docs/PROTOCOL.md): every line is ``#`` + a letter + text.

======================  ==========  ===============================================
line                    from        message
======================  ==========  ===============================================
``#D0<s><n>;0;f;1;p…``  controller  :class:`Sample` — the measurement stream
``#D1<text>``           controller  :class:`Reply` — a value asked for at start-up
``#O``                  controller  :class:`Ack`
``#B<nn>``              either      :class:`Command` — a numbered command or event
``#D0<p><v>``           PC          :class:`SetParam` — one digit of parameter, value
``#D12<v>;<a>;<b>;…``   PC          :class:`Ramp` — the main test's definition
``#D21<n>``             PC          :class:`BreakThreshold` — after break detection on
``   NAME   value``      controller  :class:`ReportLine` — its own test report
anything else           either      :class:`Unknown`, kept verbatim
======================  ==========  ===============================================

**Nothing that does not parse is dropped.** An :class:`Unknown` is a line the
protocol notes do not cover yet, and seeing it is how the notes grow.

The meanings in :data:`COMMANDS` and :data:`PARAMS` carry ``confirmed``: a
meaning seen to hold — on the controller's own display, or in what the press did
— is confirmed; one inferred from when the line is sent is not, and is shown
with a question mark wherever it is shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from presscontroller.protocol.lines import CTRL_TO_PC, PC_TO_CTRL


@dataclass(frozen=True)
class Sample:
    """One line of the measurement stream: raw counts per channel.

    ``status`` is the digit after ``#D0``; it has been ``8`` in every line seen
    and its meaning is unknown, so it is kept rather than assumed. ``counter`` is
    the controller's own clock in 10 ms ticks: +10 per line at the 100 ms
    interval, +20 at 200 ms, and reset to a small number when a test's approach
    starts.
    """

    status: int
    counter: int
    raw: dict[int, int]


@dataclass(frozen=True)
class Reply:
    """``#D1<text>``: a value the controller gives back at start-up (``38.6``,
    ``04000``, ``40``, ``80``). Kept as text: ``04000`` is believed to be the
    machine's capacity in kN and ``38.6`` its firmware, neither confirmed."""

    text: str


@dataclass(frozen=True)
class Ack:
    """``#O``: the controller's acknowledgement."""


@dataclass(frozen=True)
class Command:
    """``#B<nn>``: a numbered command (from the PC) or event (from the controller)."""

    code: int


@dataclass(frozen=True)
class SetParam:
    """``#D0<p><v>`` from the PC: parameter ``p`` (one digit) set to ``v``.

    The one-digit split is itself an inference — it is the reading under which
    ``#D0510`` and ``#D0520`` are the stream interval in 10 ms units, which the
    stream then followed.
    """

    param: int
    value: int


@dataclass(frozen=True)
class Ramp:
    """``#D12<speed>;<start>;<end>;<field4>;<channel>``: the main test's ramp.

    ``channel`` is the **controlled channel**, numbered as in the stream, and
    ``speed``, ``start`` and ``end`` are in **thousandths of that channel's
    unit**: µm/s and µm for Path (channel 1; steps 15–19, at 1, 3, 6 and
    10 mm/min) and N/s and N for Force (channel 0; step 20, 5000 for 5 kN/s, which
    ran at 5.03 kN/s, and 300000 for 300 kN) — docs/PROTOCOL.md. Only those two
    channels are confirmed (:data:`DECODED_RAMP_CHANNELS`).

    What Proteus puts in ``start`` is not understood — 0, 1 and 2 times the
    piston position — and it does not set the speed, so **no speed is predicted
    from it**; the monitor measures the rate the press really runs at instead.
    ``field4`` is unknown (``0`` every time).
    """

    speed: int
    start: int
    end: int
    field4: int
    channel: int

    @property
    def rate(self) -> float:
        """The set rate in the channel's own unit per second (kN/s, mm/s)."""
        return self.speed / 1000.0

    @property
    def start_value(self) -> float:
        return self.start / 1000.0

    @property
    def end_value(self) -> float:
        return self.end / 1000.0


@dataclass(frozen=True)
class BreakThreshold:
    """``#D21<n>`` from the PC: the template's break threshold × 10.

    Proteus sends it right after ``#B33`` when its template's "Break
    identification (Servo)" is ticked: 10 ‰ → ``#D21100``, 25 ‰ → ``#D21250``
    (step 26). That it is the threshold Proteus was given is confirmed; what the
    controller does with it is not yet seen.
    """

    value: int

    @property
    def per_mil(self) -> float:
        return self.value / 10.0


@dataclass(frozen=True)
class ReportLine:
    """One line of the controller's own test report — indented text, a name in
    capitals and its value: ``      BREAK            44.9 kN``. Sent once, on
    leaving PC mode during a test (step 31): ``DATE``, ``IDENT``, ``ORDER``,
    ``TESTER``, ``AGE``, ``BREAK``, ``DEFORM``. The value is kept as text."""

    name: str
    value: str


@dataclass(frozen=True)
class Unknown:
    """A line no rule here covers, kept exactly as it arrived."""

    text: str


Message = (Sample | Reply | Ack | Command | SetParam | Ramp | BreakThreshold | ReportLine
           | Unknown)

#: The ramp channels whose units are confirmed: 0 (Force, N and N/s) and 1 (Path,
#: µm and µm/s). A ramp on any other channel is kept, but its numbers are not read
#: in that channel's unit until a test confirms it.
DECODED_RAMP_CHANNELS = frozenset({0, 1})


def rate_text(per_s: float, unit: str) -> str:
    """A rate as a test is set in it: a length per minute, anything else per second.

    Displacement rates are set in mm/min and force rates in kN/s, in Proteus and
    in the standards; showing one in the other's convention makes a correct
    number look wrong.
    """
    if unit in ("mm", "µm", "um"):
        return f"{per_s * 60:.3g} {unit}/min"
    return f"{per_s:.3g} {unit}/s"

_SAMPLE = re.compile(r"#D0(\d)(\d+)((?:;-?\d+;-?\d+)+)")
_REPLY = re.compile(r"#D1(.*)")
_COMMAND = re.compile(r"#B(\d\d)")
_RAMP = re.compile(r"#D12(\d+);(-?\d+);(-?\d+);(-?\d+);(-?\d+)")
_PARAM = re.compile(r"#D0(\d)(\d+)")
_BREAK_THRESHOLD = re.compile(r"#D21(\d+)")
_REPORT = re.compile(r" {2,}([A-Z]{2,}) {2,}(\S.*?)\s*")


def parse(direction: str, text: str) -> Message:
    """The message ``text`` carries, read as coming from ``direction``.

    The direction matters: ``#D0…`` is a stream line from the controller and a
    parameter from the PC, and ``#D1…`` a reply from one and a ramp from the
    other.
    """
    if m := _COMMAND.fullmatch(text):
        return Command(int(m[1]))
    if direction == CTRL_TO_PC:
        if text == "#O":
            return Ack()
        if m := _SAMPLE.fullmatch(text):
            nums = [int(x) for x in m[3][1:].split(";")]
            return Sample(int(m[1]), int(m[2]), dict(zip(nums[0::2], nums[1::2])))
        if m := _REPLY.fullmatch(text):
            return Reply(m[1])
        if m := _REPORT.fullmatch(text):
            return ReportLine(m[1], m[2])
    elif direction == PC_TO_CTRL:
        if m := _RAMP.fullmatch(text):
            return Ramp(*(int(g) for g in m.groups()))
        if m := _PARAM.fullmatch(text):
            return SetParam(int(m[1]), int(m[2]))
        if m := _BREAK_THRESHOLD.fullmatch(text):
            return BreakThreshold(int(m[1]))
    return Unknown(text)


@dataclass(frozen=True)
class Meaning:
    label: str
    confirmed: bool


#: ``(direction, code)`` → what a ``#B<nn>`` is believed to mean. The PC's
#: commands and the controller's events are numbered apart, so far.
COMMANDS: dict[tuple[str, int], Meaning] = {
    (PC_TO_CTRL, 3): Meaning("start-up command", False),
    (PC_TO_CTRL, 9): Meaning("start-up command", False),
    (PC_TO_CTRL, 17): Meaning("Cancel: pump off, test ends", True),
    (PC_TO_CTRL, 18): Meaning("PAUSE / CONTINUE (toggles; freezes the ramp's target)", True),
    (PC_TO_CTRL, 20): Meaning("PC mode on", False),
    (PC_TO_CTRL, 21): Meaning("PC mode off", True),
    (PC_TO_CTRL, 22): Meaning("start the ramp", True),
    (PC_TO_CTRL, 23): Meaning("start the approach", True),
    (PC_TO_CTRL, 26): Meaning("test finished (answer to ramp end)", False),
    (PC_TO_CTRL, 30): Meaning("peak detection off", True),
    (PC_TO_CTRL, 31): Meaning("peak detection on", True),
    (PC_TO_CTRL, 32): Meaning("break detection off", True),
    (PC_TO_CTRL, 33): Meaning("break detection on", True),
    (PC_TO_CTRL, 36): Meaning("stream off", True),
    (PC_TO_CTRL, 37): Meaning("stream on", True),
    (PC_TO_CTRL, 40): Meaning("start-up query", False),
    (PC_TO_CTRL, 41): Meaning("start-up command", False),
    (PC_TO_CTRL, 24): Meaning("machine switching (Proteus' program; never seen)", False),
    (PC_TO_CTRL, 34): Meaning("unknown (Proteus' program; never seen)", False),
    (PC_TO_CTRL, 38): Meaning("ramp halted (Proteus' program; never seen)", False),
    (PC_TO_CTRL, 47): Meaning("START pressed: arm the test", True),
    (PC_TO_CTRL, 60): Meaning("unknown (Proteus' program; never seen)", False),
    (PC_TO_CTRL, 50): Meaning("start-up query", False),
    (PC_TO_CTRL, 51): Meaning("start-up query", False),
    (PC_TO_CTRL, 52): Meaning("start-up query", False),
    (CTRL_TO_PC, 1): Meaning("start load reached", True),
    (CTRL_TO_PC, 2): Meaning("ramp end reached", True),
    (CTRL_TO_PC, 27): Meaning("break detected (break detection on; the force fell by the "
                              "threshold from its peak)", False),
    (CTRL_TO_PC, 28): Meaning("keypad STOP pressed", True),
    (CTRL_TO_PC, 35): Meaning("answer to the ramp", False),
    (CTRL_TO_PC, 43): Meaning("test over, load released", False),
}

#: ``#D0<p>`` parameter → meaning.
PARAMS: dict[int, Meaning] = {
    2: Meaning("start-up parameter", False),
    5: Meaning("stream interval (×10 ms)", True),
    9: Meaning("start load (×0.01 % of the force range)", False),
}


def _with_doubt(m: Meaning) -> str:
    return m.label if m.confirmed else f"{m.label}?"


def describe(direction: str, msg: Message, units: dict[int, str] | None = None) -> str:
    """One line of plain words for the event log. A guess ends in ``?``.

    ``units`` names each channel's unit (from the press file), so a ramp can be
    told in it; without it a ramp is given in raw numbers.
    """
    match msg:
        case Command(code):
            m = COMMANDS.get((direction, code))
            return _with_doubt(m) if m else "unknown command"
        case Ack():
            return "OK"
        case Reply(text):
            return f"reply {text}"
        case SetParam(param, value):
            m = PARAMS.get(param)
            if param == 5:
                return f"stream interval {value * 10} ms"
            return f"{_with_doubt(m)} = {value}" if m else f"parameter {param} = {value}"
        case Ramp():
            unit = (units or {}).get(msg.channel)
            if msg.channel not in DECODED_RAMP_CHANNELS or unit is None:
                return (f"ramp on channel {msg.channel}: speed {msg.speed}, start "
                        f"{msg.start}, end {msg.end} (units not decoded for this channel)")
            return (f"ramp on channel {msg.channel}: {rate_text(msg.rate, unit)} from "
                    f"{msg.start_value:g} to {msg.end_value:g} {unit}")
        case ReportLine(name, value):
            return "the controller's own report"
        case BreakThreshold():
            return f"break threshold {msg.per_mil:g} ‰"
        case Sample():
            return "measurement"
        case Unknown():
            return ""
    return ""
