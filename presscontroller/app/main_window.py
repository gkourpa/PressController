"""The monitor's one window: readings, the test's phase, its plot and the log.

**Listen-only, and it says so.** The window has no control that could send
anything to the press: the tap it reads from cannot write
(:mod:`presscontroller.tap.serial_tap`). The message island names the source on
every launch so a replay is never mistaken for the press.

Layout, left to right as the operator reads it:

* the **status card** — is Proteus connected, what phase the test is in, the
  ramp that was sent and what it means;
* one **gauge** per channel of the press file, and the test's **peak force**;
* the **plot** — force against displacement of the newest test — and the
  **log** of every command and event heard.

Each tick polls the source, feeds every line to the monitor and saves any test
the monitor has closed — **taking in data never waits for the screen**. What is
shown — readings, status, plot and log — is redrawn through one
:class:`~presscontroller.app.widgets.Coalescer` at no more than ``refresh_hz``
(:data:`REFRESH_HZ`, 2 Hz): the stream is ten lines a second, and a number
changing faster than it can be read is worse than one that does not (operator,
2026-10-19, as DAqReader's ``refresh_hz``). The newest data always wins and a
trailing redraw is guaranteed, so what is on screen is never more than one
interval old. A message — a warning, a lost port — is said at once.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFontDatabase
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from presscontroller.app.identity import DISPLAY_NAME
from presscontroller.app.plot import render_force_displacement
from presscontroller.app.theme import styled, text_style
from presscontroller.app.widgets import Coalescer, Gauge, MessageIsland, PlotView, island
from presscontroller.monitor import Monitor, write_test_csv
from presscontroller.protocol import PC_TO_CTRL

#: How often the source is polled. Lines are timestamped when they arrive, not
#: when they are polled, so this only sets how soon the window shows them.
TICK_MS = 50

#: The screen's redraw ceiling, in hertz — readings, status, plot and log
#: alike. DAqReader's default for its ``refresh_hz``; it becomes a global
#: setting the same way, and until then is the window's ``refresh_hz`` argument.
REFRESH_HZ = 2.0

#: Width of the reading column. The gauges hold a five-figure force and its
#: unit at a size readable from the press.
LEFT_WIDTH = 340


def _template(rng: float, decimals: int, unit: str) -> str:
    """The widest reading a channel of this range shows, to size its card for."""
    digits = len(str(int(abs(rng)))) or 1
    body = "0" * digits + ("." + "0" * decimals if decimals else "")
    return f"-{body} {unit}".strip()


class MainWindow(QMainWindow):
    def __init__(self, monitor: Monitor, source, *, tests_dir: Path | None = None,
                 refresh_hz: float = REFRESH_HZ, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.source = source
        self.tests_dir = tests_dir
        self.saved: list[Path] = []
        self._logged = 0
        self._ramp_warn: bool | None = None
        self._last_error_count = 0
        press = monitor.press
        self.setWindowTitle(f"{DISPLAY_NAME} — {press.name} — monitor (listen-only)")

        # ---- status card ---------------------------------------------------
        self.link_lbl = QLabel("–")
        self.phase_lbl = QLabel("–")
        self.ramp_lbl = QLabel("–")
        self.ramp_lbl.setWordWrap(True)
        self.rate_lbl = QLabel("–")
        self.test_lbl = QLabel("–")
        status = QWidget()
        grid = QGridLayout(status)
        grid.setContentsMargins(10, 6, 10, 6)
        for row, (name, lbl) in enumerate([("Proteus", self.link_lbl),
                                           ("Phase", self.phase_lbl),
                                           ("Test", self.test_lbl),
                                           ("Ramp", self.ramp_lbl),
                                           ("Rates", self.rate_lbl)]):
            head = QLabel(name)
            f = head.font()
            f.setBold(True)
            head.setFont(f)
            grid.addWidget(head, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(lbl, row, 1)
        grid.setColumnStretch(1, 1)

        # ---- gauges --------------------------------------------------------
        self.gauges: dict[int, Gauge] = {}
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(island(status))
        for ch in press.channels:
            g = Gauge()
            g.set_caption(ch.name)
            g.reading.fit_for(_template(ch.range, ch.decimals, ch.unit))
            self.gauges[ch.index] = g
            left.addWidget(g)
        self.peak_gauge = Gauge()
        self.peak_gauge.set_caption("Peak force, this test")
        force = press.channel(monitor.force_index) if monitor.force_index is not None else None
        if force is not None:
            self.peak_gauge.reading.fit_for(_template(force.range, force.decimals, force.unit))
        left.addWidget(self.peak_gauge)
        left.addStretch(1)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(LEFT_WIDTH)

        # ---- plots and log -------------------------------------------------
        self.plot_view = PlotView("waiting for data")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        mono.setFamilies(["Consolas", mono.family()])
        self.log_view.setFont(mono)
        self.log_view.setFrameShape(QFrame.Shape.NoFrame)
        self.log_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(island(self.plot_view))
        right.addWidget(island(self.log_view))
        right.setStretchFactor(0, 3)
        right.setStretchFactor(1, 1)

        body = QHBoxLayout()
        body.addWidget(left_w)
        body.addWidget(right, 1)
        self.message = MessageIsland()
        root = QVBoxLayout()
        root.addLayout(body, 1)
        root.addWidget(self.message)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)

        save = QAction("Save newest test as CSV…", self)
        save.triggered.connect(self.save_newest_as)
        open_dir = QAction("Open the tests folder", self)
        open_dir.triggered.connect(self.open_tests_dir)
        open_dir.setEnabled(tests_dir is not None)
        quit_ = QAction("Quit", self)
        quit_.triggered.connect(self.close)
        menu = self.menuBar().addMenu("File")
        menu.addAction(save)
        menu.addAction(open_dir)
        menu.addSeparator()
        menu.addAction(quit_)

        self._base_message = (f"Monitor only: {source.describe()}. Nothing is sent to the "
                              "press; Proteus stays in control.")
        self.say(self._base_message)
        self._display = Coalescer(self._show, refresh_hz, self)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)
        self.resize(1400, 860)

    # ---- running -----------------------------------------------------------

    def start(self) -> None:
        self.source.start()
        self._timer.start(TICK_MS)

    def say(self, text: str, *, warn: bool = False, error: bool = False) -> None:
        self.message.set_text(text)
        styled(self.message.label,
               lambda w, e=error, x=warn: w.setStyleSheet(text_style(w, error=e, warn=x)))

    def tick(self) -> None:
        events = self.source.poll()
        notices = []
        for ev in events:
            notices += self.monitor.feed(ev)
        for test in self.monitor.pop_closed():
            self._autosave(test)
        if self.source.errors and len(self.source.errors) != self._last_error_count:
            self._last_error_count = len(self.source.errors)
            self.say(self.source.errors[-1] + ". The monitor has stopped hearing that "
                     "direction; Proteus and the press are not affected.", error=True)
        elif notices:
            n = notices[-1]
            self.say(n.text, warn=n.warn)
        if events:
            self._display.post()

    def _show(self) -> None:
        """Bring everything on screen up to the monitor's state."""
        self._append_log()
        self._refresh()
        self._draw_plots()

    def _append_log(self) -> None:
        # Counted by entries ever logged, not by the log's length: the log keeps
        # only its newest entries, so once full its length stops growing.
        m = self.monitor
        fresh = min(m.log_total - self._logged, len(m.log))
        self._logged = m.log_total
        for e in (list(m.log)[-fresh:] if fresh > 0 else []):
            arrow = "PC → CTRL" if e.direction == PC_TO_CTRL else "CTRL → PC"
            mark = "" if e.known else "  !! not in the protocol notes"
            self.log_view.appendPlainText(
                f"{e.wall:%H:%M:%S.%f}"[:-3] + f"  {arrow}  {e.text:<26} {e.meaning}{mark}")

    def _refresh(self) -> None:
        m = self.monitor
        press = m.press
        if m.proteus:
            link = "connected (PC mode)"
        elif m.streaming:
            link = "streaming"
        else:
            link = "not connected"
        if m.streaming and m.interval_ms:
            link += f", data every {m.interval_ms} ms"
        self.link_lbl.setText(link)
        self.phase_lbl.setText(m.phase.value)
        test = m.last
        if test is None:
            self.test_lbl.setText("none yet")
            self.ramp_lbl.setText("–")
        else:
            state = "running" if not test.closed else f"over ({test.close_reason})"
            self.test_lbl.setText(f"#{test.number}, START at {test.started:%H:%M:%S}, {state}")
            if test.ramp is None:
                self.ramp_lbl.setText("not sent yet")
            else:
                r = test.ramp
                text = (f"{r.speed_mm_min:.3g} mm/min to {r.end_um / 1000:.3f} mm "
                        f"(sent start {r.start_um / 1000:.3f} mm)")
                if test.warnings:
                    text += "\nWarning: " + test.warnings[-1]
                self.ramp_lbl.setText(text)
            if self._ramp_warn != bool(test.warnings):
                self._ramp_warn = bool(test.warnings)
                styled(self.ramp_lbl, lambda w, bad=self._ramp_warn:
                       w.setStyleSheet(text_style(w, warn=bad)))
        parts = []
        dp = m.rate(m.path_index)
        if dp is not None:
            parts.append(f"path {dp * 60:+.2f} mm/min")
        df = m.rate(m.force_index)
        if df is not None:
            parts.append(f"force {df:+.1f} kN/s")
        self.rate_lbl.setText(" · ".join(parts) or "–")
        for idx, g in self.gauges.items():
            ch = press.channel(idx)
            v = m.latest_value(idx)
            g.set_reading("–" if v is None else f"{v:.{ch.decimals}f} {ch.unit}")
        pk = m.peak(test)
        force = press.channel(m.force_index) if m.force_index is not None else None
        if pk is None or force is None:
            self.peak_gauge.set_reading("–")
        else:
            self.peak_gauge.set_reading(f"{pk[0]:.{force.decimals}f} {force.unit}")

    def _draw_plots(self) -> None:
        """Force against displacement of the newest test
        (:meth:`~presscontroller.monitor.Monitor.force_displacement`)."""
        m = self.monitor
        test = m.last
        press = m.press
        force = press.channel(m.force_index) if m.force_index is not None else None
        path = press.channel(m.path_index) if m.path_index is not None else None
        f_lbl = f"{force.name} ({force.unit})" if force else "Force"
        unit = path.unit if path else "mm"
        fd = m.force_displacement(test)
        x_lbl = (f"Displacement since start load ({unit})" if fd.origin is not None
                 else f"Displacement ({unit})")
        title = f"Test {test.number}, {test.started:%Y-%m-%d %H:%M:%S}" if test else ""
        self.plot_view.show_plot(lambda size, dpi, margins: render_force_displacement(
            fd.displacement, fd.force, peak=fd.peak, displacement_label=x_lbl,
            force_label=f_lbl, units=(unit, force.unit if force else ""), title=title,
            size_px=size, dpi=dpi, margins=margins))

    # ---- saving ------------------------------------------------------------

    def _autosave(self, test) -> None:
        """Every closed test is written to the tests folder, if there is one."""
        if self.tests_dir is None or not test.t:
            return
        try:
            path = write_test_csv(self.monitor, test, self.tests_dir,
                                  source=self.source.describe())
        except OSError as exc:
            self.say(f"Test {test.number} could not be saved: {exc}", error=True)
            return
        self.saved.append(path)
        self.say(f"Test {test.number} saved: {path}")

    def save_newest_as(self) -> None:
        test = self.monitor.last
        if test is None or not test.t:
            QMessageBox.information(self, DISPLAY_NAME, "No test has been heard yet.")
            return
        folder = QFileDialog.getExistingDirectory(self, "Save the newest test into…",
                                                  str(self.tests_dir or Path.home()))
        if not folder:
            return
        path = write_test_csv(self.monitor, test, folder, source=self.source.describe())
        self.say(f"Test {test.number} saved: {path}")

    def open_tests_dir(self) -> None:
        if self.tests_dir is not None:
            self.tests_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(self.tests_dir)        # noqa: S606 - Windows only, by design

    def closeEvent(self, ev) -> None:
        self._timer.stop()
        # A test still open when the window closes is kept too: closing the
        # monitor must not be how a test gets lost.
        test = self.monitor.current
        if test is not None and test.t:
            self._autosave(test)
        self.source.close()
        super().closeEvent(ev)
