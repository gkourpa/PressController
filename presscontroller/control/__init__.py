"""Talking to the controller ourselves, instead of Proteus. Qt-free.

Milestone 3a: **connect, stream, switch Peak and break detection, disconnect —
and nothing that moves the press.** What may be sent is a fixed allowlist
(:mod:`~presscontroller.control.commands`) checked at the one place a byte
leaves (:class:`~presscontroller.control.link.ControllerLink`); the start-up is
Proteus' own, replayed line for line (:mod:`~presscontroller.control.session`).

The listen-only monitor does not import this package, so it stays unable to send.
"""

from presscontroller.control.commands import ALLOWED, NotAllowed
from presscontroller.control.link import ControllerLink, open_for_control
from presscontroller.control.session import ControllerSession, SessionState

__all__ = ["ALLOWED", "ControllerLink", "ControllerSession", "NotAllowed", "SessionState",
           "open_for_control"]
