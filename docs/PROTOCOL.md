# DigiMaxx C-20 serial protocol — working notes

Reverse-engineered from passive captures of the Proteus PC ↔ controller link.
Status markers: **confirmed** (seen in captures and cross-checked), **hypothesis** (fits the data, not yet proven).

## Line settings

- **9600 baud, 8 data bits, no parity, 1 stop bit** — confirmed (2026-10-16 baud scan: clean ASCII only at 9600).

## Controller → PC: measurement stream

Example (idle, measurement window open, `captures/20261016_idle8s_ctrl2pc.bin`):

```
#D0819630;0;-1246;1;15859;2;-25637<CR><LF>
```

| Part | Meaning | Status |
|---|---|---|
| `#D` | frame type: data | confirmed (only type seen so far) |
| `08` + `19630` | `08` constant so far (status/type?), then time counter without leading zeros, +10 per frame | confirmed: counter reset to `2` at test start (`#D082;…`, `#D08182;…`), unit ≈ 10 ms |
| `;0;-1246` | channel 0 = Force, raw counts | confirmed |
| `;1;15859` | channel 1 = Path, raw counts | confirmed |
| `;2;-25637` | channel 2 = Deformation, raw counts | confirmed |
| `<CR><LF>` | terminator | confirmed |

- Rate: ~9.9 frames/s while idle (79 frames in 8 s), counter +10 per frame → counter ticks every
  ~10 ms (hypothesis: 1/100 s since controller power-on).
- Idle noise: ±7 counts (1 σ) on every channel.
- The PC sent **nothing** while the measurement window was open: the controller streams on its own.
  Streaming may have been enabled by a command at Proteus start-up (not yet captured).

### Scaling (confirmed 2026-10-16)

`value = raw × channel range / 600000`, with ranges from Proteus' channel table and
`DIGIMAXXResolution = 600000`:

| Channel | Range | Idle raw (mean) | Scaled |
|---|---|---|---|
| 0 Force | 4000 kN | −1245.4 | −8.30 kN |
| 1 Path | 100 mm | 15863.4 | 2.644 mm |
| 2 Deformation | 5 mm | −25624.5 | −0.2135 mm |

Cross-check against simultaneous readings (2026-10-16):

| Channel | Controller / Proteus shows | Stream, scaled |
|---|---|---|
| Force | −7.0 kN (drifting −10 → −7) | −6.85 kN (drifting −6.92 → −6.81 over 6 s) |
| Path | +2.642 mm | 2.6428 mm |
| Deformation | −0.214 mm | −0.2136 mm |

Resolution per count: Force 6.67 N, Path 0.167 µm, Deformation 0.0083 µm (display rounds far coarser).

## PC → controller: commands

All messages in both directions are ASCII lines `#<letter><text><CR><LF>`. Hypothesis: `B` = *Befehl*
(command, 2 digits), `D` = data/value, `O` = OK/acknowledge. Controller `#D1…` lines look like single
value replies, `#D0…` lines are the periodic measurement stream.

### Start-up sequence (Proteus start → measurement window), 2026-10-16, `captures/20261016_162921_step10_startup.*`

Times relative to the first command. Controller was silent before it (stream stops when Proteus closes).

| t (ms) | Dir | Line | Notes (hypothesis) |
|---|---|---|---|
| 0 | PC | `#B21` | same as last shut-down command: reset / leave PC mode? |
| 0 | PC | `#B20` | enter PC (remote) mode? |
| 60 | CTRL | `#O` | acknowledge |
| 70 | PC | `#B50` | query? |
| 70 | PC | `#B40` | query? |
| 108 | CTRL | `#D138.6` | reply `38.6` — firmware version? |
| 108 | CTRL | `#D104000` | reply `04000` — **machine capacity 4000 kN?** |
| 136 | PC | `#D020` | set parameter? |
| 136 | PC | `#B51` | query? |
| 136 | PC | `#B52` | query? |
| 155 | CTRL | `#D140` | reply `40` |
| 155 | PC | `#B41` | |
| 161 | CTRL | `#D180` | reply `80` |
| 162 | PC | `#B03` | |
| 168 | PC | `#B09` | |
| 169 | PC | `#D0510` | set parameter? (`05` = 10 → 100 ms interval?) |
| 169 | PC | `#B37` | **start stream** (pairs with `#B36` stop, see shut-down) |
| 353 | CTRL | `#D0870941;0;-886;1;15851;2;-25635` | stream starts, every ~100 ms |

