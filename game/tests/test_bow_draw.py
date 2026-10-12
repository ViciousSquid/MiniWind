"""
Drawing the bow with right mouse.

With a bow in hand, holding right mouse draws it (``bow_charge`` 0..1, shown
by the HUD as a filling pie); releasing looses an arrow that flies further the
longer the bow was drawn. A left click, switching weapons, opening a screen or
a conversation lowers the bow without loosing, and the pie goes.

Run:  python -m pytest game/tests/test_bow_draw.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from .. import runtime as rt
from ..rpg import inventory as inv, items
from .fio_logic import FioLogic


class _Logic(FioLogic):
    def __init__(self):
        self.things = []
        self.player = None


def _session(arrows=10):
    s = rt.MiniwindSession(_Logic(), cfg={"start_hour": 12.0,
                                          "minutes_per_day": 999999.0})
    s.begin_new_character("T", "imperial", "warrior", "none", "male", head="head01")
    c = s.game.character
    inv.add_item(c.inventory, items.make("short_bow"))
    s.game.equip("short_bow")
    if arrows:
        inv.add_item(c.inventory, items.make("iron_arrow", arrows))
        s.game.equip("iron_arrow")
    else:                                   # take away any starting arrows
        s.game.unequip(items.SLOT_AMMO)
        c.inventory = [st for st in c.inventory
                       if (items.get(st.get("id")) or None) is None
                       or items.get(st.get("id")).category != items.AMMO]
    s._attack_cooldown = 0.0
    shots = []
    s._spawn_player_arrow_projectile = lambda max_dist=rt.BOW_MAX_RANGE: shots.append(max_dist)
    return s, shots


def _hold(s, seconds, step=1 / 60):
    t = 0.0
    while t < seconds:
        s._update_bow_draw(step)
        t += step


def test_holding_draws_the_bow_and_releasing_looses_a_full_shot():
    s, shots = _session()
    s.bow_draw_input("press")
    _hold(s, rt.BOW_FULL_DRAW_SECONDS / 2)
    assert 0.4 < s.bow_charge < 0.6
    _hold(s, rt.BOW_FULL_DRAW_SECONDS)
    assert s.bow_charge == 1.0
    s.bow_draw_input("release")
    s._update_bow_draw(1 / 60)
    assert s.bow_charge is None                      # the pie goes
    assert shots == [rt.BOW_MAX_RANGE]


def test_a_short_draw_is_a_short_shot():
    s, shots = _session()
    s.bow_draw_input("press")
    _hold(s, rt.BOW_FULL_DRAW_SECONDS / 4)
    s.bow_draw_input("release")
    s._update_bow_draw(1 / 60)
    assert rt.BOW_MIN_RANGE < shots[0] < (rt.BOW_MIN_RANGE + rt.BOW_MAX_RANGE) / 2


def test_cancelling_lowers_the_bow_without_loosing():
    s, shots = _session()
    s.bow_draw_input("press")
    _hold(s, 0.5)
    s.bow_draw_input("cancel")
    s._update_bow_draw(1 / 60)
    assert s.bow_charge is None and shots == []
    s.bow_draw_input("release")
    s._update_bow_draw(1 / 60)
    assert shots == []


def test_switching_weapons_lowers_the_bow():
    s, shots = _session()
    s.bow_draw_input("press")
    _hold(s, 0.3)
    s.game.unequip(items.SLOT_WEAPON)
    _hold(s, 0.1)
    assert s.bow_charge is None and shots == []


def test_opening_a_screen_lowers_the_bow():
    s, shots = _session()
    s.bow_draw_input("press")
    _hold(s, 0.3)
    s.open_screen = "inventory"
    _hold(s, 0.1)
    assert s.bow_charge is None


def test_no_arrows_no_draw():
    s, shots = _session(arrows=0)
    s.bow_draw_input("press")
    _hold(s, 0.5)
    assert s.bow_charge is None
