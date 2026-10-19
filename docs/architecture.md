# Architecture

## Package ownership

```text
presscontroller/
  protocol/  bytes → lines (lines.py), lines → messages and their meanings
             (messages.py); Qt-free, hardware-free, config-free
  config/    the press file (press.py), the global settings (settings.py), and
             DAqReader's TOML writer and typed readers (toml.py, parse.py)
  tap/       where lines come from: the live SerialTap (read-only), a
             ReplayTap of a capture, and the capture format both share
  monitor/   the Qt-free logic of the monitor: link state, test phases, each
             test's record (tracker.py), and a test as CSV (csvfile.py)
  app/       the Qt window; plot.py draws to an ndarray (Qt-free), theme.py and
             widgets.py come from DAqReader
tools/       sniff.py, the bench sniffer the protocol was learnt with
docs/        protocol notes, the tap's wiring (PDF and its generator), these topics
examples/    press.example.toml, with placeholder ports
tests/       unit and offscreen UI tests; tests/data holds real captures
captures/    the recordings the protocol notes cite
data/        the lab's own press file (git-ignored)
```

## Dependency direction

```text
app (Qt)  ->  monitor  ->  tap  ->  protocol
                 \-> config
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
- One place decides a colour: `app/theme.py`.

## Provenance

From DAqReader (`..\DAqReader`), as it stood on 2026-10-19:

- `config/toml.py` and `config/parse.py` (the typed readers, up to
  `get_str_list`), unchanged.
- `app/theme.py`, with its widget attribute renamed.
- `app/widgets.py`, without DAqReader's `PlotPanel`.
- `app/plot.py`'s `StickyMargins` and drawing helpers; the two renderers are
  this application's own.

These are copies, not a shared package: a fix in one is not automatically a fix
in the other.
