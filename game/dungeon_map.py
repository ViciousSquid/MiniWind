"""
A dungeon design -- a grid of SOLID / open cells and a few markers -- and the
playable MiniWind map built from it.

The Dungeon Designer (``game/tools/dungeon_designer.py``) edits a
:class:`Design`; :func:`build_map` turns it into a map: a floor under the
whole grid, a wall block on every solid cell (merged along rows, so a dungeon
is tens of brushes, not thousands), and the markers made real:

* **Entrance** -- the way in and out: a LevelChanger back to the map the
  dungeon is entered from ("[E] Leave ...", straight there), a dark doorway
  behind it, and the PlayerStart ``entrance`` a few steps inside, facing in.
* **Monster** -- a creature of the chosen kind (count of them on the cell).
* **Chest** -- a chest holding the listed loot (``gold:50, potion_heal:1``).
* **Light** -- a warm, cold or eerie light. With none placed, lights are
  spread through the dungeon on their own.

The design is stored in the map itself (``_dungeon_design``), so a map made
here opens again in the designer for more editing.
"""

from __future__ import annotations

import copy
import json
import math
import uuid
from typing import Dict, List, Optional

import numpy as np

from . import tilemap_gen as tg

DEFAULT_EXIT_MAP = "maps/village_walled_source.json"
MARKER_KINDS = ("entrance", "monster", "chest", "light")
STYLES = {
    # walls, wall tops, floor
    "cave": ("tiledrock.jpg", "Stone_09-512x512.png", "cave.png"),
    "dungeon": ("stone-wall-v0-63mmfjnritm81.png", "Stone_09-512x512.png", "flagstone.jpg"),
}
LIGHT_COLOURS = {"warm": (255, 150, 80), "cold": (120, 200, 255), "eerie": (140, 255, 160)}
BLACK = "_black.jpg"


def _uid():
    return str(uuid.uuid4())


class Design:
    """The designer's document: grid, markers and options."""

    def __init__(self, width=40, height=30):
        self.name = "New Dungeon"
        self.file = "maps/dungeon01.json"
        self.style = "cave"
        self.cell = 128.0
        self.wall_height = 320.0
        self.exit_map = DEFAULT_EXIT_MAP
        self.exit_spawn = ""
        self.solid = np.ones((int(height), int(width)), bool)
        self.markers: List[Dict] = []

    # -- shape -----------------------------------------------------------------
    @property
    def width(self):
        return self.solid.shape[1]

    @property
    def height(self):
        return self.solid.shape[0]

    def resize(self, width, height):
        new = np.ones((int(height), int(width)), bool)
        h, w = min(self.height, int(height)), min(self.width, int(width))
        new[:h, :w] = self.solid[:h, :w]
        self.solid = new
        self.markers = [m for m in self.markers if m["i"] < height and m["j"] < width]

    def marker_at(self, i, j) -> Optional[Dict]:
        return next((m for m in self.markers if m["i"] == i and m["j"] == j), None)

    def set_marker(self, i, j, kind, **opts):
        self.remove_marker(i, j)
        if kind == "entrance":                      # only one way in
            self.markers = [m for m in self.markers if m["kind"] != "entrance"]
        self.solid[i, j] = False
        self.markers.append(dict({"kind": kind, "i": int(i), "j": int(j)}, **opts))

    def remove_marker(self, i, j):
        self.markers = [m for m in self.markers if not (m["i"] == i and m["j"] == j)]

    def drop_buried_markers(self):
        self.markers = [m for m in self.markers if not self.solid[m["i"], m["j"]]]

    def entrance(self):
        return next((m for m in self.markers if m["kind"] == "entrance"), None)

    def ensure_entrance(self):
        """Put the entrance on the open cell nearest the bottom middle if
        there is none. Returns it (None if the grid has no open cell)."""
        e = self.entrance()
        if e is not None:
            return e
        open_cells = np.argwhere(~self.solid)
        if not len(open_cells):
            return None
        mid = self.width / 2.0
        i, j = max(open_cells.tolist(), key=lambda c: (c[0], -abs(c[1] - mid)))
        self.set_marker(i, j, "entrance")
        return self.entrance()

    def generate(self, method, seed):
        tiles = tg.generate(method, self.width, self.height, seed)
        self.solid = tiles == tg.WALL
        self.markers = []
        e = self.ensure_entrance()
        if e is not None:
            self.solid = tg.keep_connected(np.where(self.solid, tg.WALL, tg.FLOOR),
                                           (e["i"], e["j"])) == tg.WALL

    # -- persistence -------------------------------------------------------------
    def to_dict(self) -> Dict:
        return {"version": 1, "name": self.name, "file": self.file, "style": self.style,
                "cell": self.cell, "wall_height": self.wall_height,
                "exit_map": self.exit_map, "exit_spawn": self.exit_spawn,
                "rows": ["".join("#" if s else "." for s in row) for row in self.solid],
                "markers": copy.deepcopy(self.markers)}

    @classmethod
    def from_dict(cls, d: Dict) -> "Design":
        rows = d.get("rows") or ["#"]
        des = cls(len(rows[0]), len(rows))
        des.solid = np.array([[c == "#" for c in r.ljust(len(rows[0]), "#")] for r in rows], bool)
        for k in ("name", "file", "style", "exit_map", "exit_spawn"):
            if k in d:
                setattr(des, k, str(d[k]))
        des.cell = float(d.get("cell", des.cell))
        des.wall_height = float(d.get("wall_height", des.wall_height))
        des.markers = [m for m in d.get("markers", []) if m.get("kind") in MARKER_KINDS
                       and 0 <= int(m.get("i", -1)) < des.height
                       and 0 <= int(m.get("j", -1)) < des.width]
        return des

    @classmethod
    def from_map(cls, level: Dict) -> Optional["Design"]:
        d = level.get("_dungeon_design") if isinstance(level, dict) else None
        return cls.from_dict(d) if isinstance(d, dict) else None


