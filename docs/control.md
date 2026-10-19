# Control mode

This program talks to the controller itself, in Proteus' place. **This version
moves nothing**: it connects, streams, sets Peak and break detection, and
disconnects.

## Before a session

1. Leave the old PC as it is; it stays the fallback.
2. Take the controller cable off the Y-cable (or the old PC) and plug it
   **straight into the adapter named in the press file's `[control] port`**
   (the lab: Digitus "B", COM6). The tap is not needed in control mode: the
   program records both directions itself.
3. The press idle, nobody at it.
4. `python -m presscontroller.app --control`, and confirm the dialog.

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

`presscontroller/control/commands.py` — exact lines, checked at the one place
a byte leaves (`ControllerLink.send`), before writing:

- Proteus' start-up lines, `#B37`/`#B36` (stream), `#B21` (PC mode off),
- `#B30`/`#B31` (Peak), `#B32`/`#B33` (break detection),
- `#B17` (Cancel: pump off) — for the keypad STOP.

**Not on it**: `#B47`, `#B23`, `#B22`, `#D12…`, `#D0910`, `#D0520`, `#B18`,
`#B26` — everything that moves the press or belongs to moving it. A test asserts
the two sets never meet.

## Recording

A control session is captured like the tap's, both directions, to
`<data>/captures/<start>_control.jsonl`, and replays in the monitor
(`--replay`). Tests the monitor sees are saved to `<data>/tests/` as usual.
