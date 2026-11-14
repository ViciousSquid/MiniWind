"""World-wide head identity: authored NPCs, saves, guards and journeys."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ..rpg import heads
from ..rpg.head_registry import (
    HeadPoolExhausted, WorldHeadRegistry, image_key, member_identity,
)
from .test_player_head import _Globals, _actor, _session


class _Store:
    def __init__(self):
        self.data = {}

    def get(self, key, default="false"):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


def test_two_authored_npcs_cannot_keep_the_same_head():
    a = _actor("Miller", "head06")
    b = _actor("Grain Carrier", "head06")
    c = _actor("Another Grain Carrier", "head06")
    s = _session([a, b, c])
    s.begin_new_character("Player", "valian", "warrior", head="head13")
    images = [image_key(t.properties["head"]) for t in (a, b, c)]
    assert len(images) == len(set(images)) == 3
    assert image_key("head13") not in images
    assert a.properties["head"] == "head06"


def test_every_guard_has_a_distinct_guard_image():
    guards = [_actor(f"Watch {i}", "guard01", role="guard") for i in range(12)]
    s = _session(guards)
    s.begin_new_character("Player", "valian", "warrior", head="head13")
    faces = [t.properties["head"] for t in guards]
    assert all(heads.is_guard_head(face) for face in faces)
    assert len(set(map(image_key, faces))) == len(faces)


def test_legacy_save_collisions_are_repaired_and_persisted():
    stored = _Globals()
    a, b = _actor("A", "head03"), _actor("B", "head03")
    s = _session([a, b], globals_store=stored)
    s.begin_new_character("Player", "valian", "warrior", head="head13")
    faces = (a.properties["head"], b.properties["head"])
    assert len(set(faces)) == 2
    s.game.save_to_store()

    # The save's *old* authored data may still contain the collision.
    a2, b2 = _actor("A", "head03"), _actor("B", "head03")
    resumed = _session([a2, b2], globals_store=stored)
    resumed.restore()
    assert (a2.properties["head"], b2.properties["head"]) == faces
    assert "head13" not in faces


def test_offscreen_members_are_reserved_against_authored_scene():
    resident = _actor("Baker", "head04")
    member1 = dict(role="merchant", name="road_merchant_1",
                   display="Grain Carrier", alive=True, head="head04")
    member2 = dict(role="guard", name="road_guard_2",
                   display="Guard", alive=True, head="guard03")
    member3 = dict(role="guard", name="road_guard_3",
                   display="Guard", alive=True, head="guard03")
    s = _session([resident])
    trip = SimpleNamespace(id="journey1", members=[member1, member2, member3])
    s.living = SimpleNamespace(board=SimpleNamespace(journeys={"journey1": trip}))
    s.begin_new_character("Player", "valian", "warrior", head="head13")
    assert member1["head"] != resident.properties["head"]
    assert member2["head"] != member3["head"]
    assert all(heads.is_guard_head(m["head"]) for m in (member2, member3))
    assert all(image_key(m["head"]) != image_key("head13")
               for m in (member1, member2, member3))


def test_resident_and_its_travelling_proxy_are_the_same_person():
    store = _Store()
    r = WorldHeadRegistry(store)
    r.set_player("head13")
    resident = r.assign("person-42", "head21")
    proxy = r.assign(member_identity(dict(resident="person-42",
                                           name="road_proxy_42", head="head06")),
                     "head06")
    assert proxy == resident
    assert r.assign("unrelated-99", "head21") != resident


def test_saved_ledger_reserves_heads_across_map_changes():
    store = _Store()
    first = WorldHeadRegistry(store)
    first.set_player("head13")
    alice = first.assign("map-A/alice", "head02")
    second = WorldHeadRegistry(store)
    second.set_player("head13")
    assert second.assign("map-A/alice", "head99") == alice
    assert second.assign("map-B/bob", alice) != alice


def test_player_picture_wins_over_legacy_ownership():
    store = _Store()
    old = WorldHeadRegistry(store)
    old.assign("old-npc", "head13")
    fresh = WorldHeadRegistry(store)
    fresh.set_player("head13")
    assert fresh.assign("old-npc", "head13") != "head13"


def test_exhaustion_reuses_a_guard_and_keeps_its_identity(monkeypatch):
    monkeypatch.setattr(heads, "GUARD_HEAD_IDS", ["guard01"])
    r = WorldHeadRegistry(_Store())
    assert r.assign("one", guard=True) == "guard01"
    assert r.assign("two", guard=True) == "guard01"
    assert r.assign("two", "guard02", guard=True) == "guard01"


@pytest.mark.parametrize("guard,pool_attr,pool,player", [
    (False, "HEAD_IDS", ["head01", "head02", "head13"], "head13"),
    (True, "GUARD_HEAD_IDS", ["guard01", "guard02"], "head13"),
])
def test_reuse_cycles_in_assignment_order_across_save_load(monkeypatch, guard, pool_attr, pool, player):
    monkeypatch.setattr(heads, pool_attr, pool)
    store = _Store()
    r = WorldHeadRegistry(store)
    r.set_player(player)
    # Names deliberately sort in the opposite order to assignment.
    first = r.assign("z-first", pool[1], guard=guard)
    second = r.assign("a-second", pool[0], guard=guard)
    assert r.assign("third", guard=guard) == first
    resumed = WorldHeadRegistry(store)
    resumed.set_player(player)
    assert resumed.assign("fourth", guard=guard) == second
    assert resumed.assign("fifth", guard=guard) == first
    assert resumed.assign("third", guard=guard) == first
    assert player not in resumed.assignments.values()


def test_empty_pool_still_reports_no_usable_portrait(monkeypatch):
    monkeypatch.setattr(heads, "GUARD_HEAD_IDS", [])
    with pytest.raises(HeadPoolExhausted, match="No usable guard head"):
        WorldHeadRegistry(_Store()).assign("guard", guard=True)


def test_reuse_never_takes_any_coop_party_portrait(monkeypatch):
    monkeypatch.setattr(heads, "HEAD_IDS", ["head01", "head02", "head03"])
    store = _Store()
    r = WorldHeadRegistry(store)
    r.assign("legacy-npc", "head02")
    r.set_player("head01")
    r.set_players({"human": "head01", "companion": "head02"})
    assert r.assign("legacy-npc") == "head03"
    assert r.assign("another-npc") == "head03"
    resumed = WorldHeadRegistry(store)
    resumed.set_player("head01")
    resumed.set_players({"human": "head01", "companion": "head02"})
    assert resumed.assign("new-npc") == "head03"


def test_authored_human_creatures_have_individual_faces():
    bandits = [_actor(f"Bandit {i}", "head08", kind="creature",
                      role="bandit") for i in range(4)]
    cultists = [_actor(f"Cultist {i}", "head08", kind="creature",
                       role="cultist") for i in range(3)]
    s = _session(bandits + cultists)
    s.begin_new_character("Player", "valian", "warrior", head="head13")
    faces = [image_key(t.properties["head"]) for t in bandits + cultists]
    assert len(faces) == len(set(faces))
    assert image_key("head13") not in faces

def test_character_creation_finishes_with_more_people_than_unique_heads(monkeypatch):
    """Every person retains a head after the pool starts cycling."""
    monkeypatch.setattr(heads, "HEAD_IDS", ["head01", "head02", "head13"])
    actors = [_actor(f"Villager {i}") for i in range(5)]
    s = _session(actors)
    s.open_screen = "charcreate"
    s.begin_new_character("Player", "valian", "warrior", head="head13")
    assert not s.needs_char_creation
    assert s.open_screen is None
    assigned = [a.properties["head"] for a in actors]
    assert len(set(assigned)) == 2
    assert assigned == [assigned[0], assigned[1], assigned[0], assigned[1], assigned[0]]
    assert all(a.properties["custom_idle"] == heads.any_head_path(a.properties["head"])
               for a in actors)


def test_guards_reuse_guard_portraits_when_their_pool_runs_out(monkeypatch):
    monkeypatch.setattr(heads, "GUARD_HEAD_IDS", ["guard01"])
    actors = [_actor(f"Guard {i}", role="guard") for i in range(3)]
    s = _session(actors)
    s.begin_new_character("Player", "valian", "warrior", head="head13")
    assert [a.properties["head"] for a in actors] == ["guard01"] * 3
    assert all(a.properties["custom_idle"] == heads.guard_head_path("guard01") for a in actors)


def test_offscreen_journeys_do_not_block_character_creation_when_exhausted(monkeypatch):
    monkeypatch.setattr(heads, "HEAD_IDS", ["head01", "head13"])
    m = dict(role="merchant", name="road_merchant_1", display="Traveller",
             alive=True, head="")
    s = _session([_actor("Resident")])
    trip = SimpleNamespace(id="j1", members=[m])
    s.living = SimpleNamespace(board=SimpleNamespace(journeys={"j1": trip}))
    s.begin_new_character("Player", "valian", "warrior", head="head13")
    assert not s.needs_char_creation
    assert m["head"] == "head01"
    assert len(set(s.head_registry.assignments.values())) == 1




def test_heads_given_at_play_start_survive_character_creation_but_the_players():
    """Faces are handed out as play starts, under the loading bar
    (preassign_npc_heads); making the character then moves only the NPC
    holding the face the player chose -- the same faces creation alone gives."""
    people = [_actor(f"Villager {i}", "") for i in range(6)]
    s = _session(people)
    s.preassign_npc_heads()
    before = [t.properties["head"] for t in people]
    assert all(heads.is_any_head(face) for face in before)
    assert len(set(map(image_key, before))) == len(before)
    chosen = before[2]                       # the player picks a villager's face
    s.begin_new_character("Player", "valian", "warrior", head=chosen)
    after = [t.properties["head"] for t in people]
    assert image_key(chosen) not in map(image_key, after)
    assert [a == b for a, b in zip(before, after)] == [True, True, False, True, True, True]
    assert len(set(map(image_key, after))) == len(after)

    # Exactly what character creation alone hands out to everyone else.
    fresh = [_actor(f"Villager {i}", "") for i in range(6)]
    alone = _session(fresh)
    alone.begin_new_character("Player", "valian", "warrior", head=chosen)
    unmoved = [i for i in range(6) if i != 2]
    assert [after[i] for i in unmoved] == [fresh[i].properties["head"] for i in unmoved]
