"""
Authored fixes and content for MiniWind's first hour, applied to the world map.

Each change here was found by playing the first hour on foot (see
docs/main_quest.md) and is applied to ``maps/miniwind_world.json`` by name,
idempotently: running the tool again changes nothing. It never moves geometry
or anything it does not name.

* **Bryn's pasture.** A spawn point 4.4 km north of Millbrook had made two
  level-4 Fiends beside the shepherd whose quest is to cull *wolves*, and a
  save made during play had baked them into the map (as "Creature_19" and
  "Creature_20") and marked the spawner spent. Within minutes of the player
  arriving they killed Bryn and a farmer, and mauled a level-1 player walking
  up to take his quest. The baked Fiends are gone and the spawner makes three
  wolves at play start.
* **The Old Mill's bandits do not come back.** Its spawner respawned, so
  "clearing" the mill never cleared it.
* **Locked chests.** Only 14 of 330 containers were locked. Chests and
  hoards are now locked nine times in ten and crates half the time, with a
  lock as hard as what they guard; sacks, barrels and urns have none.
* **Aldric is the turn-in.** The mill quest starts with Elowen, so his
  hand-written offer and old-stage hand-in go.
* **Real names.** 81 generated townsfolk were called "Folk908 the Farmer",
  and Millbrook's two archers "Town Archer", in roll boxes, barks and
  conversation. Each gets a given name, kept in their title ("Edda the
  Farmer", "Joss of the Watch").

Run from the repo root::

    python -m game.tools.first_hour_content            # maps/miniwind_world.json
    python -m game.tools.first_hour_content in.json -o out.json
"""

from __future__ import annotations

import argparse
import json
import os
import re

WORLD = os.path.join("maps", "miniwind_world.json")

#: Given names for the townsfolk the populate tool left unnamed. Plain
#: country names, none already used by anyone in the Vale.
GIVEN_NAMES = (
    "Edda", "Joss", "Alys", "Bennet", "Cicely", "Dickon", "Emmot", "Fennel",
    "Gilly", "Hob", "Idony", "Jankin", "Kate", "Lambert", "Mabel", "Nicol",
    "Orrin", "Parnel", "Rafe", "Sibbe", "Tibbot", "Ursel", "Walt", "Avice",
    "Bartle", "Collet", "Davy", "Ellot", "Fritha", "Gib", "Hawise", "Ibbot",
    "Jacomin", "Larkin", "Magot", "Nan", "Ottilie", "Perkin", "Rohese", "Simkin",
    "Tace", "Watkin", "Amice", "Brice", "Clemence", "Drew", "Elyn", "Floss",
    "Goody", "Hick", "Isot", "Jeb", "Lovet", "Mild", "Ned", "Orrick", "Petronel",
    "Randal", "Sefton", "Tamar", "Wenna", "Abel", "Basset", "Colyn", "Dulcie",
    "Ebbe", "Femmy", "Garth", "Hester", "Jessop", "Kenelm", "Lark", "Merry",
    "Noll", "Pip", "Quenna", "Roger", "Saffy", "Tom", "Wiliam", "Aveline",
    "Benedict", "Cress", "Diggory", "Esme", "Fitch", "Gudrun", "Halley",
)

_FOLK = re.compile(r"Folk\d+(?= (?:the|of) )")


def _by_name(things, name):
    return [t for t in things if t.get("properties", {}).get("name") == name]


def fix_bryns_pasture(world, log):
    for t in _by_name(world["things"], "CreatureSpawn_1"):
        p = t["properties"]
        if p.get("creature_role") != "wolf":
            p.update(creature_role="wolf", faction="wildlife", count=3)
            log.append("CreatureSpawn_1 by Bryn's pasture: two fiends -> three wolves")
        if p.pop("_spawned", None) is not None:
            # A save made during play baked this spawner's two Fiends into the
            # map and marked it spent, so it never spawned again: the Fiends
            # stood by the pasture for good, named "Creature_19" and "_20".
            log.append("CreatureSpawn_1: spawns again at play start")
    baked = [t for t in world["things"] if t.get("type") == "creature"
             and t["properties"].get("npc_role") == "monster"
             and t["properties"].get("name") in ("Creature_19", "Creature_20")]
    for t in baked:
        world["things"].remove(t)
    if baked:
        log.append(f"removed the {len(baked)} Fiends baked in beside Bryn's pasture")


def fix_old_mill_spawner(world, log):
    for t in _by_name(world["things"], "BanditSpawner"):
        if t["properties"].get("respawn") is not False:
            t["properties"]["respawn"] = False
            log.append("BanditSpawner at the Old Mill: no longer respawns")


