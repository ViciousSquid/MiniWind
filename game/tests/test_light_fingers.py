"""Light Fingers: every theft trains it, and a deft hand is harder to see
stealing -- a theft is seen at sight x (1 - 0.003 x Light Fingers).

Run:  python -m pytest game/tests/test_light_fingers.py -q
"""

from __future__ import annotations

import pytest

from ..rpg import items
from ..sim import ownership, perception
from ..sim.events import WorldEvent
from .test_world_entities import _FakePlayer, _FakeThing, _session


class _Watcher:
    def __init__(self, x, **props):
        self.pos = [x, 0.0, 0.0]
        self.properties = dict(props, name="watcher")


def test_light_fingers_shrinks_the_sight_of_a_theft_only():
    for skill, factor in ((0, 1.0), (50, 0.85), (100, 0.7)):
        props = {"sleight": perception.sleight(skill)}
        assert perception.stealth_factor(props, "theft") == pytest.approx(factor)
        assert perception.stealth_factor(props, "attack") == 1.0
    # Sneaking and Light Fingers multiply: 0.5 x 0.7 at both mastered.
    both = {"sneaking": True, "stealth": perception.sneak_stealth(0),
            "sleight": perception.sleight(100)}
    assert perception.stealth_factor(both, "theft") == pytest.approx(0.35)

    watcher = _Watcher(800.0, sight_range=1000)          # 0.8 of its sight
    theft = WorldEvent("theft", pos=(0, 0, 0))
    clumsy = {"sleight": perception.sleight(5)}
    deft = {"sleight": perception.sleight(100)}
    assert perception.witnesses(theft, [watcher], actor_props=clumsy)
    assert not [p for p in perception.witnesses(theft, [watcher], actor_props=deft)
                if p.mode == "sight"]
    blow = WorldEvent("attack", pos=(0, 0, 0))
    assert [p for p in perception.witnesses(blow, [watcher], actor_props=deft)
            if p.mode == "sight"]


def test_every_theft_trains_light_fingers_and_the_player_carries_it():
    chest = _FakeThing([20, 0, 0], {"type": "container", "name": "Chest",
                                    "inventory": [items.make("bread", 1),
                                                  items.make("bread", 1)]})
    ownership.set_owner(chest.properties, "npc:miller", "The Miller")
    s = _session([chest], _FakePlayer([0, 0, 0]))
    c = s.game.character
    c.skills["light_fingers"] = 30
    assert s.player_actor.properties["sleight"] == pytest.approx(0.15)
    practice = []
    real = c.use_skill
    c.use_skill = lambda sid, difficulty=1.0: (practice.append((sid, difficulty)),
                                               real(sid, difficulty))[1]
    s.open_container(chest)
    assert s.container_take_is_theft()
    assert s.take_from_container(0)
    assert ("light_fingers", 1.0) in practice
    # Taking what is yours trains nothing.
    practice.clear()
    ownership.set_owner(chest.properties, "")
    assert s.take_from_container(0)
    assert not [p for p in practice if p[0] == "light_fingers"]
