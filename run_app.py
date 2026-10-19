"""Launch the PressController monitor: ``python run_app.py`` (same as ``python -m presscontroller.app``)."""

import sys

from presscontroller.app.main import main

if __name__ == "__main__":
    sys.exit(main())
