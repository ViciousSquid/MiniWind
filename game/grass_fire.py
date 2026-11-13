"""
Grass fire: flame that runs through long grass, before the wind.

Set the heath alight -- a Flare that misses, a burning man running through
the wheat, a dragon's breath -- and the fire spreads on its own, the way it
does in dry grass: fast downwind, crawling upwind, stopping at roads, water,
bare earth and ground already burnt. Behind it the ground is black and the
grass is gone; anyone caught in it catches fire.

**The model.** The world is divided into :data:`CELL`-unit cells. A cell's
*fuel* (0..1) is how much will burn there, read from the terrain (see
:meth:`game.runtime.MiniwindSession._grass_fuel`): tall tundra heath and
wheat burn hot, ordinary meadow barely, roads, paths and painted ground,
swamp, sand and snow not at all. A burning cell flares up, burns for
:func:`burn_seconds` (longer the more fuel) and dies down; while it burns
it sets each of its eight neighbours alight at a rate that grows with their
fuel, its own heat and how squarely the wind blows from it to them. A burnt
cell never burns again.

**What it costs.** The fire is stepped :data:`STEP` seconds at a time, a few
times a second, and never has more than :data:`MAX_BURNING` cells alight at
once (a wildfire past that pauses at its edge until some burn out). Fuel is
read from the terrain in batches, a cell's neighbours at once, and kept.
The flames are the engine's FIRE Effects, spawned where it burns and taken
away when it burns out (:mod:`game.flame_spawner`): the burning blocks
nearest the player each get one, with its light.

Pure Python and numpy: no Qt, no GL, so it is tested headless. The terrain,
the wind and the ground's height come in as functions.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

#: The fire's grid: world units across a cell.
CELL = 64.0
#: Seconds of fire per simulation step; the fire is advanced in these.
STEP = 0.25
#: Most cells burning at once; past it, the fire waits at its edge.
MAX_BURNING = 900
#: Least fuel that can carry flame.
MIN_FUEL = 0.08
#: How fast fire jumps to a neighbour (per second, at full fuel and heat,
#: no wind), and how much the wind adds downwind / takes upwind.
SPREAD = 0.16
WIND_PUSH = 1.8
UPWIND_FLOOR = 0.06
#: A cell flares up over this many seconds, then dies down over its last.
FLARE_SECONDS = 0.8
DIE_SECONDS = 1.6
#: Most steps' worth of time one update may advance (a hitch never runs a
#: wildfire a minute ahead in one frame).
MAX_STEPS_PER_UPDATE = 8

_NEIGHBOURS = [(dx, dz) for dx in (-1, 0, 1) for dz in (-1, 0, 1) if dx or dz]


def burn_seconds(fuel: float, rng) -> float:
    """How long a cell with *fuel* burns: a few seconds of meadow, longer in
    the heath and the wheat."""
    return 3.0 + 5.0 * float(fuel) + rng.uniform(-0.6, 0.9)


def heat(left: float, total: float) -> float:
    """How fiercely a cell burns (0..1) with *left* of its *total* seconds:
    flaring up, burning, dying down."""
    age = total - left
    if age < FLARE_SECONDS:
        return max(0.05, age / FLARE_SECONDS)
    if left < DIE_SECONDS:
        return max(0.0, left / DIE_SECONDS)
    return 1.0


def cell_of(x: float, z: float) -> Tuple[int, int]:
    return int(math.floor(float(x) / CELL)), int(math.floor(float(z) / CELL))


def centre_of(key) -> Tuple[float, float]:
    return (key[0] + 0.5) * CELL, (key[1] + 0.5) * CELL


class GrassFire:
    """Every grass fire burning in one world (see the module doc).

    *fuel* is ``fuel(xs, zs) -> array`` of 0..1 per point; *height* is
    ``height(x, z) -> float`` (the ground under a cell, for drawing);
    *wind* is ``() -> (x, z)``, the wind's vector (strength 0..1).
    """

    def __init__(self, fuel: Callable, height: Callable = None, wind: Callable = None,
                 rng=None):
        self.fuel_at = fuel
        self.height_at = height or (lambda x, z: 0.0)
        self.wind = wind or (lambda: (0.0, 0.0))
        self.rng = rng or random.Random()
        #: key -> [seconds left, total seconds, fuel, ground y, seed]
        self.burning: Dict[Tuple[int, int], list] = {}
        #: Cells that have burnt out: they never burn again.
        self.burnt = set()
        #: Cells burnt out since the session last scorched the ground.
        self.scorch_due: List[Tuple[int, int]] = []
        #: Who set it, by cell (for blame: a fire the player started).
        self.by: Dict[Tuple[int, int], object] = {}
        self._fuel: Dict[Tuple[int, int], float] = {}
        #: Told of each cell as it burns out: ``on_burnt(key)``.
        self.on_burnt = None
        #: ``() -> (douse, dryness)``: rain fighting the fire (0..1) and how
        #: dry the ground is (1 dry .. 0 soaked), from game/weather.py.
        self.weather = None
        self._carry = 0.0
        self._arrays = None

    # ------------------------------------------------------------- fuel
    def fuel(self, key) -> float:
        """The fuel in cell *key* (read from the terrain once, then kept)."""
        f = self._fuel.get(key)
        if f is None:
            self._prefetch([key])
            f = self._fuel.get(key, 0.0)
        return f

    def _prefetch(self, keys) -> None:
        keys = [k for k in keys if k not in self._fuel]
        if not keys:
            return
        xs = np.array([(k[0] + 0.5) * CELL for k in keys], np.float32)
        zs = np.array([(k[1] + 0.5) * CELL for k in keys], np.float32)
        try:
            values = np.asarray(self.fuel_at(xs, zs), np.float32).ravel()
        except Exception:
            values = np.zeros(len(keys), np.float32)
        for k, v in zip(keys, values):
            self._fuel[k] = float(max(0.0, min(1.0, v)))
        if len(self._fuel) > 200000:            # a long life: forget the oldest reads
            for k in list(self._fuel)[:100000]:
                del self._fuel[k]

    # ---------------------------------------------------------- lighting
    def ignite(self, x: float, z: float, by=None) -> bool:
        """Set the grass at (*x*, *z*) alight; False where nothing will burn
        (no fuel, already burning or burnt, or the fire is at its limit)."""
        return self._light(cell_of(x, z), by)

    def _light(self, key, by=None) -> bool:
        if key in self.burning or key in self.burnt or len(self.burning) >= MAX_BURNING:
            return False
        f = self.fuel(key)
        dry = self.weather()[1] if self.weather is not None else 1.0
        if f * dry < MIN_FUEL:
            return False                    # too little, or too wet, to catch
        total = burn_seconds(f, self.rng)
        cx, cz = centre_of(key)
        try:
            y = float(self.height_at(cx, cz))
        except Exception:
            y = 0.0
        self.burning[key] = [total, total, f, y, self.rng.random()]
        if by is not None:
            self.by[key] = by
        self._prefetch([(key[0] + dx, key[1] + dz) for dx, dz in _NEIGHBOURS])
        self._arrays = None
        return True

    def extinguish(self) -> None:
        """Put every fire out (the cells that burnt stay burnt)."""
        self.burning.clear()
        self.by.clear()
        self._arrays = None

    def clear(self) -> None:
        """Forget everything: a new world."""
        self.extinguish()
        self.burnt.clear()
        self.scorch_due.clear()
        self._fuel.clear()

    # ------------------------------------------------------------- time
    def update(self, delta: float) -> int:
        """Advance the fire by *delta* seconds; returns cells newly alight."""
        if not self.burning:
            self._carry = 0.0
            return 0
        self._carry += max(0.0, float(delta))
        steps = 0
        lit = 0
        while self._carry >= STEP and steps < MAX_STEPS_PER_UPDATE:
            self._carry -= STEP
            steps += 1
            lit += self._step()
        if steps >= MAX_STEPS_PER_UPDATE:
            self._carry = 0.0
        return lit

    def _step(self) -> int:
        wx, wz = self.wind()
        douse, dry = self.weather() if self.weather is not None else (0.0, 1.0)
        # Rain burns a fire out faster and holds it back; wet ground barely
        # catches. Heavy rain stops it spreading at all.
        burn_down = STEP * (1.0 + 5.0 * douse)
        hold = dry * max(0.0, 1.0 - 1.4 * douse) ** 2
        rng = self.rng
        newly = []
        done = []
        for key, cell in self.burning.items():
            cell[0] -= burn_down
            if cell[0] <= 0.0:
                done.append(key)
                continue
            h = heat(cell[0], cell[1]) * (0.5 + 0.5 * cell[2])
            if h <= 0.0:
                continue
            for dx, dz in _NEIGHBOURS:
                nk = (key[0] + dx, key[1] + dz)
                if nk in self.burning or nk in self.burnt:
                    continue
                f = self._fuel.get(nk)
                if f is None or f < MIN_FUEL:
                    continue
                dist = math.hypot(dx, dz)
                along = (dx * wx + dz * wz) / dist           # wind strength along the jump
                push = max(UPWIND_FLOOR, 1.0 + WIND_PUSH * along)
                rate = SPREAD * f * h * push / dist * hold
                if rng.random() < 1.0 - math.exp(-rate * STEP):
                    newly.append((nk, self.by.get(key)))
        for key in done:
            del self.burning[key]
            self.by.pop(key, None)
            self.burnt.add(key)
            self.scorch_due.append(key)
            if self.on_burnt is not None:
                self.on_burnt(key)
        lit = 0
        for nk, by in newly:
            if self._light(nk, by):
                lit += 1
        self._arrays = None                 # heat changes every step
        return lit

    # ---------------------------------------------------------- reading
    def heat_at(self, x: float, z: float) -> float:
        """How fiercely the ground at (*x*, *z*) burns (0 where it doesn't)."""
        cell = self.burning.get(cell_of(x, z))
        return heat(cell[0], cell[1]) if cell else 0.0

    def starter(self, x: float, z: float):
        """Whoever set the fire burning at (*x*, *z*), if anyone is known."""
        return self.by.get(cell_of(x, z))

    def bounds(self) -> Optional[Tuple[float, float, float, float]]:
        """``(min x, min z, max x, max z)`` of the cells alight, or None."""
        if not self.burning:
            return None
        ks = np.array(list(self.burning), np.int32)
        return (float(ks[:, 0].min() * CELL), float(ks[:, 1].min() * CELL),
                float((ks[:, 0].max() + 1) * CELL), float((ks[:, 1].max() + 1) * CELL))

    def arrays(self):
        """The burning cells as arrays: ``(x, y, z, heat, fuel, seed)``
        columns, rebuilt only when the fire changes (for drawing)."""
        if self._arrays is None:
            if not self.burning:
                self._arrays = np.zeros((0, 6), np.float32)
            else:
                rows = []
                for key, (left, total, f, y, seed) in self.burning.items():
                    cx, cz = centre_of(key)
                    rows.append((cx, y, cz, heat(left, total), f, seed))
                self._arrays = np.array(rows, np.float32)
        return self._arrays

    def take_scorch(self, most: int) -> List[Tuple[float, float, float]]:
        """Up to *most* burnt-out cells waiting to be scorched, as
        ``(x, z, fuel)``; they are then forgotten here."""
        out = []
        while self.scorch_due and len(out) < most:
            key = self.scorch_due.pop(0)
            cx, cz = centre_of(key)
            out.append((cx, cz, self._fuel.get(key, 0.5)))
        return out
