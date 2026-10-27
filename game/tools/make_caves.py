"""
Caves: a mouth in the hills of the overworld, and a map for each cave.

For every cave this tool:

* finds a mouth at the foot of a mountain slope (steep ground rising behind,
  open ground in front, clear of every site and of the other caves);
* builds the mouth on the overworld -- two rock pillars, a lintel, a black
  back wall and a few boulders -- with a **LevelChanger** in the opening
  ("[E] Enter <cave>", no confirmation box) and a **PlayerStart** named
  ``<cave>_exit`` a few steps outside, facing away from it, plus a location
  marker so the place has a name;
* writes ``maps/<cave>.json``: a rock box -- a winding cave grown by a
  cellular automaton on a 128-unit grid, every solid cell a rock pillar --
  with a PlayerStart ``entrance`` just inside, a LevelChanger back to the
  overworld's ``<cave>_exit`` start, lights, its monsters and a chest.

The overworld's own start stays the primary one. Entering a cave and leaving
it carries the character across through the game's state store, as any
level change does.

The overworld records which caves it has, so running the tool again
replaces them rather than adding more.

Run from the repo root::

    python -m game.tools.make_caves
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import uuid

import numpy as np

from . import expand_world as ew

OVERWORLD = os.path.join("maps", "village_walled_source.json")

#: (map slug, name, monsters by display name, how many, loot)
CAVES = (
    ("cave01", "Wolfmaw Cave", ("Giant Spider",), 5,
     (("gold", 60), ("potion_heal", 2), ("steel_longsword", 1))),
    ("cave02", "The Bonepit", ("Skeleton",), 6,
     (("gold", 90), ("potion_magicka", 2), ("ring_of_protection", 1))),
    ("cave03", "Glowcap Grotto", ("Shroomling",), 6,
     (("gold", 40), ("potion_heal", 3), ("potion_stamina", 2))),
    ("cave04", "Greenskin Hole", ("Greenskin",), 5,
     (("gold", 120), ("iron_shield", 1), ("potion_heal", 1))),
    ("cave05", "Frostfang Cavern", ("Giant Spider", "Skeleton"), 6,
     (("gold", 150), ("potion_heal", 2), ("steel_helmet", 1))),
    ("cave06", "Whisperdeep", ("Skeleton", "Shroomling"), 6,
     (("gold", 80), ("potion_magicka", 2), ("potion_heal", 2))),
    ("cave07", "Rattlebone Warren", ("Skeleton", "Skeleton Archer"), 7,
     (("gold", 110), ("potion_heal", 2), ("silver_sword", 1))),
    ("cave08", "Gloomroot Hollow", ("Shroomling", "Giant Spider"), 6,
     (("gold", 70), ("potion_cure", 2), ("potion_stamina", 2))),
    ("cave09", "Wrecker's Hole", ("Smuggler", "Bandit"), 6,
     (("gold", 160), ("crossbow", 1), ("steel_bolt", 20))),
    ("cave10", "Bearclaw Den", ("Bear", "Wolf"), 5,
     (("gold", 30), ("fur_cuirass", 1), ("potion_heal", 2))),
    ("cave11", "The Ashen Deep", ("Ashen Cultist", "Skeleton"), 6,
     (("gold", 140), ("potion_magicka", 3), ("book_blade", 1))),
    ("cave12", "Wightfall Barrow", ("Barrow Wight", "Skeleton", "Skeleton Archer"), 7,
     (("gold", 200), ("kite_shield", 1), ("elven_arrow", 15))),
    ("cave13", "Briarweb Cavern", ("Giant Spider",), 6,
     (("gold", 80), ("potion_cure", 2), ("potion_heal", 2))),
    ("cave14", "Hollowguard Crypt", ("Skeleton", "Skeleton Archer"), 7,
     (("gold", 130), ("silver_sword", 1), ("potion_magicka", 2))),
    ("cave15", "Mossveil Grotto", ("Shroomling", "Giant Spider"), 6,
     (("gold", 90), ("potion_heal", 3), ("potion_stamina", 3))),
    ("cave16", "Redfang Burrow", ("Greenskin", "Greenskin Archer"), 7,
     (("gold", 150), ("iron_shield", 1), ("steel_arrow", 20))),
    ("cave17", "Rimeclaw Den", ("Snow Bear", "Wolf"), 5,
     (("gold", 70), ("fur_cuirass", 1), ("potion_heal", 3))),
    ("cave18", "Cinderfall Hollow", ("Ashen Cultist", "Skeleton"), 6,
     (("gold", 190), ("potion_magicka", 3), ("book_blade", 1))),
    ("cave19", "Blackwater Hideout", ("Smuggler", "Bandit Archer"), 6,
     (("gold", 180), ("crossbow", 1), ("steel_bolt", 25))),
    ("cave20", "Moonfang Refuge", ("Wolf", "Bear"), 6,
     (("gold", 60), ("potion_heal", 3), ("potion_stamina", 2))),
)

#: The sole dragon lives in Whisperdeep; adding caves must not add dragons.
DRAGON_CAVE = "cave06"
#: A great hall carved out of the cave, one dragon and its hoard.
LAIRS = {
    DRAGON_CAVE: {
        "dragon": {
            "display_name": "Vharzul the Ember Wyrm", "head": "dragon",
            # Five times the player's head size, and hit points to match.
            "head_scale": 5.0, "health": 3000, "max_health": 3000,
            # It bites what is close; what is not, it burns (game/dragon_fire.py).
            "damage": 45, "attack_style": "melee", "creature_level": 30,
            "breathes_fire": True, "breath_damage": 14,
            "xp_value": 2500, "move_speed": 70.0, "sight_range": 1500, "sight": 1500,
            "courage": 1.0, "resist_fire": 1.0, "loot": "",
            "equipped_weapon": "",
        },
        "gold_piles": 80,
        #: FIRE Effects the breath is made of, parked under the floor.
        "flames": 16,
    },
}

ROCK = "tiledrock.jpg"
ROCK_TOP = "Stone_09-512x512.png"
FLOOR = "cave.png"
BLACK = "_black.jpg"

#: Cave grid: cells per side and the size of one.
GRID = 30
CELL = 128.0
WALL_HEIGHT = 320.0
#: Keep the changer and a standing player beyond the shoulder's front edge,
#: including diagonal mouths (the shoulder is an axis-aligned 520-unit box).
MOUTH_CHANGER_OFFSET = 220.0
#: Prefer wide spacing, relaxing only as far as needed to place every cave.
MOUTH_SPACINGS = (10000.0, 8000.0, 6500.0, 5000.0)


def _uid():
    return str(uuid.uuid4())


def _tex(side, top=None, down=None):
    t = {k: side for k in ("north", "south", "east", "west")}
    t["top"] = top or side
    t["down"] = down or side
    return t


def _editor_angle(dx, dz):
    """The PlayerStart angle (editor degrees) that faces along (dx, dz)."""
    g = math.atan2(dx, dz)
    return round((90.0 - math.degrees(g - math.pi)) % 360.0, 1)


def _thing(kind, pos, **props):
    p = {"type": kind, "name": props.pop("name", kind), "id": _uid()}
    p.update(props)
    return {"type": kind, "pos": [round(float(v), 1) for v in pos],
            "properties": p, "io_connections": []}


def _light(name, pos, radius, colour, intensity=2.0):
    return _thing("light", pos, name=name, colour=list(colour), intensity=intensity,
                  radius=float(radius), state="on", show_radius=False,
                  casts_shadows=False, parent_mover="", parent_offset=[0.0, 0.0, 0.0])


def _changer(name, pos, target, spawn, prompt):
    return _thing("levelchanger", pos, name=name, target_map=target, delay=0.0,
                  fade_time=0.5, show_radius=False, radius=170.0, usable=True,
                  destination_spawn=spawn, generate_level=False,
                  prompt=prompt, confirm=False)


def _stack(item_id, qty):
    from ..rpg import items as rpg_items
    return rpg_items.make(item_id, int(qty)) or {"id": item_id, "qty": int(qty)}


def _start(name, pos, angle, index, primary=False):
    return _thing("playerstart", pos, name=name, angle=angle,
                  primary=primary, creation_index=index)


# ---------------------------------------------------------------------------
# The overworld side
# ---------------------------------------------------------------------------
class CaveMouths:
    def __init__(self, world, report=print):
        self.world = world
        self.report = report
        td = world["terrain_data"]
        self.terrain = ew._terrain(td, heightmap=ew._load_heightmap(td))
        (self.lo, self.hi), _ = self.terrain.get_terrain_bounds()

    def ground(self, x, z):
        return float(ew._heights(self.terrain, [x], [z])[0])

    def _remove_old(self):
        """Drop the caves an earlier run made."""
        tag = "_cave"
        self.world["brushes"] = [b for b in self.world["brushes"] if not b.get(tag)]
        self.world["things"] = [t for t in self.world["things"]
                                if not t.get("properties", {}).get(tag)]

    def existing(self):
        """``{slug: (x, z)}`` of the cave mouths already on the overworld."""
        out = {}
        for t in self.world["things"]:
            p = t.get("properties", {})
            if t["type"] == "levelchanger" and p.get("_cave"):
                out[p["_cave"]] = (float(t["pos"][0]), float(t["pos"][2]))
        return out

    def find_spots(self, count, seed=5, avoid=(), spacing=10000.0):
        """*count* cave mouths ``(x, z, ground, downhill (dx, dz))``, at
        least *spacing* from each other and from every ``(x, z)`` in *avoid*
        (the caves already there). Fill the largest gaps first, choosing
        among safe foothills rather than clustering on the steepest slopes."""
        if count <= 0:
            return []
        rng = np.random.default_rng(seed)
        content = np.array([(b["pos"][0], b["pos"][2]) for b in self.world["brushes"]
                            if not ew.Expander._is_tree(b)]
                           + [(t["pos"][0], t["pos"][2]) for t in self.world["things"]
                              if t["type"] not in ("creature",)], np.float32)
        margin = 3500.0
        n = 160
        axis = np.linspace(self.lo + margin, self.hi - margin, n, dtype=np.float32)
        X, Z = np.meshgrid(axis, axis)
        xs, zs = X.ravel(), Z.ravel()
        h = ew._heights(self.terrain, xs, zs)
        step = 500.0
        best = []
        for k in range(8):
            a = 2 * math.pi * k / 8
            dx, dz = math.cos(a) * step, math.sin(a) * step
            rise = ew._heights(self.terrain, xs + dx, zs + dz) - h
            best.append((rise, dx / step, dz / step))
        rises = np.stack([b[0] for b in best])
        k_up = np.argmax(rises, axis=0)
        up = rises[k_up, np.arange(len(xs))]
        # The opening: steep ground rising behind (a slope of 1 in 2 or so),
        # level ground in front.
        front = ew._heights(self.terrain,
                            xs - np.array([best[k][1] for k in k_up]) * 400.0,
                            zs - np.array([best[k][2] for k in k_up]) * 400.0) - h
        score = up - np.abs(front) * 2.0
        # Foothills only: the mouth is at about the lowland's height, so it
        # can be walked to.
        lowland = float(np.percentile(h, 40))
        ok = (up > 160.0) & (np.abs(front) < 60.0) & (h < lowland + 220.0)
        order = np.argsort(-score)
        candidates = []
        for i in order:
            if not ok[i]:
                continue
            x, z = float(xs[i]), float(zs[i])
            x += float(rng.uniform(-60, 60))
            z += float(rng.uniform(-60, 60))
            if len(content) and np.min(np.hypot(content[:, 0] - x, content[:, 1] - z)) < 2600:
                continue
            ux, uz = best[int(k_up[i])][1], best[int(k_up[i])][2]
            candidates.append((x, z, (-ux, -uz)))
        if not candidates:
            return []
        points = np.asarray([(x, z) for x, z, _ in candidates])
        nearest = np.full(len(points), np.inf)
        for x, z in avoid:
            nearest = np.minimum(nearest, np.hypot(points[:, 0] - x, points[:, 1] - z))
        spots = []
        while len(spots) < count:
            i = int(np.argmax(nearest))
            if nearest[i] < spacing:
                break
            x, z, downhill = candidates[i]
            spots.append((x, z, self.ground(x, z), downhill))
            nearest = np.minimum(nearest, np.hypot(points[:, 0] - x, points[:, 1] - z))
            nearest[i] = -np.inf
        return spots

    def build(self, slug, name, spot, index):
        x, z, g, (dx, dz) = spot
        brushes, things = self.world["brushes"], self.world["things"]
        px, pz = -dz, dx                      # across the opening
        tag = {"_cave": slug}

        def brush(cx, cz, size, textures, base=None, **extra):
            b0 = self.ground(cx, cz) if base is None else base
            b = {"pos": [round(cx, 1), round(b0 + size[1] / 2.0 - 12.0, 1), round(cz, 1)],
                 "size": [float(v) for v in size], "textures": textures, "id": _uid()}
            b.update(tag)
            b.update(extra)
            brushes.append(b)
            return b
        rock = _tex(ROCK, ROCK_TOP)
        # The black of the tunnel, set back into the slope.
        bx, bz = x - dx * 70.0, z - dz * 70.0
        brush(bx, bz, (300.0 if abs(px) > abs(pz) else 40.0, 230.0,
                       40.0 if abs(px) > abs(pz) else 300.0), _tex(BLACK), base=g)
        # Pillars either side, a lintel over them, a shoulder of rock behind.
        for side in (-1, 1):
            brush(x + px * side * 190.0, z + pz * side * 190.0, (110.0, 300.0, 110.0), rock, base=g)
        brush(x - dx * 20.0, z - dz * 20.0,
              (460.0, 100.0, 130.0) if abs(px) > abs(pz) else (130.0, 100.0, 460.0),
              rock, base=g + 250.0)
        brush(x - dx * 200.0, z - dz * 200.0, (520.0, 340.0, 520.0), rock, base=g - 20.0)
        rng = np.random.default_rng(sum(map(ord, slug)))
        for _ in range(5):
            a = rng.uniform(0, 2 * math.pi)
            r = rng.uniform(320, 620)
            s = float(rng.uniform(60, 140))
            brush(x + math.cos(a) * r, z + math.sin(a) * r, (s, s * 0.7, s * 1.1), rock)
        cx, cz = x + dx * MOUTH_CHANGER_OFFSET, z + dz * MOUTH_CHANGER_OFFSET
        things.append(_changer(f"LevelChanger_{slug}", (cx, self.ground(cx, cz) + 64.0, cz),
                               f"maps/{slug}.json", "entrance", f"[E] Enter {name}"))
        things[-1]["properties"].update(tag)
        sx, sz = x + dx * 300.0, z + dz * 300.0
        things.append(_start(f"{slug}_exit", (sx, self.ground(sx, sz) + 72.0, sz),
                             _editor_angle(dx, dz), index))
        things[-1]["properties"].update(tag)
        things.append(_light(f"Light_{slug}_mouth", (x + dx * 120.0, g + 180.0, z + dz * 120.0),
                             420.0, (255, 170, 100), 1.6))
        things[-1]["properties"].update(tag)
        things.append(_thing("marker", (x + dx * 150.0, g + 72.0, z + dz * 150.0),
                             name=f"loc_{slug}", marker_kind="location", place_name=name,
                             discover_radius=700.0, **tag))
        return (sx, sz)

    def settle_primary(self, first_index):
        """The overworld's own start stays primary; cave exits come after."""
        for t in self.world["things"]:
            p = t.get("properties", {})
            if t["type"] == "playerstart" and not p.get("_cave"):
                p["primary"] = True
                p["creation_index"] = 0
        return first_index


