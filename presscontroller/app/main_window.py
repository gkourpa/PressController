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
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QAction, QFontDatabase, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from presscontroller.app.identity import DISPLAY_NAME
from presscontroller.app.settings_dialog import SettingsDialog
from presscontroller.app.plot import render_force_displacement
from presscontroller.app.theme import styled, text_style
from presscontroller.app.widgets import Coalescer, Gauge, MessageIsland, PlotView, island
from presscontroller.config.settings import Settings, save_settings
from presscontroller.monitor import Monitor, write_test_csv
from presscontroller.protocol import PC_TO_CTRL, rate_text

#: How often the source is polled. Lines are timestamped when they arrive, not
#: when they are polled, so this only sets how soon the window shows them.
TICK_MS = 50

#: The screen's redraw ceiling, in hertz, when no settings are given — the
#: global setting ``refresh_hz`` otherwise, as in DAqReader.
REFRESH_HZ = 2.0

#: Lines the status card's ramp line always takes, and the log below the plot.
RAMP_LINES = 4
LOG_LINES = 3

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
                 settings: Settings | None = None, save=save_settings, parent=None):
        super().__init__(parent)
        self.settings = settings if settings is not None else Settings(refresh_hz=REFRESH_HZ)
        self._save = save
        self.monitor = monitor
        self.source = source
        self.tests_dir = tests_dir
        self.saved: list[Path] = []
        self._logged = 0
        self._ramp_warn: bool | None = None
        self._last_error_count = 0
        press = monitor.press
        self.setWindowTitle(" — ".join(x for x in (DISPLAY_NAME, press.name, self.mode_title)
                                       if x))

        # ---- status card ---------------------------------------------------
        self.link_lbl = QLabel("–")
        self.phase_lbl = QLabel("–")
        self.ramp_lbl = QLabel("–")
        self.ramp_lbl.setWordWrap(True)
        self.ramp_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        # Four lines always: a ramp line that grew and shrank with its text moved
        # every gauge under it (operator, 2026-10-20).
        self.ramp_lbl.setFixedHeight(RAMP_LINES * self.ramp_lbl.fontMetrics().lineSpacing())
        self.rate_lbl = QLabel("–")
        self.test_lbl = QLabel("–")
        status = QWidget()
        grid = QGridLayout(status)
        grid.setContentsMargins(10, 6, 10, 6)
        for row, (name, lbl) in enumerate([("Link", self.link_lbl),
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
        # The log is LOG_LINES tall, fixed: the plot takes the rest (operator,
        # 2026-10-20 — no splitter to drag).
        m = self.log_view.contentsMargins()
        self.log_view.setFixedHeight(LOG_LINES * self.log_view.fontMetrics().lineSpacing()
                                     + 2 * int(self.log_view.document().documentMargin())
                                     + m.top() + m.bottom() + 2)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(island(self.plot_view), 1)
        right.addWidget(island(self.log_view))

        body = QHBoxLayout()
        body.addWidget(left_w)
        body.addLayout(right, 1)
        self.message = MessageIsland(lines=1)
        root = QVBoxLayout()
        self._root = root
        """The window's outer column, so a mode can put its own bar on top."""
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
        self.settings_action = QAction("Settings…", self)
        self.settings_action.triggered.connect(self.open_settings)
        menu = self.menuBar().addMenu("File")
        menu.addAction(save)
        menu.addAction(open_dir)
        menu.addSeparator()
        menu.addAction(self.settings_action)
        menu.addSeparator()
        menu.addAction(quit_)
        self.full_screen_action = QAction("Full screen", self)
        self.full_screen_action.setShortcut(QKeySequence(Qt.Key.Key_F11))
        self.full_screen_action.setCheckable(True)
        self.full_screen_action.triggered.connect(self.toggle_full_screen)
        plot_settings = QAction("Plot settings…", self)
        plot_settings.triggered.connect(lambda: self.open_settings("Plot"))
        view = self.menuBar().addMenu("View")
        view.addAction(self.full_screen_action)
        view.addAction(plot_settings)

        self._base_message = self.intro()
        self.say(self._base_message)
        self._display = Coalescer(self._show, self.settings.refresh_hz, self)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.tick)

    #: What the title bar calls this window's mode.
    mode_title = "monitor (listen-only)"

    def intro(self) -> str:
        """What the message island says first: the mode and the source."""
        return (f"Monitor only: {self.source.describe()}. Nothing is sent to the press; "
                "Proteus stays in control.")

    def port_lost(self, error: str) -> str:
        return (f"{error}. The monitor has stopped hearing that direction; Proteus and the "
                "press are not affected.")

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
            self.say(self.port_lost(self.source.errors[-1]), error=True)
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
            mark = "" if e.known else "!! not in the protocol notes"
            # A known line is shown without its padding (the controller's
            # report is indented); a line not in the notes exactly as it came.
            text = e.text.strip() if e.known else e.text
            self.log_view.appendPlainText(
                f"{e.wall:%H:%M:%S.%f}"[:-3] + f"  {arrow}  {text:<26} {e.meaning}{mark}")

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
                settled = test.ramp_seconds >= 2
                ch = press.channel(r.channel)
                if m.ramp_decoded(test):
                    unit, places = ch.unit, ch.decimals
                    measured = m.ramp_measured(test)
                    text = f"{ch.name} control: set {rate_text(r.rate, unit)}"
                    text += (f" · measured {rate_text(measured, unit)} "
                             f"({test.ramp_seconds:.0f} s)"
                             if measured is not None and settled else " · measuring…")
                    text += (f"\nto {r.end_value:.{places}f} {unit}; start sent "
                             f"{r.start_value:.{places}f} {unit}")
                    if r.channel == m.path_index and test.ramp_from_mm is not None:
                        text += f", piston was at {test.ramp_from_mm:.3f} mm"
                    elif test.ramp_mm_min is not None and settled:
                        text += f"; path {test.ramp_mm_min:.2f} mm/min"
                else:
                    name = ch.name if ch else f"channel {r.channel}"
                    text = f"{name} control (not decoded yet): speed field {r.speed}"
                    text += f"\nstart field {r.start}, end field {r.end}"
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
        ps = self.settings.plot
        self.plot_view.show_plot(lambda size, dpi, margins: render_force_displacement(
            fd.displacement, fd.force, peak=fd.peak, displacement_label=x_lbl,
            force_label=f_lbl, units=(unit, force.unit if force else ""), title=title,
            size_px=size, dpi=dpi, margins=margins, xlim=ps.xlim, ylim=ps.ylim,
            colour=ps.colour))

    # ---- settings ----------------------------------------------------------

    def open_settings(self, tab: str = "General") -> None:
        dlg = SettingsDialog(self.settings, save=self._save, parent=self).show_tab(tab)
        if dlg.exec():
            self.apply_settings(dlg.settings)

    def apply_settings(self, settings: Settings) -> None:
        """Take new settings into use: the redraw rate and the plot."""
        self.settings = settings
        self._display.set_rate(settings.refresh_hz)
        self._display.post()

    # ---- the window's place ------------------------------------------------

    def restore_place(self) -> None:
        """Open where and as the window was left: size, position, maximized or
        full screen (Qt's saved geometry, kept in the settings)."""
        g = self.settings.window_geometry
        if not g or not self.restoreGeometry(QByteArray.fromBase64(g.encode("ascii"))):
            self.resize(1400, 860)
        self.full_screen_action.setChecked(self.isFullScreen())

    def show_in_place(self) -> None:
        """Show the window as :meth:`restore_place` left it."""
        if self.isFullScreen():
            self.showFullScreen()
        elif self.isMaximized():
            self.showMaximized()
        else:
            self.show()

    def toggle_full_screen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()
        self.full_screen_action.setChecked(self.isFullScreen())

    def _remember_place(self) -> None:
        geometry = bytes(self.saveGeometry().toBase64()).decode("ascii")
        if geometry != self.settings.window_geometry:
            self.settings = replace(self.settings, window_geometry=geometry)
            try:
                self._save(self.settings)
            except OSError:
                pass            # a place not remembered costs a resize, nothing more

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
        self._remember_place()
        self._timer.stop()
        # A test still open when the window closes is kept too: closing the
        # monitor must not be how a test gets lost.
        test = self.monitor.current
        if test is not None and test.t:
            self._autosave(test)
        self.source.close()
        super().closeEvent(ev)
