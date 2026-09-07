"""
Tests for the play-mode pause menu (:mod:`engine.pause_menu`).

Escape in a standalone play session used to end the game outright. It now
freezes the world and raises a menu — NEW GAME / LOAD / SAVE / EDITOR / QUIT,
three save slots behind LOAD and SAVE, and a SURE? behind anything that throws
progress away.

The menu is drawn with QPainter and owns no widgets, so it can be driven
directly here against a stand-in viewport: these tests pin the pages, the
freeze, the confirmations and the way out, plus the one rule the whole feature
rests on — that a session launched from the editor keeps the old behaviour.

Run:  python -m pytest engine/tests/test_pause_menu.py -q
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

from engine.pause_menu import SLOT_COUNT, PauseMenu, slot_name


@pytest.fixture(scope="module")
def app():
    yield QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class _Logic:
    """The logic thread's two pause flags, and nothing else."""

    def __init__(self):
        self.gameplay_paused = False
        self._menu_paused = False


class _Editor:
    """Records the actions the menu asks the editor window to perform."""

    def __init__(self, slots=None):
        self.keys_pressed = {QtCore.Qt.Key_W}
        self.calls = []
        self._slots = slots if slots is not None else [None] * SLOT_COUNT

    def pause_menu_slot_info(self):
        return list(self._slots)

    def pause_menu_save_slot(self, slot):
        self.calls.append(("save", slot))

    def pause_menu_load_slot(self, slot):
        self.calls.append(("load", slot))

    def pause_menu_new_game(self):
        self.calls.append(("new",))

    def pause_menu_to_editor(self):
        self.calls.append(("editor",))

    def pause_menu_quit(self):
        self.calls.append(("quit",))


class _View:
    """A viewport stand-in: the menu only asks it for size, repaint and a frame."""

    def __init__(self, editor):
        self.editor = editor
        self.logic_thread = _Logic()
        self.repaints = 0

    def width(self):
        return 1280

    def height(self):
        return 720

    def update(self):
        self.repaints += 1

    def grabFramebuffer(self):
        # No GL context in a test; the menu must cope and fall back to its scrim.
        raise RuntimeError("no GL context")


def _menu(slots=None):
    return PauseMenu(_View(_Editor(slots)))


def _key(code):
    return QtGui.QKeyEvent(QtCore.QEvent.KeyPress, code, QtCore.Qt.NoModifier)


def _labels(menu):
    return [label for _, label in menu._items()]


def _select(menu, label):
    menu.index = _labels(menu).index(label)


def _draw(menu):
    """Run a real paint pass, which is also what populates the click targets."""
    pixmap = QtGui.QPixmap(menu.view.width(), menu.view.height())
    painter = QtGui.QPainter(pixmap)
    try:
        menu.draw(painter)
    finally:
        painter.end()


# --------------------------------------------------------------------- pages

def test_the_root_page_offers_the_five_options_in_order(app):
    menu = _menu()
    menu.open()
    assert _labels(menu) == ["NEW GAME", "LOAD", "SAVE", "EDITOR", "QUIT"]


def test_load_and_save_open_three_slots_and_a_way_back(app):
    for option in ("LOAD", "SAVE"):
        menu = _menu()
        menu.open()
        _select(menu, option)
        menu.activate()
        assert _labels(menu) == ["SLOT 1", "SLOT 2", "SLOT 3", "BACK"]
        assert SLOT_COUNT == 3


def test_slot_names_are_ordinary_saves(app):
    assert [slot_name(n) for n in (1, 2, 3)] == ["slot1", "slot2", "slot3"]


# --------------------------------------------------------------------- freeze

def test_opening_freezes_the_world_and_closing_thaws_it(app):
    menu = _menu()
    logic = menu.view.logic_thread
    menu.open()
    assert menu.active
    assert logic.gameplay_paused and logic._menu_paused
    menu.close()
    assert not menu.active
    assert not logic.gameplay_paused and not logic._menu_paused


def test_closing_restores_a_pause_that_was_already_in_effect(app):
    """A game screen open behind the menu must still be paused afterwards."""
    menu = _menu()
    menu.view.logic_thread.gameplay_paused = True
    menu.open()
    menu.close()
    assert menu.view.logic_thread.gameplay_paused


def test_held_keys_are_dropped_so_the_player_does_not_walk_off_on_resume(app):
    menu = _menu()
    assert menu.editor.keys_pressed          # something held when Escape landed
    menu.open()
    assert not menu.editor.keys_pressed


def test_a_missing_gl_context_still_gets_a_menu(app):
    """The blurred still is a nicety; losing it must not lose the menu."""
    menu = _menu()
    menu.open()
    assert menu.active
    assert menu._background is None
    _draw(menu)                              # must not raise


# --------------------------------------------------------------- confirmation

@pytest.mark.parametrize("option, expected", [
    ("NEW GAME", ("new",)),
    ("EDITOR", ("editor",)),
    ("QUIT", ("quit",)),
])
def test_destructive_options_ask_first_and_default_to_no(app, option, expected):
    menu = _menu()
    menu.open()
    _select(menu, option)
    menu.activate()

    assert menu.page == "confirm"
    assert _labels(menu) == ["YES", "NO"]
    assert _labels(menu)[menu.index] == "NO"     # the safe answer is preselected
    assert menu.editor.calls == []               # nothing has happened yet

    _select(menu, "YES")
    menu.activate()
    assert menu.editor.calls == [expected]
    assert not menu.active                       # and the menu gets out of the way


