"""Small authored landmark additions merged into the MiniWind editor scene."""

from __future__ import annotations

import json
from pathlib import Path

_MAIN_MILL_ID = "250882b7-d724-4931-b8f8-107fd10617b7"
_CATHEDRAL_MARKER_ID = "edbdab34-3f6f-4f4e-9970-3a0e4dcf8c61"
_OVERLAY = (Path(__file__).resolve().parents[1] / "maps"
            / "miniwind_chesterton_additions.json")


def _is_ruined_cathedral(thing) -> bool:
    """Recognise the authored cathedral prop without depending on its position."""
    props = getattr(thing, "properties", None)
    if not isinstance(props, dict):
        return False
    model_path = str(props.get("model_path") or "").replace("\\", "/")
    model_name = model_path.rsplit("/", 1)[-1].lower()
    authored_name = str(props.get("name") or "").strip().lower()
    return (model_name == "ruined_cathedral.obj"
            or authored_name in {"ruined_cathedral", "ruined cathedral"})


def _cathedral_marker_record(position) -> dict:
    """The cathedral's discovery point, anchored at the model's authored origin."""
    return {
        "type": "marker",
        "pos": [float(position[0]), float(position[1]), float(position[2])],
        "properties": {
            "type": "marker",
            "name": "loc_ruined_cathedral",
            "id": _CATHEDRAL_MARKER_ID,
            "marker_kind": "location",
            "place_name": "Ruined Cathedral",
            "discover_radius": 512.0,
            "stop_on_escape": True,
            "io_enabled": True,
            "custom_idle": "assets/sprites/miniwind/marker_location.png",
        },
        "io_connections": [],
    }


def install_chesterton_landmarks(editor_state, level_data) -> int:
    """Add authored landmarks after the MiniWind world has been deserialised.

    The world map contains a large embedded terrain payload. Keeping the
    Chesterton additions in a small sidecar avoids rewriting that unrelated
    data. The cathedral marker is generated from the placed model's live
    position, rather than duplicating world coordinates in another file.

    Stable entity IDs make the operation idempotent, including after the map
    is saved with the additions already embedded.
    """
    if not isinstance(level_data, dict):
        return 0
    source_things = level_data.get("things") or ()
    if not any(
        (record.get("properties") or {}).get("id") == _MAIN_MILL_ID
        and (record.get("properties") or {}).get("name") == "windmill"
        for record in source_things
    ):
        return 0

    things = getattr(editor_state, "things", None)
    if things is None:
        return 0
    existing_ids = {
        getattr(thing, "properties", {}).get("id")
        for thing in things
        if getattr(thing, "properties", None) is not None
    }
    try:
        records = json.loads(_OVERLAY.read_text(encoding="utf-8")).get("things", ())
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot read Chesterton landmark data: {exc}") from exc

    from editor.things import Thing, update_all_counters_from_entities

    additions = []
    for record in records:
        entity_id = (record.get("properties") or {}).get("id")
        if not entity_id or entity_id in existing_ids:
            continue
        thing = Thing.from_dict(record)
        if thing is not None:
            additions.append(thing)
            existing_ids.add(entity_id)

    changed = bool(additions)
    cathedral = next((thing for thing in things if _is_ruined_cathedral(thing)), None)
    if cathedral is not None:
        marker = next((thing for thing in things
                       if (getattr(thing, "properties", {}) or {}).get("id")
                       == _CATHEDRAL_MARKER_ID), None)
        marker_position = [float(v) for v in cathedral.pos[:3]]
        if marker is None:
            marker = Thing.from_dict(_cathedral_marker_record(marker_position))
            if marker is not None:
                additions.append(marker)
                existing_ids.add(_CATHEDRAL_MARKER_ID)
                changed = True
        elif list(marker.pos[:3]) != marker_position:
            # Keep the discovery point attached if the cathedral is moved in
            # the editor and the map is subsequently reopened.
            marker.pos = marker_position
            changed = True

    if additions:
        things.extend(additions)
    if changed:
        update_all_counters_from_entities(list(getattr(editor_state, "brushes", ())) + list(things))
        invalidate = getattr(editor_state, "_invalidate_entity_caches", None)
        if invalidate is not None:
            invalidate()
    return len(additions)
