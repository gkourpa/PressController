"""Small Qt pieces, from DAqReader's ``daqreader/app/widgets.py`` (itself from
OpticalDistanceMeter's ``dic.app.widgets``), copied as it stood on 2026-10-19.
Left out: DAqReader's ``PlotPanel``, whose buttons edit an experiment's plots.

* :func:`to_pixmap` / :func:`widget_dpr` — show a rendered ndarray at the
  display's real resolution; Windows scaling (this laptop: 1.25) otherwise
  upscales it and the axis text blurs first.
* :class:`Coalescer` — a redraw ceiling where the newest payload wins and a
  trailing draw is guaranteed.
* :class:`PlotView` — a label that re-renders its plot at its own size.
* :class:`ReadingLabel` / :class:`Gauge` — one number, as large as its card holds.
* :func:`island` — the card look the table and the message share.
* :class:`MessageIsland` — the card the window speaks from, on its bottom edge.
* :class:`Switch` — an on/off switch with its name and its state in words.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from presscontroller.app.plot import StickyMargins
from presscontroller.app.theme import muted, styled, text_style


def widget_dpr(widget: QWidget) -> float:
    """Physical pixels per logical pixel for ``widget``'s display."""
    return float(widget.devicePixelRatioF())


def to_pixmap(bgr: np.ndarray, dpr: float = 1.0) -> QPixmap:
    """BGR ndarray to QPixmap, tagged with the resolution it was rendered at."""
    h, w = bgr.shape[:2]
    img = QImage(bgr.data, w, h, 3 * w, QImage.Format.Format_BGR888)
    pix = QPixmap.fromImage(img.copy())
    if dpr != 1.0:
        pix.setDevicePixelRatio(dpr)
    return pix


class Coalescer:
    """Call ``fn(*payload)`` at most ``max_hz`` times a second; the newest wins.

    A plot render is tens of milliseconds of GUI thread, and rows arrive faster
    than it is worth drawing them. Dropping intermediate payloads costs nothing,
    because what is drawn is presentational — every row is recorded whatever the
    screen shows — provided the newest payload always wins and a trailing draw is
    guaranteed. The timer re-arms after a draw, so the rate is a real ceiling.
    """

    def __init__(self, fn, max_hz: float, parent=None):
        self._fn = fn
        self._max_hz = max(0.01, float(max_hz))
        self._pending: tuple | None = None
        self._timer = QTimer(parent)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timer)

    def set_rate(self, max_hz: float) -> None:
        """Change the ceiling, taking effect from the next draw.

        The timer in flight is left alone: it re-arms at the new rate when it
        fires, and cutting it short to apply a rate sooner is the one thing a
        ceiling must not do. Raising the rate therefore costs at most one
        interval of the old one, which nobody can see at these frequencies.
        """
        self._max_hz = max(0.01, float(max_hz))

    def post(self, *payload) -> None:
        self._pending = payload
        if self._timer.isActive():
            return
        self._fire()
        self._timer.start(max(1, int(1000.0 / self._max_hz)))

    def flush(self) -> None:
        """Draw whatever is waiting, now."""
        self._fire()

    def _on_timer(self) -> None:
        if self._pending is None:
            return
        self._fire()
        self._timer.start(max(1, int(1000.0 / self._max_hz)))

    def _fire(self) -> None:
        if self._pending is None:
            return
        payload, self._pending = self._pending, None
        self._fn(*payload)


Renderer = Callable[[tuple[int, int], int, StickyMargins], np.ndarray]


class PlotView(QLabel):
    """Shows whatever its renderer draws, re-rendered to the widget's size.

    Renders at device resolution: **both** the pixel size and the dpi scale with
    the display ratio, so the figure's apparent size is unchanged and it is simply
    drawn with more pixels (scaling only the size would shrink the labels).

    The view owns the plot's :class:`~presscontroller.app.plot.StickyMargins` and hands
    them to every render, so the axes box holds still while the run goes on
    instead of walking sideways each time a tick label changes width. They are
    only meaningful for one figure size, so a resize starts them over; the panel
    is rebuilt whenever the plot's definition changes, which starts them over too.
    """

    def __init__(self, placeholder: str):
        super().__init__(placeholder)
        self._render: Renderer | None = None
        self._margins = StickyMargins()
        self.setMinimumSize(320, 200)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Only ever seen before the first render and in any letterbox around the
        # figure, but it is still a surface with text on it, so it takes its two
        # colours from the palette and is re-taken on a scheme change. A fixed
        # white here was a white slab in a dark window.
        styled(self, lambda w: w.setStyleSheet(
            f"background: palette(base); color: {muted(w)};"))
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def show_plot(self, render: Renderer | None) -> None:
        self._render = render
        self._repaint()

    def resizeEvent(self, ev) -> None:
        self._margins.reset()
        self._repaint()
        super().resizeEvent(ev)

    def _repaint(self) -> None:
        if self._render is None:
            return
        dpr = widget_dpr(self)
        w, h = max(240, self.width()), max(160, self.height())
        img = self._render((round(w * dpr), round(h * dpr)), round(100 * dpr),
                           self._margins)
        self.setPixmap(to_pixmap(img, dpr))


