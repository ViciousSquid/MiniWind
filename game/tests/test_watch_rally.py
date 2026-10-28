"""An attacked guard calls the watch: every guard of his town within earshot
turns on the player at once, and so does a killing of one -- the watch does
not wait for a witness to walk the news over."""

from __future__ import annotations

from .test_combat_ai import _FakeLogic, _FakePlayer, _FakeThing, _guard
from .test_disposition import _FakeGlobals


def _named_guard(name, pos):
    g = _guard(pos)
    g.properties.update(name=name, display_name=name, health=60, max_health=60)
    return g


def _session(things, player):
    from ..runtime import MiniwindSession
    s = MiniwindSession(_FakeLogic(things, player),
                        cfg={"start_hour": 12.0, "minutes_per_day": 9e9},
                        globals_store=_FakeGlobals())
    s.clock.set_time(12.0, 1)
    return s


def _hunting(guard):
    p = guard.properties
    return p.get("aggression") == "hostile" and p.get("triggered") is False


def test_striking_a_guard_brings_the_nearby_watch_and_not_the_far_one():
    from ..runtime import GUARD_AID_RADIUS
    struck = _named_guard("Struck", [80, 0, 0])
    near = _named_guard("Near", [600, 0, 400])       # round a corner, out of sight
    far = _named_guard("Far", [GUARD_AID_RADIUS + 900, 0, 0])
    villager = _FakeThing([150, 0, 0], {
        "type": "npc", "name": "Villager", "npc_role": "villager", "faction": "villagers",
        "team": "villagers", "aggression": "passive", "triggered": True})
    s = _session([struck, near, far, villager], _FakePlayer([0, 0, 0]))
    rallied = s._rally_the_watch(struck)
    assert rallied == [near]
    assert _hunting(near)
    assert not _hunting(far)
    assert villager.properties["aggression"] == "passive"


def test_a_guard_killed_by_the_player_still_calls_the_watch():
    dead = _named_guard("Dead", [80, 0, 0])
    dead.properties.update(dead=True, health=0)
    comrade = _named_guard("Comrade", [900, 0, 0])
    s = _session([dead, comrade], _FakePlayer([0, 0, 0]))
    assert s._rally_the_watch(dead) == [comrade]
    assert _hunting(comrade)


def test_a_guard_on_his_way_to_arrest_the_player_joins_the_fight_instead():
    struck = _named_guard("Struck", [80, 0, 0])
    arresting = _named_guard("Arresting", [300, 0, 0])
    s = _session([struck, arresting], _FakePlayer([0, 0, 0]))
    s._arrest_guard, s._arrest_state = arresting, "approach"
    arresting.properties["_arrest_state"] = "approach"
    s._rally_the_watch(struck)
    assert "_arrest_state" not in arresting.properties
    assert s._arrest_guard is None and s._arrest_state == ""
    assert _hunting(arresting)


def test_a_blow_at_a_townsman_is_not_the_watchs_cry_to_answer():
    townsman = _FakeThing([80, 0, 0], {
        "type": "npc", "name": "Townsman", "npc_role": "villager", "faction": "villagers",
        "team": "villagers", "aggression": "passive", "triggered": True})
    guard = _named_guard("Guard", [400, 0, 0])
    s = _session([townsman, guard], _FakePlayer([0, 0, 0]))
    assert s._rally_the_watch(townsman) == []
    assert not _hunting(guard)


def test_provoking_a_guard_rallies_the_rest():
    struck = _named_guard("Struck", [80, 0, 0])
    near = _named_guard("Near", [500, 0, 0])
    s = _session([struck, near], _FakePlayer([0, 0, 0]))
    s._refresh_actor_cache()
    s._provoke(struck)
    assert _hunting(struck) and _hunting(near)
