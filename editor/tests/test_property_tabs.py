"""
Layout rules for the MiniWind property tabs.

The editor's own I/O widget sets the house style for an editable list: a view
exactly as tall as its contents, its action buttons right beside it, everything
packed to the top. The MiniWind tabs did not follow it — an NPC with no items
showed a slab of empty grid with its Add button pushed below the fold, and Qt's
default table header is near-white text on white.

These tests pin the rules rather than the pixels, so the tabs can be
restyled without them going stale.

Qt-dependent; skips cleanly where PyQt5 is absent.

Run:  python -m pytest editor/tests -q
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PyQt5.QtCore")
QtGui = pytest.importorskip("PyQt5.QtGui")
QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

from game import editor_ui, sim_editor   # noqa: E402


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _Thing:
    def __init__(self, **props):
        self.pos = [0, 0, 0]
        self.properties = {"type": "npc", "name": "Mara",
                           "display_name": "Mara", "npc_role": "villager"}
        self.properties.update(props)


_ITEMS = [{"id": "iron_longsword", "name": "Iron Longsword", "qty": 1, "value": 40},
          {"id": "potion_heal", "name": "Potion of Healing", "qty": 3, "value": 25},
          {"id": "lockpick", "name": "Lockpick", "qty": 12, "value": 5}]

_SCHEDULE = [{"hour": 8, "state": "GOING_TO_WORK", "location": "work"},
             {"hour": 18, "state": "GOING_HOME", "location": "home"}]


def _tabs(**props):
    thing = _Thing(**props)
    return {
        "inventory": editor_ui.make_inventory_tab(thing),
        "dialogue": editor_ui.make_dialogue_tab(thing),
        "schedule": editor_ui.make_schedule_tab(thing),
        "ties": editor_ui.make_ties_tab(thing),
        "simulation": sim_editor.make_simulation_tab(thing),
    }


def _views(widget):
    """Every table/tree/list inside a tab."""
    return widget.findChildren(QtWidgets.QTableWidget) + \
        widget.findChildren(QtWidgets.QTreeWidget) + \
        widget.findChildren(QtWidgets.QListWidget)


# --- readable headers ------------------------------------------------------
def test_no_tab_leaves_a_default_white_column_header(app):
    """Qt's stock header is near-white, which is unreadable in this editor."""
    for name, tab in _tabs(inventory=list(_ITEMS), schedule=list(_SCHEDULE)).items():
        for view in _views(tab):
            if isinstance(view, QtWidgets.QListWidget):
                continue                       # no column header to style
            style = view.styleSheet()
            assert "QHeaderView::section" in style, \
                f"{name}: {view.objectName() or type(view).__name__} unstyled header"
            assert "background-color: #3A3A3A" in style, f"{name}: header not dark"


def test_the_shared_style_is_one_definition():
    """Every tab reads the same constant, so they cannot drift apart."""
    assert "QHeaderView::section" in editor_ui.TABLE_STYLE
    assert editor_ui.TABLE_STYLE in sim_editor.editor_ui.TABLE_STYLE


# --- action buttons reachable ---------------------------------------------
def _index_in_layout(layout, widget):
    """Position of *widget* (or the layout containing it) in *layout*."""
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item.widget() is widget:
            return i
        child = item.layout()
        if child is not None:
            for j in range(child.count()):
                if child.itemAt(j).widget() is widget:
                    return i
    return -1


@pytest.mark.parametrize("tab_name,button_text,view_attr", [
    ("inventory", "＋ Add Item…", "grid"),
    ("schedule", "Add Entry", "table"),
    ("dialogue", "Add Node", "tree"),
])
def test_the_add_button_comes_before_its_list(app, tab_name, button_text, view_attr):
    """An empty list must never push its own Add button below the fold."""
    tab = _tabs(inventory=list(_ITEMS), schedule=list(_SCHEDULE))[tab_name]
    button = next(b for b in tab.findChildren(QtWidgets.QPushButton)
                  if b.text() == button_text)
    view = getattr(tab, view_attr)
    layout = tab.layout()
    button_at = _index_in_layout(layout, button)
    view_at = _index_in_layout(layout, view)
    assert button_at >= 0 and view_at >= 0
    assert button_at < view_at, f"{tab_name}: actions are below the list"


