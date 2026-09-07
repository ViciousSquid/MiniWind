"""
Death attends one funeral in four.

When an NPC dies there is a one-in-four chance the reaper is sent for them. He
fades in a random way off from the body, glides over to it, takes it with a
stroke of his scythe, pauses for a moment and fades out again. He is pure
spectacle: he does no damage, cannot be attacked, the combat AI never sees him
(``disabled``), and when the visit is over he takes himself out of the scene.

Run:  python -m pytest game/tests/test_reaper.py -q
"""

from __future__ import annotations

import math
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game import runtime
from game.runtime import MiniwindSession
from game.rpg import items as rpg_items


class _Logic:
    def __init__(self):
        self.things = []
        self.rebuilds = 0

    def _build_entity_caches(self):
        self.rebuilds += 1


class _Body:
    """A corpse for him to come for."""

    def __init__(self, pos=(0.0, 0.0, 0.0)):
        self.pos = list(pos)
        self.properties = {"type": "npc", "name": "Wick", "dead": True}


class _Session:
    """The reaper machinery, on a session with nothing else running."""

    _maybe_send_the_reaper = MiniwindSession._maybe_send_the_reaper
    _make_reaper = MiniwindSession._make_reaper
    _update_reapers = MiniwindSession._update_reapers
    _advance_reaper = MiniwindSession._advance_reaper
    _reaper_phase = MiniwindSession._reaper_phase
    _reaper_body_ok = MiniwindSession._reaper_body_ok
    _reaper_face_body = MiniwindSession._reaper_face_body
    _reaper_glide = MiniwindSession._reaper_glide
    _despawn_reaper = MiniwindSession._despawn_reaper
    _banish_reapers = MiniwindSession._banish_reapers
    _rebuild_entity_caches = MiniwindSession._rebuild_entity_caches
    _attackable = MiniwindSession._attackable

    def __init__(self, seed=1):
        self.logic = _Logic()
        self.rng = random.Random(seed)
        self._reapers = []
        self._type_index_token = None


@pytest.fixture
def session():
    return _Session()


def _summon(session, body=None):
    """Force a visit regardless of the roll, and return the reaper."""
    body = body or _Body()
    session.rng = random.Random(0)
    session.rng.random = lambda: 0.0          # always inside REAPER_CHANCE
    session._maybe_send_the_reaper(body)
    assert session._reapers, "no reaper was sent"
    return session._reapers[0], body


def _run(session, seconds, step=0.05):
    for _ in range(int(seconds / step)):
        session._update_reapers(step)


# ===========================================================================
# Who gets a visit
# ===========================================================================
def test_a_roll_under_the_chance_sends_him(session):
    session.rng.random = lambda: runtime.REAPER_CHANCE - 0.01
    session._maybe_send_the_reaper(_Body())
    assert len(session._reapers) == 1
    assert len(session.logic.things) == 1


def test_a_roll_over_the_chance_does_not(session):
    session.rng.random = lambda: runtime.REAPER_CHANCE
    session._maybe_send_the_reaper(_Body())
    assert session._reapers == []
    assert session.logic.things == []


def test_roughly_one_death_in_four_is_attended():
    """The odds, over enough deaths to be sure it is not one-in-two."""
    session = _Session(seed=7)
    visited = 0
    for _ in range(400):
        session._reapers = []               # each death judged on its own
        session.logic.things = []
        session._maybe_send_the_reaper(_Body())
        visited += bool(session._reapers)
    assert 0.18 < visited / 400 < 0.32


def test_no_more_than_the_cap_at_once(session):
    session.rng.random = lambda: 0.0
    for _ in range(runtime.REAPER_MAX + 4):
        session._maybe_send_the_reaper(_Body())
    assert len(session._reapers) == runtime.REAPER_MAX


def test_the_scene_cache_is_rebuilt_when_he_arrives(session):
    _summon(session)
    assert session.logic.rebuilds == 1, "the engine must be told the scene changed"


# ===========================================================================
# What he is
# ===========================================================================
def test_he_appears_a_random_way_off_from_the_body(session):
    visit, body = _summon(session)
    reaper = visit["thing"]
    distance = math.hypot(reaper.pos[0] - body.pos[0], reaper.pos[2] - body.pos[2])
    low, high = runtime.REAPER_ARRIVE_DIST
    assert low <= distance <= high
    assert reaper.pos[1] == body.pos[1], "he arrives on the body's floor"


def test_he_arrives_invisible(session):
    visit, _ = _summon(session)
    assert visit["thing"].properties["_opacity"] == 0.0


def test_he_carries_the_scythe(session):
    visit, _ = _summon(session)
    assert visit["thing"].properties["equipped_weapon"] == runtime.REAPER_WEAPON
    assert rpg_items.get(runtime.REAPER_WEAPON) is not None


