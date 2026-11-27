"""Small authored landmark additions merged into the MiniWind editor scene."""

from __future__ import annotations

import json
from pathlib import Path

_MAIN_MILL_ID = "250882b7-d724-4931-b8f8-107fd10617b7"
_OVERLAY = (Path(__file__).resolve().parents[1] / "maps"
            / "miniwind_chesterton_additions.json")


def install_chesterton_landmarks(editor_state, level_data) -> int:
    """Add the Chesterton mill to the shipped world after a successful load.

    The world map contains a large embedded terrain payload. Keeping this tiny
    authored addition as a sidecar avoids rewriting that unrelated terrain data.
    Entity IDs make the operation idempotent, including after the map is saved
    with the additions already embedded.
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

    if additions:
        things.extend(additions)
        update_all_counters_from_entities(list(getattr(editor_state, "brushes", ())) + list(things))
        invalidate = getattr(editor_state, "_invalidate_entity_caches", None)
        if invalidate is not None:
            invalidate()
    return len(additions)
