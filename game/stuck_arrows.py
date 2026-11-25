"""
Arrows stuck in barrels.

An arrow -- the player's or an archer's, a crossbow bolt as much as an arrow
-- that meets a barrel stops in it, where it struck and at the angle it flew,
and stays there poking out. It is kept in the barrel's own frame (its model
space), so it goes where the barrel goes: pushed, toppled, rolled or carried.

The player takes them back with the interact key (E): standing by a barrel
with arrows in it -- the nearest thing to interact with -- shows the prompt,
and one press pulls *every* arrow out of it, each added to the pack as the
ammunition that was loosed (plain iron arrows when that is not known).

A barrel that explodes takes its arrows with it: they are destroyed, not
dropped. The arrows are a public property of the barrel (:data:`KEY`), so a
save -- which keeps each changed Thing's position and public properties --
keeps them, and a load puts them back.

How it plugs in:

* The engine asks :class:`StuckArrows` about every projectile that might be
  caught (``LogicCombat.projectile_catcher``): ``trace`` while a fast
  projectile's path is swept, ``catch`` where it lands -- after the actors
  and explosive Props, before the walls. Only an arrow is caught: a
  projectile loosed with ``metadata={AMMO_KEY: item id}``.
* The barrel is a vertical cylinder in its model space, inside the model's
  bounds -- the shape of the oak barrel -- so an arrow sticks in its staves,
  not in the air at a corner of its box.
* ``update`` (once a game tick) carries the arrows with their barrels and
  publishes :attr:`StuckArrows.drawn` for game/ui/arrows.py. On a map with
  no stuck arrow it is one identity check and a return.
"""

from __future__ import annotations

import math

from engine.change_journal import touch

from . import fio

#: The barrel property the stuck arrows are kept in: a list of
#: ``{"item": ammo id, "at": [x, y, z], "dir": [x, y, z]}`` -- the tip and
#: the direction of flight, in the barrel's model space.
KEY = "stuck_arrows"
#: The projectile metadata key an arrow carries its ammunition's item id in.
AMMO_KEY = "ammo"
#: What an arrow is when its ammunition is not known (or no longer an item).
DEFAULT_AMMO = "iron_arrow"
#: Heard where an arrow sticks in a barrel (assets/sounds, loose or in a
#: sounds .fiopak; silent until the file is there).
ARROW_THUNK_SOUND = "thunk.wav"
#: How near (world units, on the ground) the player must stand to pull them.
PULL_REACH = 140.0
#: The most arrows one barrel holds; another pushes the oldest out.
MAX_PER_BARREL = 12
#: How far round a point barrels are looked for (their bases are filed).
SEARCH_RADIUS = 160.0
#: How far back along its flight an arrow's entry into a barrel is sought.
BACKTRACK = 128.0
#: How deep the head of a stuck arrow is buried in the wood (world units).
BURIED = 12.0


def _barrel_file():
    from engine.prop_entity import DEFAULT_MODEL_PATH
    return DEFAULT_MODEL_PATH.rsplit("/", 1)[-1]


_BARREL_FILE = None


def is_barrel(thing) -> bool:
    """Whether *thing* is a barrel: a Prop showing the barrel model."""
    global _BARREL_FILE
    props = getattr(thing, "properties", None)
    if not isinstance(props, dict) or props.get("type") != "prop":
        return False
    if props.get("render_mode", "model") != "model":
        return False
    path = str(props.get("model_path") or "").replace("\\", "/")
    if not path:
        return False
    if _BARREL_FILE is None:
        _BARREL_FILE = _barrel_file()
    from engine.prop_entity import current_model_path
    return str(current_model_path(path)).rsplit("/", 1)[-1] == _BARREL_FILE


# ------------------------------------------------------------- the geometry
def _rotate(turn, v):
    if turn is None:
        return tuple(v)
    return tuple(turn[i][0] * v[0] + turn[i][1] * v[1] + turn[i][2] * v[2]
                 for i in range(3))


def _rotate_back(turn, v):
    if turn is None:
        return tuple(v)
    return tuple(turn[0][i] * v[0] + turn[1][i] * v[1] + turn[2][i] * v[2]
                 for i in range(3))


