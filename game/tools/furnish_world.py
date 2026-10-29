"""
Furnish the world: containers in the cottages, the inns and the camps, many
more in the caves, and books everywhere (game/library.py).

On the overworld (``maps/miniwind_world.json``) this tool adds:

* **Homes.** A chest, sack or barrel against the wall of every townsfolk home
  that has none, owned by the person who lives there (taking from it is
  theft), and now and then a second. Cottages keep bread, eggs, wool, a few
  coins, a torch -- and, often, a book.
* **Work places.** A crate or barrel at each inn bar, stall and shop, owned by
  whoever works there.
* **Camps and named places.** Unowned containers themed by the place: urns
  at shrines and barrows, crates and barrels at brigand and greenskin camps,
  a coffer at the Ashen Circle, cocooned bundles in the spider woods, packs
  at the wayside camps and ruins.
* **Books lying about** at some shrines, camps and ruins, and in some
  townsfolk's pockets (found on them if they fall).

In every cave (``maps/caveNN.json``) it adds several containers -- urns in
the crypts, cocooned bundles in the spider caves, crates in the greenskin
holes, a dead adventurer's pack -- on open floor away from the walls, the
monsters and the way in, a few of the chests locked, and sometimes a book
lying on the floor.

Every container's contents are rolled from the place's own table, with a
chance of a book from the place's shelf (``"found"`` in items.json). Every
pick is seeded by the place, so a run always furnishes the world the same
way. Everything it adds is tagged ``_furnished``, so running it again
replaces what the last run added rather than adding more.

Run from the repo root::

    python -m game.tools.furnish_world
    python -m game.tools.furnish_world --dry-run
"""

from __future__ import annotations

import argparse
import copy
import glob
import json
import math
import os
import uuid
import zlib
from typing import Dict, List, Optional, Sequence, Tuple

from .. import library
from . import expand_world as ew

OVERWORLD = ew.MAP
CAVE_GLOB = os.path.join("maps", "cave[0-9][0-9].json")
TAG = "_furnished"
SEED = 2026

#: How far above the raw terrain height things stand (as the world's other
#: generated containers do).
GROUND_LIFT = 48.0
#: A container's footprint half-width, and how clear of others it keeps.
FOOT = 26.0
SPACING = 70.0
#: A brush rising this far above the ground is in the way.
SOLID_ABOVE = 14.0

