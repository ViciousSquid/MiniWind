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
    s.begin_new_character("T", "valian", "warrior", "none", "male", head="head01")
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


# -- the bow, heard (bow_draw.mp3 / bow_release.mp3, cut from bowsounds.mp3) ----
def _heard(s):
    from types import SimpleNamespace
    queued = []
    s.logic.game_state = SimpleNamespace(queue_sound=queued.append)
    s.logic.player = SimpleNamespace(pos=(120.0, 64.0, -40.0), angle=0.0)   # the archer
    return queued


def _files(queued):
    return [q.get("file") or ("stop " + q["entity_id"]) for q in queued]


def test_drawing_plays_the_draw_and_loosing_cuts_it_for_the_release():
    s, shots = _session()
    queued = _heard(s)
    s.bow_draw_input("press")
    s._update_bow_draw(1 / 60)
    assert _files(queued) == ["bow_draw.mp3"]                 # the pie is up
    draw = queued[0]
    assert draw["entity_id"] == rt.BOW_DRAW_CHANNEL and draw["stoppable"]
    assert draw["position"] == list(s._player_pos()) and not draw.get("global")   # from the archer
    _hold(s, 1.0)
    assert _files(queued) == ["bow_draw.mp3"]                 # once, not every tick
    s.bow_draw_input("release")
    s._update_bow_draw(1 / 60)
    assert _files(queued) == ["bow_draw.mp3", "stop player_bow_draw", "bow_release.mp3"]
    assert queued[-1]["position"] == list(s._player_pos()) and not queued[-1].get("global")
    assert shots


def test_lowering_the_bow_cuts_the_draw_and_makes_no_release():
    s, shots = _session()
    queued = _heard(s)
    s.bow_draw_input("press")
    _hold(s, 0.5)
    s.bow_draw_input("cancel")
    s._update_bow_draw(1 / 60)
    assert _files(queued) == ["bow_draw.mp3", "stop player_bow_draw"] and shots == []


def test_opening_a_screen_mid_draw_cuts_it_too():
    s, _shots = _session()
    queued = _heard(s)
    s.bow_draw_input("press")
    _hold(s, 0.3)
    s.open_screen = "inventory"
    s._update_bow_draw(1 / 60)
    assert _files(queued) == ["bow_draw.mp3", "stop player_bow_draw"]


def test_no_arrows_no_draw_and_a_failed_loose_no_release():
    s, shots = _session(arrows=0)
    queued = _heard(s)
    s.bow_draw_input("press")
    s._update_bow_draw(1 / 60)
    assert queued == [] and s.bow_charge is None              # never drawn
    s2, shots2 = _session()
    queued2 = _heard(s2)
    s2.bow_draw_input("press")
    _hold(s2, 0.5)
    s2._attack_cooldown = 5.0                                 # cannot loose yet
    s2.bow_draw_input("release")
    s2._update_bow_draw(1 / 60)
    assert shots2 == [] and _files(queued2) == ["bow_draw.mp3", "stop player_bow_draw"]


def test_the_clips_are_cut_from_bowsounds_and_ship():
    from pathlib import Path
    sounds = Path(rt.SOUND_DIR)
    assert (sounds / "bowsounds.mp3").exists()
    for name in (rt.BOW_DRAW_SOUND, rt.BOW_RELEASE_SOUND):
        data = (sounds / name).read_bytes()
        assert data[:3] == b"ID3" or data[0] == 0xFF
        assert rt.sound_available(name)


def test_the_draw_follows_an_archer_who_walks_while_drawing():
    from types import SimpleNamespace
    s, _shots = _session()
    queued = _heard(s)
    s.bow_draw_input("press")
    s._update_bow_draw(1 / 60)
    _hold(s, 0.2)
    assert [q for q in queued if q.get("action") == "move"] == []   # standing still
    s.logic.player = SimpleNamespace(pos=(300.0, 64.0, -40.0), angle=0.0)
    s._update_bow_draw(1 / 60)
    moves = [q for q in queued if q.get("action") == "move"]
    assert moves == [{"action": "move", "entity_id": rt.BOW_DRAW_CHANNEL,
                      "position": [300.0, 64.0, -40.0]}]
