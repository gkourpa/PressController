# Project overview

## Scope

Replace Proteus, the Windows 9x program that drives the lab's FORM+TEST 4000 kN
compression press through its DigiMaxx C-20 controller, with a modern program
that speaks the controller's protocol directly. The controller is discontinued
and undocumented, so the protocol is learnt from the live link first.

## Decisions

| Decision | Choice |
| --- | --- |
| How the protocol is learnt | A passive RS-232 tap on the live link: a straight Y-cable at the PC end and two FTDI adapters, each hearing one direction through its RX pin only ([wiring](RS232_Tap_Wiring.pdf)) |
| Where it is written down | [`PROTOCOL.md`](PROTOCOL.md), every finding with the capture it came from and whether it is confirmed |
| Order of work | Listen-only monitor first, so the decoding is tested on real tests with zero risk; sending only afterwards, confirmed commands only |
| Stack | DAqReader's: Python 3.14, PySide6, matplotlib rendered off-screen (pyplot-free Agg), numpy, pyserial, pytest |
| Configuration | One press file (TOML) for the installation's ports, resolution and channel ranges; global settings in `%APPDATA%\PressController` |
| Redraw rate | At most 2 Hz for everything on screen, as DAqReader's default; to become a global setting as there. Data intake is not limited |
| Records | Live, every byte heard goes to a capture (`<data>/captures/*.jsonl`, the sniffer's format) and every test to one CSV (`<data>/tests/`) |
| Python | 3.14 |

## Milestones

1. **Learn the protocol by listening.** Done for a complete test
   ([protocol notes](PROTOCOL.md)): line settings, the measurement stream and its
   scaling, start-up and shut-down, START/approach, start load, the ramp and its
   encoding, Stop, Cancel, Peak, break detection, the keypad STOP.
2. **Listen-only monitor.** Written and tested on real captures (version 0.0.1):
   live readings, test phase, ramp decoding, peak, a force–displacement plot,
   the log, a capture and a CSV per test, and the ramp's measured speed beside
   the set one with a warning when they differ. First run live on 2026-10-19
   (step 17).
3. **Run a test without Proteus.** Send the confirmed commands, in a supervised
   session, with the controller's STOP and the emergency stop at hand.
4. A test editor, results and reports to replace what operators use in Proteus.
5. Frozen Windows build and installer, as DAqReader's.

## Open questions

- What the controller does when a ramp reaches its end on its own (being
  recorded, step 21).
- What Proteus puts in the ramp's start field (0, 1 and 2 times the piston
  position); it does not set the speed (steps 17–19).

## Accepted unknowns

Decided not to pursue (operator, 2026-10-19):

- **The start-up commands not yet explained** (`#B03`, `#B09`, `#B40/41`,
  `#B50–52`, `#D020`). Proteus sends them identically every time, so they are
  replayed as they are.
- **Why step 15's 10 mm/min path ramp ran at 2.06 mm/min.** Proteus sent the
  same bytes as in step 19, which ran correctly. The monitor measures every ramp
  and warns when one is more than 20 % off, so a recurrence is caught.

## Out of scope

- **Deformation control** (channel 2): the lab will not use it (operator,
  2026-10-19). Its ramps stay undecoded and are shown as raw numbers.
