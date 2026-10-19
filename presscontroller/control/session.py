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
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from presscontroller.control import commands as cmd
from presscontroller.control.link import ControllerLink
from presscontroller.protocol import CTRL_TO_PC, Command, Sample, parse
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


class SessionState(Enum):
    CLOSED = "port closed"
    IDLE = "not connected"
    LISTENING = "checking the line is free"
    CONNECTING = "connecting"
    CONNECTED = "connected, in PC mode"
    FAILED = "connection refused or aborted"


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
        elif self.state is SessionState.CONNECTED and isinstance(msg, Sample):
            self._last_sample = now
            self._silent_said = False

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
