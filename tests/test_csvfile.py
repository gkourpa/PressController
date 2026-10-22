"""A test's CSV: strict, recoverable, never overwritten."""

from __future__ import annotations

import csv

import pytest

from presscontroller.monitor import write_test_csv
from tests.conftest import REAL_TEST, replay_all


def _read(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    comments = [ln for ln in lines if ln.startswith("#")]
    rows = list(csv.DictReader(ln for ln in lines if not ln.startswith("#")))
    return comments, rows


def test_the_real_test_as_csv(press, tmp_path):
    m, _ = replay_all(press, REAL_TEST)
    test = m.tests[0]
    path = write_test_csv(m, test, tmp_path, source="replay")
    assert path.name == "test_20261019_143651.csv"
    comments, rows = _read(path)
    text = path.read_text(encoding="utf-8")
    assert "nan" not in text.lower()
    assert len(rows) == len(test.t)
    assert list(rows[0])[:6] == ["t_s", "time", "counter", "phase", "Force_kN", "Force_raw"]
    assert max(float(r["Force_kN"]) for r in rows) == pytest.approx(1515.88, abs=0.01)
    # Every value can be taken back to the count the controller sent.
    for r in rows[::200]:
        assert float(r["Path_mm"]) == pytest.approx(int(r["Path_raw"]) * 100 / 600000)
    assert any("#B22" in r["event"] for r in rows)
    assert any(c.startswith("# ramp sent: channel 1 (Path), speed 167, start 0, end 100000, "
                            "field4 0 = 10 mm/min from 0 to 100 mm (thousandths of mm)")
               and c.endswith("piston at 79.451 mm when sent") for c in comments)
    assert any(c.startswith("# warning: The ramp is running at") for c in comments)
    assert any(c.startswith("# ramp measured: 2.05") for c in comments)
    assert any(c.startswith("# peak force: 1515.88") for c in comments)
    assert comments[-1] == "# closed: load released"


def test_never_overwrites(press, tmp_path):
    m, _ = replay_all(press, REAL_TEST)
    a = write_test_csv(m, m.tests[0], tmp_path)
    b = write_test_csv(m, m.tests[0], tmp_path)
    assert a != b and b.name == "test_20261019_143651_2.csv"


def test_a_streamed_test_matches_the_whole_one_and_grows_row_by_row(press, tmp_path):
    """The same writer streams a running test and writes a finished one."""
    import io

    from presscontroller.monitor import TestCsv
    from presscontroller.monitor.tracker import Monitor
    from presscontroller.tap.capture import read_capture
    m = Monitor(press)
    fh = io.StringIO(newline="")
    writer = None
    sizes = []
    for ev in read_capture(REAL_TEST):
        m.feed(ev)
        test = m.current
        if test is not None and test.t and writer is None:
            writer = TestCsv(m, test, fh, source="replay")
        if writer is not None and m.current is writer.test:
            writer.update()
            sizes.append(writer.rows)
    writer.finish()
    whole = write_test_csv(m, writer.test, tmp_path, source="replay")
    assert fh.getvalue() == whole.read_text(encoding="utf-8")
    assert sizes == sorted(sizes) and sizes[0] < sizes[-1]       # grew as it ran
    lines = fh.getvalue().splitlines()
    head = lines[:lines.index(next(ln for ln in lines if ln.startswith("t_s,")))]
    assert head[0] == "# PressController test 1"
    assert not any("peak force" in ln or "ramp sent" in ln for ln in head)