# ---------------------------------------------------------------------------
# The cave maps
# ---------------------------------------------------------------------------
def grow_cave(seed, n=GRID):
    """A connected cave on an n x n grid (True = open floor) and its mouth
    cell ``(i, j)`` on the south edge."""
    rng = np.random.default_rng(seed)
    open_ = rng.random((n, n)) < 0.54
    open_[0, :] = open_[-1, :] = open_[:, 0] = open_[:, -1] = False
    for _ in range(5):
        p = np.pad(open_, 1)
        nb = sum(np.roll(np.roll(p, a, 0), b, 1)[1:-1, 1:-1]
                 for a in (-1, 0, 1) for b in (-1, 0, 1) if (a, b) != (0, 0))
        open_ = (nb >= 5) | (open_ & (nb >= 4))
        open_[0, :] = open_[-1, :] = open_[:, 0] = open_[:, -1] = False
    # The mouth: a passage from the middle of the south edge up into the cave.
    mid = n // 2
    for i in range(n - 1, n // 2 - 1, -1):
        open_[i, mid - 1:mid + 2] = True
        if i < n - 4 and open_[i - 1, mid]:
            break
    open_[n - 1, mid - 1:mid + 2] = True
    # Keep what connects to the mouth.
    seen = np.zeros_like(open_)
    stack = [(n - 1, mid)]
    while stack:
        i, j = stack.pop()
        if not (0 <= i < n and 0 <= j < n) or seen[i, j] or not open_[i, j]:
            continue
        seen[i, j] = True
        stack.extend(((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)))
    return seen, (n - 1, mid)


def _cell_pos(i, j, n=GRID):
    """World (x, z) of grid cell (row i, column j): rows run along +z."""
    return ((j - n / 2.0 + 0.5) * CELL, (i - n / 2.0 + 0.5) * CELL)


def build_cave_map(slug, name, monsters, count, loot, settings, camera, protos,
                   overworld_path=OVERWORLD, seed=0):
    open_, (mi, mj) = grow_cave(seed)
    n = GRID
    lair = LAIRS.get(slug)
    hall = None
    if lair:
        # The great hall, in the north of the cave, joined to the mouth by a
        # wide passage.
        hall = (8, n // 2, 7.5)
        I, J = np.mgrid[0:n, 0:n]
        ragged = 0.6 * np.sin(I * 1.7) * np.cos(J * 1.3)
        open_ |= (np.hypot(I - hall[0], J - hall[1]) + ragged) <= hall[2]
        open_[hall[0]:mi + 1, mj - 1:mj + 2] = True
        open_[0, :] = open_[:, 0] = open_[:, -1] = False
        open_[n - 1, :] = False
        open_[n - 1, mj - 1:mj + 2] = True
    brushes, things = [], []
    rock = _tex(ROCK, ROCK_TOP)
    # Floor under everything (its top at y = 0), rock walls a cell thick
    # beyond the grid, and every solid cell inside it a rock pillar --
    # merged along rows so a cave is a few dozen brushes, not hundreds.
    span = (n + 2) * CELL
    brushes.append({"pos": [0.0, -16.0, 0.0], "size": [span, 32.0, span + CELL * 4],
                    "textures": _tex(ROCK, FLOOR), "id": _uid()})
    solid = np.pad(~open_, 1, constant_values=True)
    # The passage runs on past the grid's edge, to a black wall: the dark
    # of the way out.
    solid[n + 1, mj:mj + 3] = False
    for r in range(solid.shape[0]):
        c = 0
        while c < solid.shape[1]:
            if not solid[r, c]:
                c += 1
                continue
            c0 = c
            while c < solid.shape[1] and solid[r, c]:
                c += 1
            i, j0, j1 = r - 1, c0 - 1, c - 2
            x0, z = _cell_pos(i, j0)
            x1, _ = _cell_pos(i, j1)
            h = WALL_HEIGHT + 32.0 * ((r * 7 + c0 * 3) % 5)
            brushes.append({"pos": [round((x0 + x1) / 2.0, 1), h / 2.0, round(z, 1)],
                            "size": [(j1 - j0 + 1) * CELL, h, CELL],
                            "textures": rock, "id": _uid()})
    # The mouth: a black wall at the end of the passage, the way back out.
    mx, mz = _cell_pos(mi, mj)
    brushes.append({"pos": [mx, 140.0, mz + CELL * 1.5], "size": [CELL * 3, 280.0, 32.0],
                    "textures": _tex(BLACK), "id": _uid()})
    things.append(_changer(f"LevelChanger_{slug}_out", (mx, 64.0, mz + CELL * 0.6),
                           overworld_path.replace(os.sep, "/"), f"{slug}_exit",
                           f"[E] Leave {name}"))
    sx, sz = _cell_pos(mi - 3, mj)
    things.append(_start("entrance", (sx, 72.0, sz), _editor_angle(0.0, -1.0), 0, primary=True))
    things.append(_light("Light_daylight", (mx, 220.0, mz - CELL), 700.0, (200, 215, 255), 1.4))
    # Distance from the mouth through the cave, to place things deeper in.
    dist = np.full(open_.shape, -1)
    dist[mi, mj] = 0
    frontier = [(mi, mj)]
    while frontier:
        nxt = []
        for i, j in frontier:
            for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= a < n and 0 <= b < n and open_[a, b] and dist[a, b] < 0:
                    dist[a, b] = dist[i, j] + 1
                    nxt.append((a, b))
        frontier = nxt
    rng = np.random.default_rng(seed + 1)
    # Open cells with open neighbours all round: room to stand in.
    roomy = open_.copy()
    roomy[1:-1, 1:-1] &= (open_[:-2, 1:-1] & open_[2:, 1:-1] & open_[1:-1, :-2] & open_[1:-1, 2:])
    cells = [(int(i), int(j)) for i, j in zip(*np.nonzero(roomy)) if dist[i, j] >= 6]
    rng.shuffle(cells)
    deepest = max(((int(i), int(j)) for i, j in zip(*np.nonzero(roomy))),
                  key=lambda c: dist[c])
    # Lights through the cave, warm torches and cold glows.
    lit = []
    for i, j in sorted(cells, key=lambda c: dist[c]):
        if all(abs(i - a) + abs(j - b) >= 7 for a, b in lit):
            lit.append((i, j))
    for k, (i, j) in enumerate(lit[:8]):
        x, z = _cell_pos(i, j)
        colour = (255, 150, 80) if k % 2 == 0 else (120, 200, 255)
        things.append(_light(f"Light_{k}", (x, 200.0, z), 620.0, colour, 1.8))
    if lair:
        _furnish_lair(things, lair, hall, open_, slug)
        count = 0
    # Monsters, in the deeper part.
    placed = 0
    for i, j in cells:
        if placed >= count or dist[i, j] < 10:
            continue
        proto = protos.get(monsters[placed % len(monsters)])
        if proto is None:
            continue
        c = copy.deepcopy(proto)
        p = c["properties"]
        for k in [k for k in p if k.startswith("_")]:
            del p[k]
        x, z = _cell_pos(i, j)
        c["pos"] = [round(x, 1), 40.0, round(z, 1)]
        p.update({"name": f"{p.get('display_name', 'Creature')}_{slug}_{placed}",
                  "id": _uid(), "home": [round(x, 1), 40.0, round(z, 1)],
                  "awake": False, "triggered": False, "respawn": False})
        c["io_connections"] = []
        things.append(c)
        placed += 1
    # The prize at the far end.
    x, z = _cell_pos(*deepest)
    things.append(_thing("container", (x, 48.0, z), name=f"Chest_{slug}",
                         container_kind="chest", display_name="Chest",
                         inventory=[_stack(iid, q) for iid, q in loot],
                         use_radius=128.0, locked=False,
                         custom_idle="assets/sprites/miniwind/container_chest.png"))
    things.append(_light("Light_hoard", (x, 160.0, z), 520.0, (255, 210, 120), 2.0))
    s = copy.deepcopy(settings)
    s["pos"] = [0.0, 400.0, 0.0]
    s["properties"].update({"id": _uid(), "region_name": name,
                            # Underground: cave music only (game/music.py).
                            "underground": True})
    s["io_connections"] = []
    things.append(s)
    if camera is not None:
        cam = copy.deepcopy(camera)
        cam["pos"] = [0.0, 420.0, 64.0]
        cam["properties"]["id"] = _uid()
        things.append(cam)
    return {"version": 3, "brushes": brushes, "things": things,
            "created": "make_caves", "terrain_data": {"enabled": False},
            "_miniwind_cave": {"name": name, "overworld": overworld_path.replace(os.sep, "/")}}


def _furnish_lair(things, lair, hall, open_, slug):
    """The dragon in the middle of its hall, gold everywhere around it."""
    hi, hj, r = hall
    x, z = _cell_pos(hi, hj)
    props = {"type": "creature", "name": f"Dragon_{slug}", "id": _uid(),
             "npc_role": "dragon", "faction": "monsters", "team": "monsters",
             "aggression": "hostile", "combatant": True, "triggered": False,
             "wake_on_sight": True, "awake": False, "respawn": False, "roam": False,
             "persistent": True, "monster_type": "human", "inventory": [],
             "home": [round(x, 1), 40.0, round(z, 1)],
             "portrait": "assets/portraits/miniwind/monster.png"}
    props.update(lair["dragon"])
    things.append({"type": "creature", "pos": [round(x, 1), 40.0, round(z, 1)],
                   "properties": props, "io_connections": []})
    rng = np.random.default_rng(sum(map(ord, slug)) + 7)
    n = open_.shape[0]
    cells = [(i, j) for i in range(n) for j in range(n)
             if open_[i, j] and math.hypot(i - hi, j - hj) <= r + 0.5]
    for k in range(int(lair.get("gold_piles", 60))):
        i, j = cells[int(rng.integers(len(cells)))]
        gx, gz = _cell_pos(i, j)
        gx += float(rng.uniform(-50, 50))
        gz += float(rng.uniform(-50, 50))
        things.append(_thing("itempickup", (gx, 24.0, gz), name=f"Gold_{slug}_{k}",
                             item_id="gold", quantity=int(rng.integers(8, 45)),
                             respawn=False, pickup_radius=60.0,
                             custom_idle="assets/sprites/items/gold.png"))
    for k in range(int(lair.get("flames", 0))):
        things.append(_thing("effect", (x, -3000.0, z), name=f"DragonFire_{slug}_{k}",
                             effect_type="FIRE", preview=False, silent=True,
                             fire_texture="assets/textures/effects/fire02.gif",
                             orb_texture="assets/textures/effects/orb01.gif",
                             custom_gif="", custom_loop=True, width=60.0, height=90.0,
                             intensity=1.0, colour=[255, 110, 25], lifetime=0.5,
                             light_enabled=(k % 4 == 0), light_radius=260.0,
                             light_intensity=2.5, light_colour=[255, 150, 60],
                             dragon_fire=True))
    for k, (dx, dz) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
        lx, lz = x + dx * r * CELL * 0.6, z + dz * r * CELL * 0.6
        things.append(_light(f"Light_lair_{k}", (lx, 260.0, lz), 900.0, (255, 120, 50), 2.2))


def _write_cave_maps(world, overworld_path, only=None):
    settings = next(t for t in world["things"] if t["type"] == "miniwindsettings")
    camera = next((t for t in world["things"] if t["type"] == "logic_command"), None)
    protos = {}
    for t in world["things"]:
        if t["type"] == "creature":
            protos.setdefault(t["properties"].get("display_name"), t)
    for k, (slug, name, monsters, count, loot) in enumerate(CAVES):
        if only and slug not in only:
            continue
        cave = build_cave_map(slug, name, monsters, count, loot, settings, camera,
                              protos, overworld_path, seed=101 + k * 17)
        path = os.path.join("maps", f"{slug}.json")
        with open(path, "w") as f:
            json.dump(cave, f, indent=1)
        print(f"{name} -> {path} ({len(cave['brushes'])} brushes, "
              f"{len(cave['things'])} things)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map", nargs="?", default=OVERWORLD)
    ap.add_argument("--count", type=int, default=len(CAVES))
    ap.add_argument("--maps-only", nargs="*", metavar="CAVE",
                    help="only rewrite the cave maps (all, or those named), "
                         "leaving the overworld and its cave mouths alone")
    ap.add_argument("--add", action="store_true",
                    help="add the caves the overworld does not have yet, leaving "
                         "the existing caves, their mouths and their maps alone")
    args = ap.parse_args()
    with open(args.map) as f:
        world = json.load(f)
    if args.maps_only is not None:
        _write_cave_maps(world, args.map, set(args.maps_only))
        return
    if args.add:
        _add_caves(world, args.map)
        return
    mouths = CaveMouths(world)
    mouths._remove_old()
    caves = CAVES[:args.count]
    for spacing in MOUTH_SPACINGS:
        spots = mouths.find_spots(len(caves), spacing=spacing)
        if len(spots) >= len(caves):
            break
    if len(spots) < len(caves):
        raise RuntimeError(f"only found {len(spots)} cave mouths for {len(caves)} caves")
    mouths.settle_primary(1)
    settings = next(t for t in world["things"] if t["type"] == "miniwindsettings")
    camera = next((t for t in world["things"] if t["type"] == "logic_command"), None)
    protos = {}
    for t in world["things"]:
        if t["type"] == "creature":
            protos.setdefault(t["properties"].get("display_name"), t)
    for k, ((slug, name, monsters, count, loot), spot) in enumerate(zip(caves, spots)):
        mouths.build(slug, name, spot, k + 1)
        cave = build_cave_map(slug, name, monsters, count, loot, settings, camera,
                              protos, args.map, seed=101 + k * 17)
        path = os.path.join("maps", f"{slug}.json")
        with open(path, "w") as f:
            json.dump(cave, f, indent=1)
        print(f"{name}: mouth at {spot[0]:.0f},{spot[2]:.0f},{spot[1]:.0f} -> {path} "
              f"({len(cave['brushes'])} brushes, {len(cave['things'])} things)")
    world.setdefault("_miniwind_world", {})["caves"] = [c[0] for c in caves[:len(spots)]]
    ew.dump(world, args.map)
    print(f"wrote {args.map}")


def _add_caves(world, path):
    """Give the overworld the caves in :data:`CAVES` it lacks, as the full
    run would have, without touching the ones it has (which may have been
    furnished by hand since)."""
    mouths = CaveMouths(world)
    have = mouths.existing()
    todo = [(k, c) for k, c in enumerate(CAVES) if c[0] not in have]
    if not todo:
        print("every cave is already there")
        return
    spots = []
    for spacing in MOUTH_SPACINGS:
        spots = mouths.find_spots(len(todo), avoid=list(have.values()), spacing=spacing)
        if len(spots) >= len(todo):
            break
    if len(spots) < len(todo):
        raise RuntimeError(f"only found {len(spots)} cave mouths for {len(todo)} caves")
    settings = next(t for t in world["things"] if t["type"] == "miniwindsettings")
    camera = next((t for t in world["things"] if t["type"] == "logic_command"), None)
    protos = {}
    for t in world["things"]:
        if t["type"] == "creature":
            protos.setdefault(t["properties"].get("display_name"), t)
    added = []
    for (k, (slug, name, monsters, count, loot)), spot in zip(todo, spots):
        mouths.build(slug, name, spot, k + 1)
        cave = build_cave_map(slug, name, monsters, count, loot, settings, camera,
                              protos, path, seed=101 + k * 17)
        out = os.path.join("maps", f"{slug}.json")
        with open(out, "w") as f:
            json.dump(cave, f, indent=1)
        added.append(slug)
        print(f"{name}: mouth at {spot[0]:.0f},{spot[2]:.0f},{spot[1]:.0f} -> {out} "
              f"({len(cave['brushes'])} brushes, {len(cave['things'])} things)")
    record = world.setdefault("_miniwind_world", {})
    record["caves"] = sorted(set(record.get("caves") or []) | set(have) | set(added))
    ew.dump(world, path)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
