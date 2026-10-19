"""One test as one CSV: ``#`` header lines, then a plain table.

DAqReader's layout and rules (``daqreader/session/csvfile.py``): standard
dialect; ``#`` lines first saying what the test was; a gap is an empty cell,
never ``NaN``; an existing file is never overwritten. pandas reads it with
``comment="#"``.

**The raw counts go in beside the values**, with the range and resolution they
were scaled by in the header, so a value can always be taken back to what the
controller sent: ``value = raw × range / resolution``. A press file edited later
must not leave old tests unreadable.

Columns: ``t_s`` (seconds since START), ``time`` (wall clock), ``counter`` (the
controller's own 10 ms clock), ``phase``, then ``<channel>_<unit>`` and
``<channel>_raw`` per channel, then ``event`` — every command and event heard,
on the first row at or after it.
"""

from __future__ import annotations

import csv
import math
from datetime import timedelta
from pathlib import Path

from presscontroller.monitor.tracker import Monitor, TestRecord


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


def write_test_csv(monitor: Monitor, test: TestRecord, folder: str | Path, *,
                   source: str = "") -> Path:
    """Write ``test`` into ``folder`` under a name no other file has; return it."""
    press = monitor.press
    path = _unique(Path(folder) / csv_filename(test))
    path.parent.mkdir(parents=True, exist_ok=True)
    indices = sorted(test.raw)
    names = []
    for idx in indices:
        ch = press.channel(idx)
        names.append(f"{ch.name}_{ch.unit}" if ch else f"ch{idx}")

    header = [f"PressController test {test.number}",
              f"press: {press.name}",
              f"started: {test.started:%Y-%m-%d %H:%M:%S}",
              f"resolution: {press.resolution} (value = raw * range / resolution)"]
    for idx in indices:
        ch = press.channel(idx)
        header.append(f"channel {idx}: {ch.name}, {ch.unit}, range {ch.range:g}" if ch
                      else f"channel {idx}: not in the press file, raw counts only")
    if source:
        header.append(f"heard from: {source}")
    if test.ramp is not None:
        r = test.ramp
        header.append(f"ramp sent: {r.speed_um_s} um/s ({r.speed_mm_min:.3g} mm/min) from "
                      f"{r.start_um} um to {r.end_um} um, field4 {r.field4}, channel {r.channel}"
                      + (f"; piston at {test.ramp_from_mm:.3f} mm when sent"
                         if test.ramp_from_mm is not None else ""))
    peak = monitor.peak(test)
    if peak is not None:
        f, t, p = peak
        header.append(f"peak force: {format_value(f)} at t = {t:.2f} s"
                      + (f", path {format_value(p)}" if p is not None else ""))
    header += [f"warning: {w}" for w in test.warnings]

    # Each event goes on the first row at or after it; any later than the last
    # row are kept in the closing lines rather than dropped.
    events = sorted(test.events)
    row_events: dict[int, list[str]] = {}
    tail: list[str] = []
    j = 0
    for t, text in events:
        while j < len(test.t) and test.t[j] < t:
            j += 1
        if j < len(test.t):
            row_events.setdefault(j, []).append(text)
        else:
            tail.append(f"{t:.3f} s {text}")

    values = {idx: monitor.series(test, idx) for idx in indices}
    with open(path, "x", encoding="utf-8", newline="") as fh:
        for line in header:
            fh.write("# " + " ".join(str(line).splitlines()) + "\n")
        w = csv.writer(fh, lineterminator="\n")
        cols = ["t_s", "time", "counter", "phase"]
        for name, idx in zip(names, indices):
            cols += [name, f"{name.rsplit('_', 1)[0]}_raw"]
        w.writerow(cols + ["event"])
        for i, t in enumerate(test.t):
            wall = test.started + timedelta(seconds=t)
            row = [f"{t:.3f}", wall.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                   str(test.counter[i]), test.phase[i]]
            for idx in indices:
                raw = test.raw[idx][i]
                row += [format_value(values[idx][i]), "" if raw is None else str(raw)]
            w.writerow(row + [" | ".join(row_events.get(i, []))])
        for line in tail + [f"closed: {test.close_reason or 'still open when saved'}"]:
            fh.write("# " + line + "\n")
    return path
