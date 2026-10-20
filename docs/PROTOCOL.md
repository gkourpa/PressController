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

#### Ramp command `#D12<speed>;<start>;<end>;0;<channel>` — decoded 2026-10-19 (path), step 20 (force)

**All numbers are thousandths of the controlled channel's unit**, and the last field is the controlled
channel, numbered as in the stream: µm/s and µm on Path (channel 1), N/s and N on Force (channel 0).

| Test | Template speed | Command | Measured path rate |
|---|---|---|---|
| step 15 (full test) | 10 mm/min | `#D12167;0;100000;0;1` | 2.06 mm/min |
| step 16 (`captures/20261019_150027_step16_ramp_6mm_min.*`) | 6 mm/min | `#D12100;79446;100000;0;1` | ≈ 6 mm/min (6.6 → 5.0 as load rose) |

| Field | Meaning | Status |
|---|---|---|
| `#D12` | ramp command | confirmed for path and force (same form) |
| speed | thousandths of the channel unit per second: **µm/s** (167 = 10 mm/min, 100 = 6, 50 = 3, 17 = 1) and **N/s** (5000 = 5 kN/s, ran at 5.03) | **confirmed** |
| start | thousandths of the channel unit; what Proteus puts here is not understood and it does not set the speed (below) | unit only |
| end | thousandths of the channel unit: 100000 = 100.000 mm, 300000 = 300 kN (template End) | **confirmed** |
| `0` | ? | unknown |
| channel | the controlled channel, as numbered in the stream: **1 = Path, 0 = Force** | **confirmed** (step 20) |

**Step 17** (first live run of the monitor, `captures/20261019_155241_step17_live_monitor_3mm_min.jsonl`,
template 3 mm/min): `#D1250;159202;100000;0;1` — speed 50 µm/s = 3 mm/min, but start **159.202 mm =
exactly 2 × the piston position (79.6005 mm)**, past the end. The press ran at the set **3.0 mm/min**
(measured 2.7–3.1 mm/min over the ramp). Start-up of this Proteus session was in the previous capture;
this was its first test.

| Test | Start sent / piston position | Ran at / set |
|---|---|---|
| step 15 | 0× (0 mm) | 2.06 / 10 mm/min |
| step 16 | 1× | 6 / 6 mm/min |
| step 17 | 2× | 3.0 / 3 mm/min |
| step 18 | 0× (0 mm) | **1.016 / 1 mm/min** |

**Step 18** (`captures/20261019_160140_step18_live_monitor_1mm_min.jsonl`, first test after
Proteus start-up, template 1 mm/min): `#D1217;0;100000;0;1` — start **0** again, as in step 15, yet
the press ran at the **set speed** (1.016 mm/min measured over 56 s). So the start field does not
explain step 15's slow ramp either way; it seems to be ignored or harmless. **Step 15 remains the only
ramp that ran slow** (2.06 / 10 mm/min, from its first second and at 11 kN, so not a pump limit under
load). Open: whether the press can run a 10 mm/min path ramp at all — repeat at 10 mm/min.
Step 18 also had three Stop presses (`#B18` ×3) before Cancel.

**Step 19** (`captures/20261019_161427_step19_live_10mm_min.jsonl`, template 10 mm/min, a soft or
yielding specimen): force rose from ~0 to 3.8 kN at 45.25 mm and the controller reported the start load
(`#B01`, 0.1 % of 4000 kN = 4 kN). After CONTINUE the ramp `#D12167;0;100000;0;1` was sent with the
piston at 48.295 mm — start **0** again — and the press ran at **9.86 mm/min** (least squares over 51 s;
8–12 mm/min second by second) while the force stayed at 7–9 kN over 8.5 mm of travel. So the press
**can** run a 10 mm/min path ramp, and a start of 0 does not slow it.

| Test | Start sent / piston position | Ran at / set |
|---|---|---|
| step 19 | 0× (0 mm) | 9.86 / 10 mm/min |

**Step 20 — force control** (`captures/20261019_163951_step20_force_5kN_s.jsonl`, template Ramp
Control **Force, 5 kN/s, End 300 kN**, a 150 mm cube, stopped by the operator at 247 kN; the cube
survived). Everything up to CONTINUE was the path test's sequence (`#B47` … `#B23`, `#B01` at the start
load, `#D0520`), then `#D125000;0;300000;0;0`, `#B35`, `#B22`, `#O`. Force rose at **5.03 kN/s**
(least squares over 47 s) while the piston moved at about 4.7 mm/min. So the ramp command is the same
for both modes: the last field selects the channel, and the numbers are in thousandths of its unit.