# ---------------------------------------------------------------------------
# Building the map
# ---------------------------------------------------------------------------
def _tex(side, top=None, down=None):
    t = {k: side for k in ("north", "south", "east", "west")}
    t["top"] = top or side
    t["down"] = down or side
    return t


def _thing(kind, pos, **props):
    p = {"type": kind, "name": props.pop("name", kind), "id": _uid()}
    p.update(props)
    return {"type": kind, "pos": [round(float(v), 1) for v in pos],
            "properties": p, "io_connections": []}


def _light(name, pos, radius, colour, intensity=1.8):
    return _thing("light", pos, name=name, colour=list(colour), intensity=intensity,
                  radius=float(radius), state="on", show_radius=False,
                  casts_shadows=False, parent_mover="", parent_offset=[0.0, 0.0, 0.0])


def _editor_angle(dx, dz):
    """The PlayerStart angle (editor degrees) that faces along (dx, dz)."""
    g = math.atan2(dx, dz)
    return round((90.0 - math.degrees(g - math.pi)) % 360.0, 1)


def parse_loot(text) -> List[Dict]:
    """``"gold:50, potion_heal"`` as item stacks (unknown ids are skipped)."""
    from .rpg import items as rpg_items
    out = []
    for part in str(text or "").split(","):
        part = part.strip()
        if not part:
            continue
        iid, _, qty = part.partition(":")
        try:
            n = int(qty) if qty.strip() else 1
        except ValueError:
            n = 1
        stack = rpg_items.make(iid.strip(), max(1, n))
        if stack:
            out.append(stack)
    return out


def _distances(open_, start):
    h, w = open_.shape
    dist = np.full(open_.shape, -1)
    dist[start] = 0
    frontier = [start]
    while frontier:
        nxt = []
        for i, j in frontier:
            for a, b in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if 0 <= a < h and 0 <= b < w and open_[a, b] and dist[a, b] < 0:
                    dist[a, b] = dist[i, j] + 1
                    nxt.append((a, b))
        frontier = nxt
    return dist


