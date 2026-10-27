"""Cursor-release policy for the always-visible quickbar and character sheet."""

import types

import pytest

pytest.importorskip("PyQt5", reason="QtGameView requires PyQt5")

pytestmark = pytest.mark.qt

from engine.qt_game_view import _window_wants_cursor
from game.ui import hits


class _Window:
    def __init__(self, key, *, active=True, wants_cursor=True):
        self.key = key
        self.active = active
        self.wants_cursor = wants_cursor


class _Manager:
    def __init__(self, *windows):
        self.windows = list(windows)


class _View:
    play_mode = True
    console_overlay_active = False
    _actor_pick = None
    pause_menu = None
    play_menu = None

    def __init__(self, *windows):
        self.floating_windows = _Manager(*windows)


def test_inventory_strip_alone_keeps_mouse_look_captured():
    assert not _window_wants_cursor(_View(_Window("strip")))


@pytest.mark.parametrize("key", [
    "screen:statistics", "screen:character", "screen:spells", "screen:trade", "debug:tools", "debug:pathfinding",
])
def test_interactive_windows_release_cursor(key):
    assert _window_wants_cursor(_View(_Window(key)))


@pytest.mark.parametrize("key", [
    "screen:container",
    "screen:book",
    "dialogue",
    "sysmon",
])
def test_other_game_windows_do_not_release_cursor(key):
    assert not _window_wants_cursor(_View(_Window(key)))


def test_character_sheet_does_not_release_cursor_when_inactive():
    assert not _window_wants_cursor(_View(_Window("screen:character", active=False)))


def test_non_play_mode_never_releases_cursor_for_game_windows():
    view = _View(_Window("screen:character"))
    view.play_mode = False
    assert not _window_wants_cursor(view)


def test_console_suppresses_floating_window_cursor_claims():
    view = _View(_Window("screen:character"))
    view.console_overlay_active = True
    assert not _window_wants_cursor(view)


def test_game_pointer_is_requested_for_clickable_game_screens(monkeypatch):
    monkeypatch.setattr(hits, "has_targets", lambda: True)

    def pointer_for(*, screen=None, dialogue=None, needs_creation=False):
        session = types.SimpleNamespace(
            game=types.SimpleNamespace(
                character=types.SimpleNamespace(is_dead=False)
            ),
            open_screen=screen,
            dialogue=dialogue,
            needs_char_creation=needs_creation,
        )
        view = types.SimpleNamespace(logic_thread=types.SimpleNamespace(_miniwind=session))
        return hits.GamePointer(view).wants_pointer()

    assert pointer_for(screen="character")
    assert pointer_for(screen="trade")
    assert pointer_for(screen="spells")
    assert pointer_for(screen="inventory")
    assert pointer_for(screen="journal")
    assert pointer_for(screen="map")
    assert not pointer_for(screen="container")
    assert not pointer_for(dialogue=object())
    # Character creation is a pre-game modal, not free-play mouse-look.
    assert pointer_for(needs_creation=True)


@pytest.mark.parametrize("screen", ["trade", "spells"])
def test_closing_interactive_screen_releases_pointer_ownership(monkeypatch, screen):
    monkeypatch.setattr(hits, "has_targets", lambda: True)
    session = types.SimpleNamespace(
        game=types.SimpleNamespace(character=types.SimpleNamespace(is_dead=False)),
        open_screen=screen,
        dialogue=None,
        needs_char_creation=False,
    )
    view = types.SimpleNamespace(logic_thread=types.SimpleNamespace(_miniwind=session))
    pointer = hits.GamePointer(view)

    assert pointer.wants_pointer()
    session.open_screen = None  # Leave/close the trade window.
    assert not pointer.wants_pointer()


def test_closing_debug_tools_recaptures_cursor():
    window = _Window("debug:tools")
    view = _View(window)

    assert _window_wants_cursor(view)
    window.active = False  # DebugToolsWindow close button was pressed.
    assert not _window_wants_cursor(view)
