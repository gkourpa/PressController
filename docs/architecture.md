# Architecture

## Package ownership

```text
presscontroller/
  protocol/  bytes → lines (lines.py), lines → messages and their meanings
             (messages.py); Qt-free, hardware-free, config-free
  config/    the press file (press.py), the global settings and the test
             template's defaults (settings.py), and
             DAqReader's TOML writer and typed readers (toml.py, parse.py)
  tap/       where lines come from: the live SerialTap (read-only), a
             ReplayTap of a capture, and the capture format both share
  monitor/   the Qt-free logic of the monitor: link state, test phases, each
             test's record (tracker.py), and a test as CSV (csvfile.py)
  control/   talking to the controller ourselves: the allowlist
             (commands.py), the one port that writes (link.py), and the
             connect / disconnect / keypad-STOP state machine (session.py);
             Qt-free
  app/       the Qt window; plot.py draws to an ndarray (Qt-free), theme.py and
             widgets.py come from DAqReader
tools/       sniff.py, the bench sniffer the protocol was learnt with
docs/        protocol notes, the tap's wiring (PDF and its generator), these topics
examples/    press.example.toml, with placeholder ports
tests/       unit and offscreen UI tests; tests/data holds real captures
data/        git-ignored: the lab's own press file, the Proteus CD, and
             data/captures/, the recordings the protocol notes cite (kept
             out of the repository, operator 2026-10-20)
```

## Dependency direction

```text
app (Qt)  ->  monitor  ->  tap  ->  protocol
   |             \-> config
   \-> control (control window only)  ->  tap, protocol
```

- `protocol` imports nothing of this package's but itself.
- `tap` turns bytes into `TapEvent` lines; it knows directions and timing, not
  meanings. `SerialTap` and `ReplayTap` have the same `start / poll / close /
  describe / errors` surface, so the monitor and the window run identically on
  the press and on a file.
- pyserial is imported lazily inside `open_read_only`, so replay and the tests
  load without it.
- One place says what a line means: `protocol/messages.py` (`COMMANDS`,
  `PARAMS`). The window shows `describe()`; it never interprets a line itself.
- One place may write to a port: `control/link.py`, and only lines in
  `control/commands.ALLOWED`. The monitor window (`app/main_window.py`) does not
  import `control`; a test checks it in a fresh interpreter.
- `ControllerSession` has the tap's surface (`start / poll / close / describe /
  errors`) and hands out what it sends as `PC>CTRL` lines, so the monitor
  follows our own session exactly as it follows Proteus'.
- One place decides a colour: `app/theme.py`.

## Provenance

From DAqReader (`..\DAqReader`), as it stood on 2026-10-19:

- `config/toml.py` and `config/parse.py` (the typed readers, up to
  `get_str_list`), unchanged.
- `app/theme.py`, with its widget attribute renamed.
- `app/widgets.py`, without DAqReader's `PlotPanel`.
- `app/plot.py`'s `StickyMargins` and drawing helpers; the renderer is this
  application's own.
- 2026-10-20: `config/parse.py`'s `get_range`; the settings dialog's
  `AxisRange` (from DAqReader's plot dialog); `app/resources/` — `__init__.py`
  and `generate_icon.py` unchanged but for the package name. The icon itself
  (`icon.svg`, a press frame, platens and a cracked cube) is this application's,
  drawn in the siblings' palette: #161B22 ground, teal #2DD4BF lines, amber
  #F2A93B subject, grey #C9D1D9 solids.

These are copies, not a shared package: a fix in one is not automatically a fix
in the other.
