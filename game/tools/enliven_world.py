"""
Give the Vale its geography: relief, biomes, forests and shrines.

Runs over the expanded world map (``maps/village_walled_source.json``) and:

* **Relief.** Rolling hills everywhere (stronger in some regions, gentle in
  others), long ridgelines, dunes and a few flat-topped mesas in the desert,
  all added to the heightmap. Every site keeps its ground: the relief fades
  to nothing within reach of any building, person or prop, so settlements sit
  in the valleys and the hills rise between them. Trees, creatures and
  anything else on changed ground are lifted with it.
* **Biomes**, painted into the terrain's biome map (engine/terrain_biomes.py):
  desert in the south-west corner fading through dry steppe into the meadows,
  snow on the Emberpeaks in the north-east and on every high summit, swamp
  around the lakes and tarns (an oasis in the desert), and wheat: patchwork
  fields around every farm and three great golden plains of them.
* **Forests.** Dense woods in broad patches and a great forest around
  Greywood, each biome with its own trees -- pines and snowy pines in the
  north-east, willows in the swamps, palms at desert water, dead trees and
  scrub on the desert's edge, broadleaf everywhere else. None on the wheat,
  the high mountains or anywhere near a site.
* **Shrines**, one per biome, each a named place.
* Turns grass on.

The map records the pass, so running it twice needs ``--force``.

Run from the repo root::

    python -m game.tools.enliven_world --preview world.png
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import os

import numpy as np

from engine import terrain_biomes as tb
from . import expand_world as ew

MAP = ew.MAP
SEED = 2026

#: The south-west / north-east diagonals (world z grows to the south).
SW = np.array((-1.0, 1.0)) / math.sqrt(2.0)
NE = np.array((1.0, -1.0)) / math.sqrt(2.0)
BIOME_SIZE = 1024

#: Farm-like places whose land is laid out in wheat fields.
FARM_WORDS = ("farm", "steading", "mill", "croft", "cross", "brook", "field",
              "rest", "barrow", "oakridge", "thornfield", "ashby", "kettlewick")

#: (name, biome) for the shrines.
SHRINES = (("Shrine of the Green Lady", "forest"), ("Shrine of the Burning Sun", "desert"),
           ("Shrine of the White Stag", "snow"), ("Shrine of the Last Sheaf", "wheat"),
           ("Shrine of the Drowned", "swamp"), ("Shrine of the Long Road", "meadow"))

TREES = {
    "broadleaf": ("tree01.png", "tree02.png", "tree03.png", "tree04.png",
                  "tree05.png", "tree06.png", "tree07.png", "trees0.png"),
    "pine": ("pine01.png", "pine02.png"),
    "snowpine": ("snowpine01.png", "snowpine02.png"),
    "willow": ("willow01.png", "trees0.png"),
    "palm": ("palm01.png",),
    "dry": ("deadtree01.png", "scrub01.png", "scrub02.png"),
}


def _noise(X, Z, scale, seed):
    return ew._value_noise(X, Z, scale, seed)


def _fbm(X, Z, scale, seed, octaves=3):
    total, amp, norm = 0.0, 1.0, 0.0
    for o in range(octaves):
        total = total + _noise(X, Z, scale / (2.07 ** o), seed + o * 31) * amp
        norm += amp
        amp *= 0.5
    return total / norm


def _ss(e0, e1, x):
    return ew._smoothstep(e0, e1, x)


class Enliven:
    def __init__(self, world, report=print):
        self.world = world
        self.report = report
        self.td = world["terrain_data"]
        self.hm = ew._load_heightmap(self.td).astype(np.float32)
        self.terrain = ew._terrain(self.td, heightmap=self.hm)
        (self.lo, self.hi), _ = self.terrain.get_terrain_bounds()
        self.rng = np.random.default_rng(SEED)
        self.content = self._content_points()
        self.water = [b for b in world["brushes"] if b.get("water_plane")
                      and max(b["size"][0], b["size"][2]) >= 200.0]
        self._plan_fields()

    # -- what is where -----------------------------------------------------
    def _content_points(self):
        pts = [(b["pos"][0], b["pos"][2]) for b in self.world["brushes"]
               if not ew.Expander._is_tree(b)]
        pts += [(t["pos"][0], t["pos"][2]) for t in self.world["things"]
                if t["type"] not in ("creature", "creaturespawn")
                and str(t["type"]).lower() not in ew._GLOBAL_THINGS]
        return np.array(pts, np.float32)

    def _clearance(self, n, cell, reach):
        """Distance from every pixel of an n x n grid over the world to the
        nearest content point (up to *reach*)."""
        mask = np.zeros((n, n), bool)
        c = np.clip(np.round((self.content[:, 0] - self.lo) / cell).astype(int), 0, n - 1)
        r = np.clip(np.round((self.content[:, 1] - self.lo) / cell).astype(int), 0, n - 1)
        mask[r, c] = True
        return ew._dilate_distance(mask, cell, int(reach / cell) + 2)

    def _near_content(self, x, z, radius):
        d = np.hypot(self.content[:, 0] - x, self.content[:, 1] - z)
        return bool(np.any(d < radius))

    def markers(self):
        for t in self.world["things"]:
            p = t.get("properties", {})
            if t["type"] == "marker" and p.get("marker_kind") == "location":
                yield p.get("place_name") or p.get("name") or "", t["pos"][0], t["pos"][2]

    # -- biome fields --------------------------------------------------------
    def mountain(self, X, Z, hm=None):
        """The heightmap's lift (mountains, relief) at points."""
        t = self.terrain if hm is None else ew._terrain(self.td, heightmap=hm, sculpt=False)
        x = np.asarray(X, np.float32).ravel()
        z = np.asarray(Z, np.float32).ravel()
        return t._sample_heightmap_batch(x, z, np.zeros(len(x), np.float32)).reshape(np.shape(X))

    def desert(self, X, Z):
        u = X * SW[0] + Z * SW[1]
        warp = _noise(X, Z, 7000.0, SEED + 1) * 4500.0 + _noise(X, Z, 2300.0, SEED + 2) * 1400.0
        return _ss(16500.0, 24500.0, u + warp)

    def snow(self, X, Z, M):
        v = X * NE[0] + Z * NE[1]
        warp = _noise(X, Z, 6000.0, SEED + 3) * 3500.0
        ne = _ss(14000.0, 22000.0, v + warp)
        corner = _ss(26000.0, 32000.0, v + warp)
        return np.clip(np.maximum.reduce([ne * _ss(220.0, 600.0, M), corner,
                                          _ss(1650.0, 2250.0, M)]), 0.0, 1.0)

    def swamp(self, X, Z):
        out = np.zeros(np.shape(X), np.float32)
        for b in self.water:
            cx, cz = b["pos"][0], b["pos"][2]
            hx, hz = b["size"][0] / 2.0, b["size"][2] / 2.0
            dx = np.maximum(np.abs(X - cx) - hx, 0.0)
            dz = np.maximum(np.abs(Z - cz) - hz, 0.0)
            d = np.hypot(dx, dz)
            reach = 3000.0 + 1.1 * max(hx, hz)
            out = np.maximum(out, _ss(reach, reach * 0.35, d))
        ragged = 0.55 + 0.45 * _ss(-0.3, 0.3, _fbm(X, Z, 2200.0, SEED + 4))
        return out * ragged

    def _plan_fields(self):
        """Wheat fields: rectangles ``(cx, cz, half_w, half_h, angle)``."""
        rng = self.rng
        fields = []
        for name, x, z in self.markers():
            low = name.lower()
            if not any(w in low for w in FARM_WORDS):
                continue
            base = rng.uniform(0, math.pi)
            for _ in range(int(rng.integers(5, 10))):
                a = rng.uniform(0, 2 * math.pi)
                r = rng.uniform(700.0, 2600.0)
                cx, cz = x + math.cos(a) * r, z + math.sin(a) * r
                if self._near_content(cx, cz, 350.0):
                    continue
                fields.append((cx, cz, rng.uniform(320, 760), rng.uniform(200, 460),
                               base + rng.uniform(-0.12, 0.12)))
        # The great plains: patchworks of fields far from anything.
        self.plains = []
        tries = 0
        while len(self.plains) < 3 and tries < 4000:
            tries += 1
            x, z = rng.uniform(-26000, 26000, 2)
            if self._near_content(x, z, 3600.0):
                continue
            if any(math.hypot(x - px, z - pz) < 14000 for px, pz in self.plains):
                continue
            X, Z = np.array([x]), np.array([z])
            if self.desert(X, Z)[0] > 0.05 or self.snow(X, Z, self.mountain(X, Z))[0] > 0.05:
                continue
            if self.mountain(X, Z)[0] > 120.0:
                continue
            self.plains.append((x, z))
            ang = rng.uniform(0, math.pi)
            ca, sa = math.cos(ang), math.sin(ang)
            for i in range(-3, 4):
                for j in range(-3, 4):
                    if rng.random() < 0.12:
                        continue          # a fallow patch
                    w, h = rng.uniform(560, 720), rng.uniform(340, 460)
                    lx, lz = i * 1560.0, j * 1000.0
                    cx, cz = x + lx * ca - lz * sa, z + lx * sa + lz * ca
                    if self._near_content(cx, cz, 400.0):
                        continue
                    fields.append((cx, cz, w, h, ang + rng.uniform(-0.04, 0.04)))
        self.fields = fields
        self.report(f"{len(fields)} wheat fields ({len(self.plains)} great plains)")

    def wheat(self, X, Z, cell):
        out = np.zeros(np.shape(X), np.float32)
        for cx, cz, hw, hh, a in self.fields:
            ca, sa = math.cos(a), math.sin(a)
            dx, dz = X - cx, Z - cz
            lx = dx * ca + dz * sa
            lz = -dx * sa + dz * ca
            inside = (np.clip((hw - np.abs(lx)) / cell + 0.5, 0, 1)
                      * np.clip((hh - np.abs(lz)) / cell + 0.5, 0, 1))
            out = np.maximum(out, inside)
        return out

    # -- relief --------------------------------------------------------------
    def build_relief(self):
        n = self.hm.shape[0]
        cell = (self.hi - self.lo) / (n - 1)
        axis = self.lo + np.arange(n, dtype=np.float32) * cell
        X, Z = np.meshgrid(axis, axis)
        M = (self.hm - 0.5) * float(self.td.get("heightmap_strength", ew.HM_STRENGTH))
        desert = self.desert(X, Z)
        swamp = self.swamp(X, Z)
        wheat = self.wheat(X, Z, cell)
        regional = _noise(X, Z, 17000.0, SEED + 10) * 0.5 + 0.5
        hills01 = _fbm(X, Z, 7200.0, SEED + 11) * 0.5 + 0.5
        amp = 120.0 + 560.0 * _ss(0.3, 0.8, regional)
        R = hills01 ** 1.5 * amp
        # Ridgelines in their own regions.
        ridge = ew._ridged(X, Z, 6400.0, SEED + 12, 3)
        R += ridge ** 3 * 760.0 * _ss(0.5, 0.72, _noise(X, Z, 15000.0, SEED + 13) * 0.5 + 0.5)
        # Desert dunes, long and parallel, warped.
        a = 0.6
        phase = (X * math.cos(a) + Z * math.sin(a)) / 1100.0 * 2 * math.pi \
            + _noise(X, Z, 3400.0, SEED + 14) * 3.0
        R += (0.5 + 0.5 * np.sin(phase)) ** 3 * 170.0 * desert
        # Mesas: flat tops, steep sides.
        self.mesas = []
        for _ in range(400):
            if len(self.mesas) >= 4:
                break
            x, z = self.rng.uniform(-36000, -8000), self.rng.uniform(8000, 36000)
            if self.desert(np.array([x]), np.array([z]))[0] < 0.75 or self._near_content(x, z, 3400):
                continue
            if any(math.hypot(x - mx, z - mz) < 6000 for mx, mz, _r in self.mesas):
                continue
            self.mesas.append((x, z, float(self.rng.uniform(900, 1600))))
        for mx, mz, r in self.mesas:
            d = np.hypot(X - mx, Z - mz) * (1.0 + 0.18 * _noise(X, Z, 700.0, SEED + 15))
            R = np.maximum(R, _ss(r + 160.0, r - 160.0, d) * 420.0)
        R *= (1.0 - 0.8 * wheat) * (1.0 - 0.9 * swamp)
        # Nothing moves under a site: the relief fades out near content.
        clear = self._clearance(n, cell, 3000.0)
        R *= _ss(700.0, 2700.0, clear)
        self.old_terrain = self.terrain
        self.hm = (self.hm + R / float(self.td.get("heightmap_strength", ew.HM_STRENGTH))).astype(np.float32)
        self._store_heightmap()
        self.report(f"relief: up to {R.max():.0f} units, mean {R.mean():.0f}; "
                    f"{len(self.mesas)} mesas")

    def _store_heightmap(self):
        buf = io.BytesIO()
        np.save(buf, self.hm)
        self.td["heightmap_blob"] = base64.b64encode(buf.getvalue()).decode("ascii")
        self.terrain = ew._terrain(self.td, heightmap=self.hm)

    def lift_objects(self):
        """Everything stands on the ground it stood on, raised or lowered with it."""
        objs = [b for b in self.world["brushes"]] + [
            t for t in self.world["things"] if str(t["type"]).lower() not in ew._GLOBAL_THINGS]
        xs = np.array([o["pos"][0] for o in objs], np.float32)
        zs = np.array([o["pos"][2] for o in objs], np.float32)
        old = ew._heights(self.old_terrain, xs, zs)
        new = ew._heights(self.terrain, xs, zs)
        moved = 0
        for o, d in zip(objs, (new - old).tolist()):
            if abs(d) > 1.0:
                o["pos"] = [o["pos"][0], round(o["pos"][1] + d, 1), o["pos"][2]]
                moved += 1
        self.report(f"{moved} objects lifted with the ground")

    # -- biome map -------------------------------------------------------------
    def build_biomes(self):
        n = BIOME_SIZE
        cell = (self.hi - self.lo) / n
        axis = self.lo + (np.arange(n, dtype=np.float32) + 0.5) * cell
        X, Z = np.meshgrid(axis, axis)
        M = self.mountain(X, Z)
        snow = self.snow(X, Z, M)
        desert = self.desert(X, Z) * (1.0 - snow)
        swamp = self.swamp(X, Z) * (1.0 - snow) * (1.0 - 0.75 * desert)
        clear = self._clearance(n, cell, 600.0)
        wheat = (self.wheat(X, Z, cell) * (1.0 - desert) * (1.0 - snow) * (1.0 - swamp)
                 * _ss(140.0, 300.0, clear) * _ss(260.0, 120.0, M))
        self.biome = np.stack([desert, snow, swamp, wheat], -1)
        self.biome_axis = (self.lo, cell)
        img = np.clip(self.biome * 255.0 + 0.5, 0, 255).astype(np.uint8)
        self.td["biome_map_blob"] = tb.encode(img)
        self.td["grass_enabled"] = True
        self.td["grass_density"] = 0.02
        cover = (self.biome > 0.5).mean(axis=(0, 1)) * 100.0
        self.report("biomes: " + ", ".join(f"{name} {c:.1f}%" for name, c in zip(tb.NAMES, cover)))

    def biome_at(self, xs, zs):
        lo, cell = self.biome_axis
        n = BIOME_SIZE
        c = np.clip(((np.asarray(xs) - lo) / cell).astype(int), 0, n - 1)
        r = np.clip(((np.asarray(zs) - lo) / cell).astype(int), 0, n - 1)
        return self.biome[r, c]

    # -- forests ---------------------------------------------------------------
    def plant_forests(self, spacing=200.0, limit=11000):
        rng = np.random.default_rng(SEED + 20)
        lo, hi = self.lo + 2500.0, self.hi - 2500.0
        axis = np.arange(lo, hi, spacing, dtype=np.float32)
        X, Z = np.meshgrid(axis, axis)
        X = (X + rng.uniform(-0.45, 0.45, X.shape) * spacing).ravel()
        Z = (Z + rng.uniform(-0.45, 0.45, Z.shape) * spacing).ravel()
        patches = _ss(0.12, 0.34, _fbm(X, Z, 6200.0, SEED + 21))
        great = np.zeros_like(X)
        for name, x, z in self.markers():
            if name == "Greywood":
                great = _ss(9500.0, 4200.0, np.hypot(X - x, Z - z))
        density = np.maximum(patches, great)
        b = self.biome_at(X, Z)
        desert, snow, swamp, wheat = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
        M = self.mountain(X, Z)
        v = X * NE[0] + Z * NE[1]
        density = density * (1.0 - _ss(0.05, 0.25, wheat))
        density = density * _ss(1000.0, 600.0, M)
        density = density * (1.0 - 0.75 * _ss(0.4, 0.9, desert))
        density = np.maximum(density, swamp * 0.45)
        # Oasis palms: desert ground near water.
        oasis = np.zeros_like(X)
        for w in self.water:
            d = np.hypot(X - w["pos"][0], Z - w["pos"][2]) - max(w["size"][0], w["size"][2]) / 2
            oasis = np.maximum(oasis, _ss(1300.0, 250.0, d) * desert)
        density = np.maximum(density, oasis * 0.7)
        keep = rng.random(len(X)) < density
        # Away from every site.
        n = 512
        cell = (self.hi - self.lo) / (n - 1)
        clear = self._clearance(n, cell, 900.0)
        c = np.clip(np.round((X - self.lo) / cell).astype(int), 0, n - 1)
        r = np.clip(np.round((Z - self.lo) / cell).astype(int), 0, n - 1)
        keep &= clear[r, c] > 520.0
        idx = np.flatnonzero(keep)
        if len(idx) > limit:
            idx = np.sort(rng.choice(idx, limit, replace=False))
        X, Z = X[idx], Z[idx]
        desert, snow, swamp, M, v, oasis = desert[idx], snow[idx], swamp[idx], M[idx], v[idx], oasis[idx]
        ground = ew._heights(self.terrain, X, Z)
        proto = next(b for b in self.world["brushes"] if ew.Expander._is_tree(b))
        counts = {}
        for k in range(len(X)):
            if oasis[k] > 0.3:
                kind = "palm"
            elif desert[k] > 0.3:
                kind = "dry"
            elif snow[k] > 0.45:
                kind = "snowpine"
            elif snow[k] > 0.08 or M[k] > 380.0 or (v[k] > 9000 and rng.random() < 0.6):
                kind = "pine"
            elif swamp[k] > 0.35:
                kind = "willow"
            else:
                kind = "broadleaf"
            names = TREES[kind]
            tex = names[int(rng.integers(len(names)))]
            s = float(rng.uniform(150.0, 240.0)) * (0.7 if kind == "dry" else 1.0)
            b = {"pos": [round(float(X[k]), 1), round(float(ground[k]) + 190.0, 1),
                         round(float(Z[k]), 1)],
                 "size": [round(s, 1), 16.0, round(s, 1)],
                 "textures": {**{f: "nodraw.jpg" for f in ("north", "south", "east", "west", "down")},
                              "top": tex},
                 "uv_scale": dict(proto.get("uv_scale", {})), "id": ew._uid()}
            self.world["brushes"].append(b)
            counts[kind] = counts.get(kind, 0) + 1
        self.report(f"{len(X)} trees planted: " +
                    ", ".join(f"{v} {k}" for k, v in sorted(counts.items())))

    # -- shrines ---------------------------------------------------------------
    def build_shrines(self):
        rng = np.random.default_rng(SEED + 30)
        stone = ew.Expander._textured("Stone_09-512x512.png")
        flag = ew.Expander._textured("nodraw.jpg", "flagstone.jpg")
        fire = ew.Expander._textured("Stone_09-512x512.png", "fire01.png")
        placed = []
        for name, biome in SHRINES:
            spot = None
            for _ in range(6000):
                x, z = rng.uniform(self.lo + 6000, self.hi - 6000, 2)
                if self._near_content(x, z, 2500.0):
                    continue
                if any(math.hypot(x - a, z - b) < 7000 for a, b in placed):
                    continue
                w = self.biome_at([x], [z])[0]
                M = self.mountain(np.array([x]), np.array([z]))[0]
                if M > 500.0:
                    continue
                want = {"desert": w[0] > 0.7, "snow": w[1] > 0.6, "swamp": w[2] > 0.5,
                        "wheat": 0.0 < w[3] < 0.2 and any(
                            math.hypot(x - f[0], z - f[1]) < 1600 for f in self.fields),
                        "forest": max(w) < 0.1 and self._tree_count_near(x, z, 900.0) > 6,
                        "meadow": max(w) < 0.1}[biome]
                if want:
                    spot = (float(x), float(z))
                    break
            if spot is None:
                self.report(f"no spot for {name}")
                continue
            x, z = spot
            placed.append(spot)
            self._clear_trees(x, z, 420.0)
            g = float(ew._heights(self.terrain, [x], [z])[0])
            brushes = self.world["brushes"]

            def brush(dx, dz, size, tex, base=g, sink=8.0):
                brushes.append({"pos": [round(x + dx, 1), round(base + size[1] / 2 - sink, 1),
                                        round(z + dz, 1)],
                                "size": [float(v) for v in size], "textures": dict(tex),
                                "id": ew._uid()})
            brush(0, 0, (380.0, 4.0, 380.0), flag, sink=0.0)
            brush(0, 0, (120.0, 60.0, 120.0), stone)
            brush(0, 0, (54.0, 200.0, 54.0), stone, base=g + 52.0)
            for k in range(4):
                a = math.pi / 4 + k * math.pi / 2
                brush(math.cos(a) * 165, math.sin(a) * 165, (40.0, 120.0, 40.0), stone)
            brush(0, 120, (60.0, 30.0, 60.0), fire)
            self.world["things"].append(ew.Expander._light(
                f"Light_{name.replace(' ', '')}", [x, g + 230.0, z], 560.0,
                {"desert": [255, 190, 90], "snow": [190, 220, 255], "swamp": [140, 255, 180]}
                .get(biome, [255, 170, 110])))
            slug = "loc_" + "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
            self.world["things"].append({
                "type": "marker", "pos": [round(x, 1), round(g + 72.0, 1), round(z, 1)],
                "properties": {"type": "marker", "name": slug, "id": ew._uid(),
                               "marker_kind": "location", "place_name": name,
                               "discover_radius": 700.0},
                "io_connections": []})
        self.report(f"{len(placed)} shrines")

    def _tree_count_near(self, x, z, r):
        n = 0
        for b in self.world["brushes"]:
            if abs(b["pos"][0] - x) < r and abs(b["pos"][2] - z) < r and ew.Expander._is_tree(b):
                n += 1
        return n

    def _clear_trees(self, x, z, r):
        self.world["brushes"] = [b for b in self.world["brushes"] if not (
            ew.Expander._is_tree(b) and math.hypot(b["pos"][0] - x, b["pos"][2] - z) < r)]

    def run(self):
        self.build_relief()
        self.lift_objects()
        self.build_biomes()
        self.plant_forests()
        self.build_shrines()
        self.world.setdefault("_miniwind_world", {})["enlivened"] = True
        return self.world


