"""The Vale has pickable locks, while barrels and sacks stay open."""

import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from game.rpg.lockpicking import LOCKS
from game.tools.container_locks import (apply_container_locks,
                                        apply_overworld_lock_overrides,
                                        configure_container_lock, update_map_text)


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def world_containers():
    world = json.loads((ROOT / "maps/village_walled_source.json").read_bytes())
    # Apply the authored lock overlay without discarding newer furnished map data.
    assert apply_overworld_lock_overrides(world["things"]) == 13
    assert apply_overworld_lock_overrides(world["things"]) == 0
    return [t for t in world["things"] if t.get("type") == "container"]


def test_the_loaded_world_has_a_mix_of_open_and_pickable_containers(world_containers):
    props = [t["properties"] for t in world_containers]
    locked = [p for p in props if p.get("locked")]
    assert 0 < len(locked) < len(props)
    assert all(p["container_kind"] in ("chest", "crate") for p in locked)
    assert all(p["lock_difficulty"] in LOCKS and not p.get("lock_key") for p in locked)
    assert len(Counter(p["lock_difficulty"] for p in locked)) >= 2
    assert all(not p.get("locked") and not p.get("lock_jammed")
               for p in props if p["container_kind"] in ("barrel", "sack"))


@pytest.mark.parametrize("kind", ["barrel", "BARREL", "sack", "SACK"])
def test_barrels_and_sacks_cannot_inherit_a_prototype_lock(kind):
    props = {"container_kind": kind, "locked": True, "lock_jammed": True,
             "lockpick_state": {"pins_set": 2}, "inventory": [{"id": "gold", "qty": 2}]}
    configure_container_lock(props, [0., 0., 0.], preserve_existing=False)
    assert props["locked"] is False
    assert "lock_jammed" not in props and "lockpick_state" not in props
    assert props["inventory"] == [{"id": "gold", "qty": 2}]


def test_lock_assignment_preserves_authored_contents_and_existing_locks():
    things = [{"type": "container", "pos": [n * 10., 0., 40.],
               "properties": {"name": f"Chest {n}", "container_kind": "chest",
                              "inventory": [{"id": "gold", "qty": n + 1}], "owner": "Aldric"}}
              for n in range(40)]
    authored = {"type": "container", "pos": [0., 0., 0.], "properties": {
        "name": "Authored strongbox", "container_kind": "chest", "locked": True,
        "lock_difficulty": "expert", "lock_key": "gaol_key", "inventory": []}}
    things.append(authored)
    world = {"things": things}
    before = copy.deepcopy(world)
    assert apply_container_locks(world) > 0
    assert authored == before["things"][-1]
    for old, new in zip(before["things"], world["things"]):
        assert old["pos"] == new["pos"]
        assert old["properties"]["inventory"] == new["properties"]["inventory"]
        if "owner" in old["properties"]:
            assert old["properties"]["owner"] == new["properties"]["owner"]
    assert apply_container_locks(world) == 0


def test_the_content_pass_preserves_compact_terrain_and_windows_line_endings():
    thing = {"type": "container", "pos": [0., 0., 0.], "properties": {
        "container_kind": "barrel", "locked": True}}
    text = json.dumps({"things": [thing]}, indent=4)[:-1]
    text += ',\n    "terrain_data": {"sculpt_offsets":[[0,0,2],[1,0,3]]}\n}'
    text = text.replace("\n", "\r\n")
    changed, count = update_map_text(text)
    assert count == 1
    assert not json.loads(changed)["things"][0]["properties"]["locked"]
    assert '"sculpt_offsets":[[0,0,2],[1,0,3]]' in changed
    assert changed.count("\n") == changed.count("\r\n")
    assert update_map_text(changed) == (changed, 0)


def test_new_generated_containers_obey_the_same_lock_policy():
    from game.tools.expand_world import Expander
    prototype = {"type": "container", "pos": [0., 0., 0.], "properties": {
        "container_kind": "chest", "locked": True, "lock_difficulty": "master",
        "lock_key": "old_key", "lock_jammed": True, "inventory": []}}
    expander = object.__new__(Expander)
    expander.world = {"things": [prototype]}
    expander._ground = lambda x, z: 0.
    for index in range(40):
        for kind in ("chest", "barrel", "sack"):
            expander._container(index * 40., 60., kind, [("gold", 5)])
    generated = [t["properties"] for t in expander.world["things"][1:]]
    assert any(p["locked"] for p in generated)
    assert all(not p["locked"] for p in generated if p["container_kind"] in ("barrel", "sack"))
    assert all(not p.get("lock_key") for p in generated if p["locked"])
    assert all(not p.get("lock_jammed") for p in generated)
    assert prototype["properties"]["lock_key"] == "old_key"


def test_an_authored_world_lock_requires_picking_before_looting(world_containers):
    from .test_corpse_loot import _Thing
    from .test_lockpicking import _picking
    source = next(t for t in world_containers if t["properties"].get("locked"))
    props = copy.deepcopy(source["properties"])
    name = props.pop("name")
    # An unowned cache isolates the lock from the separate witness system.
    props.pop("owner", None)
    chest = _Thing(name, [40., 0., 0.], **props)
    session, chest = _picking(chest)
    assert session.open_screen == "lockpicking"
    assert session.container_inventory() == []
    for _ in range(500):
        attempt = session.lockpick_attempt
        if attempt is None:
            break
        attempt.angle = attempt.target
        attempt.set_tension(True)
        session.tick_lockpicking(.05)
    assert not chest.properties["locked"]
    assert session.open_screen == "container"
    assert session.container_inventory()
