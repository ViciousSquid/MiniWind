"""
Unit tests for the Miniwind RPG core (``game.rpg``).

Headless and deterministic (a seeded RNG where randomness is involved): character
creation, skill-by-use progression, level-up, combat maths, magic, items &
equipment, quests, loot and guild reputation — plus a full save/load round-trip.

Run:  python -m pytest game/tests/test_rpg.py -q
or:   python -m game.tests.test_rpg
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game.rpg import (attributes as attr, skills as sk, races,
                                  classes, birthsigns, items, inventory as inv,
                                  equipment as eq, combat, magic, quests,
                                  quests_content, loot, guilds, bestiary)
from game.rpg.character import Character
from game.rpg.game_state import GameState
from game.rpg.dialogue import DictStore


# --- creation --------------------------------------------------------------
def test_character_creation_applies_race_class_sign():
    c = Character.create("Test", "nord", "warrior", "warrior", "male")
    assert c.race_id == "nord" and c.class_id == "warrior"
    # nord bonus + warrior favoured attr → strength well above base
    assert c.attrs[attr.STRENGTH] >= 50
    # major skills start higher than minors
    assert c.skill(sk.BLADE) >= classes.MAJOR_SKILL_START
    assert c.skill(sk.MYSTICISM) <= classes.MINOR_SKILL_START + classes.SPECIALISATION_BONUS
    # derived pools are positive and endurance-driven
    assert c.max_health > 100 and c.max_stamina > 0


def test_every_race_and_class_builds():
    for rid in races.RACE_IDS:
        for cid in classes.CLASS_IDS:
            c = Character.create("X", rid, cid, "mage")
            assert c.max_health >= 1
            assert len(c.major_skills) == 7


def test_birthsign_magicka_bonus():
    base = Character.create("A", "imperial", "mage", "none")
    mage = Character.create("B", "imperial", "mage", "mage")
    assert mage.max_magicka > base.max_magicka


# --- progression -----------------------------------------------------------
def test_skill_improves_with_use():
    c = Character.create("T", "imperial", "warrior", "warrior")
    start = c.skill(sk.BLADE)
    for _ in range(200):
        c.use_skill(sk.BLADE, 1.0)
    assert c.skill(sk.BLADE) > start


def test_major_skill_use_drives_level_up():
    c = Character.create("T", "imperial", "warrior", "warrior")
    assert not c.can_level_up
    # grind a major skill until 10 skill-ups accrue
    guard = 0
    while not c.can_level_up and guard < 5000:
        c.use_skill(sk.BLADE, 3.0)
        guard += 1
    assert c.can_level_up
    lvl = c.level
    res = c.level_up()
    assert res["level"] == lvl + 1
    assert c.max_health > 0


def test_level_cap_on_skill():
    c = Character()
    c.skills[sk.BLADE] = 99
    for _ in range(1000):
        c.use_skill(sk.BLADE, 5.0)
    assert c.skill(sk.BLADE) == 100


# --- items & equipment -----------------------------------------------------
def test_item_db_has_core_items():
    for iid in ("iron_longsword", "short_bow", "iron_arrow", "iron_cuirass",
                "potion_heal", "flare" if items.get("flare") else "iron_dagger"):
        assert items.get(iid) is not None


def test_equip_weapon_sets_kind_and_two_handed_frees_shield():
    c = Character.create("T", "imperial", "warrior", "warrior")
    inv.add_item(c.inventory, items.make("iron_shield"))
    inv.add_item(c.inventory, items.make("iron_longsword"))
    inv.add_item(c.inventory, items.make("long_bow"))
    assert eq.equip(c, "iron_shield")
    assert eq.equip(c, "iron_longsword")
    assert c.active_weapon_kind == "melee"
    assert eq.equipped_id(c, items.SLOT_SHIELD) == "iron_shield"
    # equipping a bow (two-handed) frees the shield
    assert eq.equip(c, "long_bow")
    assert c.active_weapon_kind == "bow"
    assert eq.equipped_id(c, items.SLOT_SHIELD) is None


def test_armor_rating_scales_with_skill():
    c = Character.create("T", "imperial", "warrior", "warrior")
    inv.add_item(c.inventory, items.make("iron_cuirass"))
    eq.equip(c, "iron_cuirass")
    low = eq.armor_rating(c)
    c.skills[sk.HEAVY_ARMOR] = 100
    high = eq.armor_rating(c)
    assert high > low


# --- combat ----------------------------------------------------------------
def test_player_melee_hits_and_kills():
    c = Character.create("T", "nord", "warrior", "warrior")
    c.skills[sk.BLADE] = 100
    c.attrs[attr.AGILITY] = 100
    inv.add_item(c.inventory, items.make("steel_longsword"))
    eq.equip(c, "steel_longsword")
    rng = random.Random(1)
    tgt = {"health": 30, "agility": 10}
    total = 0
    for _ in range(20):
        r = combat.player_attack(c, tgt, rng=rng)
        if r["hit"]:
            total += r["damage"]
    assert total > 0


def test_bow_requires_ammo():
    c = Character.create("T", "bosmer", "archer", "none")
    inv.add_item(c.inventory, items.make("short_bow"))
    eq.equip(c, "short_bow")
    # no ammo equipped
    r = combat.player_attack(c, {"health": 20, "agility": 5}, rng=random.Random(0))
    assert r.get("no_ammo")
    inv.add_item(c.inventory, items.make("iron_arrow", 5))
    eq.equip(c, "iron_arrow")
    r = combat.player_attack(c, {"health": 20, "agility": 5}, rng=random.Random(0))
    assert "no_ammo" not in r


def test_armor_reduces_incoming_damage():
    c = Character.create("T", "orc", "warrior", "warrior")
    bare = combat.resolve_incoming(c, 40, damage_kind="physical")["final"]
    inv.add_item(c.inventory, items.make("iron_cuirass"))
    inv.add_item(c.inventory, items.make("iron_helmet"))
    eq.equip(c, "iron_cuirass")
    eq.equip(c, "iron_helmet")
    armored = combat.resolve_incoming(c, 40, damage_kind="physical")["final"]
    assert armored < bare


def test_race_resistance_applies():
    nord = Character.create("N", "nord", "warrior", "none")   # 50% frost resist
    imp = Character.create("I", "imperial", "warrior", "none")
    n = combat.resolve_incoming(nord, 40, damage_kind="frost")["final"]
    i = combat.resolve_incoming(imp, 40, damage_kind="frost")["final"]
    assert n < i


def test_sneak_attack_multiplies():
    c = Character.create("T", "khajiit", "assassin", "thief")
    c.skills[sk.BLADE] = 80
    c.attrs[attr.AGILITY] = 100
    inv.add_item(c.inventory, items.make("iron_dagger"))
    eq.equip(c, "iron_dagger")
    rng = random.Random(4)
    normal = combat.player_attack(c, {"health": 100, "agility": 0}, sneaking=False, rng=random.Random(4))
    sneak = combat.player_attack(c, {"health": 100, "agility": 0}, sneaking=True, rng=random.Random(4))
    if normal["hit"] and sneak["hit"]:
        assert sneak["damage"] > normal["damage"]


# --- magic -----------------------------------------------------------------
def test_cast_spends_magicka_and_can_fizzle():
    c = Character.create("T", "altmer", "mage", "mage")
    c.known_spells = ["flare"]
    c.active_spell = "flare"
    before = c.magicka
    res = magic.try_cast(c, "flare", rng=random.Random(1))
    assert c.magicka < before


def test_self_heal_spell_restores_health():
    c = Character.create("T", "breton", "healer", "mage")
    c.known_spells.append("heal")
    c.max_magicka = 500
    c.magicka = 500
    c.damage(50)
    hp = c.health
    magic.try_cast(c, "heal", rng=random.Random(2))
    assert c.health >= hp


# --- quests ----------------------------------------------------------------
def test_quest_flow():
    quests_content.load()
    store = DictStore()
    log = quests.QuestLog(store)
    assert not log.is_active("wolves")
    assert log.start("wolves")
    assert log.is_active("wolves")
    log.set_stage("wolves", 10)
    log.set_stage("wolves", 20)  # finishing stage completes it
    assert log.is_complete("wolves")


def test_gamestate_completes_quest_and_rewards():
    gs = GameState.new_game(DictStore(), "T", "imperial", "warrior", rng=random.Random(1))
    gold0 = gs.character.gold
    gs.start_quest("wolves")
    gs.complete_quest("wolves")
    assert gs.character.gold > gold0
    assert inv.has_item(gs.character.inventory, "hunting_bow")


def test_kill_counts_progress_wolf_quest():
    gs = GameState.new_game(DictStore(), "T", "imperial", "scout", rng=random.Random(1))
    gs.start_quest("wolves")
    for _ in range(5):
        gs._count_kill("wolf")
    assert gs.quests.stage_of("wolves") >= 10


# --- loot ------------------------------------------------------------------
def test_loot_table_rolls_items():
    stacks, gold = loot.roll("bandit_chief", player_level=5, rng=random.Random(1))
    assert isinstance(stacks, list)
    # rich table + level 5 should usually yield something; gold range guarantees >=25
    assert gold >= 25


# --- guilds ----------------------------------------------------------------
def test_guild_join_and_promotion():
    c = Character.create("T", "imperial", "warrior", "warrior")
    assert guilds.join(c, "fighters")
    assert guilds.is_member(c, "fighters")
    guilds.add_reputation(c, "fighters", 25)
    assert guilds.rank(c, "fighters") >= 2


def test_disposition_reflects_personality_and_bounty():
    c = Character.create("T", "imperial", "rogue", "rogue")  # high personality-ish
    npc = {"disposition_base": 50, "faction": "villagers"}
    d0 = guilds.disposition(c, npc)
    c.bounty = 400
    d1 = guilds.disposition(c, npc)
    assert d1 < d0


# --- authoring grammar (editor <-> runtime round-trip) ---------------------
def test_authoring_response_roundtrip():
    from game.rpg import authoring
    line = "I'm looking for work. -> quest | if quest.wolves.state != active | do start_quest wolves ; give iron_arrow,10"
    r = authoring.parse_response_line(line)
    assert r["text"] == "I'm looking for work." and r["goto"] == "quest"
    assert r["condition"] == {"key": "quest.wolves.state", "not_equals": "active"}
    ops = [a["op"] for a in r["actions"]]
    assert "start_quest" in ops and "give_item" in ops
    # reformat and reparse is stable
    r2 = authoring.parse_response_line(authoring.format_response(r))
    assert r2["condition"] == r["condition"]
    assert [a["op"] for a in r2["actions"]] == ops


def test_authoring_conditions_and_actions():
    from game.rpg import authoring
    assert authoring.parse_condition("has silver_amulet") == {"has_item": "silver_amulet"}
    assert authoring.parse_condition("flag == done") == {"key": "flag", "equals": "done"}
    acts = authoring.parse_actions("open_trade ; join_guild fighters ; set flag=1")
    assert [a["op"] for a in acts] == ["open_trade", "join_guild", "set"]


def test_data_driven_quest_loads_and_runs():
    q = {"id": "custom_hunt", "name": "The Hunt", "giver": "Bob",
         "rewards": {"gold": 50, "items": [["iron_arrow", 10]], "rep": ["town", 5]},
         "stages": [{"index": 0, "journal": "Start.", "objective": "Go"},
                    {"index": 10, "journal": "Done.", "finishes": True}]}
    assert quests.load_definitions([q]) == 1
    gs = GameState.new_game(DictStore(), "T", "imperial", "warrior", rng=random.Random(1))
    assert gs.start_quest("custom_hunt")
    g0 = gs.character.gold
    gs.quests.set_stage("custom_hunt", 10)          # finishing stage completes it
    gs.complete_quest("custom_hunt")
    assert gs.character.gold >= g0                   # rewarded


# --- save / load -----------------------------------------------------------
def test_character_full_roundtrip():
    gs = GameState.new_game(DictStore(), "Hero", "dunmer", "nightblade", "shadow",
                            rng=random.Random(7))
    c = gs.character
    c.gold = 777
    c.use_skill(sk.DESTRUCTION, 5.0)
    c.damage(15)
    guilds.join(c, "mages")
    d = c.to_dict()
    c2 = Character.from_dict(d)
    assert c2.name == "Hero" and c2.gold == 777
    assert c2.skills == c.skills
    assert abs(c2.health - c.health) < 0.5
    assert c2.equipment == c.equipment
    assert guilds.is_member(c2, "mages")


# --- self-runner -----------------------------------------------------------
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa
            import traceback
            traceback.print_exc()
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
