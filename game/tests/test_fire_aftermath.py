"""
After a grass fire (game/fire_aftermath.py): everyone knows it for certain,
the wheat it took grows no grain, farmers whose fields burnt are furious or
terrified and say so, and once the scorch has gone they sow again, hard.
"""

from __future__ import annotations

from types import SimpleNamespace

from .. import entities
from .. import farm_work
from .. import fire_aftermath as fa
from ..grass_fire import CELL, cell_of


class _Store(dict):
    def get(self, key, default=None):
        return super().get(key, default)

    def set(self, key, value):
        self[key] = value


def _session(npcs=(), burning=True):
    clock = SimpleNamespace(day=1, hour=10.0)
    fire = SimpleNamespace(burning={(0, 0): [1, 1, 1, 0, 0]} if burning else {}, burnt=set())
    s = SimpleNamespace(clock=clock, store=_Store(), grass_fire=fire, logic=None, living=None,
                        director=None, memory=SimpleNamespace(key="test"),
                        npcs=lambda: list(npcs), _player_pos=lambda: None,
                        SCORCH_ART=("a.png",))
    s.barks = []
    s.bark = lambda thing, text, *a: s.barks.append((thing.properties.get("name"), text))
    s.bark_later = lambda thing, text, d: s.barks.append((thing.properties.get("name"), text))
    return s


def _farmer(name, rows, courage=0.6):
    return entities.NPC(pos=[0.0, 0.0, 0.0], properties={
        "name": name, "npc_role": "farmer", "courage": courage, "_farm_rows": rows})


def _burn(after, s, keys):
    after.ignited(0.0, 0.0)
    for k in keys:
        after.burnt(k)
    s.grass_fire.burning = {}
    after.update()


def test_a_burnt_field_makes_its_farmer_furious_or_terrified():
    rows = [[CELL * 0.5, CELL * 0.5], [CELL * 1.5, CELL * 0.5]]
    brave, timid = _farmer("Bram", rows, 0.7), _farmer("Wynn", rows, 0.2)
    far = _farmer("Hobb", [[CELL * 40.5, CELL * 40.5]])
    s = _session([brave, timid, far])
    after = fa.FireAftermath(s)
    after._is_wheat = lambda key: True
    _burn(after, s, [cell_of(*rows[0]), cell_of(*rows[1])])
    assert brave.properties["fire_mood"] == "furious"
    assert timid.properties["fire_mood"] == "terrified"
    assert "fire_mood" not in far.properties                  # his field didn't burn
    now = 34.0
    assert brave.properties["resow_from"] == now + fa.SCORCH_HOURS
    assert not after.sowing(brave.properties, now)            # not while it's scorched


def test_farmers_cry_fire_and_speak_of_it_when_the_player_is_near():
    rows = [[CELL * 0.5, CELL * 0.5]]
    bram = _farmer("Bram", rows, 0.7)
    s = _session([bram])
    after = fa.FireAftermath(s)
    after._is_wheat = lambda key: True
    after.ignited(0.0, 0.0)
    assert any(text in fa._FIRE_CRIES for _n, text in s.barks)
    after.burnt(cell_of(*rows[0]))
    s.grass_fire.burning = {}
    s._player_pos = lambda: [0.0, 0.0, 100.0]
    s.barks.clear()
    after.update()
    (who, line), = s.barks
    assert who == "Bram" and line in fa._FURIOUS + fa._LOST_FOOD
    after.update()
    assert len(s.barks) == 1                                  # not again at once


def test_the_scorch_goes_then_the_field_lies_bare_until_it_is_sown():
    rows = [[CELL * 0.5, CELL * 0.5], [CELL * 2.5, CELL * 0.5]]
    bram = _farmer("Bram", rows)
    s = _session([bram])
    after = fa.FireAftermath(s)
    after._is_wheat = lambda key: True
    keys = [cell_of(*r) for r in rows]
    _burn(after, s, keys)
    s.grass_fire.burnt.update(keys)
    s.clock.day, s.clock.hour = 1 + 3, 11.0                   # 3 days on: the scorch has gone
    after.update()
    assert all(after.burns[0]["cells"][k][1] == fa.BARE for k in keys)
    now = s.clock.day * 24 + s.clock.hour
    assert after.sowing(bram.properties, now)
    assert sorted(map(tuple, after.sow_points(bram, now))) == sorted(map(tuple, rows))
    assert after.sow(*rows[0]) == 1
    assert after.sow_points(bram, now) == [rows[1]]
    assert keys[0] not in s.grass_fire.burnt                  # it can burn again


