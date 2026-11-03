"""Shields make real saves, reduce real damage, and keep AI dice off the HUD."""

import random
from types import SimpleNamespace

import pytest

from game.diceroll import DiceRoller, roll_check
from game.held_weapons import HeldWeapons
from game.multiplayer.bots import PartyBots
from game.rpg import blocking, combat, equipment, items
from game.rpg.dialogue import DictStore
from game.rpg.game_state import GameState
from game.tests.test_multiplayer_bots import companions, think_until
from game.tests.test_multiplayer_integration import coop_game  # noqa: F401


class Faces(random.Random):
    def __init__(self, *faces):
        super().__init__(0)
        self.faces = iter(faces)

    def randint(self, low, high):
        face = next(self.faces)
        assert low <= face <= high
        return face


def fighter():
    return GameState.new_game(DictStore(), "Fighter", "imperial", "warrior", rng=random.Random(0))


def guard(**extra):
    return {"name": "Shield Guard", "type": "npc", "health": 500,
            "equipped_weapon": "iron_longsword", "offhand_weapon": "iron_shield",
            "_shield_blocking": True, "block_skill": 50, "endurance": 50,
            **extra}


def test_successful_character_save_mitigates_damage_and_failed_save_does_not(monkeypatch):
    monkeypatch.setattr(equipment, "deflect_chance", lambda _: 0)
    failed = combat.resolve_incoming(fighter().character, 100, blocking=True,
                                     dice=DiceRoller(rng=Faces(1)))
    saved = combat.resolve_incoming(fighter().character, 100, blocking=True,
                                    dice=DiceRoller(rng=Faces(20)))
    assert failed["blocked"] == 0 and not failed["block_roll"]["success"]
    assert saved["blocked"] > 0 and saved["block_roll"]["success"]
    assert saved["block_roll"]["dice_notation"] == "1d20"
    assert saved["final"] < failed["final"]


def test_block_skill_and_fatigue_change_the_saving_throw_odds():
    shield = items.get("iron_shield")
    low = blocking.block_save(100, 10, 40, shield=shield, dice=DiceRoller(rng=Faces(20)))
    high = blocking.block_save(100, 90, 40, shield=shield, dice=DiceRoller(rng=Faces(20)))
    tired = blocking.block_save(100, 90, 40, 0.1, shield=shield,
                                dice=DiceRoller(rng=Faces(20)))
    assert high["block_roll"]["target"] < low["block_roll"]["target"]
    assert tired["block_roll"]["target"] > high["block_roll"]["target"]


@pytest.mark.parametrize("extra", [{"_shield_blocking": False}, {"dead": True},
    {"offhand_weapon": "iron_dagger"}, {"equipped_weapon": "short_bow"},
    {"hand_spells": {"off": "flare"}}, {"_torch_lit": "torch"}, {"_stamina": 0}])
def test_npc_needs_a_raised_available_shield_to_attempt_a_save(extra):
    dice = DiceRoller(rng=Faces())
    assert blocking.npc_block(guard(**extra), 50, dice=dice)["damage"] == 50
    assert not dice.roll_history


def test_magic_fire_and_zero_damage_do_not_roll_shield_saves():
    dice = DiceRoller(rng=Faces())
    for kind in ("magic", "fire", "frost", "shock"):
        assert blocking.npc_block(guard(), 50, damage_kind=kind, dice=dice)["damage"] == 50
    assert blocking.npc_block(guard(), 0, dice=dice)["damage"] == 0


def test_player_hit_tests_the_npc_shield_and_applies_the_saved_damage():
    outcomes = []
    for face in (1, 20):
        game = fighter()
        game.dice = DiceRoller(rng=Faces(1, face))  # failed critical, then the defender's save
        target = guard()
        result = game.attack_creature(target, guaranteed=True)
        assert target["health"] == 500 - round(result["damage"])
        assert result["block_roll"]["success"] == (face == 20)
        outcomes.append(result["damage"])
    assert outcomes[1] < outcomes[0]


