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

# Control mode: this program in charge (old PC unplugged); runs tests
.venv\Scripts\python -m presscontroller.app --control

# The monitor on a recording, ten times faster than it happened
.venv\Scripts\python -m presscontroller.app --replay captures\20261019_143520_step15_real_test.jsonl --speed 10

# The bench sniffer: raw two-direction capture, baud scan
.venv\Scripts\python tools\sniff.py --list
.venv\Scripts\python tools\sniff.py --pc-port COM7 --ctrl-port COM6 --baud 9600 --lines

# Proteus' installation CD (data/proteus_cd, git-ignored), read as data, never run:
# unpack the installer archive, then list the commands proteus.exe sends
.venv\Scripts\python tools\proteus_cd.py unpack data\proteus_cd out\proteus_cd
.venv\Scripts\python tools\proteus_cd.py commands out\proteus_cd\_root\proteus.exe

# Regenerate the tap's wiring PDF (needs reportlab)
.venv\Scripts\python docs\make_wiring_pdf.py
```

## Tests

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python -m pytest -q
```

No test opens a serial port. Control mode is tested against
`tests/controller_fake.py`, a simulated DigiMaxx that answers Proteus' start-up
as the real one did in every recording, streams after `#B37`, keeps PC mode,
Peak and break detection, and can have its keypad STOP pressed; it also runs a
test as steps 21, 23 and 26 show (`#O` to START, `#B01` after the approach,
`#B35`/`#O` to the ramp, `#B18` toggling, `#B02` at the ramp's end, `#B43`
after Cancel). `tests/test_motion.py` compares what control mode sends with what
Proteus sent in those recordings, line for line. The serial tap is tested against simulated ports
that refuse to be written to, and `open_read_only` against a stand-in for
pyserial that records the order DTR, RTS and `open()` were set in. Everything
the monitor decides is tested on real captures in `tests/data`:

| File | What it is |
| --- | --- |
| `real_test_10mm_min.jsonl` | step 15: Proteus start-up, a 150 mm cube to failure (1515.88 kN), the ramp sent with start 0, Stop, Cancel, keypad STOP, shut-down |
| `ramp_6mm_min.jsonl` | step 16: a cancelled START, then a 6 mm/min ramp sent with the real start, stopped at ~570 kN |
| `piston_still_4_min.jsonl` | 2026-10-20: four idle minutes in control mode — the piston still, the Path reading's noise that the piston label must not take for movement |
| `dryrun_start_cancel.jsonl` | step 13: START without a specimen, Cancel during the approach |

The offscreen platform has no fonts, so text renders as boxes: UI tests check
text and state, never pixels. For a readable offscreen screenshot set
`$env:QT_QPA_FONTDIR = "C:\Windows\Fonts"` and the application font to Segoe UI.

## Frozen Windows build and installer

```powershell
.venv\Scripts\python -m pip install pyinstaller==6.22.3   # once; a build tool, not a runtime pin
.venv\Scripts\python tools/build_installer.py
```

runs PyInstaller (`PressController.spec`, onedir, at `dist/PressController/`)
and then Inno Setup 6 (`installer/PressController.iss`; `winget install
JRSoftware.InnoSetup`), producing `dist/installer/PressController-<version>-setup.exe`
— DAqReader's arrangement. The Start menu gets **PressController** (control
mode, `--control`) and **PressController monitor (listen-only)**.

- **Upgrades in place** (fixed AppId) and replaces `_internal` wholesale.
- **Never touches** `%APPDATA%\PressController` (the settings) or the operator's
  press file, captures and tests; **no `*.toml` is packaged**. A new PC needs
  none: the first run writes the lab's press file (no ports) beside the
  settings, and asks for the control port in Settings.
- **Refuses to build from uncommitted changes**, so a setup's number always
  names one commit.

### Versioning

The version is `presscontroller/__init__.py`'s `__version__` and nothing else.
**Every build handed out bumps it first** (edit, commit, then build), so no two
setups of one number differ. 0.1.0 (2026-10-20) is the first installer.

## The tap

Wiring, parts and the checks before connecting to the press are in
[`RS232_Tap_Wiring.pdf`](RS232_Tap_Wiring.pdf). The lab's adapters: **A** (hears
the PC, line pin 3) and **B** (hears the controller, line pin 2), each with its
FTDI latency timer set to 1 ms in Device Manager. Which COM port each is lives in
the press file, never in source.
