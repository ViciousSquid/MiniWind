"""The top tabs and shortcuts share one Statistics window, including Map."""

from types import SimpleNamespace

import numpy as np
import pytest
from PyQt5 import QtCore, QtGui

from engine.floating_windows import WindowManager
from engine.qt_game_view import _window_wants_cursor
from game import host, keybinds
from game.runtime import MiniwindSession
from game.rpg import equipment as eq, items
from game.ui import drag, hits, screens, worldmap
from game.ui.pack_window import TABS
from .test_menu_clicks import _Logic, _Press

pytestmark = pytest.mark.qt


@pytest.fixture
def ui(qt_app, monkeypatch):
    for _action, _label, constant, default in keybinds.ACTIONS:
        monkeypatch.setattr(host, constant, default)
    world = worldmap.WorldMap()
    world.bounds = ((-5000., 5000.), (-5000., 5000.))
    world.rgb = np.full((64, 64, 3), 90, dtype=np.uint8)
    monkeypatch.setattr(worldmap, "WORLD", world)
    session = MiniwindSession(_Logic(), cfg={})
    session.needs_char_creation = False
    session.open_screen = "inventory"
    session.game.character.class_id = "mage"
    session.game.character.known_spells = ["flare", "lightning"]
    game = host.MiniwindGame.__new__(host.MiniwindGame)
    manager = WindowManager()
    view = SimpleNamespace(window_manager=manager, floating_windows=manager,
                           play_mode=True, update=lambda: None)
    hits.clear()
    drag.reset()
    game._sync_overlay_windows(session, view, 1280, 800)
    yield game, session, view, session._overlay_win
    hits.clear()
    drag.reset()


def _paint(window):
    image = QtGui.QImage(1400, 1000, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.black)
    painter = QtGui.QPainter(image)
    hits.begin()
    hits.end()  # floating windows paint after the overlay publishes its targets
    try:
        window.draw(painter)
    finally:
        painter.end()
    return image


def _sync(ui):
    game, session, view, window = ui
    game._sync_overlay_windows(session, view, 1280, 800)
    assert session._overlay_win is window
    assert view.window_manager.windows == [window]
    _paint(window)


def _tab(ui, screen):
    _game, session, view, window = ui
    _paint(window)
    index = [key for _label, key in TABS].index(screen)
    tab_width = (window.width - 20 - 90 - 16) // len(TABS)
    point = QtCore.QPoint(window.window_rect.x() + 10 + index * tab_width + 20,
                         window.window_rect.y() + window.HEADER_H + 24)
    assert window.handle_mouse_press(_Press(point))
    hits.run_clicks(session)
    assert session.open_screen == screen
    _sync(ui)


def test_top_tabs_keep_one_window_and_preserve_position_and_selection(ui):
    _game, session, view, window = ui
    window.window_rect.moveTo(73, 31)
    window.selected = "iron_shortsword"
    for screen in ("skills", "fortune", "alignment", "character", "journal",
                   "spells", "map", "inventory"):
        _tab(ui, screen)
        assert window.screen == screen
        assert window.title == "Statistics"
        assert window.key == "screen:statistics"
        assert _window_wants_cursor(view)
        assert window.window_rect.topLeft() == QtCore.QPoint(73, 31)
        assert window.selected == "iron_shortsword"
    assert session.map_request is None


def test_shortcuts_select_tabs_in_the_same_window_and_escape_closes(ui):
    game, session, view, window = ui
    for key, screen in (("c", "character"), ("i", "inventory"),
                        ("j", "journal"), ("p", "spells"), ("m", "map")):
        game._handle_screen_input(session, {key}, None)
        assert session.open_screen == screen
        _sync(ui)
    game._handle_screen_input(session, {"escape"}, None)
    game._sync_overlay_windows(session, view, 1280, 800)
    assert session.open_screen is None
    assert view.window_manager.windows == []
    assert not _window_wants_cursor(view)
    assert not window.active
    assert drag.target_at(100, 200) is None


def test_rebound_inventory_and_character_shortcuts_select_tabs(ui, monkeypatch):
    game, session, _view, _window = ui
    monkeypatch.setattr(host, "K_INVENTORY", "o")
    monkeypatch.setattr(host, "K_CHARACTER", "u")
    game._handle_screen_input(session, {"u"}, None)
    assert session.open_screen == "character"
    _sync(ui)
    game._handle_screen_input(session, {"o"}, None)
    assert session.open_screen == "inventory"
    _sync(ui)