**Step 21 — a force ramp left to reach its end** (`captures/20261019_165004_step21_force_2kN_s_to_end.jsonl`,
template Force **2 kN/s, End 100 kN**, the same cube; it survived). Ramp `#D122000;0;100000;0;0` — the
second force rate confirms the unit (2000 = 2 kN/s, measured 2.01 kN/s). At **99.67 kN** the
controller sent **`#B02` — ramp end reached** (new, controller-initiated); **10 ms later Proteus sent
`#B26`** (new; ends the test, as the template's "The test is successful" / "End test" steps suggest)
and **`#B17`** (Cancel), and the load was released (98 → 2 kN within 3 s). The operator pressed
nothing: **a force test ends by itself at its end force**, with Proteus driving the end.

**Step 22 — a path ramp at 120 mm/min by mistake** (`captures/20261019_170350_step22_path_120mm_min_pause_lag.jsonl`):
the template was on Path with 2 mm/**s** instead of 2 mm/min, so Proteus sent `#D122000;0;100000;0;1`
(2000 µm/s). On the cube the piston followed only about **20 mm/min** (17 mm/min fitted) and force rose
at ~65 kN/s. The operator pressed Stop (`#B18`) at 174 kN — and **the load kept rising to 464 kN** for
4.4 s, the piston moving another 1.6 mm, until Cancel (`#B17`) released it (464 → 34 kN in 1.5 s).

**Step 23 — PAUSE / CONTINUE** (`captures/20261019_170652_step23_path_2mm_min_pause_resume.jsonl`,
Path 2 mm/min, `#D1233;0;100000;0;1`): `#B18` four times — the force held at ~100 kN, rose again to
208 kN, held at ~190 kN, rose to 282 kN — then Cancel. **`#B18` toggles pause and continue**: one
button in Proteus, one command (operator). Measured with the paused time left out, the ramp ran at
1.95 mm/min.

**Why PAUSE held in step 23 and not in step 22:** pausing freezes the ramp's **target**, not the piston.
At 2 mm/min the piston follows its target closely, so it stops at once. At 120 mm/min the target ran
ahead at 2 mm/s while the piston managed ~0.35 mm/s, so when the target was frozen 3.6 s into the ramp
it was ~6 mm ahead, and the piston went on after it. **PAUSE is not a stop; Cancel (`#B17`) is.** And a
ramp must never be set faster than the press can follow under load (≈ 20 mm/min on a cube): the press
file's `[limits]` say how fast is allowed, and a faster ramp is said the moment it is sent.

At a ramp's start the servo takes up the load: force dipped 11.8 → 10.9 kN, then jumped to 19.4 kN,
before rising at 2 kN/s. The monitor leaves a ramp's first 3 s out of its measured rate.

Conclusion for now: the start field does not set the speed (steps 17, 18, 19), and 10 mm/min is
within the press's reach (at low load). **Step 15's 2.06 mm/min remains unexplained.** The monitor measures every
ramp's speed and warns after 10 s if it is more than 20 % off, so a recurrence will be caught and
recorded.

So the start field is **not** simply where Proteus believes the piston is, and the "duration = (end − start)
/ speed" model below fits step 15 but **not** step 17 (it would predict ~1 mm/min). Proteus' own Zero/Reset (software tare) was ruled out: neither was pressed
before steps 15 or 17 (operator). **Unresolved.** The monitor therefore measures
the ramp's speed rather than predicting it.

**Why step 15 ran at 2.06 mm/min (one model, contradicted by step 17):** Proteus sent start = **0**. The controller seems to plan the ramp
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
- **Proteus has no command that lowers the piston**: none in its manuals, none on its test screen,
  none in the program (see [From Proteus' own program](#from-proteus-own-program-installation-cd)).
  Sinking is the keypad's alone: leave PC mode (`#B36` `#B21`), then STOP.

### Actions that send nothing

- **Reset** (Proteus measurement window), 2026-10-16 step 12.
- **Zero** (Proteus measurement window), 2026-10-16, `captures/20261016_162626_step9_zero.*`: no PC→CTRL bytes;
  raw stream continued unchanged (force −6.3 kN, no jump); controller display unchanged while
  Proteus showed 0.0. → **Zero is a software tare inside Proteus.** A replacement app must do its own
  tare (subtract the raw value at the moment of zeroing).

### Break identification on, 2026-10-20, `captures/20261020_101100_step26_break_threshold_10_25.jsonl`

The template's **Break identification (Servo)** ticked, threshold 10 ‰, then 25 ‰; each time START
without a specimen and Cancel after the start load. Proteus sent at START:

`#B47` `#O` `#B30` **`#B33` `#D21100`** `#D0910` `#B23` (10 ‰) and the same with **`#D21250`** (25 ‰).

So `#D21<n>` is the threshold × 10, sent right after break detection on, before the start load. The
controller answered neither. Both approaches ended against something at **67.1 mm**: `#B01` at 3.4 and
3.6 kN, the force overshooting to **19.7 kN** within 2 s and settling at ~11.7 kN until Cancel —
the "20 kN" the operator sees at the start load is this overshoot, not a setting.

### Control mode: this program in Proteus' place, 2026-10-19, `captures/20261019_174926_step24_control_connect.jsonl`, `…175412_step25_control_connect_again.jsonl`

The old PC unplugged; the controller cable straight into a Digitus adapter (COM7). This program sent
Proteus' start-up byte for byte and the controller answered **exactly as it answered Proteus in every
recording** (`#O`; `#D138.6 #D104000`; `#D140 #D180`), then streamed at 10 Hz without a gap. Operator:
**PC** appeared on connecting; **PK** and **BD** followed `#B31/#B30` and `#B32/#B33`; after
Disconnect (`#B36 #B21` only) **PC** went away and the keypad worked again (STOP → SINKING). Both
sessions identical.

## From Proteus' own program (installation CD)

The operator found Proteus' installation CD (Proteus 2.4.5, Wüst, 2003) on 2026-10-19; its contents
are in `data/proteus_cd/` (git-ignored: proprietary). Nothing on it is run.
`tools/proteus_cd.py unpack` reads the installer archive as data, and `tools/proteus_cd.py commands`
lists the commands `proteus.exe` sends. What the program says is **evidence of what Proteus can send,
not of what the controller does**: a code learnt only from here stays unconfirmed until it is seen on
the line and the press's behaviour shows its meaning.

**How it sends.** `proteus.exe` is a Delphi program. Its classes are `TServoAbstract` → `TDigimess`
(another controller model), `TDigimaxx`, `TDigimaxxSynchro` (two machines run together). Every
command leaves through one of two methods, which build `#B` + code or `#D` + value. The codes are
fixed strings in the program, so the full list of `#B` codes it can ever send is known:

| Code | Where the program sends it | Seen on our line |
| --- | --- | --- |
| `#B21` `#B20` | connecting, in that order | yes, start-up |
| `#B04` | connecting, after `#B21 #B20`, **only for the Digimess** model | no (correctly) |
| `#B40` `#B50` `#B51` `#B52` | connecting / machine set-up | yes, start-up |
| `#B41`, then per channel `#B03` / `#B09` / `#B11` | connecting: one of the three per channel, chosen by a channel setting | `#B41 #B03 #B09` (two channels qualify); `#B11` never |
| `#B37` / `#B36` | stream on / off | yes |
| `#B30` / `#B31` | the Peak button (`SBPeakClick`) | yes |
| `#B32` / `#B33` | the BR button (`SBBruchClick`) | yes |
| `#B47` | the START button (`SBPruefenClick`) | yes |
| `#B23` | starting the approach | yes |
| `#B22` | starting the ramp | yes |
| `#B18` | Stop / Continue (`SBStopWeiterClick`) | yes |
| `#B17` | Cancel and every way back to idle (internal state "Messen") | yes |
| `#B26` | after the ramp end | yes |
| `#B38` | puts Proteus in its state "ramp halted"; reached from Cancel during a ramp under a condition not identified (every recorded Cancel sent `#B17`) | **no** |
| `#B24` | machine switching ("Maschinenumschaltung", after a configurable wait); a multi-machine feature | **no** |
| `#D160` / `#D161` | the same routine as `#B24`, when it does not send `#B24` | **no** |
| `#B34` | an internal routine, purpose unknown | **no** |
| `#B60` | an internal routine, purpose unknown | **no** |

`#D` commands with run-time values are built elsewhere: `#D02<machine>` (we see `#D020`), `#D05<n>`
(stream interval), the ramp `#D12…`, and others never seen (`#D06…`, `#D11…;0`/`;1`, `#D19…`,
`#D21…` with a one-decimal value).

**The test screen's buttons** (published handlers): `SBPruefenClick` (START), `SBAbbruchClick`
(Cancel), `SBStopWeiterClick` (Stop / Continue — one handler, consistent with `#B18` toggling),
`SBPeakClick`, `SBBruchClick`, `SBEndeClick` (Exit), `SBNaechstesElementClick` and two
unnamed SpeedButtons (one acts only in a simulation mode).

**"Next" is "Nächstes Element"** — next element of the test sequence. It acts only while a ramp or a
hold time runs, and ends that element so the sequence goes on to the next. It does not lower the
piston, and with our templates (one ramp) there is no element after the ramp.

**Proteus' internal states** (`ss…`, in order): OffLine, OnLine, Messen (measuring, idle), Einrichten
(setting up), Anfahren (approach), Angefahren (approached), Entlasten (unloading), Rampe,
RampeAngehalten (ramp halted), Haltezeit (hold time), Starten, RampenEnde (ramp end), Error, Bruch
(break), SoftwareBruch (software-detected break), MaschineZustandAbfragen (asking the machine's
state). They match the phases decoded from the line.

**The manuals** (`Handbuch proteus GR.pdf` is the German original; the English one is a poor machine
translation) describe the same buttons, START → approach → "Weiterfahren" (continue) → load, and
nothing that lowers the piston.

## Proteus' test template (operator's video, 2026-10-20)

The lab's template is a sequence of elements — Peak, Break identification (Servo),
Start, Adjustment, The test is successful, Ramp, End test. What each holds and
sends is tabled in [motion](motion.md#proteus-test-template-element-by-element-operators-video-2026-10-20).
In short: Peak's checkbox (off) is the `#B30` at START; Break identification's
checkbox (off) is the `#B32`, and when on Proteus' program sends `#B33` then
`#D21<threshold × 10>` (threshold 10.00 ‰); Start's "start load 0.1000 % of range"
is `#D0910`; the Ramp's "Measur. dist. 200 ms" is `#D0520`; Adjustment, the
validity question and "keep measuring" send nothing.

## Command summary

| Code | From | Meaning | Status |
|---|---|---|---|
| `#B01` | CTRL | start load reached | confirmed |
| `#B02` | CTRL | ramp end reached (force ramp at its end force) | confirmed (step 21) |
| `#B28` | CTRL | keypad STOP pressed (in PC mode, not obeyed locally) | confirmed |
| `#B35` | CTRL | answer to the ramp definition | hypothesis |
| `#B43` | CTRL | test over, load released | hypothesis |
| `#B17` | PC | Cancel: pump off, test ends | confirmed |
| `#B18` | PC | PAUSE / CONTINUE, toggling; freezes the ramp's target, so it does not hold a piston that lags it | confirmed (steps 22, 23) |
| `#B20` / `#B21` | PC | PC mode on / off | `#B21` confirmed (step 24: `#B36 #B21` alone clears **PC** from the display and frees the keypad); `#B20` hypothesis |
| `#B22` | PC | start the ramp | confirmed |
| `#B23` | PC | start the approach | confirmed |
| `#B26` | PC | test finished, sent in answer to `#B02` | hypothesis (step 21) |
| `#B30` / `#B31` | PC | peak detection off / on | confirmed (display PK) |
| `#B32` / `#B33` | PC | break detection off / on | confirmed (display BD) |
| `#B36` / `#B37` | PC | stream off / on | confirmed |
| `#B47` | PC | START pressed (arm the test) | confirmed (Proteus' START handler sends it; the approach follows) |
| `#B24` `#B34` `#B38` `#B60` `#D160` `#D161` | PC | in Proteus' program, never seen on the line (see above) | unknown — never to be sent |
| `#D05<n>` | PC | stream interval n × 10 ms — the template's ramp "Measur. dist." (200 ms → `#D0520`) | confirmed |
| `#D09<n>` | PC | start load, n × 0.01 % of the force range (template "Start load 0.1000 %" → `#D0910` = 4 kN; `#B01` came at 3–4 kN in every test) | hypothesis, strongly supported |
| `#D21<n>` | PC | break threshold, n × 0.1 ‰, sent right after `#B33` when the template's break identification is on | encoding confirmed (step 26: 10 ‰ → `#D21100`, 25 ‰ → `#D21250`); its effect on the controller not yet seen |
| `#D12…` | PC | ramp: speed; start; end; 0; channel, in thousandths of the channel unit | confirmed for Path and Force |
| `#B03 #B09 #B40 #B41 #B50–52 #D020` | PC | start-up / approach, replayed as recorded | unknown, accepted |

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
- What Proteus puts in the ramp's start field (0×, 1×, 2×, 0×, 0× the piston position in steps 15–19); it does not affect the speed (steps 17–19).
- Why step 15's 10 mm/min ramp ran at 2.06 mm/min; step 19 ran 10 mm/min correctly (at 7–9 kN).
- Ramp field 4 (`0`) and whether field 5 changes with Force/Deformation control.
- Whether break detection (`#B33`) is ever enabled by a template, and what the controller sends on break.
- Whether other keypad keys (START, ZERO, PEAK…) are forwarded like STOP (`#B28`) in PC mode.
- Meaning of `#D0910`, controller `#B35`, `#B43`; what the `8` after `#D0` is.
- What `#B34`, `#B38` and `#B60` do (in Proteus' program, never seen on the line).
- What Peak and BR change inside the controller (stream looks the same).
- Whether channel 3 (External, 250 kN) appears when active.