#: The card look, from OpticalDistanceMeter's islands. Written in terms of
#: ``palette(...)`` rather than literal colours so Qt re-resolves it against
#: whichever scheme is in force when :func:`~presscontroller.app.theme.styled` sets it
#: again — and naming a background *and* a foreground together, which is the one
#: rule the theme module asks of every style here.
#:
#: ``base``, the same fill and the same corner the channel table has, because
#: they are the same thing: a panel the window puts its content in. The window's
#: own colour shows in the margin around them, and nowhere else (operator,
#: 2026-09-22). Anything given this look must therefore get :func:`island`
#: rather than its own sheet, or the two drift apart.
ISLAND_QSS = """
QFrame#island { background: palette(base); color: palette(text);
                border: 1px solid palette(mid); border-radius: 8px; }
"""

#: Lines of message an island shows before it scrolls. Three holds the longest
#: thing the window says — a device that failed, named, in the driver's own
#: words — and is a height the operator stops noticing.
MESSAGE_LINES = 3


def island(inner: QWidget, margins: tuple[int, int, int, int] = (4, 4, 4, 4)) -> QFrame:
    """Put ``inner`` in a card with the window's corner, border and fill.

    For a widget that draws its own frame — a table, a scroll area — the caller
    turns that frame off first: two borders a few pixels apart is what a card
    around a framed widget looks like. The margin is what lets the rounded
    corner be seen, so it is small but not nothing.
    """
    frame = QFrame()
    frame.setObjectName("island")
    root = QVBoxLayout(frame)
    root.setContentsMargins(*margins)
    root.setSpacing(0)
    root.addWidget(inner)
    return styled(frame, lambda w: w.setStyleSheet(ISLAND_QSS))


class MessageIsland(QFrame):
    """The card along the window's bottom edge: the next action, or what went wrong.

    A card rather than a bare line of text because this is the one part of the
    window that changes without being asked to, and it has to be findable at a
    glance — the same reason OpticalDistanceMeter gives its panels a message
    footer.

    It is :data:`MESSAGE_LINES` lines tall **always**, and scrolls past that
    rather than growing. A window that resizes its own status bar moves the plots
    the operator is watching, and it would do it exactly when something has gone
    wrong and the message got longer; a fixed height costs a little white space
    under a one-line message and never moves anything.

    ``label`` is the message itself, so a caller can colour it (``theme``) or read
    it back.
    """

    def __init__(self, parent=None, *, lines: int = MESSAGE_LINES):
        super().__init__(parent)
        self.setObjectName("island")
        self.lines = lines
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.label.setAutoFillBackground(False)

        self.scroll = QScrollArea()
        self.scroll.setWidget(self.label)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Never sideways: the text wraps, so a horizontal bar would mean the
        # island had been made narrower than one word, not that there is more to
        # read.
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The scroll area and its viewport paint nothing, so the card's own fill
        # shows through and there is one place that decides it. Turning
        # autoFillBackground off is not enough on its own: the style still fills
        # the viewport from its background role, which left the middle of the
        # island a different colour from its edges. `transparent` names no
        # colour, so the card's background/foreground pair still holds.
        styled(self.scroll, lambda w: w.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }"))
        self.scroll.viewport().setAutoFillBackground(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 6, 10, 6)
        root.setSpacing(0)
        root.addWidget(self.scroll)
        # Ignored across: a long message must not be able to widen the window,
        # which is what a label of unbreakable text would otherwise do.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        styled(self, lambda w: w.setStyleSheet(ISLAND_QSS))
        self.scroll.setFixedHeight(lines * self.label.fontMetrics().lineSpacing())

    def set_text(self, text: str) -> None:
        """Say ``text``, from its beginning.

        The scroll goes back to the top: a message left scrolled down from the
        previous one would open on its middle, and the first line is the one that
        says what happened.
        """
        self.label.setText(text)
        self.scroll.verticalScrollBar().setValue(0)

    def text(self) -> str:
        return self.label.text()


