# PressController

Talking to the lab's FORM+TEST 4000 kN compression press — a DigiMaxx C-20
controller — without Proteus.

The controller's protocol has been learnt by listening to Proteus through a
passive RS-232 tap ([notes](docs/PROTOCOL.md), [wiring](docs/RS232_Tap_Wiring.pdf)).
The first program built on it is a **listen-only monitor**: it shows the live
force, path and deformation, the test's phase and ramp, the peak, a
force–displacement plot and every command heard, and saves each test as a CSV — while
Proteus still runs the press.

```powershell
py -3.14 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install -e .
.venv\Scripts\python -m presscontroller.app
```

Start here if you are changing the code: [AGENTS.md](AGENTS.md).
