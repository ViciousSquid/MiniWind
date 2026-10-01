"""
Fill the expanded world's open land with places to find.

``expand_world`` made the Vale huge but left most of it empty: a few dozen
major places in an 82 000-unit square. This pass keeps those major landmarks
but also builds a much denser layer of small countryside content between them:
cottages, small farms, pastures, roadside stops, minor ruins and shrines. The
result should read as a lived-in countryside rather than a handful of isolated
dots:

* **hamlets** -- a handful of cottages round a well, a market stall, a few
  folk who live and work there, sheep and hens;
* **farmsteads** -- a farmhouse and barn, a fenced paddock of cows or sheep,
  a farmer and a farmhand;
* **a wayside inn** -- an innkeeper who sells food and drink;
* **ruins and barrows** -- broken walls, the dead that guard them, a chest;
* **lairs** -- greenskin warrens, spider nests, a shroomling dell, brigand
  camps, each with its spoils;
* **shrines** -- standing stones and a lit altar.

Buildings are the map's own top-down house art on flat-topped brushes, each
seated on ground levelled under it (a sculpt, feathered into the
surroundings). People and creatures are copies of the map's own (a farmhand,
a merchant, a sheep, a skeleton), renamed, re-homed and given new ids. Every
place has a location marker, so it is named on discovery and on the map.

Run once on an expanded map (it refuses to run twice):

    python -m game.tools.populate_world [MAP] [--preview out.png]
"""

from __future__ import annotations
import argparse
import copy
import glob
import math
import os

import numpy as np

from .expand_world import (MAP, Expander, _heights, _load_heightmap, _props,
                           _smoothstep, _terrain, _uid, dump, preview)

#: (place name, kind), nearest first. Placed on open lowland, apart from
#: everything already there and from each other.
SITES = (
    ("Ashby", "hamlet"), ("Hayward's Farm", "farm"), ("The Wanderer's Rest", "inn"),
    ("Cairnmoor Barrow", "barrow"), ("Thornfield", "hamlet"), ("Coldharbour Farm", "farm"),
    ("Rotfang Warren", "greenskins"), ("Shrine of the Wayfarer", "shrine"),
    ("Kettlewick", "hamlet"), ("Silkhollow", "spiders"), ("Pennick Farm", "farm"),
    ("The Drowned Chapel", "ruin"), ("Cutthroat Ridge", "brigands"),
    ("Brackenford", "hamlet"), ("Mushroom Dell", "shrooms"), ("Marlow Steading", "farm"),
    ("Saint Aldric's Ruin", "ruin"), ("Moonwell", "shrine"), ("Elderbrook", "hamlet"),
    ("Snaggletooth Camp", "greenskins"), ("Gallows Crypt", "barrow"),
    ("Furrow End", "farm"), ("Raven's Roost", "brigands"), ("Wyndham Cross", "hamlet"),
    ("Webfall Hollow", "spiders"), ("The Pilgrim's Lantern", "inn"),
    ("Old Hob's Ruin", "ruin"), ("Greenmantle Shrine", "shrine"),
)

#: How far from the centre each kind may be: homes nearer, danger further.
REACH = {"hamlet": (5000, 26000), "farm": (4500, 24000), "inn": (6000, 22000),
         "shrine": (7000, 32000)}
DANGER_REACH = (9000, 33000)

#: Names for the folk who live in the new places.
FOLK = ("Aldous", "Berta", "Cedric", "Dorcas", "Edwin", "Freya", "Godric", "Hilda",
        "Ivo", "Joan", "Kenric", "Leofa", "Maud", "Nell", "Osric", "Prue", "Quill",
        "Rowan", "Sabine", "Tamsin", "Ulric", "Wynn", "Yarrow", "Agnes", "Bertram",
        "Cuthbert", "Elsie", "Fulk", "Gwen", "Hamon", "Isolde", "Jory", "Kit", "Lettice",
        "Merrick", "Odo", "Piers", "Rosamund", "Sim", "Tobias", "Wat", "Wilmot")

HOUSES = (("house01.png", 390, 260), ("house04.png", 340, 292), ("house05.png", 400, 200),
          ("house06.png", 300, 225), ("house01.png", 330, 220), ("house06.png", 340, 255))
