"""Tending a cow collects its actual milk yields and frees production slots."""

from ..rpg import inventory, items
from ..sim import production
from .test_corpse_loot import _Thing
from .test_fizzle_float import _session


def _farm(cow_pos=(150.0, 0.0, 0.0), **cow_props):
    farmer = _Thing("Farmer", (100.0, 0.0, 0.0), type="npc", npc_role="farmer")
    props = dict(type="creature", npc_role="cow", produces="milk", produce_every_hours=1.0)
    props.update(cow_props)
    cow = _Thing("Bessie", cow_pos, **props)
    s = _session(farmer, cow)
    s.clock.hour = 12.0
    return s, farmer, cow


def _produce(s, cow, hours=1.0):
    s.director.tick_production([cow], hours)
    for producer, yielded in s.director.drain_yields():
        s._place_yield(producer, yielded)


def test_a_farmer_tending_a_cow_collects_a_bucket_and_production_resumes():
    s, farmer, cow = _farm(produce_max=1)
    _produce(s, cow)
    [bucket] = s._things_of_type("itempickup")
    assert production.pending(cow.properties) == 1
    assert s.farm_work.drive(s, farmer)
    inv = inventory.get_inventory(farmer)
    assert inventory.quantity(inv, "milk") == 1
    assert bucket.properties["dead"] and bucket.properties["hidden"]
    assert production.pending(cow.properties) == 0
    assert [(f[0], f[1]) for f in s.live_floats()] == [(farmer, "+1 bucket of milk")]
    s.farm_work.drive(s, farmer)
    assert inventory.quantity(inv, "milk") == 1              # bucket was already taken
    _produce(s, cow)
    s.farm_work.drive(s, farmer)
    assert inventory.quantity(inv, "milk") == 2              # next produced bucket


def test_the_farmer_must_reach_the_cow_before_collecting():
    s, farmer, cow = _farm(cow_pos=(500.0, 0.0, 0.0))
    _produce(s, cow)
    assert s.farm_work.drive(s, farmer)
    assert inventory.quantity(inventory.get_inventory(farmer), "milk") == 0
    assert s.live_floats() == []
    farmer.pos = [450.0, 0.0, 0.0]
    assert s.farm_work.drive(s, farmer)
    assert inventory.quantity(inventory.get_inventory(farmer), "milk") == 1


def test_an_empty_or_dead_cow_gives_no_milk():
    s, farmer, cow = _farm()
    assert s.farm_work.drive(s, farmer)
    assert inventory.quantity(inventory.get_inventory(farmer), "milk") == 0
    assert s.live_floats() == []
    _produce(s, cow)
    cow.properties["dead"] = True
    assert not s.farm_work.drive(s, farmer)
    assert inventory.quantity(inventory.get_inventory(farmer), "milk") == 0


def test_a_farmer_does_not_take_another_cows_bucket():
    s, farmer, cow = _farm()
    other = _Thing("Clover", (500.0, 0.0, 0.0), type="creature", npc_role="cow",
                   produces="milk", produce_every_hours=1.0)
    s.logic.things.append(other)
    s._type_index_token = None
    _produce(s, other)
    assert s.farm_work.drive(s, farmer)
    assert inventory.quantity(inventory.get_inventory(farmer), "milk") == 0
    assert production.pending(other.properties) == 1


def test_a_cow_configured_to_keep_its_milk_hands_over_an_existing_bucket():
    s, farmer, cow = _farm(produce_into=production.INTO_SELF, inventory=[items.make("milk")])
    assert s.farm_work.drive(s, farmer)
    assert inventory.quantity(inventory.get_inventory(farmer), "milk") == 1
    assert inventory.quantity(inventory.get_inventory(cow), "milk") == 0
    s.farm_work.drive(s, farmer)
    assert inventory.quantity(inventory.get_inventory(farmer), "milk") == 1
