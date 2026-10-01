"""
Tests for the play-mode pause menu (:mod:`game.ui.pause_menu`).

Escape in play freezes the world and raises a menu, one row across the
screen: RESUME / GAME (NEW, LOAD, SAVE) / OPTIONS / EDITOR / QUIT, three
save slots behind LOAD and SAVE, and a SURE? behind anything that throws
progress away.

The menu is drawn with QPainter and owns no widgets, so it can be driven
directly here against a stand-in viewport: these tests pin the pages, the
freeze, the confirmations, the options and the way out.

Run:  python -m pytest game/tests/test_pause_menu.py -q
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

from ..ui import pause_menu
from ..ui.pause_menu import SLOT_COUNT, PauseMenu, slot_name


@pytest.fixture(scope="module")
def app(qt_app):
    # The session-wide QApplication (root conftest). A module-local one would be
    # destroyed with the module and abort the next Qt test that builds a widget.
    yield qt_app


class _Logic:
    """The logic thread's per-owner world pause (LogicThread.set_world_paused)."""

    def __init__(self):
        self.owners = set()

    def set_world_paused(self, owner, paused=True):
        (self.owners.add if paused else self.owners.discard)(owner)

    @property
    def world_paused(self):
        return bool(self.owners)


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

    volume = 0.5
    applied = 0

    def pause_menu_music_volume(self):
        return self.volume

    def pause_menu_set_music_volume(self, volume):
        self.volume = volume
        self.calls.append(("volume", round(volume, 2)))

    def pause_menu_display_settings(self):
        if not hasattr(self, "_display"):
            import configparser
            from ..ui.launcher import DisplaySettings
            self.saves = 0

            def _save():
                self.saves += 1
            self._display = DisplaySettings(config=configparser.ConfigParser(),
                                            save=_save)
        return self._display

    def pause_menu_apply_display(self):
        self.applied += 1


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


def _click(pos):
    return QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, pos,
                             QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                             QtCore.Qt.NoModifier)


def _labels(menu):
    return [label for _, label in menu._items()]


def _select(menu, label):
    menu.index = _labels(menu).index(label)


_GAME_LABELS = [label for _, label in PauseMenu.GAME_ITEMS]


def _choose(menu, label):
    """Choose *label*: from the GAME dropdown (by keyboard) or the row."""
    if menu.page == "root" and label in _GAME_LABELS:
        _select(menu, "GAME")
        menu.activate()                          # opens the dropdown
        assert menu.expanded
        for _ in range(_GAME_LABELS.index(label)):
            menu.handle_key(_key(QtCore.Qt.Key_Down))
        menu.handle_key(_key(QtCore.Qt.Key_Return))
    else:
        _select(menu, label)
        menu.activate()


def _draw(menu):
    """Run a real paint pass, which is also what populates the click targets."""
    pixmap = QtGui.QPixmap(menu.view.width(), menu.view.height())
    painter = QtGui.QPainter(pixmap)
    try:
        menu.draw(painter)
    finally:
        painter.end()


# --------------------------------------------------------------------- pages

def test_the_root_page_offers_its_options_in_order(app):
    menu = _menu()
    menu.open()
    assert _labels(menu) == ["RESUME", "MAP", "GAME", "OPTIONS", "EDITOR", "QUIT"]


def test_new_load_and_save_live_in_the_game_dropdown(app):
    menu = _menu()
    menu.open()
    assert not menu.expanded
    assert _GAME_LABELS == ["NEW GAME", "LOAD GAME", "SAVE GAME"]
    _select(menu, "GAME")
    menu.handle_key(_key(QtCore.Qt.Key_Down))    # Down on GAME opens it
    assert menu.expanded and menu.sub_index == 0
    menu.handle_key(_key(QtCore.Qt.Key_Up))      # and wraps inside it
    assert menu.sub_index == 2
    menu.handle_key(_key(QtCore.Qt.Key_Escape))  # Escape folds it first
    assert not menu.expanded and menu.active


def test_the_dropdown_opens_and_folds_with_clicks(app):
    menu = _menu()
    menu.open()
    _draw(menu)
    header = dict(menu._hit_rects)[_labels(menu).index("GAME")]
    menu.handle_mouse_press(_click(header.center()))
    assert menu.expanded
    _draw(menu)
    assert len(menu._drop_rects) == 3
    # Every entry hangs below the ribbon, under its header.
    for _, rect in menu._drop_rects:
        assert rect.top() >= header.bottom()
    menu.handle_mouse_press(_click(header.center()))
    assert not menu.expanded


