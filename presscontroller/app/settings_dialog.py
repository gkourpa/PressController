"""The settings, in one dialog of four tabs: General, Connection, Test, Plot.

As DAqReader's settings dialog: it edits the :class:`Settings` it is given, and
only OK saves (``settings`` holds the result; after Cancel it is what was passed
in). The theme takes effect at once on OK, as DAqReader's does.

* **General** — the theme (system, light, dark), the screen's redraw ceiling,
  and the files: the data folder (chosen here; used from the next start) and
  the press file in use (shown, with its folder a click away, to be edited).
* **Connection** — control mode's port, and whether it connects by itself.
* **Test** — Proteus' test template (docs/motion.md): Peak, break detection and
  its threshold, the start load, the ramps and the measuring interval; what the
  control window's switches and ramp start from, and what START sends.
* **Plot** — the force–displacement plot's axes (fitted, or a fixed range) and
  its colour, as DAqReader's plot dialog has them.

Every value is limited to the range a settings file may hold
(:mod:`presscontroller.config.settings`). The ramp's speed is not limited here:
the press file's ``[limits]`` are, and START refuses a ramp above them, saying
so — in visible text here, not a tooltip.

The serial ports offered come from :meth:`SettingsDialog._ports`, the colour
from :meth:`SettingsDialog._ask_colour` and the folder from
:meth:`SettingsDialog._ask_folder`, methods so a test can stub them.
"""

from __future__ import annotations

from dataclasses import replace

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from presscontroller.app.theme import apply_theme, muted, styled
from presscontroller.config.settings import (
    MAX_BREAK_THRESHOLD,
    MAX_INTERVAL_MS,
    MAX_REFRESH_HZ,
    MAX_START_LOAD,
    MIN_BREAK_THRESHOLD,
    MIN_INTERVAL_MS,
    MIN_REFRESH_HZ,
    MIN_START_LOAD,
    RAMP_CONTROL_LABELS,
    RAMP_CONTROLS,
    THEME_LABELS,
    THEMES,
    PlotSettings,
    Settings,
    TemplateSettings,
    save_settings,
)

#: The tabs, in order, by name — :meth:`SettingsDialog.show_tab` takes these.
TABS = ("General", "Connection", "Test", "Plot")

RANGE_LIMIT = 1e9
RANGE_DECIMALS = 3


def _spin(lo: float, hi: float, value: float, decimals: int, step: float, suffix: str):
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setSuffix(suffix)
    box.setValue(value)
    return box


