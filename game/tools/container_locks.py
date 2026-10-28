"""Give a repeatable subset of the Vale's chests and crates pickable locks.

Run on an existing authored map with ``python -m game.tools.container_locks
[MAP]``. Container identity and position determine selection, so applying this
pass again does not reroll locks or consume the world generator's RNG.
Barrels and sacks are always left open; existing authored chest locks keep
their difficulty and key settings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


DEFAULT_MAP = Path("maps/village_walled_source.json")
LOCK_CHANCE = {"chest": 0.45, "crate": 0.25}
NEVER_LOCK = frozenset({"barrel", "sack"})


# Authored overworld lock states. These are applied to loaded entities by id,
# preserving the newer, furnished source map and any subsequent map additions.
# The generated-container policy below remains separate.
OVERWORLD_LOCKS = {
    "7524e34d-2566-4940-9da5-da258f929873": "novice",
    "a09bdaf0-ae9e-5916-9024-27ac08f48c02": "novice",
    "cbd6c873-6a90-5b33-95ea-c9d6a506494a": "novice",
    "e33b228f-7709-595f-8c81-70db7990aeae": "adept",
    "b525e89b-ac0e-5a97-b243-93395a21f4ba": "apprentice",
    "7574ea46-4e73-5e6f-adbc-8ef790f39850": "adept",
    "18fcb74b-18e5-452c-a876-2bf60bf111c3": "novice",
    "fe3f2a08-8770-4b3b-9ebb-cd4aa6e1cb3e": "novice",
    "b0b6436e-0fc9-4078-b18f-874197e33c8c": "adept",
    "86fa63f5-fbd7-45d2-b695-1c01806b431e": "novice",
    "79f583dc-b8a8-4ab6-840a-1f9529ffa5f5": "novice",
    "549ce98a-e32a-4666-882d-ccaa1078a55f": "novice",
    "0dd16bdf-7ff3-4e2a-aaeb-29fff9d224ef": "novice",
}


def apply_overworld_lock_overrides(things):
    """Restore the Vale's authored lock choices on the live map entities.

    Existing picked/unlocked state may be restored by map memory afterwards.
    Other containers, inventories, ownership and map content are untouched.
    """
    applied = 0
    for thing in things:
        props = thing.get("properties", {}) if isinstance(thing, dict) else getattr(thing, "properties", {})
        difficulty = OVERWORLD_LOCKS.get(props.get("id"))
        if difficulty is None:
            continue
        if props.get("locked") and props.get("lock_difficulty"):
            continue
        props["locked"] = True
        props["lock_key"] = ""
        props["lock_difficulty"] = difficulty
        applied += 1
    return applied


def configure_container_lock(properties, pos, *, preserve_existing=True):
    """Apply the lock policy to one container, leaving its contents untouched."""
    kind = str(properties.get("container_kind", "chest")).strip().lower()
    label = str(properties.get("display_name") or properties.get("name", "")).lower()
    if kind in NEVER_LOCK or any(word in label for word in ("barrel", "sack", "satchel")):
        properties["locked"] = False
        properties.pop("lock_jammed", None)
        properties.pop("lockpick_state", None)
        return
    if preserve_existing and properties.get("locked"):
        return
    if not preserve_existing:
        # A generated container is a new object, not the source prototype's
        # lock or partially picked state.
        properties["locked"] = False
        properties["lock_key"] = ""
        properties.pop("lock_jammed", None)
        properties.pop("lockpick_state", None)
    chance = LOCK_CHANCE.get(kind, 0.0)
    identity = f"{kind}:{properties.get('name', '')}:{float(pos[0]):.1f}:{float(pos[2]):.1f}"
    digest = hashlib.sha256(identity.encode("utf-8")).digest()
    if int.from_bytes(digest[:4], "big") / 2**32 >= chance:
        return
    properties["locked"] = True
    properties["lock_key"] = ""       # these are picked, never key-only locks
    roll = digest[4] % 100
    properties["lock_difficulty"] = ("novice" if roll < 55 else
                                      "apprentice" if roll < 85 else "adept")


def apply_container_locks(world):
    """Apply authored locks in-place and return the number of changed containers."""
    changed = 0
    for thing in world.get("things", ()):
        properties = thing.get("properties", {})
        if str(thing.get("type") or properties.get("type", "")).lower() != "container":
            continue
        before = dict(properties)
        configure_container_lock(properties, thing.get("pos", (0., 0., 0.)))
        changed += properties != before
    return changed


def update_map_text(text):
    """Change container records without reformatting the map's terrain arrays."""
    decoder = json.JSONDecoder()

    def skip(index):
        while index < len(text) and text[index].isspace():
            index += 1
        return index

    index = skip(0)
    if text[index] != "{":
        raise ValueError("Expected a JSON map object")
    index = skip(index + 1)
    while text[index] != "}":
        key, index = decoder.raw_decode(text, index)
        index = skip(index)
        if text[index] != ":":
            raise ValueError("Expected a JSON map property")
        index = skip(index + 1)
        if key != "things":
            _, index = decoder.raw_decode(text, index)
            index = skip(index)
            if text[index] == ",":
                index = skip(index + 1)
            continue
        if text[index] != "[":
            raise ValueError("Expected a map things list")
        index = skip(index + 1)
        edits = []
        newline = "\r\n" if "\r\n" in text else "\n"
        while text[index] != "]":
            start = index
            thing, index = decoder.raw_decode(text, index)
            if apply_container_locks({"things": [thing]}):
                prefix = text[text.rfind("\n", 0, start) + 1:start]
                indent = prefix if not prefix.strip() else ""
                replacement = json.dumps(thing, indent=4)
                replacement = replacement.replace("\n", newline + indent)
                edits.append((start, index, replacement))
            index = skip(index)
            if text[index] == ",":
                index = skip(index + 1)
        for start, end, replacement in reversed(edits):
            text = text[:start] + replacement + text[end:]
        return text, len(edits)
    return text, 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map", nargs="?", type=Path, default=DEFAULT_MAP)
    args = parser.parse_args()
    source = args.map.read_bytes()
    text, changed = update_map_text(source.decode("utf-8"))
    if changed:
        args.map.write_bytes(text.encode("utf-8"))
    print(f"Updated {changed} container(s) in {args.map}; barrels and sacks remain unlocked.")


if __name__ == "__main__":
    main()
