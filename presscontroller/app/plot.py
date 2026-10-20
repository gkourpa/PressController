"""The live plot of a test — force against displacement — rendered to an ndarray.

Qt-free and testable. DAqReader's ``daqreader/app/plot.py`` way of drawing, for
its reasons: render to an Agg buffer and show it as a pixmap, with the
**pyplot-free** ``Figure`` + ``FigureCanvasAgg`` API, because pyplot selects a GUI
backend at import and a QtAgg canvas deadlocks under the offscreen platform the
tests use. :class:`StickyMargins` and the helpers below are copied from there as
they stood on 2026-10-19; the renderer is this application's own.

Kept from there: plain lines, a gap left as a break (``None`` becomes NaN and
is never bridged), no axis offset (``1515.88`` must not read as ``0.88`` with
``+1.515e3`` in a corner), and a dot on the newest point of a parametric curve.

**Force against displacement, not against time** (operator, 2026-10-19): the
curve is what a compression test is read by — its stiffness, the peak and what
the specimen did after it — and time adds only the approach and the hold at the
start load, which say nothing about the specimen.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

LATEST_MARKER_MS = 6.0
PEAK_MARKER_MS = 8.0


class StickyMargins:
    """Figure margins that may grow between redraws but never shrink back.

    From OpticalDistanceMeter's class of the same name, for the same reason.
    ``tight_layout`` fits the margins to the tick labels of *this* redraw, so the
    axes box moves whenever they change width — ``0.02`` to ``-0.015`` to
    ``119.170`` walks the left edge by tens of pixels, and a live plot whose frame
    shifts while the operator is reading it looks like the data shifted. Holding
    the widest margins seen so far keeps the frame still: it steps outwards only,
    and only when a label would otherwise be clipped, which settles within the
    first minutes of a run.

    ``hspace`` is kept the same way, which the original did not need: a time plot
    here stacks one panel per unit, and the gap between them is fitted to the tick
    labels too, so leaving it free would slide the panels against each other while
    their outer frame held still.

    The fractions mean nothing except for one figure size and one set of axis
    labels, so the owner calls :meth:`reset` when either changes.
    """

    def __init__(self) -> None:
        self._pars: tuple[float, float, float, float, float] | None = None

    def reset(self) -> None:
        self._pars = None

    def fit(self, fig) -> None:
        """Lay ``fig`` out tight, then widen to whatever an earlier redraw needed."""
        fig.tight_layout()
        p = fig.subplotpars
        left, bottom, right, top, hspace = p.left, p.bottom, p.right, p.top, p.hspace
        if self._pars is not None:
            l0, b0, r0, t0, h0 = self._pars
            left, bottom = max(left, l0), max(bottom, b0)
            right, top = min(right, r0), min(top, t0)
            hspace = max(hspace, h0)
        self._pars = (left, bottom, right, top, hspace)
        fig.subplots_adjust(left=left, bottom=bottom, right=right, top=top,
                            hspace=hspace)


def _lay_out(fig, margins: StickyMargins | None) -> None:
    """Fit the axes into the figure, holding the frame still if asked to."""
    if margins is None:
        fig.tight_layout()
    else:
        margins.fit(fig)


def _figure(size_px: tuple[int, int], dpi: int):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    w, h = size_px
    fig = Figure(figsize=(w / dpi, h / dpi), dpi=dpi)
    FigureCanvasAgg(fig)
    return fig


def _no_offset(ax) -> None:
    for axis in (ax.xaxis, ax.yaxis):
        axis.get_major_formatter().set_useOffset(False)


def _to_bgr(fig) -> np.ndarray:
    fig.canvas.draw()
    rgba = np.asarray(fig.canvas.buffer_rgba())
    return rgba[:, :, [2, 1, 0]].copy()


def _empty(fig, text: str) -> np.ndarray:
    ax = fig.add_subplot(111)
    ax.text(0.5, 0.5, text, ha="center", va="center", transform=ax.transAxes,
            color="#888")
    ax.set_xticks([])
    ax.set_yticks([])
    return _to_bgr(fig)


def _array(values: Sequence[float | None]) -> np.ndarray:
    return np.array([np.nan if v is None else v for v in values], dtype=float)


def render_force_displacement(displacement: Sequence[float | None],
                               force: Sequence[float | None], *,
                               peak: tuple[float, float] | None = None,
                               displacement_label: str = "Displacement (mm)",
                               force_label: str = "Force (kN)",
                               units: tuple[str, str] = ("mm", "kN"), title: str = "",
                               size_px: tuple[int, int] = (720, 480), dpi: int = 100,
                               margins: StickyMargins | None = None,
                               xlim: tuple[float, float] | None = None,
                               ylim: tuple[float, float] | None = None,
                               colour: str = "C0") -> np.ndarray:
    """Force against displacement, the newest point dotted, the peak marked.

    ``peak`` is ``(displacement, force)``; ``units`` are the two axes' units, in
    that order, for the peak's note. It is drawn as a marker and written out
    in the corner, because the peak is the number a compression test is for and
    the highest pixel of a curve is a poor way to read it.

    Only the points where **both** channels have a value are drawn, so a gap in
    one leaves a break rather than a point invented from the other.

    ``xlim``/``ylim`` fix an axis's range (``None``: fitted to the data) and
    ``colour`` is the curve's — the settings' Plot tab, as DAqReader's plots.
    """
    fig = _figure(size_px, dpi)
    x, y = _array(displacement), _array(force)
    good = np.flatnonzero(np.isfinite(x) & np.isfinite(y))
    if not good.size:
        return _empty(fig, title or "no test yet: waiting for START")
    ax = fig.add_subplot(111)
    ax.plot(x, y, lw=1, color=colour)
    i = good[-1]
    ax.plot([x[i]], [y[i]], marker="o", ms=LATEST_MARKER_MS, linestyle="none", color=colour)
    if peak is not None:
        ax.plot([peak[0]], [peak[1]], marker="v", ms=PEAK_MARKER_MS, linestyle="none",
                color="C3")
        ax.text(0.01, 0.98, f"peak {peak[1]:.2f} {units[1]} at {peak[0]:.3f} {units[0]}", transform=ax.transAxes,
                ha="left", va="top", fontsize=8)
    ax.set_xlabel(displacement_label, fontsize=8)
    ax.set_ylabel(force_label, fontsize=8)
    if title:
        ax.set_title(title, fontsize=9)
    ax.grid(True, alpha=0.3)
    if xlim is not None:
        ax.set_xlim(*xlim)
    if ylim is not None:
        ax.set_ylim(*ylim)
    _no_offset(ax)
    _lay_out(fig, margins)
    return _to_bgr(fig)
