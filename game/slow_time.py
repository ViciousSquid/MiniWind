"""Slow Time: one record per world of every Slow Time running in it.

The rule, the same for one player or a party, for a player or an NPC caster:

* **The world slows once.** While any Slow Time lasts the world runs at
  :data:`SLOW_TIME_SCALE` of the speed it ran before -- never slower, however
  many are cast: casts never compound.
* **Every caster is exempt for their own spell.** Each caster's own clock runs
  at ``1 / SLOW_TIME_SCALE`` of the world's (engine/actor_time.py) until *their*
  spell ends, so they move at their normal speed; then they slow with
  everyone else while anyone else's lasts.
* **The world stays slow until the last spell ends**, then runs at the speed
  it ran before. A caster who falls ends their own cast; leaving the map ends
  them all.
* **Everyone sees every bubble.** Each caster wears their own bubble and gives
  off their own light; the greyscale covers everything outside all bubbles.

:class:`SlowTime` holds this for one world. It lives on the *authoritative*
world logic (:func:`registry`), so every session sharing the world -- the root
session and each extra co-op player's session over its
``game.multiplayer.session.PlayerLogic`` adapter -- reads and writes the one
record, and its writes (``time_scale``, the actor clock rates) reach the world
the logic thread actually runs, never an adapter. On a network client the
record is a replica: :func:`capture` puts the host's casts in the world frame,
:func:`receive` rebuilds them on the client by identity, and a replica never
changes the client's own world speed (the host's world is what it shows).
The presentation -- bubbles, lights, sound, the screen's edge -- is
:class:`game.runtime.MiniwindSession`'s, drawn from this record.
"""

from __future__ import annotations

import math
import time

from engine import actor_time

#: How fast the world runs while any Slow Time lasts (never slower: casts
#: never compound), for how long one cast lasts (real seconds), and a second
#: more per level past this. Each caster is not slowed for their own spell's
#: time: their clock runs at 1 / SLOW_TIME_SCALE of the world's
#: (engine/actor_time.py), so they move at their normal speed -- twice as fast
#: as everyone else.
SLOW_TIME_SCALE = 0.5
SLOW_TIME_SECONDS = 5.0
SLOW_TIME_PER_LEVEL = 1.0
SLOW_TIME_FROM_LEVEL = 5
#: The tint (from the first cast's start to the last one's end), and each
#: caster's bubble and light (their own spell's), fade in and out over this
#: long (s).
SLOW_TIME_FADE = 0.35
#: The spell icon's violet (its colour in game/rpg/magic.py): the casters'
#: lights, the bubbles' glass and rim, and the screen's tint (RGB 0-255).
SLOW_TIME_COLOUR = (166, 130, 234)
#: The flickering light each caster gives off while their spell lasts: its
#: reach, its brightness at the top of a flicker, how high above the feet it
#: hangs, and the least share of that brightness a flicker dips to (never
#: fully out).
SLOW_TIME_LIGHT_RADIUS = 350.0
SLOW_TIME_LIGHT_INTENSITY = 8.0
SLOW_TIME_LIGHT_HEIGHT = 90.0
SLOW_TIME_FLICKER_FLOOR = 0.45
#: The fisheye bubble round each caster: its radius as a share of the caster's
#: height, how hard it magnifies, where its violet rim glows (as a share of the
#: radius), the ripple through its glass, and how violet it tints the inside.
SLOW_TIME_BUBBLE_SCALE = 1.5
#: 0.6: the middle seen about 2.5x larger, squeezed toward the rim (fisheye).
SLOW_TIME_BUBBLE_LENS = 0.6
#: The bubble gently pulses larger and smaller: by this share of its radius,
#: this many times a second (and its fisheye a little with it).
SLOW_TIME_BUBBLE_PULSE = 0.10
SLOW_TIME_BUBBLE_PULSE_HZ = 0.45
SLOW_TIME_BUBBLE_RIM = 0.94
SLOW_TIME_BUBBLE_SHIMMER = 0.35
SLOW_TIME_BUBBLE_FILL = 0.55
#: A caster's height when nothing says otherwise (world units).
SLOW_TIME_CASTER_HEIGHT = 112.0


