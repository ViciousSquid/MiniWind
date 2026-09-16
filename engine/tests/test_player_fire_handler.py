"""The engine's shot path hands fire buttons to a game layer's handler.

``LogicThread._handle_shooting`` owns *when* a shot happens (queued by the view,
consumed on the logic tick); an installed ``player_fire_handler`` owns *what* a
shot is. MiniWind installs one that swings, looses arrows and casts spells.
Without one, primary fire is Fio's hitscan weapon and secondary fire is inert.

Run:  python -m pytest engine/tests/test_player_fire_handler.py -q
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from engine.logic_thread import LogicThread
from engine.threaded_game_state import ThreadedGameState


class _Logic:
    """Just what _handle_shooting reads before it reaches the hitscan path."""

    _handle_shooting = LogicThread._handle_shooting

    def __init__(self, handler=None, weapon=None):
        self.player = object()
        self.player_fire_handler = handler
        self.active_weapon = weapon
        self.events = []
        self.hitscan_reached = False

    def _plugin_emit(self, name, **payload):
        self.events.append((name, payload))


def test_primary_and_secondary_fire_reach_the_handler():
    calls = []
    logic = _Logic(handler=lambda lt, mode: calls.append((lt, mode)) or True)
    logic._handle_shooting()
    logic._handle_shooting(secondary=True)
    assert calls == [(logic, "primary"), (logic, "secondary")]
    assert [p["mode"] for n, p in logic.events if n == "player_shoot"] == ["primary", "secondary"]


def test_a_handled_shot_never_falls_through_to_hitscan():
    logic = _Logic(handler=lambda lt, mode: True, weapon="gun1")
    logic.game_state = None            # the hitscan path would touch this
    logic._handle_shooting()           # must return before reaching it


def test_secondary_fire_without_a_handler_does_nothing():
    logic = _Logic(handler=None, weapon="gun1")
    logic._handle_shooting(secondary=True)
    assert logic.events == []


def test_a_failing_handler_is_logged_and_counts_as_handled():
    def boom(lt, mode):
        raise RuntimeError("bow string snapped")
    logic = _Logic(handler=boom, weapon="gun1")
    logic.game_state = None
    logic._handle_shooting()
    assert logic.events and logic.events[0][0] == "player_shoot"


def test_the_game_state_queues_secondary_shots_like_primary_ones():
    gs = ThreadedGameState()
    assert gs.consume_secondary_shot() is False
    gs.queue_secondary_shot()
    gs.queue_shot()
    assert gs.consume_secondary_shot() is True
    assert gs.consume_secondary_shot() is False
    assert gs.consume_shot() is True
