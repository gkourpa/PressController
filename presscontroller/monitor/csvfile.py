"""One test as one CSV, written as the test runs: ``#`` head lines, a plain
table growing a row per measurement, and ``#`` summary lines at the end.

DAqReader's rules (``daqreader/session/csvfile.py``): standard dialect; ``#``
lines say what the test was; a gap is an empty cell, never ``NaN``; an existing
file is never overwritten. pandas reads it with ``comment="#"``, which skips a
``#`` line wherever it stands.

**Streamed** (operator, 2026-10-22): the head — the press, START, the
resolution and each channel's range — is written with the first measurement;
each measurement then adds one row, flushed at once, so a crash or a power cut
loses nothing already heard. What is only known later — the ramp sent and
where the piston was, its measured rate, the peak, the warnings — closes the
file with the reason it closed. A file without its ``closed:`` line is a test
that never finished being written.

**The raw counts go in beside the values**, with the range and resolution they
were scaled by in the head, so a value can always be taken back to what the
controller sent: ``value = raw × range / resolution``. A press file edited later
must not leave old tests unreadable.

Columns: ``t_s`` (seconds since START), ``time`` (wall clock), ``counter`` (the
controller's own 10 ms clock), ``phase``, then ``<channel>_<unit>`` and
``<channel>_raw`` per channel, then ``event`` — every command and event heard,
on the first row written at or after it. The columns are fixed by the first
row: the press file's channels and any other the stream carried then.
"""

from __future__ import annotations

import csv
import math
from datetime import timedelta
from pathlib import Path
from typing import TextIO

from presscontroller.monitor.tracker import Monitor, TestRecord
from presscontroller.protocol import rate_text


def format_value(v: float | None) -> str:
    if v is None or not math.isfinite(v):
        return ""
    return f"{v:.10g}"


def _unique(path: Path) -> Path:
    """``path``, or ``path`` with ``_2``, ``_3``… — never one that exists."""
    if not path.exists():
        return path
    n = 2
    while (candidate := path.with_name(f"{path.stem}_{n}{path.suffix}")).exists():
        n += 1
    return candidate


def csv_filename(test: TestRecord) -> str:
    return f"test_{test.started:%Y%m%d_%H%M%S}.csv"


def new_csv_path(test: TestRecord, folder: str | Path) -> Path:
    """Where ``test`` goes in ``folder``: a name no file has yet."""
    return _unique(Path(folder) / csv_filename(test))


def open_test_csv(test: TestRecord, folder: str | Path) -> tuple[Path, TextIO]:
    """A new file for ``test`` in ``folder``, open for writing; never one that
    exists."""
    path = new_csv_path(test, folder)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path, open(path, "x", encoding="utf-8", newline="")


def write_test_csv(monitor: Monitor, test: TestRecord, folder: str | Path, *,
                   source: str = "") -> Path:
    """Write ``test`` whole into ``folder`` under a name no other file has."""
    path, fh = open_test_csv(test, folder)
    with fh:
        TestCsv(monitor, test, fh, source=source).finish()
    return path


