# The window

Run with `python -m presscontroller.app` (or `python run_app.py`). The first
launch asks for the press file and the data folder; both are remembered.
`--replay CAPTURE.jsonl [--speed N]` plays a recording instead of listening.

## Listen-only

The monitor has **no control that sends anything to the press**: no Start, no
Stop, no Zero. Proteus stays in control. The message island says so, and names
the source — the two ports, or the capture being replayed — so a replay is never
mistaken for the press.

## Layout

- **Status card**: whether Proteus has the controller in PC mode, the data
  interval, the test's phase, the test (number, START time, running or why it
  ended), the ramp that was sent, and the live path and force rates.
- **Gauges**: one per channel of the press file, and the peak force of the
  newest test. Copied from DAqReader, with its rules: right-aligned, sized for the
  widest reading the channel's range can give, shrinking only, never a zero for
  a missing value (a dash instead).
- **Plot**: force against displacement of the newest test, with the newest
  point dotted and the peak marked and written out. **Not against time**
  (operator, 2026-10-19): the curve is what a compression test is read by, and
  time only adds the approach and the hold. Displacement is the position channel
  (*Path*) counted **from where the start load was reached** — the approach
  before it is tens of millimetres at no load and would flatten the loading
  curve into a vertical line. During the approach the plot shows position as it
  stands, so it is not blank while the piston moves.
- **Log**: every non-measurement line heard, both directions, with its meaning;
  a guess ends in `?`, and a line not in the protocol notes is marked `!!`.
- **Message island**: what needs saying now — a ramp whose start is not where
  the piston is (with the speed the controller will really run at), the keypad
  STOP being pressed, an unknown line, a test saved, a port lost.

## Saving

Live, every byte heard is written to `<data>/captures/<start>.jsonl` as it
arrives, and every test the monitor closes is written to
`<data>/tests/test_<START time>.csv` without being asked. A test still open when
the window closes is saved too. A replay writes nothing on its own;
**File → Save newest test as CSV…** saves on request.
