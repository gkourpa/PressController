# Milestone 3b — motion (proposal, awaiting the operator's approval)

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
| Break identification (Servo) | checkbox (off), threshold **10.00 ‰** | off: `#B32`. On: `#B33` then **`#D21<threshold × 10>`** (`#D21100` for 10 ‰) | `#B32` confirmed; the on-path read from Proteus' program, **never recorded** |
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
| Break detection | **on** (operator) | `#B32` / `#B33` |
| Break threshold | 10.00 ‰ | `#D21…` — **only after it is recorded** (see below) |
| Start load | 0.10 % of the force range (4 kN) | `#D09…` |
| Ramp: control | Path | channel `1` / `0` |
| Ramp: speed | 2 mm/min (Path), 2 kN/s (Force) | in the ramp |
| Ramp: end | 100 mm (Path), 100 kN (Force) | in the ramp |
| Ramp: measuring interval | 200 ms | `#D05…` |
| Screen refresh | 2 Hz | nothing (the window's redraw) |

The ramp is also editable in the control window before START, and what is
entered there is remembered.

**The switches are obeyed, never reset.** The Peak and Break detection switches
in the control window show the saved setting when the window opens; flipping one
sends it at once and saves it. START sends what they show — it does not put them
back to a default.

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
| `#D05<n>` | measuring interval 50–1000 ms in 10 ms steps (n = 5–100); 100 ms (`#D0510`) and 200 ms (`#D0520`) are recorded |
| `#D21<n>` | **not yet** — waits for the recording below |

Anything else is refused before a byte is written.

## The break threshold — one recording first

Proteus never had break identification enabled here, so `#B33 #D21…` has never
been on the line. Before this program sends `#D21`, record Proteus doing it:
old PC and tap as before; in the template tick **Break identification (Servo)**
(threshold 10.00 ‰); START without a specimen, Cancel during the approach (as
step 13). Until then, with break detection on, the controller uses whatever
threshold it holds.

## The buttons, state by state

| State | START | CONTINUE | PAUSE | STOP |
| --- | --- | --- | --- | --- |
| connected, idle | **yes** if the ramp is valid | — | — | — |
| approaching | — | — | — | **yes** |
| at the start load (`#B01`) | — | **yes**: `#D05…`, the ramp, `#B22` | — | **yes** |
| ramp running | — | — | **yes** (`#B18`) | **yes** |
| paused | — | **yes** (`#B18` again) | — | **yes** |
| ramp end (`#B02`) | answered automatically: `#B26 #B17` → idle | | | |

- START sends `#B47`, waits for `#O`, then Peak and Break detection as the
  switches show, `#D09…`, `#B23`.
- **STOP is always `#B17`** (Proteus' Cancel: pump off, load released), large,
  red, and also on the **Esc** key. PAUSE is labelled as not a stop.
- START shows the ramp it will send in words ("Path 2 mm/min to 100 mm").
- With break detection on, **the controller itself reacts to the break**. What
  it then sends has never been recorded, so the first break is learnt at the
  press (step 5 below); until it is decoded, any unexplained controller line
  during a test is answered with STOP.

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
5. **A cube to failure, break detection ON**: watch what the controller does
   and sends at the break; the operator ready on STOP.

Each step is recorded and checked against Proteus' recording of the same thing
before the next.

## Not in this milestone

Software break detection of our own (the controller's is used), test templates
as files, specimen data, the validity question, reports, the "next element"
sequence, the Adjustment element, Deformation control.