def test_the_whole_burnt_field_is_sown_not_just_the_rows_walked():
    rows = [[CELL * 0.5, CELL * 0.5]]
    bram = _farmer("Bram", rows)
    s = _session([bram])
    after = fa.FireAftermath(s)
    after._is_wheat = lambda key: True
    keys = [(i, j) for i in range(4) for j in range(3)]     # a 4 x 3 patch round the row
    _burn(after, s, keys)
    s.clock.day, s.clock.hour = 4, 11.0
    for _ in range(3):
        after.update()
    now = 4 * 24 + 11.0
    points = after.sow_points(bram, now)
    assert len(points) == len(keys)                          # all of it, though one row
    while points:
        after.sow(*points[0])
        points = after.sow_points(bram, now)
    after.update()                                           # the empty burn is let go
    assert not after.burns


def test_heath_grows_back_by_itself():
    s = _session([])
    after = fa.FireAftermath(s)
    after._is_wheat = lambda key: False
    _burn(after, s, [(5, 5)])
    s.clock.day = 5
    after.update()
    assert not after.burns


def test_burns_are_saved_and_come_back():
    rows = [[CELL * 0.5, CELL * 0.5]]
    s = _session([_farmer("Bram", rows)])
    after = fa.FireAftermath(s)
    after._is_wheat = lambda key: True
    _burn(after, s, [cell_of(*rows[0])])
    after.persist()
    again = fa.FireAftermath(s)
    s.grass_fire.burnt.clear()
    again.restore()
    assert cell_of(*rows[0]) in again.burns[0]["cells"]
    assert cell_of(*rows[0]) in s.grass_fire.burnt            # still unburnable


def test_no_grain_is_reaped_from_scorched_ground():
    import numpy as np
    from engine import terrain_biomes as tb

    class _Terrain:
        GRASS_PAINT_CLEAR = 0.25
        biome_map = np.zeros((2, 2, 5), np.uint8)

        def __init__(self, scorched):
            self.scorched = scorched

        def biome_weights_batch(self, xs, zs):
            w = np.zeros((1, 5), np.float32)
            w[0, tb.WHEAT] = 1.0
            return w

        def _paint_alpha_batch(self, xs, zs):
            return np.array([1.0 if self.scorched else 0.0], np.float32)

    for scorched, gained in ((False, 1), (True, 0)):
        npc = _farmer("Bram", [])
        farm_work.FarmWork()._harvest(npc, _Terrain(scorched))
        assert sum(int(it.get("qty", 1)) for it in npc.properties.get("inventory", [])
                   if it.get("id") == "wheat") == gained


def test_a_fire_is_news_everyone_is_sure_of():
    from ..sim import rumours, knowledge
    fact = {"kind": "grass_fire", "item": "the wheat near Millbrook", "source": knowledge.SOURCE_TOLD,
            "certainty": 0.9, "day": 1, "e": 7}
    line = rumours.line(fact, today=1)
    assert line.split(":")[0] in ("It's true", "It's certain") or line.startswith("No word of a lie")
    assert "fire swept through the wheat near Millbrook" in line


def test_word_of_a_fire_loses_nothing_in_the_telling():
    from .. import runtime
    me = SimpleNamespace(player_key="player")
    assert runtime.MiniwindSession._rumour_decay(me, {"kind": "grass_fire", "actor": ""}) == 0.0
    assert runtime.MiniwindSession._rumour_decay(me, {"kind": "theft", "actor": "bram"}) is None


def test_sowing_farmers_work_past_their_usual_hours():
    bram = _farmer("Bram", [])
    s = _session([bram])
    s.fire_aftermath = fa.FireAftermath(s)
    s.clock.day, s.clock.hour = 4, 5.5
    now = 4 * 24 + 5.5
    bram.properties.update(resow_from=now - 1, resow_until=now + 40)
    assert farm_work.sowing_late(s, bram)                      # up before the schedule's day
    s.clock.hour = 21.0
    assert not farm_work.sowing_late(s, bram)                  # but they do sleep
