"""Colours derived from the running palette, so the windows read on any theme.

DAqReader's ``daqreader/app/theme.py``, copied as it stood on 2026-10-19; the
operator reports quoted below were made there.

The app follows Windows' light/dark setting unless the operator overrides it
(:func:`apply_theme`), so the palette is a light one or a dark one and neither is
known until a widget exists. Every colour here is therefore a **function of a
widget**, read at the moment it is applied, never a constant chosen at import.

That is not fussiness. The first version wrote a fixed
``background: #fff0f0`` on an invalid field, which is a near-white tint; under
Windows' dark theme the text stayed the palette's near-white and the field became
**unreadable exactly when it had something to say** (operator screenshot,
2026-09-21). A colour that assumes a background is a colour that will be wrong on
half the machines.

The rule this follows: **set a background and a foreground together, or set
neither.** A stylesheet that names one and inherits the other is what produces
white-on-white, and it fails silently — the widget looks fine to whoever wrote it.
"""

from __future__ import annotations

import weakref

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

try:
    from shiboken6 import isValid as _is_alive
except ImportError:                       # pragma: no cover - shiboken ships with PySide6
    def _is_alive(_obj) -> bool:
        return True

#: Above this palette lightness the theme is treated as light. A mid grey could
#: go either way; the comparison is against the text-entry background, which is
#: the surface these colours are actually read against.
_LIGHT_ABOVE = 128

#: (light theme, dark theme) for each role. The dark entries are lifted, not the
#: same hue at the same lightness: a #c00 that reads as urgent on white is nearly
#: invisible on #1e1e1e.
_DANGER = ("#cc0000", "#ff6b6b")
_WARNING = ("#a15c00", "#e0a44a")
_MUTED = ("#666666", "#9a9a9a")


def is_dark(widget: QWidget) -> bool:
    """Whether ``widget`` is being drawn on a dark palette."""
    return widget.palette().color(QPalette.ColorRole.Base).lightness() <= _LIGHT_ABOVE


def _pick(widget: QWidget, pair: tuple[str, str]) -> str:
    return pair[1] if is_dark(widget) else pair[0]


def danger(widget: QWidget) -> str:
    """The colour for something wrong: a failed device, a refused entry."""
    return _pick(widget, _DANGER)


def warning(widget: QWidget) -> str:
    """The colour for something worth knowing that does not block."""
    return _pick(widget, _WARNING)


def muted(widget: QWidget) -> str:
    """The colour for a note beside a control — present, not competing."""
    return _pick(widget, _MUTED)


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(round(a.red() * (1 - t) + b.red() * t),
                  round(a.green() * (1 - t) + b.green() * t),
                  round(a.blue() * (1 - t) + b.blue() * t))


def invalid_palette(reference: QPalette) -> QPalette:
    """``reference`` with the text-entry colours tinted to say "not usable".

    A **palette**, not a stylesheet. Naming a ``border`` in a stylesheet hands the
    whole box model to ``QStyleSheetStyle``, which does not know the native
    style's padding and falls back to none — so the field visibly shrank the
    moment it went red (operator, 2026-09-21), which is the worst moment for a
    row to jump. A palette changes no metric at all.

    The background is the theme's own text-entry colour **tinted** toward red
    rather than replaced by a fixed pink, and the foreground is carried over
    unchanged, so the contrast the theme already guarantees between the two
    survives whether the field started white or nearly black.
    """
    base = reference.color(QPalette.ColorRole.Base)
    text = reference.color(QPalette.ColorRole.Text)
    dark = base.lightness() <= _LIGHT_ABOVE
    tint = _mix(base, QColor(_DANGER[1] if dark else _DANGER[0]), 0.22)
    pal = QPalette(reference)
    # Both groups: an unfocused invalid field is still invalid, and leaving
    # Inactive alone makes it revert to plain the moment the window loses focus.
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        pal.setColor(group, QPalette.ColorRole.Base, tint)
        pal.setColor(group, QPalette.ColorRole.Text, text)
    return pal


def mark_valid(widget: QWidget, ok: bool) -> None:
    """Show whether ``widget`` holds something usable, without moving it.

    Registered through :func:`styled`, so it is recomputed against the palette in
    force after a theme change. A valid field is given a **default-constructed**
    palette, which resolves nothing of its own and so goes back to inheriting the
    application's — rather than being pinned to a copy of whatever was current.
    """
    widget._presscontroller_valid = bool(ok)
    styled(widget, _restyle_field)


