"""The monitor on real recordings: phases, the ramp, the peak, and what it says."""

from __future__ import annotations

from datetime import datetime

import pytest

from presscontroller.monitor import Monitor, Phase
from presscontroller.monitor.tracker import (
    RAMP_JUDGE_AFTER_S,
    RAMP_SETTLE_S,
    RAMP_SPEED_TOLERANCE,
)
from presscontroller.protocol import CTRL_TO_PC, PC_TO_CTRL, Ramp
from presscontroller.tap import TapEvent, read_capture
from tests.conftest import (
    DRY_RUN,
    FORCE_2_TO_END,
    FORCE_5,
    RAMP_3,
    RAMP_6,
    REAL_TEST,
    replay_all,
)


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


def test_a_slow_ramp_is_measured_and_said_out_loud(press):
    # Step 15: set 10 mm/min, sent with start 0, ran at 2.06 mm/min.
    m, notices = replay_all(press, REAL_TEST)
    test = m.tests[0]
    assert test.ramp == Ramp(167, 0, 100000, 0, 1)
    assert test.ramp_from_mm == pytest.approx(79.45, abs=0.01)
    assert test.ramp_mm_min == pytest.approx(2.06, abs=0.01)
    [speed] = test.warnings
    assert speed.startswith("The ramp is running at 2.") and "not the 10 mm/min set" in speed
    assert [n.text for n in notices if n.warn] == [speed]


def test_the_measured_speed_is_the_slope_of_path_against_time(press):
    m, _ = replay_all(press, REAL_TEST)
    test = m.tests[0]
    path = m.series(test, m.path_index)
    ramp = [(t, p) for t, p, ph in zip(test.t, path, test.phase) if ph == Phase.RAMP.value]
    (t0, p0), (t1, p1) = ramp[0], ramp[-1]
    assert test.ramp_mm_min == pytest.approx((p1 - p0) / (t1 - t0) * 60, rel=0.03)
    assert test.ramp_seconds == pytest.approx(t1 - t0)


def test_a_start_off_the_piston_is_kept_but_not_warned_about(press):
    # Step 17: start sent as exactly twice the position; the press still ran at 3.
    m, notices = replay_all(press, RAMP_3)
    test = m.tests[0]
    assert test.ramp == Ramp(50, 159202, 100000, 0, 1)
    assert test.ramp.start_value / test.ramp_from_mm == pytest.approx(2.0, abs=1e-4)
    assert test.ramp_mm_min == pytest.approx(3.0, abs=0.1)
    assert test.warnings == []
    assert not any(n.warn for n in notices)
    assert m.peak(test)[0] == pytest.approx(409.46, abs=0.01)


def test_a_ramp_from_where_the_piston_is_at_its_speed_gives_no_warning(press):
    m, notices = replay_all(press, RAMP_6)
    assert [t.ramp for t in m.tests] == [None, Ramp(100, 79446, 100000, 0, 1)]
    assert m.tests[1].ramp_mm_min == pytest.approx(6.0, rel=RAMP_SPEED_TOLERANCE)
    assert not any(t.warnings for t in m.tests)
    assert not any(n.warn for n in notices)


def test_the_speed_is_judged_once_after_ten_seconds(press):
    m = Monitor(press)
    first_judged = None
    for ev in read_capture(REAL_TEST):
        m.feed(ev)
        test = m.current
        if test is not None and test.ramp_judged and first_judged is None:
            first_judged = test.ramp_seconds
    assert first_judged == pytest.approx(RAMP_JUDGE_AFTER_S, abs=0.3)
    assert sum("running at" in w for w in m.tests[0].warnings) == 1


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


