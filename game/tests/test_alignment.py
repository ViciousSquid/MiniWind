"""
Alignment: deeds move the player and every NPC between Villainous and
Saintly, and it changes how the world treats them.

Run:  python -m pytest game/tests/test_alignment.py -q
"""

from __future__ import annotations

import configparser

import pytest

from .. import runtime
from ..rpg import alignment, disposition, magic
from ..rpg.character import Character
from .test_ember_tome import _FakePlayer, _FakeThing, _session


def test_tiers_and_diminishing_returns():
    assert alignment.tier(90) == "Saintly" and alignment.tier(-90) == "Villainous"
    assert alignment.tier(0) == "Neutral"
    near_middle = alignment.shift(0, 10) - 0
    near_top = alignment.shift(80, 10) - 80
    assert near_middle == 10 and 0 < near_top < near_middle
    # A single atrocity still costs a saint dearly.
    assert alignment.shift(90, -20) <= 70


def test_saving_a_village_lifts_you_and_massacring_it_sinks_you():
    hero, butcher = Character(), Character()
    for _ in range(20):
        alignment.player_deed(hero, "slay_brigand")
        alignment.player_deed(hero, "defend")
    for _ in range(8):
        alignment.player_deed(butcher, "murder")
    assert alignment.tier(hero.alignment) in ("Good", "Saintly")
    assert alignment.tier(butcher.alignment) in ("Evil", "Villainous")
    assert hero.alignment_log[-1]["text"] == "defended the innocent"
    restored = Character.from_dict(hero.to_dict())
    assert restored.alignment == pytest.approx(hero.alignment, abs=0.01)
    assert len(restored.alignment_log) == len(hero.alignment_log)


def test_what_a_killing_counts_as():
    assert alignment.kill_deed({"npc_role": "bandit", "faction": "bandits"},
                               hostile_to_killer=True) == "slay_brigand"
    assert alignment.kill_deed({"npc_role": "farmer"}, hostile_to_killer=False) == "murder"
    assert alignment.kill_deed({"npc_role": "guard"}, hostile_to_killer=True,
                               crime=True) == "slay_guard"
    assert alignment.kill_deed({"npc_role": "sheep"}, hostile_to_killer=False) == "slay_animal"
    assert alignment.kill_deed({"npc_role": "skeleton", "monster_type": "undead"},
                               hostile_to_killer=True) == "slay_monster"


def test_npcs_have_alignments_and_can_fall_from_grace():
    guard = {"npc_role": "guard", "faction": "guards"}
    assert alignment.of_npc(guard) == 35
    fell = False
    for _ in range(10):
        _v, now = alignment.npc_deed(guard, "murder")
        fell = fell or now
    assert fell and alignment.tier(guard["alignment"]) in ("Evil", "Villainous")
    bandit = {"npc_role": "bandit", "faction": "bandits"}
    for _ in range(5):
        assert alignment.npc_deed(bandit, "murder")[1] is False     # already an outlaw


def test_consequences():
    good, evil = 80.0, -80.0
    assert alignment.bounty_mult(good) < 1 < alignment.bounty_mult(evil)
    assert alignment.magic_power(good, "defensive") > 1
    assert alignment.magic_power(evil, "offensive") > 1
    assert alignment.magic_power(good, "offensive") == 1
    assert alignment.affinity(good, 35) > 0 > alignment.affinity(evil, 35)
    assert alignment.affinity(evil, -45) > 0
    assert alignment.kinship(evil) and not alignment.kinship(good)
    assert alignment.heartens(good) > 0 > alignment.heartens(evil)
    assert alignment.consequences(good) and alignment.consequences(evil)


def test_a_good_player_heals_harder_and_an_evil_one_strikes_harder():
    c = Character.create("T", "breton", "mage", "none")
    base_heal = magic.for_caster(c, "heal_minor").effects[0]["magnitude"]
    base_bolt = magic.for_caster(c, "flare").damage
    c.alignment = 90
    assert magic.for_caster(c, "heal_minor").effects[0]["magnitude"] > base_heal
    assert magic.for_caster(c, "flare").damage == base_bolt
    c.alignment = -90
    assert magic.for_caster(c, "flare").damage > base_bolt


def test_like_warms_to_like():
    from ..rpg.dialogue import DictStore
    store = DictStore()
    farmer = {"name": "Tom", "npc_role": "farmer"}
    c = Character()
    neutral = disposition.of(c, farmer, store)
    c.alignment = 90
    assert disposition.of(c, farmer, store) > neutral
    c.alignment = -90
    assert disposition.of(c, farmer, store) < neutral


@pytest.fixture
def config():
    config = configparser.ConfigParser()
    previous = runtime._editor_config
    runtime.set_editor_config(config)
    yield config
    runtime.set_editor_config(previous)


def _npc(props, pos=(100.0, 0.0, 0.0)):
    base = {"type": "npc", "name": "Someone"}
    base.update(props)
    return _FakeThing(list(pos), base)


def test_the_player_is_judged_by_who_they_kill(config):
    farmer = _npc({"name": "Tom", "npc_role": "farmer"})
    bandit = _npc({"name": "Brigand", "npc_role": "bandit", "faction": "bandits",
                   "aggression": "hostile"}, pos=(150.0, 0.0, 0.0))
    s = _session([farmer, bandit], _FakePlayer([0, 0, 0]))
    s._alignment_kill(None, bandit, by_player=True, crime=False)
    after_brigand = s.game.character.alignment
    assert after_brigand > 0
    # The farmer was standing right there: that was defending the innocent too.
    assert any(e["deed"] == "defend" for e in s.game.character.alignment_log)
    s._alignment_kill(None, farmer, by_player=True, crime=True)
    assert s.game.character.alignment < after_brigand


def test_an_npc_murderer_turns_outlaw(config):
    guard = _npc({"name": "Bad Guard", "npc_role": "guard", "faction": "guards"})
    s = _session([guard], _FakePlayer([0, 0, 0]))
    for i in range(10):
        victim = _npc({"name": f"Villager {i}", "npc_role": "villager",
                       "faction": "villagers"})
        s._alignment_kill(guard, victim, by_player=False, crime=False)
    assert guard.properties["faction"] == "bandits"
    assert guard.properties["aggression"] == "hostile"


def test_the_watch_charges_the_wicked_more(config):
    from types import SimpleNamespace
    s = _session([], _FakePlayer([0, 0, 0]))
    event = SimpleNamespace(data={"law_region": "vale"}, kind="theft", id=1, pos=(0, 0, 0),
                            actor="player", target="", actor_name="You", target_name="")
    s.game.character.alignment = -90
    s._sim_on_bounty(100, event, "witness")
    assert s.law.bounty("vale") == 150


def test_a_reputation_is_mentioned_on_meeting(config):
    farmer = _npc({"name": "Tom", "npc_role": "farmer"})
    s = _session([farmer], _FakePlayer([0, 0, 0]))
    tree = {"start": "g", "nodes": {"g": {"text": "Hello.", "responses": []}}}
    assert s._with_reputation(tree, farmer) is tree             # unremarkable
    s.game.character.alignment = -90
    told = s._with_reputation(tree, farmer)["nodes"]["g"]["text"]
    assert told.endswith("Hello.") and told != "Hello."
