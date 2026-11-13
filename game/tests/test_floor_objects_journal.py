"""Containers and pickups drawn on the floor are kept current from Fio's
change journal (only what changed is re-read) and always equal the list
derived from scratch."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5")
pytestmark = pytest.mark.qt

from engine.change_journal import touch
from editor.things import Thing
from game.ui import world_objects


class _Session:
    def __init__(self, containers, pickups):
        self.logic = None
        self.player = [0.0, 0.0, 0.0]
        self.buckets = {"container": list(containers), "itempickup": list(pickups)}

    def _player_pos(self):
        return self.player

    def _things_of_type(self, kind):
        return self.buckets.get(kind, ())


def _check(session):
    got = world_objects.visible(session)
    assert got == world_objects.visible_reference(session)
    return got


def test_moves_pickups_and_parking_reach_the_floor_list():
    chest = Thing([100.0, 0.0, 0.0], {"type": "container", "container_kind": "chest"})
    barrel = Thing([5000.0, 0.0, 0.0], {"type": "container", "container_kind": "barrel"})
    sword = Thing([0.0, 0.0, 200.0], {"type": "itempickup", "item_id": "iron_shortsword"})
    session = _Session([chest, barrel], [sword])
    first = _check(session)
    assert len(first) == 2                      # the barrel is out of range

    barrel.pos = [300.0, 0.0, 0.0]              # assigned: journalled
    assert len(_check(session)) == 3

    sword.properties["dead"] = sword.properties["hidden"] = True
    touch(sword)                                # taken
    assert len(_check(session)) == 2

    chest.properties["_bw_parked_hidden"] = True
    touch(chest)                                # parked by Big World
    assert len(_check(session)) == 1

    session.player = [5000.0, 0.0, 0.0]         # the player walks off
    assert _check(session) == []


def test_a_new_object_rebuilds_the_list():
    chest = Thing([0.0, 0.0, 0.0], {"type": "container"})
    session = _Session([chest], [])
    assert len(_check(session)) == 1
    session.buckets["itempickup"] = [Thing([10.0, 0.0, 0.0],
                                           {"type": "itempickup", "item_id": "torch"})]
    assert len(_check(session)) == 2
