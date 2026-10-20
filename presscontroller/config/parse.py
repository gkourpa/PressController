"""Typed reads from a parsed TOML table, naming the file and key when one is wrong.

``tomllib`` hands back whatever the file holds, so ``rate_hz = "fast"`` arrives
as a string. Coercing it with ``float()`` would fail far from the file with no
mention of where; these fail here, saying which entry and which key.

Two kinds of trouble, kept apart on purpose. A value of the wrong *type* means
the file cannot be read as a configuration at all, so it raises
:class:`ConfigError`. A well-typed value that is merely unusable (a rate of 0,
a blank port) is a *problem*, reported by the config's ``problems()`` so every
one of them can be shown at once rather than one per attempt.
"""

from __future__ import annotations

import math


class ConfigError(ValueError):
    """A file that cannot be read as a configuration at all."""


def _where(where: str, key: str) -> str:
    return f"{where}: {key}" if where else key


def get_str(t: dict, key: str, default: str, where: str) -> str:
    v = t.get(key, default)
    if not isinstance(v, str):
        raise ConfigError(f"{_where(where, key)} must be text, not {v!r}")
    return v


def get_float(t: dict, key: str, default: float, where: str) -> float:
    v = t.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ConfigError(f"{_where(where, key)} must be a number, not {v!r}")
    if not math.isfinite(v):
        raise ConfigError(f"{_where(where, key)} must be a finite number, not {v!r}")
    return float(v)


def get_opt_float(t: dict, key: str, where: str) -> float | None:
    return get_float(t, key, 0.0, where) if key in t else None


def get_bool(t: dict, key: str, default: bool, where: str) -> bool:
    """A TOML ``true``/``false``. A number is refused rather than taken as truthy:
    ``track_peaks = 1`` is a typo worth naming, not a yes."""
    v = t.get(key, default)
    if not isinstance(v, bool):
        raise ConfigError(f"{_where(where, key)} must be true or false, not {v!r}")
    return v


def get_int(t: dict, key: str, default: int, where: str) -> int:
    v = t.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ConfigError(f"{_where(where, key)} must be a whole number, not {v!r}")
    return v


def get_str_list(t: dict, key: str, where: str) -> tuple[str, ...]:
    v = t.get(key, [])
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ConfigError(f"{_where(where, key)} must be a list of text, not {v!r}")
    return tuple(v)


def get_range(t: dict, key: str, where: str) -> tuple[float, float] | None:
    """A ``[low, high]`` axis range, or ``None`` where the key is absent.

    An inverted or empty pair is refused here rather than carried to the plot,
    where matplotlib draws a frame with nothing in it and says nothing about why
    — which on a live plot reads as the channel having stopped.
    """
    if key not in t:
        return None
    v = t[key]
    ok = (isinstance(v, list) and len(v) == 2
          and all(not isinstance(x, bool) and isinstance(x, (int, float)) for x in v))
    if not ok:
        raise ConfigError(f"{_where(where, key)} must be two numbers, "
                          f"[low, high], not {v!r}")
    lo, hi = float(v[0]), float(v[1])
    if not (math.isfinite(lo) and math.isfinite(hi)):
        raise ConfigError(f"{_where(where, key)} must be finite numbers, not {v!r}")
    if hi <= lo:
        raise ConfigError(f"{_where(where, key)} must be [low, high] with the high "
                          f"one larger, not {v!r}")
    return (lo, hi)
