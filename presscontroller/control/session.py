"""Connecting to the controller as Proteus does, and leaving it as Proteus does.

A small state machine, driven by :meth:`ControllerSession.poll` from the
window's tick, so it never blocks and every wait has a deadline.

**Connect** (:meth:`ControllerSession.connect`):

1. **Listen first.** For :data:`LISTEN_FIRST_S` nothing is sent. Anything heard
   means something else is talking to the controller — the old PC, most likely,
   still cabled — and the session refuses without sending a byte.
2. **Proteus' start-up, replayed** in its four groups
   (:data:`~presscontroller.control.commands.STARTUP_GROUPS`). After each, the
   session waits for exactly what Proteus always got back. **A different answer,
   or none within** :data:`REPLY_TIMEOUT_S`, **aborts**: the stream off and PC
   mode off are sent, and the session says what it got instead. A controller
   that answers differently is in a state no recording has covered, and the safe
   response to the unknown is to hand control back.
3. **Connected** once the first measurement line arrives after ``#B37``.

**Keypad STOP.** In PC mode the controller does not act on its own STOP key; it
sends ``#B28`` and leaves it to the PC (docs/PROTOCOL.md). The session answers it
the way that keeps the operator in charge: Cancel (pump off), then stream off and
PC mode off, so the keypad works locally again at once.

**Peak and break detection are switches with a known state.** The controller
does not report them, and Proteus never sets them at start-up, so whatever an
earlier session left is in force. The session therefore keeps the state the
operator wants (:attr:`ControllerSession.peak`,
:attr:`ControllerSession.break_detection`) and **sends it right after
connecting** and on every change, so a switch on screen can never disagree with
the controller (operator, 2026-10-19: "a switch, easy for everyone to
understand"). Break detection starts on — the controller's own power-up default,
and the one that stops the press when a specimen fails; Peak starts off, its
power-up default too.

**Disconnect** — and closing, which always disconnects first — sends the stream
off and PC mode off, as Proteus does when it exits.

**A test** (docs/motion.md), Proteus' sequence line for line:

* :meth:`ControllerSession.start_test` builds every line the test will need
  from the settings first — the ramp against the press file's limits — and
  sends nothing if one is refused. Then ``#B47``; on the controller's ``#O``,
  Peak and break detection **as the switches stand** (``#B33`` followed by the
  break threshold ``#D21…``), the start load ``#D09…`` and the approach ``#B23``.
* ``#B01`` — the start load reached — waits for CONTINUE
  (:meth:`ControllerSession.continue_test`): the measuring interval ``#D05…``
  and the ramp; on the controller's ``#B35``, ``#B22``; on its ``#O``, the ramp
  runs.
* PAUSE and CONTINUE during the ramp are both ``#B18``, which toggles.
  **PAUSE is not a stop**: it freezes the ramp's target (step 22).
* The controller's ``#B02`` (the ramp's end) is answered as Proteus does,
  ``#B26 #B17``.
* **STOP is ``#B17``** — Proteus' Cancel, pump off — and so is every way a test
  can go wrong: an answer that does not come, a controller line no recording
  explains (it may be how the controller tells a break), the readings stopping,
  Disconnect or closing during a test. The keypad STOP is answered as before.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from presscontroller.control import commands as cmd
from presscontroller.config.settings import TemplateSettings
from presscontroller.control.commands import NotAllowed
from presscontroller.control.link import ControllerLink
from presscontroller.protocol import CTRL_TO_PC, Ack, Command, Sample, parse
from presscontroller.tap.events import TapEvent

#: Seconds of silence required before the first byte is sent. The controller is
#: silent until a PC starts it; a stream heard here is another PC's session.
LISTEN_FIRST_S = 1.5

#: Seconds to wait for each group's replies. They came within 40 ms every time.
REPLY_TIMEOUT_S = 1.0

#: Seconds to wait for the first measurement line after ``#B37``; it came within
#: 0.2 s every time.
STREAM_TIMEOUT_S = 1.5

#: Seconds without a measurement line, while connected, before it is said. The
#: slowest interval in use is 0.2 s.
SILENT_AFTER_S = 2.0

#: Seconds without a measurement line, during a test, before the test is
#: stopped. The ramp's interval is at most 1 s (the settings' ceiling).
TEST_SILENT_S = 1.5

#: What the controller says during a test that the recordings explain: the
#: start load reached, the ramp's end, the answer to a ramp, the load released,
#: the keypad STOP. Anything else, during a test, stops it.
EXPLAINED_EVENTS = frozenset({1, 2, 35, 43, 28})


class SessionState(Enum):
    CLOSED = "port closed"
    IDLE = "not connected"
    LISTENING = "checking the line is free"
    CONNECTING = "connecting"
    CONNECTED = "connected, in PC mode"
    FAILED = "connection refused or aborted"


class RunPhase(Enum):
    NONE = "no test running"
    ARMING = "START sent, waiting for the controller"
    APPROACH = "approaching the specimen"
    AT_START_LOAD = "at the start load: CONTINUE starts the ramp"
    STARTING_RAMP = "sending the ramp"
    RAMP = "ramp running"
    PAUSED = "paused (PAUSE holds the ramp's target, not the piston)"


#: The phases in which a test is running and STOP is the way out.
RUNNING = frozenset(set(RunPhase) - {RunPhase.NONE})


@dataclass(frozen=True)
class RunLines:
    """Every line a test will send that is built from settings, built before
    the first byte goes, so a refused value stops nothing midway."""

    switches: tuple[str, ...]
    start_load: str
    interval: str
    ramp: str
    told: str
    """The ramp in words: ``Path 2 mm/min to 100 mm``."""


@dataclass(frozen=True)
class SessionMessage:
    text: str
    level: str = "info"
    """``info``, ``warn`` or ``error``."""


class ControllerSession:
    """The window's source in control mode: start / poll / close / describe /
    errors, as a tap has — plus connect, disconnect and the two switches."""

    def __init__(self, link: ControllerLink, *, clock: Callable[[], float] = time.monotonic):
        self.link = link
        self._clock = clock
        self.state = SessionState.CLOSED
        self.replies: list[str] = []
        """What the controller answered during the last start-up."""
        self._messages: list[SessionMessage] = []
        self._group = 0
        self._got: list[str] = []
        self._deadline = 0.0
        self._last_sample = 0.0
        self._silent_said = False
        self.peak = False
        """Peak detection as the operator wants it; sent on connect and on change."""
        self.break_detection = True
        """Break detection as the operator wants it; sent on connect and on change."""
        self.test = RunPhase.NONE
        self.plan: RunLines | None = None
        """The running test's lines; ``None`` between tests."""
        self._await = ""
        self._test_deadline = 0.0

    # ---- the source surface the window drives --------------------------------

    @property
    def errors(self) -> list[str]:
        return self.link.errors

    def describe(self) -> str:
        return f"{self.link.describe()}; {self.state.value}"

    def start(self) -> None:
        self.link.start()
        self.state = SessionState.IDLE

    def close(self) -> None:
        if self.state in (SessionState.CONNECTING, SessionState.CONNECTED):
            if self.test in RUNNING:
                self.link.send(cmd.CANCEL)
                self._end_test()
            self._send_all(cmd.DISCONNECT)
        self.link.close()
        self.state = SessionState.CLOSED

    def pop_messages(self) -> list[SessionMessage]:
        out, self._messages = self._messages, []
        return out

    # ---- operator actions ----------------------------------------------------

    def connect(self) -> None:
        if self.state not in (SessionState.IDLE, SessionState.FAILED):
            return
        self.replies = []
        self.state = SessionState.LISTENING
        self._deadline = self._clock() + LISTEN_FIRST_S
        self._say("Checking that nothing else is talking to the controller…")

    def disconnect(self) -> None:
        if self.state in (SessionState.CONNECTING, SessionState.CONNECTED):
            if self.test in RUNNING:
                self.link.send(cmd.CANCEL)
                self._end_test()
            self._send_all(cmd.DISCONNECT)
            self._say("Disconnected: stream off, PC mode off. The controller's keypad "
                      "works locally again.")
        if self.state is not SessionState.CLOSED:
            self.state = SessionState.IDLE

    def set_peak(self, on: bool) -> None:
        """Want Peak on or off; sent now if connected, else on connecting."""
        self.peak = bool(on)
        if self.state is SessionState.CONNECTED:
            self.link.send(cmd.PEAK_ON if self.peak else cmd.PEAK_OFF)

    def set_break_detection(self, on: bool) -> None:
        """Want break detection on or off; sent now if connected, else on connecting."""
        self.break_detection = bool(on)
        if self.state is SessionState.CONNECTED:
            self.link.send(cmd.BREAK_ON if self.break_detection else cmd.BREAK_OFF)

    def _apply_switches(self) -> None:
        self.link.send(cmd.PEAK_ON if self.peak else cmd.PEAK_OFF)
        self.link.send(cmd.BREAK_ON if self.break_detection else cmd.BREAK_OFF)

    # ---- the test ------------------------------------------------------------

    def build_lines(self, t: TemplateSettings) -> RunLines:
        """Every built line of a test from ``t`` and the switches; raises
        :class:`~presscontroller.control.commands.NotAllowed`, saying why."""
        switches = [cmd.PEAK_ON if self.peak else cmd.PEAK_OFF]
        if self.break_detection:
            switches += [cmd.BREAK_ON, cmd.break_threshold_line(t.break_threshold_per_mil)]
        else:
            switches.append(cmd.BREAK_OFF)
        if t.ramp_control == "path":
            speed, end = t.path_speed_mm_min, t.path_end_mm
            told = f"Path {speed:g} mm/min to {end:g} mm"
        else:
            speed, end = t.force_speed_kn_s, t.force_end_kn
            told = f"Force {speed:g} kN/s to {end:g} kN"
        return RunLines(switches=tuple(switches),
                         start_load=cmd.start_load_line(t.start_load_percent),
                         interval=cmd.interval_line(t.measuring_interval_ms),
                         ramp=cmd.ramp_line(self.link.limits, t.ramp_control, speed, end),
                         told=told)

    def can_start(self) -> bool:
        return self.state is SessionState.CONNECTED and self.test is RunPhase.NONE

    def start_test(self, t: TemplateSettings) -> bool:
        """START: ``#B47``, then on ``#O`` the switches, the start load and the
        approach. Nothing is sent if any line of the test is refused."""
        if not self.can_start():
            return False
        try:
            plan = self.build_lines(t)
        except NotAllowed as exc:
            self._say(f"START refused, nothing sent: {exc}.", "error")
            return False
        self.plan = plan
        self.link.send(cmd.START)
        self._expect(RunPhase.ARMING, "#O")
        self._say(f"START: {plan.told}. Waiting for the controller…")
        return True

    def continue_test(self) -> bool:
        """CONTINUE: at the start load, send the ramp; while paused, ``#B18``."""
        if self.state is not SessionState.CONNECTED:
            return False
        if self.test is RunPhase.AT_START_LOAD and self.plan is not None:
            self.link.send(self.plan.interval)
            self.link.send(self.plan.ramp)
            self._expect(RunPhase.STARTING_RAMP, "#B35")
            return True
        if self.test is RunPhase.PAUSED:
            self.link.send(cmd.PAUSE_CONTINUE)
            self.test = RunPhase.RAMP
            self._say("CONTINUE: the ramp goes on.")
            return True
        return False

    def pause_test(self) -> bool:
        """PAUSE: ``#B18``. Freezes the ramp's target — not a stop."""
        if self.state is SessionState.CONNECTED and self.test is RunPhase.RAMP:
            self.link.send(cmd.PAUSE_CONTINUE)
            self.test = RunPhase.PAUSED
            self._say("PAUSE: the ramp's target is held. PAUSE is not a stop: STOP is.",
                      "warn")
            return True
        return False

    def stop(self) -> bool:
        """STOP: ``#B17`` — pump off, load released. Sent whenever connected."""
        if self.state is not SessionState.CONNECTED:
            return False
        self.link.send(cmd.CANCEL)
        was = self.test
        self._end_test()
        self._say("STOP: pump off, load released (Cancel)." if was in RUNNING
                  else "STOP sent (Cancel): pump off.", "warn")
        return True

    def _expect(self, phase: RunPhase, line: str) -> None:
        self.test = phase
        self._await = line
        self._test_deadline = self._clock() + REPLY_TIMEOUT_S

    def _end_test(self) -> None:
        self.test = RunPhase.NONE
        self.plan = None
        self._await = ""

    def _stop_for(self, why: str) -> None:
        self.link.send(cmd.CANCEL)
        self._end_test()
        self._say(f"Test stopped (Cancel: pump off): {why}.", "error")

    def _heard_in_test(self, ev: TapEvent, msg) -> None:
        """What the controller said while a test runs."""
        if isinstance(msg, Sample):
            return
        if isinstance(msg, Ack):
            if self.test is RunPhase.ARMING and self._await == "#O":
                assert self.plan is not None
                self._send_all(self.plan.switches + (self.plan.start_load, cmd.APPROACH))
                self.test = RunPhase.APPROACH
                self._await = ""
                self._say("Approaching the specimen…")
            elif self.test is RunPhase.STARTING_RAMP and self._await == "#O":
                self.test = RunPhase.RAMP
                self._await = ""
                self._say(f"Ramp running: {self.plan.told if self.plan else ''}. "
                          "STOP (or Esc) stops the pump.")
            return
        if not isinstance(msg, Command) or msg.code not in EXPLAINED_EVENTS:
            self._stop_for(f"the controller said {ev.text!r}, which no recording explains "
                           "(it may be how it tells a break)")
            return
        if msg.code == 1 and self.test is RunPhase.APPROACH:
            self.test = RunPhase.AT_START_LOAD
            self._say("Start load reached. CONTINUE starts the ramp; STOP ends the test.")
        elif msg.code == 35 and self.test is RunPhase.STARTING_RAMP and self._await == "#B35":
            self.link.send(cmd.RAMP_GO)
            self._expect(RunPhase.STARTING_RAMP, "#O")
        elif msg.code == 2 and self.test in (RunPhase.RAMP, RunPhase.PAUSED):
            self._send_all((cmd.RAMP_END_ANSWER, cmd.CANCEL))
            self._end_test()
            self._say("The ramp reached its end: answered as Proteus does (#B26), pump off.")

    # ---- the tick ------------------------------------------------------------

    def poll(self) -> list[TapEvent]:
        events = self.link.poll()
        now = self._clock()
        for ev in events:
            if ev.direction == CTRL_TO_PC:
                self._heard(ev, now)
        self._advance(now)
        # The lines sent while advancing are heard on the next poll; hand out
        # what is already there so nothing waits a tick for no reason.
        return events + self.link.poll()

    def _heard(self, ev: TapEvent, now: float) -> None:
        msg = parse(ev.direction, ev.text)
        if self.state is SessionState.LISTENING:
            self._refuse(f"the line is not free: heard {ev.text!r} before sending anything. "
                         "Is the old PC still connected to the controller?")
            return
        if isinstance(msg, Command) and msg.code == 28 and self.state in (
                SessionState.CONNECTING, SessionState.CONNECTED):
            self.link.send(cmd.CANCEL)
            self._send_all(cmd.DISCONNECT)
            self._end_test()
            self.state = SessionState.IDLE
            self._say("Keypad STOP pressed on the controller: pump off (Cancel), stream off "
                      "and PC mode off. The controller's keypad is in charge again.", "warn")
            return
        if self.state is SessionState.CONNECTING:
            if isinstance(msg, Sample):
                if self._group == len(cmd.STARTUP_GROUPS):
                    self.state = SessionState.CONNECTED
                    self._last_sample = now
                    self._silent_said = False
                    self._apply_switches()
                    self._say("Connected: the controller is in PC mode and streaming; Peak "
                              f"{'on' if self.peak else 'off'}, break detection "
                              f"{'on' if self.break_detection else 'off'}. No motion command "
                              "can be sent in this version.")
                else:
                    self._abort("the controller streamed before it was asked to")
                return
            self._got.append(ev.text)
            self.replies.append(ev.text)
        elif self.state is SessionState.CONNECTED:
            if isinstance(msg, Sample):
                self._last_sample = now
                self._silent_said = False
            if self.test in RUNNING:
                self._heard_in_test(ev, msg)

    def _advance(self, now: float) -> None:
        if self.state is SessionState.LISTENING and now >= self._deadline:
            self.state = SessionState.CONNECTING
            self._group = 0
            self._send_group(now)
        elif self.state is SessionState.CONNECTING:
            done = self._group == len(cmd.STARTUP_GROUPS)
            if not done:
                expected = list(cmd.STARTUP_REPLIES[self._group])
                if self._got[:len(expected)] != expected[:len(self._got)]:
                    self._abort(f"the controller answered {self._got} where it has always "
                                f"answered {expected}")
                    return
                if len(self._got) >= len(expected):
                    if len(self._got) > len(expected):
                        self._abort(f"the controller answered {self._got}, more than the "
                                    f"{expected} it has always answered")
                        return
                    self._group += 1
                    if self._group < len(cmd.STARTUP_GROUPS):
                        self._send_group(now)
                    else:
                        self._deadline = now + STREAM_TIMEOUT_S
                    return
            if now >= self._deadline:
                what = ("no measurement line after #B37" if done else
                        f"no answer to {' '.join(cmd.STARTUP_GROUPS[self._group])} "
                        f"(got {self._got}, expected {list(cmd.STARTUP_REPLIES[self._group])})")
                self._abort(what)
        elif self.state is SessionState.CONNECTED:
            if self.test in RUNNING:
                if self._await and now >= self._test_deadline:
                    self._stop_for(f"the controller did not answer {self._await} within "
                                   f"{REPLY_TIMEOUT_S:g} s")
                elif now - self._last_sample > TEST_SILENT_S:
                    self._stop_for(f"no measurement for {TEST_SILENT_S:g} s; if the press "
                                   "does not stop, press STOP on the keypad")
            if now - self._last_sample > SILENT_AFTER_S and not self._silent_said:
                self._silent_said = True
                self._say(f"No measurement from the controller for {SILENT_AFTER_S:.0f} s.",
                          "warn")

    def _send_group(self, now: float) -> None:
        group = cmd.STARTUP_GROUPS[self._group]
        self._got = []
        self._send_all(group)
        if self._group == len(cmd.STARTUP_GROUPS) - 1:
            # The last group is #B37 alone; what answers it is the stream.
            self._group += 1
            self._deadline = now + STREAM_TIMEOUT_S
        else:
            self._deadline = now + REPLY_TIMEOUT_S

    def _send_all(self, lines) -> None:
        for line in lines:
            self.link.send(line)

    def _abort(self, why: str) -> None:
        self._send_all(cmd.DISCONNECT)
        self.state = SessionState.FAILED
        self._say(f"Connection aborted: {why}. Stream off and PC mode off were sent; "
                  "nothing else.", "error")

    def _refuse(self, why: str) -> None:
        self.state = SessionState.FAILED
        self._say(f"Not connecting: {why} Nothing was sent.", "error")

    def _say(self, text: str, level: str = "info") -> None:
        self._messages.append(SessionMessage(text, level))