# ---------------------------------------------------------------------------
# What is in them
# ---------------------------------------------------------------------------
#: theme -> (item rows ``(id, chance, (lo, hi))``, gold (chance, lo, hi),
#: book (shelf, chance)).
TABLES: Dict[str, Tuple] = {
    "cottage": ((("bread", 0.6, (1, 3)), ("egg", 0.3, (2, 6)), ("wool", 0.2, (1, 2)),
                 ("ingr_flax", 0.25, (2, 5)), ("milk", 0.12, (1, 1)), ("torch", 0.25, (1, 2)),
                 ("cloth_trousers", 0.1, (1, 1)), ("cloth_wraps", 0.1, (1, 1)),
                 ("potion_heal_minor", 0.15, (1, 1)), ("copper_ring", 0.04, (1, 1)),
                 ("shovel", 0.05, (1, 1))),
                (0.55, 2, 18), (library.TOWN, 0.4)),
    "inn": ((("bread", 0.8, (2, 5)), ("potion_stamina", 0.2, (1, 2)), ("torch", 0.3, (1, 3)),
             ("egg", 0.3, (3, 8)), ("milk", 0.2, (1, 2))),
            (0.4, 5, 25), (library.TOWN, 0.5)),
    "work": ((("bread", 0.4, (1, 2)), ("torch", 0.3, (1, 2)), ("lockpick", 0.15, (1, 2)),
              ("repair_hammer", 0.1, (1, 1)), ("iron_arrow", 0.2, (5, 15))),
             (0.5, 3, 20), (library.TOWN, 0.3)),
    "camp": ((("bread", 0.6, (1, 3)), ("torch", 0.4, (1, 2)), ("potion_heal_minor", 0.3, (1, 1)),
              ("iron_arrow", 0.25, (4, 12)), ("lockpick", 0.15, (1, 2)),
              ("leather_boots", 0.08, (1, 1)), ("hide_cap", 0.06, (1, 1))),
             (0.5, 3, 30), (library.WILD, 0.3)),
    "shrine": ((("potion_cure", 0.35, (1, 1)), ("potion_heal_minor", 0.35, (1, 2)),
                ("bread", 0.3, (1, 2)), ("silver_amulet", 0.04, (1, 1)),
                ("copper_ring", 0.1, (1, 1))),
               (0.6, 3, 25), (library.SHRINE, 0.7)),
    "barrow": ((("ingr_bonemeal", 0.7, (1, 4)), ("copper_ring", 0.2, (1, 1)),
                ("silver_amulet", 0.06, (1, 1)), ("iron_shortsword", 0.15, (1, 1)),
                ("chain_coif", 0.06, (1, 1)), ("potion_heal", 0.15, (1, 1))),
               (0.7, 10, 60), (library.WILD, 0.25)),
    "crypt": ((("ingr_bonemeal", 0.7, (1, 4)), ("iron_shield", 0.15, (1, 1)),
               ("chain_leggings", 0.06, (1, 1)), ("silver_sword", 0.03, (1, 1)),
               ("copper_ring", 0.15, (1, 1)), ("potion_heal", 0.25, (1, 2)),
               ("potion_magicka", 0.15, (1, 1))),
              (0.7, 10, 70), (library.WILD, 0.3)),
    "bandit": ((("steel_arrow", 0.4, (5, 15)), ("iron_bolt", 0.25, (4, 12)),
                ("lockpick", 0.4, (1, 4)), ("potion_heal_minor", 0.35, (1, 2)),
                ("leather_cuirass", 0.12, (1, 1)), ("iron_dagger", 0.2, (1, 1)),
                ("bread", 0.3, (1, 3)), ("silver_amulet", 0.04, (1, 1))),
               (0.75, 10, 80), (library.BANDIT, 0.45)),
    "greenskin": ((("club", 0.25, (1, 1)), ("iron_battleaxe", 0.1, (1, 1)),
                   ("hide_armour", 0.15, (1, 1)), ("ingr_wolf_pelt", 0.4, (1, 3)),
                   ("iron_arrow", 0.3, (5, 15)), ("potion_heal_minor", 0.2, (1, 1))),
                  (0.6, 5, 50), (library.WILD, 0.25)),
    "cult": ((("potion_magicka", 0.5, (1, 2)), ("ingr_nightshade", 0.5, (1, 3)),
              ("iron_dagger", 0.25, (1, 1)), ("cloth_robe", 0.2, (1, 1)),
              ("cloth_hood", 0.2, (1, 1)), ("potion_shield", 0.1, (1, 1))),
             (0.6, 10, 60), (library.CULT, 0.6)),
    "nest": ((("elven_arrow", 0.2, (4, 12)), ("iron_helmet", 0.12, (1, 1)),
              ("leather_gauntlets", 0.12, (1, 1)), ("copper_ring", 0.15, (1, 1)),
              ("iron_shortsword", 0.15, (1, 1)), ("torch", 0.25, (1, 1))),
             (0.6, 5, 50), (library.WILD, 0.4)),
    "den": ((("ingr_wolf_pelt", 0.5, (1, 3)), ("ingr_bonemeal", 0.4, (1, 2)),
             ("leather_boots", 0.1, (1, 1)), ("hunting_bow", 0.05, (1, 1)),
             ("iron_arrow", 0.25, (3, 10))),
            (0.4, 2, 25), (library.WILD, 0.2)),
    "grotto": ((("ingr_mushroom", 0.7, (2, 6)), ("potion_stamina", 0.3, (1, 2)),
                ("potion_cure", 0.2, (1, 1)), ("ingr_nightshade", 0.2, (1, 2))),
               (0.4, 3, 30), (library.WILD, 0.25)),
    # A dead adventurer's pack: what was carried down, and often a journal.
    "remains": ((("torch", 0.6, (1, 2)), ("potion_heal_minor", 0.5, (1, 2)),
                 ("lockpick", 0.3, (1, 3)), ("iron_dagger", 0.2, (1, 1)),
                 ("bread", 0.3, (1, 2)), ("leather_helmet", 0.1, (1, 1))),
                (0.7, 5, 40), (library.WILD, 0.7)),
}

