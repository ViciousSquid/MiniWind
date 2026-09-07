"""
Being arrested: where the guard takes you, and what he does when you run.

Two things were wrong. The escort walked the player to the guard's own post
instead of the gaol — the prison was looked up by *entity name* while the editor
authors it as a Marker with ``marker_kind = "prison"``, so the lookup almost
never matched and fell through to the nearest guardpost. And breaking away only
flipped nearby guards hostile, which hands them to the combat AI: that engages
what it can *see*, so a guard lost the player at the first corner and stood
there. Guards now also hold a runtime-driven pursuit that keeps them coming.

Run:  python -m pytest game/tests/test_arrest.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game import runtime
from game.runtime import MiniwindSession


class _Thing:
    def __init__(self, pos, **props):
        self.pos = list(pos)
        self.properties = dict(props)


def _marker(pos, kind, name=""):
    return _Thing(pos, type="marker", marker_kind=kind, name=name)


def _guard(pos, name="Guard"):
    return _Thing(pos, type="npc", npc_role="guard", faction="guards",
                  name=name, display_name=name, aggression="defensive",
                  combatant=True)


class _Character:
    def __init__(self, bounty=0):
        self.bounty = bounty
        self.is_dead = False


class _Game:
    def __init__(self, bounty=0):
        self.character = _Character(bounty)


class _Player:
    def __init__(self, pos):
        self.pos = list(pos)


class _Logic:
    def __init__(self, things, player_pos):
        self.things = list(things)
        self.player = _Player(player_pos)


class _Session:
    """The arrest flow, bound to a scene of plain things.

    Every method under test is MiniwindSession's own; only the scene plumbing
    the flow reaches for is stood in.
    """

    _prison_marker = MiniwindSession._prison_marker
    _prison_position = MiniwindSession._prison_position
    _update_arrest = MiniwindSession._update_arrest
    _update_arrest_pursuit = MiniwindSession._update_arrest_pursuit
    _start_arrest_pursuit = MiniwindSession._start_arrest_pursuit
    _end_arrest_pursuit = MiniwindSession._end_arrest_pursuit
    _begin_escort = MiniwindSession._begin_escort
    _clear_arrest = MiniwindSession._clear_arrest
    _decide_arrest = MiniwindSession._decide
    _is_arrest_guard = MiniwindSession._is_arrest_guard
    _is_guard = staticmethod(MiniwindSession._is_guard)
    _marker_kind = staticmethod(MiniwindSession._marker_kind)
    # Markers are grouped by kind once per scene change rather than rescanned
    # (and re-lowercased) on every arrest tick; the stub takes the same route.
    _markers_of_kind = MiniwindSession._markers_of_kind
    _find_named = MiniwindSession._find_named
    _nearest_of = MiniwindSession._nearest_of
    _dist2d = staticmethod(MiniwindSession._dist2d)
    _player_pos = MiniwindSession._player_pos

    def __init__(self, things=(), player_pos=(0.0, 0.0, 0.0), bounty=0):
        self._marker_kinds = {}
        self._marker_kinds_token = None
        self.logic = _Logic(things, player_pos)
        self.game = _Game(bounty)
        self._arrest_guard = None
        self._arrest_state = ""
        self._arrest_notice_sent = False
        self._arrest_pursuers = []
        self.notices = []

    # The flow only ever reads these two off the scene.
    def _things_of_type(self, type_name):
        wanted = type_name.replace("_", "").lower()
        return [t for t in self.logic.things
                if str(t.properties.get("type", "")).replace("_", "").lower() == wanted]

    def npcs(self):
        return [t for t in self._things_of_type("npc")
                if not t.properties.get("dead")]

    def notify(self, text, seconds=3.0):
        self.notices.append(text)


# ------------------------------------------------------------------- prison

def test_the_prison_is_found_by_its_marker_kind():
    """The regression: it was looked up by name, which almost never matched."""
    prison = _marker((900.0, 0.0, 900.0), "prison", name="gaol_01")
    post = _marker((10.0, 0.0, 10.0), "guardpost", name="post_a")
    session = _Session([prison, post])
    assert session._prison_position() == [900.0, 0.0, 900.0]


def test_a_guardpost_is_never_mistaken_for_a_prison():
    """You are taken to gaol, not to where the guard happens to work."""
    session = _Session([_marker((10.0, 0.0, 10.0), "guardpost", name="post_a")])
    assert session._prison_position() is None


def test_a_prison_authored_only_by_name_still_works():
    named = _Thing((5.0, 0.0, 5.0), type="marker", marker_kind="",
                   name=runtime.PRISON_MARKER_NAME)
    assert _Session([named])._prison_position() == [5.0, 0.0, 5.0]


def test_an_escort_walks_toward_the_prison():
    prison = _marker((900.0, 0.0, 900.0), "prison", name="gaol_01")
    post = _marker((10.0, 0.0, 10.0), "guardpost", name="post_a")
    guard = _guard((20.0, 0.0, 20.0))
    session = _Session([prison, post, guard], bounty=200)
    session._arrest_guard = guard
    session._begin_escort()
    assert session._arrest_state == "escorting"

    session._decide_arrest(guard)
    assert guard.properties["_dest"] == [900.0, 0.0, 900.0]
    assert guard.properties["sched_state"] == "ESCORT"


def test_an_escort_cannot_start_without_a_prison():
    guard = _guard((20.0, 0.0, 20.0))
    session = _Session([_marker((10.0, 0.0, 10.0), "guardpost"), guard], bounty=200)
    session._arrest_guard = guard
    session._begin_escort()
    assert session._arrest_state != "escorting"
    assert session.notices


# ------------------------------------------------------------------ pursuit

def test_breaking_away_starts_a_chase():
    guard = _guard((100.0, 0.0, 0.0))
    session = _Session([guard], player_pos=(0.0, 0.0, 0.0), bounty=200)
    session._start_arrest_pursuit()

    assert session._arrest_state == "pursuit"
    assert guard in session._arrest_pursuers
    assert guard.properties["_arrest_state"] == "pursuit"
    assert guard.properties["aggression"] == "hostile"


def test_a_pursuing_guard_keeps_walking_to_where_the_player_is():
    """The point of the chase: he must not stop at the corner you ran round."""
    guard = _guard((100.0, 0.0, 0.0))
    session = _Session([guard], player_pos=(0.0, 0.0, 0.0), bounty=200)
    session._start_arrest_pursuit()

    session.logic.player.pos = [2000.0, 0.0, 400.0]      # the player runs
    session._decide_arrest(guard)
    assert guard.properties["_dest"] == [2000.0, 0.0, 400.0]
    assert guard.properties["sched_state"] == "PURSUE"


def test_a_distant_guard_does_not_join_the_chase():
    near = _guard((100.0, 0.0, 0.0), name="Near")
    far = _guard((runtime.GUARD_PURSUIT_RADIUS * 3, 0.0, 0.0), name="Far")
    session = _Session([near, far], player_pos=(0.0, 0.0, 0.0), bounty=200)
    session._start_arrest_pursuit()
    assert session._arrest_pursuers == [near]


def test_the_chase_needs_no_prison_on_the_map():
    """Refusing arrest in a village with no gaol still gets you run down."""
    guard = _guard((100.0, 0.0, 0.0))
    session = _Session([guard], player_pos=(0.0, 0.0, 0.0), bounty=200)
    session._start_arrest_pursuit()
    session._update_arrest()
    assert session._arrest_state == "pursuit"


def test_the_chase_ends_when_the_bounty_is_settled():
    guard = _guard((100.0, 0.0, 0.0))
    session = _Session([guard], player_pos=(0.0, 0.0, 0.0), bounty=200)
    session._start_arrest_pursuit()

    session.game.character.bounty = 0
    session._update_arrest()

    assert session._arrest_state == ""
    assert session._arrest_pursuers == []
    assert "_arrest_state" not in guard.properties
    assert guard.properties["aggression"] == "defensive"


def test_a_dead_pursuer_drops_out_of_the_chase():
    one = _guard((100.0, 0.0, 0.0), name="One")
    two = _guard((120.0, 0.0, 0.0), name="Two")
    session = _Session([one, two], player_pos=(0.0, 0.0, 0.0), bounty=200)
    session._start_arrest_pursuit()

    one.properties["dead"] = True
    session._update_arrest_pursuit()
    assert session._arrest_pursuers == [two]
    assert session._arrest_state == "pursuit"


def test_the_last_pursuer_falling_ends_the_chase():
    guard = _guard((100.0, 0.0, 0.0))
    session = _Session([guard], player_pos=(0.0, 0.0, 0.0), bounty=200)
    session._start_arrest_pursuit()
    guard.properties["dead"] = True
    session._update_arrest_pursuit()
    assert session._arrest_state == ""


def test_clearing_an_arrest_calls_off_any_chase():
    guard = _guard((100.0, 0.0, 0.0))
    session = _Session([guard], player_pos=(0.0, 0.0, 0.0), bounty=200)
    session._start_arrest_pursuit()
    session._clear_arrest()
    assert session._arrest_pursuers == []
    assert guard.properties["aggression"] == "defensive"