def test_the_simulation_tab_puts_its_memory_actions_above_the_list(app):
    tab = _tabs()["simulation"]
    button = next(b for b in tab.findChildren(QtWidgets.QPushButton)
                  if "Tell it" in b.text())
    box = button.parent()
    layout = box.layout()
    assert _index_in_layout(layout, button) < _index_in_layout(layout, tab.knowledge)


# --- lists sized to their contents ----------------------------------------
def test_an_empty_list_is_a_header_not_a_slab(app):
    """The whole complaint: a huge empty box you had to scroll past."""
    empty = _tabs()
    row = empty["schedule"].table.fontMetrics().height() + 12
    assert empty["schedule"].table.height() <= row * 4
    assert empty["inventory"].grid.height() <= 120


def test_a_list_grows_as_it_is_filled(app):
    empty = _tabs()
    full = _tabs(inventory=list(_ITEMS), schedule=list(_SCHEDULE))
    assert full["schedule"].table.height() > empty["schedule"].table.height()
    assert full["inventory"].grid.height() > empty["inventory"].grid.height()


def test_growth_stops_at_the_cap_so_one_list_cannot_own_the_panel(app):
    tab = _tabs(schedule=[{"hour": h, "state": "IDLE", "location": "home"}
                          for h in range(24)])["schedule"]
    row = tab.table.fontMetrics().height() + 12
    assert tab.table.height() <= tab.table.horizontalHeader().height() + row * 13


# --- the inventory reads as one card per row ------------------------------
def test_each_item_gets_its_own_row(app):
    grid = _tabs(inventory=list(_ITEMS))["inventory"].grid
    assert grid.viewMode() == QtWidgets.QListView.ListMode
    assert grid.count() == len(_ITEMS)
    rects = [grid.visualItemRect(grid.item(i)) for i in range(grid.count())]
    tops = [r.top() for r in rects]
    assert tops == sorted(tops) and len(set(tops)) == len(rects), \
        "items share a row — this is a grid, not a list"


def test_item_names_are_shown_in_full(app):
    """A tiled grid had to elide them ("Lo…", "Iron…"), which is the one thing
    an item list has to get right."""
    grid = _tabs(inventory=list(_ITEMS))["inventory"].grid
    assert grid.textElideMode() == QtCore.Qt.ElideNone
    metrics = QtGui.QFontMetricsF(grid.font())
    longest = max(metrics.horizontalAdvance(s["name"]) for s in _ITEMS)
    assert grid.visualItemRect(grid.item(0)).width() > longest


def test_the_icons_keep_their_size(app):
    grid = _tabs(inventory=list(_ITEMS))["inventory"].grid
    assert grid.iconSize().width() == 56
    assert grid.visualItemRect(grid.item(0)).height() >= 56


# --- Ties and Patrol are separate sections --------------------------------
def test_ties_and_patrol_are_separate_collapsible_sections(app):
    """Two unrelated things share the tab; folding one away should not cost
    the other."""
    tab = _tabs()["ties"]
    assert tab.ties_section is not tab.patrol_section
    for section, table in ((tab.ties_section, tab.rel_table),
                           (tab.patrol_section, tab.pat_table)):
        assert hasattr(section, "toggle"), "not collapsible"
        assert section.toggle.isChecked(), "open by default"
        assert section.isAncestorOf(table)

    tab.ties_section.toggle.setChecked(False)
    assert not tab.rel_table.isVisibleTo(tab.ties_section)
    assert tab.patrol_section.toggle.isChecked(), "the other stays open"


def test_each_ties_section_keeps_its_own_actions(app):
    tab = _tabs()["ties"]
    for section, texts in ((tab.ties_section, {"Add Tie"}),
                           (tab.patrol_section, {"Add Waypoint", "Move Up"})):
        labels = {b.text() for b in section.findChildren(QtWidgets.QPushButton)}
        assert texts <= labels