def slow_time_seconds(level) -> float:
    """How long Slow Time lasts cast at *level*: five seconds, a second more
    for each level past the fifth."""
    try:
        level = int(level)
    except (TypeError, ValueError):
        level = 1
    return SLOW_TIME_SECONDS + max(0, level - SLOW_TIME_FROM_LEVEL) * SLOW_TIME_PER_LEVEL


def slow_time_flicker(t: float) -> float:
    """How bright a Slow Time caster's light is at real time *t*, as a share
    of :data:`SLOW_TIME_LIGHT_INTENSITY`: four incommensurate waves between 6
    and 17 Hz, so it jitters irregularly, never settling into a rhythm and
    never dipping below :data:`SLOW_TIME_FLICKER_FLOOR`."""
    tau = math.tau
    a = math.sin(t * tau * 7.1)
    b = math.sin(t * tau * 10.7 + 1.9)
    c = math.sin(t * tau * 6.3 + 0.7)
    d = math.sin(t * tau * 16.9 + 2.6)
    wave = 0.38 * a + 0.30 * b + 0.20 * c + 0.12 * d            # -1..1
    return max(SLOW_TIME_FLICKER_FLOOR, min(1.0, 0.75 + 0.25 * wave))


#: The attribute of the world logic the record lives under.
_ATTR = "miniwind_slow_time"


class Cast:
    """One caster's Slow Time: who, from when (``since``) until when
    (``until``, both real ``time.monotonic`` seconds), and their light."""

    __slots__ = ("caster", "owner", "player", "level", "since", "until", "light")

    def __init__(self, caster, owner=None, player=False, level=1, since=0.0, until=0.0):
        self.caster = caster
        #: The session whose own player the caster is (its fall ends the
        #: cast), or None for an NPC or creature.
        self.owner = owner
        #: Whether the caster is a player's body (its origin at its feet).
        self.player = bool(player)
        self.level = level
        self.since = float(since)
        self.until = float(until)
        self.light = None

    def left(self, now) -> float:
        return max(0.0, self.until - now)

    def envelope(self, now) -> float:
        """This caster's bubble and light: fading in from their cast, out to
        its end (0..1)."""
        return max(0.0, min(1.0, (now - self.since) / SLOW_TIME_FADE,
                            (self.until - now) / SLOW_TIME_FADE))


def world_of(logic):
    """The world logic the logic thread runs: *logic* itself, or the world
    under a co-op player's adapter (``PlayerLogic``)."""
    from .multiplayer.session import PlayerLogic
    while isinstance(logic, PlayerLogic):
        logic = vars(logic)["world"]
    return logic


def registry(logic) -> "SlowTime":
    """The one Slow Time record of *logic*'s world (made on first ask)."""
    world = world_of(logic)
    found = getattr(world, _ATTR, None)
    if not isinstance(found, SlowTime) or found.world is not world:
        found = SlowTime(world)
        try:
            setattr(world, _ATTR, found)
        except Exception:
            pass
    return found


