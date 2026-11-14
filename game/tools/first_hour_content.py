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
* **Hal Corbin's band.** The spawner's four anonymous bandits and the two
  "Bandit Archer"s are now Hal Corbin and three named men, tuned for a
  level-1 or 2 character, one archer on the far side. Hal carries the ledger.
* **The Old Mill grinds again.** It had no mill: now a windmill beside the
  old mill house, held (idle) while Hal Corbin lives, which Hollin's Cross
  buys from when it works. Its strongbox holds the Cross's stolen tolls.
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


#: Hal Corbin's band at the Old Mill, tuned for a level-1 or 2 character:
#: four men who stay dead, each with a real name, one archer posted on the
#: far side from the Millbrook road. Hal is tougher than his men but not the
#: stock level-5 bandit chief; he carries the ledger chapter one turns on.
OLD_MILL_BAND = (
    dict(name="Hal Corbin", role="bandit_chief", pos=(8840.0, 292.0, -5540.0),
         health=80, damage=11, level=2, xp=45, head="assets/sprites/heads/head18.png",
         carries=(("corbin_ledger", 1), ("gold", 25))),
    dict(name="Wat Fenner", role="bandit", pos=(8760.0, 292.0, -5700.0),
         health=50, damage=9, level=1, xp=14, head="assets/sprites/heads/head04.png",
         carries=(("gold", 6),)),
    dict(name="Ned Crake", role="bandit", pos=(8800.0, 292.0, -5480.0),
         health=50, damage=9, level=1, xp=14, head="assets/sprites/heads/head11.png",
         carries=(("gold", 4),)),
    dict(name="Jory Spratt", role="bandit_archer", pos=(9380.0, 292.0, -5960.0),
         health=40, damage=8, level=1, xp=16, head="assets/sprites/heads/head22.png",
         carries=(("iron_arrow", 6),)),
)

#: The Old Mill's own windmill, idle while Hal Corbin holds it
#: (game/windmills.py ``mill_held_by``): a copy of Mara's mill, sunk into the
#: ground as hers is.
OLD_MILL_WINDMILL = dict(name="old_mill_windmill", sails="old_mill_sails",
                         pos=(9100.0, 226.0, -5800.0), rotation=(0.0, 30.0, 0.0),
                         held_by="Hal Corbin")


def old_mill_band(world, log):
    """The Old Mill was held by four anonymous spawned bandits ("Creature_21"
    to "_24" in the roll boxes) and two "Bandit Archer"s, both on the
    Millbrook side: a level-1 player lost half their health in four seconds
    at the edge of the camp. Now it is Hal Corbin and three named men."""
    import uuid
    from game.rpg import items as rpg_items
    things = world["things"]
    gone = [t for t in things if t.get("properties", {}).get("name") in ("BanditSpawner",)
            or (t.get("type") == "creature"
                and t.get("properties", {}).get("display_name") == "Bandit Archer"
                and t.get("properties", {}).get("npc_role") == "bandit_archer"
                and 8000 < t["pos"][0] < 9800 and -6400 < t["pos"][2] < -5000)]
    for t in gone:
        things.remove(t)
    if gone:
        log.append(f"Old Mill: removed its spawner and {len(gone) - 1} anonymous archers")
    for spec in OLD_MILL_BAND:
        if _by_name(things, spec["name"]):
            continue
        props = {
            "type": "creature", "name": spec["name"], "display_name": spec["name"],
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "miniwind:old-mill:" + spec["name"])),
            "npc_role": spec["role"], "faction": "bandits", "aggression": "hostile",
            "health": spec["health"], "max_health": spec["health"], "damage": spec["damage"],
            "creature_level": spec["level"], "xp_value": spec["xp"],
            "custom_idle": spec["head"], "custom_shoot": spec["head"],
            "portrait": "assets/portraits/miniwind/bandit.png", "monster_type": "human",
            "sprite_width": 128, "sprite_height": 128, "monster_id": 0,
            "respawn_lair": False,
            "inventory": [rpg_items.make(i, q) for i, q in spec["carries"]],
        }
        things.append({"type": "creature", "pos": list(spec["pos"]),
                       "properties": props, "io_connections": []})
        log.append(f"Old Mill: placed {spec['name']} ({spec['role']})")


