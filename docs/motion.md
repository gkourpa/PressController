# Milestone 3b — motion (first run on the press 2026-10-20, step 27)

The control window gets **START / PAUSE / CONTINUE / STOP**, and sends exactly
what Proteus sends for the same buttons. What Proteus keeps in its test template
becomes this program's **settings**: saved in a TOML file and edited in a
settings dialog, as in DAqReader.

## What Proteus sends (steps 15–23, every recording the same)

| Moment | Proteus sends | Controller answers |
| --- | --- | --- |
| START | `#B47` | `#O` |
| ~1.5 s later | `#B30` `#B32` `#D0910` `#B23` (Peak off, break detection off, start load, approach) | — |
| piston touches the specimen | — | `#B01` (start load reached; seen at 3–4 kN every time) |
| CONTINUE | `#D0520` `#D12<speed>;<start>;<end>;0;<channel>` | `#B35` |
| | `#B22` (start the ramp) | `#O` |
| Stop / Continue | `#B18` (toggles) | — |
| ramp end reached | `#B26` `#B17` (answer) | `#B02` (first) |
| Cancel | `#B17` | `#B43` ~20 s later |

## Proteus' test template, element by element (operator's video, 2026-10-20)

The lab's template ("Test universal / No standard / Würfel 150×150×150") is a
sequence of elements. Each one, what it holds, and what it sends:

| Element | Setting (lab's value) | Sends | Status |
| --- | --- | --- | --- |
| Peak | checkbox (off) | `#B30` off / `#B31` on, at START | confirmed — the recordings send `#B30` |
| Break identification (Servo) | checkbox (off), threshold **10.00 ‰** | off: `#B32`. On: `#B33` then **`#D21<threshold × 10>`** | **confirmed** (step 26: 10 ‰ → `#D21100`, 25 ‰ → `#D21250`) |
| Start | start load **0.1000 % of range** | **`#D09<start load × 100>`**: `#D0910` = 0.10 % of 4000 kN = 4 kN | matches `#B01` at 3–4 kN in every test |
| Adjustment | "Automatic" (off) | nothing seen (zeroing an extensometer) | — |
| The test is successful | "Validity inquiry" (on) | nothing: a question Proteus asks the operator after the test | software only |
| Ramp | control, end, speed, **measuring interval 200 ms** | `#D05<interval ÷ 10 ms>` then the ramp: `#D0520` = 200 ms | **confirmed**: the stream goes from 100 to 200 ms when the ramp starts (step 23) |
| End test | "Keep measuring" (on) | nothing: the readings go on after the test | software only |

## Settings (saved, with a settings dialog)

`%APPDATA%\PressController\settings.toml`, as in DAqReader; a **Settings…**
dialog edits it; every value is checked when read and when entered.

| Setting | Default | Sent as |
| --- | --- | --- |
| Peak | off | `#B30` / `#B31` |
| Break threshold | 10.0 ‰ | `#D21…`, right after `#B33` |
| Start load | 0.10 % of the force range (4 kN) | `#D09…` |
| Program: the steps | one Path ramp, 2 mm/min to 100 mm, break detection **on** (operator) | below, "Programs" |
| Program: measuring interval | 200 ms | `#D05…` before every ramp |
| Measuring interval before the program | 100 ms (the start-up's) | `#D05…` after Connect and after each test, only when not already in force — ours, not Proteus' (below) |
| Screen refresh | 2 Hz | nothing (the window's redraw) |

The program is edited in the control window's **Program → Edit** (docs/ui.md,
"The program") and saved there; the rest in Settings → Test.

**The interval before the ramp** (operator, 2026-10-22). Proteus sets 100 ms at
start-up and the ramp's interval at CONTINUE, and **never sets it back**: after a
test the stream stays at the ramp's rate, and in step 16 its next approach ran at
200 ms (every Proteus recording checked). This program sends the setting's
`#D05…` once connected if it is not the start-up's 100 ms, and **after every
test whose ramp had started** — right after the test's last `#B17` — so idle and
the next approach always run at the chosen rate. That position after `#B17` is
ours alone; the line is one the controller has taken both idle (start-up) and in
a test (CONTINUE). To be checked at the press: after a test, the stream's
counter steps by 10 again (100 ms).

**Peak is obeyed, never reset.** The Peak switch in the control window shows
the saved setting when the window opens; flipping it sends it at once and saves
it. START sends what it shows. **Break detection is the program's** (below):
connecting sends it off, and every START sends it as the program starts — the
controller keeps its last state across tests and Proteus restarts (step 37).

## Programs (steps 35–38, 2026-11-09)

A program is any list of **ramps** and **holds**, starting with a ramp. Each
ramp has its own control (step 41: Path and Force in one Proteus test):
**Force** to an end force at a rate, up or down from where the step before
ended; **Path** at a rate, *to* a position or *by* a signed distance — counted
as Proteus counts its template's "+2 mm": from the previous ramp's set end when
that was a Path ramp, else from the piston as the ramp is sent (steps 39–41), so
that ramp's line is built then. A hold is a time at the force or position
reached. Learnt from Proteus' recordings (docs/PROTOCOL.md, steps 35–41) and
planned by `control/program.py` before START sends a byte:

| Moment | This program sends | As Proteus (step 38) |
| --- | --- | --- |
| START, on `#O` | Peak, then `#B33 #D21…` if step 1 has break detection on, else `#B32`; `#D09…`, `#B23` | `#B30 #B32 #D091 #B23` |
| CONTINUE at the start load | step 1 | |
| a ramp | `#D05…` `#D12…`; on `#B35`, `#B22` | `#D0510 #D122000;0;200000;0;0 #B22` |
| the ramp that switches break detection on | `#B33 #D21…` first, in the same burst | `#B33 #D21100 #D0510 #D124000;0;250000;0;0` |
| a ramp's end (`#B02`), not the last step | `#B26` alone: the controller holds the force; the next step | `#B26` |
| a hold | nothing; the program times it, then the next step | 10.0 s, then the next ramp |
| the last step's end | `#B26 #B17` (a ramp) or `#B17` (a hold) | `#B26 #B17` |

`#B02` is the ramp's *target* reaching its end, not the reading (step 40): on a
specimen the press cannot follow, a ramp "ends" short of it.

**Break detection** is a ramp's "on from here", and stays on to the end:
switching it off mid-test (`#B32` during a test) was never recorded. It trips on
a fall of threshold × force range from the peak since `#B33` (39.9 kN at 10 ‰,
steps 35 and 37), so a ramp down by that much after it is refused before START,
with the step and the reason; after a Path step the force is not known, so a
Force ramp down there is not checked, and a **Path ramp down with break
detection on is refused** (its load fell 123 kN in step 41). PAUSE is off during
a hold (`#B18` in a hold was never recorded); STOP is `#B17` in every step. A
Path ramp "by" a distance whose end falls outside the channel's range is found
only when it is sent: the test is stopped then (Cancel).

## What this program will send

**Fixed lines added to the allowlist:** `#B47`, `#B23`, `#B22`, `#B18`, `#B26`
(`#B17` is already there). Nothing else from Proteus' program:
`#B24 #B34 #B38 #B60 #D160 #D161` stay off.

**Lines built from settings — one function each, checked again at the write
point:**

| Line | Allowed |
| --- | --- |
| `#D12<speed>;0;<end>;0;<channel>` | channel `1` (Path) or `0` (Force), never Deformation; speed above 0 and **at most the press file's `[limits]`** (10 mm/min, 15 kN/s); end above 0 and within the channel's range; start always `0` (it does not change the speed — steps 17–19) |
| `#D09<n>` | start load 0.01–1.00 % of the force range (n = 1–100); 0.10 % = Proteus' |
| `#D05<n>` | measuring interval 100–500 ms in 10 ms steps (n = 10–50); 100 ms (`#D0510`) and 200 ms (`#D0520`) are recorded. Narrowed from 50–1000 ms on 2026-10-22 (operator): faster than 100 ms was never seen (one stream line takes ~39 ms at 9600 baud), and 500 ms still leaves three lines inside the 1.5 s a test may go without one |
| `#D21<n>` | break threshold 1.0–100.0 ‰ in 0.1 ‰ steps (n = 10–1000), sent only right after `#B33`; 10 ‰ and 25 ‰ are recorded |

Anything else is refused before a byte is written.

## The buttons, state by state

| State | START | CONTINUE | PAUSE | STOP |
| --- | --- | --- | --- | --- |
| connected, idle | **yes** if every step of the program is valid | — | — | — |
| approaching | — | — | — | **yes** |
| at the start load (`#B01`) | — | **yes**: the program's first step | — | **yes** |
| ramp running | — | — | **yes** (`#B18`) | **yes** |
| paused | — | **yes** (`#B18` again) | — | **yes** |
| hold | — | — | — | **yes** |
| ramp end (`#B02`) | answered automatically: `#B26` and the next step, or `#B26 #B17` → idle | | | |

- START sends `#B47`, waits for `#O`, then Peak as the switch shows, break
  detection as the program starts (`#B33` followed by `#D21…`, or `#B32`),
  `#D09…`, `#B23` — Proteus' order (step 26).
- **STOP is always `#B17`** (Proteus' Cancel: pump off, load released), large,
  red, and also on the **Esc** key. PAUSE is not a stop; the message line says
  so when it is pressed (the button itself just reads PAUSE — operator,
  2026-10-20).
- START shows the program in words ("Path 2 mm/min to 100 mm · break detection
  on"; "5 steps (3 ramps, 2 holds) · about 3 min 27 s · break detection
  from step 5").
- With break detection on, **the controller reports a break as `#B27`**
  (confirmed at a cube's failure, step 32) — and then **holds the load**: Cancel
  stops the pump but does not release it. The keypad STOP releases it once PC
  mode is off. On `#B27` the session sends `#B17` and **stays connected**; the
  message, in red, says to press STOP: that second Cancel releases the load and
  the piston sinks, and a third stops the sinking (step 33; kept manual,
  operator 2026-10-20). If the load does not come off, Disconnect and the
  keypad STOP.
  Any other controller line no recording explains is answered with STOP.

## When something goes wrong — every case ends in `#B17`

| Event | Sent | Then |
| --- | --- | --- |
| keypad STOP on the controller (`#B28`) | `#B17 #B36 #B21` | keypad in charge (as now) |
| no `#O` after `#B47`, no `#B35`/`#O` after the ramp (1 s) | `#B17` | idle, message |
| a controller line no recording explains, during a test | `#B17` | idle, the line shown (it may be what the controller says on a break) |
| the readings stop for 1.5 s during a test | `#B17` | message: press STOP on the keypad |
| Disconnect or closing the window during a test | `#B17 #B36 #B21` | — |
| the port lost | nothing can be sent | message: press STOP on the keypad |

The controller's own STOP and the press's emergency stop stay the primary
safety devices.

## Tests before the press

The simulated controller learns the test: `#O` after `#B47`, `#B01` after the
approach, `#B35`/`#O` for the ramp, `#B02` at the ramp's end, `#B18` toggling.
Tests for: every button in every state; the exact bytes against steps 21 and 23;
each built line refused outside its range with nothing written; each failure row
above ending in `#B17`; settings round-trip and bad values named; the monitor
following our own test as it follows Proteus'.

## First run at the press — one step at a time, operator's hand on the keypad STOP

1. **Dry START without a specimen**, STOP during the approach (as step 13).
2. **A cube, Path 2 mm/min**: START → start load → CONTINUE → PAUSE → CONTINUE
   → STOP at about 300 kN.
3. **A cube, Force 2 kN/s to 100 kN**: the ramp ends by itself; the program
   answers `#B02` with `#B26 #B17` (as step 21).
4. **Keypad STOP** during a ramp → pump off, keypad in charge.
Steps 1–4 done on 2026-10-20 (steps 27–31 in docs/PROTOCOL.md).
Next session (0.1.1): after any test that reached the ramp, the recording shows
`#D0510` after the last `#B17` and the stream back at 100 ms.

5. **A cube to failure, break detection ON**: done (step 32) — peak 1908.9 kN,
   `#B27` at the break; the load stayed held after Cancel until PC mode was off
   and the keypad STOP pressed. Handled since as above.
6. **The next cube, break detection ON**: done (step 33) — the program's STOP,
   a second Cancel 10 s after the first, released the load at once.

Each step is recorded and checked against Proteus' recording of the same thing
before the next.

## Later: more of Proteus' elements

Proteus' template can hold more elements than the lab's: Break identification
(PC), Cycle start, Holding time, UNLOAD, Limit, Wait, Digischmidt, ramp for
calibration, relais, Data transfer. The operator chose **UNLOAD** and **Cycle
start** to add later (2026-10-20), each after its own Proteus recording, as the
break threshold was learnt (step 26). Nothing is sent for an element before a
recording shows its lines. Load cycles are now programs (above).

**Load cycles (EN 12390-13), first recordings 2026-11-09** (steps 35, 36 in
docs/PROTOCOL.md): a ramp up, a hold, a ramp down and a hold need no new line.
A ramp down is `#D12…` with an end below the force; every ramp end is `#B02`,
answered `#B26` alone to hold; the program times the hold, then sends the next
ramp as CONTINUE does; `#B26 #B17` only at the last. Break detection must be off
while unloading by more than its threshold (40 kN at 10 ‰ tripped it, step 35);
switched on before the last ramp, it counts from then (step 36). The controller
keeps its last state across tests, so START must send `#B32` explicitly (step 37).
Step 38 ran the whole cycle so, to 250 kN, without a false break.

## Not in this milestone

Software break detection of our own (the controller's is used), test templates
as files, specimen data, the validity question, reports, the "next element"
sequence, the Adjustment element, Deformation control.
