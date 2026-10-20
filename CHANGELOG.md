# Changelog

What each version added or changed, newest first.

## 0.1.0 — 2026-10-20

The first installer. Control mode runs tests on the press without Proteus.

### Added

- **Control mode** (`--control`): the program connects to the controller itself,
  with the old PC unplugged — Proteus' start-up replayed exactly, the live
  readings, Peak and break detection as on/off switches, disconnect. It cannot
  send anything that moves the press. Pressing STOP on the controller's keypad
  hands control back to the keypad at once. Run on the press on 2026-10-19: the
  controller answered exactly as it answers Proteus.
- The press file's `[limits]`: the fastest path and force ramps allowed. The
  monitor says so the moment a faster ramp is sent.

- **Tests from control mode**: START, PAUSE, CONTINUE and STOP, sending what
  Proteus sends, line for line. STOP (and Esc) is Cancel; every failure during a
  test ends in Cancel. Ramps are refused above the press file's `[limits]`.
- **Settings** (File → Settings…), saved in the settings file: the screen's
  redraw rate, control mode's port, and Proteus' test template — Peak, break
  detection and threshold, start load, the ramp and its measuring interval. The
  Peak and Break detection switches are remembered, never reset.
- `tools/proteus_cd.py`: reads Proteus' installation CD as data and lists the
  commands it sends.
- At a break (break detection on) the program stops the pump and says to press
  STOP again to release the load; "Piston: going down / still / going up" in the
  test bar.
- Settings in tabs: theme (system, light, dark), auto-connect, the plot's axis
  ranges and colour. The window opens as it was left (size, position,
  maximized, full screen with F11).
- The app icon, and a Windows installer (`tools/build_installer.py`).

### Changed

- PAUSE / CONTINUE (`#B18`) is understood as one toggling command; the measured
  ramp speed leaves paused time out.

## 0.0.1 — 2026-10-19

### Added

- **A listen-only monitor** on the passive RS-232 tap: live force, path and
  deformation; whether Proteus is connected; the test's phase (START, approach,
  start load, ramp, stopped, cancelled); the ramp Proteus sent, decoded; the
  peak force; a force–displacement plot of the newest test; and a log of
  every command and event heard, with its meaning.
- The ramp's real rate, measured while it runs, beside the rate that was set —
  mm/min for path control, kN/s for force control — and a warning when the two
  differ by more than 20 %. The start
  position the ramp was sent with is shown beside the piston's, as a note.
- Every byte heard is kept as a capture, and every test as a CSV with raw counts
  beside the values.
- `--replay` plays a recorded capture instead of listening.

First run on the live tap on 2026-10-19; tested on four real recordings.
