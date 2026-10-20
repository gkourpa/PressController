"""The settings, in one dialog: the screen, control mode's port, and the test.

As DAqReader's settings dialog: it edits the :class:`Settings` it is given, and
only OK saves (``settings`` holds the result; after Cancel it is what was passed
in). The **test** part is Proteus' test template — Peak, break identification
and its threshold, the start load, the ramp and its measuring interval
(docs/motion.md) — and holds this program's defaults: what the control window's
switches and ramp start from, and what START sends.

Every value is limited to the range a settings file may hold
(:mod:`presscontroller.config.settings`). The ramp's speed is not limited here:
the press file's ``[limits]`` are, and START refuses a ramp above them, saying
so. The dialog says that in visible text rather than a tooltip.

The serial ports offered are listed by :meth:`SettingsDialog._ports`, a method so
a test can stub it; any name may be typed.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from presscontroller.app.theme import muted, styled
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
    Settings,
    TemplateSettings,
    save_settings,
)


def _spin(lo: float, hi: float, value: float, decimals: int, step: float, suffix: str):
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setSuffix(suffix)
    box.setValue(value)
    return box


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, *, save=save_settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PressController — settings")
        self.settings = settings
        self._save = save
        t = settings.test

        # ---- screen and port ----------------------------------------------
        self.refresh = _spin(MIN_REFRESH_HZ, MAX_REFRESH_HZ, settings.refresh_hz, 1, 0.5, " Hz")
        self.port = QComboBox()
        self.port.setEditable(True)
        names = self._ports()
        if settings.control_port and settings.control_port not in names:
            names.insert(0, settings.control_port)
        self.port.addItems(names)
        self.port.setCurrentText(settings.control_port)
        general = QFormLayout()
        general.addRow("Screen redraws at most", self.refresh)
        general.addRow("Control mode's port", self.port)
        general_box = QGroupBox("This computer")
        general_box.setLayout(general)

        # ---- the test: Proteus' template ----------------------------------
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
        test.addRow("Measuring interval during the ramp", self.interval)
        test_box = QGroupBox("The test (Proteus' test template)")
        test_box.setLayout(test)

        note = QLabel("Peak and Break detection are also the control window's switches; "
                      "a flip there is remembered here. START refuses a ramp faster than "
                      "the press file's [limits] and says so. The measuring interval is "
                      "rounded to 10 ms.")
        note.setWordWrap(True)
        styled(note, lambda w: w.setStyleSheet(f"color: {muted(w)};"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.addWidget(general_box)
        root.addWidget(test_box)
        root.addWidget(note)
        root.addStretch(1)
        root.addWidget(buttons)
        self.resize(520, self.sizeHint().height())

    def _ports(self) -> list[str]:
        """The serial ports Windows knows of now."""
        try:
            from serial.tools import list_ports
            return sorted(p.device for p in list_ports.comports())
        except Exception:
            return []

    def _accept(self) -> None:
        interval = int(round(self.interval.value() / 10.0)) * 10
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
            measuring_interval_ms=min(MAX_INTERVAL_MS, max(MIN_INTERVAL_MS, interval)))
        self.settings = replace(self.settings, refresh_hz=float(self.refresh.value()),
                                control_port=self.port.currentText().strip(), test=test)
        self._save(self.settings)
        self.accept()
