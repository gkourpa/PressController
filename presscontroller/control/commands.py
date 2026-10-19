"""What this milestone may send to the controller, and nothing else.

**An allowlist of exact lines**, not of command numbers: a line is sent only if
it is character for character one of these. Every one was sent by Proteus in
the recorded sessions (docs/PROTOCOL.md), and none of them moves the press.

Left out on purpose, until a milestone adds motion with its own review:

* ``#B47`` START, ``#B23`` approach, ``#B22`` ramp, ``#D12…`` ramp definition,
  ``#D0910`` (sent with the approach), ``#D0520`` (sent with the ramp) — they
  move the piston or belong to moving it;
* ``#B18`` Stop — holds a moving piston; there is nothing to hold here;
* ``#B26`` — Proteus' answer to a ramp's end.

``#B17`` (Cancel: pump off) **is** allowed: it is what the program sends when
the operator presses STOP on the controller's keypad, which in PC mode the
controller hands to the PC instead of acting on (docs/PROTOCOL.md, ``#B28``). It
stops the pump; it never starts anything.
"""

from __future__ import annotations

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

#: Leaving PC mode, as Proteus does when it closes: the stream off, then PC mode
#: off. Afterwards the controller's own keypad works again.
DISCONNECT = (STREAM_OFF, PC_MODE_OFF)

ALLOWED: frozenset[str] = frozenset(
    [line for group in STARTUP_GROUPS for line in group]
    + [STREAM_ON, STREAM_OFF, PC_MODE_OFF, CANCEL, PEAK_OFF, PEAK_ON, BREAK_OFF, BREAK_ON])

#: Lines that move the press or belong to moving it. Not in :data:`ALLOWED`; kept
#: here so a test can assert the two never overlap.
MOTION: frozenset[str] = frozenset(["#B47", "#B23", "#B22", "#B18", "#B26", "#D0910", "#D0520"])


class NotAllowed(ValueError):
    """A line that is not on the allowlist. Raised before a byte is written."""


def check(line: str) -> str:
    """``line`` if it may be sent; :class:`NotAllowed` otherwise."""
    if line not in ALLOWED:
        raise NotAllowed(f"{line!r} is not on this milestone's allowlist; nothing was sent")
    return line