class SlowTime:
    """Every Slow Time running in one world (see the module's rule)."""

    def __init__(self, world):
        self.world = world
        self.casts: list[Cast] = []
        #: The world's speed before the first cast (the debug tools may have
        #: set it), and the speed held while any lasts.
        self.prior = 1.0
        self.held = None
        #: When the first of the casts now running began: the shared tint
        #: fades in from here.
        self.since = None
        #: A network client's replica of the host's record: it shows the
        #: casts, but never changes this world's speed or clocks.
        self.remote = False

    # -- reading -----------------------------------------------------------
    @property
    def active(self) -> bool:
        return bool(self.casts)

    def find(self, caster):
        for cast in self.casts:
            if cast.caster is caster:
                return cast
        return None

    def casters(self) -> list:
        return [c.caster for c in self.casts]

    def left(self, caster=None, now=None) -> float:
        """Real seconds left of *caster*'s Slow Time, or (None) of the world's
        -- until the last spell ends (0: none)."""
        now = time.monotonic() if now is None else now
        if caster is not None:
            cast = self.find(caster)
            return cast.left(now) if cast is not None else 0.0
        return max((c.left(now) for c in self.casts), default=0.0)

    def tint(self, now=None) -> float:
        """The shared envelope (0..1): fading in from the first cast, out to
        the end of the last."""
        if not self.casts:
            return 0.0
        now = time.monotonic() if now is None else now
        since = self.since if self.since is not None else now
        end = max(c.until for c in self.casts)
        return max(0.0, min(1.0, (now - since) / SLOW_TIME_FADE,
                            (end - now) / SLOW_TIME_FADE))

    def exempt(self, body) -> bool:
        """Whether *body* casts a Slow Time running now (so is not slowed)."""
        return body is not None and self.find(body) is not None

    def movement_rate(self, body) -> float:
        """How much of each world tick *body* moves by. On the authority its
        actor clock rate (the logic thread already runs the world's ticks at
        the world's speed). On a client, which ticks at its own speed, the
        whole of it: half while the host's world is slowed, all of it again
        for a caster in their own spell."""
        if not self.remote:
            return actor_time.rate(self.world, body)
        if not self.casts:
            return 1.0
        return 1.0 if self.exempt(body) else SLOW_TIME_SCALE

    # -- the authority's rule ---------------------------------------------
    def cast(self, caster, level, owner=None, player=False, now=None) -> Cast:
        """*caster* casts Slow Time at *level*: their own spell for
        :func:`slow_time_seconds`; cast again, it lasts the longer of the two.
        The world slows (once) and they are exempt."""
        now = time.monotonic() if now is None else now
        if not self.casts:
            # What the world ran at before (the debug tools may have set it).
            self.prior = float(getattr(self.world, "time_scale", 1.0) or 1.0)
            self.held = None
            self.since = now
        cast = self.find(caster)
        until = now + slow_time_seconds(level)
        if cast is None:
            cast = Cast(caster, owner, player, level, now, until)
            self.casts.append(cast)
        else:
            cast.until = max(cast.until, until)
            cast.level = level
            if owner is not None:
                cast.owner = owner
        self.hold()
        return cast

    def hold(self) -> None:
        """Keep the world at :data:`SLOW_TIME_SCALE` of its speed before and
        each caster's clock at their own speed. Asked every tick while any
        lasts: a world speed changed meanwhile (the debug tools) becomes the
        speed it slows from, and one put back by anything else is slowed
        again, so nothing but the last spell's end lets it lapse."""
        if self.remote or not self.casts:
            return
        world = self.world
        current = getattr(world, "time_scale", None)
        if self.held is not None and current is not None \
                and abs(float(current) - self.held) > 1e-9:
            self.prior = float(current) or 1.0
        self.held = SLOW_TIME_SCALE * (float(self.prior) or 1.0)
        try:
            world.time_scale = self.held
        except Exception:
            pass
        for cast in self.casts:
            actor_time.set_rate(world, cast.caster, 1.0 / SLOW_TIME_SCALE)

    @staticmethod
    def _fallen(cast) -> bool:
        """Whether *cast*'s caster has fallen: their spell ends with them."""
        caster = cast.caster
        if caster is None:
            return True
        if cast.owner is not None:
            character = getattr(getattr(cast.owner, "game", None), "character", None)
            if character is not None:
                return bool(getattr(character, "is_dead", False))
        props = getattr(caster, "properties", None)
        return isinstance(props, dict) and bool(props.get("dead"))

    def update(self, now=None) -> list:
        """End each spell whose time is up or whose caster fell (their clock
        back in step: they slow with everyone else), and hold the world slowed
        while any remains; after the last, the world runs as before. Returns
        the casts that ended (their lights are the session's to put out)."""
        now = time.monotonic() if now is None else now
        if not self.casts:
            return []
        if self.remote:
            ended = [c for c in self.casts if c.until <= now]
        else:
            ended = [c for c in self.casts if c.until <= now or self._fallen(c)]
        if ended:
            self.casts = [c for c in self.casts if c not in ended]
            if not self.remote:
                for cast in ended:
                    actor_time.clear(self.world, cast.caster)
        if not self.casts:
            self._finish()
        else:
            self.hold()
        return ended

    def end_all(self) -> list:
        """Every Slow Time over (the map is left): the world runs at its own
        speed, every caster's clock in step. Returns the casts that ended."""
        ended, self.casts = self.casts, []
        if not self.remote:
            for cast in ended:
                actor_time.clear(self.world, cast.caster)
        self._finish()
        self.remote = False
        return ended

    def _finish(self) -> None:
        if not self.remote and self.held is not None:
            try:
                self.world.time_scale = float(self.prior) or 1.0
            except Exception:
                pass
        self.held = None
        self.since = None


