"""
Farmers at work: reaping the wheat with a scythe and tending the animals.

By day (:data:`WORK_HOURS`) a farmer on a WORKING schedule entry is visibly
busy instead of standing at a marker:

* **reaping** -- walking the nearest wheat field row by row (read off the
  terrain's biome map), scythe in hand, swinging it every
  :data:`SWING_EVERY` seconds, gathering one wheat per stroke in a field;
* **tending** -- going to the nearest sheep, cow or hen and working beside
  it with a pitchfork, collecting any milk a tended cow has produced.

Tasks alternate through the day. The swing uses the same ``is_shooting`` pulse
every weapon overlay animates from (game/held_weapons.py), without striking a
combat blow. Dusk puts the tool away and hands the farmer
back to the ordinary schedule. Threats and appraisal run before this, so a
farmer still flees or fights as before.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

#: Roles that farm.
FARM_ROLES = ("farmer", "farmhand", "peasant")
#: Daylight working hours (game clock).
WORK_HOURS = (7.0, 18.5)
#: How far from their work spot a farmer looks for wheat, and for animals.
FIELD_SEARCH = 2600.0
HERD_SEARCH = 1800.0
#: Wheat coverage that counts as standing crop.
FIELD_WHEAT = 0.6
#: Field rows are this far apart; a row's points this far apart.
ROW_SPACING = 160.0
ROW_STEP = 140.0
MAX_ROW_POINTS = 48
#: How long a reaping or tending spell lasts (game hours).
REAP_HOURS = 1.5
TEND_HOURS = 0.75
#: The scythe's swing (seconds between strokes, and how long one is held),
#: and the pitchfork's slower work.
SWING_EVERY = 1.2
SWING_HOLD = 0.3
FORK_EVERY = 2.4
#: How near counts as arrived (at a row point, at an animal).
ARRIVE = 70.0
TEND_DISTANCE = 75.0
LIVESTOCK = ("sheep", "cow", "hen", "pig", "goat")
SCYTHE = "scythe"
PITCHFORK = "pitchfork"
REAPING = "REAPING"
TENDING = "TENDING"


def is_farmer(props) -> bool:
    return str(props.get("npc_role", "")).lower() in FARM_ROLES


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[-1] - b[-1])


def field_rows(terrain, centre) -> List[List[float]]:
    """A path back and forth across the wheat nearest *centre* ``(x, z)``:
    row points of standing crop, the rows walked in alternating directions.
    Empty when there is no field within :data:`FIELD_SEARCH`."""
    if terrain is None or getattr(terrain, "biome_map", None) is None:
        return []
    import numpy as np
    from engine import terrain_biomes as tb
    if terrain.biome_map.shape[2] <= tb.WHEAT:
        return []
    cx, cz = float(centre[0]), float(centre[-1])
    g = np.arange(-FIELD_SEARCH, FIELD_SEARCH + 1, ROW_STEP)
    X, Z = np.meshgrid(cx + g, cz + g)
    X, Z = X.ravel(), Z.ravel()
    w = terrain.biome_weights_batch(X, Z)[:, tb.WHEAT]
    ok = w >= FIELD_WHEAT
    if not ok.any():
        return []
    X, Z = X[ok], Z[ok]
    # The field nearest the work spot: crop within reach of its nearest point.
    d = np.hypot(X - cx, Z - cz)
    nx, nz = X[np.argmin(d)], Z[np.argmin(d)]
    near = np.hypot(X - nx, Z - nz) <= 900.0
    X, Z = X[near], Z[near]
    rows: Dict[int, List] = {}
    for x, z in zip(X.tolist(), Z.tolist()):
        rows.setdefault(int(round(z / ROW_SPACING)), []).append(x)
    path = []
    for k, key in enumerate(sorted(rows)):
        xs = sorted(set(rows[key]), reverse=bool(k % 2))
        path += [[x, key * ROW_SPACING] for x in xs]
    if len(path) > MAX_ROW_POINTS:
        step = len(path) / MAX_ROW_POINTS
        path = [path[int(i * step)] for i in range(MAX_ROW_POINTS)]
    return path


def stop(props) -> None:
    """Put the tool away and leave the farm routine."""
    tool = props.pop("_farm_tool", None)
    if tool and props.get("_active_weapon") == tool:
        props.pop("_active_weapon", None)
    for key in ("_farm_task", "_farm_work", "_farm_swing"):
        props.pop(key, None)
    if props.get("_farm_swinging"):
        props.pop("_farm_swinging", None)
        props["is_shooting"] = False


class FarmWork:
    """Drives farmers' working day for the session."""

    def __init__(self, on_collect=None):
        #: id(farmer) -> the animal being tended (a scene thing).
        self._animal: Dict[int, object] = {}
        #: Optional notification after an item is added: (actor, item_id, qty).
        self._on_collect = on_collect

    # ------------------------------------------------------------ deciding
    def drive(self, session, npc) -> bool:
        """Set *npc*'s destination for this decision; True when farm work has
        it, False to fall back on the ordinary schedule."""
        p = npc.properties
        clock = session.clock
        hour = float(clock.hour)
        if not (WORK_HOURS[0] <= hour < WORK_HOURS[1]) or npc.pos is None:
            stop(p)
            return False
        now = float(clock.day) * 24.0 + hour
        task = p.get("_farm_task")
        if not task or now >= float(task.get("until", 0.0)) or now < float(task.get("since", 0.0)):
            task = self._choose(session, npc, now, task)
            if task is None:
                stop(p)
                return False
        if task["kind"] == "reap":
            return self._reap(npc, task)
        return self._tend(session, npc, task)

    def _choose(self, session, npc, now, last) -> Optional[Dict]:
        p = npc.properties
        anchor = self._work_spot(session, npc)
        rows = p.get("_farm_rows")
        if rows is None:
            from . import fio
            rows = field_rows(fio.terrain(session.logic), anchor)
            p["_farm_rows"] = rows
        animal = self._nearest_animal(session, anchor)
        # Alternate: reap, then tend, then reap again, as there is work.
        want_reap = not last or last.get("kind") != "reap"
        if rows and (want_reap or animal is None):
            # Start on the row point nearest where they stand.
            i = min(range(len(rows)), key=lambda k: _dist(npc.pos, rows[k]))
            task = dict(kind="reap", i=i, since=now, until=now + REAP_HOURS)
        elif animal is not None:
            self._animal[id(npc)] = animal
            task = dict(kind="tend", since=now, until=now + TEND_HOURS)
        else:
            return None
        p["_farm_task"] = task
        return task

    def _work_spot(self, session, npc):
        p = npc.properties
        try:
            spot = session._resolve_location(npc, "work")
        except Exception:
            spot = None
        return spot if spot is not None else (p.get("home") or list(npc.pos))

    def _nearest_animal(self, session, anchor):
        best, best_d = None, HERD_SEARCH
        for t in session._things_of_type("creature"):
            p = t.properties
            if p.get("dead") or p.get("hidden") or t.pos is None:
                continue
            if str(p.get("npc_role", "")).lower() not in LIVESTOCK:
                continue
            d = _dist(t.pos, anchor)
            if d < best_d:
                best, best_d = t, d
        return best

    def _reap(self, npc, task) -> bool:
        p = npc.properties
        rows = p.get("_farm_rows") or []
        if not rows:
            return False
        i = int(task.get("i", 0)) % len(rows)
        if _dist(npc.pos, rows[i]) <= ARRIVE:
            i = (i + 1) % len(rows)
            task["i"] = i
        target = rows[i]
        p["_dest"] = [target[0], npc.pos[1], target[1]]
        p["sched_state"] = REAPING
        p["_farm_work"] = "reap"
        p["_farm_tool"] = SCYTHE
        p["_active_weapon"] = SCYTHE
        return True

    def _tend(self, session, npc, task) -> bool:
        p = npc.properties
        animal = self._animal.get(id(npc))
        if animal is None or animal.properties.get("dead") or animal.pos is None:
            p.pop("_farm_task", None)
            return False
        p["sched_state"] = TENDING
        p["_farm_work"] = "tend"
        p["_farm_tool"] = PITCHFORK
        p["_active_weapon"] = PITCHFORK
        d = _dist(npc.pos, animal.pos)
        if d > TEND_DISTANCE:
            # Stand beside it, on the farmer's side.
            k = (d - TEND_DISTANCE * 0.8) / max(d, 1e-6)
            p["_dest"] = [npc.pos[0] + (animal.pos[0] - npc.pos[0]) * k, npc.pos[1],
                          npc.pos[2] + (animal.pos[2] - npc.pos[2]) * k]
        else:
            p.pop("_dest", None)
            p["_facing"] = math.atan2(animal.pos[0] - npc.pos[0], animal.pos[2] - npc.pos[2])
            if str(animal.properties.get("npc_role", "")).lower() == "cow":
                session.collect_produce(npc, animal, "milk")
        return True

    # ------------------------------------------------------------- swinging
    def update(self, delta, actors, terrain=None) -> None:
        """Swing the scythe (and work the fork) of farmers at it, near the
        player. Each reaping stroke in a wheat field gathers one wheat."""
        for t in actors:
            p = t.properties
            work = p.get("_farm_work")
            if not work or p.get("dead") or p.get("hidden"):
                continue
            every = SWING_EVERY if work == "reap" else FORK_EVERY
            clock = float(p.get("_farm_swing", 0.0)) + float(delta)
            if p.get("_farm_swinging") and clock >= SWING_HOLD:
                p["is_shooting"] = False
                p["_farm_swinging"] = False
            if clock >= every:
                clock = 0.0
                p["is_shooting"] = True
                p["_farm_swinging"] = True
                if work == "reap" and p.get("_active_weapon") == SCYTHE and is_farmer(p):
                    self._harvest(t, terrain)
            p["_farm_swing"] = clock

    def _harvest(self, npc, terrain) -> None:
        """Gather only where the farmer stands in a painted wheat field."""
        if npc.pos is None or terrain is None or getattr(terrain, "biome_map", None) is None:
            return
        from engine import terrain_biomes as tb
        if terrain.biome_map.shape[2] <= tb.WHEAT:
            return
        weights = terrain.biome_weights_batch([npc.pos[0]], [npc.pos[2]])
        if weights[0, tb.WHEAT] * tb.bare_keep(weights)[0] < FIELD_WHEAT:
            return
        from .rpg import inventory, items
        inventory.add_item(inventory.get_inventory(npc), items.make("wheat"))
        if self._on_collect is not None:
            self._on_collect(npc, "wheat", 1)