class TestCsv:
    """Writes ``test`` to ``fh`` as it grows: :meth:`update` adds the rows not
    yet written (the head first, with the first row); :meth:`finish` adds the
    rest and the summary. ``fh`` stays the caller's to close."""

    __test__ = False                    # not a pytest test class

    def __init__(self, monitor: Monitor, test: TestRecord, fh: TextIO, *, source: str = ""):
        self.monitor = monitor
        self.test = test
        self.fh = fh
        self.source = source
        self.indices: list[int] | None = None
        """The channels in the columns, fixed when the head is written."""
        self.rows = 0
        """Rows written so far."""
        self._events = 0
        self._writer = csv.writer(fh, lineterminator="\n")

    def update(self) -> None:
        """Write every row heard since the last call, and flush."""
        test = self.test
        if not test.t:
            return
        if self.indices is None:
            self._head()
        events = test.events
        while self.rows < len(test.t):
            i = self.rows
            t = test.t[i]
            here = []
            while self._events < len(events) and events[self._events][0] <= t:
                here.append(events[self._events][1])
                self._events += 1
            wall = test.started + timedelta(seconds=t)
            row = [f"{t:.3f}", wall.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                   str(test.counter[i]), test.phase[i]]
            for idx in self.indices:
                col = test.raw.get(idx)
                raw = col[i] if col is not None else None
                row += [format_value(None if raw is None else self.monitor.value(idx, raw)),
                        "" if raw is None else str(raw)]
            self._writer.writerow(row + [" | ".join(here)])
            self.rows += 1
        self.fh.flush()

    def finish(self) -> None:
        """The rows left, every event after the last row, the summary and the
        reason the test closed; flushed."""
        self.update()
        test, monitor, press = self.test, self.monitor, self.monitor.press
        if self.indices is None:            # not one measurement: a head alone
            self._head()
        lines = [f"{t:.3f} s {text}" for t, text in test.events[self._events:]]
        self._events = len(test.events)
        if test.ramp is not None:
            r = test.ramp
            ch = press.channel(r.channel)
            decoded = monitor.ramp_decoded(test)
            lines.append(f"ramp sent: channel {r.channel}"
                         + (f" ({ch.name})" if ch else "")
                         + f", speed {r.speed}, start {r.start}, end {r.end}, field4 {r.field4}"
                         + (f" = {rate_text(r.rate, ch.unit)} from {r.start_value:g} to "
                            f"{r.end_value:g} {ch.unit} (thousandths of {ch.unit})"
                            if decoded else " (units not decoded for this channel)")
                         + (f"; piston at {test.ramp_from_mm:.3f} mm when sent"
                            if test.ramp_from_mm is not None else ""))
        if test.ramp_mm_min is not None:
            lines.append(f"ramp measured: {test.ramp_mm_min:.3f} mm/min over "
                         f"{test.ramp_seconds:.1f} s (least squares, path against time)")
        if test.ramp_kn_s is not None:
            lines.append(f"ramp measured: {test.ramp_kn_s:.3f} kN/s over "
                         f"{test.ramp_seconds:.1f} s (least squares, force against time)")
        peak = monitor.peak(test)
        if peak is not None:
            f, t, p = peak
            lines.append(f"peak force: {format_value(f)} at t = {t:.2f} s"
                         + (f", path {format_value(p)}" if p is not None else ""))
        lines += [f"warning: {w}" for w in test.warnings]
        late = sorted(set(test.raw) - set(self.indices))
        lines += [f"channel {idx}: first heard after the columns were written; not in "
                  "this file" for idx in late]
        lines.append(f"closed: {test.close_reason or 'still open when saved'}")
        self._comments(lines)
        self.fh.flush()

    def _head(self) -> None:
        test, press = self.test, self.monitor.press
        self.indices = sorted({c.index for c in press.channels} | set(test.raw))
        lines = [f"PressController test {test.number}",
                 f"press: {press.name}",
                 f"started: {test.started:%Y-%m-%d %H:%M:%S}",
                 f"resolution: {press.resolution} (value = raw * range / resolution)"]
        for idx in self.indices:
            ch = press.channel(idx)
            lines.append(f"channel {idx}: {ch.name}, {ch.unit}, range {ch.range:g}" if ch
                         else f"channel {idx}: not in the press file, raw counts only")
        if self.source:
            lines.append(f"heard from: {self.source}")
        lines.append("the ramp, its measured rate and the peak follow the table")
        self._comments(lines)
        cols = ["t_s", "time", "counter", "phase"]
        for idx in self.indices:
            ch = press.channel(idx)
            name = f"{ch.name}_{ch.unit}" if ch else f"ch{idx}"
            cols += [name, f"{name.rsplit('_', 1)[0]}_raw"]
        self._writer.writerow(cols + ["event"])

    def _comments(self, lines: list[str]) -> None:
        for line in lines:
            self.fh.write("# " + " ".join(str(line).splitlines()) + "\n")
