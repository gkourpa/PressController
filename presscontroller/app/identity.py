"""The app's name and its Windows identity — stable identifiers, not display text.

As in DAqReader: the App User Model ID groups taskbar buttons and keys pinning,
so it **never changes**; without it the taskbar shows python.exe.
"""

from __future__ import annotations

import sys

DISPLAY_NAME = "PressController"
APP_ID = "gkourpa.PressController"


def set_app_user_model_id(app_id: str = APP_ID) -> bool:
    """Claim the taskbar identity on Windows, before the first window. Never fatal."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        return False
    return True
