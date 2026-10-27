"""
Insight into the rules and the people: explained rolls and NPC thoughts.

Every chance check says what it was for, what it needed and whether it passed
("Roll to hit Bandit: 7 (need 14+) — FAILED"), and an NPC near the player shows
a thought whenever its reason for what it is doing changes.

Run:  python -m pytest game/tests/test_explained_rolls_and_thoughts.py -q
"""

from __future__ import annotations

import configparser
import random

import pytest

from .. import diceroll, mental_state, runtime
from ..diceroll import CHECK_DIE, check_target, check_threshold, describe_roll, roll_check
from .test_ember_tome import _FakePlayer, _FakeThing, _session


# ---------------------------------------------------------------- the rolls
def test_a_check_needs_the_top_faces_of_the_die():
    for chance in (0.05, 0.25, 0.5, 0.75, 0.95):
        winning_faces = CHECK_DIE - check_target(chance) + 1
        assert winning_faces == check_threshold(chance)
    assert check_target(0.0) == CHECK_DIE + 1       # impossible: no face wins
    assert check_target(1.0) == 1


def test_a_check_passes_exactly_when_it_meets_its_target():
    roller = diceroll.DiceRoller(rng=random.Random(7))
    for _ in range(200):
        result = roll_check(roller, 0.35, "Roll to hit", why="Blade 30")
        assert result["target"] == check_target(0.35)
        assert result["success"] == (result["roll_result"] >= result["target"])
        assert result["label"] == "Roll to hit"
        assert result["why"] == "Blade 30"


def test_a_roll_is_described_in_the_players_terms():
    assert describe_roll({"label": "Roll to hit", "roll_result": 7, "target": 14,
                          "success": False}) == "Roll to hit: 7 (need 14+) — FAILED"
    assert describe_roll({"label": "Roll to cast Flare", "roll_result": 15,
                          "target": 9, "success": True}) == \
        "Roll to cast Flare: 15 (need 9+) — SUCCESS"
    assert describe_roll({"label": "Roll for how much gold",
                          "roll_result": 4}) == "Roll for how much gold: 4"


def test_an_attack_roll_names_its_target_and_its_odds():
    from ..rpg import combat
    from ..rpg.character import Character

    roller = diceroll.DiceRoller(rng=random.Random(3))
    seen = []
    roller.add_roll_listener(lambda result, source, ctx: seen.append((source, result)))
    res = combat.player_attack(Character(), {"name": "bandit", "display_name": "Bandit",
                                             "agility": 30, "health": 30},
                               dice=roller)
    source, hit = seen[0]
    assert source == "combat.hit"
    assert hit["label"] == "Roll to hit Bandit"
    assert "vs their Agility 30" in hit["why"]
    assert hit["success"] == res["hit"]
    if res["hit"]:
        source, crit = seen[1]
        assert source == "combat.critical"
        assert crit["success"] == res["crit"]


@pytest.fixture
def config():
    config = configparser.ConfigParser()
    previous = runtime._editor_config
    runtime.set_editor_config(config)
    yield config
    runtime.set_editor_config(previous)


def test_a_labelled_roll_goes_in_the_roll_log(config):
    s = _session([], _FakePlayer([0, 0, 0]))
    roll_check(s.game.dice, 0.5, "Roll to hit Wolf")
    s.game.request_roll("1d6", source="test")          # unlabelled: not logged
    assert len(s.roll_log) == 1
    assert s.roll_log[0]["text"].startswith("Roll to hit Wolf: ")
    assert s.game.log[-2].startswith("Roll to hit Wolf: ")


def test_rolls_made_together_are_shown_together(config):
    config.read_dict({"GAME": {"visualise_dice_rolls": "True"}})
    s = _session([], _FakePlayer([0, 0, 0]))
    first = roll_check(s.game.dice, 0.5, "Roll to hit Wolf")
    second = roll_check(s.game.dice, 0.1, "Roll for a critical hit")
    assert s.dice_animation["result"] is first
    assert s.dice_animation["followups"] == [second]
    s._tick_dice_animation(0.1)
    third = roll_check(s.game.dice, 0.5, "Roll to hit Wolf")
    assert s.dice_animation["result"] is third      # a later roll replaces it


# ------------------------------------------------------------- the thoughts
def test_a_thought_says_why_in_the_decisions_own_words():
    key, text = mental_state.thought({
        "name": "Ann", "sched_state": "REPORT", "_sim_intent": "REPORT",
        "_sim_reason": "Somebody must tell the watch what Rufus did"})
    assert key.startswith("intent:REPORT")
    assert text == "Somebody must tell the watch what Rufus did."