def test_spell_rows_are_clickable_inside_statistics(ui):
    _game, session, _view, window = ui
    _tab(ui, "spells")
    rect = next(r for r, label in hits.targets() if label == "spell:lightning")
    assert window.handle_mouse_press(_Press(rect.center()))
    assert hits.run_clicks(session) == 1
    assert session.game.character.active_spell == "lightning"


def test_spell_upgrades_click_and_the_hands_are_shown_not_dropped_on(ui):
    _game, session, _view, window = ui
    c = session.game.character
    c.xp = c.spell_upgrade_cost("flare")
    _tab(ui, "spells")
    upgrade = next(rect for rect, label in hits.targets()
                   if label.startswith("Raise to level 2"))
    assert not [target for _rect, target in window._targets if target[0] == "hand"]
    assert not any(label.startswith("Equip") for _rect, label in hits.targets())
    assert window.handle_mouse_press(_Press(upgrade.center()))
    assert hits.run_clicks(session) == 1
    assert c.spell_level("flare") == 2
    assert c.xp == 0
    assert not c.hand_spells


def test_spells_drag_from_the_book_to_the_shortcut_bar_or_take_a_number_key(ui):
    game, session, _view, window = ui
    c = session.game.character
    _tab(ui, "spells")
    assert game._strip_wanted(session)            # the bar stays up over the book
    bar = type("Bar", (), {"active": True})()      # the strip's drop zones
    slot = QtCore.QRect(500, 900, 50, 50)          # below the window
    _paint(window)
    drag.set_zones(bar, [(slot, ("strip", 3))])
    start = next(rect.center() for rect, src in window._cells
                 if src == ("spell", None, "lightning"))
    end = slot.center()
    assert window.handle_mouse_press(_Press(start))
    motion = SimpleNamespace(pos=lambda: end, x=lambda: end.x(), y=lambda: end.y(),
                             buttons=lambda: QtCore.Qt.LeftButton)
    assert window.handle_mouse_move(motion, 1280, 800)
    assert window.handle_mouse_release(_Press(end))
    hits.run_clicks(session)
    assert session.strip_slots()[3]["spell"] == "lightning"
    assert not c.hand_spells                       # on the bar, not in a hand
    screens.handle_key(session, "7")               # the selected spell, by key
    selected = screens._spellbook_spells(session)[
        screens._sel(session)["spells"]["row"]].id
    assert session.strip_slots()[6]["spell"] == selected


def test_map_draws_terrain_and_supports_pan_zoom_and_recentering(ui):
    game, session, _view, window = ui
    window.window_rect.moveTo(73, 31)
    _tab(ui, "map")
    page = window.map
    image = _paint(window)
    point = QtCore.QPointF(page.to_screen(page._rect, 2000., 2000.).toPoint())
    assert image.pixelColor(point.toPoint()).red() == 90
    assert window._full_rect().contains(page._rect.toRect())
    before = page.to_world(page._rect, point)
    wheel = SimpleNamespace(pos=lambda: point.toPoint(),
                            angleDelta=lambda: QtCore.QPoint(0, 120))
    span = page.span
    window.handle_wheel(wheel)
    assert page.span < span
    assert page.to_world(page._rect, point) == pytest.approx(before)
    centre = page.centre
    window.handle_mouse_press(_Press(point.toPoint()))
    assert window.mouse_captured
    move = SimpleNamespace(pos=lambda: (point + QtCore.QPointF(40, 0)).toPoint(),
                           buttons=lambda: QtCore.Qt.LeftButton)
    window.handle_mouse_move(move, 1280, 800)
    assert page.centre[0] < centre[0]
    window.handle_mouse_release(move)
    assert not window.mouse_captured
    game._handle_screen_input(session, {"space"}, None)
    _paint(window)
    assert page.centre == (0., 0.)
    game._handle_screen_input(session, {"m"}, None)
    assert session.open_screen is None


def test_quest_map_request_focuses_the_same_statistics_window(ui):
    game, session, view, window = ui
    session.map_request = (30., 40., "The Lost Ring")
    game._serve_map_request(session, view)
    _sync(ui)
    assert window.screen == "map"
    assert window.map.centre == (30., 40.)
    assert window.map.focus == (30., 40., "The Lost Ring")
