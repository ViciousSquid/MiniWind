"""
Corpses are looted, not emptied into the pack at the kill.

A kill rolls the body's loot table onto the body; E beside it opens what it
carried in the container screen, from which the player takes what they want
(gold is taken as coin). A death the player did not cause is stocked the
first time the body is searched.

Run:  python -m pytest game/tests/test_corpse_loot.py -q
"""

from __future__ import annotations

import random

import pytest

from .fio_logic import FioLogic


class _Thing:
    def __init__(self, name, pos=(0.0, 0.0, 0.0), **props):
        self.pos = list(pos)
        self.properties = {"name": name, "display_name": name, **props}


class _Logic(FioLogic):
    def __init__(self, things=()):
        self.things = list(things)
        self.player = _Thing("You", is_player=True)


def _session(*things):
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(things), cfg={})
    s.game.dice = None                 # plain random rolls, nothing on screen
    s.game.rng = random.Random(3)
    return s


def _bandit(pos=(40.0, 0.0, 0.0), **props):
    return _Thing("Bandit", pos, type="npc", npc_role="bandit", loot="bandit",
                  health=0, **props)


def test_a_kill_leaves_its_loot_on_the_body():
    body = _bandit()
    s = _session(body)
    before = [dict(st) for st in s.game.character.inventory]
    gold = s.game.character.gold
    for seed in range(50):               # until the table drops something
        body.properties.pop("loot_rolled", None)
        body.properties["inventory"] = []
        s.game.rng = random.Random(seed)
        s.game.on_kill(body.properties)
        if body.properties["inventory"]:
            break
    assert body.properties["inventory"], "the bandit table never dropped anything"
    assert body.properties["loot_rolled"]
    assert s.game.character.inventory == before        # nothing went to the pack
    assert s.game.character.gold == gold


def test_e_on_a_body_finds_only_one_with_something_on_it():
    alive = _bandit(pos=(10.0, 0.0, 0.0))
    empty = _bandit(pos=(20.0, 0.0, 0.0), dead=True, loot_rolled=True, inventory=[])
    s = _session(alive, empty)
    assert s.nearest_corpse([0.0, 0.0, 0.0]) is None
    full = _bandit(pos=(60.0, 0.0, 0.0), dead=True, loot_rolled=True,
                   inventory=[{"id": "potion_heal_minor", "name": "Potion", "qty": 1}])
    s = _session(alive, empty, full)
    assert s.nearest_corpse([0.0, 0.0, 0.0]) is full
    assert s.nearest_corpse([5000.0, 0.0, 0.0]) is None          # out of reach


def test_looting_takes_items_and_counts_coin():
    from ..rpg import items
    body = _bandit(dead=True, loot_rolled=True,
                   inventory=[items.make("potion_heal_minor", 2), items.make("gold", 17)])
    s = _session(body)
    gold = s.game.character.gold
    assert s.loot_corpse(body)
    assert s.open_screen == "container"
    assert "Bandit" in s.container_name()
    assert s.take_all_from_container() == 2
    assert s.game.character.gold == gold + 17
    assert any(st["id"] == "potion_heal_minor" and st["qty"] >= 2
               for st in s.game.character.inventory)
    assert not any(st["id"] == "gold" for st in s.game.character.inventory)
    assert body.properties["inventory"] == []
    assert s.nearest_corpse([0.0, 0.0, 0.0]) is None              # emptied


def test_a_death_the_player_did_not_cause_is_stocked_when_searched():
    body = _bandit(dead=True, inventory="iron_shortsword")
    s = _session(body)
    assert s.nearest_corpse([0.0, 0.0, 0.0]) is body              # not yet rolled
    s.loot_corpse(body)
    assert body.properties["loot_rolled"]
    ids = [st["id"] for st in s.container_inventory()]
    assert "iron_shortsword" in ids                               # its own sword too


def test_the_loot_screen_takes_the_mouse(qt_app):
    from PyQt5 import QtGui
    from ..rpg import items
    from ..ui import hits, screens
    body = _bandit(dead=True, loot_rolled=True, inventory=[items.make("gold", 5)])
    s = _session(body)
    s.loot_corpse(body)
    pixmap = QtGui.QPixmap(1280, 800)
    painter = QtGui.QPainter(pixmap)
    hits.begin()
    screens.draw(painter, s, 1280, 800)
    hits.end()
    painter.end()
    labels = [lab for _, lab in hits.targets()]
    assert "take:0" in labels and "Take all" in labels and "Close" in labels
    rect = next(r for r, lab in hits.targets() if lab == "take:0")
    gold = s.game.character.gold
    assert hits.click(rect.center().x(), rect.center().y())
    hits.run_clicks(s)
    assert s.game.character.gold == gold + 5
    hits.clear()


def test_bodies_and_chests_open_in_a_window_titled_loot(qt_app):
    from engine.floating_windows import WindowManager
    from ..host import MiniwindGame
    from ..rpg import items
    body = _bandit(dead=True, loot_rolled=True, inventory=[items.make("gold", 5)])
    chest = _Thing("Old Chest", type="container", inventory=[])
    s = _session(body, chest)
    viewport = type("V", (), {"window_manager": WindowManager()})()
    game = MiniwindGame.__new__(MiniwindGame)
    s.loot_corpse(body)
    game._sync_overlay_windows(s, viewport, 1280, 800)
    assert s._overlay_win.title == "Loot"
    s.close_container()
    game._sync_overlay_windows(s, viewport, 1280, 800)
    s.open_container(chest)
    game._sync_overlay_windows(s, viewport, 1280, 800)
    assert s._overlay_win.title == "Loot"


def test_the_e_that_opened_the_loot_does_not_close_it_when_frames_are_slow():
    """The held-key snapshot comes from the UI thread once a frame; the use
    key is latched at once. With slow frames, ticks pass before the snapshot
    shows E down at all -- the late "E pressed" edge must still not close
    the screen it opened."""
    from plugins.api import TickContext, key_code
    from ..host import MiniwindGame, K_INTERACT, INTERACT_GRACE_SECONDS
    game = MiniwindGame.__new__(MiniwindGame)
    e = frozenset({key_code(K_INTERACT)})
    game._hold_interact()                       # E opened the loot
    t0 = game._suppress_since
    for i in range(3):                          # snapshot not caught up yet
        game._update_interact_hold(TickContext(keys=frozenset()), now=t0 + 0.016 * i)
        assert game._suppress_interact
    game._update_interact_hold(TickContext(keys=e), now=t0 + 0.06)      # the late edge
    assert game._suppress_interact
    game._update_interact_hold(TickContext(keys=frozenset()), now=t0 + 0.2)  # let go
    assert not game._suppress_interact

    game._hold_interact()                       # a tap the snapshot never saw
    t0 = game._suppress_since
    game._update_interact_hold(TickContext(keys=frozenset()), now=t0 + 0.1)
    assert game._suppress_interact
    game._update_interact_hold(TickContext(keys=frozenset()),
                               now=t0 + INTERACT_GRACE_SECONDS + 0.01)
    assert not game._suppress_interact
