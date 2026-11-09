"""**Program → Edit**: the test's program as a list of steps the operator builds
(operator, 2026-11-09: "a dynamic list of steps where they should be able to
add/remove steps"; docs/ui.md, "The program").

* Each **step** is a row: a **ramp**, with its own control — **Force** "to
  [ ] kN at [ ] kN/s" (up or down from where the step before ended, the arrow
  says which), or **Path** "to [ ] mm" (a position) or "by [ ] mm" (a signed
  distance, counted as Proteus counts it: from the previous ramp's end when
  that was a Path ramp, else from the piston), "at [ ] mm/min" — or a **hold**
  "[ ] s"; **↑ ↓** move it, **Copy** duplicates it, **✕** removes it.
  **+ Ramp** and **+ Hold** add steps. A line separates the rows (operator,
  2026-11-09).
* **Break detection** is a ramp's "on from here": it stays on for every step
  after, shown so — switching it off mid-test was never recorded.
* Under a row, in red, **what is wrong with it**: the planner's own words
  (:mod:`presscontroller.control.program`), the same check START makes. OK is
  off while anything is wrong. The lines a step sends are not shown here
  (operator, 2026-11-09): the log shows them as they go.
* The **preview** at the top is the planned program
  (:mod:`~presscontroller.app.program_view`), the steps under break detection
  shaded.

The dialog edits a copy; :attr:`ProgramDialog.test` is the result after OK.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from presscontroller.app.program_view import ProgramStrip
from presscontroller.app.theme import danger, muted, styled, warning
from presscontroller.config.settings import (
    MAX_HOLD_S,
    MAX_INTERVAL_MS,
    MAX_STEPS,
    MIN_HOLD_S,
    MIN_INTERVAL_MS,
    RAMP_CONTROL_LABELS,
    RAMP_CONTROLS,
    ProgramStep,
    TemplateSettings,
)
from presscontroller.control.program import Program, duration_text

#: What a new step starts as.
NEW_RAMP = ProgramStep("ramp", 100.0, 2.0)
NEW_HOLD = ProgramStep("hold", hold_s=10.0)


def _spin(lo: float, hi: float, value: float, decimals: int, step: float,
          suffix: str) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setSuffix(suffix)
    box.setValue(value)
    box.setKeyboardTracking(False)
    return box


def _muted(text: str = "") -> QLabel:
    lbl = QLabel(text)
    styled(lbl, lambda w: w.setStyleSheet(f"color: {muted(w)};"))
    return lbl


def _arrow(st) -> str:
    """Up or down, where the plan knows; nothing where only the press will."""
    if st.path_by is not None:
        return "↑" if st.path_by > 0 else "↓"
    if st.from_value is None or st.to_value is None:
        return ""
    return "↑" if st.to_value >= st.from_value else "↓"


def _rule() -> QFrame:
    """The line between two rows, in the theme's quiet colour."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    styled(line, lambda w: w.setStyleSheet(f"color: {muted(w)};"))
    return line


def _small_button(text: str, name: str) -> QPushButton:
    b = QPushButton(text)
    b.setAccessibleName(name)
    b.setFixedWidth(max(32, b.fontMetrics().horizontalAdvance(text) + 18))
    return b


