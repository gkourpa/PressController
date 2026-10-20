"""The line protocol: assembling lines from bytes, and what each line parses to."""

from __future__ import annotations

import pytest

from presscontroller.protocol import (
    CTRL_TO_PC,
    PC_TO_CTRL,
    Ack,
    BreakThreshold,
    Command,
    LineAssembler,
    Ramp,
    Reply,
    ReportLine,
    Sample,
    SetParam,
    Unknown,
    describe,
    parse,
    rate_text,
)
from presscontroller.protocol.lines import MAX_LINE


def test_a_line_split_across_reads_is_whole_and_stamped_at_its_first_byte():
    a = LineAssembler(CTRL_TO_PC)
    assert a.feed(b"#D0819630;0;-12", 1.0) == []
    assert a.pending == b"#D0819630;0;-12"
    assert a.feed(b"46;1;15859;2;-25637\r\n#O", 1.03) == [
        (1.0, "#D0819630;0;-1246;1;15859;2;-25637")]
    assert a.feed(b"\r\n", 1.05) == [(1.03, "#O")]


def test_a_reply_split_around_a_measurement_line_is_two_lines():
    # 2026-10-20, 11:04: the controller sent #O's CR, a whole stream line, then
    # #O's LF. Read as ending only at CR LF, it was one unknown line.
    a = LineAssembler(CTRL_TO_PC)
    raw = b"23\r\n#O\r#D088002;0;17;1;383043;2;-26327\r\n\n#D088"
    assert [text for _, text in a.feed(raw, 2.0)] == [
        "23", "#O", "#D088002;0;17;1;383043;2;-26327"]
    assert a.pending == b"#D088"


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
    ("#D21100", BreakThreshold(100)),
    ("#D21250", BreakThreshold(250)),
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


def test_ramp_numbers_are_thousandths_of_the_channel_unit():
    path = Ramp(167, 0, 100000, 0, 1)            # 10 mm/min to 100 mm
    assert path.rate * 60 == pytest.approx(10.02) and path.end_value == 100.0
    force = Ramp(5000, 0, 300000, 0, 0)          # 5 kN/s to 300 kN
    assert force.rate == 5.0 and force.end_value == 300.0


def test_rates_are_told_as_tests_are_set():
    assert rate_text(10.02 / 60, "mm") == "10 mm/min"
    assert rate_text(5.028, "kN") == "5.03 kN/s"


def test_a_ramp_is_told_in_its_own_channel_unit():
    units = {0: "kN", 1: "mm", 2: "mm"}
    assert describe(PC_TO_CTRL, Ramp(5000, 0, 300000, 0, 0), units) == (
        "ramp on channel 0: 5 kN/s from 0 to 300 kN")
    assert describe(PC_TO_CTRL, Ramp(100, 79446, 100000, 0, 1), units) == (
        "ramp on channel 1: 6 mm/min from 79.446 to 100 mm")


def test_a_ramp_on_an_unconfirmed_channel_is_given_raw():
    text = describe(PC_TO_CTRL, Ramp(50, 0, 1000, 0, 2), {2: "mm"})
    assert "channel 2" in text and "units not decoded" in text and "mm" not in text
    assert "units not decoded" in describe(PC_TO_CTRL, Ramp(5000, 0, 300000, 0, 0))


def test_descriptions_mark_a_guess_with_a_question_mark():
    assert describe(PC_TO_CTRL, Command(17)) == "Cancel: pump off, test ends"
    assert describe(PC_TO_CTRL, Command(20)).endswith("?")
    assert describe(CTRL_TO_PC, Command(1)) == "start load reached"
    assert describe(PC_TO_CTRL, Command(99)) == "unknown command"
    assert describe(PC_TO_CTRL, SetParam(5, 20)) == "stream interval 200 ms"


def test_the_break_threshold_is_the_templates_value_times_ten():
    # Step 26: Proteus' template at 10 and at 25 per mil.
    assert BreakThreshold(100).per_mil == 10.0
    assert describe(PC_TO_CTRL, BreakThreshold(250)) == "break threshold 25 ‰"


def test_the_controllers_own_report_is_read_as_its_lines():
    # Step 31: sent on leaving PC mode during a test.
    assert parse(CTRL_TO_PC, "      BREAK            44.9 kN") == ReportLine("BREAK", "44.9 kN")
    assert parse(CTRL_TO_PC, "      DEFORM        + 67.39 mm") == ReportLine("DEFORM", "+ 67.39 mm")
    assert parse(CTRL_TO_PC, "      AGE               0 Days") == ReportLine("AGE", "0 Days")
    assert describe(CTRL_TO_PC, ReportLine("BREAK", "44.9 kN")) == (
        "the controller's own report")
    # From the PC, or without the indent, it is not a report.
    assert parse(PC_TO_CTRL, "      BREAK            44.9 kN") == Unknown("      BREAK            44.9 kN")
    assert parse(CTRL_TO_PC, "BREAK 44.9 kN") == Unknown("BREAK 44.9 kN")


def test_a_line_not_in_the_notes_is_said_once():
    assert describe(CTRL_TO_PC, Unknown("#X")) == ""