def _note(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    styled(lbl, lambda w: w.setStyleSheet(f"color: {muted(w)};"))
    return lbl


def _page(form: QFormLayout, note: str | None = None) -> QWidget:
    page = QWidget()
    col = QVBoxLayout(page)
    col.addLayout(form)
    if note:
        col.addWidget(_note(note))
    col.addStretch(1)
    return page


class AxisRange(QWidget):
    """Auto, or a typed low and high, for one axis — DAqReader's widget of the
    same name (from OpticalDistanceMeter). ``value()`` is ``None`` for auto and
    for an inverted or empty pair, so a half-typed range fits the data instead
    of drawing an empty frame."""

    changed = Signal()

    def __init__(self, rng: tuple[float, float] | None):
        super().__init__()
        self.auto = QCheckBox("Auto")
        self.lo = QDoubleSpinBox()
        self.hi = QDoubleSpinBox()
        for spin, start in ((self.lo, 0.0), (self.hi, 1.0)):
            spin.setRange(-RANGE_LIMIT, RANGE_LIMIT)
            spin.setDecimals(RANGE_DECIMALS)
            spin.setValue(start)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.auto)
        row.addWidget(self.lo, 1)
        row.addWidget(QLabel("to"))
        row.addWidget(self.hi, 1)
        self.auto.setChecked(rng is None)
        if rng is not None:
            self.lo.setValue(float(rng[0]))
            self.hi.setValue(float(rng[1]))
        self._on_auto(rng is None)
        self.auto.toggled.connect(self._on_auto)

    def _on_auto(self, on: bool) -> None:
        self.lo.setEnabled(not on)
        self.hi.setEnabled(not on)
        self.changed.emit()

    def value(self) -> tuple[float, float] | None:
        if self.auto.isChecked():
            return None
        lo, hi = self.lo.value(), self.hi.value()
        return (lo, hi) if hi > lo else None


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, *, save=save_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PressController — settings")
        self.settings = settings
        self._save = save
        self._data_dir = settings.data_dir
        t = settings.test

        # ---- General ---------------------------------------------------------
        self.theme = QComboBox()
        for name in THEMES:
            self.theme.addItem(THEME_LABELS[name], name)
        self.theme.setCurrentIndex(max(0, self.theme.findData(settings.theme)))
        self.refresh = _spin(MIN_REFRESH_HZ, MAX_REFRESH_HZ, settings.refresh_hz, 1, 0.5, " Hz")
        self.data_dir = QLabel(settings.data_dir or "–")
        self.data_dir.setWordWrap(True)
        data_btn = QPushButton("Choose…")
        data_btn.clicked.connect(self._choose_data_dir)
        data_row = QHBoxLayout()
        data_row.addWidget(self.data_dir, 1)
        data_row.addWidget(data_btn)
        self.press_file = QLabel(settings.press_file or "–")
        self.press_file.setWordWrap(True)
        press_btn = QPushButton("Show…")
        press_btn.setEnabled(bool(settings.press_file))
        press_btn.clicked.connect(self._show_press_folder)
        press_row = QHBoxLayout()
        press_row.addWidget(self.press_file, 1)
        press_row.addWidget(press_btn)
        self.debug_mode = QCheckBox("Debug mode: record every byte of each session "
                                    "(captures folder)")
        self.debug_mode.setChecked(settings.debug_mode)
        general = QFormLayout()
        general.addRow("Theme", self.theme)
        general.addRow("Screen redraws at most", self.refresh)
        general.addRow("Data folder", data_row)
        general.addRow("Press file", press_row)
        general.addRow(self.debug_mode)

        # ---- Connection ------------------------------------------------------
        self.port = QComboBox()
        self.port.setEditable(True)
        names = self._ports()
        if settings.control_port and settings.control_port not in names:
            names.insert(0, settings.control_port)
        self.port.addItems(names)
        self.port.setCurrentText(settings.control_port)
        self.auto_connect = QCheckBox("Connect to the controller as soon as control mode opens")
        self.auto_connect.setChecked(settings.auto_connect)
        connection = QFormLayout()
        connection.addRow("Control mode's port", self.port)
        connection.addRow(self.auto_connect)

        # ---- Test: Proteus' template ----------------------------------------
        self.peak = QCheckBox("Peak")
        self.peak.setChecked(t.peak)
        self.break_detection = QCheckBox("Break detection")
        self.break_detection.setChecked(t.break_detection)
        self.threshold = _spin(MIN_BREAK_THRESHOLD, MAX_BREAK_THRESHOLD,
                               t.break_threshold_per_mil, 1, 1.0, " ‰")
        self.start_load = _spin(MIN_START_LOAD, MAX_START_LOAD, t.start_load_percent, 2, 0.01,
                                " % of the force range")
        self.control = QComboBox()
        for name in RAMP_CONTROLS:
            self.control.addItem(RAMP_CONTROL_LABELS[name], name)
        self.control.setCurrentIndex(max(0, self.control.findData(t.ramp_control)))
        self.path_speed = _spin(0.01, 1000.0, t.path_speed_mm_min, 3, 0.5, " mm/min")
        self.path_end = _spin(0.001, 10000.0, t.path_end_mm, 3, 1.0, " mm")
        self.force_speed = _spin(0.001, 1000.0, t.force_speed_kn_s, 3, 0.5, " kN/s")
        self.force_end = _spin(0.1, 100000.0, t.force_end_kn, 1, 10.0, " kN")
        self.interval = QSpinBox()
        self.interval.setRange(MIN_INTERVAL_MS, MAX_INTERVAL_MS)
        self.interval.setSingleStep(10)
        self.interval.setSuffix(" ms")
        self.interval.setValue(t.measuring_interval_ms)
        self.idle_interval = QSpinBox()
        self.idle_interval.setRange(MIN_INTERVAL_MS, MAX_INTERVAL_MS)
        self.idle_interval.setSingleStep(10)
        self.idle_interval.setSuffix(" ms")
        self.idle_interval.setValue(t.idle_interval_ms)
        test = QFormLayout()
        test.addRow(self.peak)
        test.addRow(self.break_detection)
        test.addRow("Break threshold", self.threshold)
        test.addRow("Start load", self.start_load)
        test.addRow("Ramp control", self.control)
        test.addRow("Path ramp: speed", self.path_speed)
        test.addRow("Path ramp: end", self.path_end)
        test.addRow("Force ramp: speed", self.force_speed)
        test.addRow("Force ramp: end", self.force_end)
        test.addRow("Measuring interval before the ramp", self.idle_interval)
        test.addRow("Measuring interval during the ramp", self.interval)

        # ---- Plot ----------------------------------------------------------------
        self.x_range = AxisRange(settings.plot.xlim)
        self.y_range = AxisRange(settings.plot.ylim)
        self._colour = settings.plot.colour
        self.colour_btn = QPushButton("Colour…")
        self.colour_btn.clicked.connect(self._choose_colour)
        self._show_colour()
        plot = QFormLayout()
        plot.addRow("Displacement axis", self.x_range)
        plot.addRow("Force axis", self.y_range)
        plot.addRow("Curve colour", self.colour_btn)

        self.tabs = QTabWidget()
        self.tabs.addTab(_page(general, "The theme takes effect at once. The redraw rate is "
                                        "a ceiling, not a target: every reading is taken in "
                                        "whatever the screen shows. A new data folder is "
                                        "used from the next start, as is debug mode. The "
                                        "tests are always saved. The press file holds the "
                                        "press's channels and limits; edit it in a text "
                                        "editor and restart."), TABS[0])
        self.tabs.addTab(_page(connection, "Any port name may be typed. Connecting first "
                                           "listens for 1.5 s and refuses if something "
                                           "else — the old PC — is talking to the "
                                           "controller."), TABS[1])
        self.tabs.addTab(_page(test, "Peak and Break detection are also the control "
                                     "window's switches; a flip there is remembered here. "
                                     "START refuses a ramp faster than the press file's "
                                     "[limits] and says so. The measuring intervals are "
                                     "rounded to 10 ms; 100 ms is the fastest the "
                                     "controller has been seen to send."), TABS[2])
        self.tabs.addTab(_page(plot, "Auto fits the axis to the test's data; a fixed range "
                                     "keeps it still while the test runs."), TABS[3])

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addWidget(self.tabs)
        root.addWidget(buttons)
        self.resize(540, self.sizeHint().height())

    def show_tab(self, name: str) -> "SettingsDialog":
        self.tabs.setCurrentIndex(TABS.index(name))
        return self

    def _ports(self) -> list[str]:
        """The serial ports Windows knows of now."""
        try:
            from serial.tools import list_ports
            return sorted(p.device for p in list_ports.comports())
        except Exception:
            return []

    # ---- the files, the folder picker stubbed in tests -----------------------

    def _ask_folder(self, initial: str) -> str:
        return QFileDialog.getExistingDirectory(self, "Data folder", initial)

    def _choose_data_dir(self) -> None:
        chosen = self._ask_folder(self.settings.data_dir)
        if chosen:
            self._data_dir = str(Path(chosen))
            self.data_dir.setText(self._data_dir)

    def _show_press_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.settings.press_file).parent)))

    # ---- the colour, its picker stubbed in tests -----------------------------

    def _ask_colour(self, initial: str) -> str:
        c = QColorDialog.getColor(QColor(initial), self, "Curve colour")
        return c.name() if c.isValid() else ""

    def _choose_colour(self) -> None:
        chosen = self._ask_colour(self._colour)
        if chosen:
            self._colour = chosen
            self._show_colour()

    def _show_colour(self) -> None:
        self.colour_btn.setText(f"  {self._colour}  ")
        self.colour_btn.setStyleSheet(
            f"QPushButton {{ background: {self._colour}; color: "
            f"{'#000' if QColor(self._colour).lightness() > 140 else '#fff'}; }}")

    def _accept(self) -> None:
        def tens(ms: int) -> int:
            return min(MAX_INTERVAL_MS, max(MIN_INTERVAL_MS, int(round(ms / 10.0)) * 10))

        test = TemplateSettings(
            peak=self.peak.isChecked(),
            break_detection=self.break_detection.isChecked(),
            break_threshold_per_mil=round(self.threshold.value(), 1),
            start_load_percent=round(self.start_load.value(), 2),
            ramp_control=self.control.currentData(),
            path_speed_mm_min=self.path_speed.value(),
            path_end_mm=self.path_end.value(),
            force_speed_kn_s=self.force_speed.value(),
            force_end_kn=self.force_end.value(),
            measuring_interval_ms=tens(self.interval.value()),
            idle_interval_ms=tens(self.idle_interval.value()))
        self.settings = replace(
            self.settings, refresh_hz=float(self.refresh.value()),
            theme=self.theme.currentData(), data_dir=self._data_dir,
            debug_mode=self.debug_mode.isChecked(),
            control_port=self.port.currentText().strip(),
            auto_connect=self.auto_connect.isChecked(), test=test,
            plot=PlotSettings(xlim=self.x_range.value(), ylim=self.y_range.value(),
                              colour=self._colour))
        self._save(self.settings)
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self.settings.theme)
        self.accept()
