"""A DigiMaxx C-20 as the recordings show it, behind a stand-in serial port.

It answers Proteus' start-up as the real one did in every recorded session,
streams measurement lines after ``#B37`` until ``#B36``, keeps PC mode, Peak and
break detection, and can have its keypad STOP pressed. Everything written to it
is kept, so a test can say exactly what was sent.
"""

from __future__ import annotations

import threading
import time

#: What the controller answered to each start-up query, every time.
ANSWERS = {"#B20": "#O", "#B50": "#D138.6", "#B40": "#D104000", "#B51": "#D140",
           "#B52": "#D180"}


class FakeController:
    def __init__(self, *, interval_s: float = 0.05, answers: dict[str, str] | None = None,
                 busy: bool = False):
        self.answers = dict(ANSWERS if answers is None else answers)
        self.interval_s = interval_s
        self.written: list[str] = []
        self.pc_mode = False
        self.streaming = busy          # a "busy" line is one another PC is already streaming
        self.peak = False
        self.break_detection = True    # the controller's default after power-up
        self.cancelled = 0
        self.dtr = self.rts = None
        self.closed = False
        self._out = bytearray()
        self._buf = b""
        self._lock = threading.Lock()
        self._counter = 0
        self._next_sample = time.monotonic()

    # ---- the controller's keypad ------------------------------------------------

    def press_keypad_stop(self) -> None:
        """What the STOP key does in PC mode: tell the PC, do nothing itself."""
        if self.pc_mode:
            self._emit("#B28")

    # ---- the serial port surface ------------------------------------------------

    def _emit(self, line: str) -> None:
        with self._lock:
            self._out += line.encode("ascii") + b"\r\n"

    def _stream(self) -> None:
        now = time.monotonic()
        while self.streaming and now >= self._next_sample:
            self._counter += 10
            self._emit(f"#D08{self._counter};0;150;1;476700;2;-25600")
            self._next_sample += self.interval_s

    @property
    def in_waiting(self) -> int:
        self._stream()
        with self._lock:
            return len(self._out)

    def read(self, n: int) -> bytes:
        self._stream()
        with self._lock:
            if self._out:
                data, self._out = bytes(self._out[:n]), self._out[n:]
                return data
        time.sleep(0.002)
        return b""

    def write(self, data: bytes) -> int:
        self._buf += data
        while b"\r\n" in self._buf:
            raw, self._buf = self._buf.split(b"\r\n", 1)
            self._receive(raw.decode("ascii"))
        return len(data)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def _receive(self, line: str) -> None:
        self.written.append(line)
        if line == "#B20":
            self.pc_mode = True
        elif line == "#B21":
            self.pc_mode = False
        elif line == "#B37":
            self.streaming = True
            self._next_sample = time.monotonic() + self.interval_s
        elif line == "#B36":
            self.streaming = False
        elif line in ("#B30", "#B31"):
            self.peak = line == "#B31"
        elif line in ("#B32", "#B33"):
            self.break_detection = line == "#B33"
        elif line == "#B17":
            self.cancelled += 1
        if line in self.answers:
            self._emit(self.answers[line])
