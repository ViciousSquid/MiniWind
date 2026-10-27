"""
Every head is drawn at one size.

A head-wearing actor's head *is* its billboard, so it is drawn at the actor's
``sprite_width`` / ``sprite_height``. Those came from the role's bestiary scale
or the map (90 for a sheep, 112 for a villager, 120 for a bandit, up to 210 for
a big monster), so heads on screen were all different sizes. A head now sets
both to :data:`game.rpg.heads.HEAD_SIZE`, wherever it is put on an actor: the
actor's constructor (the editor and map loading) and the runtime's head
assignment (Play start and loading a save).

Run:  python -m pytest game/tests/test_head_size.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from ..rpg import heads
from .fio_logic import FioLogic


def _size(thing):
    return thing.properties["sprite_width"], thing.properties["sprite_height"]


def test_a_head_overrides_the_roles_and_the_maps_size():
    from ..entities import Creature, NPC
    one = (heads.HEAD_SIZE, heads.HEAD_SIZE)
    assert _size(NPC(properties={"npc_role": "villager", "head": "head03"})) == one
    assert _size(NPC(properties={"npc_role": "bandit", "head": "greenskin01",
                                 "sprite_width": 200, "sprite_height": 200})) == one
    assert _size(Creature(properties={"npc_role": "sheep", "head": "sheep01",
                                      "sprite_width": 90, "sprite_height": 90})) == one
    assert _size(Creature(properties={"npc_role": "monster", "head": "spider01",
                                      "sprite_width": 210, "sprite_height": 210})) == one


def test_an_actor_without_a_head_keeps_its_own_size():
    from ..entities import Creature
    hen = Creature(properties={"npc_role": "hen", "sprite_width": 60,
                               "sprite_height": 60})
    assert _size(hen) == (60, 60)


# --- runtime wiring --------------------------------------------------------
class _FakeThing:
    def __init__(self, pos, properties):
        self.pos = list(pos)
        self.properties = dict(properties)


class _FakePlayer:
    def __init__(self, pos):
        self.pos = list(pos)
        self.properties = {}


class _FakeLogic(FioLogic):
    def __init__(self, things, player):
        self.things = things
        self.player = player


def test_heads_assigned_at_play_start_are_the_one_size():
    from ..runtime import MiniwindSession
    authored = _FakeThing([0, 272, 0], {"type": "creature", "name": "Big",
                                        "npc_role": "monster", "head": "spider01",
                                        "sprite_width": 210, "sprite_height": 210})
    rolled = _FakeThing([64, 272, 0], {"type": "npc", "name": "Anon",
                                       "npc_role": "villager",
                                       "sprite_width": 112, "sprite_height": 112})
    s = MiniwindSession(_FakeLogic([authored, rolled], _FakePlayer([0, 272, 0])),
                        cfg={"start_hour": 12.0, "minutes_per_day": 999999.0})
    s._assign_npc_heads()

    assert authored.properties["head"] == "spider01"
    assert heads.is_any_head(rolled.properties["head"])
    for thing in (authored, rolled):
        assert _size(thing) == (heads.HEAD_SIZE, heads.HEAD_SIZE)


# --- small heads -----------------------------------------------------------
def test_a_chicken_head_is_fifty_pixels():
    third = heads.CHICKEN_SIZE
    assert heads.size_for({"npc_role": "hen", "head": "chicken"}) == third
    assert heads.size_for({"head": "chicken02"}) == third       # its variants too
    assert heads.size_for({}, "chicken") == third               # the head it is given


def test_an_authored_head_scale_still_wins():
    assert heads.size_for({"head": "chicken", "head_scale": 2.0}) == heads.HEAD_SIZE * 2
    assert heads.size_for({"head": "head03"}) == heads.HEAD_SIZE


def test_the_shipped_dragon_is_five_times_the_player_size():
    import json
    from pathlib import Path
    from ..entities import Creature

    path = Path(__file__).resolve().parents[2] / 'maps' / 'cave06.json'
    cave = json.loads(path.read_text())
    dragon = next(t for t in cave['things']
                  if t['properties'].get('npc_role') == 'dragon')
    actor = Creature(pos=dragon['pos'], properties=dragon['properties'])
    assert _size(actor) == (heads.HEAD_SIZE * 5, heads.HEAD_SIZE * 5)


def test_a_hen_wears_the_chicken_head(tmp_path, monkeypatch):
    folder = tmp_path / heads.HEAD_DIR
    folder.mkdir(parents=True)
    monkeypatch.setattr(heads, "_repo_root", lambda: str(tmp_path))
    assert heads.animal_head("hen") == heads.PLACEHOLDER_HEAD     # not drawn yet
    (folder / "chicken.png").write_bytes(b"")
    assert heads.animal_head("hen") == "chicken"
    (folder / "hen.png").write_bytes(b"")                       # its own art wins
    assert heads.animal_head("hen") == "hen"


def test_every_variant_of_an_animals_head_is_worn(tmp_path, monkeypatch):
    import random
    folder = tmp_path / heads.HEAD_DIR
    folder.mkdir(parents=True)
    monkeypatch.setattr(heads, "_repo_root", lambda: str(tmp_path))
    for name in ("chicken", "chicken2", "chicken3", "wolf01", "wolf02", "wolfsbane"):
        (folder / f"{name}.png").write_bytes(b"")
    assert heads.animal_heads("hen") == ["chicken", "chicken2", "chicken3"]
    assert heads.animal_heads("wolf") == ["wolf01", "wolf02"]     # not wolfsbane
    # Dealt across a flock, the variants come out in even numbers.
    deck, rng = {}, random.Random(4)
    flock = [heads.animal_head("hen", rng, deck) for _ in range(30)]
    assert sorted(set(flock)) == ["chicken", "chicken2", "chicken3"]
    assert {flock.count(h) for h in set(flock)} == {10}
    pack = [heads.animal_head("wolf", rng, deck) for _ in range(7)]
    assert sorted(pack.count(h) for h in set(pack)) == [3, 4]
    # Every chicken is small, whichever it is.
    assert {heads.size_for({"head": h}) for h in flock} == {heads.CHICKEN_SIZE}
