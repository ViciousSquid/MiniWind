from types import SimpleNamespace

import json


def test_ruined_cathedral_gets_a_discovery_marker_at_its_placed_position(tmp_path, monkeypatch):
    from editor.things import Thing
    from game import world_landmarks

    overlay = tmp_path / "landmarks.json"
    overlay.write_text(json.dumps({"things": []}), encoding="utf-8")
    monkeypatch.setattr(world_landmarks, "_OVERLAY", overlay)

    cathedral = Thing(
        pos=[1200.0, 34.0, -560.0],
        properties={
            "type": "prop",
            "name": "ruined_cathedral",
            "model_path": "assets/models/ruined_cathedral.obj",
        },
    )
    invalidations = []
    state = SimpleNamespace(
        things=[cathedral],
        brushes=[],
        _invalidate_entity_caches=lambda: invalidations.append(True),
    )
    level_data = {
        "things": [{
            "type": "prop",
            "properties": {
                "id": world_landmarks._MAIN_MILL_ID,
                "name": "windmill",
            },
        }],
    }

    added = world_landmarks.install_chesterton_landmarks(state, level_data)

    markers = [thing for thing in state.things
               if (getattr(thing, "properties", {}) or {}).get("id")
               == world_landmarks._CATHEDRAL_MARKER_ID]
    assert added == 1
    assert len(markers) == 1
    marker = markers[0]
    assert marker.properties["marker_kind"] == "location"
    assert marker.properties["place_name"] == "Ruined Cathedral"
    assert marker.properties["discover_radius"] == 512.0
    assert list(marker.pos) == [1200.0, 34.0, -560.0]
    assert invalidations

    # Reopening after the cathedral is moved keeps the discovery point attached
    # without creating a second marker.
    cathedral.pos = [1300.0, 40.0, -600.0]
    assert world_landmarks.install_chesterton_landmarks(state, level_data) == 0
    markers = [thing for thing in state.things
               if (getattr(thing, "properties", {}) or {}).get("id")
               == world_landmarks._CATHEDRAL_MARKER_ID]
    assert len(markers) == 1
    assert list(markers[0].pos) == [1300.0, 40.0, -600.0]