def build_map(design: Design, settings: Optional[Dict] = None) -> Dict:
    """The playable map for *design*."""
    from .rpg import bestiary
    d = design
    cell = float(d.cell)
    h, w = d.height, d.width
    walls, tops, floor = STYLES.get(d.style, STYLES["cave"])

    def pos_of(i, j):
        return ((j - w / 2.0 + 0.5) * cell, (i - h / 2.0 + 0.5) * cell)

    open_ = ~d.solid
    brushes, things = [], []
    brushes.append({"pos": [0.0, -16.0, 0.0],
                    "size": [(w + 2) * cell, 32.0, (h + 2) * cell],
                    "textures": _tex(walls, floor), "id": _uid()})
    solid = np.pad(d.solid, 1, constant_values=True)
    wall_tex = _tex(walls, tops)
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
            x0, z = pos_of(i, j0)
            x1, _ = pos_of(i, j1)
            wall_h = float(d.wall_height)
            if d.style == "cave":
                wall_h += 32.0 * ((r * 7 + c0 * 3) % 5)
            brushes.append({"pos": [round((x0 + x1) / 2.0, 1), wall_h / 2.0, round(z, 1)],
                            "size": [(j1 - j0 + 1) * cell, wall_h, cell],
                            "textures": dict(wall_tex), "id": _uid()})
    e = d.entrance()
    dist = None
    if e is not None:
        ei, ej = e["i"], e["j"]
        ex, ez = pos_of(ei, ej)
        dist = _distances(open_, (ei, ej))
        # The way out: dark on each side of the entrance cell that is wall.
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ni, nj = ei + di, ej + dj
            if 0 <= ni < h and 0 <= nj < w and open_[ni, nj]:
                continue
            px, pz = ex + dj * cell * 0.5, ez + di * cell * 0.5
            size = [cell, 260.0, 24.0] if di else [24.0, 260.0, cell]
            brushes.append({"pos": [round(px, 1), 130.0, round(pz, 1)], "size": size,
                            "textures": _tex(BLACK), "id": _uid()})
        if d.exit_map:
            things.append(_thing("levelchanger", (ex, 64.0, ez), name="LevelChanger_exit",
                                 target_map=d.exit_map, delay=0.0, fade_time=0.5,
                                 show_radius=False, radius=150.0, usable=True,
                                 destination_spawn=d.exit_spawn, generate_level=False,
                                 prompt=f"[E] Leave {d.name}", confirm=False))
        # The start: a few steps in, facing away from the way out.
        reach = [(int(dist[i, j]), i, j) for i, j in np.argwhere(open_) if 0 < dist[i, j] <= 3]
        if reach:
            _, si, sj = max(reach)
        else:
            si, sj = ei, ej
        sx, sz = pos_of(si, sj)
        things.append(_thing("playerstart", (sx, 72.0, sz), name="entrance",
                             angle=_editor_angle(sx - ex, sz - ez) if (si, sj) != (ei, ej) else 0.0,
                             primary=True, creation_index=0))
        things.append(_light("Light_entrance", (ex, 220.0, ez), 600.0, (200, 215, 255), 1.4))
    for k, m in enumerate(d.markers):
        x, z = pos_of(m["i"], m["j"])
        kind = m["kind"]
        if kind == "monster":
            role = str(m.get("role") or "skeleton")
            tmpl = bestiary.get(role) if hasattr(bestiary, "get") else None
            label = getattr(tmpl, "name", role.replace("_", " ").title())
            for n in range(max(1, int(m.get("count", 1)))):
                ox = (n % 3 - 1) * cell * 0.25
                oz = (n // 3) * cell * 0.25
                things.append(_thing("creature", (x + ox, 40.0, z + oz),
                                     name=f"{label}_{k}_{n}", npc_role=role,
                                     home=[round(x + ox, 1), 40.0, round(z + oz, 1)]))
        elif kind == "chest":
            things.append(_thing("container", (x, 48.0, z), name=f"Chest_{k}",
                                 container_kind="chest", display_name="Chest",
                                 inventory=parse_loot(m.get("loot", "gold:25")),
                                 use_radius=128.0, locked=False,
                                 custom_idle="assets/sprites/miniwind/container_chest.png"))
        elif kind == "light":
            colour = LIGHT_COLOURS.get(str(m.get("colour", "warm")), LIGHT_COLOURS["warm"])
            things.append(_light(f"Light_{k}", (x, 200.0, z), 620.0, colour))
    if not any(m["kind"] == "light" for m in d.markers):
        _auto_lights(things, open_, pos_of)
    s = copy.deepcopy(settings) if settings else {
        "type": "miniwindsettings", "pos": [0.0, 400.0, 0.0], "io_connections": [],
        "properties": {"type": "miniwindsettings", "name": "GameSettings_1",
                       "start_hour": 8.0, "start_day": 1, "minutes_per_day": 24.0,
                       "show_clock": True, "state_store": "miniwind",
                       "difficulty": "normal", "start_scenario": "prompt",
                       "player_spells": [], "quests": []}}
    s["properties"].update({"id": _uid(), "region_name": d.name})
    things.append(s)
    things.append(_thing("logic_command", (0.0, 420.0, 64.0), name="LogicCommand_1",
                         command="cam topdown", disabled=False))
    return {"version": 3, "brushes": brushes, "things": things,
            "created": "dungeon_designer", "terrain_data": {"enabled": False},
            "_dungeon_design": d.to_dict()}


def _auto_lights(things, open_, pos_of, spacing=7, limit=12):
    lit = []
    for i, j in np.argwhere(open_).tolist():
        if all(abs(i - a) + abs(j - b) >= spacing for a, b in lit):
            lit.append((i, j))
    for k, (i, j) in enumerate(lit[:limit]):
        x, z = pos_of(i, j)
        colour = LIGHT_COLOURS["warm"] if k % 2 == 0 else LIGHT_COLOURS["cold"]
        things.append(_light(f"Light_auto_{k}", (x, 200.0, z), 620.0, colour))


def save(design: Design, path: Optional[str] = None, settings=None) -> str:
    path = path or design.file
    level = build_map(design, settings)
    with open(path, "w") as f:
        json.dump(level, f, indent=1)
    return path
