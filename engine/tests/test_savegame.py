"""Tests for the full / delta / both play-session save modes.

These exercise :mod:`engine.savegame` head-less with lightweight fakes for the
``LogicThread`` and its entities, so they need no Qt/GL/window. They cover the
save-file structures, delta generation, UUID-based overlay restore, base-map
classification, the automatic loader, and backward compatibility.

Run with ``python -m pytest engine/tests/test_savegame.py`` or directly with
``python engine/tests/test_savegame.py``.
"""

import copy
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from engine import savegame  # noqa: E402


# ---------------------------------------------------------------------------
# lightweight fakes standing in for the engine objects savegame touches
# ---------------------------------------------------------------------------

class FakeThing:
    def __init__(self, tid, ttype, pos, props=None):
        self.pos = list(pos)
        self.properties = dict(props or {})
        self.properties["id"] = tid
        self.properties.setdefault("type", ttype)


class FakePlayer:
    def __init__(self):
        self.pos = [0.0, 0.0, 0.0]
        self.velocity = [0.0, 0.0, 0.0]
        self.angle = 0.0
        self.pitch = 0.0
        self.camera_height = 40.0
        self.physics_enabled = True
        self.on_ground = True
        self.in_water = False
        self.swimming = False


class FakeEditorState:
    """Serializes the owning logic's live things/brushes like get_level_data()."""

    def __init__(self, logic):
        self.logic = logic

    def get_level_data(self):
        return {
            "version": 3,
            "brushes": [copy.deepcopy(b) for b in self.logic.brushes],
            "things": [
                {
                    "type": t.properties.get("type"),
                    "pos": list(t.pos),
                    "properties": {
                        k: v for k, v in t.properties.items()
                        if k != "_io_connections"
                    },
                    "io_connections": [],
                }
                for t in self.logic.things
            ],
        }


class FakeMonsterAI:
    def __init__(self):
        self.monster_states = {}


class FakeLogic:
    def __init__(self, things, brushes):
        self.play_mode = True
        self.things = things
        self.brushes = brushes
        self.editor_state = FakeEditorState(self)
        self.player = FakePlayer()
        self.player2 = None
        # runtime defaults
        self.god_mode = False
        self.buddha_mode = False
        self.notarget = False
        self.camera_mode = "First Person"
        self.overhead_height = 800.0
        self.overhead_tilt = 0.0
        self.overhead_orientation = "north"
        self.active_weapon = None
        self.current_hud_message = ""
        self.player_health = 100
        self.player_max_health = 100
        self.player_dead = False
        self.player2_health = 100
        self.player2_max_health = 100
        self.player2_dead = False
        self.collected_keys = set()
        self.collected_pickups = set()
        self.door_states = {}
        self.mover_states = {}
        self.monster_ai = FakeMonsterAI()
        self._monster_things = [t for t in things if t.properties.get("type") == "monster"]

    def _build_entity_caches(self):
        pass


def make_world():
    """A small deterministic base world: a monster, a pickup, a door brush."""
    things = [
        FakeThing("mon-1", "monster", [10.0, 0.0, 10.0],
                  {"health": 50, "dead": False, "awake": False}),
        FakeThing("key-1", "pickup", [20.0, 0.0, 5.0],
                  {"collected": False, "pickup_type": "key_red"}),
        FakeThing("stat-1", "light", [0.0, 100.0, 0.0], {"intensity": 1.0}),
    ]
    brushes = [
        {"id": "wall-1", "pos": [0, 0, 0], "size": [64, 64, 64]},
        {"id": "door-1", "pos": [30, 0, 0], "size": [8, 96, 64], "hidden": False},
    ]
    return FakeLogic(things, brushes)


def base_level_of(logic):
    """Snapshot the current live level as an (immutable) base document."""
    return copy.deepcopy(logic.editor_state.get_level_data())


# ---------------------------------------------------------------------------
# FULL mode
# ---------------------------------------------------------------------------

def test_full_save_structure_and_roundtrip():
    logic = make_world()
    snap = savegame.build_snapshot(logic, map_name="lvl.json")
    assert snap["fio_savegame"] is True
    assert snap["save_version"] == 2
    assert snap["save_mode"] == "full"
    assert "level" in snap and "runtime" in snap and "player" in snap
    assert "base_map" not in snap  # full carries no base identity

    # Mutate, then restore the snapshot back onto the same live world.
    logic.things[0].properties["dead"] = True
    savegame.restore_snapshot(logic, snap)
    assert logic.things[0].properties["dead"] is False  # snapshot had it alive


