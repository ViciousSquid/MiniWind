"""Every living thing has an Armour Class, and every attack is d20 + the
attacker's bonus against it: the player's swings and shots, every blow the
player takes, and every fight between NPCs and creatures. AC also makes a
block's saving throw easier, and the outcome floats over the attacker."""

from __future__ import annotations

import random
from types import SimpleNamespace

import pytest

from ..diceroll import DiceRoller
from ..rpg import armour_class as ac, blocking, combat, items
from ..rpg.character import Character
from ..rpg.dialogue import DictStore
from ..rpg.game_state import GameState


class Faces(random.Random):
    def __init__(self, *faces):
        super().__init__(0)
        self.faces = iter(faces)

    def randint(self, low, high):
        return next(self.faces)


def creature(role, **extra):
    props = {"name": role, "creature_role": role, "health": 100,
             "strength": 40, "endurance": 40, "charisma": 40}
    props.update(extra)
    return props


# ------------------------------------------------------------ everyone has one
@pytest.mark.parametrize("role", ["hen", "sheep", "cow", "wolf", "boar", "bear",
                                  "mudcrab", "skeleton", "guard", "bandit", "villager"])
def test_every_kind_of_creature_has_an_armour_class(role):
    assert ac.of(creature(role)) >= ac.BASE_AC


def test_a_bear_is_harder_to_hit_than_a_hen_and_a_guard_than_a_villager():
    assert ac.of(creature("bear")) > ac.of(creature("hen"))
    assert ac.of(creature("guard")) > ac.of(creature("villager"))


def test_an_authored_armour_class_wins():
    assert ac.of(creature("hen", armour_class=19)) == 19


def test_a_shield_endurance_and_level_add_to_it():
    plain = ac.of(creature("bandit"))
    assert ac.of(creature("bandit", offhand_weapon="iron_shield")) > plain
    assert ac.of(creature("bandit", endurance=80)) == plain + 4
    assert ac.of(creature("bandit", creature_level=7)) == plain + 2


def test_to_hit_is_a_d20_held_between_five_and_ninety_five_percent():
    assert ac.to_hit(5, 15) == pytest.approx(0.55)          # need 10+
    assert ac.to_hit(50, 10) == 0.95 and ac.to_hit(-50, 30) == 0.05


def test_stronger_higher_level_foes_hit_harder_to_miss():
    assert ac.npc_attack_bonus(creature("wolf", creature_level=4, strength=75)) > \
        ac.npc_attack_bonus(creature("wolf"))
    assert ac.npc_attack_bonus(creature("wolf", attack_bonus=2)) == 2


# ----------------------------------------------------------- the player's rolls
def _game():
    game = GameState.new_game(DictStore(), "T", "imperial", "warrior", rng=random.Random(0))
    return game


def test_the_players_melee_swing_rolls_against_armour_class_even_close_and_faced():
    game = _game()
    game.dice = DiceRoller(rng=Faces(1))                  # a natural 1 misses
    target = creature("villager")
    res = game.attack_creature(target, guaranteed=True)
    assert not res["hit"] and target["health"] == 100
    assert res["ac"] == ac.of(target)


def test_a_higher_armour_class_needs_a_higher_roll():
    c = Character()
    low = combat.attack_odds(c, creature("hen"))
    high = combat.attack_odds(c, creature("bear"))
    assert high["ac"] > low["ac"] and high["hit_target"] > low["hit_target"]


def test_a_miss_still_trains_the_weapon_a_little():
    game = _game()
    c = game.character
    game.dice = DiceRoller(rng=Faces(1))
    skill = combat.player_attack(c, creature("hen"), dice=game.dice)["skill"]
    before = (c.skill(skill), c._skill_xp.get(skill, 0.0))
    game.dice = DiceRoller(rng=Faces(1))
    res = game.attack_creature(creature("hen"))
    assert not res["hit"]
    assert (c.skill(skill), c._skill_xp.get(skill, 0.0)) > before


