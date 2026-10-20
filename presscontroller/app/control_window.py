"""The control window: the monitor's window, with this program in charge.

Everything the monitor shows is here unchanged — readings, phase, plot, log —
fed by our own session instead of the tap. On top, two bars:

* **the connection** — the controller's state, the **Break detection** and
  **Peak** switches (operator, 2026-10-19: "a switch, easy for everyone to
  understand"), **Connect** / **Disconnect**;
* **the test** — its phase, the ramp (control, speed, end, and the press file's
  limit beside it), and **START / PAUSE / CONTINUE / STOP**, as the operator
  named them (docs/motion.md).

**The switches are obeyed, never reset** (operator, 2026-10-20). They open at
the saved settings; a flip is sent at once when connected and saved; connecting
and START send what they show. They are locked while a test runs: START has
sent them.

**The ramp entered here is the settings' ramp**: an edit is saved, so the next
launch starts from it. START is available only when the session can build every
line of the test — a ramp above the press file's ``[limits]`` disables it, and
the reason is shown beside it.

**Piston: going down / still / going up**, large, beside the test's phase,
redrawn with the readings: after a STOP the operator must see whether the
piston has started sinking (operator, 2026-10-20). Pressing STOP again — like
the keypad's — releases a held load and then stops the sinking (step 33).

**STOP is always Cancel** (``#B17``: pump off, load released), red, and on the
**Esc** key; it is available whenever connected. PAUSE is not a stop: the
message line says so when it is pressed. The controller's own STOP and the press's emergency stop stay the primary
safety devices.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from presscontroller.app.main_window import MainWindow
from presscontroller.app.theme import danger, styled, text_style
from presscontroller.app.widgets import Switch, island
from presscontroller.config.settings import RAMP_CONTROL_LABELS, RAMP_CONTROLS, Settings
from presscontroller.control import ControllerSession, NotAllowed, RunPhase, SessionState
from presscontroller.control.session import RUNNING


def _bold(label: QLabel) -> QLabel:
    f = label.font()
    f.setBold(True)
    label.setFont(f)
    return label


class ControlWindow(MainWindow):
    mode_title = "CONTROL"

    def __init__(self, monitor, session: ControllerSession, **kw):
        self.session = session
        super().__init__(monitor, session, **kw)
        t = self.settings.test
        session.peak, session.break_detection = t.peak, t.break_detection

        # ---- the connection bar --------------------------------------------
        self.state_lbl = _bold(QLabel())
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.session.connect)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.session.disconnect)
        self.break_switch = Switch("Break detection")
        self.break_switch.setChecked(session.break_detection)
        self.break_switch.toggled.connect(self._break_flipped)
        self.peak_switch = Switch("Peak")
        self.peak_switch.setChecked(session.peak)
        self.peak_switch.toggled.connect(self._peak_flipped)
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 4, 10, 4)
        row.addWidget(self.state_lbl, 1)
        for w in (self.break_switch, self.peak_switch, self.connect_btn, self.disconnect_btn):
            row.addWidget(w)

        # ---- the test bar --------------------------------------------------
        self.run_lbl = _bold(QLabel())
        self.run_lbl.setWordWrap(True)
        self.control_box = QComboBox()
        for name in RAMP_CONTROLS:
            self.control_box.addItem(RAMP_CONTROL_LABELS[name], name)
        self.speed_box = QDoubleSpinBox()
        self.speed_box.setDecimals(3)
        self.speed_box.setRange(0.001, 1000.0)
        self.end_box = QDoubleSpinBox()
        self.end_box.setDecimals(3)
        self.end_box.setRange(0.001, 100000.0)
        self.limit_lbl = QLabel()
        self.piston_lbl = _bold(QLabel("Piston: –"))
        f = self.piston_lbl.font()
        f.setPointSizeF(f.pointSizeF() * 1.4)
        self.piston_lbl.setFont(f)
        self.piston_lbl.setMinimumWidth(320)
        self.start_btn = QPushButton("START")
        self.start_btn.clicked.connect(self._start)
        self.pause_btn = QPushButton("PAUSE")
        self.pause_btn.clicked.connect(self.session.pause_test)
        self.continue_btn = QPushButton("CONTINUE")
        self.continue_btn.clicked.connect(self.session.continue_test)
        self.stop_btn = QPushButton("STOP")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setMinimumWidth(140)
        styled(self.stop_btn, lambda w: w.setStyleSheet(
            f"QPushButton {{ font-weight: bold; padding: 6px 18px; color: white; "
            f"background: {danger(w)}; }} QPushButton:disabled {{ background: palette(mid); }}"))
        f = self.start_btn.font()
        f.setBold(True)
        for b in (self.start_btn, self.pause_btn, self.continue_btn):
            b.setFont(f)
        test_bar = QWidget()
        trow = QHBoxLayout(test_bar)
        trow.setContentsMargins(10, 4, 10, 4)
        trow.addWidget(self.run_lbl, 1)
        trow.addWidget(self.piston_lbl)
        trow.addWidget(QLabel("Ramp"))
        for w in (self.control_box, self.speed_box, QLabel("to"), self.end_box,
                  self.limit_lbl, self.start_btn, self.pause_btn, self.continue_btn,
                  self.stop_btn):
            trow.addWidget(w)
        self._root.insertWidget(0, island(test_bar))
        self._root.insertWidget(0, island(bar))

        self._load_ramp()
        self.control_box.currentIndexChanged.connect(self._control_changed)
        self.speed_box.valueChanged.connect(self._ramp_edited)
        self.end_box.valueChanged.connect(self._ramp_edited)
        self._esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc.activated.connect(self._stop)
        self._shown: tuple | None = None
        self._update_controls()

    def intro(self) -> str:
        return (f"Control mode: {self.source.link.describe()}. The old PC must be unplugged "
                "from the controller. Press Connect to start. STOP (or Esc) is Cancel: pump "
                "off. The controller's STOP and the emergency stop remain the primary stops.")

    def port_lost(self, error: str) -> str:
        return (f"{error}. The program can no longer reach the controller. If the press was "
                "in PC mode, press STOP on the controller's keypad or switch it off and on.")

    def start(self) -> None:
        super().start()
        self._update_controls()     # the port is open now: Connect becomes available

    def tick(self) -> None:
        super().tick()
        for m in self.session.pop_messages():
            self.say(m.text, warn=m.level == "warn", error=m.level == "error")
        if (self.session.state, self.session.test) != self._shown:
            self._update_controls()

    def _refresh(self) -> None:
        super()._refresh()
        p = self.monitor.piston()
        if p is None:
            self.piston_lbl.setText("Piston: –")
        elif p[0] == "still":
            self.piston_lbl.setText("Piston: still")
        else:
            self.piston_lbl.setText(f"Piston: {p[0]}, {p[1]:+.1f} mm/min")

    # ---- switches and settings ------------------------------------------------

    def _remember(self, **test) -> None:
        self.settings = replace(self.settings, test=replace(self.settings.test, **test))
        self._save(self.settings)

    def _peak_flipped(self, on: bool) -> None:
        self.session.set_peak(on)
        self._remember(peak=bool(on))

    def _break_flipped(self, on: bool) -> None:
        self.session.set_break_detection(on)
        self._remember(break_detection=bool(on))

    def apply_settings(self, settings: Settings) -> None:
        super().apply_settings(settings)
        t = settings.test
        for sw, on in ((self.peak_switch, t.peak), (self.break_switch, t.break_detection)):
            if sw.isChecked() != on:
                sw.setChecked(on)           # obeyed: sent now if connected
        self._load_ramp()
        self._update_controls()

    # ---- the ramp ---------------------------------------------------------------

    def _load_ramp(self) -> None:
        t = self.settings.test
        boxes = (self.control_box, self.speed_box, self.end_box)
        for b in boxes:
            b.blockSignals(True)
        self.control_box.setCurrentIndex(max(0, self.control_box.findData(t.ramp_control)))
        if t.ramp_control == "path":
            self.speed_box.setSuffix(" mm/min")
            self.end_box.setSuffix(" mm")
            self.speed_box.setValue(t.path_speed_mm_min)
            self.end_box.setValue(t.path_end_mm)
        else:
            self.speed_box.setSuffix(" kN/s")
            self.end_box.setSuffix(" kN")
            self.speed_box.setValue(t.force_speed_kn_s)
            self.end_box.setValue(t.force_end_kn)
        for b in boxes:
            b.blockSignals(False)

    def _control_changed(self) -> None:
        self._remember(ramp_control=self.control_box.currentData())
        self._load_ramp()
        self._update_controls()

    def _ramp_edited(self) -> None:
        if self.settings.test.ramp_control == "path":
            self._remember(path_speed_mm_min=self.speed_box.value(),
                           path_end_mm=self.end_box.value())
        else:
            self._remember(force_speed_kn_s=self.speed_box.value(),
                           force_end_kn=self.end_box.value())
        self._update_controls()

    def _ramp_problem(self) -> str | None:
        try:
            self.session.build_lines(self.settings.test)
        except NotAllowed as exc:
            return str(exc)
        return None

    # ---- the buttons ------------------------------------------------------------

    def _start(self) -> None:
        self.session.start_test(self.settings.test)
        self._update_controls()

    def _stop(self) -> None:
        if self.session.stop():
            self._update_controls()

    def _update_controls(self) -> None:
        s = self.session
        state, test = s.state, s.test
        self._shown = (state, test)
        self.state_lbl.setText(f"Controller: {state.value}")
        styled(self.state_lbl, lambda w, bad=state is SessionState.FAILED:
               w.setStyleSheet(text_style(w, error=bad)))
        connected = state is SessionState.CONNECTED
        running = test in RUNNING
        self.connect_btn.setEnabled(state in (SessionState.IDLE, SessionState.FAILED))
        self.disconnect_btn.setEnabled(state in (SessionState.CONNECTING,
                                                 SessionState.CONNECTED))
        # Usable while not connected: a position chosen then is what connecting
        # sends. Locked during a test: START has sent them.
        for sw in (self.break_switch, self.peak_switch):
            sw.setEnabled(state is not SessionState.CLOSED and not running)
        for w in (self.control_box, self.speed_box, self.end_box):
            w.setEnabled(not running)
        self.settings_action.setEnabled(not running)

        limits = s.link.limits
        problem = self._ramp_problem()
        if limits is None:
            self.limit_lbl.setText("no [limits] in the press file: START is off")
        elif self.settings.test.ramp_control == "path":
            self.limit_lbl.setText(f"limit {limits.max_path_mm_min:g} mm/min")
        else:
            self.limit_lbl.setText(f"limit {limits.max_force_kn_s:g} kN/s")
        styled(self.limit_lbl, lambda w, bad=problem is not None:
               w.setStyleSheet(text_style(w, error=bad)))
        self.start_btn.setEnabled(s.can_start() and problem is None)
        self.pause_btn.setEnabled(connected and test is RunPhase.RAMP)
        self.continue_btn.setEnabled(connected and test in (RunPhase.AT_START_LOAD,
                                                             RunPhase.PAUSED))
        self.stop_btn.setEnabled(connected)
        self._esc.setEnabled(connected)
        text = f"Test: {test.value}"
        if problem and not running:
            text += f" — START is off: {problem}"
        self.run_lbl.setText(text)
