"""
The inspector's Properties-pane half.

An ``inspect`` pick opens the floating mental-state popup *and* brings the
picked actor's Simulation tab to the front, which is where the rest of its data
already lives. Plenty of inspectable things have no such tab — a plain engine
monster, an actor from another game, a plugin whose tabs failed to build — so
the rule under test is that a missing tab is an ordinary outcome: the panel
still shows what the thing does have, and nothing raises.

Qt-dependent; skips cleanly where PyQt5 is absent.

Run:  python -m pytest editor/tests -q
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from conftest import install_gl_stubs          # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt5.QtWidgets")


install_gl_stubs()
try:
    from editor.main_window import MainWindow
except Exception as exc:                       # pragma: no cover - env-specific
    pytest.skip(f"editor.main_window is not importable here ({exc})",
                allow_module_level=True)


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _Thing:
    def __init__(self, **props):
        self.pos = [0, 0, 0]
        self.properties = {"type": "npc", "name": "Elowen"}
        self.properties.update(props)


class _Window(QtWidgets.QMainWindow):
    """Enough of MainWindow to run the real method against real tab widgets."""

    show_simulation_tab_for = MainWindow.show_simulation_tab_for
    _display_name_of = staticmethod(MainWindow._display_name_of)
    INSPECT_TAB_LABEL = MainWindow.INSPECT_TAB_LABEL

    def __init__(self, tab_labels):
        super().__init__()
        self.selected = "untouched"
        self.toasts = []

        self.property_editor = QtWidgets.QWidget(self)
        self.property_editor.tab_widget = QtWidgets.QTabWidget(self.property_editor)
        for label in tab_labels:
            self.property_editor.tab_widget.addTab(QtWidgets.QWidget(), label)

        self.properties_tab_widget = QtWidgets.QTabWidget(self)
        self.properties_tab_widget.addTab(QtWidgets.QWidget(), "Debug Console")
        self.properties_tab_widget.addTab(self.property_editor, "Properties")
        self.properties_tab_widget.setCurrentIndex(0)

        self.properties_dock = QtWidgets.QDockWidget("Properties", self)
        self.properties_dock.setWidget(self.properties_tab_widget)
        self.properties_dock.setVisible(False)

    def set_selected_object(self, obj):
        self.selected = obj

    def show_toast(self, message, is_error=False, duration=None):
        self.toasts.append(message)


def test_an_inspected_actor_lands_on_its_simulation_tab(app):
    win = _Window(["Properties", "Inventory", "Simulation", "Schedule"])
    thing = _Thing()

    assert win.show_simulation_tab_for(thing) is True
    assert win.selected is thing
    # isHidden(), not isVisible(): the stand-in window is never shown.
    assert not win.properties_dock.isHidden()       # play mode had hidden it
    inner = win.property_editor.tab_widget
    assert inner.tabText(inner.currentIndex()) == "Simulation"
    # …and the dock's own tabs moved off the Debug Console to the Properties pane.
    outer = win.properties_tab_widget
    assert outer.widget(outer.currentIndex()) is win.property_editor


def test_a_thing_without_a_simulation_tab_does_not_crash(app):
    """The reported worry: not everything inspectable has one."""
    win = _Window(["Properties", "Advanced"])
    thing = _Thing(type="monster", name="Wolf")

    assert win.show_simulation_tab_for(thing) is False
    assert win.selected is thing                    # still selected and shown
    assert not win.properties_dock.isHidden()
    assert win.toasts and "Wolf" in win.toasts[0]


def test_a_property_editor_with_no_tabs_at_all_is_survivable(app):
    win = _Window([])
    win.property_editor.tab_widget = None
    assert win.show_simulation_tab_for(_Thing()) is False


def test_a_broken_panel_is_reported_not_raised(app):
    win = _Window(["Simulation"])
    win.property_editor = None                      # as bad as it gets
    assert win.show_simulation_tab_for(_Thing()) is False


def test_the_tab_is_found_whatever_case_or_padding_it_carries(app):
    win = _Window(["Properties", "  simulation "])
    assert win.show_simulation_tab_for(_Thing()) is True


def test_the_toast_names_whatever_the_thing_is_called(app):
    win = _Window(["Properties"])
    win.show_simulation_tab_for(_Thing(name="", display_name="Old Bram"))
    assert "Old Bram" in win.toasts[0]

    win.toasts.clear()
    nameless = _Thing()
    nameless.properties = None
    win.show_simulation_tab_for(nameless)
    assert "this object" in win.toasts[0]
