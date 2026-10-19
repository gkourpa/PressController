# Changelog

What each version added or changed, newest first.

## 0.0.1 — 2026-10-19

### Added

- **A listen-only monitor** on the passive RS-232 tap: live force, path and
  deformation; whether Proteus is connected; the test's phase (START, approach,
  start load, ramp, stopped, cancelled); the ramp Proteus sent, decoded; the
  peak force; a force–displacement plot of the newest test; and a log of
  every command and event heard, with its meaning.
- The ramp's real speed, measured from the path while it runs, beside the speed
  that was set; a warning when the two differ by more than 20 %, and when
  Proteus sends a ramp whose start is not where the piston is.
- Every byte heard is kept as a capture, and every test as a CSV with raw counts
  beside the values.
- `--replay` plays a recorded capture instead of listening.

First run on the live tap on 2026-10-19; tested on four real recordings.
