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
    assert any(c.startswith("# ramp sent: 167 um/s") for c in comments)
    assert any(c.startswith("# warning: Proteus sent the ramp's start as 0.000 mm") for c in comments)
    assert any(c.startswith("# warning: The ramp is running at") for c in comments)
    assert any(c.startswith("# ramp measured: 2.06") for c in comments)
    assert any(c.startswith("# peak force: 1515.88") for c in comments)
    assert comments[-1] == "# closed: load released"


def test_never_overwrites(press, tmp_path):
    m, _ = replay_all(press, REAL_TEST)
    a = write_test_csv(m, m.tests[0], tmp_path)
    b = write_test_csv(m, m.tests[0], tmp_path)
    assert a != b and b.name == "test_20261019_143651_2.csv"
