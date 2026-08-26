"""
Build the MiniWind living settlement map from editable data.

Reads ``game/data/settlement.json`` (markers, NPCs, threats, world settings —
all human-editable content) and materialises it into a loadable Fio map,
``maps/village.json``. This is the vertical slice for MiniWind's
living-world architecture (§18): a small handcrafted settlement whose NPCs have
persistent identities, homes, jobs, schedules and reactions to a nearby threat.

Terrain, lighting and the top-down camera command are reused from the bundled,
self-contained ``game/tools/data/base_terrain.json`` so the slice is immediately
playable overhead without re-authoring the terrain schema here and without
depending on any of Fio's demo maps. Everything RPG — where people live, what
they sell, who guards the square, what lurks east of the mill — comes from the
data file, so a community member reshapes the settlement by editing JSON.

Run from the repo root:  python -m game.tools.make_settlement
"""

from __future__ import annotations

import json
import os
import uuid

from game import data
from game.entities import sprite_for, portrait_for
from game.rpg import schedule as sched
from game.rpg import bestiary


def _uid():
    return str(uuid.uuid4())


def _art(props, role):
    """Bake per-role billboard art + scale so the map renders correct sprites
    without relying on entity construction defaults at load time."""
    tmpl = bestiary.get(role)
    props.setdefault("custom_idle", sprite_for(role))
    props.setdefault("custom_dead", sprite_for(role))
    props.setdefault("custom_shoot", sprite_for(role))
    props.setdefault("portrait", portrait_for(role))
    props.setdefault("monster_type", "human")
    props.setdefault("sprite_width", tmpl.scale if tmpl else 112)
    props.setdefault("sprite_height", tmpl.scale if tmpl else 112)
    return props


def _thing(ttype, pos, props, io=None):
    p = {"type": ttype, "name": props.get("name", ttype), "id": _uid()}
    p.update(props)
    p["type"] = ttype
    return {"type": ttype, "pos": list(pos), "properties": p, "io_connections": io or []}


def _marker_pos(markers, key):
    m = markers.get(key)
    return list(m["pos"]) if m else None


def _npc_schedule(npc, markers):
    """Build an NPC's schedule from its role default, pointing SLEEPING at the
    NPC's own bed marker so it beds down in the right spot (§12/§14)."""
    role = npc.get("role", "villager")
    entries = sched.schedule_for(role) or []
    bed = npc.get("bed")
    for e in entries:
        if e.get("state") == sched.SLEEPING and bed:
            e["location"] = bed
    return entries