def test_clicking_a_dropdown_entry_chooses_it(app):
    menu = _menu()
    menu.open()
    menu.toggle_dropdown(True)
    _draw(menu)
    save = dict(menu._drop_rects)[_GAME_LABELS.index("SAVE GAME")]
    move = QtGui.QMouseEvent(QtCore.QEvent.MouseMove, save.center(),
                             QtCore.Qt.NoButton, QtCore.Qt.NoButton,
                             QtCore.Qt.NoModifier)
    menu.handle_mouse_move(move)
    assert menu.sub_index == _GAME_LABELS.index("SAVE GAME")
    menu.handle_mouse_press(_click(save.center()))
    assert menu.page == "save"


def test_moving_off_game_folds_the_dropdown(app):
    menu = _menu()
    menu.open()
    menu.toggle_dropdown(True)
    menu.handle_key(_key(QtCore.Qt.Key_Right))
    assert not menu.expanded
    assert _labels(menu)[menu.index] == "OPTIONS"


def test_the_arrow_points_down_folded_and_up_open(app, monkeypatch):
    menu = _menu()
    menu.open()
    calls = []
    monkeypatch.setattr(PauseMenu, "_draw_arrow", staticmethod(
        lambda painter, cx, cy, pt, up, colour: calls.append(up)))
    _draw(menu)
    menu.toggle_dropdown(True)
    _draw(menu)
    assert calls == [False, True]


def test_resume_closes_the_menu(app):
    menu = _menu()
    menu.open()
    _select(menu, "RESUME")
    menu.activate()
    assert not menu.active
    assert not menu.view.logic_thread.world_paused


def _options(menu):
    menu.open()
    _select(menu, "OPTIONS")
    menu.activate()
    assert menu.page == "options"
    return menu.options


def _row(page, key):
    page.index = [r[0] for r in page.rows()].index(key)


def test_options_show_the_launchers_display_settings_and_the_music_volume(app):
    page = _options(_menu())
    rows = {key: (label, value) for key, label, value, _on in page.rows()}
    assert set(rows) == {"mode", "res", "vsync", "hidpi", "volume", "back"}
    assert rows["mode"][1] == "Fullscreen"         # the launcher's default
    assert rows["volume"][1] == "50%"
    _draw(page.menu)                                # paints without error


def test_the_window_mode_cycles_through_the_launchers_modes_and_applies(app):
    menu = _menu()
    page = _options(menu)
    _row(page, "mode")
    menu.handle_key(_key(QtCore.Qt.Key_Right))
    assert page.settings.mode == "Borderless"
    assert menu.editor.applied == 1 and menu.editor.saves == 1
    menu.handle_key(_key(QtCore.Qt.Key_Right))
    assert page.settings.mode == "Windowed"


def test_the_resolution_is_only_for_windowed_mode(app):
    menu = _menu()
    page = _options(menu)
    _row(page, "res")
    before = page.settings.resolution
    menu.handle_key(_key(QtCore.Qt.Key_Right))     # Fullscreen: no change
    assert page.settings.resolution == before
    page.settings.save("Windowed", *before, True)
    menu.handle_key(_key(QtCore.Qt.Key_Right))
    assert page.settings.resolution != before


def test_vsync_and_high_dpi_toggle_and_say_they_wait_for_a_relaunch(app):
    menu = _menu()
    page = _options(menu)
    _row(page, "vsync")
    on = page.settings.vsync
    menu.handle_key(_key(QtCore.Qt.Key_Return))
    assert page.settings.vsync is (not on)
    assert "next launch" in page._note("vsync")


def test_music_volume_steps_and_zero_is_off(app):
    menu = _menu()
    page = _options(menu)
    _row(page, "volume")
    menu.handle_key(_key(QtCore.Qt.Key_Right))
    assert menu.editor.volume == pytest.approx(0.55)
    for _ in range(20):
        menu.handle_key(_key(QtCore.Qt.Key_Left))
    assert menu.editor.volume == 0.0
    assert dict((k, v) for k, _l, v, _o in page.rows())["volume"] == "OFF"


