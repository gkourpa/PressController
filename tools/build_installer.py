"""Build the lab installer: PyInstaller, then Inno Setup, in one step.

    python tools/build_installer.py

Produces ``dist/installer/PressController-<version>-setup.exe``. Run that on the lab PC:
the first time it installs, every later time it upgrades in place, and neither
touches the operator's settings in %APPDATA% (see the notes at the top of
``installer/PressController.iss``).

**One command, because the two halves must not drift.** Compiling the .iss on its
own would package whatever happens to be sitting in ``dist/`` — possibly a build
from another commit — under a version number describing this one. Building both
here means the installer always contains the build its name claims.

**The version is ``presscontroller.__version__`` and nothing else** — ``0.1.0``, not
``0.1.0-g<commit>``: it is the number the operator reads in Windows' installed
programs and on the setup file. Every build is a new number instead (the version
is bumped and committed before each one; ``docs/development-and-testing.md``,
*Versioning*), which is what keeps two setups of one number from holding
different programs.

**So a build of uncommitted changes is refused.** It would carry a released
number without being that release, and would overwrite that release's setup file
in ``dist/installer/``. Try work in progress from source instead.

Needs Inno Setup 6 (``ISCC.exe``). Found in its default install locations, or set
``ISCC`` to its full path.

Deliberately in ``tools/``, not ``presscontroller/``: this is a build step on the
developer's machine and must never ship inside the application it packages.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "PressController.spec"
ISS = ROOT / "installer" / "PressController.iss"
DIST = ROOT / "dist" / "PressController"
OUT = ROOT / "dist" / "installer"


def _iscc() -> Path:
    candidates = [os.environ.get("ISCC", "")]
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        if base:
            candidates.append(os.path.join(base, "Inno Setup 6", "ISCC.exe"))
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    sys.exit("Inno Setup 6 not found. Install it (winget install JRSoftware.InnoSetup) "
             "or set ISCC to the full path of ISCC.exe.")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()


def _version() -> str:
    """``presscontroller.__version__``, e.g. ``"0.1.0"``."""
    # Read, not imported: importing `presscontroller` here would run package code in the
    # build environment for the sake of one string.
    text = (ROOT / "presscontroller" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"', text, re.M).group(1)


def main() -> None:
    iscc = _iscc()                       # fail before a two-minute build, not after
    if _git("status", "--porcelain"):
        sys.exit("Uncommitted changes: commit them (with the version bumped) before "
                 "building an installer.")
    version = _version()
    print(f"building {version}", flush=True)

    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", str(SPEC)],
                   cwd=ROOT, check=True)
    for exe in ("PressController.exe",):
        if not (DIST / exe).is_file():
            sys.exit(f"PyInstaller finished but {exe} is missing from {DIST}")

    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(iscc), "/Q", f"/DAppVersion={version}",
                    f"/DSourceDir={DIST}", f"/DOutputDir={OUT}", str(ISS)],
                   cwd=ISS.parent, check=True)

    setup = OUT / f"PressController-{version}-setup.exe"
    if not setup.is_file():
        sys.exit(f"Inno Setup finished but {setup} was not produced")
    print(f"\ninstaller: {setup}  ({setup.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