def test_a_thought_keeps_the_working_for_the_inspector():
    _key, text = mental_state.thought({
        "name": "Bram", "sched_state": "FLEE", "_flee": True, "_sim_intent": "FLEE",
        "_sim_reason": "Rufus attacked me and I am no fighter (courage 0.12)"})
    assert text == "Rufus attacked me and I am no fighter."


def test_needs_and_routine_have_thoughts_and_idling_has_none():
    assert mental_state.thought({"name": "F", "sched_state": "GOING_HOME",
                                 "_need_reason": "hungry"})[0] == "hungry"
    assert mental_state.thought({"name": "F", "sched_state": "GOING_TO_WORK"})[1]
    assert mental_state.thought({"name": "F", "sched_state": "WANDER"})[1] == ""
    assert mental_state.thought({"name": "F", "dead": True}) == ("", "")


def test_a_combat_thought_names_the_enemy():
    _key, text = mental_state.thought({"name": "Guard", "sched_state": "COMBAT",
                                       "_aggro_target": 1}, "Bandit")
    assert "Bandit" in text


def test_the_same_actor_puts_the_same_thought_the_same_way():
    props = {"name": "Farmer Tom", "sched_state": "GOING_TO_WORK"}
    assert mental_state.thought(props) == mental_state.thought(dict(props))


def _npc(props):
    base = {"type": "npc", "name": "Tom", "sched_state": "WORKING"}
    base.update(props)
    return _FakeThing([100.0, 0.0, 0.0], base)


def test_an_npc_thinks_aloud_when_its_reason_changes(config):
    npc = _npc({})
    s = _session([npc], _FakePlayer([0, 0, 0]))
    s._update_thoughts()
    assert s.live_thoughts() == []                 # first seen at work: quiet
    npc.properties["sched_state"] = "GOING_HOME"
    npc.properties["_need_reason"] = "hungry"
    s._update_thoughts()
    [(thing, text, _left)] = s.live_thoughts()
    assert thing is npc and text in mental_state._THOUGHTS["hungry"]


def test_an_npc_first_seen_in_trouble_says_so_at_once(config):
    npc = _npc({"sched_state": "FLEE", "_flee": True})
    s = _session([npc], _FakePlayer([0, 0, 0]))
    s._update_thoughts()
    assert len(s.live_thoughts()) == 1


def test_thoughts_can_be_turned_off(config):
    config.read_dict({"GAME": {"show_npc_thoughts": "False"}})
    npc = _npc({"sched_state": "FLEE", "_flee": True})
    s = _session([npc], _FakePlayer([0, 0, 0]))
    s._update_thoughts()
    assert s.live_thoughts() == []


# ----------------------------------------------------- the other side's dice
def _armoured():
    from ..rpg.character import Character
    c = Character()
    c.attrs["agility"] = 100          # Armour Class from agility, no armour needed
    return c


def test_a_blow_against_the_player_is_the_attacker_rolling_to_hit():
    from ..rpg import combat, equipment as eq
    c = _armoured()
    deflect = eq.deflect_chance(c)
    assert deflect > 0
    roller = diceroll.DiceRoller(rng=random.Random(5))
    seen = []
    roller.add_roll_listener(lambda result, source, ctx: seen.append((result, ctx)))
    for _ in range(60):
        res = combat.resolve_incoming(c, 10.0, dice=roller, attacker="Bandit",
                                      rng=random.Random(1))
        roll, ctx = seen[-1]
        assert roll["label"] == "Bandit rolls to hit you"
        assert roll["target"] == check_target(1.0 - deflect)
        assert ctx["quiet"] and ctx["against_player"]
        assert res.get("deflected", False) == (not roll["success"])


def test_with_no_armour_class_to_beat_nothing_is_rolled():
    from ..rpg import combat
    from ..rpg.character import Character
    roller = diceroll.DiceRoller(rng=random.Random(5))
    seen = []
    roller.add_roll_listener(lambda *a: seen.append(a))
    c = Character()
    c.attrs["agility"] = 40
    combat.resolve_incoming(c, 10.0, dice=roller, attacker="Wolf")
    assert seen == []


def test_their_rolls_go_in_the_log_coloured_for_the_player_not_the_panel(config):
    config.read_dict({"GAME": {"visualise_dice_rolls": "True"}})
    s = _session([], _FakePlayer([0, 0, 0]))
    s.game.dice.request_roll("1d20", target=30, source="combat.incoming",
                             context={"label": "Bandit rolls to hit you", "quiet": True,
                                      "against_player": True})
    assert s.dice_animation is None
    assert s.roll_log[-1]["success"] is True        # they missed: good news


