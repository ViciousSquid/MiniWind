"""
Crabs come for the dead.

A body blown apart near water brings crabs out of it: more the bigger the
body (a hen draws a couple, a man six, a bear a swarm). They scuttle up
from the water's edge, crowd the pieces and eat them -- bite by bite, chunks
gone out of each piece until nothing is left (:meth:`GoreFX.bite`) -- then
scuttle off out of sight and are gone. A brief feeding frenzy: only with
gibs, only near water.

"Near water" means water you can see: a point within :data:`REACH` of the
remains where a water surface lies above the ground (so the sea brush under
the whole land does not count). Crabs walk sideways, as crabs do: each faces
across the way it is going.

The crabs are ordinary creatures for the moment they live (they can be
fought, and are passive unless struck), marked ``_frenzy`` so a save never
keeps them: one restored mid-feast is simply gone.
"""

from __future__ import annotations

import math
import uuid

from . import fio
from .facing import face_heading

#: How far from the remains water may be and still bring crabs.
REACH = 650.0
#: Crabs per unit of body mass (a person is 1.0), and the bounds.
CRABS_PER_MASS = 6.0
MIN_CRABS, MAX_CRABS = 2, 12
#: Frenzy crabs alive at once, at most, across every feast.
MAX_LIVE = 24
#: The pieces within this of the remains are what the crabs come for, and
#: they are held (not left to fade) this long while they do.
FEAST_RADIUS = 320.0
HOLD_SECONDS = 45.0
#: Scuttling speeds (world units a second), and how near is "at" a piece.
SPEED = 170.0
LEAVE_SPEED = 240.0
ARRIVE = 26.0
#: Seconds between one crab's bites, and how many crabs crowd one piece.
BITE_EVERY = 0.35
PER_PIECE = 2
#: Seconds a crab waits in the water before it comes out (staggered).
EMERGE = (0.0, 2.2)
#: When the crabs are done: off they go, and they are gone once this far
#: from the player (out of sight) or after this many seconds of leaving.
GONE_DISTANCE = 1500.0
LEAVE_SECONDS = 12.0
#: A feast that has gone on this long ends anyway.
FEAST_SECONDS = 50.0