def test_he_wears_the_reaper_head_and_is_drawn_as_one(session):
    visit, _ = _summon(session)
    props = visit["thing"].properties
    assert "reaper" in str(props.get("custom_idle", ""))
    assert props["is_head"] is True


def test_the_combat_ai_never_sees_him(session):
    visit, _ = _summon(session)
    assert visit["thing"].properties["disabled"] is True


def test_he_cannot_be_attacked(session):
    visit, _ = _summon(session)
    assert session._attackable(visit["thing"]) is False


# ===========================================================================
# The visit
# ===========================================================================
def test_he_fades_in_where_he_appeared(session):
    visit, _ = _summon(session)
    props = visit["thing"].properties
    _run(session, runtime.REAPER_FADE_IN * 0.5)
    assert 0.0 < props["_opacity"] < 1.0
    assert visit["phase"] == "arrive"


def test_he_is_solid_once_he_has_arrived(session):
    visit, _ = _summon(session)
    _run(session, runtime.REAPER_FADE_IN + 0.2)
    assert visit["thing"].properties["_opacity"] == 1.0
    assert visit["phase"] == "approach"


def test_he_moves_toward_the_body(session):
    visit, body = _summon(session)
    reaper = visit["thing"]
    start = math.hypot(reaper.pos[0] - body.pos[0], reaper.pos[2] - body.pos[2])
    _run(session, runtime.REAPER_FADE_IN + 0.5)
    now = math.hypot(reaper.pos[0] - body.pos[0], reaper.pos[2] - body.pos[2])
    assert now < start


def test_he_stops_within_reach_and_swings(session):
    visit, body = _summon(session)
    reaper = visit["thing"]
    _run(session, 12.0)
    distance = math.hypot(reaper.pos[0] - body.pos[0], reaper.pos[2] - body.pos[2])
    assert distance <= runtime.REAPER_REACH + 1e-6
    assert visit["phase"] in ("reap", "linger", "leave")


def test_he_faces_the_body_when_he_reaps(session):
    body = _Body(pos=(0.0, 0.0, 0.0))
    visit, _ = _summon(session, body)
    _run(session, 12.0)
    reaper = visit["thing"]
    want = math.atan2(body.pos[0] - reaper.pos[0], body.pos[2] - reaper.pos[2])
    got = float(reaper.properties["_facing"])
    assert abs(math.atan2(math.sin(got - want), math.cos(got - want))) < 0.2


def test_the_swing_is_the_ordinary_attack_animation(session):
    """So the scythe animates exactly the way any other melee weapon does."""
    visit, _ = _summon(session)
    swung = False
    for _ in range(400):
        session._update_reapers(0.05)
        if visit["phase"] == "reap" and visit["thing"].properties.get("is_shooting"):
            swung = True
            assert visit["thing"].properties.get("_attack_anim")
            break
    assert swung, "he never swung"


def test_the_swing_ends(session):
    visit, _ = _summon(session)
    _run(session, 20.0)
    props = visit["thing"].properties
    assert not props.get("is_shooting")
    assert not props.get("_attack_anim")


def test_he_fades_out_and_leaves(session):
    visit, _ = _summon(session)
    _run(session, 60.0)
    assert session._reapers == []
    assert session.logic.things == [], "he must take himself out of the scene"


def test_the_whole_visit_is_over_in_well_under_a_minute(session):
    _summon(session)
    _run(session, 30.0)
    assert session._reapers == []


# ===========================================================================
# When there is nothing left to reap
# ===========================================================================
def test_a_gibbed_body_is_not_worth_the_walk(session):
    body = _Body()
    visit, _ = _summon(session, body)
    body.properties["gibbed"] = True
    _run(session, runtime.REAPER_FADE_IN + 0.2)
    assert visit["phase"] == "leave"


def test_a_resurrected_body_sends_him_away(session):
    body = _Body()
    visit, _ = _summon(session, body)
    body.properties["dead"] = False
    _run(session, runtime.REAPER_FADE_IN + 0.2)
    assert visit["phase"] == "leave"
    _run(session, runtime.REAPER_FADE_OUT + 0.2)
    assert session._reapers == []


def test_a_visit_that_cannot_reach_the_body_still_ends(session):
    """A corpse that keeps moving away must not leave him gliding for ever."""
    body = _Body()
    visit, _ = _summon(session, body)
    for _ in range(2000):
        body.pos[0] += 200.0          # always further off than he can travel
        session._update_reapers(0.05)
        if not session._reapers:
            break
    assert session._reapers == [], "he gave up and left"


def test_banishing_clears_every_visit_at_once(session):
    session.rng.random = lambda: 0.0
    for _ in range(runtime.REAPER_MAX):
        session._maybe_send_the_reaper(_Body())
    session._banish_reapers()
    assert session._reapers == []
    assert session.logic.things == []
