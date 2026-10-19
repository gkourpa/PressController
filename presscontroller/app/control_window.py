"""The control window: the monitor's window, with this program in charge.

Everything the monitor shows is here unchanged — readings, phase, plot, log —
fed by our own session instead of the tap. On top, one bar:

* **Connect** / **Disconnect** — Proteus' start-up replayed, and leaving PC mode
  as Proteus does (:class:`~presscontroller.control.ControllerSession`);
* **Break detection** and **Peak** — switches (operator, 2026-10-19). The
  controller does not report either, so the session *sets* them to the
  switches' positions as it connects and on every flip; a switch therefore
  never shows a guess. The controller's own display agrees (BD, PK).

The test controls — START, PAUSE, CONTINUE, STOP, as the operator named them —
come with the milestone that adds motion.

**No control in this window moves the press**: the commands that would are not
on the allowlist (:mod:`presscontroller.control.commands`), so no button could
send them even by mistake. The controller's keypad STOP is answered by the
session (Cancel, then PC mode off), and closing the window disconnects first.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from presscontroller.app.main_window import MainWindow
from presscontroller.app.theme import styled, text_style
from presscontroller.app.widgets import Switch, island
from presscontroller.control import ControllerSession, SessionState


class ControlWindow(MainWindow):
    mode_title = "CONTROL (no motion)"

    def __init__(self, monitor, session: ControllerSession, **kw):
        self.session = session
        super().__init__(monitor, session, **kw)
        self.state_lbl = QLabel()
        f = self.state_lbl.font()
        f.setBold(True)
        self.state_lbl.setFont(f)
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.session.connect)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.session.disconnect)
        self.break_switch = Switch("Break detection")
        self.break_switch.setChecked(self.session.break_detection)
        self.break_switch.toggled.connect(self.session.set_break_detection)
        self.peak_switch = Switch("Peak")
        self.peak_switch.setChecked(self.session.peak)
        self.peak_switch.toggled.connect(self.session.set_peak)
        bar = QWidget()
        row = QHBoxLayout(bar)
        row.setContentsMargins(10, 4, 10, 4)
        row.addWidget(self.state_lbl, 1)
        for w in (self.break_switch, self.peak_switch, self.connect_btn, self.disconnect_btn):
            row.addWidget(w)
        self._root.insertWidget(0, island(bar))
        self._shown_state: SessionState | None = None
        self._update_controls()

    def intro(self) -> str:
        return (f"Control mode: {self.source.link.describe()}. The old PC must be unplugged "
                "from the controller. This version cannot send anything that moves the press. "
                "Press Connect to start.")

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
        if self.session.state is not self._shown_state:
            self._update_controls()

    def _update_controls(self) -> None:
        state = self.session.state
        self._shown_state = state
        self.state_lbl.setText(f"Controller: {state.value}")
        styled(self.state_lbl, lambda w, bad=state is SessionState.FAILED:
               w.setStyleSheet(text_style(w, error=bad)))
        self.connect_btn.setEnabled(state in (SessionState.IDLE, SessionState.FAILED))
        self.disconnect_btn.setEnabled(state in (SessionState.CONNECTING,
                                                 SessionState.CONNECTED))
        # The switches stay usable while not connected: a position chosen then
        # is what connecting sets.
        for sw in (self.break_switch, self.peak_switch):
            sw.setEnabled(state is not SessionState.CLOSED)
