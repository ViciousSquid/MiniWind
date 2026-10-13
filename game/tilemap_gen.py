"""
Tilemap generators, ported from Fio's alpha editor (``generate_level.py`` on
the ``alpha`` branch of github.com/ViciousSquid/Fio).

A tilemap is a ``height x width`` integer array: :data:`WALL` (solid) or
:data:`FLOOR` (open). Two generators, as in alpha:

* ``genA`` -- **rooms and corridors**: non-overlapping rectangular rooms,
  each joined to the next by an L-shaped corridor two tiles wide. A dungeon.
* ``genB`` -- **winding corridors**: a few small rooms and many long
  corridors that turn at right angles every few tiles. A warren or a cave.

Changes from alpha: each generator takes its own ``random.Random`` (seeding
never touches the global generator), and genB's corridor count and length
scale with the map, so a small map is not carved solid.
"""

from __future__ import annotations

import random
from typing import Optional

import numpy as np

WALL = 0
FLOOR = 1

METHODS = {
    "genA": "Rooms and corridors",
    "genB": "Winding corridors",
}


class LevelGeneratorA:
    """Rooms and corridors (alpha's 'genA')."""

    def __init__(self, width=100, height=60, rng=None):
        self.width = width
        self.height = height
        self.rng = rng or random.Random()
        self.map = np.full((self.height, self.width), WALL, dtype=int)
        self.rooms = []

    def _create_rooms(self, max_rooms=15, min_room_size=6, max_room_size=12):
        r = self.rng
        max_room_size = max(3, min(max_room_size, (min(self.width, self.height) - 4) // 2))
        min_room_size = max(3, min(min_room_size, max_room_size))
        for _ in range(max_rooms):
            w = r.randint(min_room_size, max_room_size)
            h = r.randint(min_room_size, max_room_size)
            if self.width - w - 2 < 1 or self.height - h - 2 < 1:
                continue
            x = r.randint(1, self.width - w - 2)
            y = r.randint(1, self.height - h - 2)
            new_room = {"x": x, "y": y, "w": w, "h": h}
            if not any(self._rooms_intersect(new_room, other) for other in self.rooms):
                self._carve_room(new_room)
                self.rooms.append(new_room)

    @staticmethod
    def _rooms_intersect(a, b):
        return (a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"] and
                a["y"] < b["y"] + b["h"] and a["y"] + a["h"] > b["y"])

    def _carve_room(self, room):
        self.map[room["y"]:room["y"] + room["h"], room["x"]:room["x"] + room["w"]] = FLOOR

    def _create_corridors(self):
        for a, b in zip(self.rooms, self.rooms[1:]):
            ca = (a["x"] + a["w"] // 2, a["y"] + a["h"] // 2)
            cb = (b["x"] + b["w"] // 2, b["y"] + b["h"] // 2)
            if self.rng.random() < 0.5:
                self._carve_h_corridor(ca[0], cb[0], ca[1])
                self._carve_v_corridor(ca[1], cb[1], cb[0])
            else:
                self._carve_v_corridor(ca[1], cb[1], ca[0])
                self._carve_h_corridor(ca[0], cb[0], cb[1])

    def _carve_h_corridor(self, x1, x2, y):
        start_y = min(y, self.height - 2)
        for x in range(min(x1, x2), max(x1, x2) + 1):
            self.map[start_y:start_y + 2, x] = FLOOR

    def _carve_v_corridor(self, y1, y2, x):
        start_x = min(x, self.width - 2)
        for y in range(min(y1, y2), max(y1, y2) + 1):
            self.map[y, start_x:start_x + 2] = FLOOR

    def generate(self):
        self._create_rooms(max_rooms=max(15, self.width * self.height // 80))
        if len(self.rooms) > 1:
            self._create_corridors()
        return self.map


class LevelGeneratorB:
    """A few small rooms and many long winding corridors (alpha's 'genB')."""

    def __init__(self, width=100, height=60, rng=None):
        self.width = width
        self.height = height
        self.rng = rng or random.Random()
        self.map = np.full((self.height, self.width), WALL, dtype=int)
        self.rooms = []
        self.directions = [(-1, 0), (0, 1), (1, 0), (0, -1)]   # N, E, S, W as (dy, dx)

    _create_rooms = LevelGeneratorA._create_rooms
    _rooms_intersect = staticmethod(LevelGeneratorA._rooms_intersect)
    _carve_room = LevelGeneratorA._carve_room

    def _create_long_winding_corridor(self, start_pos, min_len, max_len, width):
        r = self.rng
        y, x = start_pos
        dir_idx = r.randint(0, 3)
        corridor_len = r.randint(min_len, max_len)
        turn_countdown = r.randint(5, 15)
        for _ in range(corridor_len):
            dy, dx = self.directions[dir_idx]
            ny, nx = y + dy, x + dx
            if not (1 <= nx < self.width - width - 1 and 1 <= ny < self.height - width - 1):
                dir_idx = (dir_idx + r.choice([-1, 1])) % 4
                continue
            turn_countdown -= 1
            if turn_countdown <= 0:
                dir_idx = (dir_idx + r.choice([-1, 1])) % 4
                turn_countdown = r.randint(5, 15)
            y, x = ny, nx
            self.map[y:y + width, x:x + width] = FLOOR

    def generate(self):
        r = self.rng
        self._create_rooms(max_rooms=5, min_room_size=5, max_room_size=10)
        width = 2
        # Alpha carved 50 corridors of 250-500 tiles into a 100 x 60 map;
        # scaled to the map so a small one is a warren, not a cleared floor.
        span = self.width + self.height
        num_corridors = max(4, self.width * self.height // 260)
        min_len, max_len = span, span * 2
        starts = [(r.randint(room["y"], room["y"] + room["h"] - 1),
                   r.randint(room["x"], room["x"] + room["w"] - 1)) for room in self.rooms]
        for _ in range(max(0, num_corridors - len(self.rooms))):
            starts.append((r.randint(1, self.height - width - 2),
                           r.randint(1, self.width - width - 2)))
        r.shuffle(starts)
        for pos in starts:
            self._create_long_winding_corridor(pos, min_len, max_len, width)
        return self.map


def generate(method: str = "genA", width: int = 100, height: int = 60,
             seed: Optional[int] = None) -> np.ndarray:
    """A ``height x width`` tilemap (WALL / FLOOR) from *method*."""
    rng = random.Random(seed)
    cls = LevelGeneratorB if method == "genB" else LevelGeneratorA
    return cls(int(width), int(height), rng).generate()


def keep_connected(tiles: np.ndarray, start) -> np.ndarray:
    """*tiles* with every open region not reachable from *start* filled in."""
    h, w = tiles.shape
    seen = np.zeros((h, w), bool)
    stack = [tuple(start)]
    while stack:
        i, j = stack.pop()
        if not (0 <= i < h and 0 <= j < w) or seen[i, j] or tiles[i, j] != FLOOR:
            continue
        seen[i, j] = True
        stack.extend(((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)))
    out = np.where(seen, FLOOR, WALL)
    return out