Stream line here: `#D08` + counter `70941`.

### Shut-down sequence (closing Proteus), 2026-10-16, `captures/20261016_163107_step11_shutdown.*`

| t (ms) | Dir | Line | Notes |
|---|---|---|---|
| 0 | CTRL | `#D0880271;…` | last complete stream frame |
| 91 | PC | `#B36` | **stop stream** — stream ends mid-frame right after it |
| 91 | PC | `#B21` | leave PC (remote) mode? (also the first start-up command) |
| 102 | CTRL | `#D0880281;0;-839;1;1` | truncated frame, then silence |
| 102–122 | PC | RTS drops and returns | Windows closing the COM port |

No acknowledgement from the controller to either command.

Start-up repeated identically on 2026-10-16 16:33 (`captures/20261016_163343_step12_buttons.*`):
same 12 commands, same order, same replies → it's a fixed script, not state-dependent.

### Operation buttons (measurement window), `captures/20261016_163343_step12_buttons.*`

Clicked ~10 s apart: Reset, Peak (on), Peak (off), BR (on), BR (off). Four commands seen, none acknowledged,
stream format unchanged:

| t (s) | Line | Button | Notes |
|---|---|---|---|
| — | — | Reset | **nothing sent** → Proteus-only |
| 33.6 | `#B31` | Peak → on (button turns green) | |
| 45.2 | `#B30` | Peak → off | |
| 58.5 | `#B33` | BR → on (button turns green) | BR = break detection (*Bruch*)? |
| 69.6 | `#B32` | BR → off | |

Pattern so far: commands come in pairs, **even = off, odd = on** (`#B30/31` peak, `#B32/33` BR,
`#B36/37` stream).

Confirmed by the controller's own display (see *Controller display indicators*). Button behaviour: the label shows the **next action**, not the
current state.

| Click | Sent | Label afterwards | Right side |
|---|---|---|---|
| (initial) | — | `Peak Off` / `BR off` (design-time caption) | grey |
| 1st | `#B31` / `#B33` (on) | `Peak off` / `BR off` → "click to switch off" | green |
| 2nd | `#B30` / `#B32` (off) | `Peak on` / `BR on` → "click to switch on" | stays green |
| further | toggles | toggles | green |

The green part does not follow the state (probably "used/armed" indicator or a Proteus quirk).
**Proteus does not set Peak/BR at start-up**, so the controller keeps whatever state it had; a
replacement app should send `#B30`/`#B31` and `#B32`/`#B33` explicitly after connecting.

### Test run: START → Cancel (dry run, no specimen), 2026-10-16, `captures/20261016_171547_step13_dryrun_start_cancel.*`

Template "Test universal / Würfel 150×150×150": Start load 0.1 % of range; Ramp = **path control**,
10 mm/min, end 100 mm, measuring interval 200 ms. Only the approach phase was run (no CONTINUE).

| t (s) | Dir | Line | Effect / hypothesis |
|---|---|---|---|
| 9.300 | PC | `#B47` | START clicked — prepare / arm test? |
| 9.307 | CTRL | `#O` | acknowledge |
| 11.018 | PC | `#B30` | Peak off (template sequence) |
| 11.024 | PC | `#B32` | BR off (template sequence) |
| 11.030 | PC | `#D0910` | parameter for approach? (`9` = `10`?) |
| 11.039 | PC | `#B23` | **start approach** — piston starts rising 0.1 s later; stream time counter resets to 2 |
| 11–56 | CTRL | stream | path 2.64 → 20.74 mm at **≈0.40 mm/s (24 mm/min)**, force ≈ −0.3 kN (no contact) |
| 56.180 | PC | `#B17` | **Cancel** — piston stops (overshoot to 20.898 mm max), then sinks slowly ≈0.08 mm/s |
| 76.445 | CTRL | `#B43` | **controller-initiated** message; path holds at 19.387 mm from here on (end of stop/return phase?) |

Max path in the stream 20.898 mm = the maximum Proteus displayed.
Force offset changed at test start (≈ −3.0 kN before, ≈ −0.3 kN while moving) — internal tare or
hydraulic effect, unknown.