def _unit(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if not length > 1e-9:
        return None
    return (v[0] / length, v[1] / length, v[2] / length)


def to_model(frame, point, direction=None):
    """*point* (and *direction*) in the model space of *frame* (``(lo, hi,
    scale, pos, turn)``, ExplosionRuntime.model_frame). A distance along a
    ray is the same in both spaces."""
    _lo, _hi, scale, pos, turn = frame
    rel = _rotate_back(turn, tuple(float(point[i]) - pos[i] for i in range(3)))
    local = tuple(rel[i] / scale[i] for i in range(3))
    if direction is None:
        return local, None
    d = _rotate_back(turn, tuple(float(v) for v in direction))
    return local, tuple(d[i] / scale[i] for i in range(3))


def to_world(frame, local, direction=None):
    """*local* (and a model-space *direction*, returned as a unit vector)
    back in the world, where *frame* has its model now."""
    _lo, _hi, scale, pos, turn = frame
    p = _rotate(turn, tuple(float(local[i]) * scale[i] for i in range(3)))
    point = tuple(p[i] + pos[i] for i in range(3))
    if direction is None:
        return point, None
    d = _rotate(turn, tuple(float(direction[i]) * scale[i] for i in range(3)))
    return point, _unit(d)


def ray_cylinder(frame, origin, direction, reach):
    """``(t_in, t_out)`` of the world ray from *origin* along the unit
    *direction*, within ``[0, reach]``, inside the barrel's cylinder -- its
    model's upright axis, as wide as the narrower side of its bounds and as
    tall as they are -- or None if it misses."""
    lo, hi = frame[0], frame[1]
    cx, cz = (lo[0] + hi[0]) * 0.5, (lo[2] + hi[2]) * 0.5
    r = min(hi[0] - lo[0], hi[2] - lo[2]) * 0.5
    o, d = to_model(frame, origin, direction)
    t0, t1 = 0.0, float(reach)
    if abs(d[1]) < 1e-12:
        if not lo[1] <= o[1] <= hi[1]:
            return None
    else:
        a, b = (lo[1] - o[1]) / d[1], (hi[1] - o[1]) / d[1]
        if a > b:
            a, b = b, a
        t0, t1 = max(t0, a), min(t1, b)
        if t0 > t1:
            return None
    ox, oz = o[0] - cx, o[2] - cz
    qa = d[0] * d[0] + d[2] * d[2]
    qc = ox * ox + oz * oz - r * r
    if qa < 1e-12:
        if qc > 0.0:
            return None
    else:
        qb = 2.0 * (ox * d[0] + oz * d[2])
        disc = qb * qb - 4.0 * qa * qc
        if disc < 0.0:
            return None
        root = math.sqrt(disc)
        t0 = max(t0, (-qb - root) / (2.0 * qa))
        t1 = min(t1, (-qb + root) / (2.0 * qa))
        if t0 > t1:
            return None
    return t0, t1


# ------------------------------------------------------------- the runtime
class StuckArrows:
    """The arrows stuck in the session's barrels (see the module docstring)."""

    def __init__(self, session):
        self.session = session
        #: ``((centre), heading, squash, sprite)`` per stuck arrow to draw,
        #: as last published (read by game/ui/arrows.py on the render thread).
        self.drawn = ()
        #: id(barrel) -> barrel, for every barrel with arrows in it.
        self._barrels = {}
        #: The Prop registry's list as last scanned (a new list when the
        #: world is rebuilt: a load, a streamed cell).
        self._seen = None
        self._sprites = {}

    @property
    def logic(self):
        return self.session.logic

    # -- lifecycle ----------------------------------------------------------
    def install(self) -> None:
        fio.set_projectile_catcher(self.logic, self)
        fio.set_prop_use_claim(self.logic, self.claims_use)

    def uninstall(self) -> None:
        fio.clear_projectile_catcher(self.logic, self)
        runtime = fio.prop_runtime(self.logic)
        if runtime is not None and getattr(runtime, "use_claim", None) == self.claims_use:
            runtime.use_claim = None
        self.drawn = ()
        self._barrels = {}
        self._seen = None

    # -- the barrels --------------------------------------------------------
    def _frame(self, barrel):
        explosions = fio.explosion_runtime(self.logic)
        if explosions is None:
            return None
        return explosions.model_frame(barrel)

    def _near(self, x, z, radius):
        runtime = fio.prop_runtime(self.logic)
        if runtime is None:
            return ()
        return [p for p in runtime.props_within(x, z, radius)
                if not p.properties.get("hidden") and is_barrel(p)]

    def _exploded(self):
        explosions = fio.explosion_runtime(self.logic)
        return getattr(explosions, "exploded", None) or {}

    @staticmethod
    def _ammo(store, row):
        meta = store.metadata_of(row)
        return meta.get(AMMO_KEY) if meta else None

    # -- the engine's questions (LogicCombat.projectile_catcher) ------------
    def trace(self, store, row, origin, direction, reach):
        """How far along a fast arrow's path this tick it meets a barrel, or
        None. One it starts inside (loosed from within it) does not count."""
        if not self._ammo(store, row):
            return None
        reach = float(reach)
        mx = float(origin[0]) + float(direction[0]) * reach * 0.5
        mz = float(origin[2]) + float(direction[2]) * reach * 0.5
        best = None
        for barrel in self._near(mx, mz, reach * 0.5 + SEARCH_RADIUS):
            frame = self._frame(barrel)
            if frame is None:
                continue
            hit = ray_cylinder(frame, origin, direction, reach)
            if hit is None or hit[0] <= 0.0:
                continue
            if best is None or hit[0] < best:
                best = hit[0]
        return best

    def catch(self, store, row, prop=None):
        """Stick the arrow in *row* in the barrel it is in now (or in *prop*,
        the explosive Prop it has just struck, if it is a barrel it would
        have reached). True when it stuck: the engine then drops it."""
        ammo = self._ammo(store, row)
        if not ammo:
            return False
        p = tuple(float(v) for v in store.pos[row])
        u = _unit(tuple(float(v) for v in store.vel[row]))
        if u is None:
            return False
        if prop is not None:
            candidates = (prop,) if is_barrel(prop) else ()
        else:
            candidates = self._near(p[0], p[2], SEARCH_RADIUS)
        if not candidates:
            return False
        start = (p[0] - u[0] * BACKTRACK, p[1] - u[1] * BACKTRACK, p[2] - u[2] * BACKTRACK)
        travelled = float(store.distance[row])
        best = None
        for barrel in candidates:
            frame = self._frame(barrel)
            if frame is None:
                continue
            hit = ray_cylinder(frame, start, u, BACKTRACK * 2.0)
            if hit is None:
                continue
            t_in, t_out = hit
            if prop is None and not t_in <= BACKTRACK <= t_out:
                continue                    # not in this one
            if BACKTRACK - t_in > travelled + 1.0:
                continue                    # it began inside it
            if best is None or t_in < best[0]:
                best = (t_in, barrel)
        if best is None:
            return False
        t_in, barrel = best
        tip = tuple(start[i] + u[i] * t_in for i in range(3))
        return self.stick(barrel, tip, u, ammo)

    # -- sticking -------------------------------------------------------------
    def stick(self, barrel, tip, direction, ammo) -> bool:
        """Leave an arrow of *ammo* in *barrel*, its tip at world *tip*,
        flying along *direction*; heard as a thunk where it struck."""
        frame = self._frame(barrel)
        u = _unit(direction)
        if frame is None or u is None:
            return False
        local, d = to_model(frame, tip, u)
        d = _unit(d) or (0.0, 0.0, 1.0)
        arrows = list(barrel.properties.get(KEY) or [])
        arrows.append({"item": str(ammo or DEFAULT_AMMO),
                       "at": [round(v, 2) for v in local],
                       "dir": [round(v, 4) for v in d]})
        del arrows[:-MAX_PER_BARREL]
        barrel.properties[KEY] = arrows
        touch(barrel)
        self._barrels[id(barrel)] = barrel
        play = getattr(self.session, "play_sound_at", None)
        if play is not None:
            play(ARROW_THUNK_SOUND, tip)
        return True

    @staticmethod
    def arrows_in(barrel):
        """The arrows stuck in *barrel* (its :data:`KEY` list)."""
        found = getattr(barrel, "properties", {}).get(KEY)
        return found if isinstance(found, list) else []

    def world_arrows(self, barrel):
        """``[(tip, direction, item id)]`` of *barrel*'s arrows in the world."""
        frame = self._frame(barrel)
        if frame is None:
            return []
        out = []
        for arrow in self.arrows_in(barrel):
            try:
                tip, d = to_world(frame, arrow["at"], arrow["dir"])
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            out.append((tip, d or (0.0, 0.0, 1.0), arrow.get("item") or DEFAULT_AMMO))
        return out

    # -- the tick -------------------------------------------------------------
    def update(self) -> None:
        """Carry the stuck arrows with their barrels; an exploded barrel's
        are destroyed. Publishes :attr:`drawn`."""
        runtime = fio.prop_runtime(self.logic)
        props = getattr(runtime, "props", None)
        if props is not self._seen:
            self._seen = props
            self._barrels = {id(p): p for p in (props or ())
                             if p.properties.get(KEY)}
        if not self._barrels:
            if self.drawn:
                self.drawn = ()
            return
        exploded = self._exploded()
        from .ui.arrows import ARROW_SIZE
        half = ARROW_SIZE * 0.5 - BURIED
        out = []
        for key, barrel in list(self._barrels.items()):
            bp = barrel.properties
            if not bp.get(KEY):
                del self._barrels[key]
                continue
            if key in exploded:
                # Blown apart with the barrel: nothing left to pull.
                bp.pop(KEY, None)
                touch(barrel)
                del self._barrels[key]
                continue
            if bp.get("hidden"):
                continue
            for tip, d, item in self.world_arrows(barrel):
                centre = (tip[0] - d[0] * half, tip[1] - d[1] * half, tip[2] - d[2] * half)
                flat = math.hypot(d[0], d[2])
                out.append((centre, math.atan2(d[0], d[2]), max(flat, 0.2),
                            self._sprite(item)))
        self.drawn = tuple(out)

    def _sprite(self, item):
        sprite = self._sprites.get(item)
        if sprite is None:
            from .ui.arrows import arrow_sprite
            sprite = self._sprites[item] = arrow_sprite(item)
        return sprite

    # -- taking them back -----------------------------------------------------
    def nearest(self, pos, radius=PULL_REACH):
        """The nearest barrel with arrows in it within *radius* of *pos* (on
        the ground), or None."""
        if not self._barrels or pos is None:
            return None
        exploded = self._exploded()
        best, best_d2 = None, float(radius) * float(radius)
        px, pz = float(pos[0]), float(pos[2])
        for key, barrel in self._barrels.items():
            if key in exploded or barrel.properties.get("hidden"):
                continue
            if not self.arrows_in(barrel):
                continue
            dx, dz = float(barrel.pos[0]) - px, float(barrel.pos[2]) - pz
            d2 = dx * dx + dz * dz
            if d2 <= best_d2:
                best, best_d2 = barrel, d2
        return best

    def claims_use(self) -> bool:
        """The use press is for the arrows (not for picking the barrel up)
        while the player stands by a barrel with arrows in it."""
        player = fio.player(self.logic)
        return player is not None and self.nearest(player.pos) is not None

    def prompt(self, barrel) -> str:
        n = len(self.arrows_in(barrel))
        return "Pull the arrow from the barrel" if n == 1 else f"Pull {n} arrows from the barrel"

    def pull(self, barrel) -> int:
        """Pull every arrow out of *barrel* into the player's pack, as the
        ammunition each was; those the pack has no room for stay. Returns how
        many were taken."""
        from .rpg import inventory as inv
        from .rpg import items as rpg_items
        session = self.session
        arrows = self.arrows_in(barrel)
        if not arrows:
            return 0
        pack = session.game.character.inventory
        has_room = getattr(session, "pack_has_room", None)
        kept, taken = [], {}
        for arrow in arrows:
            iid = str(arrow.get("item") or DEFAULT_AMMO)
            if rpg_items.get(iid) is None:
                iid = DEFAULT_AMMO
            if has_room is not None and not has_room(iid, 1):
                kept.append(arrow)
                continue
            stack = rpg_items.make(iid, 1) or inv.make_item(iid, qty=1)
            inv.add_item(pack, stack)
            name, count = taken.get(iid, (stack.get("name", iid), 0))
            taken[iid] = (name, count + 1)
        if kept:
            barrel.properties[KEY] = kept
        else:
            barrel.properties.pop(KEY, None)
            self._barrels.pop(id(barrel), None)
        touch(barrel)
        if not taken:
            note = getattr(session, "_pack_full_note", None)
            if note is not None:
                note()
            return 0
        for name, count in taken.values():
            session.notify(f"Picked up {name}" if count == 1 else f"Picked up {name} ×{count}")
        self.update()
        return sum(count for _name, count in taken.values())
