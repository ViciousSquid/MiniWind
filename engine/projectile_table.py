"""Persistent structure-of-arrays storage for live monster projectiles.

Projectile simulation state is numeric and contiguous. There are no per-projectile
Python dictionaries: the logic thread owns position, velocity, lifetime, distance,
owner, damage, range and tag as NumPy columns.

A projectile spawned with callbacks (:meth:`ProjectileStore.add` with
``on_hit``/``on_impact``) carries a non-zero ``tag``; the callbacks live in
:attr:`ProjectileStore.hooks` under it until the projectile is consumed,
expires or the store is cleared. Untagged projectiles cost nothing extra.
"""

from __future__ import annotations

import numpy as np

from .soa import grow_soa_arrays
from .monster_constants import MONSTER_PROJECTILE_MAX_DIST


class ProjectileStore:
    """Dense SoA store for monster projectiles."""

    __slots__ = (
        "pos", "vel", "lifetime", "distance", "owner_id", "damage",
        "max_dist", "tag", "hooks", "_next_tag",
        "_capacity", "_count",
    )

    def __init__(self, capacity=16):
        self._capacity = max(1, int(capacity))
        self._count = 0
        self.pos = np.empty((self._capacity, 3), dtype=np.float32)
        self.vel = np.empty((self._capacity, 3), dtype=np.float32)
        self.lifetime = np.empty(self._capacity, dtype=np.float32)
        self.distance = np.empty(self._capacity, dtype=np.float32)
        self.owner_id = np.empty(self._capacity, dtype=np.int64)
        self.damage = np.empty(self._capacity, dtype=np.float32)
        #: Distance after which the projectile is spent.
        self.max_dist = np.empty(self._capacity, dtype=np.float32)
        #: 0, or the key of the projectile's callbacks in :attr:`hooks`.
        self.tag = np.empty(self._capacity, dtype=np.int64)
        #: ``tag -> (on_hit, on_impact)`` for the live tagged projectiles.
        self.hooks = {}
        self._next_tag = 1

    def __len__(self):
        return self._count

    @property
    def count(self):
        return self._count

    def _ensure_capacity(self, required):
        if required <= self._capacity:
            return
        self._capacity, (
            self.pos,
            self.vel,
            self.lifetime,
            self.distance,
            self.owner_id,
            self.damage,
            self.max_dist,
            self.tag,
        ) = grow_soa_arrays(
            required,
            self._capacity,
            self.pos,
            self.vel,
            self.lifetime,
            self.distance,
            self.owner_id,
            self.damage,
            self.max_dist,
            self.tag,
        )

    def add(self, pos, vel, owner_id, damage, lifetime, max_dist=None,
            on_hit=None, on_impact=None):
        """Add one projectile; returns its row.

        *max_dist* is its range (``MONSTER_PROJECTILE_MAX_DIST`` when None).
        ``on_hit(monster)``, when given, resolves a hit on a monster instead of
        the flat *damage*; ``on_impact(pos, target)`` is told where the
        projectile was consumed (*target* the monster, or None for a wall).
        """
        i = self._count
        self._ensure_capacity(i + 1)
        self.pos[i] = pos
        self.vel[i] = vel
        self.owner_id[i] = int(owner_id)
        self.damage[i] = float(damage)
        self.lifetime[i] = float(lifetime)
        self.distance[i] = 0.0
        self.max_dist[i] = (MONSTER_PROJECTILE_MAX_DIST if max_dist is None
                            else float(max_dist))
        tag = 0
        if on_hit is not None or on_impact is not None:
            tag = self._next_tag
            self._next_tag += 1
            self.hooks[tag] = (on_hit, on_impact)
        self.tag[i] = tag
        self._count = i + 1
        return i

    def hooks_of(self, row):
        """``(on_hit, on_impact)`` of the projectile in *row* (Nones if untagged)."""
        tag = int(self.tag[row])
        return self.hooks.get(tag, (None, None)) if tag else (None, None)

    def add_batch(self, positions, velocities, owners, damages, lifetimes):
        positions = np.asarray(positions, dtype=np.float32)
        velocities = np.asarray(velocities, dtype=np.float32)
        owners = np.asarray(owners, dtype=np.int64)
        damages = np.asarray(damages, dtype=np.float32)
        lifetimes = np.asarray(lifetimes, dtype=np.float32)
        n = len(positions)
        if positions.shape != (n, 3) or velocities.shape != (n, 3):
            raise ValueError("projectile positions and velocities must be (N, 3)")
        if any(len(values) != n for values in (owners, damages, lifetimes)):
            raise ValueError("projectile batch columns must have equal length")
        if not n:
            return
        start = self._count
        stop = start + n
        self._ensure_capacity(stop)
        self.pos[start:stop] = positions
        self.vel[start:stop] = velocities
        self.owner_id[start:stop] = owners
        self.damage[start:stop] = damages
        self.lifetime[start:stop] = lifetimes
        self.distance[start:stop] = 0.0
        self.max_dist[start:stop] = MONSTER_PROJECTILE_MAX_DIST
        self.tag[start:stop] = 0
        self._count = stop

    def clear(self):
        self._count = 0
        self.hooks.clear()

    def compact(self, keep, pos, vel, lifetime, distance):
        keep = np.asarray(keep, dtype=np.intp)
        n = int(keep.size)
        if n:
            self.pos[:n] = np.take(pos, keep, axis=0)
            self.vel[:n] = np.take(vel, keep, axis=0)
            self.lifetime[:n] = np.take(lifetime, keep)
            self.distance[:n] = np.take(distance, keep)
            self.owner_id[:n] = np.take(self.owner_id[:self._count], keep)
            self.damage[:n] = np.take(self.damage[:self._count], keep)
            self.max_dist[:n] = np.take(self.max_dist[:self._count], keep)
        if self.hooks:
            tags = self.tag[:self._count]
            kept = set(np.take(tags, keep).tolist()) if n else set()
            for tag in [t for t in self.hooks if t not in kept]:
                del self.hooks[tag]
        if n:
            self.tag[:n] = np.take(self.tag[:self._count], keep)
        self._count = n
