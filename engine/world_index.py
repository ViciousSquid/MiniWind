"""
The engine's authoritative spatial index of the world's *actors*.

Fio already owns one authoritative index of static geometry —
:class:`engine.physics.SpatialGrid`, 512-unit XZ cells, ``floor(coord/cell)``.
It never had an equivalent for the things that move, so every system that
needed to know "who is near whom" grew its own answer:

* :meth:`engine.monster_ai.MonsterAI._build_ai_snapshot` binned actors into a
  private 1024-unit hash, once per AI tick;
* ``game.runtime.MiniwindSession`` walked its whole actor list per NPC per
  decision pass (an O(N^2) scan that dominated the settlement profile);
* the world streamer indexed the same objects again into its own 512-unit
  cells to decide what to stream;
* ``LogicThread._prepare_render_state`` decided visibility from a fourth pass.

This module is the one place that question is answered. It is a **core engine
service** (``LogicThread.world_index``), not a plugin: world-scale relevance is
what the renderer, the AI, the gameplay layer and the streamer all consume, so
it cannot live behind an optional abstraction.

What it provides
----------------
* Contiguous NumPy arrays of every actor's position, team id and liveness,
  rebuilt in a single pass per logic tick into **reusable buffers** — no
  per-frame array construction and no Python/NumPy round-tripping per actor.
* Vectorised radius queries (:meth:`WorldIndex.rows_near`,
  :meth:`WorldIndex.nearest`) over 512-unit cell bins that share the spatial
  grid's coordinate convention exactly, so an index cell and a grid cell cover
  the same patch of world.
* A **simulation LOD tier** per actor (:data:`TIER_NEAR` … :data:`TIER_DORMANT`),
  derived from the radii the engine already uses, with hysteresis so an actor
  loitering on a boundary does not flap between tiers.

Callers hold row indices, never copies: :attr:`WorldIndex.actors` maps a row
back to the live object. Nothing here mutates an actor.

Dependency-light on purpose — NumPy only, no Qt/GL/glm — so it imports in the
editor, the standalone player and headless tests alike.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

# One grid convention across the engine: the collision grid, this index, the
# renderer's camera-region brush cull and the Big World streamer all address
# cells through engine/cells.py, so cell (3, -2) means the same patch of ground
# to every one of them.
from .cells import CELL_SIZE

# --- Simulation LOD tiers ---------------------------------------------------
#: Player vicinity. Full simulation: AI, perception, schedules, movement,
#: combat, animation, needs, collision.
TIER_NEAR = 0
#: Near world. Reduced simulation: schedules and coarse movement, staggered
#: decisions, no per-frame perception.
TIER_ACTIVE = 1
#: Distant world. No normal per-frame simulation — coarse time advancement and
#: event-driven state changes only.
TIER_DISTANT = 2
#: Unloaded / streamed out. No simulation at all; state persists.
TIER_DORMANT = 3

#: Outer edge of :data:`TIER_NEAR`. ``MONSTER_SIGHT_RANGE`` — the radius inside
#: which an actor can see the player or be seen by it, so anything that could
#: interact this tick is fully simulated. Not an invented number: it is the
#: engine's own perception range.
TIER_NEAR_RADIUS = 1024.0
#: Outer edge of :data:`TIER_ACTIVE`. Matches ``bigworld``'s default activation
#: radius — the region the engine already considers streamed-in and live.
TIER_ACTIVE_RADIUS = 2048.0
#: Fraction of a tier radius an actor must travel *beyond* the boundary before
#: it is demoted, mirroring the activation/deactivation hysteresis the streamer
#: uses (2048 -> 2304). Stops an actor pacing a boundary from flapping tiers.
TIER_HYSTERESIS = 0.125

#: Below this many actors the cell bins cost more to build than they save, so
#: radius queries run as one vectorised pass over every row instead. Measured,
#: not guessed: a full NumPy pass over a few dozen rows is a couple of
#: microseconds, well under the cost of binning them.
BIN_THRESHOLD = 64

#: Empty result reused by every query that matches nothing, so a miss allocates
#: nothing. Never mutate it.
_NO_ROWS = np.empty(0, dtype=np.intp)


class WorldIndex:
    """A per-tick spatial index over a list of actor objects.

    An *actor* is anything with a ``pos`` sequence and a ``properties`` dict —
    the engine's ``Monster`` things, and by extension every MiniWind NPC and
    creature, which are the same class.

    Rebuild once per logic tick with :meth:`rebuild`; query as often as you
    like within that tick. Positions are frozen at rebuild, so every consumer
    in a tick agrees about where everyone is (the same guarantee the AI
    snapshot gave, now shared by every system).
    """

    __slots__ = (
        "cell_size", "actors", "n", "_cap",
        "px", "pz", "py", "alive", "dead", "team_ids", "tiers", "dist2", "_scratch",
        "team_names", "_team_of_name", "_bins", "_binned", "_prev_tiers",
        "authoritative",
        "_row_of", "_derived", "_focus",
    )

    def __init__(self, cell_size: float = CELL_SIZE):
        self.cell_size = float(cell_size)
        self.actors: List = []
        self.n = 0
        #: Whether this index actually classified a world this tick. False means
        #: "no relevance information" — no focus point (the editor, a headless
        #: test) or the engine deliberately skipped classification for a cast
        #: too small to be worth it. Consumers must fall back to their scalar
        #: paths in that case; they must NOT read an empty index as "nothing is
        #: relevant", because an *authoritative* empty index means exactly that
        #: and the two are opposite answers.
        self.authoritative = False
        self._cap = 0
        # Reusable coordinate/state buffers, grown geometrically and sliced to
        # ``n`` — a steady-state tick allocates nothing here.
        self.px = np.empty(0, dtype=np.float64)
        self.py = np.empty(0, dtype=np.float64)
        self.pz = np.empty(0, dtype=np.float64)
        self.alive = np.empty(0, dtype=bool)
        #: Per-row "this actor is a corpse" flag. Distinct from ``not alive``,
        #: which also covers hidden/streamed-out actors — a body still on the
        #: ground is something the living can see and react to.
        self.dead = np.empty(0, dtype=bool)
        self.team_ids = np.empty(0, dtype=np.int32)
        self.tiers = np.empty(0, dtype=np.int8)
        self.dist2 = np.empty(0, dtype=np.float64)
        self._scratch = np.empty(0, dtype=np.float64)
        #: Distinct team strings in scene order; ``team_ids`` indexes into it.
        self.team_names: List[str] = []
        self._team_of_name: Dict[str, int] = {}
        self._bins: Dict[tuple, np.ndarray] = {}
        self._binned = False
        #: Last tick's tiers, so only actual transitions are written back onto
        #: the actors. None until the first classification, and dropped whenever
        #: the actor list changes shape.
        self._prev_tiers: Optional[np.ndarray] = None
        #: ``id(actor) -> row``, built on first use. Most ticks only move
        #: actors and never ask, so building it in every rebuild was a dict of
        #: N entries per tick that nothing read.
        self._row_of: Optional[Dict[int, int]] = None
        self._derived: Dict[str, np.ndarray] = {}
        self._focus = (0.0, 0.0)

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _ensure_capacity(self, n: int) -> None:
        if n <= self._cap:
            return
        cap = max(16, self._cap * 2, n)
        self.px = np.empty(cap, dtype=np.float64)
        self.py = np.empty(cap, dtype=np.float64)
        self.pz = np.empty(cap, dtype=np.float64)
        self.alive = np.empty(cap, dtype=bool)
        self.dead = np.empty(cap, dtype=bool)
        self.team_ids = np.empty(cap, dtype=np.int32)
        self.tiers = np.empty(cap, dtype=np.int8)
        self.dist2 = np.empty(cap, dtype=np.float64)
        self._scratch = np.empty(cap, dtype=np.float64)
        self._cap = cap

    def rebuild(self, actors: Sequence, focus_xz=None,
                near_radius: float = TIER_NEAR_RADIUS,
                active_radius: float = TIER_ACTIVE_RADIUS) -> None:
        """Snapshot *actors* into the index and classify their sim tiers.

        *focus_xz* is the point relevance is measured from — the player, or the
        camera when there is no player. ``None`` leaves every loaded actor at
        :data:`TIER_NEAR` (the safe answer: full simulation), which is what a
        headless test or an editor preview wants.

        One Python pass over the actor list fills the coordinate buffers; the
        tier classification, distances and cell keys are then computed for the
        whole batch at once.
        """
        self.authoritative = focus_xz is not None
        n = len(actors)
        if self._prev_tiers is not None and (n != self._prev_tiers.shape[0]
                                             or actors is not self.actors):
            # A different actor list (or a different length) means row i is no
            # longer the same actor: last tick's tiers cannot be compared to
            # this tick's, so stamp them all.
            self._prev_tiers = None
        self.actors = actors
        self.n = n
        self._bins = {}
        self._binned = False
        self._derived = {}
        self._row_of = None
        if n == 0:
            return
        self._ensure_capacity(n)
        px, py, pz = self.px, self.py, self.pz
        alive, dead, team_ids = self.alive, self.dead, self.team_ids
        team_of_name = self._team_of_name
        team_names = self.team_names
        dormant = []
        for i in range(n):
            a = actors[i]
            p = a.pos
            px[i] = p[0]
            py[i] = p[1]
            pz[i] = p[2]
            props = a.properties
            is_dead = bool(props.get("dead"))
            # An actor the streamer parked (`disabled`) or the map hid is not
            # part of the live world at all — dormant, whatever its distance.
            parked = bool(props.get("hidden") or props.get("disabled"))
            dead[i] = is_dead
            alive[i] = not (is_dead or parked)
            if parked:
                dormant.append(i)
            team = props.get("team") or props.get("faction") or ""
            tid = team_of_name.get(team)
            if tid is None:
                tid = len(team_names)
                team_names.append(team)
                team_of_name[team] = tid
            team_ids[i] = tid

        d2 = self.dist2[:n]
        if focus_xz is None:
            d2[:] = 0.0
            self.tiers[:n] = TIER_NEAR
            self._focus = (0.0, 0.0)
            for i in dormant:
                self.tiers[i] = TIER_DORMANT
            for i in range(n):
                actors[i].properties["_sim_tier"] = int(self.tiers[i])
            return
        else:
            fx = float(focus_xz[0])
            fz = float(focus_xz[1])
            self._focus = (fx, fz)
            # d2 = (px-fx)^2 + (pz-fz)^2, computed in place on the reusable
            # buffer so no temporary array is allocated per tick.
            np.subtract(px[:n], fx, out=d2)
            np.multiply(d2, d2, out=d2)
            tmp = self._scratch[:n]
            np.subtract(pz[:n], fz, out=tmp)
            np.multiply(tmp, tmp, out=tmp)
            np.add(d2, tmp, out=d2)
            self._classify(n, d2, actors, dormant,
                           float(near_radius), float(active_radius))

    def _classify(self, n: int, d2: np.ndarray, actors: Sequence,
                  dormant: Sequence[int],
                  near_radius: float, active_radius: float) -> None:
        """Fill ``tiers[:n]`` from squared distance, with hysteresis.

        Promotion uses the plain radius; demotion needs the actor to be a
        :data:`TIER_HYSTERESIS` band beyond it. The previous tier lives on the
        actor (``_sim_tier``) so it survives an index rebuild, and a boundary
        loiterer stays put instead of re-planning every tick.

        *dormant* holds the rows the streamer has parked. They are forced to
        :data:`TIER_DORMANT` **before** the tier is stamped onto the actors, so
        the AI (which reads the stamp, not the array) sees the same answer the
        index does.
        """
        tiers = self.tiers
        near2 = near_radius * near_radius
        act2 = active_radius * active_radius
        h = 1.0 + TIER_HYSTERESIS
        near_out2 = near2 * h * h
        act_out2 = act2 * h * h
        # Batch the three bands, then fix up only the rows sitting inside a
        # hysteresis band — normally a handful, so the Python touch-up is tiny.
        raw = np.where(d2 <= near2, TIER_NEAR,
                       np.where(d2 <= act2, TIER_ACTIVE, TIER_DISTANT))
        tiers[:n] = raw
        band = np.nonzero(((d2 > near2) & (d2 <= near_out2)) |
                          ((d2 > act2) & (d2 <= act_out2)))[0]
        for i in band:
            prev = actors[i].properties.get("_sim_tier")
            if prev is not None and prev < tiers[i]:
                tiers[i] = prev
        for i in dormant:
            tiers[i] = TIER_DORMANT
        # Stamp the tier onto the actors — this is how the AI thread reads it
        # without touching these arrays across threads. Only the rows that
        # actually changed are written: in a settled world almost nobody changes
        # tier in a given tick, so this is a handful of dict writes rather than
        # one per actor per tick.
        prev = self._prev_tiers
        if prev is None or prev.shape[0] < n:
            for i in range(n):
                actors[i].properties["_sim_tier"] = int(tiers[i])
        else:
            for i in np.nonzero(prev[:n] != tiers[:n])[0].tolist():
                actors[i].properties["_sim_tier"] = int(tiers[i])
        self._prev_tiers = tiers[:n].copy()

    # ------------------------------------------------------------------
    # Bins
    # ------------------------------------------------------------------

    def _build_bins(self) -> None:
        """Group rows into 512-unit XZ cells, vectorised.

        Built lazily on the first radius query of a tick, and only above
        :data:`BIN_THRESHOLD` rows — below that a full vectorised scan beats
        the bookkeeping.
        """
        self._binned = True
        n = self.n
        if n < BIN_THRESHOLD:
            return
        inv = 1.0 / self.cell_size
        cx = np.floor(self.px[:n] * inv).astype(np.int64)
        cz = np.floor(self.pz[:n] * inv).astype(np.int64)
        # One 64-bit key per row, so grouping is a single sort.
        keys = (cx << 32) ^ (cz & 0xFFFFFFFF)
        order = np.argsort(keys, kind="stable")
        sorted_keys = keys[order]
        starts = np.flatnonzero(np.r_[True, sorted_keys[1:] != sorted_keys[:-1]])
        ends = np.r_[starts[1:], n]
        bins = self._bins
        cxs = cx[order]
        czs = cz[order]
        for s, e in zip(starts.tolist(), ends.tolist()):
            bins[(int(cxs[s]), int(czs[s]))] = order[s:e]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def rows_near(self, x: float, z: float, radius: float) -> np.ndarray:
        """Row indices whose XZ position is within *radius* of ``(x, z)``.

        Returns a NumPy integer array (possibly empty). The result is a fresh
        array only when the query actually matches; a miss returns a shared
        empty array, so a scan that finds nobody allocates nothing.
        """
        n = self.n
        if n == 0 or radius <= 0.0:
            return _NO_ROWS
        if not self._binned:
            self._build_bins()
        r2 = radius * radius
        if not self._bins:
            # Small world: one vectorised pass beats any bookkeeping.
            dx = self.px[:n] - x
            dz = self.pz[:n] - z
            hit = np.nonzero(dx * dx + dz * dz <= r2)[0]
            return hit
        cs = self.cell_size
        inv = 1.0 / cs
        cx0 = int(math.floor((x - radius) * inv))
        cx1 = int(math.floor((x + radius) * inv))
        cz0 = int(math.floor((z - radius) * inv))
        cz1 = int(math.floor((z + radius) * inv))
        bins = self._bins
        parts = []
        for gx in range(cx0, cx1 + 1):
            for gz in range(cz0, cz1 + 1):
                b = bins.get((gx, gz))
                if b is not None:
                    parts.append(b)
        if not parts:
            return _NO_ROWS
        cand = parts[0] if len(parts) == 1 else np.concatenate(parts)
        dx = self.px[cand] - x
        dz = self.pz[cand] - z
        keep = dx * dx + dz * dz <= r2
        if keep.all():
            return cand
        return cand[keep]

    def nearest(self, x: float, z: float, radius: float,
                mask: Optional[np.ndarray] = None,
                exclude_row: int = -1) -> int:
        """The row nearest ``(x, z)`` within *radius*, or ``-1``.

        *mask* is an optional per-row boolean array (length :attr:`n`) the
        candidate must satisfy — e.g. "alive and on a hostile team", built once
        per query by the caller with vectorised ops rather than a predicate
        called per candidate. Ties break toward the lower row index, matching
        the scene-order tie-break the hand-written scans used.
        """
        cand = self.rows_near(x, z, radius)
        if cand.size == 0:
            return -1
        if mask is not None:
            cand = cand[mask[cand]]
            if cand.size == 0:
                return -1
        if exclude_row >= 0:
            cand = cand[cand != exclude_row]
            if cand.size == 0:
                return -1
        dx = self.px[cand] - x
        dz = self.pz[cand] - z
        d2 = dx * dx + dz * dz
        best = int(np.argmin(d2))
        # np.argmin already returns the first minimum, and `cand` is ascending
        # within a bin; sort only matters across bins, so pick the lowest row
        # among exact ties to match the old scan order.
        tied = cand[d2 == d2[best]]
        return int(tied.min()) if tied.size > 1 else int(cand[best])

    # ------------------------------------------------------------------
    # Derived per-row data
    # ------------------------------------------------------------------

    def team_relation_table(self, rel: Callable[[str], int]) -> np.ndarray:
        """A ``team_id -> int`` lookup table built by calling *rel* once per
        **distinct team name** rather than once per actor pair.

        The faction predicate is game policy and stays in the game layer; this
        just collapses N^2 predicate calls to O(distinct teams).
        """
        return np.fromiter((rel(name) for name in self.team_names),
                           dtype=np.int8, count=len(self.team_names))

    def derived(self, key: str, build: Callable[[], np.ndarray]) -> np.ndarray:
        """Memoise a per-row boolean/int array for the current tick.

        Lets the game layer attach its own classifications (is this actor a
        combatant? is it rallied?) to the shared index without the core
        knowing what they mean, and without recomputing them per query.
        """
        arr = self._derived.get(key)
        if arr is None:
            arr = build()
            self._derived[key] = arr
        return arr

    # ------------------------------------------------------------------
    # Row / tier helpers
    # ------------------------------------------------------------------

    def _rows(self) -> Dict[int, int]:
        """The ``id(actor) -> row`` map, built on demand."""
        rows = self._row_of
        if rows is None:
            actors = self.actors
            rows = {id(actors[i]): i for i in range(self.n)}
            self._row_of = rows
        return rows

    def row_of(self, actor) -> int:
        """The row holding *actor*, or ``-1`` if it is not in the index."""
        return self._rows().get(id(actor), -1)

    def tier_of(self, actor) -> int:
        """The simulation tier of *actor*.

        Falls back to the tier stamped on the actor (then :data:`TIER_NEAR`)
        when it is not in the current index, so a caller never accidentally
        skips simulating something the index has not seen yet.
        """
        row = self._rows().get(id(actor), -1)
        if row < 0:
            return int(actor.properties.get("_sim_tier", TIER_NEAR))
        return int(self.tiers[row])

    def mark_dead(self, actor) -> None:
        """Flag *actor* not-alive in this tick's snapshot.

        Mirrors the AI's old ``_snapshot_mark_dead``: a kill resolved mid-tick
        must not still be targetable by a later query in the same tick.
        """
        row = self._rows().get(id(actor), -1)
        if row >= 0:
            self.alive[row] = False
            self.dead[row] = True

    def rows_of_tier(self, tier: int) -> np.ndarray:
        """Rows whose simulation tier is exactly *tier*."""
        if self.n == 0:
            return _NO_ROWS
        return np.nonzero(self.tiers[:self.n] == tier)[0]

    def counts_by_tier(self) -> Dict[int, int]:
        """``{tier: count}`` — the numbers a perf overlay wants."""
        if self.n == 0:
            return {}
        vals, counts = np.unique(self.tiers[:self.n], return_counts=True)
        return {int(v): int(c) for v, c in zip(vals, counts)}
