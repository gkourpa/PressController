"""The monitor on real recordings: phases, the ramp, the peak, and what it says."""

from __future__ import annotations

from datetime import datetime

import pytest

from presscontroller.monitor import Monitor, Phase
from presscontroller.protocol import CTRL_TO_PC, PC_TO_CTRL, Ramp
from presscontroller.tap import TapEvent, read_capture
from tests.conftest import DRY_RUN, RAMP_6, REAL_TEST, replay_all


def test_the_real_test_is_one_test_with_its_peak(press):
    m, _ = replay_all(press, REAL_TEST)
    assert len(m.tests) == 1
    test = m.tests[0]
    force, t, path = m.peak(test)
    # The peak this cube failed at, as the stream carried it.
    assert force == pytest.approx(1515.88, abs=0.01)
    assert path == pytest.approx(81.4935, abs=0.001)
    assert t == pytest.approx(268.1, abs=0.1)
    assert test.closed and test.close_reason == "load released"
    assert test.events[0][1].startswith("PC #B47")


def test_the_phases_follow_the_test(press):
    m, _ = replay_all(press, REAL_TEST)
    seen = list(dict.fromkeys(m.tests[0].phase))
    assert seen[:5] == [Phase.ARMED.value, Phase.APPROACH.value, Phase.AT_START_LOAD.value,
                        Phase.RAMP.value, Phase.HELD.value]
    assert Phase.CANCELLED.value in seen
    # Proteus closed at the end of the recording.
    assert m.proteus is False and m.phase is Phase.NONE


def test_a_ramp_sent_with_start_zero_is_said_out_loud(press):
    m, notices = replay_all(press, REAL_TEST)
    test = m.tests[0]
    assert test.ramp == Ramp(167, 0, 100000, 0, 1)
    assert test.ramp_from_mm == pytest.approx(79.45, abs=0.01)
    assert len(test.warnings) == 1
    assert "2.06 mm/min" in test.warnings[0] and "10 mm/min" in test.warnings[0]
    assert any(n.warn and "2.06" in n.text for n in notices)


def test_the_measured_ramp_matches_the_predicted_effective_rate(press):
    # The prediction the warning makes is the rate the press really ran at.
    m, _ = replay_all(press, REAL_TEST)
    test = m.tests[0]
    path = m.series(test, m.path_index)
    ramp = [(t, p) for t, p, ph in zip(test.t, path, test.phase)
            if ph == Phase.RAMP.value and 210 < t < 260]
    (t0, p0), (t1, p1) = ramp[0], ramp[-1]
    measured = (p1 - p0) / (t1 - t0) * 60
    assert measured == pytest.approx(test.ramp.effective_mm_min(test.ramp_from_mm), abs=0.1)


def test_a_ramp_from_where_the_piston_is_gives_no_warning(press):
    m, notices = replay_all(press, RAMP_6)
    assert [t.ramp for t in m.tests] == [None, Ramp(100, 79446, 100000, 0, 1)]
    assert not any(t.warnings for t in m.tests)
    assert not any(n.warn for n in notices)


def test_a_cancelled_start_then_a_new_start_are_two_tests(press):
    m, _ = replay_all(press, RAMP_6)
    first, second = m.tests
    assert first.closed and second.closed
    assert m.peak(second)[0] == pytest.approx(613.51, abs=0.01)


def test_the_dry_run_is_a_test_without_a_ramp(press):
    m, _ = replay_all(press, DRY_RUN)
    assert len(m.tests) == 1 and m.tests[0].ramp is None and m.tests[0].closed


def test_keypad_stop_in_pc_mode_is_said(press):
    _, notices = replay_all(press, REAL_TEST)
    assert sum("Keypad STOP" in n.text for n in notices) == 2


def test_the_approach_rate(press):
    m = Monitor(press)
    for ev in read_capture(REAL_TEST):
        if ev.t > 200:
            break
        m.feed(ev)
    assert m.rate(m.path_index) * 60 == pytest.approx(23.9, abs=0.5)
    assert m.phase is Phase.APPROACH


def test_closed_tests_are_handed_out_once(press):
    m, _ = replay_all(press, RAMP_6)
    assert len(m.pop_closed()) == 2
    assert m.pop_closed() == []


def test_loading_starts_at_the_start_load(press):
    m, _ = replay_all(press, REAL_TEST)
    test = m.tests[0]
    i = m.loading_start(test)
    assert test.phase[i] == Phase.AT_START_LOAD.value
    assert test.phase[i - 1] == Phase.APPROACH.value


def test_a_test_already_running_when_the_monitor_starts_is_picked_up(press):
    m = Monitor(press)
    for ev in read_capture(REAL_TEST):
        if ev.t > 150:                     # after START, during the approach
            m.feed(ev)
    test = m.tests[0]
    assert "already under way" in test.events[0][1]
    assert test.ramp is not None and m.peak(test)[0] == pytest.approx(1515.88, abs=0.01)


def test_an_unknown_line_is_logged_and_said(press):
    m = Monitor(press)
    notices = m.feed(TapEvent(1.0, datetime(2026, 1, 1), PC_TO_CTRL, "#Q99"))
    assert notices[0].warn and "#Q99" in notices[0].text
    assert m.log[-1].known is False and m.unknown_lines == 1


def test_a_channel_missing_from_a_line_is_a_gap_not_a_number(press):
    m = Monitor(press)
    w = datetime(2026, 1, 1)
    m.feed(TapEvent(0.0, w, PC_TO_CTRL, "#B47"))
    m.feed(TapEvent(0.1, w, CTRL_TO_PC, "#D082;0;100;1;200"))
    m.feed(TapEvent(0.2, w, CTRL_TO_PC, "#D0812;0;100;1;200;2;300"))
    test = m.current
    assert test.raw[2] == [None, 300]
    assert m.series(test, 2) == [None, pytest.approx(300 * 5 / 600000)]


def test_force_displacement_counts_from_the_start_load(press):
    m, _ = replay_all(press, REAL_TEST)
    test = m.tests[0]
    fd = m.force_displacement(test)
    assert fd.displacement[0] == 0.0
    assert fd.origin == pytest.approx(79.2, abs=0.05)          # where 4.39 kN was reached
    # The cube failed after about 2.3 mm of travel from the start load.
    assert fd.peak == (pytest.approx(81.4935 - fd.origin), pytest.approx(1515.88, abs=0.01))
    assert len(fd.displacement) == len(fd.force)


def test_during_the_approach_displacement_is_position(press):
    m = Monitor(press)
    for ev in read_capture(REAL_TEST):
        if ev.t > 200:
            break
        m.feed(ev)
    fd = m.force_displacement(m.current)
    assert fd.origin is None and fd.peak is None
    assert fd.displacement == m.series(m.current, m.path_index)


def test_no_test_no_curve(press):
    fd = Monitor(press).force_displacement(None)
    assert fd.displacement == [] and fd.force == [] and fd.peak is None
