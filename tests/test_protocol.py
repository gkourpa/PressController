"""The line protocol: assembling lines from bytes, and what each line parses to."""

from __future__ import annotations

import pytest

from presscontroller.protocol import (
    CTRL_TO_PC,
    PC_TO_CTRL,
    Ack,
    Command,
    LineAssembler,
    Ramp,
    Reply,
    Sample,
    SetParam,
    Unknown,
    describe,
    parse,
)
from presscontroller.protocol.lines import MAX_LINE


def test_a_line_split_across_reads_is_whole_and_stamped_at_its_first_byte():
    a = LineAssembler(CTRL_TO_PC)
    assert a.feed(b"#D0819630;0;-12", 1.0) == []
    assert a.pending == b"#D0819630;0;-12"
    assert a.feed(b"46;1;15859;2;-25637\r\n#O\r", 1.03) == [
        (1.0, "#D0819630;0;-1246;1;15859;2;-25637")]
    assert a.feed(b"\n", 1.05) == [(1.03, "#O")]


def test_two_lines_in_one_read():
    a = LineAssembler(PC_TO_CTRL)
    assert a.feed(b"#B21\r\n#B20\r\n", 5.0) == [(5.0, "#B21"), (5.0, "#B20")]


def test_noise_is_handed_on_visibly_rather_than_held_forever():
    a = LineAssembler(CTRL_TO_PC)
    out = a.feed(bytes([0xE0] * MAX_LINE), 0.0)
    assert len(out) == 1 and out[0][1].startswith("\\xe0")
    assert a.pending == b""


def test_stream_line():
    assert parse(CTRL_TO_PC, "#D0819630;0;-1246;1;15859;2;-25637") == Sample(
        8, 19630, {0: -1246, 1: 15859, 2: -25637})


def test_stream_line_just_after_the_counter_reset():
    # Seen when the approach started: the counter restarts at 2.
    assert parse(CTRL_TO_PC, "#D082;0;349;1;16059;2;-25513") == Sample(
        8, 2, {0: 349, 1: 16059, 2: -25513})


@pytest.mark.parametrize("text, msg", [
    ("#O", Ack()),
    ("#D138.6", Reply("38.6")),
    ("#D104000", Reply("04000")),
    ("#B01", Command(1)),
    ("#B43", Command(43)),
])
def test_controller_lines(text, msg):
    assert parse(CTRL_TO_PC, text) == msg


@pytest.mark.parametrize("text, msg", [
    ("#B47", Command(47)),
    ("#B17", Command(17)),
    ("#D0510", SetParam(5, 10)),
    ("#D0520", SetParam(5, 20)),
    ("#D020", SetParam(2, 0)),
    ("#D0910", SetParam(9, 10)),
    ("#D12167;0;100000;0;1", Ramp(167, 0, 100000, 0, 1)),
    ("#D12100;79446;100000;0;1", Ramp(100, 79446, 100000, 0, 1)),
])
def test_pc_lines(text, msg):
    assert parse(PC_TO_CTRL, text) == msg


def test_direction_decides_what_a_d_line_is():
    # A parameter from the PC is not a stream line, and a reply is not a ramp.
    assert parse(CTRL_TO_PC, "#D0510") == Unknown("#D0510")
    assert parse(PC_TO_CTRL, "#D138.6") == Unknown("#D138.6")


def test_anything_else_is_kept_verbatim():
    assert parse(PC_TO_CTRL, "#X12") == Unknown("#X12")
    assert parse(CTRL_TO_PC, "") == Unknown("")


def test_ramp_units():
    assert Ramp(167, 0, 100000, 0, 1).speed_mm_min == pytest.approx(10.02)
    assert Ramp(100, 79446, 100000, 0, 1).speed_mm_min == pytest.approx(6.0)


def test_descriptions_mark_a_guess_with_a_question_mark():
    assert describe(PC_TO_CTRL, Command(17)) == "Cancel: pump off, test ends"
    assert describe(PC_TO_CTRL, Command(20)).endswith("?")
    assert describe(CTRL_TO_PC, Command(1)) == "start load reached"
    assert describe(PC_TO_CTRL, Command(99)) == "unknown command"
    assert describe(PC_TO_CTRL, SetParam(5, 20)) == "stream interval 200 ms"
