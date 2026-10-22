# Control mode

This program talks to the controller itself, in Proteus' place: it connects,
streams, sets Peak and break detection, **runs a test as Proteus does** (START,
CONTINUE, PAUSE, STOP — [motion](motion.md)), and disconnects. Connecting was
run on the press on 2026-10-19 (steps 24, 25); a test from this program has not
been run on the press yet.

## Before a session

1. Leave the old PC as it is; it stays the fallback.
2. Take the controller cable off the Y-cable (or the old PC) and plug it
   **straight into the adapter named by the settings' `control_port`**
   (File → Settings…; the lab: Digitus "A", COM7). The first time it is taken
   from the press file's `[control] port`, or — with none there, as on a new
   PC — picked in Settings, which opens by itself; then it is remembered. The tap is not needed in control mode: the
   program records both directions itself.
3. The press idle, nobody at it.
4. `python -m presscontroller.app --control` (installed: the Start menu's
   **PressController**).

**To go back to Proteus:** close the program (it disconnects first), plug the
controller cable back into the old PC, start Proteus.

## What happens on Connect

| Step | Sent | Waits for | If it does not come |
| --- | --- | --- | --- |
| listen | nothing, 1.5 s | silence | **refused, nothing sent** — something else is talking (the old PC?) |
| 1 | `#B21 #B20` | `#O` | abort |
| 2 | `#B50 #B40` | `#D138.6 #D104000` | abort |
| 3 | `#D020 #B51 #B52 #B41 #B03 #B09 #D0510` | `#D140 #D180` | abort |
| 4 | `#B37` | the first measurement line | abort |
| switches | Peak and break detection, as the switches stand | — | — |

That is Proteus' start-up **byte for byte**, as sent in all eight recorded
sessions, with the waits Proteus made. **Any other answer aborts**: a controller
answering differently is in a state no recording covers. An abort sends stream
off and PC mode off (`#B36 #B21`) and nothing else.

## Every way out hands control back

| Event | Sent |
| --- | --- |
| Disconnect | `#B36 #B21` |
| Closing the window | `#B36 #B21` (if connected) |
| Keypad STOP on the controller (`#B28`) | `#B17 #B36 #B21` — pump off, then out of PC mode, so the keypad works locally at once |
| Abort during connect | `#B36 #B21` |
| The port lost | nothing can be sent; the message says to press STOP on the keypad or power-cycle the controller |

## The allowlist

`presscontroller/control/commands.py`, checked at the one place a byte leaves
(`ControllerLink.send`), before writing:

- **exact lines**: Proteus' start-up, `#B37`/`#B36` (stream), `#B21` (PC mode
  off), `#B30`/`#B31` (Peak), `#B32`/`#B33` (break detection), `#B17` (Cancel:
  pump off), and the test's `#B47` START, `#B23` approach, `#B22` ramp,
  `#B18` PAUSE/CONTINUE, `#B26` answer to the ramp's end;
- **four built lines, each only inside its range**: the ramp `#D12…` (Path or
  Force, within the press file's `[limits]` and the channel's range — without
  `[limits]`, no ramp at all), the start load `#D09…`, the interval `#D05…`, the
  break threshold `#D21…`.

**Never**: what Proteus' program can send but no recording has shown (`#B24`,
`#B34`, `#B38`, `#B60`, `#B04`, `#B11`, `#D160`, `#D161`) and Deformation
control. Tests assert each is refused at the write point.

## A test

See [motion](motion.md) for the sequence, the buttons state by state, and every
way a test ends in Cancel. What START sends comes from the settings (Proteus'
test template: Peak, break detection and threshold, start load, ramp, measuring
interval), edited in File → Settings… and, for the ramp, in the window.

## Recording

In debug mode (Settings → General) a control session is captured like the
tap's, both directions, to `<data>/captures/<start>_control.jsonl`, and replays
in the monitor (`--replay`). Tests are saved to `<data>/tests/` as usual, while
they run (docs/ui.md, Saving).
