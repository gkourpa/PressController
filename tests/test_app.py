"""The window, offscreen, driven by a replayed capture."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QPushButton  # noqa: E402

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
    win._display.flush()
    qapp.processEvents()
    return win


def test_mid_test_the_window_shows_the_ramp_and_its_warning(qapp, press):
    win = _window(qapp, press, until=362.0)
    try:
        assert win.phase_lbl.text() == "ramp"
        assert win.link_lbl.text().startswith("connected (PC mode), data every 200 ms")
        assert win.peak_gauge.reading.text() == "1515.88 kN"
        assert "Path control: set 10 mm/min · measured 2.0" in win.ramp_lbl.text()
        assert "piston was at 79.451 mm" in win.ramp_lbl.text()
        assert "not the 10 mm/min set" in win.message.text()
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
        assert names == ["Save newest test as CSV…", "Open the tests folder", "Settings…",
                         "Quit"]
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


def test_the_screen_is_redrawn_at_no_more_than_its_ceiling(qapp, press, monkeypatch):
    """Data is taken in every tick; the screen only at ``refresh_hz``."""
    from presscontroller.app.main_window import MainWindow
    src = ReplayTap(REAL_TEST, speed=1e9)
    from presscontroller.config.settings import Settings
    win = MainWindow(Monitor(press), src, settings=Settings(refresh_hz=2.0))
    shown = []
    monkeypatch.setattr(win, "_show", lambda: shown.append(win.monitor.latest_t))
    win._display._fn = win._show
    win.start()
    win._timer.stop()
    try:
        src._events, rest = src._events[:300], src._events[300:]
        win.tick()                         # the first redraw is immediate
        src._events += rest
        win.tick()                         # within the interval: held back
        assert len(shown) == 1
        assert win.monitor.latest_t > shown[0]      # but the data was taken in
        win._display.flush()               # the trailing redraw shows the newest
        assert shown[-1] == win.monitor.latest_t
    finally:
        win.close()


def test_the_start_sent_is_a_plain_note_on_the_ramp_line(qapp, press):
    """Step 17's start of twice the piston position: shown, in the normal colour."""
    from presscontroller.app.main_window import MainWindow
    from tests.conftest import RAMP_3
    src = ReplayTap(RAMP_3, speed=1e9)
    win = MainWindow(Monitor(press), src)
    win.start()
    win._timer.stop()
    try:
        win.tick()
        win._display.flush()
        text = win.ramp_lbl.text()
        assert "start sent 159.202 mm, piston was at 79.600 mm" in text
        assert "Warning" not in text and win.ramp_lbl.styleSheet() == ""
    finally:
        win.close()


def test_a_force_ramp_on_the_ramp_line(qapp, press):
    """Step 20: set and measured in kN/s, the end force, the path's rate beside."""
    from presscontroller.app.main_window import MainWindow
    from tests.conftest import FORCE_5
    src = ReplayTap(FORCE_5, speed=1e9)
    src._events = [e for e in src._events if e.t < 150.0]    # ramp running, before Stop
    win = MainWindow(Monitor(press), src)
    win.start()
    win._timer.stop()
    try:
        win.tick()
        win._display.flush()
        text = win.ramp_lbl.text()
        assert text.startswith("Force control: set 5 kN/s · measured 4.99 kN/s")
        assert "to 300.00 kN; start sent 0.00 kN; path 4." in text
        assert "Warning" not in text
    finally:
        win.close()


def _control_window(qapp, press, monkeypatch, settings=None, fake=None):
    from presscontroller.app.control_window import ControlWindow
    from presscontroller.config.settings import Settings
    from presscontroller.control import ControllerLink, ControllerSession, Limits
    from presscontroller.control import session as session_mod
    from tests.controller_fake import FakeController

    monkeypatch.setattr(session_mod, "LISTEN_FIRST_S", 0.05)
    fake = fake or FakeController()
    saved = []
    session = ControllerSession(ControllerLink("COM9", limits=Limits.from_press(press),
                                               open_port=lambda name: fake))
    win = ControlWindow(Monitor(press), session, settings=settings or Settings(),
                        save=saved.append)
    win.start()
    win._timer.stop()
    return win, fake, saved


