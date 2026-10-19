"""Shared fixtures.

Ordinary tests never open a serial port and never touch the operator's settings.
The captures in ``tests/data`` are real recordings from the tap
(docs/PROTOCOL.md, steps 13, 15, 16, 17 and 20), so the monitor is tested on what the
press really said.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(__file__).resolve().parent / "data"
EXAMPLE_PRESS = ROOT / "examples" / "press.example.toml"

#: Step 15: a 150 mm cube to failure, template 10 mm/min, ramp sent with start 0.
REAL_TEST = DATA / "real_test_10mm_min.jsonl"
#: Step 16: a cancelled START, then a 6 mm/min ramp stopped at ~570 kN.
RAMP_6 = DATA / "ramp_6mm_min.jsonl"
#: Step 17, the monitor's first live run: 3 mm/min, ramp start sent as twice
#: the piston position, speed unaffected.
RAMP_3 = DATA / "ramp_3mm_min_start_doubled.jsonl"
#: Step 20: a force-controlled ramp, 5 kN/s to 300 kN, stopped at 247 kN.
FORCE_5 = DATA / "force_5kn_s.jsonl"
#: Step 13: START with no specimen, then Cancel during the approach.
DRY_RUN = DATA / "dryrun_start_cancel.jsonl"


@pytest.fixture(autouse=True)
def _sandboxed_settings(tmp_path, monkeypatch):
    """Point the global settings at a per-test file, for every test — a test that
    saved settings would otherwise rewrite the operator's real file."""
    from presscontroller.config.settings import SETTINGS_ENV
    sandbox = tmp_path / "settings" / "settings.toml"
    monkeypatch.setenv(SETTINGS_ENV, str(sandbox))
    yield sandbox


@pytest.fixture
def press():
    from presscontroller.config.press import load_press
    cfg, problems = load_press(EXAMPLE_PRESS)
    assert problems == []
    return cfg


def replay_all(press, path):
    """A monitor fed every line of ``path``, and the notices it gave."""
    from presscontroller.monitor import Monitor
    from presscontroller.tap import read_capture
    m = Monitor(press)
    notices = []
    for ev in read_capture(path):
        notices += m.feed(ev)
    return m, notices


@pytest.fixture(scope="session")
def qapp():
    """The one ``QApplication`` every offscreen UI test shares. Each UI test
    module sets ``QT_QPA_PLATFORM=offscreen`` before it imports PySide6."""
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])