### Real test (concrete cube 150 mm), 2026-10-19, `captures/20261019_143520_step15_real_test.*`

Start-up identical for the 3rd time. Then (t = seconds from recording start):

| t (s) | Dir | Line | Effect / hypothesis |
|---|---|---|---|
| 91.74 | PC | `#B47` | START clicked |
| 91.74 | CTRL | `#O` | |
| 93.57 | PC | `#B30` `#B32` `#D0910` `#B23` | same as dry run → approach starts |
| 94–285 | CTRL | stream | approach ≈ 24 mm/min, path 2.67 → 79.2 mm |
| 285.24 | CTRL | `#B01` | **controller-initiated: start load reached** (F = 4.39 kN ≈ 0.1 % of 4000 kN) — piston holds |
| 299.77 | PC | `#D0520` | CONTINUE clicked. **Stream interval → 200 ms** (counter +20/frame). `#D05<n>` = interval n×10 ms (start-up sends `#D0510` = 100 ms) — **confirmed** |
| 299.78 | PC | `#D12167;0;100000;0;1` | **ramp definition** (see below) |
| 299.84 | CTRL | `#B35` | |
| 299.86 | PC | `#B22` | **start ramp** |
| 299.94 | CTRL | `#O` | |
| 300–360 | CTRL | stream | path-linear ramp: **2.06 mm/min** constant; force 11.5 → **1515.88 kN peak at 359.86 s** (force rate rising 4 → 40 kN/s) |
| 360–366 | CTRL | stream | specimen breaks: force falls 1516 → 1055 kN, press keeps pushing (no break detection, BR was switched off at START) |
| 366.65 | PC | `#B18` | **Stop** (traffic light) — piston stops, load held |
| 367.96 | PC | `#B17` | **Cancel** — pump stops, load released (986 → 340 kN in 0.6 s) |
| 388.49 | CTRL | `#B43` | controller-initiated, ~20 s after Cancel (also seen in dry run) — "unloaded / test ended"? |

| 461.85 | CTRL | **`#B28`** | **operator pressed STOP on the controller keypad** ("SINKING" flashes, but the controller does not act — PC mode) |
| 461.91 | PC | `#B36` `#B17` | Proteus reacts: stop stream + Cancel |
| 465.98 | CTRL | `#B28` | 2nd keypad STOP press |
| 465.99 | PC | `#B17` | Proteus sends Cancel again |
| 704.34 | PC | `#B37` | stream on (operator exiting the test) |
| 705.82 | PC | `#B36` `#B21` | Proteus shut-down (same as step 11) → controller leaves PC mode; keypad STOP then sinks the piston locally |

**Keypad STOP in PC mode is forwarded as `#B28` instead of acting locally** — a replacement app
must handle it (at minimum: stop/cancel the test). After `#B21` the keypad works locally again.

#### Ramp command `#D12<speed>;<start>;<end>;0;<channel>` — decoded 2026-10-19

| Test | Template speed | Command | Measured path rate |
|---|---|---|---|
| step 15 (full test) | 10 mm/min | `#D12167;0;100000;0;1` | 2.06 mm/min |
| step 16 (`captures/20261019_150027_step16_ramp_6mm_min.*`) | 6 mm/min | `#D12100;79446;100000;0;1` | ≈ 6 mm/min (6.6 → 5.0 as load rose) |

| Field | Meaning | Status |
|---|---|---|
| `#D12` | ramp command | hypothesis (only form seen) |
| `167` / `100` | **speed in µm/s** (10 mm/min = 166.7, 6 mm/min = 100) | **confirmed** |
| `0` / `79446` | **ramp start position in µm** (79446 = path at CONTINUE, 79.446 mm) | confirmed for step 16 |
| `100000` | **ramp end position in µm** (template End 100.000 mm) | confirmed |
| `0` | ? | unknown |
| `1` | control channel (1 = Path)? | hypothesis |

**Why step 15 ran at 2.06 mm/min:** Proteus sent start = **0**. The controller seems to plan the ramp
duration as (end − start) / speed = (100 − 0) mm / 10 mm/min = 10 min and then covers the *actual*
remaining distance in that time: (100 − 79.45) mm / 10 min = **2.055 mm/min** — matches the measured
2.06 mm/min. In step 16 start = actual position, so the ramp ran at the set speed.
Open: why Proteus sent 0 in step 15. Difference: step 16's CONTINUE came after a cancelled START in
the same Proteus session; step 15 was the first test after start-up. **If Proteus always sends 0 on the
first test after start-up, those tests run slower than the template states** — verify.

