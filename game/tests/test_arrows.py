"""
Arrows in flight are drawn as arrows.

Fio draws every projectile as one shared billboard (a green orb). The game
takes its arrows out of that pass and draws them itself: ``MiniwindSession.
_split_projectiles`` tells Fio which rows to keep and publishes the arrows
(position, velocity, art) for game/ui/arrows.py, which draws each flat with
its head along its flight.

Run:  python -m pytest game/tests/test_arrows.py -q
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from ..ui import arrows
from .fio_logic import FioLogic


class _Store:
    """The columns of Fio's ProjectileStore the split reads."""

    def __init__(self, rows):
        self.pos = np.array([r[0] for r in rows], dtype=np.float32)
        self.vel = np.array([r[1] for r in rows], dtype=np.float32)
        self.tag = np.array([r[2] for r in rows], dtype=np.int64)


def _session():
    from ..runtime import MiniwindSession

    class _Logic(FioLogic):
        def __init__(self):
            self.things = []
            self.player = None

    return MiniwindSession(_Logic(), cfg={"start_hour": 12.0,
                                          "minutes_per_day": 999999.0})


def test_fio_keeps_spell_bolts_and_the_game_takes_its_arrows():
    s = _session()
    s._arrow_tags = {7: "assets/sprites/items/steel_arrow.png", 9: arrows.DEFAULT_ARROW}
    store = _Store([((0, 48, 0), (1600, 0, 0), 7),        # an arrow
                    ((5, 48, 5), (0, 0, 900), 0),         # a spell bolt
                    ((9, 48, 9), (0, 0, -1600), 9)])      # another arrow
    keep = s._split_projectiles(store, 3)
    assert keep.tolist() == [False, True, False]
    assert [a[2] for a in s.arrows_in_flight] == [
        "assets/sprites/items/steel_arrow.png", arrows.DEFAULT_ARROW]
    assert s.arrows_in_flight[0][0] == (0.0, 48.0, 0.0)


def test_a_landed_arrow_is_forgotten():
    s = _session()
    s._arrow_tags = {7: arrows.DEFAULT_ARROW, 8: arrows.DEFAULT_ARROW}
    s._split_projectiles(_Store([((0, 48, 0), (1600, 0, 0), 8)]), 1)
    assert set(s._arrow_tags) == {8}


def test_with_no_arrows_fio_draws_everything():
    s = _session()
    assert s._split_projectiles(_Store([((0, 48, 0), (0, 0, 900), 0)]), 1) is None
    assert s.arrows_in_flight == ()


def test_each_ammo_has_its_own_art_or_the_plain_arrow():
    assert arrows.arrow_sprite("steel_arrow") == "assets/sprites/items/steel_arrow.png"
    assert arrows.arrow_sprite("no_such_arrow") == arrows.DEFAULT_ARROW
    assert arrows.arrow_sprite(None) == arrows.DEFAULT_ARROW


def test_an_arrow_points_along_its_flight():
    assert arrows.heading_of((0.0, 0.0, 1.0)) == 0.0
    assert math.isclose(arrows.heading_of((1.0, 0.0, 0.0)), math.pi / 2)