_TREE_TOPS = ("tree", "pine", "snowpine", "palm", "deadtree", "scrub", "willow")


def _is_tree(b):
    top = str(b.get("textures", {}).get("top", ""))
    return top.startswith(_TREE_TOPS)


# Every tool that tells trees from buildings knows the new kinds too.
ew.Expander._is_tree = staticmethod(_is_tree)


def preview(world, path, size=1100):
    """A top-down picture: biome colours, hill shading, forests, water, places."""
    from PIL import Image, ImageDraw
    td = world["terrain_data"]
    hm = ew._load_heightmap(td)
    terrain = ew._terrain(td, heightmap=hm, sculpt=False)
    (lo, hi), _ = terrain.get_terrain_bounds()
    axis = np.linspace(lo, hi, size, dtype=np.float32)
    X, Z = np.meshgrid(axis, axis)
    H = ew._heights(terrain, X.ravel(), Z.ravel()).reshape(size, size)
    M = terrain._sample_heightmap_batch(X.ravel(), Z.ravel(),
                                        np.zeros(X.size, np.float32)).reshape(size, size)
    g = np.clip(M / 1800.0, 0, 1)[..., None]
    base = np.array((0.34, 0.50, 0.24)) * (1 - g) + np.array((0.55, 0.52, 0.47)) * g
    biome = tb.decode(td["biome_map_blob"]) if td.get("biome_map_blob") else None
    w = tb.sample(biome, ((lo, hi), (lo, hi)), X.ravel(), Z.ravel())
    gy, gx = np.gradient(H)
    slope = np.clip(np.hypot(gx, gy) / ((hi - lo) / size) , 0, 1).ravel()
    col = tb.blend_colors(base.reshape(-1, 3), w, slope * 0.6).reshape(size, size, 3)
    shade = np.clip(1.0 + (gx - gy) / ((hi - lo) / size) * 1.4, 0.55, 1.35)
    img = Image.fromarray(np.clip(col * shade[..., None] * 255, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)

    def px(x, z):
        return ((x - lo) / (hi - lo) * size, (z - lo) / (hi - lo) * size)
    tree_col = {"pine": (16, 60, 30), "snowpine": (40, 80, 60), "palm": (60, 140, 40),
                "deadtree": (110, 90, 70), "scrub": (120, 115, 60), "willow": (70, 90, 40)}
    for b in world["brushes"]:
        x, _, z = b["pos"]
        if b.get("water_plane"):
            a = px(x - b["size"][0] / 2, z - b["size"][2] / 2)
            c = px(x + b["size"][0] / 2, z + b["size"][2] / 2)
            d.rectangle([a, c], fill=(40, 90, 200))
        elif _is_tree(b):
            top = b["textures"]["top"]
            c = next((v for k, v in tree_col.items() if top.startswith(k)), (22, 70, 22))
            a = px(x, z)
            d.ellipse([a[0] - 1.2, a[1] - 1.2, a[0] + 1.2, a[1] + 1.2], fill=c)
        else:
            d.point(px(x, z), fill=(120, 80, 60))
    for t in world["things"]:
        p = t.get("properties", {})
        if t["type"] == "marker" and p.get("marker_kind") == "location":
            a = px(t["pos"][0], t["pos"][2])
            d.ellipse([a[0] - 2, a[1] - 2, a[0] + 2, a[1] + 2], fill=(255, 255, 190))
            d.text((a[0] + 4, a[1] - 6), p.get("place_name", ""), fill=(255, 255, 210))
        elif t["type"] == "levelchanger":
            a = px(t["pos"][0], t["pos"][2])
            d.ellipse([a[0] - 4, a[1] - 4, a[0] + 4, a[1] + 4], fill=(255, 0, 255))
    img.save(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("map", nargs="?", default=MAP)
    ap.add_argument("-o", "--out", help="write here instead of over the input")
    ap.add_argument("--preview", help="also write a top-down PNG of the result")
    ap.add_argument("--preview-only", action="store_true",
                    help="only draw the preview of the map as it is")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    with open(args.map) as f:
        world = json.load(f)
    if args.preview_only:
        preview(world, args.preview or "world.png")
        return
    if world.get("_miniwind_world", {}).get("enlivened") and not args.force:
        raise SystemExit(f"{args.map} has already been enlivened (use --force)")
    Enliven(world).run()
    out = args.out or args.map
    ew.dump(world, out)
    print(f"wrote {out} ({os.path.getsize(out) / 1e6:.1f} MB, "
          f"{len(world['brushes'])} brushes, {len(world['things'])} things)")
    if args.preview:
        preview(world, args.preview)
        print(f"preview {args.preview}")


if __name__ == "__main__":
    main()
