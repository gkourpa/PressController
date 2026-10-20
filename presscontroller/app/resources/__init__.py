"""The application icon — one vector source, regenerated into a Windows .ico.

``icon.svg`` is the single source of truth. ``icon.ico`` (multi-resolution,
16-256 px) is a committed *generated* artefact for the two consumers that cannot
render SVG themselves: the Windows executable's own icon (PyInstaller ``icon=``)
and Qt's window and taskbar icon at runtime — loading the .ico avoids depending
on the QtSvg icon-engine plugin being present in a frozen build. Regenerate it
after editing the SVG with::

    python -m presscontroller.app.resources.generate_icon

The taskbar identity that decides *which* icon Windows shows is a separate
matter, in :mod:`presscontroller.app.identity`.

The files are package **data**: a non-editable install and a frozen build both
drop them unless they are declared (``pyproject.toml``, and the build spec when
there is one), and losing them is silent — :class:`QIcon` on a missing path
raises nothing and returns a null icon, so the windows simply have none.
"""

from __future__ import annotations

from pathlib import Path

RESOURCE_DIR = Path(__file__).parent
ICON_SVG = RESOURCE_DIR / "icon.svg"
ICON_ICO = RESOURCE_DIR / "icon.ico"


def app_icon():
    """The :class:`QIcon` for every window of this app, and for its taskbar button."""
    from PySide6.QtGui import QIcon

    return QIcon(str(ICON_ICO if ICON_ICO.exists() else ICON_SVG))
