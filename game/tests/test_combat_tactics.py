"""Casters and archers keep their distance, and can still be caught and cut down."""

import math

import pytest

from .. import combat_styles
from ..combat_tactics import (ADVANCE, COMMIT, COMMIT_RANGE, FIGHTER_SPEED, HOLD,
                              KEEP_BAND, RETREAT, CombatTactics)
from ..combat_loadout import MAGIC

combat_styles.register()

DT = 1.0 / 30.0


class _Actor:
    def __init__(self, **props):
        self.pos = [0.0, 0.0, 0.0]
        self.properties = props


def _caster():
    return _Actor(attack_style="magic", equipped_weapon="apprentice_staff",
                  spells=[{"id": "flare"}], inventory=[{"id": "iron_dagger", "qty": 1}])


def _swordsman():
    return _Actor(attack_style="melee", equipped_weapon="iron_longsword", inventory=[])


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _step(tactics, actor, foe_x, clock):
    """One engine step: the caster moves at fighter pace toward its waypoint."""
    start = (actor.pos[0], 0.0, actor.pos[2])
    wp = tactics.waypoint(actor, start, (foe_x, 0.0, 0.0))
    goal = (foe_x, 0.0, 0.0) if wp is None else wp
    dx, dz = goal[0] - start[0], goal[2] - start[2]
    d = math.hypot(dx, dz)
    # Fio steps only fighters beyond its stop distance, toward the waypoint.
    if d > 1e-3 and math.hypot(foe_x - start[0], start[2]) > 85.0:
        actor.pos[0] += dx / d * FIGHTER_SPEED * DT
        actor.pos[2] += dz / d * FIGHTER_SPEED * DT
    clock.t += DT


def _chase(foe_speed, seconds=40.0):
    """A foe running at *foe_speed* straight at a kiting caster; the time it
    first gets within striking range, or None."""
    clock = _Clock()
    tactics = CombatTactics(clock)
    caster = _caster()
    foe_x = 700.0
    for _ in range(int(seconds / DT)):
        _step(tactics, caster, foe_x, clock)
        gap = math.hypot(foe_x - caster.pos[0], caster.pos[2])
        if gap <= COMMIT_RANGE:
            return clock.t, tactics
        foe_x -= math.copysign(foe_speed * DT, foe_x - caster.pos[0])
    return None, tactics


def test_a_ranged_caster_stands_in_its_band():
    clock = _Clock()
    tactics = CombatTactics(clock)
    caster = _caster()
    near, far = KEEP_BAND[MAGIC]
    wp = tactics.waypoint(caster, (0.0, 0.0, 0.0), ((near + far) / 2, 0.0, 0.0))
    assert wp == (0.0, 0.0, 0.0)                       # stands: its own position


def test_too_far_it_advances_and_too_close_it_backs_away():
    clock = _Clock()
    tactics = CombatTactics(clock)
    caster = _caster()
    assert tactics.waypoint(caster, (0.0, 0.0, 0.0), (2000.0, 0.0, 0.0)) is None
    wp = tactics.waypoint(caster, (0.0, 0.0, 0.0), (200.0, 0.0, 0.0))
    assert wp[0] < 0.0                                  # away from the foe
    assert tactics.retreating(caster)


def test_a_swordsman_just_chases():
    tactics = CombatTactics(_Clock())
    assert tactics.waypoint(_swordsman(), (0.0, 0.0, 0.0), (200.0, 0.0, 0.0)) is None


def test_the_player_running_catches_a_caster_quickly():
    caught, _ = _chase(foe_speed=250.0)
    assert caught is not None and caught < 6.0


@pytest.mark.parametrize("speed", [FIGHTER_SPEED, 120.0])
def test_a_fighter_at_walking_pace_still_catches_a_caster(speed):
    caught, _ = _chase(foe_speed=speed)
    assert caught is not None


def test_once_caught_it_stands_and_fights_with_its_blade():
    caught, tactics = _chase(foe_speed=250.0)
    caster = next(iter(tactics._states))
    state = tactics._states[caster]
    # The next step inside striking range commits it to melee, for a while.
    actor = _caster()
    tactics._states[id(actor)] = state
    tactics.waypoint(actor, (0.0, 0.0, 0.0), (100.0, 0.0, 0.0))
    assert state.mode == COMMIT
    assert tactics.waypoint(actor, (0.0, 0.0, 0.0), (250.0, 0.0, 0.0)) is None   # closes in


