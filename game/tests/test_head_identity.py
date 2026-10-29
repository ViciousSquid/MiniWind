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
    s.begin_new_character("Player", "imperial", "warrior", head="head13")
    images = [image_key(t.properties["head"]) for t in (a, b, c)]
    assert len(images) == len(set(images)) == 3
    assert image_key("head13") not in images
    assert a.properties["head"] == "head06"


def test_every_guard_has_a_distinct_guard_image():
    guards = [_actor(f"Watch {i}", "guard01", role="guard") for i in range(12)]
    s = _session(guards)
    s.begin_new_character("Player", "imperial", "warrior", head="head13")
    faces = [t.properties["head"] for t in guards]
    assert all(heads.is_guard_head(face) for face in faces)
    assert len(set(map(image_key, faces))) == len(faces)


def test_legacy_save_collisions_are_repaired_and_persisted():
    stored = _Globals()
    a, b = _actor("A", "head03"), _actor("B", "head03")
    s = _session([a, b], globals_store=stored)
    s.begin_new_character("Player", "imperial", "warrior", head="head13")
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
    s.begin_new_character("Player", "imperial", "warrior", head="head13")
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


def test_exhaustion_is_an_error_not_a_reused_guard(monkeypatch):
    monkeypatch.setattr(heads, "GUARD_HEAD_IDS", ["guard01"])
    r = WorldHeadRegistry(_Store())
    assert r.assign("one", guard=True) == "guard01"
    with pytest.raises(HeadPoolExhausted, match="No unused guard head"):
        r.assign("two", guard=True)
