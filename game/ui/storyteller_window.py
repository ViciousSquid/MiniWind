"""Storyteller Studio, a desktop window of its own; console ``storyteller studio``.

A real top-level Qt window (move it to another monitor, resize it, minimise
it) with three tabs:

* **Live**   -- the state, live sensors, current levers, journey weights and
  hours, the decisions and their reasons, and the last observations.
* **Levers** -- each pacing state's lever table, edited with spin boxes
  (type, use the arrows or the wheel); an edit applies on the storyteller's
  ordinary samples and is saved with the session. **Reset state edits** and
  the pacing switch sit above the table.
* **World**  -- the world evidence the storyteller reads, explained.

The strip along the top collapses the window to just itself (the arrow) and
keeps it above other windows (the drawing pin; :mod:`game.ui.window_strip`).

Reading it never samples the storyteller or draws a random number.
"""

import json

import html

from PyQt5.QtCore import Qt, QTimer

from .window_strip import WindowStrip
from PyQt5.QtWidgets import (QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..living.journeys import KINDS
from ..sim.storyteller import TUNING
from ..storyteller_studio import world_explanations


def _timestamp(hours):
    if hours is None:
        return "not sampled yet"
    day, hour = divmod(float(hours), 24)
    return f"Day {int(day)} {int(hour):02d}:{int((hour % 1) * 60):02d}"


def rows_for(storyteller):
    """Read the sampler's existing data; inspection never triggers a sample."""
    if storyteller is None:
        return [("text", "No active MiniWind storyteller.")]
    levers = storyteller.levers if storyteller.enabled else {"kind_weights": {}, "kind_hours": {}}
    rows = [("heading", f"State: {storyteller.state}"),
            ("text", f"Last sampled: {_timestamp(storyteller.last_sample)}. Live sensor readings; edit data on the Levers tab."),
            ("heading", "Live sensors")]
    for key, value in storyteller.sensors.items():
        if key != "law":
            rows.append(("text", f"{key.replace('_', ' ')}: {json.dumps(value, ensure_ascii=False)}"))
    rows.append(("heading", "Current levers"))
    labels = {"population": "Road population", "hunter_bounty": "Hunter bounty threshold",
              "lair_refill_scale": "New lair refill delay multiplier",
              "market_chance": "Market trip chance", "destination_bias": "Town destination multiplier",
              "vendetta_bias": "Vendetta arrival multiplier"}
    labels["writ_hunter_scale"] = "Old unpaid writ hunter threshold multiplier"
    rows.append(("text", "Pacing enabled." if storyteller.enabled else
                 "Pristine ecology: authored defaults; storyteller sensors idle."))
    for key, value in levers.items():
        if key not in ("kind_weights", "kind_hours"):
            rows.append(("text", f"{labels.get(key, key)}: {json.dumps(value, ensure_ascii=False)}"))
    rows.append(("heading", "Journey weights and departure hours"))
    for kind, spec in KINDS.items():
        weight = levers["kind_weights"].get(kind, spec["weight"])
        lo, hi = levers["kind_hours"].get(kind, spec["hours"])
        hours = f"{lo:02g}:00–{hi:02g}:00" + (" (overnight)" if lo > hi else "")
        rows.append(("text", f"{kind}: weight {weight:g}; departs {hours}"))
    rows.append(("heading", "Decisions and reasons"))
    rows.extend(("text", f"{label}: {reason}") for label, reason in storyteller.inspector_rows()
                if label != "State decision")  # the sample history below already shows it
    rows.append(("heading", f"Last {TUNING['observation_cap']} observations · newest first"))
    observations = storyteller.observations
    if not observations:
        rows.append(("text", "No observations yet. Waiting for the next storyteller sample."))
    for observation in observations:
        rows.append(("heading", f"{_timestamp(observation['time'])} · {observation['state']}"))
        rows.append(("text", observation["reason"]))
        law = observation["sensors"].get("law", {})
        if law:
            rows.append(("text", "Regional law: " + "; ".join(
                f"{region}: bounty {row['bounty']}, phase {row['phase']}"
                for region, row in law.items())))
    return rows


_STYLE = """
QWidget { background: #14171d; color: #e4e6ec; font-size: 10pt; }
QTabWidget::pane { border: 1px solid #2c3340; }
QTabBar::tab { background: #2d323c; color: #e4e6ec; padding: 5px 18px; margin-right: 2px; }
QTabBar::tab:selected { background: #415f7d; }
QTextBrowser, QScrollArea { background: #101318; border: none; }
QPushButton { background: #37414f; border: 1px solid #4a5566; padding: 4px 12px; }
QPushButton:hover { background: #435064; }
QPushButton:checked { background: #415f7d; }
QDoubleSpinBox { background: #2d4254; border: 1px solid #44607a; padding: 2px 4px; }
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 18px; background: #3b5670;
    border-left: 1px solid #44607a; }
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background: #4d6d8c; }
QDoubleSpinBox::up-arrow { width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-bottom: 5px solid #e4e6ec; }
QDoubleSpinBox::down-arrow { width: 0; height: 0; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid #e4e6ec; }
QLabel#heading { color: #96cde1; font-weight: bold; padding-top: 8px; }
"""

#: How often the window re-reads the storyteller (milliseconds).
REFRESH_MS = 500

_open = []


def _limits(path):
    """(low, high, step) for the lever at *path* (the old drag cells' rules)."""
    step = 0.01 if path[0] in ("market_chance", "writ_hunter_scale", "lair_refill_scale") else 1.0
    high = 24 if path[0] == "kind_hours" else 1 if path[0] == "market_chance" else 10000
    low = 0.01 if path[0] == "destination_bias" else 0
    return low, high, step


def _html(rows):
    out = []
    for kind, text in rows:
        if kind == "heading":
            out.append(f'<p style="color:#96cde1; font-weight:bold; margin-top:10px">{html.escape(text)}</p>')
        else:
            out.append(f'<p style="margin:2px 0">{html.escape(text)}</p>')
    return "".join(out)


class StorytellerWindow(QWidget):
    """Storyteller Studio (module docstring)."""

    TABS = ("Live", "Levers", "World")

    def __init__(self, view, parent=None):
        super().__init__(parent, Qt.Window)
        self.view = view
        self.setWindowTitle("Storyteller Studio")
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setStyleSheet(_STYLE)
        self.resize(560, 640)
        self.setMinimumSize(380, 300)
        self.edit_state = None
        self.message = ""
        self._spins = {}                 # lever path -> spin box
        self._levers_for = None          # (storyteller, state) the form shows

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)
        self.body = QWidget()
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(4, 0, 4, 4)
        # The strip: collapse arrow, the live state, the pin.
        self.strip = WindowStrip(self, self.body)
        name = QLabel("STORYTELLER STUDIO")
        name.setStyleSheet("font-weight: bold; background: transparent;")
        self.live_state = QLabel("")
        self.live_state.setStyleSheet("font-weight: bold; background: transparent;")
        self.strip.add(name, 1)
        self.strip.add(self.live_state)
        outer.addWidget(self.strip)
        outer.addWidget(self.body, 1)

        self.tabs = QTabWidget()
        self.live = QTextBrowser()
        self.world = QTextBrowser()
        self.levers = QWidget()
        lv = QVBoxLayout(self.levers)
        lv.setContentsMargins(6, 6, 6, 6)
        states = QHBoxLayout()
        self._state_buttons = {}
        for state in TUNING["states"]:
            button = QPushButton(state)
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, st=state: self.choose_state(st))
            self._state_buttons[state] = button
            states.addWidget(button)
        states.addStretch(1)
        lv.addLayout(states)
        actions = QHBoxLayout()
        self.reset_button = QPushButton("Reset state edits")
        self.reset_button.clicked.connect(self.reset_state)
        self.pacing_button = QPushButton("Pacing on")
        self.pacing_button.clicked.connect(self.toggle_pacing)
        actions.addWidget(self.reset_button)
        actions.addWidget(self.pacing_button)
        actions.addStretch(1)
        lv.addLayout(actions)
        self.form_area = QScrollArea()
        self.form_area.setWidgetResizable(True)
        lv.addWidget(self.form_area, 1)
        self.tabs.addTab(self.live, "Live")
        self.tabs.addTab(self.levers, "Levers")
        self.tabs.addTab(self.world, "World")
        self.tabs.currentChanged.connect(lambda _i: self.refresh(force=True))
        layout.addWidget(self.tabs, 1)
        self.status = QLabel("")
        self.status.setStyleSheet("color: #b9bec8;")
        layout.addWidget(self.status)

        self._shown = {}
        #: Live and World as last read from a live session (kept when Play
        #: Mode ends).
        self._kept = {}
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(REFRESH_MS)
        self.refresh(force=True)

    # -- what it reads -------------------------------------------------------
    def _storyteller(self):
        logic = getattr(self.view, "logic_thread", None)
        return getattr(getattr(logic, "_miniwind", None), "storyteller", None)

    @property
    def tab(self) -> str:
        return self.TABS[self.tabs.currentIndex()]

    @tab.setter
    def tab(self, name):
        self.tabs.setCurrentIndex(self.TABS.index(name))

    def lever_rows(self, story, state):
        """``[(heading or None, label, path, value)]`` of *state*'s lever table."""
        table = story.state_levers(state)
        rows = []
        for key, value in table.items():
            if key not in ("kind_weights", "kind_hours"):
                rows.append((None, key.replace("_", " "), (key,), value))
        rows.append(("Journey weights", None, None, None))
        for kind, spec in KINDS.items():
            rows.append((None, kind, ("kind_weights", kind), table["kind_weights"].get(kind, spec["weight"])))
        rows.append(("Departure windows", None, None, None))
        for kind, spec in KINDS.items():
            for i, value in enumerate(table["kind_hours"].get(kind, spec["hours"])):
                rows.append((None, f"{kind} {'from' if i == 0 else 'until'}", ("kind_hours", kind, i), value))
        return rows

    # -- showing it ----------------------------------------------------------
    def refresh(self, force=False):
        story = self._storyteller()
        tab = self.tab
        if story is None and (self._kept or self._levers_for is not None):
            # Play Mode has ended: keep what was last shown, read-only.
            self.live_state.setText("Play Mode ended")
            self.message = "Play Mode ended · showing the last report · live again when you next play"
            self.status.setText(self.message)
            if tab == "Levers":
                self._refresh_levers(None, force)
            elif tab in self._kept and self._shown.get(tab) != self._kept[tab]:
                self._show_text(tab, self._kept[tab])
            return
        if story is not None and self.message.startswith("Play Mode ended"):
            self.message = ""
        self.live_state.setText(f"Live: {story.state}" if story is not None else "No active storyteller")
        if story is not None:
            # Both text tabs, so either can still be read once Play Mode ends.
            for name in ("Live", "World"):
                if name != tab:
                    self._kept[name] = self._text_rows(story, name)
        if tab == "Levers":
            self._refresh_levers(story, force)
        else:
            rows = self._text_rows(story, tab)
            if story is not None:
                self._kept[tab] = rows
            if force or self._shown.get(tab) != rows:
                self._show_text(tab, rows)
        self.status.setText(self.message)

    def _text_rows(self, story, tab):
        if story is None:
            return [("text", "No active MiniWind storyteller.")]
        if tab == "World":
            rows = []
            for group, label, reason, _events in world_explanations(story):
                rows += [("heading", f"{group}: {label}"), ("text", reason)]
            return rows
        return rows_for(story)

    def _show_text(self, tab, rows):
        self._shown[tab] = rows
        browser = self.world if tab == "World" else self.live
        bar = browser.verticalScrollBar()
        at = bar.value()
        browser.setHtml(_html(rows))
        bar.setValue(at)

    def _refresh_levers(self, story, force):
        enabled = story is not None
        for button in (*self._state_buttons.values(), self.reset_button, self.pacing_button):
            button.setEnabled(enabled)
        if story is None:
            # Nothing to edit without a session; the last table stays visible.
            if self.form_area.widget() is not None:
                self.form_area.widget().setEnabled(False)
            return
        if self.form_area.widget() is not None:
            self.form_area.widget().setEnabled(True)
        if self.edit_state is None:
            self.edit_state = story.state
        for state, button in self._state_buttons.items():
            button.setChecked(state == self.edit_state)
        self.pacing_button.setText("Pacing on" if story.enabled else "Pristine ecology")
        if force or self._levers_for != (story, self.edit_state):
            self._build_form(story)
            return
        # Live values in, without fighting a box being edited.
        for heading, _label, path, value in self.lever_rows(story, self.edit_state):
            spin = self._spins.get(path)
            if spin is not None and not spin.hasFocus() and abs(spin.value() - float(value)) > 1e-9:
                spin.blockSignals(True)
                spin.setValue(float(value))
                spin.blockSignals(False)

    def _build_form(self, story):
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setLabelAlignment(Qt.AlignLeft)
        self._spins = {}
        for heading, label, path, value in self.lever_rows(story, self.edit_state):
            if heading:
                title = QLabel(heading)
                title.setObjectName("heading")
                form.addRow(title)
                continue
            low, high, step = _limits(path)
            spin = QDoubleSpinBox()
            spin.setDecimals(2 if step < 1 or low % 1 else 0)
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setValue(float(value))
            spin.setFixedWidth(120)
            spin.valueChanged.connect(lambda v, p=path: self.edit(p, v))
            spin.editingFinished.connect(self._save)
            self._spins[path] = spin
            name = QLabel(label)
            name.setStyleSheet("color: #96cde1;")
            form.addRow(name, spin)
        self.form_area.setWidget(form_widget)
        self._levers_for = (story, self.edit_state)

    # -- editing -------------------------------------------------------------
    def choose_state(self, state):
        self.edit_state = state
        self.refresh(force=True)

    def edit(self, path, value):
        """Lever *path* of the state being edited to *value*, live."""
        story = self._storyteller()
        if story is None:
            return
        story.edit_lever(self.edit_state, path, round(float(value), 4), persist=False)
        self.message = f"Editing {self.edit_state} {' / '.join(map(str, path))}"
        self.status.setText(self.message)

    def _save(self):
        story = self._storyteller()
        if story is not None:
            story.persist()
            self.message = "Edit saved with session."
            self.status.setText(self.message)

    def reset_state(self):
        story = self._storyteller()
        if story is not None:
            story.reset_edits(self.edit_state)
            self.message = f"{self.edit_state} edits reset."
            self.refresh(force=True)

    def toggle_pacing(self):
        story = self._storyteller()
        if story is not None:
            story.set_enabled(not story.enabled)
            self.refresh(force=True)

    def closeEvent(self, event):
        self._timer.stop()
        self._save()
        if self in _open:
            _open.remove(self)
        super().closeEvent(event)


def open_storyteller(view, parent=None):
    """Open one Studio per view, or bring the open one forward."""
    session = getattr(getattr(view, "logic_thread", None), "_miniwind", None)
    if getattr(session, "storyteller", None) is None:
        return None
    for win in list(_open):
        try:
            if win.view is view:
                win.show()
                win.raise_()
                win.activateWindow()
                win.refresh(force=True)
                return win
        except RuntimeError:            # deleted on close
            _open.remove(win)
    if not isinstance(parent, QWidget):
        try:
            parent = view.window() if hasattr(view, "window") else None
        except Exception:
            parent = None
    if not isinstance(parent, QWidget):
        parent = None
    win = StorytellerWindow(view, parent)
    _open.append(win)
    win.show()
    return win