# --- Appearance moved into the Properties tab -----------------------------
def test_appearance_is_a_collapsed_section_not_a_tab(app):
    """It is a handful of fields about this entity, not a workspace, so it
    belongs with the other properties and should cost no tab and no vertical
    space until somebody opens it."""
    from plugins.manager import get_manager
    import game

    game.install()                       # idempotent; registers the surfaces
    mgr = get_manager()

    tab_labels = [label for label, _f in mgr.property_tabs_for("npc")]
    assert "Appearance" not in tab_labels

    sections = {label: expanded
                for label, _f, expanded in mgr.property_sections_for("npc")}
    assert "Appearance" in sections
    assert sections["Appearance"] is False, "collapsed by default"
    assert "Appearance" in dict(
        (l, e) for l, _f, e in mgr.property_sections_for("creature"))


def test_a_section_only_builds_when_it_is_opened(app):
    """A collapsed section nobody looks at must cost nothing to show."""
    from editor.property_editor import CollapsibleSection
    from plugins.integration import _wire_lazy_section

    built = []

    def factory(thing):
        built.append(thing)
        return QtWidgets.QLabel("content")

    thing = _Thing()
    section = CollapsibleSection("Appearance", expanded=False)
    _wire_lazy_section(section, factory, thing, "Appearance")
    assert built == [], "nothing built while collapsed"

    section.toggle.setChecked(True)
    assert built == [thing], "built on first open"
    section.toggle.setChecked(False)
    section.toggle.setChecked(True)
    assert built == [thing], "and only once"


def test_a_section_that_starts_open_builds_immediately(app):
    from editor.property_editor import CollapsibleSection
    from plugins.integration import _wire_lazy_section

    built = []
    section = CollapsibleSection("Live", expanded=True)
    _wire_lazy_section(section, lambda t: built.append(t) or QtWidgets.QLabel(),
                       _Thing(), "Live")
    assert len(built) == 1


def test_a_failing_section_factory_cannot_break_the_panel(app):
    from editor.property_editor import CollapsibleSection
    from plugins.integration import _wire_lazy_section

    section = CollapsibleSection("Bad", expanded=False)
    _wire_lazy_section(section, lambda t: 1 / 0, _Thing(), "Bad")
    section.toggle.setChecked(True)      # must not raise
    assert section.toggle.isChecked()


# --- every panel is dark ---------------------------------------------------
def test_every_tab_carries_the_shared_panel_style(app):
    """The application theme covers QWidget, buttons and inputs but not item
    views, group boxes or checkbox indicators — which Qt then paints light."""
    tabs = _tabs(inventory=list(_ITEMS), schedule=list(_SCHEDULE))
    settings = _Thing(type="miniwindsettings")
    spawn = _Thing(type="creaturespawn")
    tabs["spells"] = editor_ui.make_spells_tab(_Thing())
    tabs["player_spells"] = editor_ui.make_player_spells_tab(settings)
    tabs["quests"] = editor_ui.make_quests_tab(settings)
    tabs["spawn"] = editor_ui.make_spawn_tab(spawn)
    tabs["appearance"] = editor_ui.make_appearance_tab(_Thing())

    for name, tab in tabs.items():
        assert tab is not None, name
        style = tab.styleSheet()
        for rule in ("QGroupBox", "QCheckBox::indicator", "QListWidget",
                     "QHeaderView::section"):
            assert rule in style, f"{name}: {rule} left to the platform palette"


def test_applying_the_dark_style_twice_does_not_stack_it(app):
    w = QtWidgets.QWidget()
    editor_ui.apply_dark(w)
    once = w.styleSheet()
    editor_ui.apply_dark(w)
    assert w.styleSheet() == once


def test_a_widgets_own_styling_still_wins(app):
    """A spell card sets its own colours; the panel style must not erase them."""
    w = QtWidgets.QWidget()
    w.setStyleSheet("QLabel { color: #ff0000; }")
    editor_ui.apply_dark(w)
    assert "#ff0000" in w.styleSheet()
    assert w.styleSheet().index("QGroupBox") < w.styleSheet().index("#ff0000")


# --- Game Settings has its own icon ---------------------------------------
def test_game_settings_does_not_borrow_the_keyvalue_store_icon():
    from game.entities import GameSettings
    path = GameSettings.pixmap_path
    assert "logic_keyvalue" not in path
    assert os.path.isfile(os.path.join(ROOT_DIR, path)), path


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