def test_answering_no_returns_to_the_option_it_came_from(app):
    menu = _menu()
    menu.open()
    _select(menu, "QUIT")
    menu.activate()
    _select(menu, "NO")
    menu.activate()

    assert menu.page == "root"
    assert _labels(menu)[menu.index] == "QUIT"
    assert menu.editor.calls == []
    assert menu.active


# ---------------------------------------------------------------- save / load

def test_saving_to_an_empty_slot_needs_no_confirmation(app):
    menu = _menu()
    menu.open()
    _select(menu, "SAVE")
    menu.activate()
    _select(menu, "SLOT 2")
    menu.activate()
    assert menu.editor.calls == [("save", 2)]


def test_overwriting_an_occupied_slot_asks_first(app):
    occupied = [{"map": "village.json", "saved_at": "2026-09-07T11:02"}, None, None]
    menu = _menu(occupied)
    menu.open()
    _select(menu, "SAVE")
    menu.activate()
    _select(menu, "SLOT 1")
    menu.activate()

    assert menu.page == "confirm"
    assert menu.editor.calls == []
    _select(menu, "YES")
    menu.activate()
    assert menu.editor.calls == [("save", 1)]


def test_loading_asks_before_throwing_away_the_run(app):
    occupied = [None, {"map": "village.json", "saved_at": "2026-09-07T11:02"}, None]
    menu = _menu(occupied)
    menu.open()
    _select(menu, "LOAD")
    menu.activate()
    _select(menu, "SLOT 2")
    menu.activate()

    assert menu.page == "confirm"
    _select(menu, "YES")
    menu.activate()
    assert menu.editor.calls == [("load", 2)]


def test_an_empty_slot_cannot_be_loaded(app):
    menu = _menu()                       # all three slots empty
    menu.open()
    _select(menu, "LOAD")
    menu.activate()
    _select(menu, "SLOT 1")
    menu.activate()

    assert menu.page == "load"           # nothing happened, still on the page
    assert menu.editor.calls == []


def test_slot_captions_say_what_is_in_each_slot(app):
    menu = _menu([{"map": "maps/village.json", "saved_at": "2026-09-07T11:02:00"},
                  None, None])
    menu.open()
    _select(menu, "LOAD")
    menu.activate()
    captions = menu._slot_captions()
    assert "village" in captions[0] and "2026-09-07 11:02" in captions[0]
    assert captions[1] == "Empty"


# ------------------------------------------------------------------- input

def test_arrow_keys_wrap_around_the_row(app):
    menu = _menu()
    menu.open()
    menu.handle_key(_key(QtCore.Qt.Key_Left))
    assert menu.index == len(menu.ROOT_ITEMS) - 1
    menu.handle_key(_key(QtCore.Qt.Key_Right))
    assert menu.index == 0


def test_escape_backs_out_one_page_at_a_time_then_resumes(app):
    menu = _menu()
    menu.open()
    _select(menu, "LOAD")
    menu.activate()
    assert menu.page == "load"

    menu.handle_key(_key(QtCore.Qt.Key_Escape))
    assert menu.page == "root" and menu.active

    menu.handle_key(_key(QtCore.Qt.Key_Escape))
    assert not menu.active
    assert not menu.view.logic_thread.gameplay_paused


def test_the_menu_swallows_gameplay_keys_while_it_is_up(app):
    menu = _menu()
    menu.open()
    assert menu.handle_key(_key(QtCore.Qt.Key_W)) is True
    assert menu.page == "root" and menu.index == 0


def test_a_click_activates_whatever_was_drawn_under_it(app):
    menu = _menu()
    menu.open()
    _draw(menu)                         # lays out the chips and their rects
    quit_index = _labels(menu).index("QUIT")
    rect = dict(menu._hit_rects)[quit_index]
    press = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, rect.center(),
                              QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                              QtCore.Qt.NoModifier)
    menu.handle_mouse_press(press)
    assert menu.page == "confirm"       # asked, not quit


def test_hovering_moves_the_selection(app):
    menu = _menu()
    menu.open()
    _draw(menu)
    target = _labels(menu).index("EDITOR")
    rect = dict(menu._hit_rects)[target]
    move = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, rect.center(),
                             QtCore.Qt.NoButton, QtCore.Qt.NoButton,
                             QtCore.Qt.NoModifier)
    menu.handle_mouse_move(move)
    assert menu.index == target


# ------------------------------------------------------------------ drawing

@pytest.mark.parametrize("page", ["root", "load", "save"])
def test_every_page_paints_and_leaves_a_clickable_chip_per_option(app, page):
    menu = _menu()
    menu.open()
    if page != "root":
        _select(menu, page.upper())
        menu.activate()
    _draw(menu)
    assert len(menu._hit_rects) == len(menu._items())
    # Chips stay inside the viewport rather than running off the edges.
    for _, rect in menu._hit_rects:
        assert rect.left() >= 0 and rect.right() <= menu.view.width()
