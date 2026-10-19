"""The DigiMaxx C-20 line protocol, as reverse-engineered in ``docs/PROTOCOL.md``.

Qt-free, hardware-free and config-free: bytes in, messages out. Everything a
message is *believed* to mean carries whether that belief is confirmed, because
the protocol was learned by listening and some of it is still a guess.
"""

from presscontroller.protocol.lines import CTRL_TO_PC, DIRECTIONS, PC_TO_CTRL, LineAssembler
from presscontroller.protocol.messages import (
    DECODED_RAMP_CHANNELS,
    Ack,
    Command,
    Message,
    Ramp,
    Reply,
    Sample,
    SetParam,
    Unknown,
    describe,
    parse,
    rate_text,
)

__all__ = [
    "Ack", "CTRL_TO_PC", "DECODED_RAMP_CHANNELS", "Command", "DIRECTIONS", "LineAssembler", "Message",
    "PC_TO_CTRL", "Ramp", "Reply", "Sample", "SetParam", "Unknown", "describe",
    "parse", "rate_text",
]
