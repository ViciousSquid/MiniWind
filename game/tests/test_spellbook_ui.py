"""P opens a mouse-driven spellbook; every known spell can be readied."""

import configparser
from types import SimpleNamespace

import pytest

QtCore = pytest.importorskip("PyQt5.QtCore")
QtGui = pytest.importorskip("PyQt5.QtGui")
pytestmark = pytest.mark.qt

from engine.floating_windows import WindowManager
from engine.qt_game_view import _window_wants_cursor
from plugins.api import TickContext
from game import host, keybinds
from game.rpg import magic, equipment as eq
from game.runtime import MiniwindSession
from game.ui import hits, screens
from .fio_logic import FioLogic


class _Logic(FioLogic):
    def __init__(self):
        self.things = []
        self.player = SimpleNamespace(pos=[0.0, 0.0, 0.0], properties={})


@pytest.fixture
def session(qt_app, monkeypatch):
    for _action, _label, constant, default in keybinds.ACTIONS:
        monkeypatch.setattr(host, constant, default)
    s = MiniwindSession(_Logic(), cfg={})
    s.logic._miniwind = s
    s.needs_char_creation = False
    s.open_screen = None
    s.game.character.known_spells = ["flare", "heal_minor", "lightning"]
    s.game.character.active_spell = "flare"
    hits.clear()
    yield s
    hits.clear()


def _paint(session, width=700, height=470, dpr=1):
    image = QtGui.QImage(int((width + 80) * dpr), int((height + 100) * dpr),
                         QtGui.QImage.Format_ARGB32)
    image.setDevicePixelRatio(dpr)
    painter = QtGui.QPainter(image)
    hits.begin()
    try:
        screens.draw_in_rect(painter, session, 40, 50, width, height)
    finally:
        painter.end()
        hits.end()
    return hits.targets()


def _click(session, targets, label):
    rect = next(rect for rect, text in targets if text == label)
    point = rect.center()
    assert screens.handle_click(session, point.x(), point.y())
    assert hits.run_clicks(session) == 1


def test_p_opens_spellbook_and_cancels_aiming_without_blocking(session):
    game = host.MiniwindGame.__new__(host.MiniwindGame)
    session.spell_aiming = True
    ctx = TickContext(delta=.05, keys=frozenset({QtCore.Qt.Key_P}))
    game._handle_gameplay_input(session, game._just_pressed(ctx), ctx)
    assert keybinds.defaults()["spells"] == "p"
    assert session.open_screen == "spells"
    assert not session.spell_aiming
    assert not session._blocking
    game._handle_screen_input(session, {"p"}, ctx)
    assert session.open_screen is None


def test_b_still_allows_blocking_without_opening_spellbook(session):
    game = host.MiniwindGame.__new__(host.MiniwindGame)
    ctx = TickContext(delta=.05, keys=frozenset({QtCore.Qt.Key_B}))
    game._handle_gameplay_input(session, game._just_pressed(ctx), ctx)
    assert keybinds.defaults()["block"] == "b"
    assert session._blocking
    assert session.open_screen is None


def test_clicking_a_known_spell_readies_it_without_casting(session):
    session.open_screen = "spells"
    targets = _paint(session)
    spell_ids = {label.removeprefix("spell:") for _, label in targets
                 if label.startswith("spell:")}
    assert spell_ids == set(session.game.character.known_spells)
    magicka = session.game.character.magicka
    _click(session, targets, "spell:lightning")
    assert session.game.character.active_spell == "lightning"
    assert not eq.spell_equipped(session.game.character, "lightning")
    assert session.game.character.magicka == magicka
    assert session.notifications[-1]["text"] == "Selected Lightning Bolt"
    _click(session, _paint(session), "Close")
    assert session.open_screen is None
    assert session.game.character.active_spell == "lightning"


@pytest.mark.parametrize("width,height,dpr", [(640, 360, 1), (700, 470, 2), (1000, 640, 1)])
def test_every_known_spell_is_reachable_with_the_mouse(session, width, height, dpr):
    session.open_screen = "spells"
    session.game.character.known_spells = list(magic.SPELLS)
    seen = set()
    pages = 0
    while True:
        targets = _paint(session, width, height, dpr)
        assert all(QtCore.QRect(40, 50, width, height).contains(rect)
                   for rect, _ in targets)
        visible = [label.removeprefix("spell:") for _, label in targets
                   if label.startswith("spell:")]
        for sid in visible:
            _click(session, targets, f"spell:{sid}")
            assert session.game.character.active_spell == sid
        seen.update(visible)
        pages += 1
        assert pages <= len(magic.SPELLS)
        if not any(label == "Next" for _, label in targets):
            break
        _click(session, targets, "Next")
    assert seen == set(session.game.character.known_spells)
    assert pages > 1
    assert any(label == "Previous" for _, label in targets)


def test_empty_spellbook_can_be_closed_with_mouse_or_escape(session):
    session.game.character.known_spells = []
    session.game.character.active_spell = None
    session.open_screen = "spells"
    targets = _paint(session)
    assert [label for _, label in targets] == ["Close"]
    _click(session, targets, "Close")
    assert session.game.character.active_spell is None
    session.open_screen = "spells"
    screens.handle_key(session, "escape")
    assert session.open_screen is None


def test_keyboard_selection_survives_unknown_spell_ids_and_stale_selection(session):
    session.open_screen = "spells"
    session.game.character.known_spells.insert(1, "missing_spell")
    session.sel = {"spells": {"row": 999}}
    screens.handle_key(session, "enter")
    assert session.game.character.active_spell == "lightning"
    screens.handle_key(session, "down")
    screens.handle_key(session, "enter")
    assert session.game.character.active_spell == "flare"


def test_rebound_spellbook_shortcut_opens_and_closes_the_screen(session):
    config = configparser.ConfigParser()
    keybinds.bind(config, "spells", "z")
    game = host.MiniwindGame.__new__(host.MiniwindGame)
    ctx = TickContext(delta=.05, keys=frozenset({QtCore.Qt.Key_Z}))
    game._handle_gameplay_input(session, game._just_pressed(ctx), ctx)
    assert session.open_screen == "spells"
    screens.handle_key(session, "z")
    assert session.open_screen is None


def test_hosted_spellbook_releases_cursor_and_routes_mouse_selection(session):
    session.open_screen = "spells"
    manager = WindowManager()
    view = SimpleNamespace(window_manager=manager, floating_windows=manager, play_mode=True)
    game = host.MiniwindGame.__new__(host.MiniwindGame)
    assert game._sync_overlay_windows(session, view, 1280, 720)
    win = session._overlay_win
    assert _window_wants_cursor(view)
    image = QtGui.QImage(1280, 720, QtGui.QImage.Format_ARGB32)
    painter = QtGui.QPainter(image)
    hits.begin()
    hits.end()  # Floating windows draw after the overlay publishes its targets.
    try:
        win.draw(painter)
    finally:
        painter.end()
    rect = next(rect for rect, label in hits.targets() if label == "spell:heal_minor")
    assert win.handle_body_click(rect.center().x(), rect.center().y())
    hits.run_clicks(session)
    assert session.game.character.active_spell == "heal_minor"
    win.on_close()
    hits.run_clicks(session)  # Statistics queues UI changes for the game tick.
    game._sync_overlay_windows(session, view, 1280, 720)
    assert not _window_wants_cursor(view)
