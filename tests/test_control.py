"""Control mode: only allowed lines leave, Proteus' start-up is replayed exactly,
and every way out — disconnect, abort, keypad STOP, closing — hands control back."""

from __future__ import annotations

import os
import subprocess
import sys
import time
import types

import pytest

from presscontroller.control import (
    ALLOWED,
    ControllerLink,
    ControllerSession,
    NotAllowed,
    SessionState,
    open_for_control,
)
from presscontroller.control import commands as cmd
from presscontroller.control import session as session_mod
from presscontroller.monitor import Monitor
from presscontroller.protocol import PC_TO_CTRL
from presscontroller.tap import CaptureWriter, read_capture
from tests.controller_fake import FakeController
from tests.conftest import FORCE_2_TO_END


@pytest.fixture(autouse=True)
def _quick(monkeypatch):
    """The real waits are seconds long; the fake answers in milliseconds."""
    monkeypatch.setattr(session_mod, "LISTEN_FIRST_S", 0.1)
    monkeypatch.setattr(session_mod, "REPLY_TIMEOUT_S", 0.3)
    monkeypatch.setattr(session_mod, "STREAM_TIMEOUT_S", 0.5)


def _session(fake, capture=None):
    link = ControllerLink("COM9", open_port=lambda name: fake, capture=capture)
    s = ControllerSession(link)
    s.start()
    return s


def _run(s, until, timeout=3.0):
    events = []
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        events += s.poll()
        if until(s):
            return events
        time.sleep(0.005)
    raise AssertionError(f"timed out in state {s.state}")


def _connected(fake):
    s = _session(fake)
    s.connect()
    _run(s, lambda s: s.state is SessionState.CONNECTED)
    return s


def test_the_allowlist_holds_only_lines_proteus_was_recorded_sending():
    assert not ALLOWED & cmd.NEVER
    for line in ["#B24", "#B38", "#B60", "#D160", "#X", "", "#B17 ",
                 "#D12167;0;100000;0;1"]:      # a ramp, without the press file's limits
        with pytest.raises(NotAllowed):
            cmd.check(line)


def test_a_line_not_allowed_never_reaches_the_port():
    fake = FakeController()
    s = _session(fake)
    try:
        with pytest.raises(NotAllowed):
            s.link.send("#B38")
        assert fake.written == [] and s.link.sent == []
    finally:
        s.close()


def test_connecting_replays_proteus_startup_byte_for_byte():
    proteus = []
    for e in read_capture(FORCE_2_TO_END):
        if e.direction == PC_TO_CTRL:
            proteus.append(e.text)
            if e.text == "#B37":
                break
    fake = FakeController()
    s = _connected(fake)
    try:
        # Proteus' start-up exactly, then the two switches set to their positions.
        assert fake.written == proteus + ["#B30", "#B33"]
        assert s.replies == ["#O", "#D138.6", "#D104000", "#D140", "#D180"]
        assert fake.pc_mode and fake.streaming
    finally:
        s.close()


def test_a_busy_line_is_refused_without_sending_a_byte():
    fake = FakeController(busy=True)          # another PC already streaming
    s = _session(fake)
    try:
        s.connect()
        _run(s, lambda s: s.state is SessionState.FAILED)
        assert fake.written == []
        assert "old PC" in s.pop_messages()[-1].text
    finally:
        s.close()
    assert fake.written == []                 # closing a refused session sends nothing


def test_an_unexpected_answer_aborts_and_hands_control_back():
    answers = dict(FakeController().answers, **{"#B40": "#D103000"})
    fake = FakeController(answers=answers)
    s = _session(fake)
    try:
        s.connect()
        _run(s, lambda s: s.state is SessionState.FAILED)
        assert fake.written == ["#B21", "#B20", "#B50", "#B40", "#B36", "#B21"]
        assert not fake.pc_mode
        msg = s.pop_messages()[-1]
        assert msg.level == "error" and "#D103000" in msg.text
    finally:
        s.close()


def test_no_answer_aborts_after_the_wait():
    answers = dict(FakeController().answers)
    del answers["#B52"]
    fake = FakeController(answers=answers)
    s = _session(fake)
    try:
        s.connect()
        _run(s, lambda s: s.state is SessionState.FAILED)
        assert fake.written[-2:] == ["#B36", "#B21"] and "#B37" not in fake.written
        assert "no answer" in s.pop_messages()[-1].text
    finally:
        s.close()


