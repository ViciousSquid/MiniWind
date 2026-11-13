"""
Authored fixes and content for MiniWind's first hour, applied to the world map.

Each change here was found by playing the first hour on foot (see
docs/main_quest.md) and is applied to ``maps/miniwind_world.json`` by name,
idempotently: running the tool again changes nothing. It never moves geometry
or anything it does not name.

* **Bryn's pasture.** A spawn point 4.4 km north of Millbrook made two
  level-4 Fiends, respawning, beside the shepherd whose quest is to cull
  *wolves*. On the first morning they killed Bryn and a farmer, and mauled a
  level-1 player walking up to take his quest. It now makes three wolves.
* **The Old Mill's bandits do not come back.** Its spawner respawned, so
  "clearing" the mill never cleared it.
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
        if p.get("creature_role") == "wolf":
            continue
        p.update(creature_role="wolf", faction="wildlife", count=3)
        log.append("CreatureSpawn_1 by Bryn's pasture: two fiends -> three wolves")


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


STEPS = (fix_bryns_pasture, fix_old_mill_spawner, name_the_unnamed)


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
