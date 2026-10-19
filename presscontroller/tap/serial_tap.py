"""The live tap: two serial adapters, each hearing one direction. **Never writes.**

The tap is wired so that each adapter's *receive* pin hears one wire of the
link between Proteus and the controller, and none of its outputs is connected
(docs/RS232_Tap_Wiring.pdf). The software keeps its side of that bargain:

* nothing here calls ``write`` — the class has no path that sends a byte;
* DTR and RTS are set **off before the port opens**, so the adapter never
  drives them even for the instant between open and configure. They are not
  wired to the line, but a tap must not depend on its wiring being right.

The line settings are the controller's (9600 8N1, confirmed), not a choice, so
they are constants here rather than configuration.

pyserial is imported lazily, so the app and the tests load without it.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from presscontroller.protocol.lines import CTRL_TO_PC, PC_TO_CTRL, LineAssembler
from presscontroller.tap.capture import CaptureWriter
from presscontroller.tap.events import TapEvent

BAUD = 9600
LINE_SETTINGS = "9600 8N1"

#: How long one read waits for a byte. Short, so close() is prompt; the reads
#: themselves take whatever has arrived, so this does not limit throughput.
READ_TIMEOUT_S = 0.05


def open_read_only(name: str):
    """``name`` opened at the controller's settings, its outputs off from the start."""
    import serial

    port = serial.Serial(baudrate=BAUD, bytesize=serial.EIGHTBITS,
                         parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                         timeout=READ_TIMEOUT_S)
    # Before open: pyserial applies these as it opens, so the lines are never
    # asserted at all, rather than asserted and then dropped.
    port.dtr = False
    port.rts = False
    port.port = name
    port.open()
    return port


class SerialTap:
    """Listen on both adapters; hand out whole lines through :meth:`poll`.

    ``open_port`` is the seam the tests use to put a simulated port in place of
    pyserial; ``capture`` receives every byte as it is heard.
    """

    def __init__(self, pc_port: str, ctrl_port: str, *,
                 capture: CaptureWriter | None = None,
                 open_port: Callable[[str], object] = open_read_only,
                 clock: Callable[[], float] = time.monotonic):
        self.ports = {PC_TO_CTRL: pc_port, CTRL_TO_PC: ctrl_port}
        self._capture = capture
        self._open = open_port
        self._clock = clock
        self._queue: queue.Queue[TapEvent] = queue.Queue()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._handles: dict[str, object] = {}
        self._t0 = 0.0
        self._wall0 = datetime.now()
        self.errors: list[str] = []
        """What went wrong with a port after it opened, in words, newest last."""

    def start(self) -> None:
        """Open both ports and start listening. Raises if either cannot be opened,
        having closed whichever did open."""
        try:
            for direction, name in self.ports.items():
                self._handles[direction] = self._open(name)
        except Exception:
            self._close_handles()
            raise
        self._t0 = self._clock()
        self._wall0 = datetime.now()
        for direction, handle in self._handles.items():
            th = threading.Thread(target=self._read, args=(direction, handle),
                                  name=f"tap {direction}", daemon=True)
            th.start()
            self._threads.append(th)

    def _read(self, direction: str, port) -> None:
        asm = LineAssembler(direction)
        while not self._stop.is_set():
            try:
                data = port.read(port.in_waiting or 1)
            except Exception as exc:          # the adapter was unplugged, typically
                if not self._stop.is_set():
                    self.errors.append(f"{self.ports[direction]} ({direction}) stopped: {exc}")
                return
            if not data:
                continue
            t = self._clock() - self._t0
            if self._capture is not None:
                self._capture.write(direction, t, data)
            for t_line, text in asm.feed(data, t):
                self._queue.put(TapEvent(t_line, self._wall0 + timedelta(seconds=t_line),
                                         direction, text))

    def poll(self) -> list[TapEvent]:
        """Every line completed since the last poll, oldest first."""
        out = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                return sorted(out, key=lambda e: e.t)

    def close(self) -> None:
        self._stop.set()
        for th in self._threads:
            th.join(timeout=1.0)
        self._threads.clear()
        self._close_handles()
        if self._capture is not None:
            self._capture.close()

    def _close_handles(self) -> None:
        for h in self._handles.values():
            try:
                h.close()
            except Exception:
                pass
        self._handles.clear()

    def describe(self) -> str:
        return (f"listening on {self.ports[PC_TO_CTRL]} (PC → controller) and "
                f"{self.ports[CTRL_TO_PC]} (controller → PC), read-only, {LINE_SETTINGS}")
