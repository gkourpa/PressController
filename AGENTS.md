# PressController — agent entry point

This is the authoritative starting point for work in this repository. Read this
file first, then open only the topic documents relevant to the task. `CLAUDE.md`
redirects here so every coding agent uses the same instructions.

## Project in one paragraph

The lab's 4000 kN FORM+TEST compression press is run by a DigiMaxx C-20
controller, driven over RS-232 by *Proteus* on a failing Windows 9x PC. The
controller is discontinued and its protocol undocumented. This project learns
that protocol by listening (a passive tap: a Y-cable and two USB-serial adapters,
`docs/RS232_Tap_Wiring.pdf`), records what is learnt in `docs/PROTOCOL.md`, and
builds a modern Windows/Python replacement for Proteus. **Milestone 1 is a
listen-only monitor**: it decodes the live link while Proteus still runs the
press.

## Non-negotiable rules

1. **Only allowlisted lines are ever sent to the controller.** The allowlist
   (`control/commands.py`) is checked at the one place a byte leaves
   (`ControllerLink.send`); the tap and the monitor window have no write path
   and do not import `control`. The list holds exact lines Proteus was
   recorded sending, and four lines built from settings, each accepted only
   inside its range (the ramp within the press file's `[limits]`;
   docs/motion.md). **A code seen only in Proteus' program, never on the line,
   is never sent** (`commands.NEVER`). Every way out of a test — STOP, a missing
   answer, an unexplained controller line, the readings stopping, disconnect,
   closing — sends Cancel (`#B17`); every way out of PC mode ends with stream
   off and PC mode off. The controller's own STOP and the press emergency stop remain the
   primary safety devices; **PAUSE (`#B18`) is not a stop**, Cancel (`#B17`) is.
2. A protocol meaning is **confirmed** only when the controller's display or the
   press's behaviour showed it; anything inferred from timing is a hypothesis
   and is marked so in `docs/PROTOCOL.md` and in `protocol/messages.py`
   (`confirmed=False`, shown with a `?`).
3. Preserve the compute-first architecture. Protocol, configuration, tap and
   monitor logic stay Qt-free; windows are thin views over tested logic.
4. Never put serial ports, ranges, resolutions or paths in source. They belong
   in a press file or the global settings.
5. Never let tests read or write the operator's settings, and never let ordinary
   tests open a serial port. Real captures in `tests/data` stand in for the
   press.
6. A line that does not parse is kept verbatim and said out loud, never dropped.
   A reading is never invented: a missing value is a gap.
7. A test's output is one strict CSV: `#` header lines, no bare `NaN`, never
   overwritten, raw counts beside values so the scaling can be undone.
8. Do not add explanatory tooltips; explanations belong in visible text or
   docstrings (the sibling projects' rule).
9. Update the relevant topic document when a change makes a documented contract
   or status statement false. Do not grow this file into a development log.

## Read by task

| If the task concerns… | Read |
| --- | --- |
| what the controller says, command by command, and how each was learnt | [Protocol notes](docs/PROTOCOL.md) |
| scope, decisions, milestones, open work | [Project overview](docs/project-overview.md) |
| packages, ownership, dependency boundaries, provenance | [Architecture](docs/architecture.md) |
| the monitor window, the control window and their rules | [The window](docs/ui.md) |
| control mode: connecting without Proteus, the allowlist, the session | [Control](docs/control.md) |
| install, commands, pytest, the sniffer, the tap's wiring | [Development and testing](docs/development-and-testing.md) |

## Default working loop

1. Inspect the relevant modules and their tests before editing.
2. Make the smallest change that preserves the contracts above.
3. Add or update a regression test that exercises the real public path —
   preferably on a real capture.
4. Run the narrow tests first, then the full suite:

   ```powershell
   $env:QT_QPA_PLATFORM = "offscreen"
   .venv\Scripts\python -m pytest -q
   ```

## Fast facts

- Package: `presscontroller`; GUI entry point `python -m presscontroller.app` or
  `run_app.py`. Display name **PressController**. Stable identifiers:
  `%APPDATA%\PressController`, App User Model ID `gkourpa.PressController`.
- Python 3.14 in `.venv`; dependencies pinned in `requirements.txt` (same pins as
  DAqReader where shared); `pyproject.toml` is the human-readable summary.
- The version is set in `presscontroller/__init__.py` alone.
- Stack and several modules come from DAqReader (`..\DAqReader`): see
  [Architecture → Provenance](docs/architecture.md#provenance).
