"""The entry point: choose the press file and the data folder, then listen.

::

    python -m presscontroller.app                       # the live tap
    python -m presscontroller.app --replay CAPTURE.jsonl [--speed 10]
    python -m presscontroller.app --press PRESS.toml    # another press file
    python -m presscontroller.app --control             # this program in charge

**Control mode** talks to the controller itself, with the old PC unplugged,
through the settings' ``control_port`` (the first time, the press file's
``[control] port``, then remembered), and runs tests as Proteus does, within the
press file's ``[limits]`` (:mod:`presscontroller.control`, docs/motion.md). It
connects by itself when the settings' ``auto_connect`` is on. (A confirmation
dialog on every launch was dropped once control mode had run on the press —
operator, 2026-10-20; Connect still listens first and refuses a busy line.) Its
tests go where the monitor's do, and in debug mode its session recording,
named ``*_control.jsonl``.

The window opens where, and as, it was last closed (size, position, maximized
or full screen), in the settings' theme.

**The first run asks for nothing it can do without** (operator, 2026-10-20: the
press PC has no file of ours, and none is to be copied there). With no press
file it writes the lab's (:data:`~presscontroller.config.press.DEFAULT_PRESS`)
beside the settings; with no data folder it uses ``Documents\\PressController``;
with no control port it opens Settings at Connection to pick one. All three are
remembered in the global settings, and File → Settings… changes them. A press
file named with ``--press`` that is not there is still asked for.

Every test goes to ``<data>/tests/`` as a CSV, rewritten every few seconds
while it runs. **Only in debug mode** (the settings' ``debug_mode``, off unless
chosen — operator, 2026-10-22) does every byte heard also go to
``<data>/captures/``. A replay writes nothing on its own: it is the
recording already, and a test from it is saved only on request.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from presscontroller.app.identity import DISPLAY_NAME, set_app_user_model_id
from presscontroller.app.resources import app_icon
from presscontroller.app.main_window import MainWindow
from presscontroller.app.theme import apply_theme, follow_color_scheme
from presscontroller.config.parse import ConfigError
from presscontroller.config.press import PressConfig, load_press, write_default_press
from presscontroller.config.settings import (
    default_data_dir,
    default_press_path,
    load_settings,
    save_settings,
)
from presscontroller.monitor import Monitor
from presscontroller.tap import CaptureWriter, ReplayTap, SerialTap
from presscontroller.tap.serial_tap import LINE_SETTINGS


def _args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="presscontroller", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--press", help="the press file to use (else the one used last)")
    p.add_argument("--replay", help="replay a capture instead of listening to the tap")
    p.add_argument("--speed", type=float, default=1.0, help="replay speed (default 1)")
    p.add_argument("--control", action="store_true",
                   help="talk to the controller ourselves (old PC unplugged)")
    return p.parse_args(argv)


def _choose_press(settings, given: str | None) -> tuple[PressConfig, str] | None:
    """The press file to use, asked for until one loads without problems.

    With none named and none remembered (or the remembered one gone), the
    default one beside the settings, written the first time."""
    path = given or settings.press_file
    if not given and not (path and Path(path).is_file()):
        path = str(write_default_press(default_press_path()))
    while True:
        if not path or not Path(path).is_file():
            path, _ = QFileDialog.getOpenFileName(None, "Choose the press file", "",
                                                  "Press files (*.toml)")
            if not path:
                return None
        try:
            cfg, problems = load_press(path)
        except ConfigError as exc:
            problems = [str(exc)]
        if not problems:
            return cfg, str(Path(path).resolve())
        QMessageBox.warning(None, DISPLAY_NAME, f"{path} cannot be used:\n\n"
                            + "\n".join(f"• {p}" for p in problems))
        path = ""


def _choose_data_dir(settings) -> str | None:
    """The folder for captures and tests: the remembered one, else
    ``Documents\\PressController``, made if missing. Asked for only when it
    cannot be made — a remembered folder on a drive that is not there is not
    silently swapped for another."""
    path = settings.data_dir or str(default_data_dir())
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        pass
    chosen = QFileDialog.getExistingDirectory(
        None, "Choose where the captures and tests are kept")
    return chosen or None


def _choose_control_port(settings, save):
    """The settings with a control port: the first time, Settings opens at
    Connection to pick it. ``None`` when the operator cancels."""
    from presscontroller.app.settings_dialog import SettingsDialog

    QMessageBox.information(None, DISPLAY_NAME, "Choose the port the controller cable is "
                            "plugged into (the USB serial adapter's COM port). It is "
                            "remembered; File → Settings… changes it.")
    dlg = SettingsDialog(settings, save=save).show_tab("Connection")
    if not dlg.exec() or not dlg.settings.control_port:
        return None
    return dlg.settings


def main(argv: list[str] | None = None) -> int:
    args = _args(sys.argv[1:] if argv is None else argv)
    set_app_user_model_id()
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName(DISPLAY_NAME)
    app.setWindowIcon(app_icon())
    follow_color_scheme(app)

    settings, problem = load_settings()
    apply_theme(app, settings.theme)
    if problem:
        QMessageBox.warning(None, DISPLAY_NAME, problem)
    chosen = _choose_press(settings, args.press)
    if chosen is None:
        return 0
    press, press_path = chosen
    settings = replace(settings, press_file=press_path)

    if args.control and args.replay:
        QMessageBox.warning(None, DISPLAY_NAME, "--control and --replay cannot be used together.")
        return 1
    if args.control:
        return _run_control(app, settings, press)

    tests_dir = None
    if args.replay:
        source = ReplayTap(args.replay, speed=args.speed)
    else:
        if press.tap_problems():
            QMessageBox.warning(None, DISPLAY_NAME, "The listen-only monitor needs the tap's "
                                f"two ports, named in the press file {press_path}:\n\n"
                                + "\n".join(f"• {p}" for p in press.tap_problems()))
            return 1
        data_dir = _choose_data_dir(settings)
        if data_dir is None:
            return 0
        settings = replace(settings, data_dir=data_dir)
        tests_dir = Path(data_dir) / "tests"
        start = datetime.now()
        capture = (CaptureWriter(Path(data_dir) / "captures" / f"{start:%Y%m%d_%H%M%S}.jsonl",
                                 ports={"PC>CTRL": press.pc_port, "CTRL>PC": press.ctrl_port},
                                 settings=LINE_SETTINGS, start=start)
                   if settings.debug_mode else None)
        source = SerialTap(press.pc_port, press.ctrl_port, capture=capture)
    save_settings(settings)

    win = MainWindow(Monitor(press), source, tests_dir=tests_dir, settings=settings)
    win.restore_place()
    try:
        win.start()
    except Exception as exc:
        source.close()
        QMessageBox.critical(None, DISPLAY_NAME,
                             f"The tap could not be opened: {exc}\n\nCheck that both USB "
                             f"adapters are plugged in and that {press.pc_port} and "
                             f"{press.ctrl_port} are the ports named in the press file.")
        return 1
    win.show_in_place()
    return app.exec()


def _run_control(app, settings, press: PressConfig) -> int:
    from presscontroller.app.control_window import ControlWindow
    from presscontroller.control import ControllerLink, ControllerSession, Limits

    port = settings.control_port or press.control_port.strip()
    if not port:
        chosen = _choose_control_port(settings, save_settings)
        if chosen is None:
            return 0
        settings, port = chosen, chosen.control_port
    settings = replace(settings, control_port=port)
    data_dir = _choose_data_dir(settings)
    if data_dir is None:
        return 0
    settings = replace(settings, data_dir=data_dir)
    save_settings(settings)
    start = datetime.now()
    capture = (CaptureWriter(
        Path(data_dir) / "captures" / f"{start:%Y%m%d_%H%M%S}_control.jsonl",
        ports={"control": port}, settings=LINE_SETTINGS, start=start)
               if settings.debug_mode else None)
    session = ControllerSession(ControllerLink(port, limits=Limits.from_press(press),
                                               capture=capture))
    win = ControlWindow(Monitor(press), session, tests_dir=Path(data_dir) / "tests",
                        settings=settings)
    win.restore_place()
    try:
        win.start()
    except Exception as exc:
        session.close()
        QMessageBox.critical(None, DISPLAY_NAME,
                             f"{port} could not be opened: {exc}\n\nIs the "
                             "adapter plugged in, and is the monitor or the sniffer still "
                             "using it?")
        return 1
    if settings.auto_connect:
        session.connect()
    win.show_in_place()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
