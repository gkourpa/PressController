"""Bytes off one wire into the protocol's lines, each stamped when it began.

Every message in both directions is one ASCII line ending ``CR LF``
(docs/PROTOCOL.md). A serial read returns whatever has arrived, so a line is
routinely split across reads and two lines can share one; the assembler is what
turns that into whole lines.

**A line ends at a CR or an LF, whichever comes first, and an empty line is no
line.** The controller once (2026-10-20, ``…110322_control.jsonl``) sent a reply's
CR, then a whole measurement line, then the reply's LF — ``#O
#D08…


``.
Ending lines only at ``CR LF`` read that as one unknown line ``#O
#D08…``; ending
at either byte reads ``#O`` and the measurement line, as they were meant.

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
"""What every line is sent with. Either byte of it ends a line read."""

_ENDS = (0x0D, 0x0A)

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
            if byte in _ENDS:
                if self._buf:
                    out.append((self._t0, _text(bytes(self._buf))))
                    self._buf.clear()
                continue
            if not self._buf:
                self._t0 = t
            self._buf.append(byte)
            if len(self._buf) >= MAX_LINE:
                out.append((self._t0, _text(bytes(self._buf))))
                self._buf.clear()
        return out

    @property
    def pending(self) -> bytes:
        """What has arrived of a line not yet terminated."""
        return bytes(self._buf)


def _text(raw: bytes) -> str:
    return raw.decode("ascii", errors="backslashreplace")
