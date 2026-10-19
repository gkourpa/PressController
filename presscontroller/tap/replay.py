"""A recorded capture, handed out as if it were being heard now.

Lines come out of :meth:`ReplayTap.poll` when the replay clock reaches the time
they were recorded at, scaled by ``speed``; their own ``t`` and ``wall`` stay as
recorded, so a replayed test carries the times it really had.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from presscontroller.tap.capture import read_capture
from presscontroller.tap.events import TapEvent


class ReplayTap:
    def __init__(self, path: str | Path, *, speed: float = 1.0,
                 clock: Callable[[], float] = time.monotonic):
        if speed <= 0:
            raise ValueError("speed must be above zero")
        self.path = Path(path)
        self.speed = float(speed)
        self._clock = clock
        self._events = read_capture(self.path)
        self._next = 0
        self._t0: float | None = None
        self.errors: list[str] = []

    def start(self) -> None:
        self._t0 = self._clock()

    def poll(self) -> list[TapEvent]:
        if self._t0 is None:
            return []
        now = (self._clock() - self._t0) * self.speed
        start = self._next
        while self._next < len(self._events) and self._events[self._next].t <= now:
            self._next += 1
        return self._events[start:self._next]

    @property
    def finished(self) -> bool:
        return self._next >= len(self._events)

    def close(self) -> None:
        self._t0 = None

    def describe(self) -> str:
        return f"replaying {self.path.name} at {self.speed:g}× speed"