def name_the_unnamed(world, log):
    taken = set()
    for t in world["things"]:
        if t.get("type") == "npc":
            shown = str(t["properties"].get("display_name", ""))
            taken.add(re.split(r" (?:the|of) ", shown)[0])
    pool = [n for n in GIVEN_NAMES if n not in taken]
    people = [t for t in world["things"] if t.get("type") == "npc"]
    folk = [t for t in people if _FOLK.match(str(t["properties"].get("display_name", "")))]
    archers = [t for t in people if t["properties"].get("display_name") == "Town Archer"]
    if len(folk) + len(archers) > len(pool):
        raise SystemExit("not enough given names for %d townsfolk" % (len(folk) + len(archers)))
    for t in folk:
        p = t["properties"]
        given = pool.pop(0)
        p["display_name"] = _FOLK.sub(given, p["display_name"], count=1)
    for t in archers:
        t["properties"]["display_name"] = f"{pool.pop(0)} of the Watch"
    if folk or archers:
        log.append(f"named {len(folk)} generated townsfolk and {len(archers)} archers")


#: Barrow Hill, where Grunn's quest sends the player to clear the skeletons.
BARROW_HILL = (-4048.0, -15688.0)


def send_stray_skeletons_home(world, log):
    """Two hostile skeletons, left by the editor ("Creature_2", "Creature_2_644"),
    stood just outside Millbrook: one at Bryn's pasture and one at the
    windmill, where they killed the farmers who work there. They belong to
    the barrow."""
    import math
    barrow = [t for t in world["things"] if t.get("type") == "creature"
              and t["properties"].get("npc_role") == "skeleton"
              and math.hypot(t["pos"][0] - BARROW_HILL[0], t["pos"][2] - BARROW_HILL[1]) < 1200]
    ground_y = float(barrow[0]["pos"][1]) if barrow else 510.0
    moved = 0
    for i, name in enumerate(("Creature_2", "Creature_2_644")):
        for t in _by_name(world["things"], name):
            p = t["properties"]
            if p.get("npc_role") != "skeleton":
                continue
            x, z = BARROW_HILL[0] + 260.0 * (i - 0.5), BARROW_HILL[1] + 300.0
            t["pos"] = [x, ground_y, z]
            p["name"] = f"barrow_skeleton_{i + 1}"
            moved += 1
    if moved:
        log.append(f"moved {moved} stray skeletons from Millbrook's fields to Barrow Hill")


def rename_their_chests(world, log):
    """Containers named after an owner's old counter ("Folk1120's Chest")
    take the owner's given name, as the owner now has one."""
    given = {}
    for t in world["things"]:
        p = t["properties"]
        if t.get("type") == "npc" and p.get("name"):
            given[p["name"]] = re.split(r" (?:the|of) ", str(p.get("display_name", "")))[0]
    renamed = 0
    for t in world["things"]:
        p = t["properties"]
        if t.get("type") != "container":
            continue
        shown = str(p.get("display_name", ""))
        if re.match(r"Folk\d+'s ", shown) and given.get(p.get("owner")):
            p["display_name"] = re.sub(r"^Folk\d+", given[p["owner"]], shown)
            renamed += 1
    if renamed:
        log.append(f"renamed {renamed} containers after their owners")


#: Locks on the first hour's road. Only 14 of the world's 330 containers were
#: locked, the nearest 6.7 km from Millbrook, so a new player never met the
#: lockpicking at all. Two locks with no crime attached (a lockbox lost in
#: Bram's field outside Millbrook, the bandits' own strongbox at the Old Mill)
#: and one tempting and serious (the Reeve's toll chest at Hollin's Cross).
FIRST_LOCKS = (
    dict(name="old_mill_strongbox", display_name="Bandits' Strongbox",
         near="loc_old_mill_crate_f1", offset=(40.0, 60.0), lock="apprentice", owner=None,
         loot=(("gold", 60), ("potion_heal_minor", 2), ("lockpick", 2))),
    dict(name="rusted_lockbox", display_name="Rusted Lockbox", near="bram_farm",
         offset=(-60.0, 90.0), lock="novice", owner=None,
         loot=(("gold", 12), ("lockpick", 1), ("potion_heal_minor", 1))),
    dict(name="aldric_toll_chest", display_name="Toll Chest", near="aldric_bed",
         offset=(52.0, -40.0), lock="adept", owner="Aldric",
         loot=(("gold", 120), ("potion_heal", 1))),
)


def place_first_locks(world, log):
    import uuid
    from game.rpg import items as rpg_items
    things = world["things"]
    for spec in FIRST_LOCKS:
        if _by_name(things, spec["name"]):
            continue
        anchor = _by_name(things, spec["near"])
        if not anchor:
            raise SystemExit("no anchor %s for %s" % (spec["near"], spec["name"]))
        ax, ay, az = anchor[0]["pos"]
        props = {
            "type": "container", "name": spec["name"],
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "miniwind:first-hour:" + spec["name"])),
            "container_kind": "chest", "display_name": spec["display_name"],
            "inventory": [rpg_items.make(i, q) for i, q in spec["loot"]],
            "use_radius": 120.0, "locked": True, "lock_difficulty": spec["lock"],
            "custom_idle": "assets/sprites/miniwind/container_chest.png",
        }
        if spec["owner"]:
            props["owner"] = spec["owner"]
        things.append({"type": "container",
                       "pos": [round(ax + spec["offset"][0], 1), ay, round(az + spec["offset"][1], 1)],
                       "properties": props, "io_connections": []})
        log.append(f"placed {spec['display_name']} ({spec['lock']} lock)")


