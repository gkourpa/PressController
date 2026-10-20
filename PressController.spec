# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build spec — the lab's frozen Windows build (DAqReader's, adapted).

    python tools/build_installer.py        # this, then Inno Setup

produces ``dist/PressController/PressController.exe``, the GUI app. The Start
menu shortcuts the installer makes pass ``--control`` for control mode and
nothing for the listen-only monitor.

**--onedir, not --onefile**, deliberately (DAqReader's reasons): a onefile build
re-extracts the whole bundle on every launch — slow, and an antivirus trigger on
a lab machine — while a folder starts at once and is easy to inspect.

``serial`` (pyserial) is imported inside functions — the tap and the control
link open their ports lazily — so the import scanner would miss it; it is
collected explicitly. ``collect_all`` only *warns* when a package is absent.

The app icon is package *data*, which PyInstaller never collects on its own;
without these lines ``app_icon()`` finds no file and Qt silently shows none. The
destination mirrors the source so ``Path(__file__).parent`` still resolves.
"""

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

d, b, h = collect_all("serial")
datas += d
binaries += b
hiddenimports += h

datas += [
    ("presscontroller/app/resources/icon.ico", "presscontroller/app/resources"),
    ("presscontroller/app/resources/icon.svg", "presscontroller/app/resources"),
]

a = Analysis(
    ["run_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    # Build and test tools that must never ship inside the application.
    excludes=["pytest", "PyInstaller", "tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PressController",
    icon="presscontroller/app/resources/icon.ico",
    console=False,       # GUI app: no console window
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="PressController",
)