STALLS = (("market01.png", 200, 200), ("market03.png", 200, 200), ("shop01.png", 180, 180),
          ("market02.png", 190, 138))

# Secondary density is deliberately separate from SITES. Major locations remain
# recognisable landmarks; these smaller locations make the intervening country
# worth walking through without turning the whole map into a town.
SECONDARY_TARGET = 120
SECONDARY_MIN_GAP = 1250.0

SECONDARY_PREFIXES = (
    "Ash", "Alder", "Barley", "Black", "Briar", "Brook", "Cinder", "Cold",
    "Copper", "Crow", "Elm", "Fox", "Gorse", "Green", "Hare", "Hazel",
    "Hollow", "Moor", "Oak", "Old", "Raven", "Red", "River", "Rowan",
    "Silver", "Stone", "Thorn", "Vale", "West", "Willow",
)
SECONDARY_SUFFIXES = (
    "Cottage", "Croft", "End", "Fold", "Field", "Grove", "Hold", "Mead",
    "Rest", "Run", "Side", "Stead", "Yard", "Watch", "Cross", "Bank",
)

def _slug(text):
    return "".join(c.lower() if c.isalnum() else "_" for c in text).strip("_")


class Populator(Expander):
    """Adds :data:`SITES` to an expanded world, reusing the expander's terrain
    and placement helpers."""

    def __init__(self, world, seed=31, report=print):
        self.world = world
        self.report = report
        self.rng = np.random.default_rng(seed)
        td = world["terrain_data"]
        self.heightmap = _load_heightmap(td)
        self.res = float(td.get("sculpt_grid_resolution", 16.0))
        self.sculpt = {(int(a), int(b)): float(v) for a, b, v in td.get("sculpt_offsets", ())}
        self._stored_sculpt = dict(self.sculpt)
        self.new_terrain = _terrain(td, heightmap=self.heightmap)
        self.new_base = _terrain(td, heightmap=self.heightmap, sculpt=False)
        (lo, hi), _ = self.new_terrain.get_terrain_bounds()
        self.bounds = (lo, hi)
        things = world["things"]
        self._protos = {
            "farmhand": self._find(things, "npc", name="Pell"),
            "merchant": self._find(things, "npc", npc_role="merchant", merchant=True),
        }
        for label in ("Sheep", "Cow", "Hen", "Skeleton", "Skeleton Archer", "Wraith",
                      "Greenskin", "Giant Spider", "Shroomling", "Bandit", "Bandit Archer"):
            self._protos[label] = self._find(things, "creature", display_name=label)
        self._heads = sorted(os.path.splitext(os.path.basename(p))[0]
                             for p in glob.glob(os.path.join("assets", "sprites", "heads", "head*.png")))
        self._folk = list(FOLK)
        self.rng.shuffle(self._folk)
        self.added = []

    @staticmethod
    def _find(things, ttype, **want):
        for t in things:
            if t.get("type") != ttype:
                continue
            p = _props(t)
            if all(p.get(k) == v for k, v in want.items()):
                return t
        return None

    # -- ground ------------------------------------------------------------
    def _level(self, x, z, half_w, half_d, feather=112.0):
        """Level the ground under a footprint to its median height, feathered
        out over *feather* units. Returns that height."""
        res = self.res
        gxs = np.arange(int((x - half_w - feather) // res), int((x + half_w + feather) // res) + 2)
        gzs = np.arange(int((z - half_d - feather) // res), int((z + half_d + feather) // res) + 2)
        GX, GZ = np.meshgrid(gxs, gzs, indexing="ij")
        WX, WZ = GX * res, GZ * res
        cur = self._grid_heights(GX, GZ).reshape(GX.shape)
        out = np.hypot(np.maximum(np.abs(WX - x) - half_w, 0.0),
                       np.maximum(np.abs(WZ - z) - half_d, 0.0))
        inside = out <= 0.0
        g = float(np.median(cur[inside])) if inside.any() else float(np.median(cur))
        w = 1.0 - _smoothstep(0.0, feather, out)
        delta = (g - cur) * w
        for a, b, d in zip(GX.ravel().tolist(), GZ.ravel().tolist(), delta.ravel().tolist()):
            if abs(d) >= 0.25:
                self.sculpt[(a, b)] = self.sculpt.get((a, b), 0.0) + d
        return g

    def _ground_now(self, x, z):
        """Ground height including sculpting not yet stored."""
        gx, gz = int(round(x / self.res)), int(round(z / self.res))
        return float(self._grid_heights([gx], [gz])[0])

    # -- pieces ------------------------------------------------------------
    def _house(self, x, z, art=None):
        tex, w, d = art or HOUSES[int(self.rng.integers(len(HOUSES)))]
        g = self._level(x, z, w / 2.0 + 24, d / 2.0 + 24)
        self._brush((x, 0, z), (w, 248.0, d), self._textured("nodraw.jpg", tex), ground=g)
        return g

    def _stall(self, x, z):
        tex, w, d = STALLS[int(self.rng.integers(len(STALLS)))]
        g = self._level(x, z, w / 2.0 + 16, d / 2.0 + 16)
        self._brush((x, 0, z), (w, 88.0, d), self._textured("nodraw.jpg", tex), ground=g)

    def _well(self, x, z):
        g = self._level(x, z, 70, 70)
        stone = self._textured("Stone_09-512x512.png")
        for dx, dz, sx, sz in ((0, -48, 112, 16), (0, 48, 112, 16), (-48, 0, 16, 112), (48, 0, 16, 112)):
            self._brush((x + dx, 0, z + dz), (sx, 56.0, sz), stone, ground=g)
        self._brush((x, 0, z), (80.0, 4.0, 80.0), self._textured("nodraw.jpg"), ground=g - 2.0,
                    sink=0.0, **self._water_props())

    def _fence(self, x, z, half_w, half_d, gap=120.0):
        """A rectangular paddock fence with a gate gap on the south side."""
        fence = self._textured("nodraw.jpg", "Fence2.png")
        step = 160.0
        for side in ("n", "s", "e", "w"):
            horiz = side in ("n", "s")
            length = 2 * (half_w if horiz else half_d)
            n = max(1, int(math.ceil(length / step)))
            seg = length / n
            for k in range(n):
                t = -length / 2.0 + seg * (k + 0.5)
                if side == "s" and abs(t) < gap / 2.0:
                    continue
                if horiz:
                    px, pz = x + t, z + (-half_d if side == "n" else half_d)
                    size = (seg, 56.0, 16.0)
                else:
                    px, pz = x + (half_w if side == "e" else -half_w), z + t
                    size = (16.0, 56.0, seg)
                self._brush((px, 0, pz), size, fence, ground=self._ground_now(px, pz), sink=4.0)

    def _field(self, x, z, half_w, half_d):
        g = self._level(x, z, half_w, half_d, feather=96.0)
        self._brush((x, 0, z), (2 * half_w, 4.0, 2 * half_d),
                    self._textured("nodraw.jpg", "pixelated-ground-texture-stockcake.jpg"),
                    ground=g, sink=0.0)

    def _fire(self, x, z, name):
        g = self._ground_now(x, z)
        self._brush((x, 0, z), (110.0, 24.0, 90.0),
                    self._textured("Stone_09-512x512.png", "fire01.png"), ground=g)
        self.world["things"].append(self._light(f"Light_{_slug(name)}_fire", [x, g + 160.0, z],
                                                520.0, [255, 160, 90]))

    def _tent(self, x, z, kind=2):
        g = self._ground_now(x, z)
        self._brush((x, 0, z), (180.0, 126.0, 176.0),
                    self._textured("nodraw.jpg", f"canopy0{kind}.png"), ground=g)

    def _walls(self, x, z, size, ruined=True):
        """A broken square of walls (*ruined*: random heights, a gap or two)."""
        wall = self._textured("stone-wall-v0-63mmfjnritm81.png")
        g = self._level(x, z, size / 2.0 + 32, size / 2.0 + 32, feather=160.0)
        h = size / 2.0
        pieces = []
        for side in range(4):
            for k in range(3):
                t = -h + size * (k + 0.5) / 3.0
                if ruined and self.rng.random() < 0.3:
                    continue
                if side < 2:
                    pieces.append((x + t, z + (h if side else -h), size / 3.0, 32.0))
                else:
                    pieces.append((x + (h if side == 3 else -h), z + t, 32.0, size / 3.0))
        for px, pz, sx, sz in pieces:
            tall = float(self.rng.uniform(60.0, 280.0)) if ruined else 220.0
            self._brush((px, 0, pz), (sx, tall, sz), wall, ground=g)
        self._brush((x, 0, z), (size - 40.0, 4.0, size - 40.0),
                    self._textured("nodraw.jpg", "flagstone.jpg"), ground=g, sink=0.0)
        return g

    # -- life --------------------------------------------------------------
    def _clean(self, proto):
        t = copy.deepcopy(proto)
        p = _props(t)
        for k in [k for k in p if k.startswith("_")]:
            del p[k]
        return t, p

    def _creature(self, label, x, z, roam=True):
        proto = self._protos.get(label)
        if proto is None:
            return
        t, p = self._clean(proto)
        g = self._ground_now(x, z)
        t["pos"] = [round(x, 1), round(g + 48.0, 1), round(z, 1)]
        p.update({"id": _uid(), "home": list(t["pos"]),
                  "name": f"{p.get('name', label)}_{len(self.world['things'])}"})
        if roam and p.get("aggression") != "hostile":
            p["roam"] = True
        self.world["things"].append(t)

    def _herd(self, label, x, z, count, spread=220.0):
        for _ in range(count):
            self._creature(label, x + float(self.rng.normal(0, spread)),
                           z + float(self.rng.normal(0, spread)))

    def _work_marker(self, name, x, z, kind="work"):
        g = self._ground_now(x, z)
        self.world["things"].append({
            "type": "marker", "pos": [round(x, 1), round(g + 16.0, 1), round(z, 1)],
            "properties": {"type": "marker", "name": name, "id": _uid(), "marker_kind": kind,
                           "hidden_in_game": True},
            "io_connections": []})

    def _person(self, place, x, z, home, work, role="farmhand", line=None, title=None):
        proto = self._protos.get(role)
        if proto is None:
            return None
        t, p = self._clean(proto)
        name = self._folk.pop() if self._folk else f"Folk{len(self.world['things'])}"
        g = self._ground_now(x, z)
        t["pos"] = [round(x, 1), round(g + 48.0, 1), round(z, 1)]
        head = self._heads[int(self.rng.integers(len(self._heads)))] if self._heads else p.get("head")
        p.update({"id": _uid(), "name": f"{name}_{_slug(place)}",
                  "display_name": f"{name} of {place}" if not title else f"{name} the {title}",
                  "home": [round(home[0], 1), round(home[1], 1), round(home[2], 1)],
                  "work_location": work, "head": head,
                  "custom_idle": f"assets/sprites/heads/{head}.png",
                  "custom_shoot": f"assets/sprites/heads/{head}.png",
                  "quest_flags": {}, "relationships": {}})
        if line:
            p["dialogue"] = {"start": "greeting", "nodes": {"greeting": {
                "text": line, "responses": [{"text": "Farewell.", "goto": "END"}]}}}
        self.world["things"].append(t)
        return t

    # -- secondary countryside ---------------------------------------------
    def _secondary_name(self, kind, index):
        """Deterministic readable names for small, mostly unmarked sites."""
        a = SECONDARY_PREFIXES[index % len(SECONDARY_PREFIXES)]
        b = SECONDARY_SUFFIXES[(index * 7) % len(SECONDARY_SUFFIXES)]
        labels = {
            "cottage": "Cottage",
            "small_farm": "Farm",
            "wayside": "Wayside Camp",
            "pasture": "Pasture",
            "ruinlet": "Ruins",
            "shrinelet": "Shrine",
            "camp": "Camp",
        }
        return f"{a} {b} {labels.get(kind, kind.title())}"

    def cottage(self, name, x, z):
        """A small occupied home: enough geometry to read as habitation."""
        g = self._house(x, z)
        home = (x, g + 48.0, z + 150.0)
        if self.rng.random() < 0.75:
            self._field(x - 360.0, z + 260.0, 150.0, 190.0)
        if self.rng.random() < 0.65:
            self._fence(x + 250.0, z + 330.0, 190.0, 150.0, gap=100.0)
            self._herd("Hen", x + 250.0, z + 330.0, 2, 55.0)
        work = f"{_slug(name)}_home"
        self._work_marker(work, x - 300.0, z + 240.0)
        self._person(name, x, z + 210.0, home, work, title="Cottager")

    def small_farm(self, name, x, z):
        """A lighter farmstead used to fill the countryside without full town density."""
        g = self._house(x, z, ("house06.png", 340, 255))
        home = (x, g + 48.0, z + 130.0)
        if self.rng.random() < 0.8:
            self._field(x - 540.0, z + 40.0, 220.0, 280.0)
        if self.rng.random() < 0.85:
            self._fence(x + 300.0, z + 380.0, 250.0, 180.0, gap=120.0)
            self._herd("Cow" if self.rng.random() < 0.45 else "Sheep",
                       x + 300.0, z + 380.0, 3, 120.0)
        self._herd("Hen", x - 180.0, z + 220.0, 2, 60.0)
        work = f"{_slug(name)}_field"
        self._work_marker(work, x - 540.0, z + 40.0, kind="farm")
        self._person(name, x, z + 200.0, home, work, title="Farmer")

    def wayside(self, name, x, z):
        """A tiny roadside stop: shelter, provisions and a traveller."""
        self._tent(x, z, int(self.rng.integers(2, 4)))
        self._container(x - 130.0, z + 120.0, "barrel",
                        [("bread", 2), ("gold", int(self.rng.integers(2, 12)))])
        work = f"{_slug(name)}_camp"
        self._work_marker(work, x, z)
        self._person(name, x + 80.0, z - 130.0,
                     (x + 80.0, self._ground_now(x + 80.0, z - 130.0) + 48.0, z - 130.0),
                     work, title="Wayfarer")

    def pasture(self, name, x, z):
        """A visible working pasture with enough geometry to break up empty land."""
        hw = float(self.rng.uniform(260.0, 360.0))
        hd = float(self.rng.uniform(220.0, 320.0))
        self._fence(x, z, hw, hd, gap=140.0)
        self._herd("Cow" if self.rng.random() < 0.5 else "Sheep", x, z, 4, 150.0)
        self._herd("Hen", x - hw * 0.55, z - hd * 0.65, 2, 55.0)

    def ruinlet(self, name, x, z):
        """Small broken site: much lighter than a full ruin."""
        self._walls(x, z, float(self.rng.uniform(300.0, 440.0)))
        self._creature("Skeleton", x, z, roam=True)
        if self.rng.random() < 0.35:
            self._creature("Wraith", x + 90.0, z - 70.0)
        if self.rng.random() < 0.7:
            self._container(x + 80.0, z + 80.0, "chest",
                            [("gold", int(self.rng.integers(10, 45)))])

    def shrinelet(self, name, x, z):
        """A minor roadside shrine using the same stones as the major shrines."""
        stone = self._textured("Stone_09-512x512.png")
        g = self._level(x, z, 60.0, 60.0, feather=90.0)
        self._brush((x, 0, z), (100.0, 52.0, 80.0),
                    self._textured("Stone_09-512x512.png", "fire01.png"),
                    ground=g)
        for k in range(3):
            a = 2.0 * math.pi * k / 3.0
            self._brush((x + math.cos(a) * 180.0, 0, z + math.sin(a) * 180.0),
                        (40.0, float(self.rng.uniform(90.0, 160.0)), 40.0),
                        stone)

    def camp(self, name, x, z):
        """A small hostile camp for wilderness stretches."""
        self._tent(x - 130.0, z, int(self.rng.integers(2, 4)))
        self._fire(x + 100.0, z + 30.0, name)
        self._herd("Bandit", x, z, 2, 170.0)
        if self.rng.random() < 0.65:
            self._creature("Bandit Archer", x + 100.0, z - 80.0)
        self._container(x - 40.0, z + 170.0, "chest",
                        [("gold", int(self.rng.integers(8, 50)))])

    def build_secondary(self, kind, name, x, z):
        if kind == "cottage":
            self.cottage(name, x, z)
        elif kind == "small_farm":
            self.small_farm(name, x, z)
        elif kind == "wayside":
            self.wayside(name, x, z)
        elif kind == "pasture":
            self.pasture(name, x, z)
        elif kind == "ruinlet":
            self.ruinlet(name, x, z)
        elif kind == "shrinelet":
            self.shrinelet(name, x, z)
        elif kind == "camp":
            self.camp(name, x, z)

    # -- the sites ---------------------------------------------------------
    def hamlet(self, name, x, z):
        r = 560.0
        homes = []
        n = int(self.rng.integers(3, 6))
        for k in range(n):
            a = 2.0 * math.pi * k / n + float(self.rng.uniform(-0.25, 0.25))
            hx, hz = x + math.cos(a) * r, z + math.sin(a) * r
            g = self._house(hx, hz)
            # The door side faces the well.
            homes.append((hx - math.cos(a) * 170.0, g + 48.0, hz - math.sin(a) * 170.0))
        self._well(x, z)
        self._stall(x + 220.0, z - 160.0)
        work = f"{_slug(name)}_green"
        self._work_marker(work, x + 120.0, z + 120.0)
        lines = (f"Welcome to {name}. Quiet, most days. We like it that way.",
                 "Mind the well, the stones are slick.",
                 f"Travellers don't often come out to {name}. What brings you?",
                 "There's talk of something in the old ruins. Stay on the road.")
        for k, home in enumerate(homes[:3]):
            self._person(name, home[0], home[2], home, work, line=lines[k % len(lines)])
        self._herd("Hen", x - 160.0, z + 220.0, 3, 120.0)
        self._herd("Sheep", x + r + 420.0, z, 4, 180.0)
        self.world["things"].append(self._light(f"Light_{_slug(name)}", [x, self._ground_now(x, z) + 260.0, z],
                                                700.0, [255, 200, 140]))
        self._container(x - 260.0, z - 180.0, "barrel", [("bread", 3), ("gold", int(self.rng.integers(5, 25)))])
        self._marker(name, x, z, 1200.0)

    def farm(self, name, x, z):
        g = self._house(x, z, ("house05.png", 400, 200))
        home = (x, g + 48.0, z + 160.0)
        self._house(x + 560.0, z - 60.0, ("house06.png", 340, 255))        # the barn
        self._field(x - 760.0, z + 40.0, 280.0, 360.0)
        px, pz = x + 200.0, z + 700.0
        self._fence(px, pz, 420.0, 300.0)
        self._herd("Cow" if self.rng.random() < 0.5 else "Sheep", px, pz, 4, 140.0)
        self._herd("Hen", x - 200.0, z + 260.0, 2, 80.0)
        work = f"{_slug(name)}_field"
        self._work_marker(work, x - 760.0, z + 40.0, kind="farm")
        self._person(name, x, z + 220.0, home, work, title="Farmer",
                     line=f"This is {name}. The soil's thin but it's ours.")
        self._person(name, x - 600.0, z, home, work,
                     line="Plough, sow, reap, repeat. Don't let me keep you.")
        self._container(x + 560.0, z + 140.0, "barrel", [("milk", 2), ("egg", 4)])
        self._marker(name, x, z, 1000.0)

    def inn(self, name, x, z):
        g = self._house(x, z, ("house04.png", 420, 360))
        self._fire(x + 360.0, z + 240.0, name)
        self._stall(x - 360.0, z + 220.0)
        work = f"{_slug(name)}_bar"
        self._work_marker(work, x, z + 230.0)
        self._person(name, x, z + 260.0, (x, g + 48.0, z), work, role="merchant",
                     title="Innkeeper",
                     line=f"Welcome to {name}! Warm fire, cold ale, and no questions asked.")
        self._herd("Hen", x + 300.0, z - 300.0, 2, 80.0)
        self.world["things"].append(self._light(f"Light_{_slug(name)}", [x, g + 300.0, z],
                                                800.0, [255, 190, 120]))
        self._marker(name, x, z, 1000.0)

    def ruin(self, name, x, z):
        self._walls(x, z, float(self.rng.uniform(560.0, 760.0)))
        self._herd("Skeleton", x, z, 3, 160.0)
        self._creature("Skeleton Archer", x + 120.0, z - 120.0)
        if self.rng.random() < 0.5:
            self._creature("Wraith", x - 100.0, z + 60.0)
        self._container(x, z, "chest", [("gold", int(self.rng.integers(40, 120))),
                                        ("potion_heal", int(self.rng.integers(1, 3)))])
        self.world["things"].append(self._light(f"Light_{_slug(name)}", [x, self._ground_now(x, z) + 220.0, z],
                                                500.0, [150, 190, 255]))
        self._marker(name, x, z, 900.0)

    def barrow(self, name, x, z):
        stone = self._textured("Stone_09-512x512.png")
        g = self._level(x, z, 200.0, 140.0, feather=200.0)
        self._brush((x, 0, z), (360.0, 120.0, 220.0), stone, ground=g + 30.0)    # the mound's lid
        for k in range(6):
            a = 2.0 * math.pi * k / 6.0
            self._brush((x + math.cos(a) * 380.0, 0, z + math.sin(a) * 300.0),
                        (60.0, float(self.rng.uniform(120.0, 220.0)), 60.0), stone)
        self._herd("Skeleton", x, z + 260.0, 4, 200.0)
        self._creature("Wraith", x, z - 220.0)
        self._container(x + 240.0, z, "chest", [("gold", int(self.rng.integers(60, 160))),
                                                ("potion_heal", 2)])
        self._marker(name, x, z, 900.0)

    def lair(self, name, x, z, label, archer=None, count=4, tents=False, debris=True):
        if tents:
            self._tent(x + 240.0, z - 120.0, 2)
            self._tent(x - 220.0, z + 160.0, 3)
            self._fire(x, z, name)
        if debris:
            for _ in range(3):
                dx, dz = self.rng.normal(0, 260, 2)
                g = self._ground_now(x + dx, z + dz)
                self._brush((x + dx, 0, z + dz), (190.0, 2.0, 190.0),
                            self._textured("nodraw.jpg", "debris01.png"), ground=g + 2.0, sink=0.0)
        self._herd(label, x, z, count, 260.0)
        if archer:
            self._herd(archer, x, z, 2, 260.0)
        self._container(x + 100.0, z + 220.0, "chest", [("gold", int(self.rng.integers(30, 110)))])
        self._marker(name, x, z, 900.0)

    def shrine(self, name, x, z):
        stone = self._textured("Stone_09-512x512.png")
        g = self._level(x, z, 90.0, 90.0)
        self._brush((x, 0, z), (140.0, 70.0, 100.0), self._textured("Stone_09-512x512.png", "fire01.png"),
                    ground=g)
        for k in range(5):
            a = 2.0 * math.pi * k / 5.0
            self._brush((x + math.cos(a) * 300.0, 0, z + math.sin(a) * 300.0),
                        (60.0, float(self.rng.uniform(140.0, 240.0)), 60.0), stone)
        self.world["things"].append(self._light(f"Light_{_slug(name)}", [x, g + 220.0, z],
                                                650.0, [200, 220, 255]))
        self._container(x, z + 140.0, "chest", [("potion_heal", 2)])
        self._marker(name, x, z, 800.0)

    def build(self, kind, name, x, z):
        if kind == "hamlet":
            self.hamlet(name, x, z)
        elif kind == "farm":
            self.farm(name, x, z)
        elif kind == "inn":
            self.inn(name, x, z)
        elif kind == "ruin":
            self.ruin(name, x, z)
        elif kind == "barrow":
            self.barrow(name, x, z)
        elif kind == "greenskins":
            self.lair(name, x, z, "Greenskin", count=5, tents=True)
        elif kind == "spiders":
            self.lair(name, x, z, "Giant Spider", count=4)
        elif kind == "shrooms":
            self.lair(name, x, z, "Shroomling", count=5)
        elif kind == "brigands":
            self.lair(name, x, z, "Bandit", archer="Bandit Archer", count=3, tents=True,
                      debris=False)
        elif kind == "shrine":
            self.shrine(name, x, z)

    def run(self):
        major = []
        for name, kind in SITES:
            lo, hi = REACH.get(kind, DANGER_REACH)
            spots = self._open_spots(1, self.rng, lo, hi, 2600.0, 0.0)
            spots = [s for s in spots if all(math.hypot(s[0] - a, s[1] - b) >= 5200.0
                                             for a, b in major)]
            tries = 0
            while not spots and tries < 40:
                tries += 1
                spots = [s for s in self._open_spots(1, self.rng, lo, hi, 2600.0, 0.0)
                         if all(math.hypot(s[0] - a, s[1] - b) >= 4200.0
                                for a, b in major)]
            if not spots:
                self.report(f"no room for {name}")
                continue
            x, z = spots[0]
            self.build(kind, name, x, z)
            self._store_terrain()
            major.append((x, z))
            self.added.append((name, kind, round(x), round(z)))

        # The original pass stopped here, leaving huge stretches of empty
        # countryside. Add a second, deliberately lighter layer of content.
        # It is still generated once into the map; BigWorld remains responsible
        # for deciding what is relevant at runtime.
        if major:
            candidates = self._open_spots(
                max(SECONDARY_TARGET * 4, SECONDARY_TARGET + 40),
                self.rng, 0.0, 35000.0, 700.0, 0.0)
        else:
            candidates = []

        secondary = []
        for x, z in candidates:
            if len(secondary) >= SECONDARY_TARGET:
                break
            if not all(math.hypot(x - a, z - b) >= SECONDARY_MIN_GAP
                       for a, b in major + secondary):
                continue

            nearest = min(math.hypot(x - a, z - b) for a, b in major)
            roll = float(self.rng.random())

            if nearest < 6500.0:
                if roll < 0.46:
                    kind = "cottage"
                elif roll < 0.72:
                    kind = "small_farm"
                elif roll < 0.90:
                    kind = "pasture"
                else:
                    kind = "wayside"
            elif nearest < 13000.0:
                if roll < 0.28:
                    kind = "cottage"
                elif roll < 0.48:
                    kind = "small_farm"
                elif roll < 0.68:
                    kind = "pasture"
                elif roll < 0.84:
                    kind = "wayside"
                elif roll < 0.93:
                    kind = "shrinelet"
                else:
                    kind = "ruinlet"
            else:
                if roll < 0.28:
                    kind = "wayside"
                elif roll < 0.50:
                    kind = "pasture"
                elif roll < 0.70:
                    kind = "camp"
                elif roll < 0.86:
                    kind = "ruinlet"
                else:
                    kind = "shrinelet"

            name = self._secondary_name(kind, len(secondary))
            self.build_secondary(kind, name, x, z)
            secondary.append((x, z))

            # _ground_now() sees the accumulated sculpt immediately, but
            # periodically committing it keeps the serialized terrain state
            # coherent during a long generation pass.
            if len(secondary) % 8 == 0:
                self._store_terrain()

        if secondary:
            self._store_terrain()

        self.secondary_added = len(secondary)
        self.world.setdefault("_miniwind_world", {})["populated"] = True
        self.world["_miniwind_world"]["population_density"] = {
            "major_sites": len(major),
            "secondary_sites": len(secondary),
            "secondary_target": SECONDARY_TARGET,
        }
        self.report(f"added {len(secondary)} secondary countryside sites")
        return self.world



def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map", nargs="?", default=MAP)
    ap.add_argument("-o", "--out", help="write here instead of over the input")
    ap.add_argument("--preview", help="also write a top-down PNG of the result")
    ap.add_argument("--seed", type=int, default=31)
    ap.add_argument("--force", action="store_true", help="populate a populated map again")
    args = ap.parse_args()
    import json
    with open(args.map) as f:
        world = json.load(f)
    meta = world.get("_miniwind_world", {})
    if not meta.get("expanded"):
        raise SystemExit(f"{args.map} is not expanded; run game.tools.expand_world first")
    if meta.get("populated") and not args.force:
        raise SystemExit(f"{args.map} is already populated (use --force to do it again)")
    pop = Populator(world, seed=args.seed)
    pop.run()
    for name, kind, x, z in pop.added:
        print(f"  {kind:<10} {name:<24} {x:>7} {z:>7}")
    out = args.out or args.map
    dump(world, out)
    print(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB, "
          f"{len(pop.added)} major + {getattr(pop, 'secondary_added', 0)} secondary places, "
          f"{len(world['brushes'])} brushes, {len(world['things'])} things)")
    if args.preview:
        preview(world, args.preview)


if __name__ == "__main__":
    main()