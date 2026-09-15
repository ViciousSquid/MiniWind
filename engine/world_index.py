"""
MiniWind's actor index: vectorised "who is near whom" for the gameplay layer.

This is a **game-side acceleration structure**, not world infrastructure. The
question it answers — *which live, hostile, non-corpse actor is nearest this
one?* — is combat and perception policy, and the state it answers from (team,
faction, liveness, corpse-hood) is MiniWind's. None of it belongs in Fio, and
none of it is upstreamed.

What it no longer does
----------------------
It used to classify simulation tiers as well, once per logic tick, by measuring
every live actor's distance from the player. That is the per-frame global scan a
large persistent world cannot afford: its cost scales with the cast, not with
what is near enough to matter.

Tiers now come from Fio's Big World plugin, which assigns them to *cells* on the
crossings that already recompute residency and stamps the entities of the cells
whose band changed. So the work is proportional to how far the player moved, and
this class simply *reads* the stamp:

.. code-block:: text

    Big World cell residency  →  _sim_tier stamp  →  WorldIndex.tier_of()
                                                  →  MiniWind scheduling

:meth:`WorldIndex.rebuild` therefore takes no radii and computes no tiers. It
snapshots positions, teams and liveness into reusable buffers, and reads the
tier Fio already decided.

A tier is cell-granular, so it is conservative by up to one cell. Where MiniWind
wants a sharper line than that it draws its own, with :meth:`rows_near` — which
is exactly the right division: Fio stops a million dormant objects from being
considered, MiniWind decides the metre at which an NPC stops looking around.

What it still provides
----------------------
* Contiguous NumPy arrays of every actor's position, team id and liveness,
  rebuilt in a single pass per logic tick into **reusable buffers** — no
  per-frame array construction and no Python/NumPy round-tripping per actor.
* Vectorised radius queries (:meth:`WorldIndex.rows_near`,
  :meth:`WorldIndex.nearest`) over 512-unit cell bins that share Fio's cell
  convention exactly (:mod:`engine.spatial`), so an index cell and a Big World
  cell cover the same patch of world.
* Team-name interning and :meth:`team_relation_table`, so a faction predicate is
  called once per distinct team rather than once per actor pair.
* :meth:`derived`, so the game layer can memoise its own per-row classifications
  for a tick.

Callers hold row indices, never copies: :attr:`WorldIndex.actors` maps a row
back to the live object. Nothing here mutates an actor except
:meth:`mark_dead`.

Dependency-light on purpose — NumPy only, no Qt/GL/glm — so it imports in the
editor, the standalone player and headless tests alike.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

# One grid convention across the engine: Fio's collision grid, Big World's cell
# streaming, the renderer's region cull and this index all address cells through
# engine/spatial.py, so cell (3, -2) means the same patch of ground to every one
# of them. The tier names come from there too — Fio defines what a tier *means*;
# what MiniWind does at each one is decided in game/runtime.py.
from .spatial import (CELL_SIZE, PARKED_DISABLED_KEY, PARKED_HIDDEN_KEY,
                      TIER_NEAR, tier_of as _stamped_tier)


def _is_parked(props: dict) -> bool:
    """Whether Big World has parked this actor — not whether it is hidden.

    The engine's parking markers are what separate "the streamer put this away"
    from "the mapper hid it" or "map logic disabled it". Only the first means
    the actor is absent from the world.
    """
    return PARKED_HIDDEN_KEY in props or PARKED_DISABLED_KEY in props

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
        "px", "pz", "py", "alive", "dead", "team_ids",
        "team_names", "_team_of_name", "_bins", "_binned",
        "_row_of", "_derived", "authoritative",
    )

    def __init__(self, cell_size: float = CELL_SIZE):
        self.cell_size = float(cell_size)
        self.actors: List = []
        self.n = 0
        #: Kept for callers that ask whether relevance information exists.
        #: It always does now: Big World stamps a tier on every entity it
        #: streams, and an entity nobody stamped reads TIER_NEAR, so "no rows"
        #: means *nothing is nearby* rather than *we do not know*. The old
        #: "there was no focus point this tick" case cannot arise — this index
        #: no longer takes one.
        self.authoritative = True
        self._cap = 0
        self.px = np.empty(0, dtype=np.float64)
        self.py = np.empty(0, dtype=np.float64)
        self.pz = np.empty(0, dtype=np.float64)
        self.alive = np.empty(0, dtype=bool)
        #: Per-row "this actor is a corpse" flag. Distinct from ``not alive``,
        #: which also covers an actor the streamer has parked: a corpse is
        #: lootable and targetable-by-some-systems, a parked actor is not there.
        self.dead = np.empty(0, dtype=bool)
        self.team_ids = np.empty(0, dtype=np.int32)
        #: Distinct team strings in scene order; ``team_ids`` indexes into it.
        self.team_names: List[str] = []
        self._team_of_name: Dict[str, int] = {}
        self._bins: Dict[tuple, np.ndarray] = {}
        self._binned = False
        #: ``id(actor) -> row``, built on first use. Most ticks only move
        #: actors and never ask, so building it in every rebuild was a dict of
        #: N entries per tick that nothing read.
        self._row_of: Optional[Dict[int, int]] = None
        self._derived: Dict[str, np.ndarray] = {}

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
        self._cap = cap

    def rebuild(self, actors: Sequence) -> None:
        """Snapshot *actors* into the index for this tick.

        One Python pass over the actor list fills the coordinate, team and
        liveness buffers. Positions are frozen here, so every consumer in a tick
        agrees about where everyone is.

        No radii, no focus point and no tier classification: relevance is
        decided by Big World on cell crossings and read back through
        :meth:`tier_of`. An actor the streamer has parked is not alive for query
        purposes — it is not in the world right now — which is read from the
        engine's parking markers rather than from ``hidden``/``disabled``, so a
        mapper-hidden actor is not mistaken for a parked one.
        """
        n = len(actors)
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
        for i in range(n):
            a = actors[i]
            p = a.pos
            px[i] = p[0]
            py[i] = p[1]
            pz[i] = p[2]
            props = a.properties
            is_dead = bool(props.get("dead"))
            parked = _is_parked(props)
            dead[i] = is_dead
            alive[i] = not (is_dead or parked)
            team = props.get("team") or props.get("faction") or ""
            tid = team_of_name.get(team)
            if tid is None:
                tid = len(team_names)
                team_names.append(team)
                team_of_name[team] = tid
            team_ids[i] = tid

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
        """The simulation tier Big World gave *actor*.

        Read straight off the actor, not out of a local array: the stamp is the
        contract, it survives a rebuild, and an actor nobody has stamped reads
        :data:`~engine.spatial.TIER_NEAR` — full simulation, which is what an
        ordinary map, the editor and a headless test all want.
        """
        return _stamped_tier(actor, TIER_NEAR)

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
        """Rows whose simulation tier is exactly *tier*.

        Built from the stamps on demand rather than kept as a column: tiers
        change on cell crossings, not per tick, so most ticks would maintain a
        column nothing reads.
        """
        n = self.n
        if n == 0:
            return _NO_ROWS
        actors = self.actors
        return np.fromiter(
            (i for i in range(n) if _stamped_tier(actors[i], TIER_NEAR) == tier),
            dtype=np.intp)

    def counts_by_tier(self) -> Dict[int, int]:
        """``{tier: count}`` — the numbers a perf overlay wants."""
        counts: Dict[int, int] = {}
        for a in self.actors[:self.n]:
            t = _stamped_tier(a, TIER_NEAR)
            counts[t] = counts.get(t, 0) + 1
        return counts