# -- the network: host -> client -------------------------------------------
def capture(coop) -> dict:
    """The host's casts for the world frame: each caster by identity (a
    party member by player id, anyone else by entity id) with how long it has
    run and has left (real seconds: never a clock value, which differs
    between machines)."""
    from .multiplayer.replication import identity
    reg = registry(coop.logic)
    if not reg.casts:
        return {"casts": []}
    now = time.monotonic()
    bodies = {id(p.physics): pid for pid, p in coop.players.items()}
    casts = []
    for cast in reg.casts:
        pid = bodies.get(id(cast.caster))
        if pid is not None:
            entry = {"id": "player:" + str(pid), "player": str(pid)}
        else:
            props = getattr(cast.caster, "properties", None)
            sid = identity(cast.caster) if isinstance(props, dict) else ""
            if not sid:
                continue
            entry = {"id": sid}
        entry["age"] = round(max(0.0, now - cast.since), 3)
        entry["left"] = round(cast.left(now), 3)
        entry["level"] = cast.level if isinstance(cast.level, int) else 1
        casts.append(entry)
    return {"age": round(max(0.0, now - (reg.since or now)), 3), "casts": casts}


def receive(coop, data) -> None:
    """The host's casts (:func:`capture`) onto a client's replica record:
    every caster found here by identity -- a party member's body, or the
    replica of an NPC -- so every bubble is drawn and a local caster moves
    at its own speed."""
    reg = registry(coop.logic)
    reg.remote = True
    now = time.monotonic()
    entries = data.get("casts") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        entries = []
    here = coop.__dict__.get("_replica_index") or {}
    casts = []
    for entry in entries[:64]:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("player")
        owner = None
        if pid is not None:
            context = coop.players.get(str(pid))
            caster = context.physics if context is not None else None
            owner = context.session if context is not None else None
        else:
            caster = here.get(str(entry.get("id", "")))
        if caster is None:
            continue
        try:
            age = max(0.0, float(entry.get("age", 0.0)))
            left = max(0.0, float(entry.get("left", 0.0)))
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(age) and math.isfinite(left)):
            continue
        cast = reg.find(caster) or Cast(caster, owner, pid is not None)
        cast.since, cast.until = now - age, now + left
        cast.level = entry.get("level", 1)
        casts.append(cast)
    reg.casts = casts
    try:
        age = max(0.0, float(data.get("age", 0.0))) if casts else None
    except (TypeError, ValueError, AttributeError):
        age = 0.0
    if age is not None and not math.isfinite(age):
        age = 0.0
    reg.since = None if age is None else now - age
