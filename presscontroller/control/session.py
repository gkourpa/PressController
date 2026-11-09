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

**Peak and break detection have a known state.** The controller does not
report them, and Proteus never sets them at start-up, so whatever an earlier
session left is in force (step 37: break detection left on by the test before).
Peak is the operator's switch (:attr:`ControllerSession.peak`), **sent right
after connecting** and on every change (operator, 2026-10-19: "a switch, easy
for everyone to understand"). Break detection belongs to the test's program
(:mod:`~presscontroller.control.program`): connecting sends it off, and every
START sends it as the program's first step wants it.

**Disconnect** — and closing, which always disconnects first — sends the stream
off and PC mode off, as Proteus does when it exits.

**A test** (docs/motion.md), Proteus' sequence line for line:

* **The measuring interval before the ramp**
  (:attr:`ControllerSession.idle_interval_ms`): the start-up sets 100 ms; a
  different setting is sent once connected, and after every test, since the
  ramp's ``#D05…`` stays in force when the test ends. Nothing is sent when
  the interval in force is already the one wanted.
* :meth:`ControllerSession.start_test` plans the program first
  (:func:`~presscontroller.control.program.plan_program`) — every ramp against
  the press file's limits, every step checked — and sends nothing if any of it
  is refused. Then ``#B47``; on the controller's ``#O``, Peak as the switch
  stands and break detection as the program starts (``#B33`` followed by the
  break threshold ``#D21…``, or ``#B32``), the start load ``#D09…`` and the
  approach ``#B23``.
* ``#B01`` — the start load reached — waits for CONTINUE
  (:meth:`ControllerSession.continue_test`), which starts the program's first
  step. A ramp — Force or Path: the measuring interval ``#D05…`` and the ramp
  (after ``#B33 #D21…`` if it switches break detection on); on the controller's
  ``#B35``, ``#B22``; on its ``#O``, the ramp runs. A Path ramp "by" a distance
  gets its end here, as it is sent: the previous Path ramp's set end, or the
  piston's position from the newest reading, plus the distance (steps 39–41).
* PAUSE and CONTINUE during a ramp are both ``#B18``, which toggles.
  **PAUSE is not a stop**: it freezes the ramp's target (step 22). A hold
  cannot be paused: ``#B18`` during one was never recorded.
* The controller's ``#B02`` (a ramp's end) is answered as Proteus does:
  ``#B26`` alone, and the next step starts — a hold timed here, or the next
  ramp; ``#B26 #B17`` after the last step. A hold that is the last step ends
  with ``#B17``.
* **STOP is ``#B17``** — Proteus' Cancel, pump off — and so is every way a test
  can go wrong: an answer that does not come, a controller line no recording
  explains (it may be how the controller tells a break), the readings stopping,
  Disconnect or closing during a test. The keypad STOP is answered as before.
* **A break** (``#B27``, break detection on): the controller then held the
  load, and one Cancel did not release it (step 32); PC mode off and the keypad
  STOP did. The session sends Cancel and stays connected, so the operator can
  try STOP — a second Cancel — and, failing that, Disconnect and the keypad
  STOP. The message says both.
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
from presscontroller.control.program import FROM_PREVIOUS, PlannedStep, Program, plan_program
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
    HOLD = "holding the force (timed by this program)"


#: The phases in which a test is running and STOP is the way out.
RUNNING = frozenset(set(RunPhase) - {RunPhase.NONE})


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
        self.idle_interval_ms = cmd.STARTUP_INTERVAL_MS
        """The measuring interval wanted before the ramp; sent on connect if
        not the start-up's, and after every test."""
        self._interval_ms = 0
        """The interval in force, as last sent; 0 when unknown."""
        self.test = RunPhase.NONE
        self.plan: Program | None = None
        """The running test's program; ``None`` between tests."""
        self.step: int | None = None
        """The running step's index in :attr:`plan`; ``None`` before the first."""
        self._hold_until = 0.0
        self._step_started = 0.0
        self._path_now: float | None = None
        """The piston's position from the newest reading, mm."""
        self._path_set_end: float | None = None
        """The end the running test's newest Path ramp was sent with, mm."""
        self._await = ""
        self._test_deadline = 0.0
        self._carry: list[TapEvent] = []

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

    def set_idle_interval(self, ms: int) -> None:
        """Want ``ms`` before the ramp; sent now if connected and no test runs."""
        self.idle_interval_ms = int(ms)
        if self.test is RunPhase.NONE:
            self._restore_interval()

    def _restore_interval(self) -> None:
        """Send the interval wanted before the ramp, unless already in force."""
        if self.state is not SessionState.CONNECTED or self._interval_ms == self.idle_interval_ms:
            return
        try:
            line = cmd.interval_line(self.idle_interval_ms)
        except NotAllowed as exc:
            self._say(f"Measuring interval not sent: {exc}.", "error")
            return
        self.link.send(line)
        self._interval_ms = self.idle_interval_ms

    def _apply_switches(self) -> None:
        # Break detection off until a program's START says otherwise: a known
        # state, whatever an earlier session left (step 37).
        self.link.send(cmd.PEAK_ON if self.peak else cmd.PEAK_OFF)
        self.link.send(cmd.BREAK_OFF)

    # ---- the test ------------------------------------------------------------

    def plan_for(self, t: TemplateSettings) -> Program:
        """``t``'s program with the press file's limits and the Peak switch:
        every line built, every step checked (never raises)."""
        return plan_program(t, self.link.limits, peak=self.peak)

    def can_start(self) -> bool:
        return self.state is SessionState.CONNECTED and self.test is RunPhase.NONE

    @property
    def current_step(self) -> PlannedStep | None:
        if self.plan is None or self.step is None:
            return None
        return self.plan.steps[self.step]

    def hold_left(self) -> float | None:
        """Seconds left of the running hold, ``None`` when none runs."""
        if self.test is not RunPhase.HOLD:
            return None
        return max(0.0, self._hold_until - self._clock())

    @property
    def path_set_end(self) -> float | None:
        """The end the running test's newest Path ramp was sent with, mm."""
        return self._path_set_end if self.plan is not None else None

    def step_fraction(self) -> float | None:
        """How far the running step is through its planned length, 0–1;
        ``None`` when its length is not known."""
        st = self.current_step
        if st is None or not st.seconds:
            return None
        return min(1.0, (self._clock() - self._step_started) / st.seconds)

    def program_elapsed(self) -> float | None:
        """Where the test is on the program's planned time line, in seconds: the
        planned length of the steps done, plus the running step's time so far
        (no more than its planned length). ``None`` before the first step or
        when a step's length cannot be planned (a path ramp)."""
        if self.plan is None or self.step is None:
            return None
        done = [s.seconds for s in self.plan.steps[:self.step]]
        here = self.plan.steps[self.step].seconds
        if here is None or any(d is None for d in done):
            return None
        return sum(done) + min(here, self._clock() - self._step_started)

    def start_test(self, t: TemplateSettings) -> bool:
        """START: ``#B47``, then on ``#O`` Peak, break detection, the start load
        and the approach. Nothing is sent if any part of the program is refused."""
        if not self.can_start():
            return False
        plan = self.plan_for(t)
        if not plan.ok:
            self._say(f"START refused, nothing sent: {'; '.join(plan.problems)}.", "error")
            return False
        self.plan = plan
        self.step = None
        self._path_set_end = None
        self.link.send(cmd.START)
        self._expect(RunPhase.ARMING, "#O")
        self._say(f"START: {plan.told()}. Waiting for the controller…")
        return True

    def continue_test(self) -> bool:
        """CONTINUE: at the start load, start the program; while paused, ``#B18``."""
        if self.state is not SessionState.CONNECTED:
            return False
        if self.test is RunPhase.AT_START_LOAD and self.plan is not None:
            self._begin_step(0)
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
        self._restore_interval()
        self._say("STOP: pump off, load released (Cancel)." if was in RUNNING
                  else "STOP sent (Cancel): pump off.", "warn")
        return True

    def _expect(self, phase: RunPhase, line: str) -> None:
        self.test = phase
        self._await = line
        self._test_deadline = self._clock() + REPLY_TIMEOUT_S

    def _begin_step(self, i: int) -> None:
        """Start the program's step ``i``: a ramp's lines, or a hold's timer."""
        assert self.plan is not None
        self.step = i
        self._step_started = self._clock()
        st = self.plan.steps[i]
        n = len(self.plan.steps)
        where = f"Step {st.number} of {n}: " if n > 1 else ""
        if st.kind == "hold":
            self.test = RunPhase.HOLD
            self._await = ""
            self._hold_until = self._clock() + st.hold_s
            self._say(f"{where}{st.told}. PAUSE is not available during a hold; STOP is.")
            return
        lines = st.lines
        if st.path_by is not None:
            # Proteus' reading of "+4 mm" (steps 39-41): from the previous Path
            # ramp's set end, else from the piston as the ramp is sent.
            base = (self._path_set_end if st.path_from == FROM_PREVIOUS
                    else self._path_now)
            if base is None:
                self._stop_for(f"step {st.number} is a Path ramp by {st.path_by:+g} mm and "
                               "the piston's position is not known")
                return
            end = round(base + st.path_by, 3)
            try:
                lines = lines + (cmd.ramp_line(self.link.limits, "path", st.speed, end),)
            except NotAllowed as exc:
                self._stop_for(f"step {st.number}, to {end:g} mm: {exc}")
                return
            self._path_set_end = end
        elif st.control == "path":
            self._path_set_end = st.to_value
        for line in lines:
            self.link.send(line)
            if line.startswith("#D05"):
                self._interval_ms = int(line[4:]) * 10
        if st.switches_break_on and n > 1:
            self._say(f"{where}break detection on from here.")
        self._expect(RunPhase.STARTING_RAMP, "#B35")

    def _step_done(self) -> None:
        """The running step ended (a ramp's ``#B02`` answered, or a hold's
        time up): the next step, or the end of the test."""
        assert self.plan is not None and self.step is not None
        last = self.step == len(self.plan.steps) - 1
        if not last:
            self._begin_step(self.step + 1)
            return
        self.link.send(cmd.CANCEL)
        self._end_test()
        self._restore_interval()

    def _end_test(self) -> None:
        self.test = RunPhase.NONE
        self.plan = None
        self.step = None
        self._await = ""

    def _stop_for(self, why: str) -> None:
        self.link.send(cmd.CANCEL)
        self._end_test()
        self._restore_interval()
        self._say(f"Test stopped (Cancel: pump off): {why}.", "error")

    def _heard_in_test(self, ev: TapEvent, msg) -> None:
        """What the controller said while a test runs."""
        if isinstance(msg, Sample):
            return
        if isinstance(msg, Ack):
            if self.test is RunPhase.ARMING and self._await == "#O":
                assert self.plan is not None
                self._send_all(self.plan.start_switches
                               + (self.plan.start_load, cmd.APPROACH))
                self.test = RunPhase.APPROACH
                self._await = ""
                self._say("Approaching the specimen…")
            elif self.test is RunPhase.STARTING_RAMP and self._await == "#O":
                self.test = RunPhase.RAMP
                self._await = ""
                st = self.current_step
                n = len(self.plan.steps) if self.plan else 1
                told = (f"step {st.number} of {n}, {st.told}" if st is not None and n > 1
                        else self.plan.told() if self.plan else "")
                self._say(f"Ramp running: {told}. STOP (or Esc) stops the pump.")
            return
        if isinstance(msg, Command) and msg.code == 27:
            # After a break the controller holds the load (step 32). This first
            # Cancel stops the pump; the operator's STOP, a second Cancel,
            # releases the load and the piston sinks; a third stops the sinking
            # (step 33). Kept manual (operator, 2026-10-20), so the session
            # stays connected and STOP stays available.
            self.link.send(cmd.CANCEL)
            self._end_test()
            self._restore_interval()
            self._say("The controller reported a break (#B27): pump off. The load may still be "
                      "held — press STOP to release it. If it does not come off within a few "
                      "seconds, press Disconnect, then STOP on the controller's keypad.",
                      "error")
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
            # Proteus answers every ramp end #B26; alone, the controller then
            # holds the force (steps 36-38); #B17 after it ends the test.
            self.link.send(cmd.RAMP_END_ANSWER)
            last = self.plan is None or self.step == len(self.plan.steps) - 1
            self._step_done()
            if last:
                self._say("The program reached its end: answered as Proteus does "
                          "(#B26), pump off.")

    # ---- the tick ------------------------------------------------------------

    def poll(self) -> list[TapEvent]:
        """Every line since the last poll — each controller line through the
        session's own checks first, then handed out.

        Advancing sends lines, and a write can take tens of milliseconds over
        USB; the controller may answer meanwhile. So after advancing the link is
        polled again and **whatever came is heard too**, until nothing new is
        waiting. (It once was only handed out: the controller's ``#D138.6``,
        arriving while ``#B40`` was written, never reached the start-up check,
        which then aborted — 2026-10-20.)
        """
        out: list[TapEvent] = []
        events, self._carry = self._carry + self.link.poll(), []
        for _ in range(20):
            now = self._clock()
            for ev in events:
                if ev.direction == CTRL_TO_PC:
                    self._heard(ev, now)
            out += events
            self._advance(now)
            events = self.link.poll()
            if not events:
                break
        else:
            # Twenty rounds without the queue running dry: hear the rest on the
            # next poll rather than spin here.
            self._carry = events
        return out

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
                    self._interval_ms = cmd.STARTUP_INTERVAL_MS
                    self._apply_switches()
                    self._restore_interval()
                    self._say("Connected: the controller is in PC mode and streaming; Peak "
                              f"{'on' if self.peak else 'off'}, break detection off until "
                              "a test's program sets it. START begins a test; STOP (or "
                              "Esc) stops the pump.")
                else:
                    self._abort("the controller streamed before it was asked to")
                return
            self._got.append(ev.text)
            self.replies.append(ev.text)
        elif self.state is SessionState.CONNECTED:
            if isinstance(msg, Sample):
                self._last_sample = now
                self._silent_said = False
                limits = self.link.limits
                if limits is not None and limits.path_channel in msg.raw:
                    self._path_now = limits.path_mm(msg.raw[limits.path_channel])
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
            if self.test is RunPhase.HOLD and now >= self._hold_until:
                last = self.plan is None or self.step == len(self.plan.steps) - 1
                self._step_done()
                if last:
                    self._say("The program's last hold ended: pump off, load released "
                              "(Cancel).")
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