def test_a_wall_at_its_back_corners_it():
    clock = _Clock()
    tactics = CombatTactics(clock)
    caster = _caster()
    tactics.waypoint(caster, (0.0, 0.0, 0.0), (200.0, 0.0, 0.0))
    assert tactics.retreating(caster)
    clock.t += 0.6                                      # it did not move at all
    tactics.waypoint(caster, (0.0, 0.0, 0.0), (200.0, 0.0, 0.0))
    assert tactics._states[id(caster)].mode == COMMIT


def test_too_many_retreats_and_it_stops_running():
    clock = _Clock()
    tactics = CombatTactics(clock)
    caster = _caster()
    state = None
    for i in range(4):
        x = -i * 200.0
        tactics.waypoint(caster, (x, 0.0, 0.0), (x + 200.0, 0.0, 0.0))
        state = tactics._states[id(caster)]
        if state.mode == COMMIT:
            break
        # It backs away properly, then stands its rest.
        clock.t += 0.5
        tactics.waypoint(caster, (x - 45.0, 0.0, 0.0), (x + 200.0, 0.0, 0.0))
        clock.t += 2.0
        tactics.waypoint(caster, (x - 45.0, 0.0, 0.0), (x + 400.0, 0.0, 0.0))
    assert state.mode == COMMIT


def test_distant_tiers_chase_straight_on():
    from engine.spatial import TIER_DISTANT
    tactics = CombatTactics(_Clock(), tier_of=lambda t: TIER_DISTANT)
    assert tactics.waypoint(_caster(), (0.0, 0.0, 0.0), (200.0, 0.0, 0.0)) is None


def test_an_archer_mid_draw_stands_still():
    tactics = CombatTactics(_Clock(), busy=lambda t: True)
    archer = _Actor(attack_style="bow", equipped_weapon="long_bow", inventory=[])
    assert tactics.waypoint(archer, (5.0, 0.0, 7.0), (300.0, 0.0, 0.0)) == (5.0, 0.0, 7.0)


def test_out_of_magicka_a_caster_closes_like_a_swordsman():
    tactics = CombatTactics(_Clock())
    caster = _caster()
    caster.properties["max_magicka"] = 0
    assert tactics.waypoint(caster, (0.0, 0.0, 0.0), (200.0, 0.0, 0.0)) is None


# ------------------------------------------------------------ crossbows

def _archery(retreating=False):
    import random
    from types import SimpleNamespace
    from ..npc_archery import NpcArchery

    class _Combat:
        shots = []

        def spawn_projectile(self, pos, vel, **kw):
            self.shots.append(kw)
            return None

    combat = _Combat()
    logic = SimpleNamespace(combat_runtime=combat, monster_ai=None,
                            player_runtime=SimpleNamespace(player=None))
    session = SimpleNamespace(logic=logic, rng=random.Random(1), _archery_clock=10.0,
                              _player_pos=lambda: [100.0, 0.0, 0.0], _arrow_tags={},
                              tactics=SimpleNamespace(note_shot=lambda t: None,
                                                      retreating=lambda t: retreating))
    session.archery = NpcArchery(session)
    return session, combat


def _crossbowman():
    return _Actor(attack_style="bow", equipped_weapon="crossbow",
                  inventory=[{"id": "iron_dagger", "qty": 1}])


def test_a_crossbowman_shoots_from_the_hip_while_backing_away():
    session, combat = _archery(retreating=True)
    shooter = _crossbowman()
    assert session.archery.shot_hook(shooter, [400.0, 0, 0], None, 400.0 ** 2) is True
    assert len(combat.shots) == 1


def test_an_archer_with_a_bow_holds_its_fire_while_backing_away():
    session, combat = _archery(retreating=True)
    archer = _Actor(attack_style="bow", equipped_weapon="long_bow", inventory=[])
    assert session.archery.shot_hook(archer, [400.0, 0, 0], None, 400.0 ** 2) is True
    assert combat.shots == [] and not session.archery.drawing


def test_point_blank_a_loaded_crossbow_fires_then_the_blade_comes_out():
    session, combat = _archery()
    shooter = _crossbowman()
    assert session.archery.shot_hook(shooter, [100.0, 0, 0], None, 100.0 ** 2) is True
    assert len(combat.shots) == 1
    # Winding back: the next blow up close is the dagger's (the engine's strike).
    assert session.archery.shot_hook(shooter, [100.0, 0, 0], None, 100.0 ** 2) is False
    assert shooter.properties["_active_weapon"] == "iron_dagger"
    assert len(combat.shots) == 1


