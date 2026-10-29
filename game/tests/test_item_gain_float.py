"""Collecting wheat shows a reusable item-gain message over its collector."""

import time

import pytest

from .. import farm_work
from ..rpg import inventory
from .test_farm_work import Field, actor
from .test_fizzle_float import _session


def test_harvesting_floats_one_wheat_over_the_farmer_and_fades(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(time, "monotonic", lambda: now[0])
    farmer = actor(pos=(1500.0, 0.0, 0.0), _farm_work="reap", _active_weapon="scythe")
    s = _session()
    s.farm_work.update(farm_work.SWING_EVERY, (farmer,), Field())
    assert inventory.quantity(farmer.properties["inventory"], "wheat") == 1
    [(thing, text, left, total)] = s.live_floats()
    assert thing is farmer and text == "+1 wheat" and left == pytest.approx(total) and total > 0
    now[0] += total + 0.1
    assert s.live_floats() == []


def test_item_gain_messages_support_other_items_and_quantities():
    s = _session()
    collector = actor()
    s.float_item_gain(collector, "egg", 2)
    assert [(f[0], f[1]) for f in s.live_floats()] == [(collector, "+2 egg")]


def test_item_gain_messages_are_only_shown_near_the_player():
    s = _session()
    s.float_item_gain(actor(pos=(90000.0, 0.0, 0.0)), "wheat")
    s.float_item_gain(actor(), "wheat", 0)
    assert s.live_floats() == []
