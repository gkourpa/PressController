"""Talking to the controller ourselves, instead of Proteus. Qt-free.

Connect, stream, switch Peak and break detection, run a test as Proteus does
(START, CONTINUE, PAUSE, STOP), disconnect. What may be sent is an allowlist
of exact lines and four range-checked built lines
(:mod:`~presscontroller.control.commands`) checked at the one place a byte
leaves (:class:`~presscontroller.control.link.ControllerLink`); the start-up is
Proteus' own, replayed line for line (:mod:`~presscontroller.control.session`).

The listen-only monitor does not import this package, so it stays unable to send.
"""

from presscontroller.control.commands import ALLOWED, Limits, NotAllowed
from presscontroller.control.link import ControllerLink, open_for_control
from presscontroller.control.session import ControllerSession, SessionState, RunPhase

__all__ = ["ALLOWED", "ControllerLink", "ControllerSession", "Limits", "NotAllowed",
           "SessionState", "RunPhase", "open_for_control"]