class CrabFrenzy:
    def __init__(self, rng):
        self.rng = rng
        self.feasts = []          # {"pos", "pieces", "crabs": [crab state], "age"}
        self._water = None
        self._water_key = None

    # -- where the water is -------------------------------------------------------
    def _water_rects(self, session):
        """``[(x0, z0, x1, z1, top)]`` of the map's water brushes (cached)."""
        state = getattr(session.logic, "editor_state", None)
        brushes = getattr(state, "brushes", None) or []
        key = (id(brushes), len(brushes))
        if key != self._water_key:
            from engine.constants import is_water_brush
            rects = []
            for b in brushes:
                try:
                    if not is_water_brush(b):
                        continue
                    (x, y, z), (sx, sy, sz) = b["pos"], b["size"]
                except (KeyError, TypeError, ValueError):
                    continue
                rects.append((x - sx / 2, z - sz / 2, x + sx / 2, z + sz / 2, y + sy / 2))
            self._water, self._water_key = rects, key
        return self._water

    def water_near(self, session, pos):
        """The nearest point of visible water within :data:`REACH` of *pos*,
        ``(x, top, z)``, or None."""
        rects = self._water_rects(session)
        if not rects:
            return None
        best = None
        for radius in (0.0, REACH * 0.25, REACH * 0.5, REACH * 0.75, REACH):
            for k in range(1 if radius == 0.0 else 16):
                a = k * math.tau / 16
                x, z = pos[0] + math.cos(a) * radius, pos[2] + math.sin(a) * radius
                for x0, z0, x1, z1, top in rects:
                    if not (x0 <= x <= x1 and z0 <= z <= z1):
                        continue
                    ground = fio.ground_height(session.logic, x, z)
                    if ground is None or ground < top - 2.0:
                        d = math.hypot(x - pos[0], z - pos[2])
                        if best is None or d < best[0]:
                            best = (d, (x, top, z))
            if best is not None:
                return best[1]
        return None

    # -- a body is blown apart ----------------------------------------------------------
    def gibbed(self, session, pos, mass=1.0) -> int:
        """Remains at *pos* (a body of *mass*): if water is near, crabs come.
        Returns how many."""
        live = sum(len(f["crabs"]) for f in self.feasts)
        room = MAX_LIVE - live
        if room <= 0:
            return 0
        water = self.water_near(session, pos)
        if water is None:
            return 0
        pieces = session.gore.hold(pos, FEAST_RADIUS, HOLD_SECONDS)
        if not pieces:
            return 0
        count = int(round(float(mass) * CRABS_PER_MASS))
        count = max(MIN_CRABS, min(MAX_CRABS, count, room))
        crabs = []
        for i in range(count):
            # Out of the water's edge, spread along it.
            ox, oz = self.rng.uniform(-110, 110), self.rng.uniform(-110, 110)
            spot = [water[0] + ox, water[1], water[2] + oz]
            thing = _make_crab(session, spot)
            if thing is None:
                continue
            crabs.append({"thing": thing, "wait": self.rng.uniform(*EMERGE), "piece": None,
                          "bite": 0.0, "leaving": None, "jitter": (self.rng.uniform(-14, 14),
                                                                 self.rng.uniform(-14, 14))})
        if not crabs:
            return 0
        things = fio.things(session.logic)
        things.extend(c["thing"] for c in crabs)
        _rebuild(session)
        self.feasts.append({"pos": tuple(pos), "pieces": pieces, "crabs": crabs, "age": 0.0})
        return len(crabs)

    # -- every tick -------------------------------------------------------------------
    def update(self, session, dt) -> None:
        if not self.feasts:
            return
        dt = max(0.0, min(0.25, float(dt)))
        gone = []
        player = session._player_pos()
        for feast in self.feasts:
            feast["age"] += dt
            present = {id(p) for p in session.gore.pieces}
            feast["pieces"] = [p for p in feast["pieces"] if id(p) in present]
            done = not feast["pieces"] or feast["age"] > FEAST_SECONDS
            for crab in feast["crabs"]:
                if self._step(session, feast, crab, dt, done, player):
                    gone.append((feast, crab))
        if gone:
            things = fio.things(session.logic)
            for feast, crab in gone:
                feast["crabs"].remove(crab)
                try:
                    things.remove(crab["thing"])
                except ValueError:
                    pass
            _rebuild(session)
        self.feasts = [f for f in self.feasts if f["crabs"]]

    def _step(self, session, feast, crab, dt, done, player) -> bool:
        """One tick of one crab; True when it has gone."""
        thing = crab["thing"]
        p = thing.properties
        if p.get("dead"):
            return False                  # killed: a body like any other
        if crab["wait"] > 0.0:
            crab["wait"] -= dt
            return False
        if done and crab["leaving"] is None:
            crab["leaving"] = 0.0
        if crab["leaving"] is not None:
            crab["leaving"] += dt
            # Away from the player, out of sight.
            ax, az = thing.pos[0] - (player[0] if player else feast["pos"][0]), \
                thing.pos[2] - (player[2] if player else feast["pos"][2])
            far = math.hypot(ax, az)
            if far >= GONE_DISTANCE or crab["leaving"] >= LEAVE_SECONDS:
                return True
            if far < 1e-3:
                ax, az, far = 1.0, 0.0, 1.0
            self._walk(session, thing, ax / far, az / far, LEAVE_SPEED * dt, dt)
            return False
        piece = crab["piece"]
        if piece is None or not any(piece is q for q in feast["pieces"]):
            piece = crab["piece"] = self._choose(feast, thing)
            if piece is None:
                return False
        tx, tz = _piece_xz(session, piece)
        tx += crab["jitter"][0]
        tz += crab["jitter"][1]
        dx, dz = tx - thing.pos[0], tz - thing.pos[2]
        dist = math.hypot(dx, dz)
        if dist > ARRIVE:
            self._walk(session, thing, dx / dist, dz / dist, min(dist, SPEED * dt), dt)
            return False
        crab["bite"] -= dt
        if crab["bite"] <= 0.0:
            crab["bite"] = BITE_EVERY * self.rng.uniform(0.7, 1.3)
            if session.gore.bite(piece):
                crab["piece"] = None
        return False

    def _choose(self, feast, thing):
        """The nearest piece of the feast fewer than :data:`PER_PIECE` crabs
        are already on."""
        taken = {}
        for c in feast["crabs"]:
            if c["piece"] is not None:
                taken[id(c["piece"])] = taken.get(id(c["piece"]), 0) + 1
        free = [p for p in feast["pieces"] if taken.get(id(p), 0) < PER_PIECE]
        if not free:
            free = feast["pieces"]
        if not free:
            return None
        return min(free, key=lambda p: math.hypot(p["rest_pose"][0] - thing.pos[0],
                                                   p["rest_pose"][2] - thing.pos[2])
                   if p.get("rest") is not None else 1e9)

    @staticmethod
    def _walk(session, thing, ux, uz, step, dt):
        nx, nz = thing.pos[0] + ux * step, thing.pos[2] + uz * step
        mover = getattr(session, "_step_to", None)
        if mover is None or not mover(thing, nx, nz):
            thing.pos[0], thing.pos[2] = nx, nz
        # Sideways, as crabs go: facing across the way it walks.
        face_heading(thing, uz, -ux, dt)

    # -- saves --------------------------------------------------------------------------
    def purge(self, session) -> int:
        """Remove frenzy crabs left in the world (a save restored mid-feast)."""
        things = fio.things(session.logic)
        stale = [t for t in things if getattr(t, "properties", {}).get("_frenzy")]
        for t in stale:
            things.remove(t)
        self.feasts = []
        if stale:
            _rebuild(session)
        return len(stale)


def _piece_xz(session, piece):
    if piece.get("rest") is not None:
        return piece["rest_pose"][0], piece["rest_pose"][2]
    x, _y, z = session.gore.position(piece)
    return x, z


def _make_crab(session, pos):
    """A frenzy crab at *pos*: a Creature with a crab's head, half size."""
    try:
        from .entities import Creature
        import game.rpg.heads as heads
    except Exception:
        return None
    head = heads.animal_head("crab", session.rng)
    props = {"npc_role": "crab", "name": "Crab", "display_name": "Crab",
             "id": "crab-" + uuid.uuid4().hex, "aggression": "passive",
             "roam": False, "respawn": False, "_frenzy": True}
    if head and head != heads.PLACEHOLDER_HEAD:
        path = heads.any_head_path(head)
        size = heads.size_for(props, head)
        props.update(head=head, custom_idle=path, custom_shoot=path,
                     sprite_width=size, sprite_height=size)
    try:
        return Creature(pos=list(pos), properties=props)
    except Exception:
        return None


def _rebuild(session):
    try:
        fio.rebuild_entity_caches(session.logic)
    except Exception:
        pass
