"""Human habits vary between campaigns, persist, and constrain live decisions."""

import json
import random
from types import SimpleNamespace

import pytest

from game import fio
from game.multiplayer.bots import PartyBots
from game.multiplayer.companion_behavior import CompanionMind
from game.multiplayer.model import InputFrame
from game.rpg.dialogue import DictStore
from game.rpg.game_state import GameState


def test_new_campaigns_and_teammates_have_different_personalities():
    minds = [CompanionMind(f"campaign-{i}", "same-character") for i in range(100)]
    assert len({m.personality for m in minds}) == 100
    assert {m.personality.style for m in minds} == {"melee", "ranged", "magic"}
    assert CompanionMind("one", "a").personality != CompanionMind("one", "b").personality


def test_json_save_continues_habits_and_decision_stream_without_using_game_dice():
    mind = CompanionMind("campaign", "companion")
    dice = random.getstate()
    for _ in range(25):
        mind.think_interval()
        mind.aim_error()
    saved = json.loads(json.dumps(mind.to_dict()))
    resumed = CompanionMind("different-lobby", "same-person", saved)
    assert resumed.personality == mind.personality
    assert [resumed.uniform(0, 1) for _ in range(20)] == [mind.uniform(0, 1) for _ in range(20)]
    assert random.getstate() == dice


@pytest.mark.parametrize("saved", [None, {}, {"version": 99},
    {"version": 1, "seed": "bad", "draws": 0},
    {"version": 1, "seed": "a" * 64, "draws": -1}])
def test_older_or_invalid_behavior_saves_get_stable_defaults(saved):
    expected = CompanionMind("old-campaign", "companion")
    assert CompanionMind("old-campaign", "companion", saved).to_dict() == expected.to_dict()


@pytest.fixture
def party(monkeypatch):
    def member(pid, pos, bot):
        game = GameState.new_game(DictStore(), pid, "imperial", "warrior")
        session = SimpleNamespace(
            game=game, nav=None, _attack_cooldown=0, _cast_cooldown=0,
            _cancel_bow_draw=lambda: None,
            logic=SimpleNamespace(mover_runtime=SimpleNamespace(doors=[])),
        )
        return SimpleNamespace(
            player_id=pid, owner="host", profile={"name": pid},
            bot=bot, connected=True, returning=False, mind=None, task="",
            bot_target=None, actor=SimpleNamespace(properties={}),
            physics=SimpleNamespace(pos=list(pos), angle=0), session=session,
            frame=InputFrame(),
        )

    human = member("human", (-250, 0, 0), False)
    bot = member("companion", (0, 0, 0), True)
    actors, actions = [], []
    coop = SimpleNamespace(
        authority=True, players={p.player_id: p for p in (human, bot)},
        logic=SimpleNamespace(monster_ai=SimpleNamespace(_hunts_player=lambda a: False)),
        lobby=SimpleNamespace(state={"campaign_id": "behavior-tests"}),
        action=lambda member, action, args: actions.append((member, action, args)),
        root=SimpleNamespace(_road_plans={}),
    )
    monkeypatch.setattr(fio, "monster_things", lambda _: actors)
    return SimpleNamespace(coop=coop, brain=PartyBots(coop), human=human,
                           bot=bot, actors=actors, actions=actions)


def enemy(party, pos=(85, 64, 0)):
    actor = SimpleNamespace(pos=list(pos), properties={
        "id": f"enemy-{len(party.actors)}", "aggression": "hostile", "health": 500,
    })
    party.actors.append(actor)
    return actor


def advance(party, seconds):
    for _ in range(round(seconds / 0.05)):
        party.brain.tick(0.05)


def test_companion_reacts_after_a_delay_and_eventually_fights(party):
    target = enemy(party)
    party.brain.tick(0.01)
    assert not party.actions and party.bot.bot_target is None
    party.brain.clock = party.brain.next_think[party.bot.player_id]
    party.brain.tick(0)
    assert party.bot.task == "Noticing danger" and not party.actions
    advance(party, 2)
    assert party.bot.bot_target is target
    assert any(action == "attack" for _, action, _ in party.actions)


def test_threat_awareness_is_local_and_walls_block_discovery(party):
    target = enemy(party, (-900, 64, 0))
    party.human.physics.pos = [-850, 0, 0]
    assert party.brain._threat(party.bot, party.human) is None
    target.pos = [200, 64, 0]
    party.human.physics.pos = [-250, 0, 0]
    party.bot.session.nav = SimpleNamespace(line_clear=lambda *a: False)
    assert party.brain._threat(party.bot, party.human) is None
    party.brain.note_attack(target)
    assert party.brain._threat(party.bot, party.human) is None
    party.bot.session.nav = None
    assert party.brain._threat(party.bot, party.human) is target


def test_lost_sight_searches_last_seen_position_then_gives_up(party):
    target = enemy(party, (350, 64, 0))
    advance(party, 1.5)
    last_seen = tuple(target.pos)
    target.properties["hidden"] = True
    target.pos = [900, 64, 900]
    goals = []
    party.brain._walk = lambda bot, goal, **kw: goals.append(tuple(goal)) or InputFrame()
    party.brain.decide(party.bot, 0)
    assert party.bot.task == "Looking for the attacker"
    assert goals[-1] == last_seen
    assert party.bot.bot_target is None
    advance(party, 3)
    assert party.bot.task.startswith("Following")


def test_commitment_prevents_switching_to_each_slightly_nearer_enemy(party):
    original = enemy(party, (200, 64, 0))
    party.brain.decide(party.bot, 0)
    enemy(party, (180, 64, 0))
    assert party.brain._threat(party.bot, party.human) is original


def test_projectile_spell_aim_can_miss_instead_of_snapping_to_actor(party):
    from game.rpg import magic

    target = enemy(party, (400, 64, 0))
    action, (point, target_id) = party.brain._spell_action(
        party.bot, magic.get("flare"), target
    )
    assert action == "cast_at" and target_id is None
    assert point != target.pos
    assert abs(point[2] - target.pos[2]) < 65


def test_shot_checks_the_imperfect_aim_lane_for_bystanders_too(party):
    import math

    target = enemy(party, (500, 64, 0))
    bystander = enemy(party, (450, 64, 45))
    bystander.properties["aggression"] = "passive"
    assert party.brain._clear_shot(party.bot, target)
    assert not party.brain._clear_shot(party.bot, target, aim=math.atan2(450, 45))


def test_wounded_companion_falls_back_and_exhaustion_prevents_sprinting(party):
    target = enemy(party)
    character = party.bot.session.game.character
    character.health = character.max_health * 0.1
    advance(party, 1.5)
    assert party.bot.task == "Falling back" and party.bot.frame.move_x < 0
    character.stamina = 0
    assert "sprint" not in party.brain._walk(party.bot, (500, 0, 0)).held
    assert party.bot.bot_target is target


def test_last_human_rescue_takes_priority_over_fear_and_nearby_enemy(party):
    enemy(party)
    party.human.session.game.character.health = 0
    party.human.physics.pos = [70, 0, 0]
    party.bot.session.game.character.health = 1
    advance(party, 1)
    assert party.bot.task == "Reviving human"
    assert "interact" in party.bot.frame.held


def test_non_authoritative_client_never_advances_companion_choices(party):
    mind = party.brain.mind(party.bot)
    before = mind.to_dict()
    party.coop.authority = False
    advance(party, 2)
    assert mind.to_dict() == before and not party.actions