#### Step 16 sequence (6 mm/min, stopped before break)

Start-up as always. START (`#B47`…`#B23`), approach, then operator Cancel `#B17` (to clean the
specimen) and keypad STOP `#B28` → Proteus `#B36` `#B17`, controller `#B43`. Second START:
`#B47` `#O` `#B30` `#B32` `#D0910` **`#B37`** `#B23` — Proteus re-enables the stream inside the START
sequence because the keypad STOP had stopped it. `#B01` at 4.01 kN, CONTINUE (`#D0520`, ramp, `#B35`,
`#B22`, `#O`), Stop `#B18` at 565 kN, Cancel `#B17`, controller `#B43` 20 s later, Exit `#B36` `#B21`.

### Exit + controller STOP (return to bottom), 2026-10-16, `captures/20261016_172650_step14_exit_sinking.*`

Operator procedure after a test: exit the test in Proteus, then press **STOP on the controller**
→ display shows **SINKING** and the piston returns down.

- Proteus "Exit" closed the program: `#B36` + `#B21`, identical to the step 11 shut-down.
- Before that, the piston sat at 17.57 mm (had sunk from 19.39 mm since the Cancel).
- Controller STOP pressed **after** Proteus closed: **nothing on the line** — sinking is purely local.
  In PC mode the keypad STOP is forwarded as `#B28` instead (see real test, 2026-10-19).

### Actions that send nothing

- **Reset** (Proteus measurement window), 2026-10-16 step 12.
- **Zero** (Proteus measurement window), 2026-10-16, `captures/20261016_162626_step9_zero.*`: no PC→CTRL bytes;
  raw stream continued unchanged (force −6.3 kN, no jump); controller display unchanged while
  Proteus showed 0.0. → **Zero is a software tare inside Proteus.** A replacement app must do its own
  tare (subtract the raw value at the moment of zeroing).

## Controller display indicators

The DigiMaxx LCD has a status row at the top and bottom. After a controller power-cycle (defaults):

```
top:  4000kN  [  ]  [  ]  M1
bot:  [  ]    ZB    BD    FO    LD
```

Observed changes (user, 2026-10-16):

| Event | Indicator change | Command | Conclusion |
|---|---|---|---|
| Proteus start-up (test template / measurement window) | top: **PC** and **FO** appear | one or more of the 12 start-up commands | PC = remote/PC mode (`#B20`?), FO = force control mode? (keypad has FO/DI/DE/EX) |
| Peak on | bottom: **PK** appears | `#B31` | **confirmed** |
| Peak off | **PK** disappears | `#B30` | **confirmed** |
| BR on | no change (BD already on) | `#B33` | **confirmed** — break detection on by default |
| BR off | **BD** disappears | `#B32` | **confirmed** |

Defaults after power-up: Peak **off**, break detection (BD) **on**. Meaning of ZB, bottom FO, LD unknown.

## Handshake lines

- PC RTS (line pin 7) is **asserted** while Proteus runs.
- Controller CTS output (line pin 8) reads **not asserted** — the controller doesn't seem to use
  hardware flow control (or doesn't drive the line).

## Open questions

- Which start-up command makes **PC** / **FO** appear on the controller display.
- Meaning of display indicators ZB, (bottom) FO, LD.
- What each start-up command means (`#B20/21`, `#B40/41`, `#B50/51/52`, `#B03`, `#B09`, `#D020`, `#D0510`).
- Why Proteus sent ramp start = 0 in step 15 (first test after start-up?).
- Ramp field 4 (`0`) and whether field 5 changes with Force/Deformation control.
- Whether break detection (`#B33`) is ever enabled by a template, and what the controller sends on break.
- Whether other keypad keys (START, ZERO, PEAK…) are forwarded like STOP (`#B28`) in PC mode.
- Meaning of `#B47`, `#D0910`, controller `#B35`, `#B43`; what the `8` after `#D0` is.
- What Peak and BR change inside the controller (stream looks the same).
- Whether channel 3 (External, 250 kN) appears when active.
