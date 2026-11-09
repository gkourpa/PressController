"""The control window: the monitor's window, with this program in charge.

Everything the monitor shows is here unchanged — readings, phase, plot, log —
fed by our own session instead of the tap. On top, two bars:

* **the connection** — the controller's state, **Break detection** as the
  program sets it, the **Peak** switch (operator, 2026-10-19: "a switch, easy
  for everyone to understand"), **Connect** / **Disconnect**;
* **the test** — its phase or step, the piston, **Program → Edit**
  (:mod:`~presscontroller.app.program_dialog`), and
  **START / PAUSE / CONTINUE / STOP**, as the operator named them
  (docs/motion.md); under them, **the program drawn** — force against time as
  planned, filled in as the test goes, **Edit** in its corner — with the
  program in words beside it (docs/ui.md, "The program").

**Peak is obeyed, never reset** (operator, 2026-10-20): it opens at the saved
setting; a flip is sent at once when connected and saved. **Break detection is
the program's**: off, on for the whole test, or on from a chosen step — the
label says which; it is locked while a test runs, as the program is.

START is available only when the session can build every line of the program —
a ramp above the press file's ``[limits]`` disables it, and the reason is shown.

**Piston: going down / still / going up**, large, beside the test's phase,
redrawn with the readings: after a STOP the operator must see whether the
piston has started sinking (operator, 2026-10-20). Pressing STOP again — like
the keypad's — releases a held load and then stops the sinking (step 33).

**STOP is always Cancel** (``#B17``: pump off, load released), red, and on the
**Esc** key; it is available whenever connected. PAUSE is not a stop: the
message line says so when it is pressed, and it is off during a hold (``#B18``
during a hold was never recorded). The controller's own STOP and the press's
emergency stop stay the primary safety devices.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from presscontroller.app.main_window import MainWindow
from presscontroller.app.program_dialog import ProgramDialog
from presscontroller.app.program_view import ProgramStrip
from presscontroller.app.theme import danger, muted, styled, text_style
from presscontroller.app.widgets import Switch, island
from presscontroller.config.settings import Settings
from presscontroller.control import ControllerSession, RunPhase, SessionState
from presscontroller.control.program import Program
from presscontroller.control.session import RUNNING

#: The program's drawing in the test bar, px wide.
STRIP_WIDTH = 430


def _bold(label: QLabel) -> QLabel:
    f = label.font()
    f.setBold(True)
    label.setFont(f)
    return label


def _muted(text: str = "") -> QLabel:
    lbl = QLabel(text)
    styled(lbl, lambda w: w.setStyleSheet(f"color: {muted(w)};"))
    return lbl


def break_words(program: Program) -> tuple[str, str]:
    """Break detection as the program sets it: the label, and the note under it."""
    on_from = program.break_from
    if on_from is None:
        return "Break detection: OFF", "set by the program"
    if on_from == 1:
        return "Break detection: ON", "set by the program, for the whole test"
    return "Break detection: from step " + str(on_from), (
        f"off until step {on_from}, then on: an unload would read as a break")


class ControlWindow(MainWindow):
    mode_title = ""

    def __init__(self, monitor, session: ControllerSession, **kw):
        self.session = session
        super().__init__(monitor, session, **kw)
        t = self.settings.test
        session.peak = t.peak
        session.idle_interval_ms = t.idle_interval_ms

        # ---- the connection bar --------------------------------------------
        self.state_lbl = _bold(QLabel())
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.session.connect)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.session.disconnect)
        self.break_lbl = _bold(QLabel())
        self.break_note = _muted()
        brk = QWidget()
        bcol = QVBoxLayout(brk)
        bcol.setContentsMargins(0, 0, 0, 0)
        bcol.setSpacing(0)
        bcol.addWidget(self.break_lbl)
        bcol.addWidget(self.break_note)
        self.peak_switch = Switch("Peak")
        self.peak_switch.setChecked(session.peak)
        self.peak_switch.toggled.connect(self._peak_flipped)
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 4, 10, 4)
        row.addWidget(self.state_lbl, 1)
        row.addWidget(brk)
        row.addSpacing(12)
        for w in (self.peak_switch, self.connect_btn, self.disconnect_btn):
            row.addWidget(w)

        # ---- the test bar --------------------------------------------------
        self.run_lbl = _bold(QLabel())
        self.run_lbl.setWordWrap(True)
        self.piston_lbl = _bold(QLabel("Piston: –"))
        f = self.piston_lbl.font()
        f.setPointSizeF(f.pointSizeF() * 1.4)
        self.piston_lbl.setFont(f)
        self.piston_lbl.setMinimumWidth(320)
        self.program_lbl = QLabel()
        self.program_lbl.setWordWrap(False)     # a line per part, never broken mid-part
        self.edit_btn = QPushButton("Edit")
        self.edit_btn.setAccessibleName("Edit program")
        self.edit_btn.clicked.connect(self.edit_program)
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
        # One height for all four: STOP's padding made it taller than the
        # rest, and they no longer lined up (operator, 2026-11-09).
        tall = max(b.sizeHint().height() for b in (self.start_btn, self.pause_btn,
                                                   self.continue_btn, self.stop_btn))
        for b in (self.start_btn, self.pause_btn, self.continue_btn, self.stop_btn):
            b.setFixedHeight(tall)
        # One row, as the operator drew it (2026-11-09): the test and the
        # piston; the program drawn, Edit in its bottom-right corner; the
        # program in words; the buttons, at the top.
        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(self.run_lbl)
        left.addWidget(self.piston_lbl)
        left.addStretch(1)
        self.strip = ProgramStrip(framed=True)
        self.strip.setMinimumWidth(STRIP_WIDTH)
        self.strip.setMaximumWidth(STRIP_WIDTH)
        self.strip.set_corner_widget(self.edit_btn)
        side = QVBoxLayout()
        side.setSpacing(2)
        side.addWidget(_bold(QLabel("Program")))
        side.addWidget(self.program_lbl)
        side.addStretch(1)
        buttons = QWidget()
        brow = QHBoxLayout(buttons)
        brow.setContentsMargins(0, 0, 0, 0)
        for w in (self.start_btn, self.pause_btn, self.continue_btn, self.stop_btn):
            brow.addWidget(w)
        test_bar = QWidget()
        row_t = QHBoxLayout(test_bar)
        row_t.setContentsMargins(10, 6, 10, 6)
        row_t.setSpacing(12)
        row_t.addLayout(left, 1)
        row_t.addWidget(self.strip, 0, Qt.AlignmentFlag.AlignTop)
        # The program's words take their own width, so the buttons follow them
        # (operator, 2026-11-09: no empty space between); spare width goes left.
        row_t.addLayout(side, 0)
        row_t.addWidget(buttons, 0, Qt.AlignmentFlag.AlignTop)     # operator, 2026-11-09
        self._root.insertWidget(0, island(test_bar))
        self._root.insertWidget(0, island(bar))

        self._esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc.activated.connect(self._stop)
        self._shown: tuple | None = None
        self._program: Program | None = None
        self._show_program()
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
        s = self.session
        if (s.state, s.test, s.step) != self._shown:
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
        self._show_progress()

    # ---- Peak and the settings --------------------------------------------------

    def _remember(self, **test) -> None:
        self.settings = replace(self.settings, test=replace(self.settings.test, **test))
        self._save(self.settings)

    def _peak_flipped(self, on: bool) -> None:
        self.session.set_peak(on)
        self._remember(peak=bool(on))
        self._show_program()        # Peak is in the lines START sends

    def apply_settings(self, settings: Settings) -> None:
        super().apply_settings(settings)
        t = settings.test
        if self.peak_switch.isChecked() != t.peak:
            self.peak_switch.setChecked(t.peak)     # obeyed: sent now if connected
        self.session.set_idle_interval(t.idle_interval_ms)
        self._show_program()
        self._update_controls()

    # ---- the program --------------------------------------------------------------

    def edit_program(self) -> None:
        dlg = ProgramDialog(self.settings.test, self.session.plan_for, parent=self)
        if dlg.exec():
            self.settings = replace(self.settings, test=dlg.test)
            self._save(self.settings)
            self._show_program()
            self._update_controls()

    def _show_program(self) -> None:
        """The saved program, planned against this press: its line, its drawing,
        and break detection as it sets it. While a test runs, the running one."""
        running = self.session.plan
        program = running if running is not None else self.session.plan_for(self.settings.test)
        self._program = program
        self.program_lbl.setText(program.told().replace(" · ", "\n"))   # a line each
        self.strip.set_program(program)
        words, note = break_words(program)
        self.break_lbl.setText(words)
        self.break_note.setText(note)
        self._show_progress()

    def _show_progress(self) -> None:
        """The running step in words, the hold's countdown, and the strip filled
        in so far."""
        s = self.session
        self.strip.set_progress(s.step, s.step_fraction(), s.program_elapsed())
        if s.current_step is not None and s.plan is not None:
            self.run_lbl.setText(self._run_text())

    def _run_text(self) -> str:
        s = self.session
        st, plan = s.current_step, s.plan
        if st is None or plan is None:
            return f"Test: {s.test.value}"
        n = len(plan.steps)
        where = f"Step {st.number} of {n} — " if n > 1 else ""
        left = s.hold_left()
        if left is not None:
            if st.control == "path" and s.path_set_end is not None:
                at = f"at {s.path_set_end:g} mm"      # a "by" ramp's end, worked out when sent
            else:
                at = st.told.split(" s ", 1)[1] if " s " in st.told else ""
            return f"{where}hold {at}, {left:.0f} s left"
        if s.test is RunPhase.PAUSED:
            return f"{where}paused: {st.told}"
        return f"{where}{st.told}"

    def _program_problem(self) -> str | None:
        program = self.session.plan_for(self.settings.test)
        return "; ".join(program.problems) if program.problems else None

    # ---- the buttons ------------------------------------------------------------

    def _start(self) -> None:
        self.session.start_test(self.settings.test)
        self._show_program()
        self._update_controls()

    def _stop(self) -> None:
        if self.session.stop():
            self._update_controls()

    def _update_controls(self) -> None:
        s = self.session
        state, test = s.state, s.test
        was_running = self._shown is not None and self._shown[1] in RUNNING
        self._shown = (state, test, s.step)
        self.state_lbl.setText(f"Controller: {state.value}")
        styled(self.state_lbl, lambda w, bad=state is SessionState.FAILED:
               w.setStyleSheet(text_style(w, error=bad)))
        connected = state is SessionState.CONNECTED
        running = test in RUNNING
        if was_running and not running:
            self._show_program()        # back to the saved program
        self.connect_btn.setEnabled(state in (SessionState.IDLE, SessionState.FAILED))
        self.disconnect_btn.setEnabled(state in (SessionState.CONNECTING,
                                                 SessionState.CONNECTED))
        # Usable while not connected: a position chosen then is what connecting
        # sends. Locked during a test: START has sent it.
        self.peak_switch.setEnabled(state is not SessionState.CLOSED and not running)
        self.edit_btn.setEnabled(not running)
        self.settings_action.setEnabled(not running)

        # A program over the press file's [limits] (or without them) turns
        # START off; the test line says why ("START is off: ...").
        problem = self._program_problem()
        self.start_btn.setEnabled(s.can_start() and problem is None)
        self.pause_btn.setEnabled(connected and test is RunPhase.RAMP)
        self.continue_btn.setEnabled(connected and test in (RunPhase.AT_START_LOAD,
                                                             RunPhase.PAUSED))
        self.stop_btn.setEnabled(connected)
        self._esc.setEnabled(connected)
        if running and s.current_step is not None:
            text = self._run_text()
        else:
            text = f"Test: {test.value}"
            if problem and not running:
                text += f" — START is off: {problem}"
        self.run_lbl.setText(text)
        self._show_progress()
