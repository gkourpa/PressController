"""The program planner: every step's lines and time, and what is wrong with it,
before a byte is sent (docs/motion.md, "Programs"; steps 35-38)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from presscontroller.config.settings import ProgramStep, TemplateSettings
from presscontroller.control import Limits, plan_program
from tests.conftest import FORCE_CYCLE
from tests.test_motion import CYCLE

S = ProgramStep


@pytest.fixture
def limits(press):
    return Limits.from_press(press)


def test_step_38s_program_plans_step_38s_lines(limits):
    p = plan_program(replace(CYCLE, steps=tuple(replace(s, hold_s=10.0) if s.kind == "hold"
                                                  else s for s in CYCLE.steps)),
                     limits, peak=False)
    assert p.ok
    assert p.start_switches == ("#B30", "#B32") and p.start_load == "#D091"
    assert [s.lines for s in p.steps] == [
        ("#D0510", "#D122000;0;200000;0;0"), (), ("#D0510", "#D122000;0;100000;0;0"), (),
        ("#B33", "#D21100", "#D0510", "#D124000;0;250000;0;0")]
    assert [s.break_on for s in p.steps] == [False] * 4 + [True]
    assert p.break_from == 5
    # From the 0.4 kN start load (0.01 % of 4000 kN).
    assert p.total_s == pytest.approx((200 - 0.4) / 2 + 10 + 50 + 10 + 37.5)
    assert p.told() == ("5 steps (3 ramps, 2 holds) · about 3 min 27 s · "
                        "break detection from step 5")


def test_break_detection_from_the_first_step_goes_out_at_start(limits):
    p = plan_program(replace(CYCLE, steps=(S("ramp", 300.0, 5.0, break_on=True),)),
                     limits, peak=True)
    assert p.start_switches == ("#B31", "#B33", "#D21100")
    assert p.steps[0].lines == ("#D0510", "#D125000;0;300000;0;0")
    assert p.told() == "Force 5 kN/s to 300 kN · break detection on"


def test_the_default_program_is_the_labs_path_ramp(limits):
    p = plan_program(TemplateSettings(), limits, peak=False)
    assert p.controls == {"path"} and len(p.steps) == 1 and p.total_s is None
    assert p.start_switches == ("#B30", "#B33", "#D21100")
    assert p.told() == "Path 2 mm/min to 100 mm · break detection on"


@pytest.mark.parametrize("steps, words", [
    ((S("ramp", 200.0, 2.0, break_on=True), S("ramp", 150.0, 2.0)),
     "unloading 50 kN from 200 kN would read as a break (threshold 40 kN)"),
    ((S("ramp", 200.0, 2.0), S("ramp", 200.0, 2.0)), "this ramp would not move"),
    ((S("ramp", 200.0, 20.0),), "faster than the press file's [limits]"),
    ((S("ramp", 5000.0, 2.0),), "outside the channel's range"),
    ((S("ramp", 100.0, 2.0), S("ramp", 0.2, 2.0)), "below the start load"),
    ((S("hold", hold_s=5.0), S("ramp", 100.0, 2.0)), "must start with a ramp"),
    ((S("ramp", 100.0, 2.0), S("hold", hold_s=0.0)), "outside 1–600 s"),
    ((), "no steps"),
])
def test_a_step_that_cannot_run_is_named(limits, steps, words):
    p = plan_program(replace(CYCLE, steps=steps), limits, peak=False)
    assert not p.ok and any(words in why for why in p.problems), p.problems


def test_a_small_unload_under_break_detection_is_allowed(limits):
    # The threshold is a fall from the peak since break detection came on:
    # 30 kN down from 200 kN stays under 40 kN.
    p = plan_program(replace(CYCLE, steps=(S("ramp", 200.0, 2.0, break_on=True),
                                           S("ramp", 170.0, 2.0), S("ramp", 300.0, 2.0))),
                     limits, peak=False)
    assert p.ok


def test_the_recorded_cycle_is_in_the_test_data():
    assert FORCE_CYCLE.is_file()


def test_path_steps_by_a_distance_are_worked_out_when_sent(limits):
    # Step 41's program: Path +2 mm (from the piston), hold, Path -1 mm (from
    # the previous ramp's set end), hold, Force to 50 kN with break detection on.
    t = replace(CYCLE, steps=(
        S("ramp", control="path", path_mm=2.0, path_relative=True, speed_mm_min=2.0),
        S("hold", hold_s=10.0),
        S("ramp", control="path", path_mm=-1.0, path_relative=True, speed_mm_min=2.0),
        S("hold", hold_s=10.0),
        S("ramp", 50.0, 2.0, break_on=True)))
    p = plan_program(t, limits, peak=False)
    assert p.ok, p.problems
    assert [s.path_by for s in p.steps] == [2.0, None, -1.0, None, None]
    assert p.steps[0].path_from == "the piston"
    assert p.steps[2].path_from == "the previous ramp's end"
    assert p.steps[0].lines == ("#D0510",)              # the ramp is built when sent
    assert p.steps[4].lines == ("#B33", "#D21100", "#D0510", "#D122000;0;50000;0;0")
    assert p.steps[0].seconds == pytest.approx(60.0)     # 2 mm at 2 mm/min
    assert p.steps[4].seconds is None                    # the force after Path is not known
    assert not p.force_profile_known and p.controls == {"path", "force"}
    assert p.told().startswith("5 steps (3 ramps, 2 holds) · break detection from step 5")


@pytest.mark.parametrize("steps", [
    (S("ramp", control="path", path_mm=2.0, path_relative=True, break_on=True),
     S("ramp", control="path", path_mm=-1.0, path_relative=True)),
    (S("ramp", control="path", path_mm=60.0, break_on=True),
     S("ramp", control="path", path_mm=50.0)),
])
def test_a_path_ramp_down_under_break_detection_is_refused(limits, steps):
    # Step 41: the Path ramp down took the load from 133 to 10 kN.
    p = plan_program(replace(CYCLE, steps=steps), limits, peak=False)
    assert any("a Path ramp down unloads the specimen" in why for why in p.problems)


def test_a_path_ramp_over_its_limit_or_range_is_named(limits):
    fast = S("ramp", control="path", path_mm=1.0, path_relative=True, speed_mm_min=12.0)
    far = S("ramp", control="path", path_mm=150.0, speed_mm_min=2.0)
    assert "faster than the press file's [limits]" in plan_program(
        replace(CYCLE, steps=(fast,)), limits, peak=False).problems[0]
    assert "outside the channel's range" in plan_program(
        replace(CYCLE, steps=(far,)), limits, peak=False).problems[0]
