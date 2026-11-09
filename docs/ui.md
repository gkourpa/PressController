# The window

Run with `python -m presscontroller.app` (or `python run_app.py`). **The first
launch asks for no file** (operator, 2026-10-20 — the press PC has none of
ours): it writes the lab's press file beside the settings
(`%APPDATA%\PressController\press.toml`, ports blank; it is never overwritten),
keeps captures and tests in `C:\Users\<user>\Documents\PressController`, and
in control mode opens Settings at Connection to pick the port. All three are
remembered; Settings → General shows the press file and changes the data folder
(from the next start). The listen-only monitor's live tap needs the press
file's `[tap]` ports, and says so if they are blank.

**Two files, on purpose** (operator, 2026-10-20): `settings.toml` is this PC's
and operator's choices, rewritten whole on every OK and every close;
`press.toml` is the press — ranges, resolution, the ramp limits — read only,
so no dialog can lose or change a limit.
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
  interval, the test's phase (a hold too: `#B26` alone), the test (number,
  START time, running or why it ended), the newest ramp that was sent, and the
  live path and force rates.
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

Every test is saved to `<data>/tests/test_<START time>.csv` without being
asked (with a `step` column: each ramp and hold of a program counted as heard), **streamed while it runs** (operator, 2026-10-22): the file opens with the
test's first measurement, its `#` head (the press, START, the resolution and
each channel's range) first, and **every measurement adds a row at once**, so
a crash or a power cut loses nothing already heard. The file is held open
while the test runs; another program (Excel) can still open it to read. When
the test closes — the load released (`#B43`), the next START, PC mode off, or
the window closing — the `#` summary goes **at the end**: each ramp sent and
where the piston was, its measured rate, the peak, the warnings, and
`closed: <why>`. A file without that last line never finished being written.
If the file cannot be written while the test runs, that is said once and the
whole test is written when it closes (to a new file, `_2`, if one is there).

**The session recording** — every byte, both directions, to
`<data>/captures/<start>.jsonl` (`<start>_control.jsonl` in control mode) — is
kept **only in debug mode** (Settings → General; off unless chosen, from the
next start). It is what the protocol was learnt from, and what to switch on for
a session whose line is to be checked. A replay writes nothing on its own;
**File → Save newest test as CSV…** saves on request.

## The control window

`python -m presscontroller.app --control`, with the old PC unplugged from the
controller and the controller cable plugged into the settings' `control_port`.
Every launch asks that to be confirmed first. The window is the monitor's, with
two bars on top. The connection bar:

- **Controller: …** — the session's state (not connected, checking the line is
  free, connecting, connected in PC mode, refused or aborted).
- **Break detection: …** — what the program sets, in words, with a note under
  it: OFF, ON (for the whole test), or "from step 5 — off until step 5, then
  on: an unload would read as a break". Not a switch: it belongs to the
  program (Program → Edit, below). Connecting sends it off; START sends it as the
  program starts.
- **Peak** — an on/off **switch** with the state in words (operator,
  2026-10-19: "a switch, easy for everyone to understand"). The controller does
  not report it, so the program *sets* it as it connects, at START and on every
  flip. **Obeyed, never reset** (operator, 2026-10-20): it opens at the saved
  setting (off by default) and a flip is saved. Flipped while not connected it
  is applied on connecting; during a test it is locked.
- **Connect** / **Disconnect**.

The test bar, one row as the operator drew it (2026-11-09): the test's phase
or step, and under it **Piston: going down / still / going up** with its rate,
large, from a line fitted to the Path readings of the last 5 s — after a STOP
the operator must see whether the piston has started sinking (operator,
2026-10-20). "Still" is under 0.6 mm/min at rest (a resting piston drifts up to
±0.43 for a second or two), but under 0.1 mm/min while a test runs: under a
Force ramp on concrete the piston moves only 0.4–0.7 mm/min, and it read
"still"; in a hold it may creep (operator, 2026-11-09); **the
program drawn**, with **Edit** in its bottom-right corner; **Program**, the
program in words a line each; and the buttons, at the top of the bar and
named as the operator asked (2026-10-19):

| Button | Sends | Notes |
| --- | --- | --- |
| **START** | `#B47`; on `#O`: Peak as the switch stands, break detection as the program starts (`#B33` then the threshold `#D21…`, or `#B32`), the start load `#D09…`, `#B23` | approach to the start load; off when a step of the program cannot run, with the reason shown |
| **CONTINUE** (after the start load) | the program's first step: the interval `#D05…`, the ramp `#D12…`; on `#B35`: `#B22` | the test itself; the steps after it follow by themselves |
| **PAUSE** / **CONTINUE** (during a ramp) | `#B18` | one toggling command; freezes the ramp's target; off during a hold |
| **STOP** | `#B17` | Proteus' "Cancel": pump off, load released. The real stop |

**The program drawn**, in a frame: force against time as planned (one block
per step when a Path step is in it), the steps under break detection shaded;
while a test runs, the part done is filled in and a line marks now. The test's
line says the step: "Step 8 of 15 — hold at 200 kN, 6 s left".

### The program (operator, 2026-11-09)

**Edit** opens the program as a list of steps the operator builds
("a dynamic list of steps where they should be able to add/remove steps"):

- Each **ramp** has its own control: **Force** "to [ ] kN at [ ] kN/s", the
  arrow saying up or down from where the step before ended, or **Path** "to
  [ ] mm" (a position) or "by [ ] mm" (a signed distance, counted as Proteus
  counts it) "at [ ] mm/min". A **hold** is "[ ] s" at the force or position
  reached. The measuring interval is the program's too.
- Each row: **↑ ↓** move it, **Copy** duplicates it, **✕** removes it (not the
  last). **+ Ramp** and **+ Hold** add steps. A line separates the rows
  (operator, 2026-11-09).
- **Break detection** is a ramp's "on from here"; every step after it shows "on
  (stays on)".
- Under a row, in red, **what stops it** — the same check START makes
  (`control/program.py`): a rate above `[limits]`, an end outside the range or
  below the start load, a ramp that would not move, an unload break detection
  would read as a break, a program not starting with a ramp. **OK is off while
  anything is red.** The lines a step sends are not shown (operator,
  2026-11-09); the log shows them as they go.
- The preview at the top, framed as in the control window, is the planned force
  against time — or, once a
  Path step is in it, one block per step (`P+2`, `10 s`, `F↑50`), as wide as
  its planned time.

**PAUSE is not a safety stop**: it freezes the ramp's target, so a piston that
lags its target keeps going (step 22). STOP is Cancel: red, on the **Esc** key,
available whenever connected. Like the keypad's STOP it can be pressed again:
after a break the first press stops the pump, the next releases the load and the
piston sinks, the next stops the sinking (step 33).

**Settings…** (File menu, both windows, as DAqReader's): the screen's redraw
ceiling, control mode's port, and the test — what Proteus' template held besides
the program: Peak, the break threshold, the start load, and the measuring
interval before the program (100–500 ms). Saved to the global settings file only
on OK; locked during a test.

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
