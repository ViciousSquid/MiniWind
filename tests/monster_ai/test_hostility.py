"""A game-supplied hostility model decides who fights whom and who hunts the
player (``engine/hostility.py``), in both the dense pass and the per-monster
path, and the batch's nearest enemy follows the model's matrix.

With no model installed nothing changes (every other test in this package).
"""

import math
import random

import numpy as np
import pytest

from editor.things import Monster
from engine.hostility import HostilityModel
from engine.monster_ai import MonsterAI
from engine.monster_constants import MONSTER_SHOOT_INTERVAL
from tests.helpers.fakes import FakeLogicThread, FakePlayer
from tests.helpers.worlds import box_brush, make_thing

pytestmark = pytest.mark.qt

TICK = 1.0 / 30.0


# ---------------------------------------------------------------- the model

def _model(**kw):
    # red attacks blue but not the other way round; only red hunts the player.
    return HostilityModel(["red", "blue", "green"],
                          [[False, True, False],
                           [False, False, False],
                           [False, False, False]],
                          [True, False, False], **kw)


def test_the_matrix_is_resolved_into_the_tables_team_order():
    matrix, hunts = _model().for_names(["blue", "red", "stranger"])
    assert matrix.tolist() == [[False, False, True],     # blue: nobody but the stranger
                               [True, False, True],      # red: blue (and the stranger)
                               [True, True, False]]      # unknown: the old rule
    assert hunts.tolist() == [False, True, True]


def test_scalar_answers_match_the_matrix():
    m = _model()
    assert m.is_hostile("Red", " blue ")             # names are normalised
    assert not m.is_hostile("blue", "red")
    assert m.is_hostile("red", "stranger") and m.is_hostile("stranger", "green")
    assert not m.is_hostile("", "red")


def test_an_actor_can_override_its_groups_player_mask():
    m = _model(hunts_key="aggression", hunts_values=("hostile",))
    props = [{"team": "red"}, {"team": "blue"}, {"team": "blue", "aggression": "hostile"},
             {"team": "red", "aggression": "passive"}, {}]
    names = ["red", "blue"]
    codes = np.array([0, 1, 1, 0, -1])
    assert m.row_hunts(props, codes, names).tolist() == [True, False, True, False, True]
    assert [m.hunts(p) for p in props] == [True, False, True, False, True]


def test_the_model_rejects_a_matrix_of_the_wrong_shape():
    with pytest.raises(ValueError):
        HostilityModel(["a", "b"], np.zeros((3, 3), bool), [True, True])


# ------------------------------------------------------ the dense kernel

def test_the_batch_kernel_follows_the_matrix():
    rng = np.random.default_rng(7)
    count = 90
    pos = rng.uniform(-1500, 1500, size=(count, 3))
    team_id = rng.integers(-1, 3, size=count).astype(np.int32)
    alive = rng.random(count) > 0.1
    hostile = np.array([[False, True, False], [False, False, True], [True, False, False]])
    got = MonsterAI._nearest_enemy_rows(pos, team_id, alive, 1200.0, hostile)
    p32 = pos.astype(np.float32)
    for row in range(count):
        if not alive[row] or team_id[row] < 0:
            continue
        best, best_d = -1, None
        for col in range(count):
            if (not alive[col] or team_id[col] < 0
                    or not hostile[team_id[row], team_id[col]]):
                continue
            d = p32[row] - p32[col]
            dd = d[0] * d[0] + d[1] * d[1] + d[2] * d[2]
            if dd <= np.float32(1200.0) ** 2 and (best_d is None or dd < best_d):
                best, best_d = col, dd
        assert got[row] == best, row


# ------------------------------------------------- dense vs per-monster

def _world(seed, dense, model):
    rng = random.Random(seed)
    brushes = [box_brush("ground", (0, -16, 0), (8192, 32, 8192)),
               box_brush("wall", (0, 64, 700), (600, 160, 32))]
    things = []
    for i in range(16):
        # green and blue never fight anyone, so nothing depends on which
        # monster moves first in a tick; only red goes for the player. Red
        # stands east of the player and the rest west, out of red's line of
        # fire: a monster hit by crossfire rounds on whoever hit it, which
        # is right, but would be a fight, and a fight is order-dependent.
        team = ("red", "blue", "green")[i % 3]
        r = rng.uniform(300, 1200)
        angle = rng.uniform(-0.6, 0.6) + (0.0 if team == "red" else math.pi)
        things.append(make_thing(
            Monster, "%s%02d" % (team, i), (r * math.cos(angle), 96, r * math.sin(angle)),
            monster_type=rng.choice(["human", "flying"]), team=team,
            awake=rng.random() < 0.8, wake_on_sight=True, health=60, damage=9))
    logic = FakeLogicThread(brushes=brushes, things=things,
                            player=FakePlayer((0.0, 0.0, 0.0)))
    logic.player_health = 10 ** 9
    logic._monster_things = [t for t in logic.things if isinstance(t, Monster)]
    ai = MonsterAI(logic)
    ai.DENSE_UPDATE = dense
    ai.set_spatial_grid(logic.build_spatial_grid())
    ai.set_hostility(model)
    return ai, logic