#: theme -> the kinds of container it is furnished with, most common first.
KINDS = {
    "cottage": ("chest", "sack", "barrel", "crate"), "inn": ("barrel", "crate"),
    "work": ("crate", "barrel", "sack"), "camp": ("sack", "crate", "barrel"),
    "shrine": ("urn", "chest"), "barrow": ("urn", "chest", "urn"),
    "crypt": ("urn", "chest", "urn", "sack"), "bandit": ("crate", "barrel", "chest", "sack"),
    "greenskin": ("crate", "sack", "barrel", "chest"), "cult": ("chest", "urn", "sack"),
    "nest": ("sack", "sack", "chest"), "den": ("sack",), "grotto": ("sack", "urn", "crate"),
    "remains": ("sack",),
}

#: Display names that read better than the kind alone.
NAMES = {("nest", "sack"): "Cocooned Bundle", ("remains", "sack"): "Adventurer's Pack",
         ("crypt", "urn"): "Burial Urn", ("barrow", "urn"): "Burial Urn",
         ("shrine", "urn"): "Offering Urn", ("cult", "chest"): "Ashen Coffer",
         ("bandit", "crate"): "Stolen Goods", ("greenskin", "chest"): "War Chest"}

#: How hard a locked chest's lock is, by theme; and how often a chest is locked.
LOCKS = {"crypt": "adept", "barrow": "adept", "bandit": "apprentice", "cult": "expert",
         "greenskin": "apprentice", "nest": "novice", "cottage": "novice"}
LOCK_CHANCE = {"cottage": 0.12}
DUNGEON_LOCK_CHANCE = 0.4

#: Named places on the overworld (``loc_*`` markers), by words in their names:
#: (theme, how many containers, chance of a book lying about).
PLACES = (
    (("shrine", "chapel", "moonwell", "saint_aldric", "greenmantle", "wayfarer"), "shrine", 1, 0.5),
    (("barrow", "crypt", "cairn", "gallows"), "barrow", 3, 0.2),
    (("brigand", "cutthroat", "smuggler", "raven_s_roost"), "bandit", 3, 0.3),
    (("greenskin", "snaggletooth", "rotfang"), "greenskin", 3, 0.2),
    (("ashen",), "cult", 2, 0.5),
    (("webwood", "silkhollow", "webfall"), "nest", 2, 0.3),
    (("wolf_den",), "den", 1, 0.0),
    (("ruin", "tower", "watchtower", "old_mill", "hob", "seven_sisters", "sunken_stones",
      "abandoned_camp", "dunstan_s_camp", "hunter_s_rest", "frostcap", "witch_s_knoll"),
     "camp", 2, 0.3),
)

#: Cave monsters (display names) -> the cave's theme.
CAVE_THEMES = (("Giant Spider", "nest"), ("Ashen Cultist", "cult"), ("Barrow Wight", "crypt"),
               ("Skeleton", "crypt"), ("Greenskin", "greenskin"), ("Smuggler", "bandit"),
               ("Bandit", "bandit"), ("Shroomling", "grotto"), ("Bear", "den"),
               ("Wolf", "den"), ("Dragon", "crypt"))
