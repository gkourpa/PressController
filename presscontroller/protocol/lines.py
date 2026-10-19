"""Bytes off one wire into the protocol's lines, each stamped when it began.

Every message in both directions is one ASCII line ending ``CR LF``
(docs/PROTOCOL.md). A serial read returns whatever has arrived, so a line is
routinely split across reads and two lines can share one; the assembler is what
turns that into whole lines.

**A line is stamped with the arrival of its first byte**, not its last. At
9600 baud a 34-byte stream line takes 35 ms to arrive, and the moment the
controller started sending it is the closer of the two to when it measured.

The two wires are separate, so each direction has its own assembler; the line
is the unit the directions are interleaved in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Direction labels, as the captures written by ``tools/sniff.py`` spell them.
PC_TO_CTRL = "PC>CTRL"
CTRL_TO_PC = "CTRL>PC"
DIRECTIONS = (PC_TO_CTRL, CTRL_TO_PC)

TERMINATOR = b"\r\n"

#: A line longer than this without a terminator is noise or a wrong baud rate,
#: not a message: the longest one seen is the 35-byte stream line. It is handed
#: on as it stands rather than held, so garbage cannot grow without bound.
MAX_LINE = 256


@dataclass
class LineAssembler:
    """Collect one direction's bytes and hand back the lines they complete."""

    direction: str
    _buf: bytearray = field(default_factory=bytearray)
    _t0: float | None = None

    def feed(self, data: bytes, t: float) -> list[tuple[float, str]]:
        """Add ``data``, which arrived at ``t``; return ``(t_first_byte, text)``
        for every line it completed, terminator removed.

        Bytes that are not ASCII are kept visible as ``\\xNN`` rather than
        dropped, so a corrupted line is seen to be corrupted.
        """
        out: list[tuple[float, str]] = []
        for byte in data:
            if not self._buf:
                self._t0 = t
            self._buf.append(byte)
            if self._buf.endswith(TERMINATOR):
                out.append((self._t0, _text(bytes(self._buf[:-2]))))
                self._buf.clear()
            elif len(self._buf) >= MAX_LINE:
                out.append((self._t0, _text(bytes(self._buf))))
                self._buf.clear()
        return out

    @property
    def pending(self) -> bytes:
        """What has arrived of a line not yet terminated."""
        return bytes(self._buf)


def _text(raw: bytes) -> str:
    return raw.decode("ascii", errors="backslashreplace")
