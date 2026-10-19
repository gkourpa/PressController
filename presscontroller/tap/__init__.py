"""Where protocol lines come from: the live tap, or a recorded capture replayed.

Both sources hand out the same :class:`~presscontroller.tap.events.TapEvent`
through the same ``poll()``, so everything downstream — the monitor and the
window — runs identically on the press and on a file. That is what lets the
monitor be tested on real tests without the press.
"""

from presscontroller.tap.capture import CaptureWriter, read_capture
from presscontroller.tap.events import TapEvent
from presscontroller.tap.replay import ReplayTap
from presscontroller.tap.serial_tap import BAUD, SerialTap, open_read_only

__all__ = ["BAUD", "CaptureWriter", "ReplayTap", "SerialTap", "TapEvent",
           "open_read_only", "read_capture"]
