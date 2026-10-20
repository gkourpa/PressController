"""Launch PressController: ``python run_app.py [--control]`` (same as ``python -m presscontroller.app``).

Also the frozen build's entry point (PressController.spec)."""

import sys

from presscontroller.app.main import main

if __name__ == "__main__":
    sys.exit(main())
