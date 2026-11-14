"""MiniWind has no split screen: F9 (and the console's ``ss``) do nothing in
play; local players share one view through Multiplayer's local co-op."""

from __future__ import annotations


def _pointer(party=None):
    from engine.view_pointer import ViewPointer
    pointer = ViewPointer.__new__(ViewPointer)
    pointer._party = lambda: party
    return pointer


def test_miniwind_turns_split_screen_off(monkeypatch):
    import game
    from plugins.manager import get_manager
    manager = get_manager()
    manager.register_builtin_game(game.GAME)
    assert game.GAME.allows_splitscreen is False
    assert not _pointer().splitscreen_allowed()


def test_a_game_that_allows_it_still_can(monkeypatch):
    from plugins.manager import get_manager
    manager = get_manager()
    monkeypatch.setattr(manager, "_builtin_games", [type("Other", (), {})()])
    assert _pointer().splitscreen_allowed()
    assert not _pointer(party=object()).splitscreen_allowed()   # a party never


def test_f9_leaves_the_view_alone(monkeypatch):
    from types import SimpleNamespace
    from engine.qt_game_view import QtGameView
    toasts = []
    view = SimpleNamespace(pointer=_pointer(), splitscreen_mode=False, play_mode=True,
                           editor=SimpleNamespace(show_toast=toasts.append))
    import game
    from plugins.manager import get_manager
    get_manager().register_builtin_game(game.GAME)
    QtGameView._toggle_splitscreen(view)
    assert view.splitscreen_mode is False and not toasts
