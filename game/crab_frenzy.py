"""
Crabs come for the dead.

A body blown apart near water brings crabs out of it: more the bigger the
body (a hen draws a couple, a man six, a bear twelve). Bodies falling by a
feast already going join it, up to :data:`MAX_LIVE` crabs: crabs are a
nuisance, and a real danger only when something huge, or many things, die
by the water together. They scuttle up
from the water's edge, crowd the pieces and eat them -- bite by bite, chunks
gone out of each piece until nothing is left (:meth:`GoreFX.bite`) -- then
scuttle off out of sight and are gone. A brief feeding frenzy: only with
gibs, only near water.

"Near water" means water you can see: a point within :data:`REACH` of the
remains where a water surface lies above the ground (so the sea brush under
the whole land does not count). Crabs walk sideways, as crabs do: each faces
across the way it is going.

While they feed, crabs **attack anything near the feast** -- the player,
people, any animal but another crab: the nearest within :data:`AGGRO` of a
crab is swarmed and nipped, and never chased further than :data:`LEASH`
from where the chase began. One nip is
nothing (:data:`NIP_DAMAGE`); six crabs nipping together are a real threat.
Leaving crabs no longer bite. Nips go through the engine's own damage paths
(the player's armour and the game's mitigation apply; a bitten villager or
wolf fights back).

The crabs are ordinary creatures for the moment they live (they can be
fought), marked ``_frenzy`` so a save never keeps them: one restored
mid-feast is simply gone.
"""

from __future__ import annotations

import math
import uuid

from . import fio
from .facing import face_heading

