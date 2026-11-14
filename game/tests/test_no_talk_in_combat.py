"""No talking in a fight: not while the player is in combat, nor with anyone
who is (game/runtime.py talk_block / player_in_combat / actor_in_combat)."""

from __future__ import annotations

import pytest

from .. import runtime as rt
from .test_player_head import _actor, _session


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(rt.time, "monotonic", lambda: now[0])
    return now


def _talker(name="Mara"):
    npc = _actor(name)
    npc.properties["dialogue"] = {"start": "hi", "nodes": {"hi": {"text": "Well met.", "responses": []}}}
    npc.properties["display_name"] = name
    return npc


def _world(*extra):
    npc = _talker()
    s = _session([npc, *extra])
    s.begin_new_character("Tester", "imperial", "warrior", "none", "male", head="head13")
    return s, npc


def _messages(s):
    return [n.get("text", "") for n in s.notifications]


def test_talking_in_peace_works(clock):
    s, npc = _world()
    assert s.talk_block(npc) == ""
    assert s.start_dialogue(npc, None)


def test_no_talking_in_the_middle_of_a_fight_until_it_has_died_down(clock):
    foe = _actor("Bandit", kind="npc", role="bandit")
    s, npc = _world(foe)
    s.note_combat(foe, True)                            # the player swung at someone
    assert s.player_in_combat()
    assert not s.start_dialogue(npc, None)
    assert any("middle of a fight" in m for m in _messages(s))
    clock[0] += rt.COMBAT_GRACE + 0.5                   # it has died down
    assert not s.player_in_combat()
    assert s.start_dialogue(npc, None)


def test_a_foe_with_eyes_on_the_player_keeps_them_in_combat(clock, monkeypatch):
    foe = _actor("Wolf", kind="creature", role="wolf")
    s, npc = _world(foe)
    foe.properties["_aggro_target"] = id(s.player_actor)
    monkeypatch.setattr(rt.fio, "monster_things", lambda _logic: [foe])
    assert s.player_in_combat()
    assert "middle of a fight" in s.talk_block(npc)
    foe.properties["dead"] = True
    assert not s.player_in_combat()


def test_no_talking_with_someone_who_is_fighting(clock):
    s, npc = _world()
    npc.properties["_aggro_target"] = 12345              # swinging at someone
    reason = s.talk_block(npc)
    assert "Mara is fighting" in reason
    assert not s.start_dialogue(npc, None)
    npc.properties.pop("_aggro_target")
    npc.properties["sched_state"] = rt.sched.FLEE         # running for it
    assert s.talk_block(npc)
    npc.properties["sched_state"] = rt.sched.IDLE if hasattr(rt.sched, "IDLE") else "IDLE"
    npc.properties["_aggro_target"] = 12345
    npc.properties["triggered"] = True                    # parked: only a memory of a fight
    assert s.talk_block(npc) == ""


def test_a_fight_breaks_off_a_conversation_under_way(clock):
    foe = _actor("Bandit", kind="npc", role="bandit")
    s, npc = _world(foe)
    assert s.start_dialogue(npc, None)
    s.note_combat(foe, False)                           # struck mid-conversation
    assert s.dialogue is None
    assert any("breaks off" in m for m in _messages(s))


def test_a_partner_drawn_into_a_fight_ends_the_talk(clock):
    s, npc = _world()
    assert s.start_dialogue(npc, None)
    npc.properties["sched_state"] = rt.sched.COMBAT
    s._check_talk_partner()                             # what every tick does
    assert s.dialogue is None


def test_notice_boards_are_still_read_in_a_fight(clock):
    s, _npc = _world()
    board = _actor("Board", kind="noticeboard", role="")
    s.note_combat(_actor("Bandit", role="bandit"), True)
    assert s.player_in_combat()
    s.start_dialogue(board, None)
    assert not any("middle of a fight" in m for m in _messages(s))
