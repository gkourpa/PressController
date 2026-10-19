"""The tap: it never writes, it opens with its outputs off, and replay is faithful."""

from __future__ import annotations

import sys
import threading
import types

import pytest

from presscontroller.protocol import CTRL_TO_PC, PC_TO_CTRL
from presscontroller.tap import CaptureWriter, ReplayTap, SerialTap, open_read_only, read_capture
from tests.conftest import RAMP_6


class FakePort:
    """A port that plays back chunks and refuses to be written to."""

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self._lock = threading.Lock()
        self.closed = False

    @property
    def in_waiting(self):
        with self._lock:
            return len(self._chunks[0]) if self._chunks else 0

    def read(self, n):
        with self._lock:
            if self._chunks:
                return self._chunks.pop(0)
        threading.Event().wait(0.005)
        return b""

    def write(self, data):                                # pragma: no cover - the point
        raise AssertionError(f"the tap wrote {data!r}")

    def close(self):
        self.closed = True


def _drain(tap, n, timeout=2.0):
    import time
    got, end = [], time.monotonic() + timeout
    while len(got) < n and time.monotonic() < end:
        got += tap.poll()
        time.sleep(0.01)
    return got


def test_the_serial_tap_hands_out_both_directions_and_captures_every_byte(tmp_path):
    ports = {"COM7": FakePort([b"#B4", b"7\r\n"]),
             "COM6": FakePort([b"#O\r\n#D082;0;349;1;16059;2;-25513\r\n"])}
    cap = CaptureWriter(tmp_path / "c.jsonl", ports={}, settings="9600 8N1",
                        start=__import__("datetime").datetime(2026, 10, 19, 15, 0))
    tap = SerialTap("COM7", "COM6", capture=cap, open_port=ports.__getitem__)
    tap.start()
    events = _drain(tap, 3)
    tap.close()
    assert sorted((e.direction, e.text) for e in events) == sorted([
        (PC_TO_CTRL, "#B47"), (CTRL_TO_PC, "#O"),
        (CTRL_TO_PC, "#D082;0;349;1;16059;2;-25513")])
    assert all(p.closed for p in ports.values())
    # The capture holds the bytes, and reading it back gives the same lines.
    assert sorted(e.text for e in read_capture(cap.path)) == sorted(e.text for e in events)


def test_a_port_that_will_not_open_closes_the_one_that_did():
    opened = FakePort([])

    def open_port(name):
        if name == "COM6":
            raise OSError("COM6 is busy")
        return opened

    tap = SerialTap("COM7", "COM6", open_port=open_port)
    with pytest.raises(OSError, match="busy"):
        tap.start()
    assert opened.closed


def test_open_read_only_turns_dtr_and_rts_off_before_opening(monkeypatch):
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
    open_read_only("COM7")
    assert calls[0] == ("init", 9600)
    i_open = calls.index(("open",))
    assert calls.index(("set", "dtr", False)) < i_open
    assert calls.index(("set", "rts", False)) < i_open
    assert not any(c[0] == "set" and c[1] in ("dtr", "rts") and c[2] for c in calls)


def test_the_tap_module_has_no_way_to_send():
    import inspect

    import presscontroller.tap.serial_tap as mod
    assert ".write(" not in inspect.getsource(mod).replace("self._capture.write(", "")


def test_capture_refuses_to_append_to_an_existing_file(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text("", encoding="utf-8")
    with pytest.raises(FileExistsError):
        CaptureWriter(p, ports={}, settings="", start=__import__("datetime").datetime.now())


def test_read_capture_rebuilds_the_lines_in_time_order():
    events = read_capture(RAMP_6)
    assert [e.text for e in events[:2]] == ["#B21", "#B20"]
    assert all(a.t <= b.t for a, b in zip(events, events[1:]))
    # Wall time comes from the capture's own start.
    assert events[0].wall.strftime("%Y-%m-%d") == "2026-10-19"


def test_replay_follows_its_clock_and_speed():
    now = [0.0]
    tap = ReplayTap(RAMP_6, speed=10.0, clock=lambda: now[0])
    assert tap.poll() == []                       # not started
    tap.start()
    first_t = read_capture(RAMP_6)[0].t
    now[0] = first_t / 10.0 - 0.01
    assert tap.poll() == []
    now[0] = first_t / 10.0 + 0.001
    got = tap.poll()
    assert got and got[0].text == "#B21"
    now[0] = 1e6
    rest = tap.poll()
    assert tap.finished and len(got) + len(rest) == len(read_capture(RAMP_6))
