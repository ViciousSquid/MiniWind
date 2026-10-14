"""
The player is a head, and no NPC ever wears it.

Character creation picks the player's head; the player's overhead sprite is
that head (``logic.player_head_sprite``), and every NPC, creature and monster
is given a head that is not the player's -- including one whose head was set
in the editor or the map, which is re-rolled when it is the player's.

Run:  python -m pytest game/tests/test_player_head.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from ..rpg import heads
from .fio_logic import FioLogic


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


class _Globals:
    """An in-memory stand-in for the plugin host's global store."""

    def __init__(self):
        self.values = {}

    def get(self, key, default=None, store=None):
        return self.values.get((store, key), default)

    def set(self, key, value, store=None):
        self.values[(store, key)] = value


def _session(things, globals_store=None):
    from ..runtime import MiniwindSession
    s = MiniwindSession(_FakeLogic(things, _FakePlayer([0, 272, 0])),
                        cfg={"start_hour": 12.0, "minutes_per_day": 999999.0},
                        globals_store=globals_store)
    s.clock.set_time(12.0, 1)
    return s


def _actor(name, head="", kind="npc", role="farmer"):
    return _FakeThing([0, 272, 0], {"type": kind, "name": name,
                                    "npc_role": role, "head": head})


def test_the_chosen_head_is_the_players_sprite():
    s = _session([])
    s.begin_new_character("Tester", "imperial", "warrior", "none", "male",
                          head="head13")
    assert s.game.character.head == "head13"
    assert s.logic.player_head_sprite == heads.head_path("head13")


def test_no_npc_keeps_the_players_head_even_when_it_was_authored():
    farmers = [_actor("Farmer %d" % i, head="head13") for i in range(12)]
    guard = _actor("Town Guard", head="head13", role="guard")
    other = _actor("Baker", head="head05")
    browsed = _actor("Cook", head="Chef")
    sheep = _actor("Sheep", head="sheep01", kind="creature", role="sheep")
    rolled = _actor("Anon")
    s = _session(farmers + [guard, other, browsed, sheep, rolled])

    s.begin_new_character("Tester", "imperial", "warrior", "none", "male",
                          head="head13")

    actors = farmers + [guard, other, browsed, sheep, rolled]
    assert all(a.properties["head"] != "head13" for a in actors)
    assert all(heads.is_any_head(a.properties["head"]) for a in actors)
    # A guard-named NPC that loses the player's head gets a guard head.
    assert heads.is_guard_head(guard.properties["head"])
    # Heads that are not the player's are kept as authored.
    assert other.properties["head"] == "head05"
    assert browsed.properties["head"] == "Chef"
    assert sheep.properties["head"] == "sheep01"


def test_a_character_without_a_head_is_given_one():
    npc = _actor("Farmer")
    s = _session([npc])
    s.begin_new_character("Tester", "imperial", "warrior", "none", "male")
    head = s.game.character.head
    assert heads.is_head(head)
    assert s.logic.player_head_sprite == heads.head_path(head)
    assert npc.properties["head"] != head


def test_a_loaded_character_keeps_its_head_and_npcs_avoid_it():
    saved = _Globals()
    s = _session([], globals_store=saved)
    s.begin_new_character("Tester", "imperial", "warrior", "none", "male",
                          head="head07")
    s.game.save_to_store()

    npc = _actor("Farmer", head="head07")
    loaded = _session([npc], globals_store=saved)
    loaded.restore()

    assert loaded.game.character.head == "head07"
    assert loaded.logic.player_head_sprite == heads.head_path("head07")
    assert npc.properties["head"] != "head07"


# --- animals ---------------------------------------------------------------
def test_an_animal_without_a_head_wears_its_own_kind_or_the_placeholder():
    hen = _actor("Hen", kind="creature", role="hen")
    wolf = _actor("Wolf", kind="creature", role="wolf")
    bear = _actor("Bear", kind="creature", role="bear")
    cow = _actor("Cow", kind="creature", role="cow")
    sheep = _actor("Sheep", head="sheep02", kind="creature", role="sheep")
    s = _session([hen, wolf, bear, cow, sheep])

    s.begin_new_character("Tester", "imperial", "warrior", "none", "male",
                          head="head13")

    # Hens wear the chickens and wolves the wolves -- never a person's.
    assert hen.properties["head"] in ("chicken", "chicken2", "chicken3")
    assert wolf.properties["head"] in ("wolf01", "wolf02")
    # No bear head has been drawn yet: the placeholder.
    assert bear.properties["head"] == heads.PLACEHOLDER_HEAD
    assert bear.properties["custom_idle"] == "assets/sprites/heads/placeholder.png"
    # Cows have their own heads (cow01, cow02).
    assert cow.properties["head"] in ("cow01", "cow02")
    # A head set in the map is kept.
    assert sheep.properties["head"] == "sheep02"
    one = (heads.HEAD_SIZE, heads.HEAD_SIZE)
    for animal in (wolf, bear, cow, sheep):
        assert (animal.properties["sprite_width"],
                animal.properties["sprite_height"]) == one
    third = heads.CHICKEN_SIZE                     # chickens are small
    assert (hen.properties["sprite_width"], hen.properties["sprite_height"]) == (third, third)


def test_the_placeholder_head_ships_and_is_never_the_players():
    assert heads.is_any_head(heads.PLACEHOLDER_HEAD)
    assert not heads.is_head(heads.PLACEHOLDER_HEAD)


def test_an_animals_own_head_replaces_the_placeholder_once_drawn(tmp_path,
                                                                monkeypatch):
    folder = tmp_path / "assets" / "sprites" / "heads"
    folder.mkdir(parents=True)
    monkeypatch.setattr(heads, "_repo_root", lambda: str(tmp_path))
    assert heads.animal_head("hen") == heads.PLACEHOLDER_HEAD
    (folder / "hen.png").write_bytes(b"png")
    assert heads.animal_head("hen") == "hen"
    (folder / "boar01.png").write_bytes(b"png")
    (folder / "boar02.png").write_bytes(b"png")
    assert heads.animal_head("boar") in ("boar01", "boar02")