#: Containers per cave, and its chance of a book lying on the floor.
CAVE_CONTAINERS = (7, 10)
CAVE_BOOK_CHANCE = 0.5

#: Roles that keep a home with a container in it.
HOME_ROLES = frozenset({"farmer", "villager", "merchant", "blacksmith"})
#: Townsfolk who carry a book about with them.
POCKET_CHANCE = 0.12


def _uid(*parts):
    """A stable id for what this tool adds, so a run repeats exactly."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "miniwind-furnish|" + "|".join(map(str, parts))))


def _stack(item_id, qty):
    from ..rpg import items as rpg_items
    return rpg_items.make(item_id, int(qty)) or {"id": item_id, "qty": int(qty)}


def roll_contents(theme: str, rng) -> List[Dict]:
    """What a container of *theme* holds: rolled from its table, a little
    gold, perhaps a book; never empty."""
    rows, (gold_p, lo, hi), (shelf, book_p) = TABLES[theme]
    out = []
    for iid, chance, (qlo, qhi) in rows:
        if rng.random() < chance:
            out.append(_stack(iid, rng.randint(qlo, qhi)))
    if rng.random() < gold_p:
        out.append(_stack("gold", rng.randint(lo, hi)))
    if rng.random() < book_p:
        book = library.pick(rng, shelf)
        if book:
            out.append(_stack(book, 1))
            if rng.random() < book_p * 0.25:
                more = library.pick(rng, shelf, exclude=[book])
                if more and more != book:
                    out.append(_stack(more, 1))
    if not out:
        iid, _c, (qlo, qhi) = rows[0]
        out.append(_stack(iid, rng.randint(qlo, qhi)))
    return out


def container(theme, kind, pos, rng, name, owner=None, locked=None):
    """A Container thing of *kind* at *pos*, stocked for *theme*."""
    owner_name = ""
    if owner is not None:
        op = owner.get("properties", owner)
        first = str(op.get("name") or "").split("_")[0]
        owner_name = str(op.get("display_name") or first)
        display = f"{first}'s {kind.title()}"
    else:
        display = NAMES.get((theme, kind), kind.title())
    p = {"type": "container", "name": name, "id": _uid(name, *[round(float(v)) for v in pos]),
         "container_kind": kind,
         "display_name": display, "inventory": roll_contents(theme, rng),
         "use_radius": 120.0, "locked": False,
         "custom_idle": f"assets/sprites/miniwind/container_{kind}.png", TAG: True}
    # Turned as it was set down: a chest or crate square to the world (a
    # little askew), anything else any way at all (game/ui/world_objects.py).
    if kind in ("chest", "crate"):
        p["angle"] = round(rng.randrange(4) * 90.0 + rng.uniform(-8.0, 8.0), 1)
    else:
        p["angle"] = round(rng.uniform(0.0, 360.0), 1)
    if owner is not None:
        p["owner"] = str(op.get("name"))
        p["owner_name"] = owner_name
    if locked is None:
        locked = kind == "chest" and rng.random() < LOCK_CHANCE.get(theme, 0.0)
    if locked:
        p["locked"] = True
        p["lock_difficulty"] = LOCKS.get(theme, "novice")
    return {"type": "container", "pos": [round(float(v), 1) for v in pos],
            "properties": p, "io_connections": []}


def book_pickup(book_id, pos, name):
    """A book lying where it was left: walk over it to pick it up."""
    from ..rpg import items as rpg_items
    d = rpg_items.get(book_id)
    icon = f"assets/sprites/items/{book_id}.png"
    if not os.path.isfile(icon):
        icon = "assets/sprites/items/_book.png"
    return {"type": "itempickup", "pos": [round(float(v), 1) for v in pos],
            "properties": {"type": "itempickup", "name": name,
                           "id": _uid(name, *[round(float(v)) for v in pos]),
                           "item_id": book_id, "quantity": 1, "respawn": False,
                           "pickup_radius": 60.0, "custom_idle": icon,
                           "display_name": d.name if d else book_id,
                           "angle": float(zlib.crc32(name.encode("utf-8")) % 360), TAG: True},
            "io_connections": []}


def _strip(world) -> int:
    """Take out what an earlier run added. Returns how many things went."""
    before = len(world["things"])
    world["things"] = [t for t in world["things"] if not t.get("properties", {}).get(TAG)]
    meta = world.get("_miniwind_world")
    pockets = (meta or {}).pop("furnished_pockets", None) or []
    by_id = {t.get("properties", {}).get("id"): t for t in world["things"]}
    for npc_id, book in pockets:
        t = by_id.get(npc_id)
        inv = t.get("properties", {}).get("inventory") if t else None
        if isinstance(inv, list):
            for i, s in enumerate(inv):
                if isinstance(s, dict) and s.get("id") == book:
                    del inv[i]
                    break
    return before - len(world["things"])


# ---------------------------------------------------------------------------
# The overworld
# ---------------------------------------------------------------------------
class Overworld:
    """Places on the overworld map, and the furnishing of them."""

    CELL = 512.0

    def __init__(self, world, report=print):
        self.world = world
        self.report = report
        self.removed = _strip(world)
        td = world["terrain_data"]
        self.terrain = ew._terrain(td, heightmap=ew._load_heightmap(td))
        self._index_brushes()
        self.taken: List[Tuple[float, float]] = [
            (t["pos"][0], t["pos"][2]) for t in world["things"]
            if t.get("type") in ("container", "itempickup", "levelchanger", "playerstart",
                                 "spellbook")]
        self.added = {"containers": 0, "books": 0, "pockets": 0}

    # -- the ground and what stands on it ------------------------------------
    def _index_brushes(self):
        self.grid: Dict[Tuple[int, int], list] = {}
        for b in self.world["brushes"]:
            (x, y, z), (sx, sy, sz) = b["pos"], b["size"]
            tex = " ".join(str(v) for v in (b.get("textures") or {}).values()).lower()
            water = "water" in tex or "water" in str(b.get("shader", "")).lower()
            box = (x - sx / 2, x + sx / 2, z - sz / 2, z + sz / 2, y - sy / 2, y + sy / 2, water)
            for i in range(int(box[0] // self.CELL), int(box[1] // self.CELL) + 1):
                for j in range(int(box[2] // self.CELL), int(box[3] // self.CELL) + 1):
                    self.grid.setdefault((i, j), []).append(box)

    def ground(self, x, z) -> float:
        return float(ew._heights(self.terrain, [x], [z])[0])

    def _boxes_near(self, x, z, r):
        seen = set()
        for i in range(int((x - r) // self.CELL), int((x + r) // self.CELL) + 1):
            for j in range(int((z - r) // self.CELL), int((z + r) // self.CELL) + 1):
                for box in self.grid.get((i, j), ()):
                    if id(box) not in seen:
                        seen.add(id(box))
                        yield box

    def clear(self, x, z) -> bool:
        """Whether a container fits at (x, z): no wall, tree or water there,
        and clear of everything else placed."""
        g = self.ground(x, z) + GROUND_LIFT
        for x0, x1, z0, z1, y0, y1, water in self._boxes_near(x, z, FOOT):
            if x1 < x - FOOT or x0 > x + FOOT or z1 < z - FOOT or z0 > z + FOOT:
                continue
            if water or (y1 > g - GROUND_LIFT + SOLID_ABOVE and y0 < g + 80.0):
                return False
        return all((x - a) ** 2 + (z - b) ** 2 >= SPACING ** 2 for a, b in self.taken)

    def _wall_distance(self, x, z, reach=90.0) -> float:
        """How far (x, z) is from the nearest wall within *reach*."""
        best = reach
        g = self.ground(x, z)
        for x0, x1, z0, z1, y0, y1, water in self._boxes_near(x, z, reach):
            if water or y1 <= g + SOLID_ABOVE:
                continue
            dx = max(x0 - x, 0.0, x - x1)
            dz = max(z0 - z, 0.0, z - z1)
            best = min(best, math.hypot(dx, dz))
        return best

    def spot(self, x, z, rng, near=(60.0, 160.0), against_wall=True):
        """A clear spot around (x, z): against a wall when there is one."""
        candidates = []
        start = rng.random() * math.tau
        for ring in range(4):
            r = near[0] + (near[1] - near[0]) * ring / 3.0
            for k in range(16):
                a = start + k * math.tau / 16
                px, pz = x + math.cos(a) * r, z + math.sin(a) * r
                if self.clear(px, pz):
                    candidates.append((px, pz, r))
        if not candidates:
            return None
        if against_wall:
            px, pz, _r = min(candidates, key=lambda c: (round(self._wall_distance(c[0], c[1]) / 24.0), c[2]))
        else:
            px, pz, _r = candidates[0]
        self.taken.append((px, pz))
        return px, self.ground(px, pz) + GROUND_LIFT, pz

    # -- furnishing ----------------------------------------------------------
    def _add(self, thing):
        self.world["things"].append(thing)
        if thing["type"] == "container":
            self.added["containers"] += 1
            self.added["books"] += sum(library.is_book(s.get("id"))
                                       for s in thing["properties"]["inventory"])
        else:
            self.added["books"] += 1

    def homes(self):
        """A container (or two) at every townsfolk home without one."""
        things = self.world["things"]
        owners = {str(t["properties"].get("owner") or "") for t in things
                  if t.get("type") == "container"}
        seen = []
        for t in list(things):
            p = t.get("properties", {})
            if p.get("type") != "npc" or str(p.get("npc_role")) not in HOME_ROLES:
                continue
            home = p.get("home")
            if not (isinstance(home, list) and len(home) == 3):
                continue
            if str(p.get("name")) in owners:
                continue                       # already keeps one
            if any((home[0] - a) ** 2 + (home[2] - b) ** 2 < 220.0 ** 2 for a, b in seen):
                continue                       # a home already furnished
            seen.append((home[0], home[2]))
            rng = library.seeded(SEED, "home", p.get("id"))
            words = str(p.get("display_name") or "").lower()
            theme = "inn" if "innkeeper" in words else "cottage"
            for n in range(2 if rng.random() < 0.3 else 1):
                pos = self.spot(home[0], home[2], rng)
                if pos is None:
                    break
                kind = KINDS[theme][0 if n == 0 and rng.random() < 0.5
                                    else rng.randrange(len(KINDS[theme]))]
                self._add(container(theme, kind, pos, rng,
                                    f"{str(p.get('name')).split('_')[0]}'s{kind.title()}_f{n}",
                                    owner=t))

    def work_places(self):
        """A crate or barrel at each inn bar, stall, forge and shop."""
        npcs = [t for t in self.world["things"] if t.get("properties", {}).get("type") == "npc"]
        for t in list(self.world["things"]):
            p = t.get("properties", {})
            name = str(p.get("name") or "")
            if p.get("type") != "marker" or not name.endswith(("_bar", "_stall", "_forge", "_shop")):
                continue
            x, _y, z = t["pos"]
            owner = min(npcs, key=lambda n: (n["pos"][0] - x) ** 2 + (n["pos"][2] - z) ** 2,
                        default=None)
            if owner is not None and math.hypot(owner["pos"][0] - x, owner["pos"][2] - z) > 900:
                owner = None
            rng = library.seeded(SEED, "work", p.get("id"))
            theme = "inn" if name.endswith("_bar") else "work"
            pos = self.spot(x, z, rng)
            if pos is not None:
                kind = KINDS[theme][rng.randrange(len(KINDS[theme]))]
                self._add(container(theme, kind, pos, rng, f"{name}_{kind}_f", owner=owner))

    def places(self):
        """Containers, and books lying about, at camps and named places."""
        for t in list(self.world["things"]):
            p = t.get("properties", {})
            name = str(p.get("name") or "")
            if p.get("type") != "marker":
                continue
            if name.endswith("wayside_camp_camp"):
                theme, count, book_p = "camp", 2, 0.3
            elif name.startswith("loc_"):
                match = next((row for row in PLACES if any(w in name for w in row[0])), None)
                if match is None:
                    continue
                _words, theme, count, book_p = match
            else:
                continue
            x, _y, z = t["pos"]
            rng = library.seeded(SEED, "place", p.get("id"))
            for n in range(count):
                pos = self.spot(x, z, rng, near=(90.0, 420.0), against_wall=True)
                if pos is None:
                    break
                kinds = KINDS[theme]
                kind = kinds[0] if n == 0 else kinds[rng.randrange(len(kinds))]
                locked = kind == "chest" and rng.random() < DUNGEON_LOCK_CHANCE
                self._add(container(theme, kind, pos, rng, f"{name}_{kind}_f{n}",
                                    locked=locked))
            if rng.random() < book_p:
                shelf = TABLES[theme][2][0]
                book = library.pick(rng, shelf)
                pos = self.spot(x, z, rng, near=(60.0, 260.0), against_wall=False)
                if book and pos is not None:
                    self._add(book_pickup(book, pos, f"Book_{name}_f"))

    def pockets(self):
        """Now and then a townsperson carries a book about."""
        record = []
        for t in self.world["things"]:
            p = t.get("properties", {})
            if p.get("type") != "npc" or str(p.get("npc_role")) not in HOME_ROLES:
                continue
            rng = library.seeded(SEED, "pocket", p.get("id"))
            if rng.random() >= POCKET_CHANCE:
                continue
            inv = p.get("inventory")
            if not isinstance(inv, list):
                continue
            book = library.pick(rng, library.TOWN)
            if book is None:
                continue
            inv.append(_stack(book, 1))
            record.append([p.get("id"), book])
        self.world.setdefault("_miniwind_world", {})["furnished_pockets"] = record
        self.added["pockets"] = len(record)

    def run(self):
        removed = self.removed
        self.homes()
        self.work_places()
        self.places()
        self.pockets()
        a = self.added
        self.report(f"overworld: {a['containers']} containers, {a['books']} books and notes in "
                    f"them or lying about, {a['pockets']} in pockets"
                    + (f" (replacing {removed} from the last run)" if removed else ""))
        return self.world


# ---------------------------------------------------------------------------
# The caves
# ---------------------------------------------------------------------------
def cave_floor(cave) -> Dict[Tuple[int, int], Tuple[float, float]]:
    """The cave's open floor cells ``{(i, j): (x, z)}``, read back from its
    rock pillars (game/tools/make_caves.py lays one per solid cell, merged
    along rows, on a grid of CELL-unit squares)."""
    from .make_caves import CELL, GRID, _cell_pos
    pillars = []
    for b in cave["brushes"]:
        (x, y, z), (sx, sy, sz) = b["pos"], b["size"]
        if y - sy / 2 >= 1.0 or y + sy / 2 <= 40.0:
            continue                          # the floor slab, or nothing to bump into
        pillars.append((x - sx / 2, x + sx / 2, z - sz / 2, z + sz / 2))
    cells = {}
    for i in range(GRID):
        for j in range(GRID):
            x, z = _cell_pos(i, j)
            if not any(x0 < x < x1 and z0 < z < z1 for x0, x1, z0, z1 in pillars):
                cells[(i, j)] = (x, z)
    return cells


def cave_theme(cave) -> str:
    names = [str(t["properties"].get("display_name") or t["properties"].get("name") or "")
             for t in cave["things"] if t.get("type") in ("creature", "monster", "npc")]
    for monster, theme in CAVE_THEMES:
        if any(n.startswith(monster) for n in names):
            return theme
    return "crypt"


def furnish_cave(cave, slug, report=print):
    """Several containers through the cave, and sometimes a book on the floor."""
    from .make_caves import CELL
    removed = _strip(cave)
    cells = cave_floor(cave)
    theme = cave_theme(cave)
    rng = library.seeded(SEED, "cave", slug)

    def cell_of(x, z):
        return min(cells, key=lambda c: (cells[c][0] - x) ** 2 + (cells[c][1] - z) ** 2)

    def neighbours(c):
        i, j = c
        return sum((i + a, j + b) in cells for a, b in ((1, 0), (-1, 0), (0, 1), (0, -1)))

    # Distance (in steps) from the way in, to keep the entrance clear.
    start = next((t["pos"] for t in cave["things"] if t.get("type") == "playerstart"), None)
    dist = {}
    if start is not None and cells:
        frontier = [cell_of(start[0], start[2])]
        dist[frontier[0]] = 0
        while frontier:
            nxt = []
            for i, j in frontier:
                for c in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                    if c in cells and c not in dist:
                        dist[c] = dist[(i, j)] + 1
                        nxt.append(c)
            frontier = nxt
    busy = set()
    for t in cave["things"]:
        if t.get("type") in ("creature", "monster", "npc", "container", "levelchanger",
                             "playerstart", "itempickup", "spellbook"):
            ci, cj = cell_of(t["pos"][0], t["pos"][2])
            busy.update((ci + a, cj + b) for a in (-1, 0, 1) for b in (-1, 0, 1))
    # Against the walls first: a cell with open floor on two or three sides.
    open_cells = [c for c in sorted(cells) if c not in busy and dist.get(c, 99) >= 5]
    rng.shuffle(open_cells)
    open_cells.sort(key=lambda c: 0 if neighbours(c) in (2, 3) else 1)
    placed: List[Tuple[int, int]] = []

    def take():
        for c in open_cells:
            if all(abs(c[0] - a) + abs(c[1] - b) >= 3 for a, b in placed):
                placed.append(c)
                open_cells.remove(c)
                return c
        return None

    count = rng.randint(*CAVE_CONTAINERS)
    added = books = 0
    for n in range(count):
        c = take()
        if c is None:
            break
        here = "remains" if n == count - 1 else theme
        kinds = KINDS[here]
        kind = kinds[0] if n == 0 else kinds[rng.randrange(len(kinds))]
        locked = kind == "chest" and rng.random() < DUNGEON_LOCK_CHANCE
        x, z = cells[c]
        thing = container(here, kind, (x, 48.0, z), rng, f"{kind.title()}_{slug}_f{n}",
                          locked=locked)
        cave["things"].append(thing)
        added += 1
        books += sum(library.is_book(s.get("id")) for s in thing["properties"]["inventory"])
    if rng.random() < CAVE_BOOK_CHANCE:
        c = take()
        book = library.pick(rng, TABLES[theme][2][0] if theme != "den" else library.WILD)
        if c is not None and book:
            x, z = cells[c]
            cave["things"].append(book_pickup(book, (x, 40.0, z), f"Book_{slug}_f"))
            books += 1
    report(f"{slug}: {added} containers ({theme}), {books} books and notes"
           + (f" (replacing {removed})" if removed else ""))
    return cave


# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--map", default=OVERWORLD)
    ap.add_argument("--caves", default=CAVE_GLOB)
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    args = ap.parse_args(argv)
    with open(args.map) as f:
        world = json.load(f)
    Overworld(world).run()
    if not args.dry_run:
        ew.dump(world, args.map)
    for path in sorted(glob.glob(args.caves)):
        with open(path) as f:
            cave = json.load(f)
        furnish_cave(cave, os.path.splitext(os.path.basename(path))[0])
        if not args.dry_run:
            with open(path, "w") as f:
                json.dump(cave, f, indent=1)


if __name__ == "__main__":
    main()
