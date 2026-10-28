"""
Wildlife roams.

The combat AI only moves a creature that has something to fight; the rest of
the time a wolf stood exactly where the map put it. This pass walks idle
wildlife about its home: a leg to somewhere within its range, a pause to
sniff or graze, another leg. Packs spawned together share a home, so they
drift about the same ground.

* **Who:** every creature of the ``wildlife`` faction except sheep and cows
  (they stay in their fields), and any other creature authored with
  ``roam: true``.
* **When:** only while idle -- not dead, not chasing or fighting anything, and
  (for the hostile ones) with no one to hunt in sight. The moment a wolf sees
  the player the combat AI has it again.
* **Where the world is simulated:** Big World's NEAR and ACTIVE tiers only.
  DISTANT and DORMANT creatures are not walked at all, so nothing far from
  the camera costs anything.
"""

from __future__ import annotations

import math

from engine.monster_constants import MONSTER_SIGHT_RANGE
from engine.spatial import TIER_DISTANT, TIER_NEAR

from .facing import face_heading

#: Wildlife that stays put.
STAY_PUT = frozenset({"sheep", "cow"})
#: How far a beast wanders from home, at least, by role (else roam_radius).
RANGE_BY_ROLE = {"wolf": 1100.0, "bear": 800.0, "boar": 700.0, "deer": 1000.0}
MIN_RANGE = 500.0
#: Walking pace as a fraction of the creature's move speed, and the pause
#: between legs (seconds).
PACE = 0.45
PAUSE = (2.5, 11.0)
ARRIVE = 24.0
#: Give up a leg after this many blocked steps.
BLOCKED_GIVE_UP = 12


def _roams(role, team, roam) -> bool:
    if str(role or "").lower() in STAY_PUT:
        return False
    return str(team or "").lower() == "wildlife" or bool(roam)


#: roams() answers by the raw values it reads: asked for every live creature
#: every tick, and a world has a handful of distinct (role, team) pairs.
_ROAMS = {}


def roams(props) -> bool:
    key = (props.get("npc_role", ""), props.get("faction") or props.get("team"),
           props.get("roam"))
    try:
        return _ROAMS[key]
    except KeyError:
        if len(_ROAMS) > 1024:
            _ROAMS.clear()
        found = _ROAMS[key] = _roams(*key)
        return found
    except TypeError:                    # an unhashable value: just answer
        return _roams(*key)


class Wildlife:
    def __init__(self, session):
        self.session = session

    def _creatures(self):
        s = self.session
        wi = s._world_index()
        if wi is None:
            return [t for t in s._type_buckets().get("creature", ())
                    if not t.properties.get("dead")]
        return s._live_of_type(wi, "creature")

    def update(self, delta: float) -> None:
        s = self.session
        ppos = None
        rng = s.rng
        for t in self._creatures():
            p = t.properties
            # The tier first: a dict read that turns away everything distant
            # before the string work in roams().
            if p.get("_sim_tier", TIER_NEAR) >= TIER_DISTANT:
                continue
            if p.get("dead") or p.get("hidden") or not roams(p):
                continue
            if ppos is None:
                ppos = s._player_pos() or ()
            if not self._idle(t, p, ppos):
                p.pop("_roam_dest", None)
                continue
            dest = p.get("_roam_dest")
            if dest is None:
                wait = float(p.get("_roam_wait", 0.0)) - delta
                if wait > 0.0:
                    p["_roam_wait"] = wait
                    continue
                p["_roam_dest"] = dest = self._pick(t, p, rng)
                p["_roam_blocked"] = 0
            x, z = float(t.pos[0]), float(t.pos[2])
            dx, dz = dest[0] - x, dest[1] - z
            dist = math.hypot(dx, dz)
            if dist <= ARRIVE:
                self._rest(p, rng)
                continue
            speed = float(p.get("move_speed", 90.0) or 90.0) * PACE
            step = min(speed * delta, dist)
            if s._step_to(t, x + dx / dist * step, z + dz / dist * step):
                face_heading(p, dx, dz, delta)
                p["_roam_blocked"] = 0
            else:
                blocked = int(p.get("_roam_blocked", 0)) + 1
                p["_roam_blocked"] = blocked
                if blocked >= BLOCKED_GIVE_UP:
                    self._rest(p, rng)

    @staticmethod
    def _rest(p, rng):
        p.pop("_roam_dest", None)
        p["_roam_wait"] = rng.uniform(*PAUSE)

    def _idle(self, t, p, ppos) -> bool:
        """Nothing to fight: free to wander."""
        if p.get("resurrection_used") and p.get("follow_player"):
            return False  # the follower runtime owns the raised creature's movement
        if p.get("_aggro_target") or p.get("_flee") or p.get("_bow_charge") is not None:
            return False
        if p.get("is_shooting"):
            return False
        if str(p.get("aggression")) == "hostile" and ppos:
            sight = max(float(p.get("sight_range", MONSTER_SIGHT_RANGE) or 0.0),
                        float(MONSTER_SIGHT_RANGE))
            dx, dz = t.pos[0] - ppos[0], t.pos[2] - ppos[2]
            if dx * dx + dz * dz <= (sight + 150.0) ** 2:
                return False
        return True

    @staticmethod
    def _pick(t, p, rng):
        home = p.get("home") or list(t.pos)
        role = str(p.get("npc_role", "") or "").lower()
        reach = max(MIN_RANGE, RANGE_BY_ROLE.get(role, float(p.get("roam_radius", 0.0) or 0.0)))
        a = rng.uniform(0.0, 2.0 * math.pi)
        r = reach * math.sqrt(rng.random())
        return (float(home[0]) + math.cos(a) * r, float(home[2]) + math.sin(a) * r)
