"""The window, offscreen, driven by a replayed capture."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from presscontroller.monitor import Monitor  # noqa: E402
from presscontroller.tap import ReplayTap  # noqa: E402
from tests.conftest import REAL_TEST  # noqa: E402


def _window(qapp, press, until=None, tests_dir=None):
    from presscontroller.app.main_window import MainWindow
    src = ReplayTap(REAL_TEST, speed=1e9)
    if until is not None:
        src._events = [e for e in src._events if e.t < until]
    win = MainWindow(Monitor(press), src, tests_dir=tests_dir)
    win.resize(1200, 800)
    win.show()
    win.start()
    win._timer.stop()           # the test drives the ticks
    win.tick()
    win._plots.flush()
    qapp.processEvents()
    return win


def test_mid_test_the_window_shows_the_ramp_and_its_warning(qapp, press):
    win = _window(qapp, press, until=362.0)
    try:
        assert win.phase_lbl.text() == "ramp"
        assert win.link_lbl.text().startswith("connected (PC mode), data every 200 ms")
        assert win.peak_gauge.reading.text() == "1515.88 kN"
        assert "2.06 mm/min" in win.ramp_lbl.text()
        assert "2.06 mm/min" in win.message.text()
        assert win.gauges[0].reading.text().endswith(" kN")
        assert not win.plot_view.pixmap().isNull()
        assert "#B22" in win.log_view.toPlainText()
    finally:
        win.close()


def test_a_closed_test_is_saved_by_itself(qapp, press, tmp_path):
    win = _window(qapp, press, tests_dir=tmp_path)
    try:
        assert [p.name for p in win.saved] == ["test_20261019_143651.csv"]
        assert (tmp_path / "test_20261019_143651.csv").is_file()
    finally:
        win.close()


def test_a_replay_says_it_is_a_replay(qapp, press):
    win = _window(qapp, press, until=1.0)
    try:
        assert "replaying real_test_10mm_min.jsonl" in win.message.text()
        assert "Nothing is sent to the press" in win.message.text()
    finally:
        win.close()


def test_the_window_has_no_control_that_sends(qapp, press):
    """Listen-only by construction: no action or button speaks to the press."""
    from PySide6.QtWidgets import QAbstractButton
    win = _window(qapp, press, until=1.0)
    try:
        names = [a.text() for a in win.menuBar().actions()[0].menu().actions() if a.text()]
        assert names == ["Save newest test as CSV…", "Open the tests folder", "Quit"]
        assert [b for b in win.findChildren(QAbstractButton)
                if b.isVisible() and b.text()] == []
    finally:
        win.close()


@pytest.mark.parametrize("until", [0.5, 90.0])   # START is at 91.7 s
def test_before_any_test_the_plots_wait(qapp, press, until):
    win = _window(qapp, press, until=until)
    try:
        assert win.peak_gauge.reading.text() in ("–", "")
    finally:
        win.close()


def test_the_plot_is_force_against_displacement():
    """Rendered Qt-free; an empty test says what it is waiting for."""
    from presscontroller.app.plot import render_force_displacement
    img = render_force_displacement([0.0, 0.5, None, 1.0], [0.0, 400.0, 900.0, 1200.0],
                                    peak=(1.0, 1200.0), size_px=(400, 300), dpi=100)
    assert img.shape == (300, 400, 3)
    blank = render_force_displacement([], [], size_px=(400, 300), dpi=100)
    assert blank.shape == (300, 400, 3)
