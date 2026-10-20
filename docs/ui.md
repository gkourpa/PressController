# The window

Run with `python -m presscontroller.app` (or `python run_app.py`). The first
launch asks for the press file and the data folder; both are remembered.
`--replay CAPTURE.jsonl [--speed N]` plays a recording instead of listening.

## Listen-only

The monitor has **no control that sends anything to the press**: no Start, no
Stop, no Zero. Proteus stays in control. The message island says so, and names
the source — the two ports, or the capture being replayed — so a replay is never
mistaken for the press.

## Redraw rate

Everything on screen — readings, status, plot, log — is redrawn **at most twice
a second** (operator, 2026-10-19): the stream is ten lines a second, and a number
changing faster than it can be read is worse than one that does not. The newest
data always wins and a trailing redraw is guaranteed. Taking in data, the
capture and the saved tests do not wait for the screen; a message (a warning, a
lost port) is shown at once. The ceiling is the window's `refresh_hz`, 2 Hz, and
becomes a global setting as DAqReader's `refresh_hz` is.

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
- **Message island**: what needs saying now — a ramp sent faster than the press
  file's `[limits]` (said the moment it is sent), a ramp running more than 20 % off
  its set speed, the keypad STOP being pressed, an unknown line, a test saved, a
  port lost.

## The ramp's speed is measured, not predicted

The status card shows the speed that was set and the speed the press is really
running at: a least-squares fit of position against time over every ramp sample
so far on the ramp's own clock — paused time is not counted — leaving out the
ramp's first 3 s, where the servo takes up the load and
force can jump 8 kN (step 21) (operator, 2026-10-19). After 10 s of ramp the two are compared once, and
a difference over 20 % is said out loud. It used to be *predicted* from the
ramp's start field, a model that fitted one test and was contradicted by the
next ([protocol notes](PROTOCOL.md)); a measurement is right whatever the
explanation turns out to be.

A **path** ramp is set and measured in mm/min (position against time), a
**force** ramp in kN/s (force against time), each against its own channel, and
both are judged the same way. A force ramp's line also shows the path's rate.
A ramp on a channel whose units are not confirmed yet (deformation) shows its raw
fields and is not judged — comparing a number in an unknown unit would be a false
alarm.

The **start position** the ramp was sent with is shown beside where the piston
really was, as a **plain note, not a warning** (operator, 2026-10-19). Proteus
sends odd starts — 0, 1 and 2 times the piston position — and ramps with a wrong
start ran at their set speed, so warning on every one alarmed the operator about
nothing and would have taught them to ignore the one warning that matters.

## Saving

Live, every byte heard is written to `<data>/captures/<start>.jsonl` as it
arrives, and every test the monitor closes is written to
`<data>/tests/test_<START time>.csv` without being asked. A test still open when
the window closes is saved too. A replay writes nothing on its own;
**File → Save newest test as CSV…** saves on request.

## The control window

`python -m presscontroller.app --control`, with the old PC unplugged from the
controller and the controller cable plugged into the settings' `control_port`.
Every launch asks that to be confirmed first. The window is the monitor's, with
two bars on top. The connection bar:

- **Controller: …** — the session's state (not connected, checking the line is
  free, connecting, connected in PC mode, refused or aborted).
- **Break detection** and **Peak** — on/off **switches** with the state in words
  (operator, 2026-10-19: "a switch, easy for everyone to understand"). The
  controller does not report either, so the program *sets* them to the switches'
  positions as it connects, at START and on every flip; a switch never shows a
  guess. **They are obeyed, never reset** (operator, 2026-10-20): they open at
  the saved settings (break detection on, Peak off by default) and a flip is
  saved. A switch flipped while not connected is applied on connecting; during a
  test they are locked.
- **Connect** / **Disconnect**.

The test bar: the test's phase; **Piston: going down / still / going up** with
its rate, large, from the Path readings of the last 2 s — after a STOP the
operator must see whether the piston has started sinking (operator,
2026-10-20); the ramp — control (Path or Force), speed, end,
and the press file's limit beside it (an edit is saved as the settings' ramp);
and the buttons, named as the operator asked (2026-10-19):

| Button | Sends | Notes |
| --- | --- | --- |
| **START** | `#B47`; on `#O`: Peak and break detection as the switches stand (`#B33` then the threshold `#D21…`), the start load `#D09…`, `#B23` | approach to the start load; off when the ramp is outside the limits, with the reason shown |
| **CONTINUE** (after the start load) | the interval `#D05…`, the ramp `#D12…`; on `#B35`: `#B22` | the test itself |
| **PAUSE** / **CONTINUE** (during the ramp) | `#B18` | one toggling command; freezes the ramp's target |
| **STOP** | `#B17` | Proteus' "Cancel": pump off, load released. The real stop |

**PAUSE is not a safety stop**: it freezes the ramp's target, so a piston that
lags its target keeps going (step 22). STOP is Cancel: red, on the **Esc** key,
available whenever connected. Like the keypad's STOP it can be pressed again:
after a break the first press stops the pump, the next releases the load and the
piston sinks, the next stops the sinking (step 33).

**Settings…** (File menu, both windows, as DAqReader's): the screen's redraw
ceiling, control mode's port, and the test — Proteus' template: Peak, break
detection and its threshold, the start load, the ramp (Path and Force speed and
end) and its measuring interval. Saved to the global settings file only on OK;
locked during a test.

## The window's frame (operator, 2026-10-20)

- **Fixed heights, so nothing moves while a test runs**: the status card's ramp
  line is always four lines, the log under the plot three (no splitter), the
  message line one.
- **Title**: the program and the press; the monitor adds "monitor
  (listen-only)", control mode nothing.
- **It opens as it was left**: size, position, maximized or **full screen**
  (View → Full screen, F11), saved to the settings when the window closes.
- **Settings…** has four tabs: **General** (theme — system, light, dark — and
  the redraw ceiling), **Connection** (control mode's port; **connect by itself**
  when control mode opens), **Test** (Proteus' template), **Plot** (each axis
  fitted or a fixed range, and the curve's colour, as DAqReader's plots; also
  View → Plot settings…).
- Control mode no longer asks for confirmation at every launch; Connect still
  listens first and refuses a busy line.