def test_disconnect_is_stream_off_then_pc_mode_off():
    fake = FakeController()
    s = _connected(fake)
    try:
        n = len(fake.written)
        s.disconnect()
        assert fake.written[n:] == ["#B36", "#B21"]
        assert not fake.pc_mode and not fake.streaming
        assert s.state is SessionState.IDLE
    finally:
        s.close()
    assert fake.written[-2:] == ["#B36", "#B21"] and fake.written.count("#B21") == 2


def test_closing_while_connected_disconnects_first():
    fake = FakeController()
    s = _connected(fake)
    s.close()
    assert fake.written[-2:] == ["#B36", "#B21"] and fake.closed and not fake.pc_mode


def test_keypad_stop_cancels_and_hands_the_keypad_back():
    fake = FakeController()
    s = _connected(fake)
    try:
        n = len(fake.written)
        fake.press_keypad_stop()
        _run(s, lambda s: s.state is SessionState.IDLE)
        assert fake.written[n:] == ["#B17", "#B36", "#B21"]
        assert fake.cancelled == 1 and not fake.pc_mode
        assert any(m.level == "warn" and "Keypad STOP" in m.text for m in s.pop_messages())
    finally:
        s.close()


def test_switches_start_at_the_controllers_defaults_and_are_set_on_connect():
    fake = FakeController()
    fake.peak, fake.break_detection = True, False        # left so by an earlier session
    s = _session(fake)
    try:
        assert s.peak is False and s.break_detection is True
        s.connect()
        _run(s, lambda s: s.state is SessionState.CONNECTED)
        assert fake.peak is False and fake.break_detection is True
    finally:
        s.close()


def test_a_switch_flipped_before_connecting_waits_and_sends_nothing():
    fake = FakeController()
    s = _session(fake)
    try:
        s.set_break_detection(False)
        s.set_peak(True)
        assert fake.written == []
        s.connect()
        _run(s, lambda s: s.state is SessionState.CONNECTED)
        assert fake.written[-2:] == ["#B31", "#B32"]
        assert fake.peak and not fake.break_detection
    finally:
        s.close()


def test_a_switch_flipped_while_connected_is_sent_at_once():
    fake = FakeController()
    s = _connected(fake)
    try:
        s.set_break_detection(False)
        assert fake.written[-1] == "#B32" and not fake.break_detection
        s.set_break_detection(True)
        assert fake.written[-1] == "#B33" and fake.break_detection
    finally:
        s.close()


def test_the_monitor_follows_our_own_session(press):
    fake = FakeController()
    s = _session(fake)
    m = Monitor(press)
    try:
        s.connect()
        end = time.monotonic() + 3.0
        while not (s.state is SessionState.CONNECTED and m.latest) and time.monotonic() < end:
            for ev in s.poll():
                m.feed(ev)
            time.sleep(0.005)
        assert m.proteus and m.streaming and m.interval_ms == 100
        assert m.latest_value(m.force_index) == pytest.approx(1.0)
    finally:
        s.close()


def test_a_control_session_is_captured_in_both_directions(tmp_path):
    from datetime import datetime
    fake = FakeController()
    cap = CaptureWriter(tmp_path / "c.jsonl", ports={"control": "COM9"},
                        settings="9600 8N1", start=datetime(2026, 10, 19, 17, 0))
    s = _session(fake, capture=cap)
    s.connect()
    _run(s, lambda s: s.state is SessionState.CONNECTED)
    s.close()
    lines = [(e.direction, e.text) for e in read_capture(cap.path)
             if not e.text.startswith("#D08")]
    assert [t for d, t in lines if d == PC_TO_CTRL] == fake.written
    assert ("CTRL>PC", "#D104000") in lines


def test_open_for_control_asserts_dtr_and_rts_before_opening(monkeypatch):
    calls = []

    class Serial:
        def __init__(self, **kw):
            calls.append(("init", kw["baudrate"]))

        def __setattr__(self, name, value):
            calls.append(("set", name, value))
            object.__setattr__(self, name, value)

        def open(self):
            calls.append(("open",))

    fake = types.SimpleNamespace(Serial=Serial, EIGHTBITS=8, PARITY_NONE="N", STOPBITS_ONE=1)
    monkeypatch.setitem(sys.modules, "serial", fake)
    open_for_control("COM6")
    i_open = calls.index(("open",))
    assert calls.index(("set", "dtr", True)) < i_open
    assert calls.index(("set", "rts", True)) < i_open


def test_the_monitor_window_does_not_load_the_control_package():
    code = ("import sys, presscontroller.app.main_window; "
            "print('presscontroller.control' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env=dict(os.environ, QT_QPA_PLATFORM="offscreen"), check=True)
    assert out.stdout.strip() == "False"