# ------------------------------------------------------ odds before acting
def test_the_odds_shown_are_the_odds_rolled():
    from ..rpg import combat
    from ..rpg.character import Character
    c = Character()
    target = {"agility": 30}
    odds = combat.attack_odds(c, target)
    fatigue = c.stamina / c.max_stamina
    assert odds["hit_chance"] == combat.hit_chance(c, c.skill("blade"), 30, fatigue)
    assert odds["hit_target"] == check_target(odds["hit_chance"])
    assert odds["crit_target"] == check_target(combat.critical_chance(c))


@pytest.mark.qt
def test_the_nameplate_says_what_the_player_needs(qt_app):
    from ..rpg.character import Character
    from ..ui import hud
    c = Character()
    line = hud._target_odds(c, {"agility": 30})
    assert line.startswith("Sure hit") and "Critical: need" in line
    c.active_weapon_kind = "bow"
    assert hud._target_odds(c, {"agility": 30}).startswith("To hit: need ")


# ------------------------------------------------------------ conversations
def _fact(**kw):
    base = {"kind": "theft", "actor": "player", "actor_name": "Rufus",
            "target": "bram", "target_name": "Bram", "item": "bread",
            "source": "told", "certainty": 0.8, "e": 4}
    base.update(kw)
    return base


def test_a_rumour_is_passed_on_in_words():
    from .. import chatter
    opener, reply = chatter.gossip_lines(_fact(), "Ann", "Tom")
    assert "Rufus stole bread from Bram" in opener or "rufus stole bread" in opener.lower()
    assert reply in chatter._REPLIES["property"]
    _o, reply = chatter.gossip_lines(_fact(kind="death"), "Ann", "Tom")
    assert reply in chatter._REPLIES["grave"]


def test_gossip_is_said_aloud_with_a_reply(config):
    ann = _npc({"name": "Ann"})
    tom = _npc({"name": "Tom"})
    s = _session([ann, tom], _FakePlayer([0, 0, 0]))
    s._on_gossip(ann, tom, _fact())
    s.__dict__["_bark_queue"] = [(0.0, t, x) for _at, t, x in s._bark_queue]  # due now
    said = {id(thing): text for thing, text, _left in s.live_barks()}
    assert "Bram" in said[id(ann)]
    assert id(tom) in said


def test_small_talk_suits_the_hour():
    from .. import chatter
    opener, reply = chatter.small_talk("Ann", "Tom", 7.0)
    assert (opener, reply) in [(o.format(a="Ann", b="Tom"), r.format(a="Ann", b="Tom"))
                               for o, r in chatter._SMALL_TALK["morning"]]


def test_two_idle_neighbours_pass_the_time_of_day(config):
    ann = _npc({"name": "Ann", "sched_state": "IDLE"})
    tom = _npc({"name": "Tom", "sched_state": "IDLE"})
    s = _session([ann, tom], _FakePlayer([0, 0, 0]))
    s._chat_rng = random.Random(0)
    s._chat_rng.random = lambda: 0.0           # this pass, somebody chats
    s._update_small_talk()
    talkers = [thing for thing, _text, _left in s.live_barks()]
    assert len(talkers) == 1 and len(s._bark_queue) == 1
    s._update_small_talk()                      # both on cooldown now
    assert len(s._bark_queue) == 1


# ---------------------------------------------------- what's on your mind?
def test_an_npc_explains_what_it_is_doing_and_what_it_knows():
    text = mental_state.speak_mind(
        {"name": "Tom", "sched_state": "GOING_HOME", "_need_reason": "hungry",
         "need_fatigue": 0.9},
        facts=[_fact(source="witnessed", certainty=0.9)])
    assert text.split(". ")[0] + "." in mental_state._THOUGHTS["hungry"] or \
        any(line in text for line in mental_state._THOUGHTS["hungry"])
    assert "dead on my feet" in text
    assert "I saw it with my own eyes: you stole bread from Bram." in text


def test_an_idle_npc_with_nothing_on_its_mind_says_so():
    assert mental_state.speak_mind({"sched_state": "WORKING"}) == \
        "Just working. Somebody has to."


def test_whats_on_your_mind_is_offered_in_conversation(config):
    tom = _npc({"name": "Tom", "sched_state": "WORKING"})
    s = _session([tom], _FakePlayer([0, 0, 0]))
    tree = {"start": "g", "nodes": {"g": {"text": "Hello.", "responses": [
        {"text": "Bye.", "goto": "END"}]}}}
    out = s._with_mind_topic(tree, tom)
    responses = out["nodes"]["g"]["responses"]
    assert responses[0] == {"text": "What's on your mind?", "goto": "_mind"}
    assert responses[-1]["text"] == "Bye."
    assert out["nodes"]["_mind"]["text"] == "Just working. Somebody has to."
    assert tree["nodes"]["g"]["responses"] == [{"text": "Bye.", "goto": "END"}]
    hostile = _npc({"name": "Brute", "aggression": "hostile"})
    assert s._with_mind_topic(tree, hostile) is tree