def _peaceful_model():
    return HostilityModel(["red", "blue", "green"], np.zeros((3, 3), bool),
                          [True, False, False])


def _snapshot(ai, logic):
    out = []
    for m in logic._monster_things:
        p = m.properties
        st = ai.monster_states.get(id(m))
        out.append((tuple(m.pos), p.get('awake'), p.get('is_shooting'),
                    None if st is None else (st['shoot_timer'], st['in_sight'])))
    return out, list(logic.damage_applied), len(logic._monster_projectiles)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_dense_and_per_monster_paths_agree_under_a_model(seed):
    dense_ai, dense_logic = _world(seed, True, _peaceful_model())
    ref_ai, ref_logic = _world(seed, False, _peaceful_model())
    for tick in range(int(4 * MONSTER_SHOOT_INTERVAL / TICK)):
        dense_ai.update(TICK)
        ref_ai.update(TICK)
        assert _snapshot(dense_ai, dense_logic) == _snapshot(ref_ai, ref_logic), tick


@pytest.mark.parametrize("dense", [True, False])
def test_only_the_hunters_go_for_the_player(dense):
    ai, logic = _world(4, dense, _peaceful_model())
    start = {m.name: tuple(m.pos[i] for i in (0, 2)) for m in logic._monster_things}
    for _ in range(int(3 * MONSTER_SHOOT_INTERVAL / TICK)):
        ai.update(TICK)
    for m in logic._monster_things:
        moved = start[m.name] != tuple(m.pos[i] for i in (0, 2))
        if not m.name.startswith("red"):
            assert not moved, m.name                 # no target: stays put
            assert not m.properties.get('is_shooting'), m.name
    assert any(start[m.name] != tuple(m.pos[i] for i in (0, 2))
               for m in logic._monster_things if m.name.startswith("red"))


def test_a_non_hunter_never_targets_the_player_even_when_provoked():
    """Shot by a hunter, a non-hunter fights back: at the hunter, never the
    player."""
    from engine.monster_table import TARGET_PLAYER
    ai, logic = _world(6, True, _peaceful_model())
    red = next(m for m in logic._monster_things if m.name.startswith("red"))
    blue = next(m for m in logic._monster_things if m.name.startswith("blue"))
    blue.properties['awake'] = True
    blue.properties['_aggro_target'] = id(red)        # provoked
    for _ in range(40):
        ai.update(TICK)
        row = ai.table.row_of.get(id(blue))
        assert ai.table.target[row] != TARGET_PLAYER


@pytest.mark.parametrize("dense", [True, False])
def test_a_non_hunter_does_not_wake_to_the_player(dense):
    ai, logic = _world(5, dense, _peaceful_model())
    sleeper = next(m for m in logic._monster_things if m.name.startswith("blue"))
    sleeper.properties['awake'] = False
    sleeper.pos[0], sleeper.pos[2] = 50.0, 50.0       # right beside the player
    ai.update(TICK)
    assert not sleeper.properties.get('awake')


# ------------------------------------------------------------- lifecycle

def test_forgetting_the_session_clears_its_game_hooks():
    ai, _logic = _world(1, True, _peaceful_model())

    def hook(thing, state, in_melee):
        return "melee"
    MonsterAI.install_attack_style_hook(hook)
    try:
        ai.forget_monsters()
        assert ai.hostility is None
        assert MonsterAI._attack_style_hook is None
    finally:
        MonsterAI.clear_attack_style_hook()


def test_clearing_someone_elses_hook_leaves_it():
    def ours(*a):
        return "bow"

    def theirs(*a):
        return "melee"
    MonsterAI.install_attack_style_hook(theirs)
    try:
        MonsterAI.clear_attack_style_hook(ours)
        assert MonsterAI._attack_style_hook is theirs
    finally:
        MonsterAI.clear_attack_style_hook()
