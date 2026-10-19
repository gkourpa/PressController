"""The one thing a tap hands out: a whole line, from one direction, with its time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class TapEvent:
    t: float
    """Seconds since the source started, at the line's first byte."""
    wall: datetime
    """Local wall-clock time of the same instant."""
    direction: str
    """:data:`~presscontroller.protocol.PC_TO_CTRL` or
    :data:`~presscontroller.protocol.CTRL_TO_PC`."""
    text: str
    """The line, terminator removed."""