def _restyle_field(widget: QWidget) -> None:
    if getattr(widget, "_presscontroller_valid", True):
        widget.setPalette(QPalette())
    else:
        widget.setPalette(invalid_palette(QApplication.palette()))


def text_style(widget: QWidget, *, error: bool = False, warn: bool = False) -> str:
    """A label's colour: the theme's own unless it is saying something."""
    if error:
        return f"color: {danger(widget)};"
    if warn:
        return f"color: {warning(widget)};"
    return ""


# ---- switching the scheme -------------------------------------------------------

#: The colour scheme each setting asks Qt for. ``system`` asks for nothing and
#: lets the platform answer, which is what makes it follow a later change to the
#: operator's Windows setting without the app restarting.
_SCHEMES = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}

#: Where a widget's restyle callback is kept, on the widget itself.
_RESTYLE = "_presscontroller_restyle"

#: The widgets that carry one. Held weakly and walked instead of
#: ``QApplication.allWidgets()``: that call is not safe to make once any widget's
#: C++ side has been deleted while its Python wrapper is still around — it does
#: not raise, it corrupts the heap and takes the process down (seen under the
#: test suite, 2026-09-21, after a few dialogs had been opened and closed). This
#: also visits only the handful of widgets we style rather than every one.
_registered: "weakref.WeakSet[QWidget]" = weakref.WeakSet()


def apply_theme(app: QApplication, name: str) -> None:
    """Put the whole application on ``name``'s colour scheme.

    Qt is asked for the *scheme* rather than handed a palette of ours: the
    platform style then draws its own light or dark widgets, exactly as it does
    when following the system, including the controls we never touch — native
    dialogs, scrollbars, a combo's popup — which a hand-built palette leaves
    behind at the first one we forgot. ``system`` simply withdraws the override.

    Under the offscreen platform used by the tests there is no platform theme to
    override, so this is a no-op there; what the tests check instead is that every
    colour follows the palette it is given, which is the part that can be wrong.
    """
    app.styleHints().setColorScheme(_SCHEMES.get(name, Qt.ColorScheme.Unknown))


def styled(widget: QWidget, restyle) -> QWidget:
    """Style ``widget`` with ``restyle(widget)`` now, and again on every scheme change.

    A stylesheet is resolved when it is **set**, not when it is drawn, so a widget
    styled once keeps its old colours after a scheme change — OpticalDistanceMeter
    saw this as "dark islands in a light window until a restart" (operator,
    2026-09-18). Its fix was to set each sheet again, which works where the sheet
    names ``palette(base)`` and Qt re-resolves it.

    That is not enough here, because what is applied carries **literal** colours
    already blended out of the palette (:func:`invalid_palette`); applying the
    same thing again would change nothing. So the widget keeps the *function*
    that styled it and runs it afresh, recomputing against the new palette.
    """
    setattr(widget, _RESTYLE, restyle)
    _registered.add(widget)
    restyle(widget)
    return widget


def follows_theme(widget: QWidget) -> bool:
    """Whether ``widget``'s style will be recomputed when the scheme changes.

    A widget that carries a stylesheet and is **not** registered keeps whatever
    that sheet resolved to when it was set, including the colours it inherited
    rather than named — which is how a bold heading set up under the dark scheme
    stayed near-white after a switch to light (operator, 2026-09-22). The rule is
    walked by the tests rather than left to review.
    """
    return getattr(widget, _RESTYLE, None) is not None


def restyle_widgets() -> None:
    """Re-run every registered restyle against the palette now in force.

    Each widget is checked for life before it is touched: a closed dialog's
    wrapper can outlive the widget it wrapped, and using one is undefined rather
    than an exception, so ``RuntimeError`` is a backstop and not the guard.
    """
    for w in list(_registered):
        if not _is_alive(w):
            _registered.discard(w)
            continue
        restyle = getattr(w, _RESTYLE, None)
        if restyle is None:
            continue
        try:
            restyle(w)
        except RuntimeError:
            pass            # deleted between the check and here; it is going anyway


def follow_color_scheme(app: QApplication) -> None:
    """Restyle whenever the scheme changes — a Settings save, or Windows itself
    switching while the theme is *System*.

    Deferred one turn of the event loop so it runs **after** Qt has installed the
    new palette: called inline, every colour would be recomputed from the palette
    that is on its way out.
    """
    app.styleHints().colorSchemeChanged.connect(
        lambda _scheme: QTimer.singleShot(0, restyle_widgets))