def old_mill_windmill(world, log):
    """The Old Mill had no mill at all: the Cross's mill is a copy of Mara's,
    held -- idle -- while Hal Corbin lives, a working mill once he is dead."""
    import copy
    import uuid
    things = world["things"]
    spec = OLD_MILL_WINDMILL
    if _by_name(things, spec["name"]):
        return
    body0 = next((t for t in _by_name(things, "windmill") if t["properties"].get("windmill")), None)
    sails0 = next((t for t in things if body0 is not None and t["properties"].get(
        "mill_rotor_for") == body0["properties"].get("id")), None)
    if body0 is None or sails0 is None:
        raise SystemExit("no windmill to copy for the Old Mill")
    body, sails = copy.deepcopy(body0), copy.deepcopy(sails0)
    bid = str(uuid.uuid5(uuid.NAMESPACE_URL, "miniwind:old-mill:windmill"))
    body["pos"] = list(spec["pos"])
    bp = body["properties"]
    bp.update(name=spec["name"], id=bid, display_name="The Old Mill",
              rotation=list(spec["rotation"]), mill_held_by=spec["held_by"])
    bp["inventory"] = []
    for key in ("mill_progress", "mill_updated_at", "flour_queue", "_bw_parked_disabled"):
        bp.pop(key, None)
    sails["pos"] = [spec["pos"][0], spec["pos"][1] + 550.0, spec["pos"][2]]
    sp = sails["properties"]
    sp.update(name=spec["sails"], id=str(uuid.uuid5(uuid.NAMESPACE_URL, "miniwind:old-mill:sails")),
              mill_rotor_for=bid, rotation=list(spec["rotation"]))
    things.extend([body, sails])
    log.append("Old Mill: placed its windmill, held while Hal Corbin lives")


def the_cross_buys_from_its_mill(world, log):
    """Hollin's Cross has always bought its flour from the Old Mill; while
    the mill is held, its brewer goes to the nearest working mill instead
    (game/flour_supply.py ``flour_mill``)."""
    mills = _by_name(world["things"], OLD_MILL_WINDMILL["name"])
    if not mills:
        return
    mid = mills[0]["properties"]["id"]
    for t in world["things"]:
        p = t["properties"]
        if p.get("display_name") == "Hollin Brewer" and p.get("flour_target"):
            if p.get("flour_mill") != mid:
                p["flour_mill"] = mid
                log.append("Hollin Brewer: buys from the Old Mill when it works")


def the_tolls_in_the_strongbox(world, log):
    """The strongbox at the Old Mill holds the Cross's stolen mill tolls, the
    Reeve's by right: taking them is theft from Aldric unless the player
    hands them back (quests/mill_bandits.quest ``returns``). The bandits' own
    potions and picks lie in the crate beside it."""
    from game.rpg import items as rpg_items
    for t in _by_name(world["things"], "old_mill_strongbox"):
        p = t["properties"]
        if p.get("owner") == "Aldric":
            continue
        loose = [s for s in p.get("inventory") or [] if s.get("id") != "gold"]
        p.update(owner="Aldric", owner_name="Aldric the Reeve", display_name="Toll Strongbox",
                 inventory=[rpg_items.make("toll_purse", 1)])
        for crate in _by_name(world["things"], "loc_old_mill_crate_f1"):
            crate["properties"].setdefault("inventory", []).extend(loose)
        log.append("Old Mill strongbox: holds the Cross's tolls, Aldric's by right")


#: Notice boards (the map had none, though the system was there): Millbrook
#: square by the market stalls, and Hollin's Cross at its crossroads.
NOTICE_BOARDS = (
    dict(name="millbrook_notice_board", pos=(150.0, 300.0, 60.0), angle=0.0),
    dict(name="hollins_cross_notice_board", pos=(8600.0, 300.0, 6640.0), angle=0.0),
)


def put_up_notice_boards(world, log):
    import uuid
    from game.entities import NOTICE_BOARD_SPRITE
    for spec in NOTICE_BOARDS:
        if _by_name(world["things"], spec["name"]):
            continue
        world["things"].append({"type": "noticeboard", "pos": list(spec["pos"]), "properties": {
            "type": "notice_board", "name": spec["name"], "display_name": "Notice Board",
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, "miniwind:board:" + spec["name"])),
            "use_radius": 120.0, "angle": spec["angle"], "custom_idle": NOTICE_BOARD_SPRITE,
        }, "io_connections": []})
        log.append(f"put up {spec['name']}")


def hals_brother_rook(world, log):
    """Hal Corbin's brother Rook lives with the bandits at Cutthroat Ridge.
    When word of Hal's death reaches him, the storyteller can send him after
    whoever did it -- a vendetta announced before he arrives, on the notice
    boards and in the departures news (docs/main_quest.md beat 13)."""
    things = world["things"]
    for t in _by_name(things, "Bandit_457"):
        p = t["properties"]
        p.update(name="Rook Corbin", display_name="Rook Corbin",
                 relationships={"Hal Corbin": "brother"})
        log.append("Cutthroat Ridge: Bandit_457 is Rook Corbin, Hal's brother")
    for t in _by_name(things, "Hal Corbin"):
        rels = t["properties"].setdefault("relationships", {})
        if rels.get("Rook Corbin") != "brother":
            rels["Rook Corbin"] = "brother"
            log.append("Hal Corbin: brother to Rook")


STEPS = (fix_bryns_pasture, fix_old_mill_spawner, name_the_unnamed,
         send_stray_skeletons_home, rename_their_chests, place_first_locks,
         lock_the_chests, aldric_is_the_turn_in, old_mill_band, old_mill_windmill,
         the_cross_buys_from_its_mill, the_tolls_in_the_strongbox, put_up_notice_boards,
         hals_brother_rook)


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
