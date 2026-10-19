"""The one serial port the program talks to the controller through.

This is the only place in the package that writes to a port, and every line
goes through :func:`~presscontroller.control.commands.check` first, so a line
not on the allowlist raises before a byte is written.

**What is sent is heard as well as what is received.** Each sent line is
handed out through :meth:`ControllerLink.poll` as a ``PC>CTRL``
:class:`~presscontroller.tap.TapEvent`, exactly as the tap would have heard it,
so the monitor follows our own session as it followed Proteus', and the capture
holds both directions in the sniffer's format — replayable like any other.

The port is opened as Proteus' was: 9600 8N1, with DTR and RTS asserted (the
tap saw the PC's RTS asserted throughout; a Windows port asserts DTR with it).
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from presscontroller.control.commands import check
from presscontroller.protocol.lines import CTRL_TO_PC, PC_TO_CTRL, LineAssembler
from presscontroller.tap.capture import CaptureWriter
from presscontroller.tap.events import TapEvent
from presscontroller.tap.serial_tap import BAUD, LINE_SETTINGS, READ_TIMEOUT_S

TERMINATOR = b"\r\n"


def open_for_control(name: str):
    """``name`` opened at the controller's settings, DTR and RTS asserted as a
    PC's port is."""
    import serial

    port = serial.Serial(baudrate=BAUD, bytesize=serial.EIGHTBITS,
                         parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                         timeout=READ_TIMEOUT_S, write_timeout=1.0)
    port.dtr = True
    port.rts = True
    port.port = name
    port.open()
    return port


class ControllerLink:
    """Read the controller's lines; send ours, if they are allowed."""

    def __init__(self, port_name: str, *, capture: CaptureWriter | None = None,
                 open_port: Callable[[str], object] = open_for_control,
                 clock: Callable[[], float] = time.monotonic):
        self.port_name = port_name
        self._capture = capture
        self._open = open_port
        self._clock = clock
        self._queue: queue.Queue[TapEvent] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._port = None
        self._write_lock = threading.Lock()
        self._t0 = 0.0
        self._wall0 = datetime.now()
        self.errors: list[str] = []
        self.sent: list[str] = []
        """Every line sent, in order — what the tests compare with Proteus'."""

    @property
    def is_open(self) -> bool:
        return self._port is not None

    def start(self) -> None:
        self._port = self._open(self.port_name)
        self._t0 = self._clock()
        self._wall0 = datetime.now()
        self._thread = threading.Thread(target=self._read, name="controller link", daemon=True)
        self._thread.start()

    def _now(self) -> float:
        return self._clock() - self._t0

    def _event(self, t: float, direction: str, text: str) -> TapEvent:
        return TapEvent(t, self._wall0 + timedelta(seconds=t), direction, text)

    def _read(self) -> None:
        asm = LineAssembler(CTRL_TO_PC)
        port = self._port
        while not self._stop.is_set():
            try:
                data = port.read(port.in_waiting or 1)
            except Exception as exc:
                if not self._stop.is_set():
                    self.errors.append(f"{self.port_name} stopped: {exc}")
                return
            if not data:
                continue
            t = self._now()
            if self._capture is not None:
                self._capture.write(CTRL_TO_PC, t, data)
            for t_line, text in asm.feed(data, t):
                self._queue.put(self._event(t_line, CTRL_TO_PC, text))

    def send(self, line: str) -> None:
        """Send one allowed line. Raises
        :class:`~presscontroller.control.commands.NotAllowed` — before writing —
        for any other."""
        check(line)
        if self._port is None:
            raise RuntimeError("the link is not open")
        data = line.encode("ascii") + TERMINATOR
        with self._write_lock:
            t = self._now()
            self._port.write(data)
            self._port.flush()
            self.sent.append(line)
            if self._capture is not None:
                self._capture.write(PC_TO_CTRL, t, data)
            self._queue.put(self._event(t, PC_TO_CTRL, line))

    def poll(self) -> list[TapEvent]:
        out = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                return sorted(out, key=lambda e: e.t)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                pass
            self._port = None
        if self._capture is not None:
            self._capture.close()

    def describe(self) -> str:
        return f"in control on {self.port_name}, {LINE_SETTINGS}"