def _tick_until(win, cond, timeout=3.0):
    import time
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        win.tick()
        time.sleep(0.01)
    win.tick()
    assert cond()


def test_the_control_window_connects_switches_and_disconnects_on_close(qapp, press, monkeypatch):
    from presscontroller.control import SessionState
    win, fake, saved = _control_window(qapp, press, monkeypatch)
    session = win.session
    try:
        assert win.windowTitle() == f"PressController — {press.name}"
        assert win.connect_btn.isEnabled() and not win.disconnect_btn.isEnabled()
        assert not win.start_btn.isEnabled() and not win.stop_btn.isEnabled()
        assert win.break_switch.isChecked() and not win.peak_switch.isChecked()
        assert win.break_switch.state_text() == "Break detection: ON"
        win.connect_btn.click()
        _tick_until(win, lambda: session.state is SessionState.CONNECTED)
        assert win.state_lbl.text() == "Controller: connected, in PC mode"
        assert win.disconnect_btn.isEnabled() and not win.connect_btn.isEnabled()
        assert win.start_btn.isEnabled() and win.stop_btn.isEnabled()
        assert "Connected" in win.message.text()
        win.peak_switch.click()
        win.break_switch.click()
        assert fake.peak and not fake.break_detection
        assert win.break_switch.state_text() == "Break detection: OFF"
        # A flip is remembered, never reset.
        assert saved[-1].test.peak and not saved[-1].test.break_detection
    finally:
        win.close()
    assert fake.written[-2:] == ["#B36", "#B21"] and not fake.pc_mode


def test_the_switches_open_at_the_saved_settings(qapp, press, monkeypatch):
    from presscontroller.config.settings import Settings, TemplateSettings
    from presscontroller.control import SessionState
    settings = Settings(test=TemplateSettings(peak=True, break_detection=False))
    win, fake, _ = _control_window(qapp, press, monkeypatch, settings)
    try:
        assert win.peak_switch.isChecked() and not win.break_switch.isChecked()
        win.connect_btn.click()
        _tick_until(win, lambda: win.session.state is SessionState.CONNECTED)
        assert fake.peak and not fake.break_detection
    finally:
        win.close()


def test_a_test_run_from_the_buttons(qapp, press, monkeypatch):
    from presscontroller.control import RunPhase, SessionState
    win, fake, saved = _control_window(qapp, press, monkeypatch)
    s = win.session
    try:
        win.connect_btn.click()
        _tick_until(win, lambda: s.state is SessionState.CONNECTED)
        assert win.limit_lbl.text() == "limit 10 mm/min"
        win.start_btn.click()
        _tick_until(win, lambda: s.test is RunPhase.AT_START_LOAD)
        assert not win.start_btn.isEnabled() and win.continue_btn.isEnabled()
        assert not win.peak_switch.isEnabled() and not win.speed_box.isEnabled()
        win.continue_btn.click()
        _tick_until(win, lambda: s.test is RunPhase.RAMP)
        assert fake.ramp == "#D1233;0;100000;0;1"
        assert win.run_lbl.text() == "Test: ramp running"
        win._display.flush()
        assert win.test_lbl.text().startswith("#1, START at")      # the monitor's own line
        assert win.pause_btn.isEnabled() and not win.continue_btn.isEnabled()
        win.pause_btn.click()
        win.tick()
        assert s.test is RunPhase.PAUSED and win.continue_btn.isEnabled()
        assert "not a stop" in win.message.text()
        win.continue_btn.click()
        win.tick()
        assert s.test is RunPhase.RAMP
        win._esc.activated.emit()               # Esc is STOP
        win.tick()
        assert s.test is RunPhase.NONE and fake.written[-1] == "#B17"
        assert win.start_btn.isEnabled()
    finally:
        win.close()


def test_a_ramp_over_the_limit_turns_start_off_and_says_why(qapp, press, monkeypatch):
    from presscontroller.control import SessionState
    win, fake, saved = _control_window(qapp, press, monkeypatch)
    try:
        win.connect_btn.click()
        _tick_until(win, lambda: win.session.state is SessionState.CONNECTED)
        win.speed_box.setValue(120.0)           # step 22's mistake
        assert not win.start_btn.isEnabled()
        assert "START is off" in win.run_lbl.text() and "limits" in win.run_lbl.text()
        assert saved[-1].test.path_speed_mm_min == 120.0      # remembered as entered
        win.control_box.setCurrentIndex(win.control_box.findData("force"))
        assert win.speed_box.suffix() == " kN/s" and win.limit_lbl.text() == "limit 15 kN/s"
        assert win.start_btn.isEnabled()
    finally:
        win.close()