#: How far from the remains water may be and still bring crabs.
REACH = 650.0
#: Crabs per unit of body mass (a person is 1.0), and the bounds for one
#: body: a hen draws a couple, a person six, a bear twelve, anything huge
#: twenty.
CRABS_PER_MASS = 6.0
MIN_CRABS, MAX_CRABS = 2, 20
#: Frenzy crabs alive at once, at most: the ceiling when many die near water
#: together (or something enormous does) -- a real danger.
MAX_LIVE = 32
#: Bodies blown apart within this of a feast still going join it: its crabs
#: are joined by more, and the frenzy grows instead of starting over.
MERGE = 450.0
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
#: In the frenzy: anything within AGGRO of a crab is attacked, and never
#: chased further than LEASH from where the chase began; a nip reaches
#: NIP_RANGE and does
#: NIP_DAMAGE (tiny alone). Each crab nips once in every NIP_PERIOD, at a
#: random moment in it -- a swarm's bites fall all through the second, not
#: together -- and not at all if what it is after is out of reach then.
AGGRO = 150.0
LEASH = 150.0
NIP_RANGE = 52.0
NIP_DAMAGE = 2
NIP_PERIOD = 1.0
#: How often the feast looks round for something to attack (seconds).
LOOK_EVERY = 0.25


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
        # Another body by a feast still going: the frenzy grows.
        joined = next((f for f in self.feasts if f["pieces"]
                       and math.hypot(f["pos"][0] - pos[0], f["pos"][2] - pos[2]) <= MERGE), None)
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
                          "bite": 0.0, "nip_clock": 0.0, "nip_at": self.rng.random() * NIP_PERIOD,
                          "nipped": False, "leaving": None,
                          "jitter": (self.rng.uniform(-14, 14), self.rng.uniform(-14, 14))})
        if not crabs:
            return 0
        things = fio.things(session.logic)
        things.extend(c["thing"] for c in crabs)
        _rebuild(session)
        if joined is not None:
            known = {id(p) for p in joined["pieces"]}
            joined["pieces"].extend(p for p in pieces if id(p) not in known)
            joined["crabs"].extend(crabs)
            joined["age"] = min(joined["age"], FEAST_SECONDS * 0.5)   # more to eat
        else:
            self.feasts.append({"pos": tuple(pos), "pieces": pieces, "crabs": crabs, "age": 0.0,
                                "prey": [], "look": 0.0})
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
            feast["look"] -= dt
            if not done and feast["look"] <= 0.0:
                feast["look"] = LOOK_EVERY
                feast["prey"] = self._prey(session, feast, player)
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
        # Anything near the feast is attacked first. One nip a period, at
        # its own random moment in it.
        crab["nip_clock"] += dt
        if crab["nip_clock"] >= NIP_PERIOD:
            crab["nip_clock"] -= NIP_PERIOD
            crab["nip_at"] = self.rng.random() * NIP_PERIOD
            crab["nipped"] = False
        anchor = crab.get("chase_from")
        target = self._target(thing, feast["prey"], anchor)
        if target is None:
            crab["chase_from"] = None             # back to the feast
        else:
            if anchor is None:
                crab["chase_from"] = (thing.pos[0], thing.pos[2])
            tpos, victim = target
            dx, dz = tpos[0] - thing.pos[0], tpos[2] - thing.pos[2]
            dist = math.hypot(dx, dz)
            if dist > NIP_RANGE * 0.8:
                self._walk(session, thing, dx / dist, dz / dist,
                           min(dist - NIP_RANGE * 0.6, SPEED * 1.15 * dt), dt)
            if not crab["nipped"] and crab["nip_clock"] >= crab["nip_at"]:
                crab["nipped"] = True       # this period's moment: bite, or miss it
                if dist <= NIP_RANGE:
                    self._nip(session, thing, victim)
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

    def _prey(self, session, feast, player):
        """``[(pos, victim)]`` near the feast to attack: the player (victim
        None) and every living actor but a crab within :data:`LEASH`."""
        fx, fz = feast["pos"][0], feast["pos"][2]
        prey = []
        reach = FEAST_RADIUS + AGGRO
        if player is not None and not _player_dead(session) \
                and math.hypot(player[0] - fx, player[2] - fz) <= reach:
            prey.append((player, None))
        for t in fio.monster_things(session.logic):
            p = getattr(t, "properties", None) or {}
            if (p.get("dead") or p.get("hidden") or p.get("_frenzy")
                    or str(p.get("npc_role", "")).lower() == "crab"
                    or p.get("multiplayer_player")):
                continue
            pos = getattr(t, "pos", None)
            if pos is not None and math.hypot(pos[0] - fx, pos[2] - fz) <= reach:
                prey.append((pos, t))
        return prey

    @staticmethod
    def _target(thing, prey, anchor=None):
        """The nearest prey within :data:`AGGRO` of this crab -- and, once it
        is chasing, within :data:`LEASH` of where the chase began -- or None."""
        best, best_d = None, AGGRO
        for pos, victim in prey:
            if victim is not None and victim.properties.get("dead"):
                continue
            if anchor is not None and math.hypot(pos[0] - anchor[0], pos[2] - anchor[1]) > LEASH:
                continue                          # too far: never chased past the leash
            d = math.hypot(pos[0] - thing.pos[0], pos[2] - thing.pos[2])
            if d <= best_d:
                best, best_d = (pos, victim), d
        return best

    @staticmethod
    def _nip(session, crab, victim):
        """One nip: tiny alone, through the engine's own damage paths."""
        logic = session.logic
        if victim is None:
            runtime = getattr(logic, "player_runtime", None)
            triggers = getattr(logic, "trigger_runtime", None)
            if triggers is None:
                return
            if runtime is not None:
                runtime.damage_source = tuple(crab.pos)   # the damage indicator
            triggers._apply_player_damage(NIP_DAMAGE, "physical", source=crab, cause="crab")
            return
        ai = getattr(logic, "monster_ai", None)
        if ai is not None:
            ai._apply_monster_damage(victim, NIP_DAMAGE, attacker=crab)

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


def _player_dead(session) -> bool:
    runtime = getattr(session.logic, "player_runtime", None)
    return bool(getattr(runtime, "player_dead", False))


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