def build(settlement: dict, base: dict) -> dict:
    markers = settlement.get("markers", {})

    world = {
        "version": base.get("version", 3),
        "brushes": base.get("brushes", []),
        "terrain_data": base.get("terrain_data", {"enabled": True}),
        "things": [],
    }

    # Reuse the base lighting + top-down camera command (drop its player start and
    # any base NPCs — the settlement supplies its own).
    for t in base.get("things", []):
        if str(t.get("type", "")).replace("_", "") in {"light", "logiccommand"}:
            world["things"].append(t)

    # --- player start ---
    ps = settlement.get("player_start", {"pos": [0, 272, 0], "angle": 0.0})
    world["things"].append(_thing("playerstart", ps["pos"], {
        "name": "PlayerStart_1", "angle": ps.get("angle", 0.0)}))

    # --- world settings (game clock + start scenario) ---
    w = settlement.get("world", {})
    world["things"].append(_thing("miniwindsettings",
                                  [ps["pos"][0], ps["pos"][1], ps["pos"][2] - 40], {
        "name": "MiniwindSettings_1",
        "start_hour": w.get("start_hour", 7.0),
        "start_day": w.get("start_day", 1),
        "minutes_per_day": w.get("minutes_per_day", 12.0),
        "show_clock": True,
        "state_store": "miniwind",
        "region_name": w.get("region_name", "The Vale of MiniWind"),
        "start_scenario": w.get("start_scenario", "quick"),
        "difficulty": w.get("difficulty", "normal"),
    }))

    # --- persistent quest/clock store ---
    world["things"].append(_thing("logic_keyvalue",
                                  [ps["pos"][0] + 40, ps["pos"][1], ps["pos"][2] - 40], {
        "name": "miniwind", "store_name": "miniwind", "initial_data": {}}))

    # --- markers (authored anchors NPCs reference by name) ---
    from game.entities import marker_sprite
    for mid, m in markers.items():
        kind = m.get("kind", "idle")
        world["things"].append(_thing("marker", m["pos"], {
            "name": mid, "marker_kind": kind, "hidden_in_game": True,
            "custom_idle": marker_sprite(kind)}))

    # --- NPCs (persistent identity, home/work/bed, role schedule, dialogue) ---
    for npc in settlement.get("npcs", []):
        home_pos = _marker_pos(markers, npc.get("home")) or list(ps["pos"])
        props = {
            "name": npc["name"],
            "display_name": npc.get("display_name", npc["name"]),
            "npc_role": npc.get("role", "villager"),
            "home": home_pos,
            "work_location": npc.get("work", ""),   # a marker name -> resolved live
            "schedule": _npc_schedule(npc, markers),
        }
        if "faction" in npc:
            props["faction"] = npc["faction"]
            props["team"] = npc["faction"]
        if npc.get("merchant"):
            props["merchant"] = True
            props["merchant_gold"] = npc.get("gold", 200)
        if "inventory" in npc:
            props["inventory"] = _resolve_inventory(npc["inventory"])
        if "dialogue" in npc:
            props["dialogue"] = npc["dialogue"]
        if "relationships" in npc:
            # Authored ties between townsfolk (sister / friend / sweetheart …).
            # Persisted on the NPC so dialogue and reactions can read them, and so
            # they survive save/load like any other identity data.
            props["relationships"] = npc["relationships"]
        if "patrol" in npc:
            # Patrol markers become the guard's schedule waypoints at night.
            props["patrol_markers"] = npc["patrol"]
        _art(props, npc.get("role", "villager"))
        world["things"].append(_thing("npc", home_pos, props))

    # --- the threat outside the settlement (hostile creatures, core MonsterAI) ---
    for threat in settlement.get("threats", []):
        role = threat.get("role", "bandit")
        world["things"].append(_thing("creature", threat["pos"], _art({
            "name": threat["name"],
            "display_name": threat.get("display_name", threat["name"]),
            "npc_role": role,
            "aggression": "hostile",
            # A modest sight range keeps the bandit camp dormant until the player
            # (or a patrolling guard) comes near — an encounter, not a spawn-war.
            "sight_range": 520,
        }, role)))

    return world


def _resolve_inventory(entries):
    """Expand ``[{"id","qty"}]`` shorthand into full item stacks from the item DB."""
    from game.rpg import items as rpg_items
    out = []
    for e in entries:
        stack = rpg_items.make(e["id"], e.get("qty", 1))
        if stack:
            out.append(stack)
    return out


def main():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    base_path = os.path.join(os.path.dirname(__file__), "data", "base_terrain.json")
    with open(base_path) as f:
        base = json.load(f)
    settlement = data.load("settlement")
    world = build(settlement, base)
    # Write to a distinct file so this generator never clobbers the hand-authored
    # canonical level (maps/village.json, the walled village). To put the living
    # settlement onto a level you keep editing, use
    # ``game.tools.apply_settlement_content`` instead, which upgrades NPC content
    # in place without touching geometry or placement.
    out = os.path.join(root, "maps", "village_flat.json")
    with open(out, "w") as f:
        json.dump(world, f, indent=2)
    print(f"wrote {out} with {len(world['things'])} things "
          f"({len(settlement.get('markers', {}))} markers, "
          f"{len(settlement.get('npcs', []))} NPCs, "
          f"{len(settlement.get('threats', []))} threats)")


if __name__ == "__main__":
    main()