def test_full_restores_changed_entities_player_and_monster():
    logic = make_world()
    logic.things[0].properties["health"] = 0
    logic.things[0].properties["dead"] = True
    logic.things[1].properties["collected"] = True
    logic.player.pos = [123.0, 4.0, 5.0]
    logic.player_health = 42
    logic.god_mode = True
    logic.door_states = {2: {"state": "open", "progress": 1.0, "_cache": object()}}
    logic.monster_ai.monster_states = {id(logic.things[0]): {"target": "player", "_np": object()}}

    snap = savegame.build_snapshot(logic, map_name="lvl.json")

    fresh = make_world()  # pristine identical world
    savegame.restore_snapshot(fresh, snap)
    assert fresh.things[0].properties["dead"] is True
    assert fresh.things[1].properties["collected"] is True
    assert list(fresh.player.pos) == [123.0, 4.0, 5.0]
    assert fresh.player_health == 42
    assert fresh.god_mode is True
    # Door state restored, transient _cache dropped.
    assert fresh.door_states[2]["state"] == "open"
    assert "_cache" not in fresh.door_states[2]
    # Monster state remapped back to the fresh object id, _np cache dropped.
    assert list(fresh.monster_ai.monster_states.values())[0]["target"] == "player"


# ---------------------------------------------------------------------------
# DELTA mode
# ---------------------------------------------------------------------------

def test_delta_no_changes_is_minimal():
    logic = make_world()
    base = base_level_of(logic)
    snap = savegame.build_snapshot(logic, map_name="lvl.json",
                                   save_mode="delta", base_level=base)
    assert snap["save_mode"] == "delta"
    assert snap["delta"]["level"]["things"] == []
    assert snap["delta"]["level"]["brushes"] == []
    assert "level" not in snap  # delta carries no full level
    assert snap["base_map"]["fingerprint"]


def test_delta_captures_only_changes():
    logic = make_world()
    base = base_level_of(logic)

    logic.things[0].properties["dead"] = True     # kill monster
    logic.things[0].properties["health"] = 0
    logic.things[1].pos = [21.0, 0.0, 5.0]        # move pickup
    logic.things[1].properties["collected"] = True
    logic.brushes[1]["hidden"] = True             # hide a door brush

    snap = savegame.build_snapshot(logic, map_name="lvl.json",
                                   save_mode="delta", base_level=base)
    changed_ids = {t["properties"]["id"] for t in snap["delta"]["level"]["things"]}
    assert changed_ids == {"mon-1", "key-1"}      # static light unchanged, absent
    changed_brushes = {b["id"] for b in snap["delta"]["level"]["brushes"]}
    assert changed_brushes == {"door-1"}
    assert snap["delta"]["level"]["brushes"][0]["hidden"] is True


def test_delta_restore_overlays_by_uuid_onto_fresh_base():
    logic = make_world()
    base = base_level_of(logic)
    logic.things[0].properties["dead"] = True
    logic.things[1].properties["collected"] = True
    logic.player_health = 7
    logic.player.pos = [1.0, 2.0, 3.0]
    snap = savegame.build_snapshot(logic, map_name="lvl.json",
                                   save_mode="delta", base_level=base)

    fresh = make_world()
    report = savegame.restore_auto(fresh, snap, current_map_name="lvl.json")
    assert report["mode"] == "delta"
    assert fresh.things[0].properties["dead"] is True
    assert fresh.things[1].properties["collected"] is True
    assert fresh.things[2].properties["intensity"] == 1.0  # untouched static
    assert fresh.player_health == 7
    assert list(fresh.player.pos) == [1.0, 2.0, 3.0]


def test_delta_skips_missing_entities_safely():
    logic = make_world()
    base = base_level_of(logic)
    logic.things[0].properties["dead"] = True
    snap = savegame.build_snapshot(logic, map_name="lvl.json",
                                   save_mode="delta", base_level=base)

    # A related map that dropped the monster entirely: overlay must not crash.
    fresh = make_world()
    fresh.things = [t for t in fresh.things if t.properties["id"] != "mon-1"]
    fresh._monster_things = []
    report = savegame.restore_auto(fresh, snap, current_map_name="lvl.json")
    assert report["mode"] == "delta"  # applied what it could
    assert {t.properties["id"] for t in fresh.things} == {"key-1", "stat-1"}


def test_delta_against_wrong_map_raises():
    logic = make_world()
    base = base_level_of(logic)
    snap = savegame.build_snapshot(logic, map_name="lvl.json",
                                   save_mode="delta", base_level=base)

    # Wholly different map: different ids and different name.
    other = FakeLogic(
        [FakeThing("z-1", "monster", [0, 0, 0], {}),
         FakeThing("z-2", "pickup", [0, 0, 0], {}),
         FakeThing("z-3", "light", [0, 0, 0], {})],
        [{"id": "z-b1"}],
    )
    try:
        savegame.restore_auto(other, snap, current_map_name="other.json")
    except ValueError as exc:
        assert "different base map" in str(exc)
    else:
        raise AssertionError("expected a ValueError for the wrong base map")


