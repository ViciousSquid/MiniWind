"""
Upgrade a hand-authored MiniWind map with the latest settlement *content*.

Unlike :mod:`game.tools.make_settlement` (which builds a whole map from data on a
flat base), this tool leaves an existing, hand-edited level — its geometry, its
lighting, and the exact placement of every marker, NPC and threat — completely
untouched, and only refreshes the authored *content* of the townsfolk from
``game/data/settlement.json``:

* dialogue trees (so mourning / relationship branches appear),
* ``relationships`` (the authored social web),
* ``patrol_markers`` for anyone the data gives a ``patrol`` circuit,
* and, for any livestock the map already places by name, its ``owner`` and its
  production settings — so a cow keeps making the right goods for the right
  farmer without the tool ever moving it.

Matching is by NPC ``name``. Anything the map has and the data doesn't is left
alone; anything the data has for a name not in the map is ignored. Exact
duplicate things (same type + name + position) — a common autosave artifact —
are collapsed to one.

This is the workflow for developing the living settlement on top of a level you
keep editing in the editor (e.g. a walled village): edit the walls in the
editor, edit the people in ``settlement.json``, run this to marry the two.

    python -m game.tools.apply_settlement_content maps/village.json
    python -m game.tools.apply_settlement_content in.json -o out.json
"""

from __future__ import annotations

import argparse
import json
import os

from game import data


def _slug(text) -> str:
    """The identity key ownership and memory are filed under (matches
    :func:`game.sim.director.actor_key`)."""
    return "".join(ch.lower() if ch.isalnum() else "_"
                   for ch in str(text)).strip("_")


def _dedupe(things):
    """Drop exact-duplicate things (same type, name and rounded position)."""
    seen = set()
    out = []
    for t in things:
        key = (t.get("type"),
               t.get("properties", {}).get("name"),
               tuple(round(float(c), 1) for c in t.get("pos", [])))
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    return out


#: Livestock content refreshed onto creatures the map already places. Placement
#: stays the designer's, exactly like every other entity this tool touches —
#: only what the thing *is* comes from the data.
_LIVESTOCK_FIELDS = ("produces", "produce_every_hours", "produce_into",
                     "produce_quantity", "produce_max", "owner_faction")


def apply_content(world: dict, settlement: dict) -> dict:
    by_name = {n["name"]: n for n in settlement.get("npcs", [])}
    beasts = {b["name"]: b for b in settlement.get("livestock", [])}
    upgraded = 0
    for t in world.get("things", []):
        p = t.get("properties", {})
        # Livestock: refresh ownership and production so a cow the designer
        # placed keeps making the right thing for the right owner.
        beast = beasts.get(p.get("name"))
        if beast is not None:
            for field in _LIVESTOCK_FIELDS:
                if field in beast:
                    p[field] = beast[field]
            if beast.get("owner"):
                p["owner"] = _slug(beast["owner"])
                p["owner_name"] = beast["owner"]
            upgraded += 1
            continue
        if str(p.get("type", "")) != "npc":
            continue
        src = by_name.get(p.get("name"))
        if not src:
            continue
        if "dialogue" in src:
            p["dialogue"] = src["dialogue"]
        if "relationships" in src:
            p["relationships"] = src["relationships"]
        if src.get("patrol"):
            # A patrol circuit of marker names the runtime walks while on duty.
            p["patrol_markers"] = list(src["patrol"])
        upgraded += 1
    world["things"] = _dedupe(world.get("things", []))
    world["_settlement_content_applied"] = True
    return world, upgraded


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("map", help="path to the map JSON to upgrade in place")
    ap.add_argument("-o", "--out", help="write here instead of overwriting the input")
    args = ap.parse_args()

    with open(args.map) as f:
        world = json.load(f)
    settlement = data.load("settlement")
    world, n = apply_content(world, settlement)

    out = args.out or args.map
    with open(out, "w") as f:
        json.dump(world, f, indent=2)
    print(f"upgraded {n} NPC(s)/livestock with settlement content -> {out} "
          f"({len(world['things'])} things after de-duplication)")


if __name__ == "__main__":
    main()