LOCK_TIERS = ("novice", "apprentice", "adept", "expert", "master")
#: Containers named for what they guard: hoards and coffers take the hard locks.
HOARDS = ("Hoard", "Coffer", "Strongbox", "Barrow Chest", "Cache")


def _stable_roll(props) -> float:
    """A fixed number in [0, 1) for this container, from its id: the same lock
    every time the tool runs, but varied across the world."""
    import hashlib
    key = str(props.get("id") or props.get("name") or "")
    return int(hashlib.sha1(key.encode()).hexdigest()[:8], 16) / 0x100000000


def lock_the_chests(world, log):
    """Most chests are locked, as they would be: only a tenth have a broken
    lock. Crates are padlocked half the time. A sack, a barrel or an urn has
    nothing to lock. How hard a lock is follows what it guards: the worth of
    what is inside, a merchant's chest a tier harder, a named hoard or coffer
    expert or master. Locks already authored are kept as they are."""
    people = {t["properties"].get("name"): t["properties"] for t in world["things"]
              if t.get("type") == "npc"}
    locked = 0
    for t in world["things"]:
        p = t["properties"]
        if t.get("type") != "container" or p.get("locked"):
            continue
        kind = str(p.get("container_kind", ""))
        roll = _stable_roll(p)
        shown = str(p.get("display_name", ""))
        if kind == "chest" or any(h in shown for h in HOARDS):
            if roll < 0.10 and not any(h in shown for h in HOARDS):
                continue                             # a broken lock: left open
        elif kind == "crate":
            if roll >= 0.5:
                continue
        else:
            continue
        worth = sum(int(i.get("value", 0) or 0) * int(i.get("qty", 1) or 1)
                    for i in p.get("inventory", []) if isinstance(i, dict))
        tier = 0 if worth < 20 else 1 if worth < 60 else 2 if worth < 150 else 3
        if kind == "crate":
            tier = min(tier, 1)
        owner = people.get(p.get("owner")) or {}
        if owner.get("merchant"):
            tier += 1
        if any(h in shown for h in HOARDS):
            tier = max(tier, 3)
        if roll > 0.85:
            tier += 1                                # now and then a better lock
        p["locked"] = True
        p["lock_difficulty"] = LOCK_TIERS[max(0, min(tier, len(LOCK_TIERS) - 1))]
        locked += 1
    if locked:
        log.append(f"locked {locked} chests and crates")


def aldric_is_the_turn_in(world, log):
    """Trouble at the Old Mill now starts with Elowen in Millbrook and ends
    with Aldric (quests/mill_bandits.quest, whose stage tells him what to
    say). His hand-written offer and his hand-in, keyed to the old stage
    numbers, would offer a quest already begun and pay out at the wrong
    step: both go, the rest of what he says stays."""
    for t in _by_name(world["things"], "Aldric"):
        dlg = t["properties"].get("dialogue")
        if not isinstance(dlg, dict):
            continue
        nodes = dlg.get("nodes") or {}
        start = nodes.get(dlg.get("start")) or {}
        before = len(start.get("responses") or [])
        start["responses"] = [r for r in start.get("responses") or []
                              if r.get("goto") not in ("offer_mill_bandits", "handin_mill_bandits")]
        gone = [k for k in ("offer_mill_bandits", "handin_mill_bandits") if k in nodes]
        for k in gone:
            del nodes[k]
        if gone or len(start["responses"]) != before:
            log.append("Aldric: no longer offers or hands in the Old Mill by hand")


STEPS = (fix_bryns_pasture, fix_old_mill_spawner, name_the_unnamed,
         send_stray_skeletons_home, rename_their_chests, place_first_locks,
         lock_the_chests, aldric_is_the_turn_in)


def apply(world):
    """Apply every step to *world* (the map's dict). Returns what changed."""
    log = []
    for step in STEPS:
        step(world, log)
    return log


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map", nargs="?", default=WORLD)
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args(argv)
    with open(args.map, "r", encoding="utf-8") as fh:
        world = json.load(fh)
    changes = apply(world)
    for line in changes:
        print(" *", line)
    if not changes:
        print("nothing to change")
        return
    with open(args.out or args.map, "w", encoding="utf-8") as fh:
        json.dump(world, fh, indent=4)     # the map's own layout, byte for byte


if __name__ == "__main__":
    main()