#: Clear space each side of a gauge's number, so it never touches the card's
#: border — the one thing that makes a very large digit look clipped.
READING_PAD = 4

#: How tall a gauge card asks to be, and the most it is ever drawn. **A gauge
#: does not take the column's spare height — the table does** (operator,
#: 2026-09-22): a card given the whole column sets a two-digit reading in
#: letters a hand high and leaves the channel list crushed above it, where the
#: room is worth more. This is about as tall as the number can usefully be
#: beside a table of the same width.
GAUGE_HEIGHT = 104

#: How short a gauge card may be squeezed where the window cannot hold them all.
#: Below this the number is smaller than the table's own text, at which point
#: the card is taking room to say something the table already said.
GAUGE_MIN_HEIGHT = 64

#: The card's clear space around its contents, and the gap between the caption
#: row and the number.
GAUGE_MARGINS = (10, 6, 10, 6)
GAUGE_SPACING = 2

#: How much wider the Reset button is than its text needs, and how far it stays
#: inside the card's top edge. It is drawn over the caption row rather than in
#: it (:class:`Gauge`), so these make it bigger without the row, or the number
#: under it, giving up a pixel.
RESET_EXTRA_WIDTH = 20
RESET_TOP_INSET = 2

#: The reading a gauge is sized for even while it is showing something shorter:
#: a sign, three digits and three decimals, which is the shape
#: the monitor gives an ordinary engineering
#: value. Without it a card opens showing a dash and sizes that dash to the whole
#: card, and the first real reading then shrinks it by a factor of ten — which
#: looks like a fault in the window rather than a number arriving.
READING_TEMPLATE = "-000.000"


def reading_template(decimals: int | None = None) -> str:
    """The full-width reading a card is sized for, in a gauge's own format.

    A gauge fixed at one decimal is never as wide as :data:`READING_TEMPLATE`,
    and sizing it for a number it cannot show would cost it the room for nothing.
    The three integer digits and the sign stay — they are what the reading may
    still grow into, and the grow-only rule means room not asked for now is a
    number that shrinks later.
    """
    if decimals is None:
        return READING_TEMPLATE
    head = READING_TEMPLATE.split(".")[0]
    return f"{head}.{'0' * decimals}" if decimals else head


