"""The program, drawn (docs/ui.md, "The program").

* **Force only, every length known**: force against time as planned.
* **Otherwise** — a Path step, whose force only the press will know — one block
  per step, as wide as its planned time (or an even share when that is not
  known), labelled ``F↑200``, ``P+2``, ``10 s``.

The steps under break detection are shaded. While a test runs, the part done is
filled in and a line marks now. A view over a
:class:`~presscontroller.control.program.Program`; it computes nothing the
planner has not. Colours are read from the palette when it paints, so a theme
change needs nothing more than the repaint Qt sends.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from presscontroller.app.theme import muted, warning
from presscontroller.control.program import PlannedStep, Program

#: The strip's height, px: the profile reads at a glance, the window keeps its plot.
STRIP_HEIGHT = 72


def profile(program: Program) -> list[tuple[float, float]]:
    """``(seconds, kN)`` corners of the planned force against time, from the
    start load; empty when it cannot be drawn (:attr:`Program.force_profile_known`)."""
    if not program.force_profile_known or not program.steps:
        return []
    t, out = 0.0, [(0.0, program.start_kn)]
    for s in program.steps:
        t += s.seconds or 0.0
        out.append((t, s.to_value))
    return out


def break_from_s(program: Program) -> float | None:
    """When, on the planned time line, break detection comes on."""
    t = 0.0
    for s in program.steps:
        if s.break_on:
            return t
        t += s.seconds or 0.0
    return None


def block_label(s: PlannedStep) -> str:
    if s.kind == "hold":
        return f"{s.hold_s:g} s"
    if s.control == "path":
        if s.path_by is not None:
            return f"P{s.path_by:+g}"
        return f"P→{s.to_value:g}"
    up = s.from_value is None or s.to_value >= s.from_value
    return f"F{'↑' if up else '↓'}{s.to_value:g}"


def block_widths(program: Program) -> list[float]:
    """Each step's share of the strip: its planned time, or an even share of
    the time the others take when it has none."""
    secs = [s.seconds for s in program.steps]
    known = [x for x in secs if x]
    fill = (sum(known) / len(known)) if known else 1.0
    widths = [x if x else fill for x in secs]
    total = sum(widths) or 1.0
    return [w / total for w in widths]


class ProgramStrip(QWidget):
    """The planned program; :meth:`set_progress` marks how far a test is."""

    def __init__(self, parent=None, *, framed: bool = False):
        super().__init__(parent)
        self._framed = framed
        """A thin border round it, where it stands among other things (the
        control window's test bar)."""
        self._program: Program | None = None
        self._step: int | None = None
        self._fraction: float | None = None
        self._elapsed: float | None = None
        self.setMinimumHeight(STRIP_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def sizeHint(self) -> QSize:
        return QSize(600, STRIP_HEIGHT)

    def set_corner_widget(self, widget: QWidget) -> None:
        """Show ``widget`` (the control window's Edit) in the bottom-right
        corner, over the drawing (operator, 2026-11-09)."""
        widget.setParent(self)
        self._corner = widget
        self._place_corner()

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._place_corner()

    def _place_corner(self) -> None:
        w = getattr(self, "_corner", None)
        if w is None:
            return
        size = w.sizeHint()
        w.resize(size)
        w.move(self.width() - size.width() - 4, self.height() - size.height() - 4)
        w.raise_()

    def set_program(self, program: Program | None) -> None:
        self._program = program
        self.update()

    def set_progress(self, step: int | None, fraction: float | None = None,
                     elapsed: float | None = None) -> None:
        """The running step's index, how far through it (0–1), and the seconds
        along the planned time line; all ``None`` between tests."""
        state = (step, fraction, elapsed)
        if state != (self._step, self._fraction, self._elapsed):
            self._step, self._fraction, self._elapsed = state
            self.update()

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        text_c = QColor(muted(self))
        if self._framed:
            p.setPen(QPen(text_c, 1))
            p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
            r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        else:
            r = QRectF(self.rect()).adjusted(4, 6, -4, -6)
        prog = self._program
        if prog is None or not prog.steps:
            p.setPen(text_c)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "no program")
            return
        if prog.force_profile_known:
            self._paint_profile(p, r, prog, text_c)
        else:
            self._paint_blocks(p, r, prog, text_c)

    def _shade(self, p: QPainter, r: QRectF, x: float) -> None:
        shade = QColor(warning(self))
        shade.setAlpha(36)
        p.fillRect(QRectF(x, r.top(), r.right() - x, r.height()), shade)

    def _now_line(self, p: QPainter, r: QRectF, x: float) -> None:
        p.setPen(QPen(self.palette().color(QPalette.ColorRole.Text), 1.5))
        p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))

    def _paint_profile(self, p: QPainter, r: QRectF, prog: Program, text_c: QColor) -> None:
        pts = profile(prog)
        total = pts[-1][0] or 1.0
        top = max(f for _, f in pts) * 1.08 or 1.0

        def at(t: float, f: float) -> QPointF:
            return QPointF(r.left() + t / total * r.width(),
                           r.bottom() - max(0.0, f) / top * r.height())

        bd = break_from_s(prog)
        if bd is not None:
            self._shade(p, r, r.left() + bd / total * r.width())
        p.setPen(QPen(text_c, 2))
        p.drawPolyline(QPolygonF([at(t, f) for t, f in pts]))
        now = self._elapsed
        if now is not None:
            done = [at(t, f) for t, f in pts if t <= now]
            for (t0, f0), (t1, f1) in zip(pts, pts[1:]):
                if t0 < now < t1:
                    done.append(at(now, f0 + (now - t0) / (t1 - t0) * (f1 - f0)))
                    break
            p.setPen(QPen(self.palette().color(QPalette.ColorRole.Highlight), 3))
            p.drawPolyline(QPolygonF(done))
            self._now_line(p, r, r.left() + min(now, total) / total * r.width())

    def _paint_blocks(self, p: QPainter, r: QRectF, prog: Program, text_c: QColor) -> None:
        widths = block_widths(prog)
        lefts, x = [], r.left()
        for w in widths:
            lefts.append(x)
            x += w * r.width()
        bd = prog.break_from
        if bd is not None:
            self._shade(p, r, lefts[bd - 1])
        hl = self.palette().color(QPalette.ColorRole.Highlight)
        mid = r.top() + r.height() / 2
        for i, (s, left, w) in enumerate(zip(prog.steps, lefts, widths)):
            box = QRectF(left + 1, mid - 14, w * r.width() - 2, 28)
            done = self._step is not None and (i < self._step)
            part = (self._fraction or 0.0) if self._step == i else (1.0 if done else 0.0)
            if part > 0:
                fill = QColor(hl)
                fill.setAlpha(110)
                p.fillRect(QRectF(box.left(), box.top(), box.width() * part, box.height()), fill)
            p.setPen(QPen(hl if self._step == i else text_c, 2 if self._step == i else 1))
            p.drawRect(box)
            p.setPen(QPen(self.palette().color(QPalette.ColorRole.Text)))
            if box.width() > 24:
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, block_label(s))
        if self._step is not None and self._step < len(lefts):
            self._now_line(p, r, lefts[self._step]
                           + (self._fraction or 0.0) * widths[self._step] * r.width())