class ProgramDialog(QDialog):
    def __init__(self, test: TemplateSettings, planner: Callable[[TemplateSettings], Program],
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("PressController — program")
        self.test = test
        self._planner = planner
        self._steps: list[ProgramStep] = list(test.steps)
        self._rows: list[dict] = []

        # ---- the interval ----------------------------------------------------------
        self.interval = QSpinBox()
        self.interval.setRange(MIN_INTERVAL_MS, MAX_INTERVAL_MS)
        self.interval.setSingleStep(10)
        self.interval.setSuffix(" ms")
        self.interval.setValue(test.measuring_interval_ms)
        self.interval.setKeyboardTracking(False)
        self.interval.valueChanged.connect(self._replan)
        self.start_note = _muted()
        top = QHBoxLayout()
        top.addWidget(QLabel("Measuring interval"))
        top.addWidget(self.interval)
        top.addSpacing(16)
        top.addWidget(self.start_note, 1)

        # ---- preview -------------------------------------------------------------
        self.strip = ProgramStrip(framed=True)      # as in the control window
        self.summary = _muted()

        # ---- the steps -----------------------------------------------------------
        # The grid sits at the top of the scroll area with the spare height
        # below it: a grid given the whole height shares it out between its
        # rows, and a row grew with every step removed (operator, 2026-11-09).
        self._grid_host = QWidget()
        host = QVBoxLayout(self._grid_host)
        host.setContentsMargins(0, 0, 0, 0)
        rows = QWidget()
        host.addWidget(rows)
        host.addStretch(1)
        self._grid = QGridLayout(rows)
        self._grid.setContentsMargins(6, 4, 6, 4)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(4)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._grid_host)
        self._scroll = scroll

        self.add_ramp = QPushButton("+ Ramp")
        self.add_hold = QPushButton("+ Hold")
        self.add_ramp.clicked.connect(lambda: self._add([NEW_RAMP]))
        self.add_hold.clicked.connect(lambda: self._add([NEW_HOLD]))
        self.add_note = _muted()
        adds = QHBoxLayout()
        for b in (self.add_ramp, self.add_hold):
            adds.addWidget(b)
        adds.addWidget(self.add_note, 1)

        self.errors = QLabel()
        self.errors.setWordWrap(True)
        styled(self.errors, lambda w: w.setStyleSheet(f"color: {danger(w)};"))

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(self.strip)
        root.addWidget(self.summary)
        root.addWidget(scroll, 1)
        root.addLayout(adds)
        root.addWidget(self.errors)
        root.addWidget(self.buttons)
        self._rebuild()
        self.resize(940, 760)

    # ---- the model -----------------------------------------------------------------

    def current(self) -> TemplateSettings:
        """The program as the dialog holds it now."""
        return replace(self.test, steps=tuple(self._steps),
                       measuring_interval_ms=int(round(self.interval.value() / 10.0)) * 10)

    def _add(self, steps: list[ProgramStep], at: int | None = None) -> None:
        room = MAX_STEPS - len(self._steps)
        steps = steps[:max(0, room)]
        if at is None:
            self._steps += steps
        else:
            self._steps[at:at] = steps
        self._rebuild()

    def _move(self, i: int, d: int) -> None:
        j = i + d
        if 0 <= j < len(self._steps):
            self._steps[i], self._steps[j] = self._steps[j], self._steps[i]
            self._rebuild()

    def _remove(self, i: int) -> None:
        if len(self._steps) > 1:
            del self._steps[i]
            self._rebuild()

    def _copy(self, i: int) -> None:
        self._add([replace(self._steps[i], break_on=False)], i + 1)

    def _edit(self, i: int, **change) -> None:
        self._steps[i] = replace(self._steps[i], **change)
        if {"break_on", "control", "path_relative"} & set(change):
            self._rebuild()         # the row's fields, or the steps after it, change
        else:
            self._replan()

    def _set_path_mode(self, i: int, relative: bool) -> None:
        if self._steps[i].path_relative != relative:
            # A position and a distance are different numbers: start from one
            # that makes sense rather than carry 100 mm over as a distance.
            self._edit(i, path_relative=relative, path_mm=1.0 if relative else 100.0)

    # ---- the rows ------------------------------------------------------------------

    def _clear(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()            # not drawn while it waits to be deleted
                item.widget().deleteLater()
        self._rows = []

    def _header(self) -> None:
        for col, text in enumerate(("#", "Step", "Setting", "Break detection", "Time", "")):
            lbl = QLabel(f"<b>{text}</b>")
            self._grid.addWidget(lbl, 0, col)
        self._grid.addWidget(_rule(), 1, 0, 1, 6)

    def _rebuild(self) -> None:
        """Lay the rows out again: after a step is added, removed or moved, the
        control changed, or break detection's step moved."""
        self._clear()
        self._header()
        first_on = next((i for i, s in enumerate(self._steps)
                         if s.kind == "ramp" and s.break_on), None)
        for i, s in enumerate(self._steps):
            self._step_row(i, s, first_on)
        self._grid.setColumnStretch(2, 1)
        for b in (self.add_ramp, self.add_hold):
            b.setEnabled(len(self._steps) < MAX_STEPS)
        self.add_note.setText("New steps go at the end; ↑ ↓ move them. Each ramp has its "
                              "own control: Force or Path.")
        self._replan()

    def _row_widgets(self, r: int, number: int, kind: str, setting: QWidget,
                     bd: QWidget, buttons: list[QPushButton]) -> dict:
        n = QLabel(str(number))
        k = QLabel(f"<b>{kind}</b>")
        time = QLabel()
        time.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        btns = QWidget()
        bl = QHBoxLayout(btns)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(4)
        for b in buttons:
            bl.addWidget(b)
        problem = QLabel()
        problem.setWordWrap(True)
        styled(problem, lambda w: w.setStyleSheet(f"color: {danger(w)};"))
        for col, w in enumerate((n, k, setting, bd, time, btns)):
            self._grid.addWidget(w, r, col)
        self._grid.addWidget(problem, r + 1, 2, 1, 4)
        self._grid.addWidget(_rule(), r + 2, 0, 1, 6)
        return {"time": time, "problem": problem}

    def _step_row(self, i: int, s: ProgramStep, first_on: int | None) -> None:
        r = 2 + 3 * i
        setting = QWidget()
        sl = QHBoxLayout(setting)
        sl.setContentsMargins(0, 0, 0, 0)
        row: dict = {}
        if s.kind == "ramp":
            control = QComboBox()
            for name in RAMP_CONTROLS:
                control.addItem(RAMP_CONTROL_LABELS[name], name)
            control.setCurrentIndex(max(0, control.findData(s.control)))
            control.setAccessibleName(f"Step {i + 1} control")
            control.currentIndexChanged.connect(
                lambda _=0, i=i, box=control: self._edit(i, control=box.currentData()))
            arrow = QLabel()
            arrow.setFixedWidth(arrow.fontMetrics().horizontalAdvance("↓") + 6)
            sl.addWidget(control)
            sl.addWidget(arrow)
            if s.control == "path":
                mode = QComboBox()
                mode.addItem("to", False)
                mode.addItem("by", True)
                mode.setCurrentIndex(1 if s.path_relative else 0)
                mode.setAccessibleName(f"Step {i + 1}: to a position or by a distance")
                mode.currentIndexChanged.connect(
                    lambda _=0, i=i, box=mode: self._set_path_mode(i, box.currentData()))
                if s.path_relative:
                    end = _spin(-100.0, 100.0, s.path_mm, 3, 0.5, " mm")
                else:
                    end = _spin(0.001, 100000.0, s.path_mm, 3, 1.0, " mm")
                speed = _spin(0.01, 1000.0, s.speed_mm_min, 2, 0.5, " mm/min")
                end.valueChanged.connect(lambda v, i=i: self._edit(i, path_mm=v))
                speed.valueChanged.connect(lambda v, i=i: self._edit(i, speed_mm_min=v))
                sl.addWidget(mode)
            else:
                end = _spin(0.1, 100000.0, s.end_kn, 1, 10.0, " kN")
                speed = _spin(0.01, 1000.0, s.speed_kn_s, 2, 0.5, " kN/s")
                end.valueChanged.connect(lambda v, i=i: self._edit(i, end_kn=v))
                speed.valueChanged.connect(lambda v, i=i: self._edit(i, speed_kn_s=v))
                sl.addWidget(QLabel("to"))
            end.setAccessibleName(f"Step {i + 1} end")
            speed.setAccessibleName(f"Step {i + 1} speed")
            for w in (end, QLabel("at"), speed):
                sl.addWidget(w)
            row["arrow"] = arrow
            if first_on is None or i <= first_on:
                bd: QWidget = QCheckBox("on from here" if i == first_on else "off")
                bd.setChecked(i == first_on)
                bd.toggled.connect(lambda on, i=i: self._edit(i, break_on=on))
            else:
                bd = QLabel("on (stays on)")
                styled(bd, lambda w: w.setStyleSheet(f"color: {warning(w)};"))
        else:
            secs = _spin(MIN_HOLD_S, MAX_HOLD_S, s.hold_s, 1, 1.0, " s")
            secs.setAccessibleName(f"Step {i + 1} hold time")
            secs.valueChanged.connect(lambda v, i=i: self._edit(i, hold_s=v))
            at = _muted()
            sl.addWidget(secs)
            sl.addWidget(at)
            row["at"] = at
            bd = QLabel("")
        sl.addStretch(1)
        up, down = _small_button("↑", "Move up"), _small_button("↓", "Move down")
        copy, remove = _small_button("Copy", "Copy"), _small_button("✕", "Remove step")
        up.setEnabled(i > 0)
        down.setEnabled(i < len(self._steps) - 1)
        remove.setEnabled(len(self._steps) > 1)
        copy.setEnabled(len(self._steps) < MAX_STEPS)
        up.clicked.connect(lambda _=False, i=i: self._move(i, -1))
        down.clicked.connect(lambda _=False, i=i: self._move(i, 1))
        copy.clicked.connect(lambda _=False, i=i: self._copy(i))
        remove.clicked.connect(lambda _=False, i=i: self._remove(i))
        row.update(self._row_widgets(r, i + 1, "Ramp" if s.kind == "ramp" else "Hold",
                                     setting, bd, [up, down, copy, remove]))
        self._rows.append(row)

    # ---- planning ------------------------------------------------------------------

    def _replan(self) -> None:
        """Plan what the dialog holds and show it: each row's direction, time
        and trouble; the preview; OK only when nothing is wrong."""
        program = self._planner(self.current())
        self.program = program
        for row, st in zip(self._rows, program.steps):
            if "arrow" in row:
                row["arrow"].setText(_arrow(st))
            if "at" in row:
                row["at"].setText(st.told.split(" s ", 1)[1] if " s " in st.told else "")
            row["time"].setText("–" if st.seconds is None else duration_text(st.seconds))
            row["problem"].setText(st.problem or "")
            row["problem"].setVisible(bool(st.problem))
        self.strip.set_program(program)
        self.summary.setText(program.told())
        t = self.current()
        self.start_note.setText(
            f"Starts from the start load, {program.start_kn:.3g} kN. Break detection's "
            f"threshold: {t.break_threshold_per_mil:g} ‰ (Settings → Test).")
        steps_own = {f"step {s.number}: {s.problem}" for s in program.steps if s.problem}
        rest = [p for p in program.problems if p not in steps_own]
        self.errors.setText(" ".join(rest) if rest else
                            ("Fix the steps marked in red." if steps_own else ""))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(program.ok)

    def _accept(self) -> None:
        if not self._planner(self.current()).ok:
            return
        self.test = self.current()
        self.accept()