def test_the_settings_dialog_saves_only_on_ok(qapp):
    from presscontroller.app.settings_dialog import SettingsDialog
    from presscontroller.config.settings import Settings
    saved = []
    dlg = SettingsDialog(Settings(control_port="COM7"), save=saved.append)
    assert dlg.port.currentText() == "COM7"
    dlg.threshold.setValue(25.0)
    dlg.interval.setValue(205)
    dlg.refresh.setValue(1.0)
    dlg.reject()
    assert saved == [] and dlg.settings.test.break_threshold_per_mil == 10.0
    dlg = SettingsDialog(Settings(control_port="COM7"), save=saved.append)
    dlg.threshold.setValue(25.0)
    dlg.interval.setValue(205)
    dlg.port.setCurrentText("COM6")
    dlg._accept()
    got = saved[-1]
    assert got.test.break_threshold_per_mil == 25.0 and got.control_port == "COM6"
    assert got.test.measuring_interval_ms in (200, 210)   # whole 10 ms steps
    assert got.test.problems() == []


def test_the_settings_dialog_has_its_four_tabs_and_saves_them(qapp, monkeypatch):
    from presscontroller.app.settings_dialog import TABS, SettingsDialog
    from presscontroller.config.settings import Settings
    saved = []
    dlg = SettingsDialog(Settings(), save=saved.append).show_tab("Plot")
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == list(TABS)
    assert dlg.tabs.currentIndex() == TABS.index("Plot")
    monkeypatch.setattr(dlg, "_ask_colour", lambda initial: "#d62728")
    dlg.colour_btn.click()
    dlg.y_range.auto.setChecked(False)
    dlg.y_range.lo.setValue(0.0)
    dlg.y_range.hi.setValue(2000.0)
    dlg.theme.setCurrentIndex(dlg.theme.findData("dark"))
    dlg.auto_connect.setChecked(True)
    dlg._accept()
    got = saved[-1]
    assert got.plot.colour == "#d62728" and got.plot.ylim == (0.0, 2000.0)
    assert got.plot.xlim is None and got.theme == "dark" and got.auto_connect


def test_the_window_opens_where_it_was_closed(qapp, press):
    from presscontroller.app.main_window import MainWindow
    from presscontroller.config.settings import Settings
    saved = []
    src = ReplayTap(REAL_TEST, speed=1e9)
    win = MainWindow(Monitor(press), src, settings=Settings(), save=saved.append)
    win.restore_place()
    win.setGeometry(20, 30, 760, 740)       # within the offscreen screen (800 x 800)
    win.show()
    qapp.processEvents()
    left_as = (win.x(), win.y(), win.width(), win.height())
    win.close()
    geometry = saved[-1].window_geometry
    assert geometry
    again = MainWindow(Monitor(press), ReplayTap(REAL_TEST, speed=1e9),
                       settings=saved[-1], save=saved.append)
    again.restore_place()
    assert (again.width(), again.height()) == left_as[2:]
    # The offscreen platform's frame shifts the origin by a pixel or two.
    assert abs(again.x() - left_as[0]) <= 4 and abs(again.y() - left_as[1]) <= 4
    again.close()


def test_the_plot_takes_its_settings(qapp, press):
    from presscontroller.app.main_window import LOG_LINES, MainWindow
    from presscontroller.config.settings import PlotSettings, Settings
    win = _window(qapp, press, until=362.0)
    try:
        win.apply_settings(Settings(plot=PlotSettings(ylim=(0.0, 2000.0), colour="#d62728")))
        win._display.flush()
        assert win.settings.plot.colour == "#d62728"
        assert win.log_view.height() < 5 * LOG_LINES * win.log_view.fontMetrics().lineSpacing()
        assert win.message.lines == 1
    finally:
        win.close()
