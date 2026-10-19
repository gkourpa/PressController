"""Captures: every byte heard, as JSON lines — written live, read back for replay.

The format is the one ``tools/sniff.py`` writes, so the captures recorded while
the protocol was being worked out replay in the monitor unchanged::

    {"type": "meta", "settings": "9600 8N1", "ports": {...}, "start": "<iso>"}
    {"type": "frame", "t": 1.234, "dir": "CTRL>PC", "hex": "2344..."}
    {"type": "lines", ...}          (sniff's modem-line records; skipped here)

**Bytes, not lines, are what is kept.** A capture is the evidence a decoding was
checked against, and a decoder that mis-split a line must not have its mistake
baked into the record it is checked against. Lines are rebuilt on reading.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from pathlib import Path

from presscontroller.protocol.lines import DIRECTIONS, LineAssembler
from presscontroller.tap.events import TapEvent


class CaptureWriter:
    """Append raw chunks to a capture file, flushed as they come.

    Thread-safe: the tap's two reader threads share one writer. A file that
    already exists is refused rather than appended to — two sessions in one file
    would share one clock and could not be told apart.
    """

    def __init__(self, path: str | Path, *, ports: dict[str, str], settings: str,
                 start: datetime):
        path = Path(path)
        if path.exists():
            raise FileExistsError(f"{path} already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._f = open(path, "x", encoding="utf-8", newline="\n")
        self._put({"type": "meta", "settings": settings, "ports": ports,
                   "start": start.isoformat()})

    def _put(self, record: dict) -> None:
        self._f.write(json.dumps(record) + "\n")
        self._f.flush()

    def write(self, direction: str, t: float, data: bytes) -> None:
        with self._lock:
            if not self._f.closed:
                self._put({"type": "frame", "t": round(t, 6), "dir": direction,
                           "hex": data.hex()})

    def close(self) -> None:
        with self._lock:
            if not self._f.closed:
                self._f.close()


def read_capture(path: str | Path) -> list[TapEvent]:
    """Every whole line in the capture at ``path``, in time order.

    A line still unterminated when the capture ends is left out: it was cut off
    by the recording stopping, and a half line parses as something it is not.
    """
    start: datetime | None = None
    asm = {d: LineAssembler(d) for d in DIRECTIONS}
    events: list[TapEvent] = []
    lines: list[tuple[float, str, str]] = []
    with open(path, encoding="utf-8") as f:
        for raw in f:
            if not raw.strip():
                continue
            rec = json.loads(raw)
            kind = rec.get("type")
            if kind == "meta":
                start = datetime.fromisoformat(rec["start"])
            elif kind == "frame" and rec.get("dir") in asm:
                for t0, text in asm[rec["dir"]].feed(bytes.fromhex(rec["hex"]), rec["t"]):
                    lines.append((t0, rec["dir"], text))
    base = start or datetime.fromtimestamp(0)
    lines.sort(key=lambda x: x[0])
    for t, d, text in lines:
        events.append(TapEvent(t=t, wall=base + timedelta(seconds=t), direction=d,
                               text=text))
    return events
