"""
A spider (an actor wearing a ``spider`` head) is never seen holding a weapon:
whatever it carries, nothing is drawn in its legs.

Run:  python -m pytest game/tests/test_spider_weapons.py -q
"""

from __future__ import annotations

from types import SimpleNamespace

from ..held_weapons import HeldWeapons


def _actor(head):
    return SimpleNamespace(pos=[10.0, 0.0, 10.0], properties={
        "head": head, "equipped_weapon": "iron_shortsword", "handed": "right"})


def _overhead(*actors):
    session = SimpleNamespace(_player_pos=lambda: (0.0, 0.0, 0.0), _actors=list(actors))
    return HeldWeapons(session).overhead()


def test_a_spider_carrying_a_sword_shows_no_weapon():
    assert _overhead(_actor("spider01")) == []
    assert _overhead(_actor("spider02")) == []


def test_everyone_else_still_shows_theirs():
    held = _overhead(_actor("head05"), _actor("spider01"))
    assert [h[2] for h in held] == ["iron_shortsword"]