# ---------------------------------------------------------------------------
# BOTH mode
# ---------------------------------------------------------------------------

def test_both_writes_delta_and_full_fallback():
    logic = make_world()
    base = base_level_of(logic)
    logic.things[0].properties["dead"] = True
    snap = savegame.build_snapshot(logic, map_name="lvl.json",
                                   save_mode="both", base_level=base)
    assert snap["save_mode"] == "both"
    assert "delta" in snap and "level" in snap        # both representations
    assert snap["base_map"]["fingerprint"]


def test_both_prefers_delta_on_matching_map():
    logic = make_world()
    base = base_level_of(logic)
    logic.things[0].properties["dead"] = True
    snap = savegame.build_snapshot(logic, map_name="lvl.json",
                                   save_mode="both", base_level=base)

    fresh = make_world()
    report = savegame.restore_auto(fresh, snap, current_map_name="lvl.json")
    assert report["mode"] == "delta"
    assert fresh.things[0].properties["dead"] is True


def test_both_falls_back_to_full_on_incompatible_map():
    logic = make_world()
    base = base_level_of(logic)
    logic.things[0].properties["dead"] = True
    snap = savegame.build_snapshot(logic, map_name="lvl.json",
                                   save_mode="both", base_level=base)

    other = FakeLogic(
        [FakeThing("z-1", "monster", [0, 0, 0], {}),
         FakeThing("z-2", "pickup", [0, 0, 0], {}),
         FakeThing("z-3", "light", [0, 0, 0], {})],
        [{"id": "z-b1"}],
    )
    report = savegame.restore_auto(other, snap, current_map_name="other.json")
    assert report["mode"] == "full"
    assert "fallback" in report["warning"]


# ---------------------------------------------------------------------------
# base-map classification
# ---------------------------------------------------------------------------

def test_classify_exact_related_incompatible():
    logic = make_world()
    base = base_level_of(logic)
    snap = savegame.build_snapshot(logic, map_name="lvl.json",
                                   save_mode="both", base_level=base)

    # Exact: same current level.
    assert savegame.classify_base_map(snap, base, "lvl.json") == savegame.BASE_EXACT

    # Related: same map name, a minor edit (one brush id changed).
    edited = copy.deepcopy(base)
    edited["brushes"][0]["id"] = "wall-1-moved"
    assert savegame.classify_base_map(snap, edited, "lvl.json") == savegame.BASE_RELATED

    # Incompatible: different name and no id overlap.
    foreign = {
        "things": [{"properties": {"id": "q-1"}}, {"properties": {"id": "q-2"}}],
        "brushes": [{"id": "q-b"}],
    }
    assert savegame.classify_base_map(snap, foreign, "foreign.json") == savegame.BASE_INCOMPATIBLE


# ---------------------------------------------------------------------------
# backward compatibility & error handling
# ---------------------------------------------------------------------------

def test_legacy_v1_full_save_still_loads():
    logic = make_world()
    logic.things[0].properties["dead"] = True
    snap = savegame.build_snapshot(logic, map_name="lvl.json")
    # Downgrade to a v1 legacy file: version 1 and no save_mode key.
    legacy = copy.deepcopy(snap)
    legacy["save_version"] = 1
    legacy.pop("save_mode", None)

    fresh = make_world()
    report = savegame.restore_auto(fresh, legacy)
    assert report["mode"] == "full"
    assert fresh.things[0].properties["dead"] is True


def test_invalid_file_rejected():
    for bad in ({}, {"hello": "world"}, {"fio_savegame": False}):
        try:
            savegame.restore_auto(make_world(), bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {bad!r}")


def test_future_version_read_fails_safely():
    logic = make_world()
    snap = savegame.build_snapshot(logic, map_name="lvl.json")
    snap["save_version"] = 999
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "future.fiosave")
        savegame.write(path, snap)
        try:
            savegame.read(path)
        except ValueError as exc:
            assert "newer than this build" in str(exc)
        else:
            raise AssertionError("expected a ValueError for a future save version")


def test_write_read_roundtrip_on_disk():
    logic = make_world()
    base = base_level_of(logic)
    logic.things[1].properties["collected"] = True
    snap = savegame.build_snapshot(logic, map_name="lvl.json",
                                   save_mode="both", base_level=base)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "s.fiosave")
        savegame.write(path, snap)
        loaded = savegame.read(path)
    assert loaded["save_mode"] == "both"
    fresh = make_world()
    report = savegame.restore_auto(fresh, loaded, current_map_name="lvl.json")
    assert report["mode"] == "delta"
    assert fresh.things[1].properties["collected"] is True


# ---------------------------------------------------------------------------
# direct runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in funcs:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(funcs) - failed}/{len(funcs)} passed")
    sys.exit(1 if failed else 0)
