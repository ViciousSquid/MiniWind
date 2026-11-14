"""Crabs feed on gibs near water (game/crab_frenzy.py, GoreFX.bite/hold)."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from .. import crab_frenzy as cf
from .. import fio
from ..gore_fx import GoreFX, PIECE_REST, PIECE_FADE


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def _gore(clock):
    gore = GoreFX(rng=random.Random(3), clock=clock)
    return gore


def _land_pieces(gore, clock, pos=(0.0, 0.0, 0.0), count=3):
    gore._pieces(pos, "assets/sprites/heads/head01.png", 96.0, None, keep=count)
    for _ in range(40):                    # let them fall and come to rest
        clock.now += 0.05
        gore.update()
    assert all(p.get("rest") is not None for p in gore.pieces)
    return list(gore.pieces)


# -- bites -----------------------------------------------------------------------
def test_a_bite_takes_a_chunk_out_and_the_piece_keeps_its_size():
    clock = Clock()
    gore = _gore(clock)
    piece = _land_pieces(gore, clock, count=1)[0]
    body, quad = piece["body"], [tuple(q) for q in piece["quad"]]
    assert gore.bite(piece) is False
    assert len(piece["bites"]) == 1
    assert piece["body"] == body and [tuple(q) for q in piece["quad"]] == quad   # not shrunk
    u, v, r = piece["bites"][0]
    assert 0.0 < r < 0.2


def test_bites_eat_from_the_outside_in_until_nothing_is_left():
    clock = Clock()
    gore = _gore(clock)
    piece = _land_pieces(gore, clock, count=1)[0]
    from ..gore_fx import _remaining_points
    first_edge = {(u, v) for u, v, edge in _remaining_points(piece) if edge}
    gore.bite(piece)
    u, v, _r = piece["bites"][0]
    assert (u, v) in first_edge                     # the first bite is at the outline
    bites = 1
    while not gore.bite(piece):
        bites += 1
        assert bites < 200
    assert piece not in gore.pieces and bites > 4   # many bites, then gone


def test_held_pieces_wait_for_the_crabs_then_fade():
    clock = Clock()
    gore = _gore(clock)
    pieces = _land_pieces(gore, clock)
    held = gore.hold((0.0, 0.0, 0.0), 400.0, 30.0)
    assert len(held) == len(pieces)
    clock.now += PIECE_REST + 5.0
    gore.update()
    assert len(gore.pieces) == len(pieces)
    assert gore.piece_pose(pieces[0])[4] == 1.0       # still whole, not fading
    clock.now += 30.0
    gore.update()
    assert not gore.pieces                           # the hold ran out: gone in a fade


# -- the frenzy -----------------------------------------------------------------------
def _session(monkeypatch, ground=0.0, water_top=32.0, gore=None, clock=None):
    clock = clock or Clock()
    water = {"pos": [0.0, water_top - 16.0, -600.0], "size": [1000.0, 32.0, 600.0],
             "is_water": True}
    state = SimpleNamespace(brushes=[water], things=[])
    logic = SimpleNamespace(editor_state=state)
    monkeypatch.setattr(fio, "ground_height", lambda _l, x, z, below=None: ground)
    monkeypatch.setattr(cf, "_rebuild", lambda _s: None)
    session = SimpleNamespace(logic=logic, gore=gore or _gore(clock), rng=random.Random(5),
                              _player_pos=lambda: [0.0, 0.0, 400.0])
    return session, clock


def test_gibs_by_the_water_bring_crabs_more_for_a_bigger_body(monkeypatch):
    session, clock = _session(monkeypatch)
    _land_pieces(session.gore, clock, pos=(0.0, 0.0, -150.0))
    frenzy = cf.CrabFrenzy(random.Random(1))
    small = frenzy.gibbed(session, (0.0, 0.0, -150.0), mass=0.1)       # a hen
    big = frenzy.gibbed(session, (0.0, 0.0, -150.0), mass=2.0)         # a bear
    assert cf.MIN_CRABS <= small < big <= cf.MAX_CRABS
    crabs = [t for t in fio.things(session.logic) if t.properties.get("_frenzy")]
    assert len(crabs) == small + big
    head = crabs[0].properties
    assert head["npc_role"] == "crab" and head["aggression"] == "passive"
    assert head["sprite_width"] == 64                     # half the player's head


def test_no_crabs_far_from_water_or_where_land_covers_it(monkeypatch):
    session, clock = _session(monkeypatch)
    _land_pieces(session.gore, clock, pos=(0.0, 0.0, 2000.0))
    assert cf.CrabFrenzy(random.Random(1)).gibbed(session, (0.0, 0.0, 2000.0)) == 0
    # The sea brush under the whole land: the ground is above its surface.
    session, clock = _session(monkeypatch, ground=200.0)
    _land_pieces(session.gore, clock, pos=(0.0, 0.0, -150.0))
    assert cf.CrabFrenzy(random.Random(1)).gibbed(session, (0.0, 0.0, -150.0)) == 0


def test_the_crabs_eat_every_piece_then_scuttle_off_and_are_gone(monkeypatch):
    session, clock = _session(monkeypatch)
    _land_pieces(session.gore, clock, pos=(0.0, 0.0, -150.0), count=3)
    frenzy = cf.CrabFrenzy(random.Random(1))
    assert frenzy.gibbed(session, (0.0, 0.0, -150.0), mass=1.0) > 0
    things = fio.things(session.logic)
    saw_bitten = False
    for _ in range(3000):
        clock.now += 0.05
        session.gore.update()
        frenzy.update(session, 0.05)
        saw_bitten = saw_bitten or any(p.get("bites") for p in session.gore.pieces)
        if not frenzy.feasts:
            break
    assert saw_bitten                                   # eaten bite by bite
    assert not session.gore.pieces                      # every piece eaten
    assert not frenzy.feasts                            # and the crabs have gone
    assert not [t for t in things if t.properties.get("_frenzy")]


def test_a_save_restored_mid_feast_keeps_no_crabs(monkeypatch):
    session, clock = _session(monkeypatch)
    _land_pieces(session.gore, clock, pos=(0.0, 0.0, -150.0))
    frenzy = cf.CrabFrenzy(random.Random(1))
    made = frenzy.gibbed(session, (0.0, 0.0, -150.0), mass=1.0)
    assert cf.CrabFrenzy(random.Random(2)).purge(session) == made
    assert not [t for t in fio.things(session.logic) if t.properties.get("_frenzy")]


def test_a_person_brings_six_crabs(monkeypatch):
    session, clock = _session(monkeypatch)
    _land_pieces(session.gore, clock, pos=(0.0, 0.0, -150.0))
    assert cf.CrabFrenzy(random.Random(1)).gibbed(session, (0.0, 0.0, -150.0), mass=1.0) == 6


# -- the frenzy bites -----------------------------------------------------------------
class _Hurt:
    def __init__(self):
        self.player = []
        self.actors = []

    def _apply_player_damage(self, damage, kind="physical", source=None, cause=None):
        self.player.append((damage, cause, source))

    def _apply_monster_damage(self, victim, damage, attacker=None):
        self.actors.append((victim, damage, attacker))
        victim.properties["health"] = victim.properties.get("health", 30) - damage


def _armed(monkeypatch, player_at, actors=()):
    session, clock = _session(monkeypatch)
    hurt = _Hurt()
    session.logic.trigger_runtime = hurt
    session.logic.monster_ai = hurt
    session.logic.player_runtime = SimpleNamespace(damage_source=None, player_dead=False)
    session.logic.world_runtime = SimpleNamespace(monster_things=list(actors))
    session._player_pos = lambda: list(player_at)
    _land_pieces(session.gore, clock, pos=(0.0, 0.0, -150.0), count=3)
    return session, clock, hurt


def _run(session, clock, frenzy, seconds):
    for _ in range(int(seconds / 0.05)):
        clock.now += 0.05
        session.gore.update()
        frenzy.update(session, 0.05)


def test_the_frenzy_swarms_the_player_and_each_nip_is_small(monkeypatch):
    session, clock, hurt = _armed(monkeypatch, player_at=(30.0, 0.0, -150.0))
    frenzy = cf.CrabFrenzy(random.Random(1))
    crabs = frenzy.gibbed(session, (0.0, 0.0, -150.0), mass=1.0)
    _run(session, clock, frenzy, 6.0)
    assert hurt.player, "the crabs never bit"
    assert all(d == cf.NIP_DAMAGE and cause == "crab" for d, cause, _s in hurt.player)
    assert cf.NIP_DAMAGE <= 3                                    # one nip is nothing
    biters = {id(src) for _d, _c, src in hurt.player}
    assert len(biters) >= crabs // 2                             # but many crabs bite
    assert sum(d for d, _c, _s in hurt.player) >= 15             # a real threat


def test_people_and_animals_near_the_feast_are_attacked_but_not_crabs(monkeypatch):
    from ..entities import Creature
    villager = SimpleNamespace(pos=[60.0, 0.0, -120.0], properties={"npc_role": "villager", "health": 30})
    other_crab = SimpleNamespace(pos=[-60.0, 0.0, -120.0], properties={"npc_role": "crab", "health": 8})
    session, clock, hurt = _armed(monkeypatch, player_at=(0.0, 0.0, 3000.0),
                                  actors=[villager, other_crab])
    frenzy = cf.CrabFrenzy(random.Random(1))
    frenzy.gibbed(session, (0.0, 0.0, -150.0), mass=1.0)
    _run(session, clock, frenzy, 6.0)
    bitten = {id(v) for v, _d, _a in hurt.actors}
    assert id(villager) in bitten and id(other_crab) not in bitten
    assert not hurt.player                                       # the player is far away


def test_leaving_crabs_no_longer_bite(monkeypatch):
    session, clock, hurt = _armed(monkeypatch, player_at=(0.0, 0.0, 3000.0))
    frenzy = cf.CrabFrenzy(random.Random(1))
    frenzy.gibbed(session, (0.0, 0.0, -150.0), mass=1.0)
    _run(session, clock, frenzy, 40.0)                           # everything eaten: off they go
    assert not session.gore.pieces
    session._player_pos = lambda: [frenzy.feasts[0]["crabs"][0]["thing"].pos[0], 0.0,
                                   frenzy.feasts[0]["crabs"][0]["thing"].pos[2]] \
        if frenzy.feasts else [0.0, 0.0, 3000.0]
    before = len(hurt.player)
    _run(session, clock, frenzy, 2.0)
    assert len(hurt.player) == before


def test_each_crab_nips_once_a_second_at_a_random_moment(monkeypatch):
    session, clock, hurt = _armed(monkeypatch, player_at=(30.0, 0.0, -150.0))
    times = []
    real = hurt._apply_player_damage
    hurt._apply_player_damage = lambda *a, **k: (times.append((clock.now, id(k.get("source")))), real(*a, **k))
    frenzy = cf.CrabFrenzy(random.Random(1))
    frenzy.gibbed(session, (0.0, 0.0, -150.0), mass=1.0)
    _run(session, clock, frenzy, 10.0)
    by_crab = {}
    for t, crab in times:
        by_crab.setdefault(crab, []).append(t)
    for bites in by_crab.values():
        gaps = [b - a for a, b in zip(bites, bites[1:])]
        assert all(g > 0.04 for g in gaps)                     # never twice at once
        assert len(bites) <= 10 / cf.NIP_PERIOD + 1             # at most one a second
    # The swarm's bites are spread through the second, not in step.
    phases = {round((t % cf.NIP_PERIOD), 1) for t, _c in times}
    assert len(phases) >= 4