def test_the_volume_slider_follows_a_click_and_a_drag(app):
    menu = _menu()
    page = _options(menu)
    _draw(menu)
    track = page._slider
    press = QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress,
                              QtCore.QPoint(int(track.left() + track.width() * 0.8),
                                            int(track.center().y())),
                              QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                              QtCore.Qt.NoModifier)
    menu.handle_mouse_press(press)
    assert menu.editor.volume == pytest.approx(0.8)
    drag = QtGui.QMouseEvent(QtCore.QEvent.MouseMove,
                             QtCore.QPoint(int(track.left() - 40), int(track.center().y())),
                             QtCore.Qt.NoButton, QtCore.Qt.LeftButton,
                             QtCore.Qt.NoModifier)
    menu.handle_mouse_move(drag)
    assert menu.editor.volume == 0.0                # dragged off the left: off
    menu.handle_mouse_release()


def test_escape_leaves_the_options_for_the_root_row(app):
    menu = _menu()
    _options(menu)
    menu.handle_key(_key(QtCore.Qt.Key_Escape))
    assert menu.page == "root" and _labels(menu)[menu.index] == "OPTIONS"


def test_actions_can_come_from_the_game_rather_than_the_window(app):
    actions = _Editor()
    view = _View(_Editor())
    menu = PauseMenu(view, actions)
    menu.open()
    _choose(menu, "SAVE GAME")
    _select(menu, "SLOT 1")
    menu.activate()
    assert actions.calls == [("save", 1)]
    assert view.editor.calls == []


def test_closing_hands_the_cursor_back_to_the_view(app):
    menu = _menu()
    closed = []
    menu.view.play_menu_closed = lambda: closed.append(True)
    menu.open()
    menu.close()
    assert closed == [True]


def test_load_and_save_open_three_slots_and_a_way_back(app):
    for option in ("LOAD GAME", "SAVE GAME"):
        menu = _menu()
        menu.open()
        _choose(menu, option)
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
    assert logic.owners == {pause_menu.PAUSE_OWNER}
    menu.close()
    assert not menu.active
    assert not logic.world_paused


def test_closing_restores_a_pause_that_was_already_in_effect(app):
    """A game screen open behind the menu must still be paused afterwards."""
    menu = _menu()
    menu.view.logic_thread.set_world_paused("game.screen", True)
    menu.open()
    menu.close()
    assert menu.view.logic_thread.owners == {"game.screen"}


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
    _choose(menu, option)

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
    _choose(menu, "SAVE GAME")
    _select(menu, "SLOT 2")
    menu.activate()
    assert menu.editor.calls == [("save", 2)]


def test_overwriting_an_occupied_slot_asks_first(app):
    occupied = [{"map": "village.json", "saved_at": "2026-09-07T11:02"}, None, None]
    menu = _menu(occupied)
    menu.open()
    _choose(menu, "SAVE GAME")
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
    _choose(menu, "LOAD GAME")
    _select(menu, "SLOT 2")
    menu.activate()

    assert menu.page == "confirm"
    _select(menu, "YES")
    menu.activate()
    assert menu.editor.calls == [("load", 2)]


def test_an_empty_slot_cannot_be_loaded(app):
    menu = _menu()                       # all three slots empty
    menu.open()
    _choose(menu, "LOAD GAME")
    _select(menu, "SLOT 1")
    menu.activate()

    assert menu.page == "load"           # nothing happened, still on the page
    assert menu.editor.calls == []


def test_slot_captions_say_what_is_in_each_slot(app):
    menu = _menu([{"map": "maps/village.json", "saved_at": "2026-09-07T11:02:00"},
                  None, None])
    menu.open()
    _choose(menu, "LOAD GAME")
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
    _choose(menu, "LOAD GAME")
    assert menu.page == "load"

    # Back to the GAME dropdown it was chosen from, still on LOAD GAME...
    menu.handle_key(_key(QtCore.Qt.Key_Escape))
    assert menu.page == "root" and menu.active and menu.expanded
    assert _GAME_LABELS[menu.sub_index] == "LOAD GAME"

    # ...then the dropdown folds, then the menu closes.
    menu.handle_key(_key(QtCore.Qt.Key_Escape))
    assert menu.active and not menu.expanded
    menu.handle_key(_key(QtCore.Qt.Key_Escape))
    assert not menu.active
    assert not menu.view.logic_thread.world_paused


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
        _choose(menu, page.upper() + " GAME")
    _draw(menu)
    assert len(menu._hit_rects) == len(menu._items())
    # Chips stay inside the viewport rather than running off the edges.
    for _, rect in menu._hit_rects:
        assert rect.left() >= 0 and rect.right() <= menu.view.width()