def _force_ramp(press, rate_kn_s=5.0, seconds=15.0, speed_field=5000):
    """A force ramp as it might be heard: channel 0, force rising, path creeping."""
    m = Monitor(press)
    w = datetime(2026, 1, 1)
    feed = lambda t, d, text: m.feed(TapEvent(t, w, d, text))
    notices = []
    for t, d, text in [(0.0, PC_TO_CTRL, "#B47"), (0.1, PC_TO_CTRL, "#B23"),
                       (1.0, CTRL_TO_PC, "#B01"), (2.0, PC_TO_CTRL, f"#D12{speed_field};0;300000;0;0"),
                       (2.1, PC_TO_CTRL, "#B22")]:
        notices += feed(t, d, text)
    k = 0
    while k * 0.2 < seconds:
        t = 2.2 + k * 0.2
        force_raw = round((10 + rate_kn_s * k * 0.2) * 600000 / 4000)
        path_raw = round((80 + 0.01 * k * 0.2) * 600000 / 100)
        notices += feed(t, CTRL_TO_PC, f"#D08{k * 20};0;{force_raw};1;{path_raw};2;-25600")
        k += 1
    return m, notices


def test_a_force_ramp_at_its_rate_is_measured_in_kn_per_s_and_passes(press):
    m, notices = _force_ramp(press, rate_kn_s=5.0)
    test = m.tests[0]
    assert m.ramp_decoded(test) and test.ramp.channel == m.force_index
    assert m.ramp_measured(test) == pytest.approx(5.0, abs=0.01)
    assert test.ramp_mm_min == pytest.approx(0.6, abs=0.01)
    assert test.warnings == [] and not any(n.warn for n in notices)
    assert any(e.meaning == "ramp on channel 0: 5 kN/s from 0 to 300 kN" for e in m.log)


def test_a_force_ramp_off_its_rate_is_said_in_kn_per_s(press):
    m, notices = _force_ramp(press, rate_kn_s=3.0, speed_field=5000)
    [warning] = m.tests[0].warnings
    assert warning.startswith("The ramp is running at 3 kN/s, not the 5 kN/s set")


def test_the_real_force_ramp(press):
    # Step 20: 5 kN/s to 300 kN set in Proteus, stopped at 247 kN.
    m, notices = replay_all(press, FORCE_5)
    test = m.tests[0]
    assert test.ramp == Ramp(5000, 0, 300000, 0, 0)
    assert m.ramp_measured(test) == pytest.approx(4.99, abs=0.01)
    assert test.warnings == [] and not any(n.warn for n in notices)
    assert m.peak(test)[0] == pytest.approx(247.27, abs=0.01)


def test_a_ramp_left_to_reach_its_end(press):
    # Step 21: 2 kN/s to 100 kN; the controller says #B02 at the end, Proteus
    # answers #B26 and cancels by itself.
    m, notices = replay_all(press, FORCE_2_TO_END)
    test = m.tests[0]
    assert test.ramp == Ramp(2000, 0, 100000, 0, 0)
    assert m.unknown_lines == 0
    assert [e.meaning for e in m.log if e.text in ("#B02", "#B26")] == [
        "ramp end reached", "test finished (answer to ramp end)?"]
    assert m.peak(test)[0] == pytest.approx(99.67, abs=0.01)
    # Proteus cancels 20 ms after #B02, before the next sample, so the phase is
    # seen at the moment #B02 is heard rather than on any sample.
    m2 = Monitor(press)
    for ev in read_capture(FORCE_2_TO_END):
        m2.feed(ev)
        if ev.text == "#B02":
            break
    assert m2.phase is Phase.RAMP_END


def test_the_take_up_at_a_ramp_start_is_no_false_alarm(press):
    # Step 21's first seconds: force dips, then jumps 8 kN, before rising at 2 kN/s.
    m, notices = replay_all(press, FORCE_2_TO_END)
    test = m.tests[0]
    assert m.ramp_measured(test) == pytest.approx(2.0, abs=0.05)
    assert test.warnings == [] and not any(n.warn for n in notices)


def test_the_first_seconds_of_a_ramp_are_not_in_its_rate(press):
    m, _ = _force_ramp(press, rate_kn_s=5.0, seconds=RAMP_SETTLE_S - 0.5)
    assert m.tests[0].ramp_kn_s is None and m.tests[0].ramp_seconds > 0
