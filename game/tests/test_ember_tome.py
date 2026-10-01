"""The Ember Tome: a spellbook that is also a quest item, the quest whose
arrow points at it, and the expanded world it sits in.

The session tests are headless (fake logic, fake things); the map tests read
``maps/village_walled_source.json`` as data.
"""

from __future__ import annotations

import json
import math
import os

from ..rpg import inventory as inv
from ..rpg import items as rpg_items
from ..rpg import quests

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MAP = os.path.join(ROOT, "maps", "village_walled_source.json")


class _FakeThing:
    def __init__(self, pos, properties):
        self.pos = list(pos)
        self.properties = dict(properties)


class _FakePlayer:
    def __init__(self, pos):
        self.pos = list(pos)
        self.properties = {}


class _FakeLogic:
    def __init__(self, things, player):
        self.things = things
        self.player = player


def _book(pos=(20000.0, 900.0, -20000.0)):
    return _FakeThing(pos, {"type": "spellbook", "name": "Ember_Tome",
                            "spell": "firebolt", "quest_item": "ember_tome",
                            "pickup_radius": 70.0})


class _Globals:
    """The engine's global store, as the session reaches it."""

    def __init__(self):
        self.d = {}

    def get(self, key, default=None, store=""):
        return self.d.get((store, key), default)

    def set(self, key, value, store=""):
        self.d[(store, key)] = value

    def all(self, store=""):
        return {k: v for (s, k), v in self.d.items() if s == store}


def _session(things, player):
    from ..runtime import MiniwindSession
    s = MiniwindSession(_FakeLogic(things, player),
                        cfg={"start_hour": 12.0, "minutes_per_day": 9e9},
                        globals_store=_Globals())
    s.clock.set_time(12.0, 1)
    return s


def test_the_tome_is_a_quest_item():
    item = rpg_items.get("ember_tome")
    assert item is not None and item.category == "quest"


def test_thalen_gives_a_fetch_quest_for_the_tome():
    s = _session([], _FakePlayer([0, 272, 0]))       # registers the quests
    q = quests.get("ember_tome")
    assert q is not None and q.giver == "Thalen"
    first = q.stage(0)
    assert first.condition_kind() == quests.COND_FETCH
    assert first.condition_target() == "ember_tome"
    assert s is not None


def test_the_quest_arrow_points_at_the_book():
    book = _book()
    s = _session([book], _FakePlayer([0, 272, 0]))
    assert s.game.start_quest("ember_tome")
    targets = s.quest_arrow_targets()
    assert targets and targets[0][1] == "ember_tome"
    assert targets[0][0] == list(book.pos)
    guide = s.quest_guidance()
    assert guide["target_pos"] == list(book.pos)
    assert "The Ember Tome" in guide["action"]


def test_reading_the_book_hands_over_the_item_and_finishes_the_quest():
    book = _book()
    player = _FakePlayer([book.pos[0], book.pos[1], book.pos[2] + 20.0])
    s = _session([book], player)
    s.game.start_quest("ember_tome")
    gold = s.game.character.gold
    s._tick_spellbooks()
    s._tick_quests()
    assert "firebolt" in s.game.character.known_spells
    assert inv.has_item(s.game.character.inventory, "ember_tome", 1)
    assert s.game.quests.is_complete("ember_tome")
    assert s.game.character.gold == gold + 120
    assert book.properties.get("dead")
    assert s.quest_arrow_targets() == []


def test_a_book_without_a_quest_item_only_teaches():
    book = _book()
    book.properties["quest_item"] = ""
    s = _session([book], _FakePlayer(list(book.pos)))
    s._tick_spellbooks()
    assert "firebolt" in s.game.character.known_spells
    assert s.game.character.inventory == [] or \
        not inv.has_item(s.game.character.inventory, "ember_tome", 1)


# ---------------------------------------------------------------------------
# The map
# ---------------------------------------------------------------------------

def _map():
    with open(MAP) as f:
        return json.load(f)


def test_the_world_is_huge_and_has_mountains():
    m = _map()
    td = m["terrain_data"]
    span = (td["max_chunk_x"] - td["min_chunk_x"] + 1) * td["chunk_size"]
    assert span >= 80000
    assert td.get("heightmap_blob"), "the mountains are a heightmap overlay"
    assert not any(b["pos"][1] == 76.0 and not b.get("shader")
                   and all(v == "nodraw.jpg" for v in b["textures"].values())
                   for b in m["brushes"]), "the 2.4 floor slabs are gone"


def test_the_tome_rests_on_the_mountain_altar_far_from_the_village():
    m = _map()
    books = [t for t in m["things"] if t["type"] == "spellbook"]
    assert len(books) == 1
    book = books[0]
    p = book["properties"]
    assert p["quest_item"] == "ember_tome" and p["name"] == "Ember_Tome"
    x, y, z = book["pos"]
    assert math.hypot(x, z) > 25000, "far from Millbrook"
    assert y > 600, "up in the mountains"
    shrine = [t for t in m["things"]
              if t["properties"].get("place_name") == "Emberpeak Shrine"]
    assert shrine and math.hypot(shrine[0]["pos"][0] - x, shrine[0]["pos"][2] - z) < 400


def test_the_sites_are_spread_out():
    m = _map()
    locs = [t["pos"] for t in m["things"]
            if t["properties"].get("marker_kind") == "location"
            and t["properties"].get("place_name") != "Millbrook"]
    nearest = []
    for i, a in enumerate(locs):
        d = min(math.hypot(a[0] - b[0], a[2] - b[2])
                for j, b in enumerate(locs) if j != i)
        nearest.append(d)
    nearest.sort()
    # The lake shore keeps its villages together; everything else has room.
    assert nearest[len(nearest) // 2] > 4000


def test_every_lake_is_one_water_brush_over_a_sculpted_depression():
    import pytest
    pytest.importorskip("OpenGL", reason="engine.terrain samples the ground")
    import numpy as np
    from ..tools.expand_world import _heights, _load_heightmap, _terrain
    m = _map()
    water = [b for b in m["brushes"] if b.get("water_plane")]

    def rect(b):
        return (b["pos"][0] - b["size"][0] / 2, b["pos"][2] - b["size"][2] / 2,
                b["pos"][0] + b["size"][0] / 2, b["pos"][2] + b["size"][2] / 2)
    rects = [rect(b) for b in water]
    for i, a in enumerate(rects):        # no water body is built of pieces
        for c in rects[i + 1:]:
            assert not (a[0] <= c[2] and c[0] <= a[2] and a[1] <= c[3] and c[1] <= a[3])
    terrain = _terrain(m["terrain_data"], heightmap=_load_heightmap(m["terrain_data"]))
    lakes = [b for b in water if b["size"][0] > 600]
    assert len(lakes) >= 4                # Mirrormere and the new ponds
    for b in lakes:
        x0, z0, x1, z1 = rect(b)
        top = b["pos"][1] + b["size"][1] / 2
        xs, zs = np.meshgrid(np.linspace(x0, x1, 60), np.linspace(z0, z1, 60))
        h = _heights(terrain, xs.ravel(), zs.ravel()).reshape(60, 60)
        wet = h < top
        assert 0.3 < wet.mean() < 0.9, "the water fills a depression, not the box"
        edge = np.concatenate([wet[0], wet[-1], wet[:, 0], wet[:, -1]])
        assert not edge.any(), "the brush's edges lie under dry bank"
        assert h.min() > b["pos"][1] - b["size"][1] / 2, "the bed is inside the brush"
