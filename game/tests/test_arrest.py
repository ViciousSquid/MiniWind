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

from .. import runtime
from ..runtime import MiniwindSession


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


# -------------------------------------------------------------------- sound

def test_a_guard_stopping_the_player_says_one_of_the_arrest_lines(monkeypatch):
    """Either arrest1.mp3 or arrest2.mp3, picked at random, once per stop."""
    import random
    played = []

    class _Sounding(_Session):
        play_ui_sound = MiniwindSession.play_ui_sound

        def start_dialogue(self, npc, player):
            self.talking_to = npc

    for seed in range(12):
        guard = _guard((10.0, 0.0, 0.0))
        prison = _marker((5000.0, 0.0, 0.0), "prison")
        session = _Sounding([guard, prison], player_pos=(0.0, 0.0, 0.0), bounty=200)
        session.rng = random.Random(seed)
        session.logic.game_state = type("GS", (), {
            "queue_sound": staticmethod(played.append)})()
        session._arrest_guard = guard
        session._arrest_state = "approach"

        session._update_arrest()
        assert session._arrest_state == "ready"
        session._update_arrest()                     # still standing there: no repeat

    files = [p["file"] for p in played]
    assert len(files) == 12                          # one per arrest, none repeated
    assert set(files) == set(runtime.ARREST_SOUNDS)  # both lines get used
    for name in runtime.ARREST_SOUNDS:               # and the files are in the game
        assert os.path.isfile(os.path.join(runtime.SOUND_DIR, name))


# ------------------------------------------------------------- head marks

class _Marked(_Session):
    head_mark = MiniwindSession.head_mark
    head_marks = MiniwindSession.head_marks
    set_head_mark = MiniwindSession.set_head_mark

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._head_marked = {}


def test_a_guard_coming_to_arrest_shows_an_exclamation_mark():
    guard = _guard((10.0, 0.0, 0.0))
    bystander = _guard((50.0, 0.0, 0.0), name="Other")
    session = _Marked([guard, bystander], bounty=200)
    assert session.head_marks() == []
    for state in ("approach", "ready"):
        session._arrest_guard, session._arrest_state = guard, state
        assert session.head_marks() == [(guard, "!")]
    session._arrest_state = "escorting"          # walking you to gaol is calm
    assert session.head_marks() == []


def test_every_guard_running_the_player_down_shows_one():
    one, two = _guard((100.0, 0.0, 0.0), name="One"), _guard((120.0, 0.0, 0.0), name="Two")
    session = _Marked([one, two], player_pos=(0.0, 0.0, 0.0), bounty=200)
    session._start_arrest_pursuit()
    assert sorted(m for _n, m in session.head_marks()) == ["!", "!"]
    session.game.character.bounty = 0
    session._update_arrest()                     # settled: the chase ends
    assert session.head_marks() == []


def test_any_npc_can_be_given_a_mark_and_have_it_taken_away():
    villager = _Thing((0.0, 0.0, 0.0), type="npc", name="Ada")
    session = _Marked([villager])
    session.set_head_mark(villager, "?")
    assert session.head_marks() == [(villager, "?")]
    session.set_head_mark(villager, "!")
    assert session.head_mark(villager) == "!"
    villager.properties["dead"] = True
    assert session.head_marks() == []
    villager.properties.pop("dead")
    session.set_head_mark(villager, None)
    assert session.head_marks() == []
    assert "_head_mark" not in villager.properties


def test_both_mark_images_ship_with_the_game():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    for name in ("exclamation.png", "question.png"):
        assert os.path.isfile(os.path.join(root, "assets", "sprites", "marks", name))
