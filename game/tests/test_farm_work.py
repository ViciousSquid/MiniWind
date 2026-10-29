"""Farmers at work: a scythe in the wheat, a pitchfork with the animals."""

from types import SimpleNamespace

import numpy as np

from .. import farm_work, mental_state
from ..farm_work import FarmWork


class Field:
    """A terrain whose wheat is the rectangle x 1000..2000, z -400..400."""

    biome_map = np.zeros((4, 4, 5), np.uint8)

    def biome_weights_batch(self, xs, zs):
        xs, zs = np.asarray(xs, float), np.asarray(zs, float)
        out = np.zeros((len(xs), 5), np.float32)
        out[:, 3] = ((xs >= 1000) & (xs <= 2000) & (np.abs(zs) <= 400)).astype(np.float32)
        return out


def actor(role="farmer", pos=(0.0, 0.0, 0.0), **props):
    return SimpleNamespace(properties=dict(npc_role=role, home=[0.0, 0.0, 0.0], **props),
                           pos=list(pos))


def session(hour=12.0, things=(), terrain=None):
    s = SimpleNamespace(clock=SimpleNamespace(day=3, hour=hour),
                        logic=SimpleNamespace(world_runtime=SimpleNamespace(terrain=terrain)))
    s._things_of_type = lambda kind: [t for t in things if t.properties.get("type") == kind]
    s._resolve_location = lambda npc, key: [0.0, 0.0, 0.0]
    return s


def test_the_rows_cover_the_field_back_and_forth():
    rows = farm_work.field_rows(Field(), (0.0, 0.0))
    assert rows and all(1000 <= x <= 2000 and abs(z) <= 400 for x, z in rows)
    zs = [z for _x, z in rows]
    assert zs == sorted(zs)                                  # row by row
    first = [x for x, z in rows if z == zs[0]]
    second = [x for x, z in rows if z == sorted(set(zs))[1]]
    assert first == sorted(first) and second == sorted(second, reverse=True)
    assert farm_work.field_rows(Field(), (9000.0, 9000.0)) == []


def test_a_farmer_reaps_by_day_with_a_scythe_and_walks_the_rows():
    farmer = actor()
    s = session(terrain=Field())
    w = FarmWork()
    assert w.drive(s, farmer)
    p = farmer.properties
    assert p["sched_state"] == "REAPING" and p["_active_weapon"] == "scythe"
    first = list(p["_dest"])
    farmer.pos = [first[0], 0.0, first[2]]                  # arrives
    w.drive(s, farmer)
    assert p["_dest"] != first                              # on to the next


def test_with_no_field_near_the_farmer_tends_the_nearest_animal():
    sheep = SimpleNamespace(properties=dict(type="creature", npc_role="sheep"), pos=[500.0, 0.0, 0.0])
    far = SimpleNamespace(properties=dict(type="creature", npc_role="cow"), pos=[1700.0, 0.0, 0.0])
    farmer = actor()
    s = session(things=[far, sheep], terrain=None)
    w = FarmWork()
    assert w.drive(s, farmer)
    p = farmer.properties
    assert p["sched_state"] == "TENDING" and p["_active_weapon"] == "pitchfork"
    assert 400 < p["_dest"][0] < 500                         # beside the sheep
    farmer.pos = [450.0, 0.0, 0.0]
    w.drive(s, farmer)
    assert "_dest" not in p and abs(p["_facing"] - np.pi / 2) < 1e-6


def test_work_alternates_between_the_field_and_the_animals():
    sheep = SimpleNamespace(properties=dict(type="creature", npc_role="sheep"), pos=[300.0, 0.0, 0.0])
    farmer = actor()
    s = session(things=[sheep], terrain=Field())
    w = FarmWork()
    w.drive(s, farmer)
    assert farmer.properties["_farm_task"]["kind"] == "reap"
    s.clock.hour = 12.0 + farm_work.REAP_HOURS + 0.1
    w.drive(s, farmer)
    assert farmer.properties["_farm_task"]["kind"] == "tend"


def test_dusk_puts_the_tool_away_and_hands_back_the_schedule():
    farmer = actor(equipped_weapon="iron_shortsword")
    s = session(terrain=Field())
    w = FarmWork()
    w.drive(s, farmer)
    s.clock.hour = 20.0
    assert not w.drive(s, farmer)
    p = farmer.properties
    assert "_active_weapon" not in p and "_farm_task" not in p and p["equipped_weapon"] == "iron_shortsword"


def test_the_scythe_swings_on_a_steady_beat_and_strikes_nothing():
    farmer = actor(_farm_work="reap")
    w = FarmWork()
    swings = 0
    for _ in range(int(6.0 / 0.05)):
        before = farmer.properties.get("is_shooting", False)
        w.update(0.05, (farmer,))
        swings += farmer.properties.get("is_shooting", False) and not before
    assert swings == int(6.0 / farm_work.SWING_EVERY)
    assert "health" not in farmer.properties                # a pulse, not a blow


def test_only_farmers_farm_and_their_thoughts_are_brief():
    assert farm_work.is_farmer({"npc_role": "Farmer"}) and not farm_work.is_farmer({"npc_role": "guard"})
    for state in ("REAPING", "TENDING"):
        key, text = mental_state.thought({"name": "Bram", "sched_state": state})
        assert key == state and 0 < len(text.split()) <= mental_state.THOUGHT_WORDS