def test_npc_damage_filter_saves_then_applies_wards():
    from game.npc_magic import NpcMagic
    from game.tests.test_npc_magic import _Session

    game = fighter()
    game.dice = DiceRoller(rng=Faces(20, 1))
    session = _Session(game=game, rng=game.rng)
    magic = NpcMagic(session)
    actor = SimpleNamespace(properties=guard())
    saved = magic.damage_filter(actor, 100)
    failed = magic.damage_filter(actor, 100)
    assert saved < failed == 100
    assert magic.damage_filter(actor, 100, damage_kind="fire") == 100


def test_npc_equips_carried_shield_and_visibly_raises_it_between_attacks():
    props = guard(offhand_weapon="", inventory=[items.make("iron_shield")],
                  triggered=False, awake=True)
    blocking.ready_npc_shield(props)
    actor = SimpleNamespace(pos=[0, 64, 0], properties=props)
    foe = SimpleNamespace(pos=[0, 64, 120], properties={})
    props["_aggro_target"] = id(foe)
    session = SimpleNamespace(_actors=[actor, foe], _player_pos=lambda: [0, 0, 0],
                              _archery_clock=0.0, rng=random.Random(0))
    held = HeldWeapons(session)
    held.update()
    assert not props["_shield_blocking"]  # it must first react
    session._archery_clock = 1
    held.update()
    assert props["_shield_blocking"]
    shield = next(entry for entry in held.overhead() if entry[2] == "iron_shield")
    assert shield[6] > 0
    props["is_shooting"] = True
    held.update()
    assert not props["_shield_blocking"]
    props["is_shooting"] = False
    props["_active_weapon"] = "short_bow"
    session._archery_clock = 2
    held.update()
    assert not props["_shield_blocking"]


def test_companion_holds_its_shield_without_waiting_for_its_own_attack(coop_game):
    from game.tests.test_companion_defense import enemy_near

    coop = coop_game.logic.game_session.coop
    human, bot, *others = companions(coop)
    for member in (human, *others):
        member.physics.pos.x -= 350
        member.physics.pos.z -= 250
    bot.session.nav = None
    enemy_near(coop, bot, offset=170)
    brain = PartyBots(coop)
    think_until(brain, lambda: "block" in bot.frame.held)
    assert equipment.shield(bot.session.game.character) is not None
    assert bot.session._attack_cooldown == 0


def test_companion_save_changes_real_health_and_logs_without_animating(coop_game, monkeypatch):
    coop = coop_game.logic.game_session.coop
    human, bot, *_ = companions(coop)
    c = bot.session.game.character
    monkeypatch.setattr(equipment, "deflect_chance", lambda _: 0)
    sentinel = {"result": {"label": "Player's own roll"}, "elapsed": 0.2}
    human.session.dice_animation = sentinel
    bot.session.toggle_block(True)
    before = c.health
    c.health = c.max_health
    bot.session.game.dice.rng = Faces(20)
    reduced = coop.damage(bot.player_id, 25)
    assert reduced < 25 and c.health == c.max_health - reduced
    assert human.session.dice_animation is sentinel and bot.session.dice_animation is None
    assert "saving throw" in human.session.roll_log[-1]["text"]
    assert bot.profile["name"] in human.session.roll_log[-1]["text"]
    c.health = before


