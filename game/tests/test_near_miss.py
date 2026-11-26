"""An arrow past the player's head, missing by inches: a whoosh (game/near_miss.py)."""

from types import SimpleNamespace

import pytest

from engine.logic_combat import PLAYER_PROJECTILE_OWNER
from engine.projectile_table import ProjectileStore

from .. import near_miss as nm
from ..stuck_arrows import AMMO_KEY

ARCHER = 12345                      # any owner that is not the player
DT = 1.0 / 60.0


def _world():
    store = ProjectileStore()
    played = []
    logic = SimpleNamespace(
        combat_runtime=SimpleNamespace(_monster_projectiles=store),
        player_runtime=SimpleNamespace(player=SimpleNamespace(pos=(0.0, 100.0, 0.0))),
        session_runtime=SimpleNamespace(monster_lock=None))
    session = SimpleNamespace(logic=logic, play_ui_sound=lambda name, volume=1.0: played.append(name))
    return store, nm.NearMiss(session), played


def _loose(store, start, vel, owner=ARCHER, arrow=True):
    return store.add(start, vel, owner, 10.0, 5.0,
                     metadata={AMMO_KEY: "iron_arrow"} if arrow else None)


def _fly(store, near, seconds=1.0, hit_radius=nm.HIT_RADIUS):
    """Move every projectile; one that ends a tick inside the hit sphere is
    consumed, as the engine does a hit."""
    head = (0.0, 100.0, 0.0)
    for _ in range(int(seconds / DT)):
        keep = []
        for row in range(len(store)):
            store.pos[row] += store.vel[row] * DT
            d = sum((float(store.pos[row, k]) - head[k]) ** 2 for k in range(3)) ** 0.5
            if d >= hit_radius:
                keep.append(row)
        if len(keep) != len(store):
            import numpy as np
            idx = np.asarray(keep, dtype=np.intp)
            store.compact(idx, store.pos[:len(store)], store.vel[:len(store)],
                          store.lifetime[:len(store)], store.distance[:len(store)])
        near.update()


def test_an_arrow_missing_the_head_by_inches_whooshes_once():
    store, near, played = _world()
    _loose(store, (-600.0, 100.0, 45.0), (1200.0, 0.0, 0.0))    # 45 off: inside the near band
    _fly(store, near)
    assert played == ["whoosh.mp3"]


def test_one_that_passes_wide_is_silent():
    store, near, played = _world()
    _loose(store, (-600.0, 100.0, 120.0), (1200.0, 0.0, 0.0))
    _fly(store, near)
    assert played == []


def test_one_that_hits_is_not_a_near_miss():
    store, near, played = _world()
    _loose(store, (-600.0, 100.0, 5.0), (1200.0, 0.0, 0.0))
    _fly(store, near)
    assert played == [] and len(store) == 0                    # consumed by the hit


def test_only_arrows_and_never_the_players_own():
    store, near, played = _world()
    _loose(store, (-600.0, 100.0, 45.0), (1200.0, 0.0, 0.0), owner=PLAYER_PROJECTILE_OWNER)
    _loose(store, (-600.0, 100.0, -45.0), (1200.0, 0.0, 0.0), arrow=False)   # a spell
    _fly(store, near)
    assert played == []


def test_a_fast_arrow_cannot_slip_between_ticks_unheard():
    store, near, played = _world()
    _loose(store, (-3000.0, 100.0, 50.0), (6000.0, 0.0, 0.0))   # 100 units a tick
    _fly(store, near)
    assert played == ["whoosh.mp3"]


def test_an_archer_beside_the_player_loosing_away_is_not_a_near_miss():
    store, near, played = _world()
    _loose(store, (0.0, 100.0, 40.0), (0.0, 0.0, 1200.0))       # starts beside, flies off
    _fly(store, near)
    assert played == []


def test_two_arrows_past_at_once_is_one_whoosh_each_tick():
    store, near, played = _world()
    _loose(store, (-600.0, 100.0, 45.0), (1200.0, 0.0, 0.0))
    _loose(store, (600.0, 100.0, -45.0), (-1200.0, 0.0, 0.0))
    _fly(store, near)
    assert played == ["whoosh.mp3"]                             # same tick: heard once


def test_nothing_in_flight_costs_nothing():
    store, near, played = _world()
    assert near.update() == 0 and played == []


@pytest.mark.parametrize("a, b, p, distance, t", [
    ((0, 0, 0), (10, 0, 0), (5, 3, 0), 3.0, 0.5),
    ((0, 0, 0), (10, 0, 0), (-5, 0, 0), 5.0, 0.0),
    ((0, 0, 0), (10, 0, 0), (12, 0, 0), 2.0, 1.0),
])
def test_closest_on_segment(a, b, p, distance, t):
    d, s = nm.closest_on_segment(a, b, p)
    assert d == pytest.approx(distance) and s == pytest.approx(t)


def test_whoosh_mp3_ships_and_is_found():
    from pathlib import Path
    from .. import runtime
    data = (Path(runtime.SOUND_DIR) / nm.WHOOSH_SOUND).read_bytes()
    assert data[:3] == b"ID3" or data[0] == 0xFF
    assert runtime.sound_available(nm.WHOOSH_SOUND)
