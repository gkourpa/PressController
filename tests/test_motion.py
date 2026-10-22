"""Milestone 3b: a test run as Proteus runs it, and every way out ending in Cancel.

The simulated controller answers as steps 21, 23 and 26 show; what is sent is
compared line for line with what Proteus sent in those recordings.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest

from presscontroller.config.settings import TemplateSettings
from presscontroller.control import (
    ControllerLink,
    ControllerSession,
    Limits,
    NotAllowed,
    SessionState,
    RunPhase,
)
from presscontroller.control import commands as cmd
from presscontroller.control import session as session_mod
from presscontroller.protocol import PC_TO_CTRL
from presscontroller.tap import read_capture
from tests.conftest import FORCE_2_TO_END, PATH_2_PAUSE, ROOT
from tests.controller_fake import FakeController

STEP_26 = ROOT / "tests" / "data" / "break_threshold_start.jsonl"   # step 26, to its first #B23

#: Proteus' template in steps 21 and 23: Peak off, break identification off.
FORCE_2_TO_100 = TemplateSettings(ramp_control="force", force_speed_kn_s=2.0,
                                  force_end_kn=100.0)
PATH_2_TO_100 = TemplateSettings(ramp_control="path", path_speed_mm_min=2.0, path_end_mm=100.0)


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    monkeypatch.setattr(session_mod, "LISTEN_FIRST_S", 0.1)
    monkeypatch.setattr(session_mod, "REPLY_TIMEOUT_S", 0.3)
    monkeypatch.setattr(session_mod, "STREAM_TIMEOUT_S", 0.5)
    monkeypatch.setattr(session_mod, "TEST_SILENT_S", 0.4)


@pytest.fixture
def limits(press):
    return Limits.from_press(press)


def _run(s, until, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        s.poll()
        if until(s):
            return
        time.sleep(0.005)
    raise AssertionError(f"timed out: {s.state}, {s.test}")


def _connected(fake, limits, *, peak=False, break_detection=False):
    s = ControllerSession(ControllerLink("COM9", limits=limits, open_port=lambda n: fake))
    s.start()
    s.set_peak(peak)
    s.set_break_detection(break_detection)
    s.connect()
    _run(s, lambda s: s.state is SessionState.CONNECTED)
    return s


def _after_startup(fake):
    return fake.written[fake.written.index("#B37") + 3:]     # past #B37 and the two switches


def _proteus_test_lines(path, start="#B47", stop_at=None):
    """What Proteus sent from START on, without the shut-down."""
    lines = [e.text for e in read_capture(path) if e.direction == PC_TO_CTRL]
    lines = lines[lines.index(start):]
    if stop_at:
        lines = lines[:lines.index(stop_at) + 1]
    return lines


# ---- the built lines -----------------------------------------------------------------

def test_built_lines_are_proteus_numbers(limits):
    assert cmd.ramp_line(limits, "path", 2.0, 100.0) == "#D1233;0;100000;0;1"     # step 23
    assert cmd.ramp_line(limits, "path", 10.0, 100.0) == "#D12167;0;100000;0;1"   # step 19
    assert cmd.ramp_line(limits, "force", 2.0, 100.0) == "#D122000;0;100000;0;0"  # step 21
    assert cmd.start_load_line(0.10) == "#D0910"
    assert cmd.interval_line(200) == "#D0520"
    assert cmd.break_threshold_line(10.0) == "#D21100"                             # step 26
    assert cmd.break_threshold_line(25.0) == "#D21250"


@pytest.mark.parametrize("build", [
    lambda L: cmd.ramp_line(L, "path", 10.5, 100.0),        # above 10 mm/min
    lambda L: cmd.ramp_line(L, "path", 120.0, 100.0),       # step 22's mistake
    lambda L: cmd.ramp_line(L, "force", 15.5, 100.0),       # above 15 kN/s
    lambda L: cmd.ramp_line(L, "force", 2.0, 4001.0),       # beyond the force range
    lambda L: cmd.ramp_line(L, "path", 2.0, 0.0),
    lambda L: cmd.ramp_line(L, "deformation", 0.1, 1.0),
    lambda L: cmd.ramp_line(None, "path", 2.0, 100.0),      # no [limits]: no ramp at all
    lambda L: cmd.start_load_line(1.5),
    lambda L: cmd.interval_line(205),
    lambda L: cmd.interval_line(50),                         # faster than ever seen
    lambda L: cmd.interval_line(510),
    lambda L: cmd.break_threshold_line(0.5),
])
def test_a_value_outside_its_range_is_refused_when_built(limits, build):
    with pytest.raises(NotAllowed):
        build(limits)


@pytest.mark.parametrize("line", [
    "#D12168;0;100000;0;1",          # 10.08 mm/min: one count over the limit
    "#D122000;0;100000;0;2",         # Deformation control
    "#D122000;5;100000;0;0",         # a start field Proteus' builder never writes here
    "#D1233;0;100001;0;1",           # beyond the path range
    "#D0901", "#D09101", "#D0904x", "#D054", "#D055", "#D059", "#D0551", "#D05101", "#D219", "#D211001", "#D21010",
    "#B24", "#B34", "#B38", "#B60", "#B04", "#B11", "#D160", "#D161", "#X", "", "#B17 ",
])
def test_the_write_point_refuses_what_no_builder_would_make(limits, line):
    with pytest.raises(NotAllowed):
        cmd.check(line, limits)


def test_nothing_from_proteus_program_alone_is_allowed(limits):
    for line in cmd.NEVER:
        with pytest.raises(NotAllowed):
            cmd.check(line, limits)


def test_without_limits_no_ramp_passes_the_write_point(limits):
    line = cmd.ramp_line(limits, "path", 2.0, 100.0)
    assert cmd.check(line, limits) == line
    with pytest.raises(NotAllowed):
        cmd.check(line, None)


# ---- the sequence, against Proteus' recordings -----------------------------------------

def test_a_force_ramp_to_its_end_sends_what_proteus_sent_in_step_21(limits):
    fake = FakeController(ramp_s=0.15)
    s = _connected(fake, limits)
    try:
        assert s.start_test(FORCE_2_TO_100)
        _run(s, lambda s: s.test is RunPhase.AT_START_LOAD)
        assert s.continue_test()
        _run(s, lambda s: s.test is RunPhase.RAMP)
        _run(s, lambda s: s.test is RunPhase.NONE)
        # Proteus' lines, then ours alone: the interval before the ramp again
        # (Proteus leaves the ramp's in force after a test).
        assert _after_startup(fake) == (_proteus_test_lines(FORCE_2_TO_END, stop_at="#B17")
                                        + ["#D0510"])
        assert fake.ramp == "#D122000;0;100000;0;0" and fake.cancelled == 1
    finally:
        s.close()


def test_pause_and_continue_send_what_proteus_sent_in_step_23(limits):
    fake = FakeController()
    s = _connected(fake, limits)
    try:
        s.start_test(PATH_2_TO_100)
        _run(s, lambda s: s.test is RunPhase.AT_START_LOAD)
        s.continue_test()
        _run(s, lambda s: s.test is RunPhase.RAMP)
        assert s.pause_test() and s.test is RunPhase.PAUSED and fake.paused
        assert not s.pause_test()                      # PAUSE twice is not CONTINUE
        assert s.continue_test() and s.test is RunPhase.RAMP and not fake.paused
        s.pause_test()
        s.continue_test()
        assert s.stop() and s.test is RunPhase.NONE
        assert _after_startup(fake) == (_proteus_test_lines(PATH_2_PAUSE, stop_at="#B17")
                                        + ["#D0510"])
    finally:
        s.close()


def test_break_detection_on_sends_its_threshold_in_step_26s_order(limits):
    fake = FakeController()
    s = _connected(fake, limits, break_detection=True)
    try:
        s.start_test(replace(PATH_2_TO_100, break_threshold_per_mil=25.0))
        _run(s, lambda s: s.test is RunPhase.APPROACH)
        proteus = _proteus_test_lines(STEP_26, stop_at="#B23")
        proteus = proteus[:proteus.index("#B23") + 1]
        assert _after_startup(fake)[:6] == [
            line.replace("#D21100", "#D21250") for line in proteus]
    finally:
        s.close()


def test_start_sends_the_switches_as_they_stand_and_never_resets_them(limits):
    fake = FakeController()
    s = _connected(fake, limits, peak=True, break_detection=False)
    try:
        s.start_test(PATH_2_TO_100)
        _run(s, lambda s: s.test is RunPhase.APPROACH)
        assert _after_startup(fake)[:5] == ["#B47", "#B31", "#B32", "#D0910", "#B23"]
        assert s.peak and not s.break_detection
    finally:
        s.close()


def test_a_ramp_over_the_limits_sends_nothing_at_all(limits):
    fake = FakeController()
    s = _connected(fake, limits)
    try:
        n = len(fake.written)
        assert not s.start_test(replace(PATH_2_TO_100, path_speed_mm_min=120.0))
        assert fake.written[n:] == [] and s.test is RunPhase.NONE
        msg = s.pop_messages()[-1]
        assert msg.level == "error" and "limits" in msg.text
    finally:
        s.close()


def test_buttons_do_nothing_out_of_their_phase(limits):
    fake = FakeController()
    s = _connected(fake, limits)
    try:
        n = len(fake.written)
        assert not s.continue_test() and not s.pause_test()
        assert fake.written[n:] == []
        s.start_test(PATH_2_TO_100)
        assert not s.start_test(PATH_2_TO_100)          # one test at a time
        _run(s, lambda s: s.test is RunPhase.APPROACH)
        assert not s.continue_test() and not s.pause_test()
    finally:
        s.close()


# ---- every way out ends in Cancel ------------------------------------------------------

@pytest.mark.parametrize("phase", [RunPhase.APPROACH, RunPhase.AT_START_LOAD,
                                   RunPhase.RAMP, RunPhase.PAUSED])
def test_stop_is_cancel_in_every_phase(limits, phase):
    fake = FakeController(approach_s=0.3)
    s = _connected(fake, limits)
    try:
        s.start_test(PATH_2_TO_100)
        _run(s, lambda s: s.test in (phase, RunPhase.AT_START_LOAD))
        if phase in (RunPhase.RAMP, RunPhase.PAUSED):
            s.continue_test()
            _run(s, lambda s: s.test is RunPhase.RAMP)
        if phase is RunPhase.PAUSED:
            s.pause_test()
        _run(s, lambda s: s.test is phase)
        n = len(fake.written)
        assert s.stop()
        # After the ramp's #D0520, the interval before the ramp follows Cancel.
        ramp_ran = phase in (RunPhase.RAMP, RunPhase.PAUSED)
        assert fake.written[n:] == (["#B17", "#D0510"] if ramp_ran else ["#B17"])
        assert s.test is RunPhase.NONE
        assert s.state is SessionState.CONNECTED
    finally:
        s.close()


def test_no_answer_to_start_stops_the_test(limits):
    answers = dict(FakeController().answers)
    del answers["#B47"]
    fake = FakeController(answers=answers)
    s = _connected(fake, limits)
    try:
        s.start_test(PATH_2_TO_100)
        _run(s, lambda s: s.test is RunPhase.NONE)
        assert _after_startup(fake) == ["#B47", "#B17"]
        assert "did not answer #O" in s.pop_messages()[-1].text
    finally:
        s.close()


def test_an_unexplained_controller_line_during_a_test_stops_it(limits):
    fake = FakeController()
    s = _connected(fake, limits)
    try:
        s.start_test(PATH_2_TO_100)
        _run(s, lambda s: s.test is RunPhase.AT_START_LOAD)
        s.continue_test()
        _run(s, lambda s: s.test is RunPhase.RAMP)
        fake.say("#B05")                                 # no recording has it
        _run(s, lambda s: s.test is RunPhase.NONE)
        assert fake.written[-2:] == ["#B17", "#D0510"]
        msg = s.pop_messages()[-1]
        assert msg.level == "error" and "#B05" in msg.text
    finally:
        s.close()


def test_the_readings_stopping_during_a_test_stops_it(limits):
    fake = FakeController()
    s = _connected(fake, limits)
    try:
        s.start_test(PATH_2_TO_100)
        _run(s, lambda s: s.test is RunPhase.AT_START_LOAD)
        fake.silent = True
        _run(s, lambda s: s.test is RunPhase.NONE)
        assert fake.written[-1] == "#B17" and "no measurement" in s.pop_messages()[-1].text
    finally:
        s.close()


def test_keypad_stop_during_a_ramp_cancels_and_hands_the_keypad_back(limits):
    fake = FakeController()
    s = _connected(fake, limits)
    try:
        s.start_test(PATH_2_TO_100)
        _run(s, lambda s: s.test is RunPhase.AT_START_LOAD)
        s.continue_test()
        _run(s, lambda s: s.test is RunPhase.RAMP)
        n = len(fake.written)
        fake.press_keypad_stop()
        _run(s, lambda s: s.state is SessionState.IDLE)
        assert fake.written[n:] == ["#B17", "#B36", "#B21"] and s.test is RunPhase.NONE
    finally:
        s.close()


@pytest.mark.parametrize("leave", ["disconnect", "close"])
def test_leaving_during_a_test_cancels_first(limits, leave):
    fake = FakeController()
    s = _connected(fake, limits)
    s.start_test(PATH_2_TO_100)
    _run(s, lambda s: s.test is RunPhase.AT_START_LOAD)
    n = len(fake.written)
    getattr(s, leave)()
    assert fake.written[n:n + 3] == ["#B17", "#B36", "#B21"]
    if leave == "disconnect":
        s.close()


def test_the_load_released_after_stop_is_not_mistaken_for_trouble(limits):
    fake = FakeController(released_s=0.05)
    s = _connected(fake, limits)
    try:
        s.start_test(PATH_2_TO_100)
        _run(s, lambda s: s.test is RunPhase.AT_START_LOAD)
        s.stop()
        s.pop_messages()
        end = time.monotonic() + 0.3
        while time.monotonic() < end:
            s.poll()
        assert fake.written.count("#B17") == 1 and s.state is SessionState.CONNECTED
        assert not [m for m in s.pop_messages() if m.level == "error"]
    finally:
        s.close()


def test_a_break_is_cancelled_and_stop_stays_available(limits):
    # Step 32: at a cube's failure (1909 kN) the controller sent #B27; Cancel
    # stopped the pump but the load stayed (~1528 kN). Step 33: the operator's
    # STOP, a second Cancel, released it.
    fake = FakeController()
    s = _connected(fake, limits, break_detection=True)
    try:
        s.start_test(PATH_2_TO_100)
        _run(s, lambda s: s.test is RunPhase.AT_START_LOAD)
        s.continue_test()
        _run(s, lambda s: s.test is RunPhase.RAMP)
        n = len(fake.written)
        fake.say("#B27")
        _run(s, lambda s: s.test is RunPhase.NONE)
        assert fake.written[n:] == ["#B17", "#D0510"]
        assert s.state is SessionState.CONNECTED and fake.pc_mode
        msg = s.pop_messages()[-1]
        assert msg.level == "error" and "press STOP to release it" in msg.text
        assert "Disconnect, then STOP on the controller's keypad" in msg.text
        assert s.stop() and fake.written[n:] == ["#B17", "#D0510", "#B17"]
    finally:
        s.close()


def test_a_break_reported_after_stop_changes_nothing(limits):
    fake = FakeController()
    s = _connected(fake, limits, break_detection=True)
    try:
        s.start_test(PATH_2_TO_100)
        _run(s, lambda s: s.test is RunPhase.AT_START_LOAD)
        s.stop()
        fake.say("#B27")
        end = time.monotonic() + 0.2
        while time.monotonic() < end:
            s.poll()
        assert fake.written.count("#B17") == 1 and s.state is SessionState.CONNECTED
    finally:
        s.close()


def test_start_survives_the_controller_splitting_its_answer_around_a_reading(limits):
    # 2026-10-20, 11:04: "#O" CR, a stream line, then LF, in answer to START.
    answers = dict(FakeController().answers,
                   **{"#B47": "#O\r#D088002;0;17;1;383043;2;-26327\r\n"})
    fake = FakeController(answers=answers)
    s = _connected(fake, limits)
    try:
        s.start_test(PATH_2_TO_100)
        _run(s, lambda s: s.test in (RunPhase.APPROACH, RunPhase.NONE))
        assert s.test is RunPhase.APPROACH and "#B17" not in _after_startup(fake)
    finally:
        s.close()


def test_the_interval_before_the_ramp_is_sent_once_connected_unless_it_is_the_startups(limits):
    for wanted, after_switches in ((100, []), (200, ["#D0520"])):
        fake = FakeController()
        s = ControllerSession(ControllerLink("COM9", limits=limits, open_port=lambda n: fake))
        s.start()
        s.idle_interval_ms = wanted
        s.connect()
        try:
            _run(s, lambda s: s.state is SessionState.CONNECTED)
            i = fake.written.index("#B37")
            assert fake.written[i + 1:] == ["#B30", "#B33"] + after_switches
        finally:
            s.close()


def test_the_interval_before_the_ramp_follows_the_setting_and_returns_after_a_test(limits):
    fake = FakeController()
    s = _connected(fake, limits)
    try:
        s.set_idle_interval(300)
        assert fake.written[-1] == "#D0530"
        n = len(fake.written)
        s.set_idle_interval(300)                  # already in force: nothing sent
        assert len(fake.written) == n
        s.start_test(PATH_2_TO_100)
        _run(s, lambda s: s.test is RunPhase.AT_START_LOAD)
        s.set_idle_interval(150)                  # during a test: kept for its end
        assert "#D0515" not in fake.written
        s.continue_test()
        _run(s, lambda s: s.test is RunPhase.RAMP)
        n = len(fake.written)
        assert s.stop()
        assert fake.written[n:] == ["#B17", "#D0515"]
    finally:
        s.close()


def test_a_test_stopped_before_the_ramp_sends_no_interval(limits):
    """Before CONTINUE the ramp's interval was never sent: nothing to restore."""
    fake = FakeController()
    s = _connected(fake, limits)
    try:
        s.start_test(PATH_2_TO_100)
        _run(s, lambda s: s.test is RunPhase.AT_START_LOAD)
        n = len(fake.written)
        assert s.stop()
        assert fake.written[n:] == ["#B17"]
    finally:
        s.close()