def test_only_human_rolls_animate_and_bot_attack_rolls_enter_the_log(coop_game, monkeypatch):
    coop = coop_game.logic.game_session.coop
    human, bot, *_ = companions(coop)
    monkeypatch.setattr(human.session, "_visualise_dice_rolls_enabled", lambda: True)
    human.session.dice_animation = None
    own = roll_check(human.session.game.dice, 0.5, "Human attack", source="combat.hit")
    animation = human.session.dice_animation
    assert animation["result"] is own
    roll_check(bot.session.game.dice, 0.5, "Companion attack", source="combat.hit")
    assert bot.session.dice_animation is None
    assert human.session.dice_animation is animation and not animation.get("followups")
    assert "Companion attack" in human.session.roll_log[-1]["text"]
    roll_check(human.session.game.dice, 0.5, "Guard's shield save", source="combat.block",
               context={"quiet": True, "npc": True})
    assert human.session.dice_animation is animation and not animation.get("followups")
    assert "Guard's shield save" in human.session.roll_log[-1]["text"]
    from game.rpg import magic
    caster = SimpleNamespace(properties={"name": "Guard", "magic_skill": 100})
    human.session.game.dice.rng = Faces(20)
    assert not human.session.npc_magic._fizzles(caster, magic.get("flare"))
    assert human.session.dice_animation is animation and not animation.get("followups")
    assert "Guard casts" in human.session.roll_log[-1]["text"]
    snapshot = coop.snapshot()
    assert snapshot["players"][bot.player_id]["dice_animation"] is None
    assert snapshot["players"][human.player_id]["roll_log"][-1]["text"].startswith("Guard")
    human.session.roll_log = []
    human.session.dice_animation = None
    coop.authority = False
    try:
        coop.apply_snapshot(snapshot)
    finally:
        coop.authority = True
    assert human.session.dice_animation["result"]["label"] == "Human attack"
    assert human.session.roll_log[-1]["text"].startswith("Guard")
    assert bot.session.dice_animation is None


def test_humans_own_shield_save_animates(coop_game, monkeypatch):
    coop = coop_game.logic.game_session.coop
    human, *_ = companions(coop)
    monkeypatch.setattr(human.session, "_visualise_dice_rolls_enabled", lambda: True)
    monkeypatch.setattr(equipment, "deflect_chance", lambda _: 0)
    human.session.dice_animation = None
    human.session.toggle_block(True)
    human.session.game.dice.rng = Faces(20)
    coop.damage(human.player_id, 10)
    result = human.session.dice_animation["result"]
    assert result["success"] and "shield saving throw" in result["label"]


def test_companion_reequips_its_shield_when_putting_away_a_bow(coop_game):
    coop = coop_game.logic.game_session.coop
    _, bot, *_ = companions(coop)
    c = bot.session.game.character
    assert equipment.equip(c, "short_bow")
    assert equipment.shield(c) is None
    target = SimpleNamespace(pos=[bot.physics.pos[0] + 90, bot.physics.pos[1], bot.physics.pos[2]])
    PartyBots(coop)._choose_weapon(bot, target)
    assert equipment.shield(c) is not None


def test_engine_preserves_damage_kind_and_legacy_filter_signature():
    from engine.monster_ai import MonsterAI

    ai = MonsterAI.__new__(MonsterAI)
    ai.lt = SimpleNamespace(game_session=None, io_manager=None)
    ai.monster_debug_active = False
    victim = SimpleNamespace(properties={"health": 100})
    seen = []
    try:
        MonsterAI.install_damage_filter(lambda v, d, a: d / 2)
        ai._apply_monster_damage(victim, 10, damage_kind="fire")
        assert victim.properties["health"] == 95
        def typed(victim, damage, attacker, *, damage_kind):
            seen.append(damage_kind)
            return damage
        MonsterAI.install_damage_filter(typed, damage_kinds=True)
        ai._apply_monster_damage(victim, 10, damage_kind="magic")
        assert seen == ["magic"]
        routed = []
        ai.lt.game_session = SimpleNamespace(coop=SimpleNamespace(
            damage=lambda pid, damage, kind, **kw: routed.append((pid, kind)),
        ))
        victim.properties.update(multiplayer_player=True, player_id="companion")
        ai._apply_monster_damage(victim, 10, damage_kind="fire")
        assert routed == [("companion", "fire")]
    finally:
        MonsterAI.clear_damage_filter()