# --------------------------------------------------------- blows on the player
def test_the_attackers_bonus_decides_a_blow_on_the_player():
    c = Character()
    # AC 10: d20 + 0 needs a 10, d20 + 8 needs a 2. A 9 misses one, hits the other.
    weak = combat.resolve_incoming(c, 10.0, dice=DiceRoller(rng=Faces(9)), attack_bonus=0)
    strong = combat.resolve_incoming(c, 10.0, dice=DiceRoller(rng=Faces(9)), attack_bonus=8)
    assert weak.get("deflected") and weak["final"] == 0.0 and not strong.get("deflected")
    assert weak["defence_roll"]["target"] == 10 and strong["defence_roll"]["target"] == 2


def test_armour_class_makes_a_block_easier():
    shield = items.get("iron_shield")
    bare = blocking.block_save(100, 30, 40, shield=shield, dice=DiceRoller(rng=Faces(20)),
                               armour_class=10)
    plated = blocking.block_save(100, 30, 40, shield=shield, dice=DiceRoller(rng=Faces(20)),
                                 armour_class=20)
    assert plated["block_roll"]["target"] < bare["block_roll"]["target"]


# ---------------------------------------------------------- NPCs among themselves
def test_npcs_roll_against_each_others_armour_class_and_say_so():
    from ..npc_magic import NpcMagic
    floated = []

    boxes = []

    class Session:
        game = SimpleNamespace(dice=None)
        rng = Faces(*([10] * 6))                # every d20 lands a 10

        def attack_outcome(self, who, hit, crit=False):
            floated.append((who, hit))

        def show_roll_box(self, who, result, **kw):
            boxes.append((who, result["roll_result"], kw.get("kind")))

        def side_of(self, who):
            return "ally"

        def gore_npc_hit(self, *a):
            pass

    session = Session()
    magic = NpcMagic(session)
    wolf = SimpleNamespace(properties=creature("wolf"))
    plated = SimpleNamespace(properties=creature("guard", armour_class=30))
    bare = SimpleNamespace(properties=creature("hen", armour_class=5))
    assert magic.damage_filter(plated, 10, wolf) == 0      # needs a 20: a miss
    assert magic.damage_filter(bare, 10, wolf) == 10       # needs a 2: a hit
    assert floated == [(wolf, False), (wolf, True)]
    # Each roll shows in a box over the attacker, as an NPC fight.
    assert boxes == [(wolf, 10, "npc"), (wolf, 10, "npc")]
    # Magic is not turned by armour.
    assert magic.damage_filter(plated, 10, wolf, damage_kind="fire") == 10


def test_hit_and_miss_float_over_the_attacker(qt_app):
    from .test_cast_controls import _Logic, _Thing
    from ..runtime import MiniwindSession, HIT_TEXT, MISS_TEXT
    s = MiniwindSession(_Logic(), cfg={})
    wolf = _Thing("Wolf", (10.0, 0.0, 10.0))
    s._player_pos = lambda: [0.0, 0.0, 0.0]
    s.attack_outcome(wolf, True)
    assert s.floats[id(wolf)][1] == HIT_TEXT
    s.attack_outcome(wolf, False)
    assert s.floats[id(wolf)][1] == MISS_TEXT


def test_wolves_wear_the_wolf_heads(qt_app):
    """A wolf -- spawned (npc_role) or placed by hand (creature_role only) --
    wears wolf01 / wolf02, dealt evenly, never a human face."""
    from .test_cast_controls import _Logic, _Thing
    from ..runtime import MiniwindSession
    from ..rpg import heads
    assert heads.animal_heads("wolf") == ["wolf01", "wolf02"]
    spawner = _Thing("Spawn_wolf", (0, 0, 0), type="creaturespawn", creature_role="wolf",
                     count=4, faction="wildlife")
    placed = _Thing("Wolf", (300, 0, 0), type="creature", creature_role="wolf", health=40)
    s = MiniwindSession(_Logic([spawner, placed]), cfg={})
    s.spawn_creature_points()
    s._assign_npc_heads()
    wolves = [t for t in s.logic.things
              if (t.properties.get("npc_role") or t.properties.get("creature_role")) == "wolf"
              and t.properties.get("type") != "creaturespawn"]
    worn = [t.properties["head"] for t in wolves]
    assert len(worn) == 5 and set(worn) <= {"wolf01", "wolf02"}
    assert {"wolf01", "wolf02"} <= set(worn)