def test_a_pair_of_crossbows_fires_twice_before_both_wind_back():
    session, combat = _archery()
    shooter = _Actor(attack_style="bow", equipped_weapon="crossbow",
                     offhand_weapon="crossbow",
                     inventory=[{"id": "crossbow", "qty": 2}])
    hook = session.archery.shot_hook
    assert hook(shooter, [400.0, 0, 0], None, 400.0 ** 2) is True
    assert hook(shooter, [400.0, 0, 0], None, 400.0 ** 2) is True
    assert len(combat.shots) == 2
    assert shooter.properties["_offhand_anim"] > 0       # the second was the off hand's
    assert hook(shooter, [400.0, 0, 0], None, 400.0 ** 2) is True
    assert len(combat.shots) == 2                        # both winding back


def test_crossbowmen_may_carry_a_second_crossbow_but_archers_never_a_second_bow():
    import random
    from ..held_weapons import arm_fighters
    from ..rpg import items
    paired = 0
    for seed in range(60):
        xbow = _Actor(type="npc", combatant=True, faction="bandits", npc_role="bandit",
                      attack_style="bow", equipped_weapon="crossbow", inventory=[])
        bow = _Actor(type="npc", combatant=True, faction="bandits", npc_role="bandit",
                     attack_style="bow", equipped_weapon="long_bow", inventory=[])
        arm_fighters([xbow, bow], random.Random(seed), lambda i: items.make(i, 1))
        assert not bow.properties.get("offhand_weapon")
        if xbow.properties.get("offhand_weapon"):
            assert xbow.properties["offhand_weapon"] == "crossbow"
            paired += 1
    assert paired > 0


def test_marksmen_never_pair_crossbows():
    import random
    from ..held_weapons import arm_fighters
    from ..rpg import items
    for seed in range(60):
        hunter = _Actor(type="npc", combatant=True, faction="bandits", npc_role="hunter",
                        attack_style="bow", equipped_weapon="crossbow", inventory=[])
        arm_fighters([hunter], random.Random(seed), lambda i: items.make(i, 1))
        assert not hunter.properties.get("offhand_weapon")


def test_a_pair_of_crossbows_scatters_its_bolts_a_single_one_does_not():
    import math
    session, combat = _archery()
    session.rng.seed(3)

    def headings(actor):
        out = []
        combat.spawn_projectile = lambda pos, vel, **kw: out.append(math.atan2(vel[2], vel[0]))
        for _ in range(16):
            actor.properties.pop("_bow_ready_at", None)
            actor.properties.pop("_offhand_ready_at", None)
            session.archery.shot_hook(actor, [400.0, 0, 0], None, 400.0 ** 2)
        return out

    single = _Actor(attack_style="bow", equipped_weapon="crossbow", inventory=[])
    pair = _Actor(attack_style="bow", equipped_weapon="crossbow", offhand_weapon="crossbow",
                  inventory=[{"id": "crossbow", "qty": 2}])
    assert max(abs(a) for a in headings(single)) < 1e-6
    wide = [abs(math.degrees(a)) for a in headings(pair)]
    assert max(wide) > 1.0 and max(wide) <= 5.0 + 1e-6


def test_dual_wielding_costs_the_player_accuracy():
    from types import SimpleNamespace
    from ..rpg import combat, equipment, items, inventory as inv
    from ..rpg.character import Character
    c = Character()
    for _ in range(2):
        inv.add_item(c.inventory, items.make("iron_shortsword", 1))
    equipment.equip(c, "iron_shortsword")
    p = combat.hit_chance(c, c.skill("blade"), 30, c.stamina / c.max_stamina)
    # A roll just under the lone sword's chance, but over the pair's.
    roll = SimpleNamespace(random=lambda: p * 0.9)
    assert combat.player_attack(c, {"health": 50, "agility": 30}, rng=roll)["hit"]
    equipment.equip(c, "iron_shortsword", items.SLOT_SHIELD)
    assert equipment.dual_wielding(c)
    assert not combat.player_attack(c, {"health": 50, "agility": 30}, rng=roll)["hit"]
