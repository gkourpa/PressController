# Development and testing

## Environment

- Windows, Python 3.14, 64-bit, in `.venv`.
- Versions pinned in `requirements.txt`, the same as DAqReader's where shared.
- PySide6 is the GUI toolkit. Plots use pyplot-free `Figure`/`FigureCanvasAgg`
  (pyplot can select QtAgg and deadlock offscreen tests).

Install:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -e .
```

## Commands

```powershell
# The monitor on the live tap
.venv\Scripts\python -m presscontroller.app

# The monitor on a recording, ten times faster than it happened
.venv\Scripts\python -m presscontroller.app --replay captures\20261019_143520_step15_real_test.jsonl --speed 10

# The bench sniffer: raw two-direction capture, baud scan
.venv\Scripts\python tools\sniff.py --list
.venv\Scripts\python tools\sniff.py --pc-port COM7 --ctrl-port COM6 --baud 9600 --lines

# Regenerate the tap's wiring PDF (needs reportlab)
.venv\Scripts\python docs\make_wiring_pdf.py
```

## Tests

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python -m pytest -q
```

No test opens a serial port. The serial tap is tested against simulated ports
that refuse to be written to, and `open_read_only` against a stand-in for
pyserial that records the order DTR, RTS and `open()` were set in. Everything
the monitor decides is tested on real captures in `tests/data`:

| File | What it is |
| --- | --- |
| `real_test_10mm_min.jsonl` | step 15: Proteus start-up, a 150 mm cube to failure (1515.88 kN), the ramp sent with start 0, Stop, Cancel, keypad STOP, shut-down |
| `ramp_6mm_min.jsonl` | step 16: a cancelled START, then a 6 mm/min ramp sent with the real start, stopped at ~570 kN |
| `dryrun_start_cancel.jsonl` | step 13: START without a specimen, Cancel during the approach |

The offscreen platform has no fonts, so text renders as boxes: UI tests check
text and state, never pixels. For a readable offscreen screenshot set
`$env:QT_QPA_FONTDIR = "C:\Windows\Fonts"` and the application font to Segoe UI.

## The tap

Wiring, parts and the checks before connecting to the press are in
[`RS232_Tap_Wiring.pdf`](RS232_Tap_Wiring.pdf). The lab's adapters: **A** (hears
the PC, line pin 3) and **B** (hears the controller, line pin 2), each with its
FTDI latency timer set to 1 ms in Device Manager. Which COM port each is lives in
the press file, never in source.
