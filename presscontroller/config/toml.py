"""Deterministic TOML writing, and replacing a file without ever half-writing it.

Reading is the stdlib's ``tomllib``. Writing is here because the stdlib has none
and the files are small, flat and ours, so a writer that emits exactly the keys
we define, in a fixed order, is shorter than a dependency — and a fixed order
means a saved file diffs cleanly against the one it replaced.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable
from pathlib import Path

_ESCAPES = {"\\": "\\\\", '"': '\\"', "\b": "\\b", "\t": "\\t",
            "\n": "\\n", "\f": "\\f", "\r": "\\r"}


def toml_str(s: str) -> str:
    """A TOML basic string, every character that needs it escaped."""
    out = []
    for ch in str(s):
        if ch in _ESCAPES:
            out.append(_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def toml_value(v) -> str:
    """One scalar or a flat list, as TOML.

    Refuses NaN and infinity: TOML can spell them, but a configuration value
    that is not a number is a mistake to catch here rather than to write down.
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise ValueError(f"refusing to write a non-finite number ({v!r})")
        return repr(v)
    if isinstance(v, str):
        return toml_str(v)
    if isinstance(v, Iterable):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    raise TypeError(f"no TOML form for {type(v).__name__}")


def write_atomic(path: str | Path, text: str) -> Path:
    """Write ``text`` to ``path`` so a crash leaves the old file or the new one.

    The new content goes to a sibling temporary file first and replaces the
    target in one ``os.replace``, which is atomic on the same volume; an
    interrupted save therefore never leaves a truncated configuration behind.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return path
