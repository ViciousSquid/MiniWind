"""Regression coverage for non-modal Debug Tools actions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5")

pytestmark = pytest.mark.qt

from game import host as game_host
from game import music
from game.ui import hits, inspector


class _Session:
    needs_char_creation = False
    open_screen = None
    dialogue = None

    def __init__(self):
        self.tick_count = 0
        self.teleported = None
        self.persist_count = 0

    def teleport_player(self, pos):
        self.teleported = tuple(pos)
        return True

    def tick(self, delta):
        self.tick_count += 1

    def persist(self):
        self.persist_count += 1


@pytest.fixture(autouse=True)
def _empty_click_queue():
    hits.clear()
    yield
    hits.clear()


def test_unpaused_play_tick_drains_debug_tools_action_queue(monkeypatch):
    """Cave teleport and rewind queue work that must run outside modal menus."""
    session = _Session()
    logic = SimpleNamespace(_miniwind=session)
    ctx = SimpleNamespace(delta=0.1)
    game = object.__new__(game_host.MiniwindGame)

    # Keep this regression focused on host tick routing, not unrelated runtime
    # systems that also run during a real gameplay tick.
    game._just_pressed = lambda _ctx: set()
    game._update_interact_hold = lambda _ctx: None
    game._handle_gameplay_input = lambda *_args: None
    game._handle_interaction = lambda *_args: None
    monkeypatch.setattr(game_host.fio, "set_world_paused", lambda *_args: None)
    monkeypatch.setattr(game_host.fio, "world_paused", lambda _logic: False)
    monkeypatch.setattr(music.PLAYER, "poll", lambda: None)
    monkeypatch.setattr(inspector, "cancel_focus_on_move", lambda *_args: None)

    hits.queue(lambda active_session: active_session.teleport_player((10, 20, 30)))
    game.on_tick(logic, ctx)

    assert session.teleported == (10, 20, 30)
    assert session.tick_count == 1
    assert session.persist_count == 1
