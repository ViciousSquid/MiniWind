"""The sidecar Chesterton landmark loads as three ordinary non-solid entities."""

import json
import pytest
from pathlib import Path
from types import SimpleNamespace

from game.world_landmarks import install_chesterton_landmarks

ROOT = Path(__file__).resolve().parents[2]
MAIN_MILL_ID = "250882b7-d724-4931-b8f8-107fd10617b7"


def test_chesterton_addition_is_a_linked_non_solid_windmill():
    overlay = json.loads((ROOT / "maps/miniwind_chesterton_additions.json").read_text())
    body = next(t for t in overlay["things"] if t["properties"].get("name") == "chesterton_windmill")
    props = body["properties"]
    rotor = next(t for t in overlay["things"]
                 if t["properties"].get("mill_rotor_for") == props["id"])
    marker = next(t for t in overlay["things"]
                  if t["properties"].get("name") == "loc_chesterton_windmill")

    assert props["model_path"] == "assets/models/chesterton_windmill_body.obj"
    assert props["windmill"] is True and props["no_collision"] is True
    assert props["inventory"] == []
    assert rotor["properties"]["model_path"] == "assets/models/chesterton_windmill_rotor.obj"
    assert rotor["properties"]["mill_rotor_axis"] == "z"
    assert rotor["properties"]["no_collision"] is True
    anchor = props["mill_rotor_anchor"]
    assert anchor == [0, 700, 260]
    assert rotor["pos"] == [body["pos"][i] + anchor[i] for i in range(3)]
    assert marker["properties"]["place_name"] == "Chesterton Windmill"
    assert marker["pos"] == [body["pos"][0], body["pos"][1] + 32, body["pos"][2]]

    mesh = (ROOT / props["model_path"]).read_text()
    rotor_mesh = (ROOT / rotor["properties"]["model_path"]).read_text()
    rotor_mtl = (ROOT / "assets/models/chesterton_windmill_rotor.mtl").read_text()
    mtl = (ROOT / "assets/models/chesterton_windmill_body.mtl").read_text()
    assert "mtllib chesterton_windmill_body.mtl" in mesh
    assert "g undercroft_arches" in mesh and "g slate_dome" in mesh
    for name in ("Grass", "Foundation", "Sandstone", "SandstoneLight",
                 "SandstoneDark", "Slate", "Iron"):
        assert f"newmtl {name}" in mtl
    assert "mtllib chesterton_windmill_rotor.mtl" in rotor_mesh
    assert "o chesterton_axle" in rotor_mesh
    assert "o chesterton_hub" in rotor_mesh
    assert "newmtl Iron" in rotor_mtl and "newmtl Sail_red" in rotor_mtl

    # The sail vertices precede the axle group and should lie in a vertical
    # XY plane (thin Z depth), not the original horizontal XZ plane.
    sail_vertices = []
    for line in rotor_mesh.split("o chesterton_axle", 1)[0].splitlines():
        if line.startswith("v "):
            sail_vertices.append([float(v) for v in line.split()[1:4]])
    assert len(sail_vertices) > 300
    assert max(v[0] for v in sail_vertices) - min(v[0] for v in sail_vertices) > 550
    assert max(v[1] for v in sail_vertices) - min(v[1] for v in sail_vertices) > 550
    assert max(v[2] for v in sail_vertices) - min(v[2] for v in sail_vertices) <= 10.01
    assert min(float(line.split()[3]) for line in rotor_mesh.splitlines()
               if line.startswith("v ")) <= -99.0

    for record in (body, rotor):
        assert (ROOT / record["properties"]["model_path"]).is_file()


def test_landmark_injection_is_world_specific_and_idempotent():
    pytest.importorskip("PyQt5.QtGui", reason="editor entity factory is Qt-backed")
    source = {"things": [{"properties": {"id": MAIN_MILL_ID, "name": "windmill"}}]}
    foreign = {"things": [{"properties": {"id": "another-world", "name": "windmill"}}]}
    state = SimpleNamespace(things=[], brushes=[])

    assert install_chesterton_landmarks(state, foreign) == 0
    assert state.things == []
    assert install_chesterton_landmarks(state, source) == 3
    assert install_chesterton_landmarks(state, source) == 0
    names = {thing.properties.get("name") for thing in state.things}
    assert {"chesterton_windmill", "chesterton_windmill_sails",
            "loc_chesterton_windmill"} <= names