class ReadingLabel(QLabel):
    """One number, drawn at the largest size that fits the room it is given.

    **The size may only fall between readings.** Fitting each reading afresh
    makes the digits breathe in and out as the value changes width, which is
    unreadable at the distance a gauge exists for — the same fault, and the same
    rule, as the plots' sticky margins
    (:class:`~presscontroller.app.plot.StickyMargins`). So a longer reading shrinks the
    number and a shorter one leaves it where it is, which settles within the
    first readings of a run. A card of a new size is a new fit, so it starts over
    there.

    :meth:`fit_for` is what stops that settling being visible: the label is sized
    for a reading the channel has not sent yet — a full-width one
    (:data:`READING_TEMPLATE`) — so it opens at the size it will keep instead of
    scaling a dash to the whole card and then collapsing.

    Its size policy is ``Ignored`` both ways: what is inside a gauge must never
    decide how wide the window is, and the card is what decides how tall.
    """

    #: Never smaller than this, even where the card cannot hold the reading. A
    #: number clipped at a legible size can still be read; one scaled to four
    #: pixels cannot, and says nothing about the card being too small.
    MIN_POINT = 9.0

    #: The size the text is measured at before being scaled to the room. Font
    #: metrics are near enough linear in point size for a first guess, and the
    #: loop below settles the rest.
    _PROBE = 96.0

    def __init__(self, placeholder: str = "–"):
        super().__init__(placeholder)
        # Right, like the table's Value column and for the same reason: the
        # digits a reading is read by are its last ones, and right-aligned they
        # stay put as the number gains and loses a figure, where centred every
        # digit shifts on every reading.
        self.setAlignment(Qt.AlignmentFlag.AlignRight
                          | Qt.AlignmentFlag.AlignVCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self._point = 0.0
        self._room = (0, 0)
        self._template = ""
        self._fitting = False

    def fit_for(self, text: str) -> None:
        """Also keep room for ``text``, whatever is being shown at the time."""
        self._template = text
        self._point = 0.0            # a wider string to fit is a fit to redo
        self._fit()

    def setText(self, text: str) -> None:
        super().setText(text)
        self._fit()

    def resizeEvent(self, ev) -> None:
        self._fit()
        super().resizeEvent(ev)

    def _fit(self) -> None:
        w = self.width() - 2 * READING_PAD
        h = self.height()
        shown = [t for t in (self.text(), self._template) if t]
        if self._fitting or w <= 0 or h <= 0 or not shown:
            return
        # The grow-only rule holds *for one size of card*. The room is checked
        # here rather than in resizeEvent alone because a resize is delivered
        # through the event queue, so a reading can arrive before it.
        if self._room != (w, h):
            self._room = (w, h)
            self._point = 0.0
        font = QFont(self.font())
        font.setPointSizeF(self._PROBE)
        metrics = QFontMetricsF(font)
        # The widest of what is shown and what is still to come, so the size is
        # the one this gauge will keep rather than the one this reading allows.
        advance = max(metrics.horizontalAdvance(t) for t in shown) or 1.0
        point = min(self._PROBE * w / advance,
                    self._PROBE * h / (metrics.height() or 1.0))
        if self._point:
            point = min(point, self._point)
        point = max(self.MIN_POINT, point)
        # The guess is linear and the metrics are not, so step down until it
        # really fits. Bounded by MIN_POINT, and after the first reading the
        # start is already the size that fitted the last one.
        while point > self.MIN_POINT:
            font.setPointSizeF(point)
            metrics = QFontMetricsF(font)
            if (max(metrics.horizontalAdvance(t) for t in shown) <= w
                    and metrics.height() <= h):
                break
            point -= 1.0
        self._point = point
        self._fitting = True
        try:
            fitted = QFont(self.font())
            fitted.setPointSizeF(point)
            self.setFont(fitted)
        finally:
            self._fitting = False


class Gauge(QFrame):
    """One reading, captioned, in a card of its own under the channel table.

    The table answers "what is every channel doing?" and a gauge answers "what is
    *this* number?" from across the room, which is why the answer was not to
    enlarge the table's own text: the table has to show every channel at once,
    and a font that carries that far would take the window (operator,
    2026-09-22).

    One card per gauge, in the card the table and the message island already use
    (:data:`ISLAND_QSS`), so the window has one fill, one border and one corner
    radius and the gauges do not read as a third kind of thing.

    **A card asks for :data:`GAUGE_HEIGHT` and never more**, so the spare height
    in the column goes to the channel table instead. It can be squeezed to
    :data:`GAUGE_MIN_HEIGHT` where the window cannot hold every card at full
    height, which is the one direction that costs nothing: the number simply
    gets smaller.

    The caption is bold through the **font**, never a stylesheet, for the reason
    a plot's heading is (a stylesheet would pin its colours).

    **A gauge showing a peak carries its own Reset** (:meth:`set_resettable`),
    beside its caption, rather than one button for every peak in the toolbar: the
    operator resets the number they are looking at, and a shared button reached
    peaks on gauges they were not (operator, 2026-09-23). ``reset_requested``
    carries nothing; the window knows which gauge a card is.
    """

    reset_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("island")
        self.caption = QLabel()
        caption_font = self.caption.font()
        caption_font.setBold(True)
        self.caption.setFont(caption_font)
        self.caption.setSizePolicy(QSizePolicy.Policy.Ignored,
                                   QSizePolicy.Policy.Preferred)
        self.note = QLabel()
        styled(self.note, lambda w: w.setStyleSheet(text_style(w, warn=True)))
        self.note.setVisible(False)
        self.reading = ReadingLabel()
        # **The button is drawn over the caption row, not laid out in it.** The
        # row keeps an empty slot the size of a plain tool button on every card,
        # shown or not: the button is taller than the caption, and a card that
        # alone had it gave its number less height, so the same reading came out
        # smaller than on the card beside it (operator, 2026-09-23). The button
        # itself is then made bigger than the slot — wider, and up into the
        # card's top margin and down into the gap above the number — which is
        # room nothing else uses, so neither the row nor the number moves.
        self.reset_btn = QToolButton(self)
        self.reset_btn.setText("Reset")
        self.reset_btn.clicked.connect(self.reset_requested.emit)
        self.reset_btn.setVisible(False)
        slot = self.reset_btn.sizeHint()
        self._reset_slot = QWidget()
        self._reset_slot.setFixedSize(slot.width() + RESET_EXTRA_WIDTH, slot.height())
        self._reset_slot.installEventFilter(self)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self.caption, 1)
        head.addWidget(self.note)
        head.addWidget(self._reset_slot)
        root = QVBoxLayout(self)
        root.setContentsMargins(*GAUGE_MARGINS)
        root.setSpacing(GAUGE_SPACING)
        root.addLayout(head)
        root.addWidget(self.reading, 1)
        # Ignored across, like the message island: a long reading must not be
        # able to widen the window. Down the column it asks for GAUGE_HEIGHT
        # (sizeHint) and is capped there, so the slack goes to the table.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(GAUGE_MIN_HEIGHT)
        self.setMaximumHeight(GAUGE_HEIGHT)
        styled(self, lambda w: w.setStyleSheet(ISLAND_QSS))

    def sizeHint(self) -> QSize:
        """The height a card asks for. Its contents cannot say: the reading
        inside has an ``Ignored`` policy precisely so that what it happens to
        show never decides how big the card is."""
        return QSize(super().sizeHint().width(), GAUGE_HEIGHT)

    def set_caption(self, text: str) -> None:
        self.caption.setText(text)

    def set_unit(self, unit: str, decimals: int | None = None) -> None:
        """Size the card for a full-width reading in ``unit``, before one comes.

        A gauge would otherwise open by fitting its dash to the whole card and
        shrink tenfold at the first reading, which reads as the window failing
        rather than the instrument answering. ``decimals`` is the gauge's own
        format, so a card is sized for the widest number *it* will show
        (:func:`reading_template`) rather than for the widest any gauge could.
        """
        self.reading.fit_for(f"{reading_template(decimals)} {unit}".strip())

    def set_note(self, text: str) -> None:
        """A channel this session does not have, said out loud — a gauge showing
        a dash for no stated reason reads as an instrument that has stopped."""
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def set_reading(self, text: str) -> None:
        self.reading.setText(text)

    def set_resettable(self, on: bool) -> None:
        """Show the card's Reset — for a gauge of a peak, which is the only kind
        there is anything to reset on."""
        self.reset_btn.setVisible(on)
        self._place_reset()

    def eventFilter(self, watched, event) -> bool:
        # The slot is where the layout put the room for the button, so the
        # button follows it whenever the layout moves or resizes it.
        if watched is self._reset_slot and event.type() in (QEvent.Type.Move,
                                                            QEvent.Type.Resize):
            self._place_reset()
        return super().eventFilter(watched, event)

    def _place_reset(self) -> None:
        """Lay the button over its slot, taller than the slot by the top margin
        (less a small inset) and the gap under the caption row."""
        g = self._reset_slot.geometry()
        top = RESET_TOP_INSET
        bottom = g.bottom() + GAUGE_SPACING
        self.reset_btn.setGeometry(g.left(), top, g.width(), bottom - top + 1)
        self.reset_btn.raise_()


class Switch(QAbstractButton):
    """An on/off switch: a sliding knob, its name, and **ON** or **OFF** in words.

    Asked for as "a switch, easy for everyone to understand" (operator,
    2026-10-19): the knob's side and colour say it at a glance, and the word says
    it to anyone who does not read switches. The colours are the palette's —
    highlight for on, mid for off — so it reads on either theme
    (:mod:`presscontroller.app.theme`).

    It is a checkable button, so ``toggled(bool)`` carries the new state.
    """

    TRACK_W, TRACK_H = 44, 22
    GAP = 8

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self._name = name
        self.setText(name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def state_text(self) -> str:
        return f"{self._name}: {'ON' if self.isChecked() else 'OFF'}"

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        widest = max(fm.horizontalAdvance(f"{self._name}: ON"),
                     fm.horizontalAdvance(f"{self._name}: OFF"))
        return QSize(self.TRACK_W + self.GAP + widest + 4,
                     max(self.TRACK_H, fm.height()) + 4)

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        enabled = self.isEnabled()
        on = self.isChecked()
        track = pal.color(QPalette.ColorRole.Highlight if on else QPalette.ColorRole.Mid)
        if not enabled:
            track = QColor(track)
            track.setAlpha(90)
        y = (self.height() - self.TRACK_H) / 2
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(0, y, self.TRACK_W, self.TRACK_H, self.TRACK_H / 2, self.TRACK_H / 2)
        d = self.TRACK_H - 6
        x = self.TRACK_W - d - 3 if on else 3
        p.setBrush(pal.color(QPalette.ColorRole.Base))
        p.drawEllipse(int(x), int(y + 3), d, d)
        p.setPen(pal.color(QPalette.ColorGroup.Active if enabled else QPalette.ColorGroup.Disabled,
                           QPalette.ColorRole.WindowText))
        f = self.font()
        f.setBold(on)
        p.setFont(f)
        p.drawText(self.TRACK_W + self.GAP, 0, self.width() - self.TRACK_W - self.GAP,
                   self.height(), Qt.AlignmentFlag.AlignVCenter, self.state_text())
        p.end()
