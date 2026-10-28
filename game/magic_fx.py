"""
What magic looks like: every visible effect a spell leaves, as plain data.

The game calls in as things happen -- a cast (:meth:`MagicFX.cast`), a bolt
loosed and flying (:meth:`MagicFX.bolt`, :meth:`MagicFX.track_bolts`), it
striking (:meth:`MagicFX.impact`), a heal, a summoning, a resurrection -- and
:meth:`MagicFX.frame` hands the renderer (``game.ui.magic_gl``, the 2D layer
``game.ui.magic_overlay``) all that is alive this instant:

* **sprites** -- one row per glowing quad, drawn additively in the world: bolt
  orbs with a fresnel rim, trails of embers / frost / sparks, shockwave rings,
  rotating rune circles under casters, radial light rays, flashes, ice stars,
  rising motes, and the fresnel bubble of a ward around whoever wears one;
* **lenses** -- screen-space fisheye bulges, each with a refracting shock ring,
  where a heavy spell lands (firebolt, lightning, frostbite, disintegrate,
  resurrection);
* **tints** -- whole-screen washes: the 3-second dark red of a resurrection,
  a lightning flash, an elemental vignette when a spell hits the player.

Positions given for an actor (a cast, a heal, a summoning, a resurrection, a
ward) are its *feet*, the ground it stands on; an impact is the point in the
air a bolt struck. Nothing here draws or touches GL, so it is safe to drive
from the logic thread and to test headless. Spells are matched to a *look*
(:func:`look_for`) by id first, then by element, so a designer's new spell
still looks like its kind.

Cost is bounded the way the rest of the game is: effects farther than
:data:`FX_RADIUS` from the player (in Big World terms, beyond the tiers the
player can watch) are never spawned, and live particles are capped at
:data:`MAX_PARTICLES`.
"""

from __future__ import annotations

import math
import random
import threading
import time

import numpy as np

# Sprite modes: must match game/ui/magic_gl.py's fragment shader.
ORB, RING, RUNES, MOTE, BUBBLE, RAYS, FLASH, SHARDS, ARC = range(9)

#: Nothing is spawned farther than this from the player.
FX_RADIUS = 2600.0
#: Live particles at most; the oldest go first.
MAX_PARTICLES = 1600
#: Lenses at once (the screen pass's uniform array).
MAX_LENSES = 8
#: Heights above the ground: ground rings and runes just over the floor
#: decals, glows and flashes at body height, and how high a bolt flies (an
#: impact's ground is this far below where it struck).
GROUND_LIFT = 20.0
BODY_LIFT = 56.0
BOLT_HEIGHT = 48.0
#: A ward bubble's diameter, comfortably round the wearer; how strongly it
#: bends what is behind it, and where (0 centre .. 1 edge) its rim refracts.
WARD_SIZE = 200.0
WARD_LENS = 0.45
WARD_RIM = 0.9
#: The ward breathes: its size swells by this share, this many times a second,
#: and its lens shimmers (a ripple through the glass) by WARD_SHIMMER.
WARD_PULSE = 0.06
WARD_PULSE_HZ = 0.7
WARD_SHIMMER = 1.0
#: Drinking a potion: a momentary green bubble round the drinker, bending
#: the world behind it like a ward's (a fisheye lens with a shimmer through
#: it), swelling in fast and fading: its colour, size, lens strength and life.
DRINK_COLOUR = (90, 255, 130)
DRINK_SIZE = 180.0
DRINK_LENS = 0.4
DRINK_SECONDS = 0.7
DRINK_IN = 0.08
#: The colours of fire, from the white-gold heart to the deep orange tips.
FLAME_HOT = (1.0, 0.86, 0.42)
FLAME_DEEP = (1.0, 0.36, 0.06)
#: A hostile bolt ending this near the player struck the player.
PLAYER_HIT_REACH = 110.0
#: The resurrection's dark red wash: in, held, out (3 seconds in all).
RESURRECT_TINT = (0.25, 1.75, 1.0)

#: Particle columns.
(PX, PY, PZ, VX, VY, VZ, GRAV, START, LIFE, SIZE0, SIZE1,
 CR, CG, CB, CA, MODE, SEED, FLAT, DRAG) = range(19)
COLUMNS = 19


def _rgb(colour):
    """0-255 or 0-1 RGB -> 0-1 floats."""
    c = [float(v) for v in list(colour)[:3]]
    if max(c) > 1.0:
        c = [v / 255.0 for v in c]
    return tuple(min(1.0, max(0.0, v)) for v in c)


def _lift(pos, dy):
    return (float(pos[0]), float(pos[1]) + dy, float(pos[2]))


def _mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


# ---------------------------------------------------------------- looks

#: Per element: the bolt, its trail and what its impact does.
#:   orb      -- bolt orb size (world units)
#:   trail    -- "embers" | "frost" | "arcs" | "motes"
#:   flash    -- impact flash size; ring -- shockwave size
#:   sparks   -- impact sparks; shards -- an ice star; rays -- a ray burst
#:   lens     -- fisheye strength at the impact (0 for none)
#:   hit_tint -- the screen wash when the player is the one hit
ELEMENT_LOOKS = {
    "fire": dict(orb=34.0, trail="embers", flash=150.0, ring=240.0, sparks=26,
                 shards=False, rays=False, lens=0.0, hit_tint="burn"),
    "frost": dict(orb=30.0, trail="frost", flash=120.0, ring=220.0, sparks=18,
                  shards=True, rays=False, lens=0.22, hit_tint="frost"),
    "shock": dict(orb=26.0, trail="arcs", flash=170.0, ring=260.0, sparks=34,
                  shards=False, rays=True, lens=0.45, hit_tint="shock"),
    "magic": dict(orb=30.0, trail="motes", flash=130.0, ring=220.0, sparks=20,
                  shards=False, rays=False, lens=0.0, hit_tint="arcane"),
}
#: Spell-specific changes on top of their element's look.
SPELL_LOOKS = {
    "firebolt": dict(orb=42.0, flash=200.0, ring=320.0, sparks=40, lens=0.38),
    "lightning": dict(lens=0.55),
    "disintegrate": dict(orb=40.0, flash=260.0, ring=420.0, sparks=60, rays=True,
                         lens=0.9, hit_tint="disintegrate"),
}


#: What a spell's ``visuals`` (set in the Spell Editor) may change, and the
#: type each must be. Anything else in it is ignored.
VISUAL_KEYS = {"orb": float, "trail": str, "flash": float, "ring": float,
               "sparks": int, "shards": bool, "rays": bool, "lens": float,
               "hit_tint": str, "cast": str}
TRAILS = ("embers", "frost", "arcs", "motes")
CAST_EFFECTS = ("runes", "none")


def clean_visuals(visuals) -> dict:
    """*visuals* kept to :data:`VISUAL_KEYS`, each coerced to its type (an
    entry that will not coerce, or names an unknown trail or wash, is dropped)."""
    out = {}
    for key, kind in VISUAL_KEYS.items():
        if not isinstance(visuals, dict) or visuals.get(key) is None:
            continue
        try:
            value = kind(visuals[key])
        except (TypeError, ValueError):
            continue
        if key == "trail" and value not in TRAILS:
            continue
        if key == "hit_tint" and value not in HIT_TINTS and value != "none":
            continue
        if key == "cast" and value not in CAST_EFFECTS:
            continue
        if kind in (float, int):
            value = max(0, value)
        out[key] = value
    return out


def look_for(spell_id="", colour=None, element="magic", visuals=None) -> dict:
    """How *spell_id* (or, failing that, its *element*) looks, in *colour*,
    with the spell's own *visuals* from the Spell Editor over the top."""
    element = element if element in ELEMENT_LOOKS else "magic"
    look = dict(ELEMENT_LOOKS[element])
    look["cast"] = "runes"
    look.update(SPELL_LOOKS.get(str(spell_id), {}))
    look.update(clean_visuals(visuals))
    if colour is None:
        from .rpg import magic
        colour = magic.element_color(element)
    look["colour"] = _rgb(colour)
    look["element"] = element
    look["spell"] = str(spell_id or "")
    return look


#: What a hit on the player does to the screen, per ``hit_tint``:
#: (colour 0-1, peak alpha, seconds, style).
HIT_TINTS = {
    "burn": ((1.0, 0.45, 0.1), 0.38, 0.6, "vignette"),
    "frost": ((0.75, 0.9, 1.0), 0.55, 1.4, "frost"),
    "shock": ((0.85, 0.85, 1.0), 0.45, 0.35, "flash"),
    "arcane": ((0.6, 0.5, 1.0), 0.32, 0.6, "vignette"),
    "disintegrate": ((0.9, 0.05, 0.05), 0.6, 0.9, "vignette"),
}


class MagicFX:
    """Every live magic effect (see the module doc). Thread-safe."""

    def __init__(self, clock=time.perf_counter, player_pos=None, rng=None):
        self._clock = clock
        #: ``player_pos() -> (x, y, z)`` or None: what "near" is measured from.
        self._player_pos = player_pos
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self._p = np.zeros((0, COLUMNS), dtype=np.float32)
        #: tag -> [look, pos, vel, seen_at, emitted_at]
        self._bolts = {}
        #: [x, y, z, start, life, strength, radius, r, g, b]
        self._lenses = []
        #: [start, fade_in, hold, fade_out, (r, g, b), peak, style]
        self._tints = []
        #: [x, y, z, start]: potions being drunk (the green shimmer).
        self._drinks = []
        #: ``wards() -> [(feet, colour, kind)]`` read every frame: who wears a
        #: ward (shield, flame cloak, ...), drawn as a fresnel bubble.
        self.wards = None
        #: ``hands() -> [(position, spell look)]`` for persistent equipped magic.
        self.hands = None

    # -- spawning helpers -----------------------------------------------------
    def near(self, pos) -> bool:
        if self._player_pos is None or pos is None:
            return True
        player = self._player_pos()
        if player is None:
            return True
        return math.hypot(float(pos[0]) - float(player[0]),
                          float(pos[2]) - float(player[2])) <= FX_RADIUS

    def _emit(self, rows) -> None:
        if not rows:
            return
        new = np.asarray(rows, dtype=np.float32).reshape(-1, COLUMNS)
        with self._lock:
            self._p = np.concatenate((self._p, new))
            if len(self._p) > MAX_PARTICLES:
                self._p = self._p[-MAX_PARTICLES:]

    def _row(self, pos, mode, life, size0, size1=None, colour=(1, 1, 1), alpha=1.0,
             vel=(0.0, 0.0, 0.0), grav=0.0, flat=False, drag=0.0, now=None, seed=None):
        r = self._rng
        return [float(pos[0]), float(pos[1]), float(pos[2]),
                float(vel[0]), float(vel[1]), float(vel[2]), float(grav),
                self._clock() if now is None else now, float(life),
                float(size0), float(size0 if size1 is None else size1),
                colour[0], colour[1], colour[2], float(alpha), float(mode),
                r.random() if seed is None else seed, 1.0 if flat else 0.0, float(drag)]

    def _burst(self, pos, count, colour, speed, life, size, grav=-420.0,
               up=0.6, mode=MOTE, now=None):
        """*count* sparks flung out from *pos*."""
        r = self._rng
        rows = []
        for _ in range(int(count)):
            a = r.uniform(0.0, math.tau)
            s = speed * r.uniform(0.35, 1.0)
            v = (math.cos(a) * s, speed * up * r.uniform(0.2, 1.0), math.sin(a) * s)
            c = _mix(colour, (1.0, 1.0, 1.0), r.uniform(0.0, 0.5))
            rows.append(self._row(pos, mode, life * r.uniform(0.6, 1.0),
                                  size * r.uniform(0.6, 1.2), 0.0, c, 1.0, v, grav,
                                  drag=1.5, now=now))
        self._emit(rows)

    def _lens(self, pos, strength, radius, colour, life=0.55, now=None):
        if strength <= 0:
            return
        now = self._clock() if now is None else now
        with self._lock:
            self._lenses.append([float(pos[0]), float(pos[1]), float(pos[2]), now,
                                 float(life), float(strength), float(radius), *colour])
            if len(self._lenses) > MAX_LENSES:
                self._lenses = self._lenses[-MAX_LENSES:]

    def tint(self, colour, peak, fade_in, hold, fade_out, style="fill"):
        with self._lock:
            self._tints.append([self._clock(), float(fade_in), float(hold),
                                float(fade_out), _rgb(colour), float(peak), style])

    # -- what happens ---------------------------------------------------------
    def cast(self, feet, look) -> None:
        """A rune circle under the caster's *feet* and a swirl of motes."""
        if not self.near(feet) or look.get("cast") == "none":
            return
        now = self._clock()
        c = look["colour"]
        foot, body = _lift(feet, GROUND_LIFT), _lift(feet, BODY_LIFT)
        rows = [self._row(foot, RUNES, 0.9, 130.0, 150.0, c, 0.95, flat=True, now=now),
                self._row(body, FLASH, 0.25, 70.0, 110.0, _mix(c, (1, 1, 1), 0.5), 0.8, now=now)]
        r = self._rng
        for i in range(12):
            a = i / 12.0 * math.tau
            p = (feet[0] + math.cos(a) * 55.0, feet[1] + 10.0, feet[2] + math.sin(a) * 55.0)
            v = (-math.cos(a) * 60.0, 120.0 + r.uniform(0, 60), -math.sin(a) * 60.0)
            rows.append(self._row(p, MOTE, 0.6, 14.0, 4.0, _mix(c, (1, 1, 1), 0.3), 0.9, v,
                                  now=now))
        self._emit(rows)

    def bolt(self, tag, look, hostile=False) -> None:
        """A bolt (Fio projectile *tag*) is in flight with *look*; *hostile*:
        cast at the player (one that ends on the player washes the screen)."""
        if not tag:
            return
        with self._lock:
            self._bolts[int(tag)] = [look, None, (0.0, 0.0, 0.0), 0.0, 0.0, bool(hostile)]

    def bolt_tags(self):
        with self._lock:
            return list(self._bolts)

    def track_bolts(self, live) -> list:
        """Where each bolt is now (``{tag: (pos, vel)}``, the bolts Fio still
        holds). Trails are laid behind the live ones; one gone since the last
        call struck something (or spent its range) and bursts where it was.
        Returns ``[(pos, look)]`` for the bolts that ended."""
        now = self._clock()
        ended, rows = [], []
        r = self._rng
        with self._lock:
            for tag in list(self._bolts):
                entry = self._bolts[tag]
                if tag in live:
                    pos, vel = live[tag]
                    entry[1], entry[2], entry[3] = tuple(pos), tuple(vel), now
                    if now - entry[4] >= 1.0 / 45.0:
                        entry[4] = now
                        rows.extend(self._trail(entry[0], pos, vel, now, r))
                elif entry[1] is not None:
                    ended.append((entry[1], entry[0], entry[5]))
                    del self._bolts[tag]
        self._emit(rows)
        player = self._player_pos() if self._player_pos is not None else None
        for pos, look, hostile in ended:
            hit = bool(hostile and player is not None and math.dist(
                (pos[0], pos[2]), (float(player[0]), float(player[2]))) < PLAYER_HIT_REACH)
            self.impact(pos, look, player_hit=hit)
        return [(pos, look) for pos, look, _h in ended]

    def _trail(self, look, pos, vel, now, r):
        c = look["colour"]
        kind = look["trail"]
        rows = []
        if kind == "arcs":
            for _ in range(2):
                j = (r.uniform(-14, 14), r.uniform(-14, 14), r.uniform(-14, 14))
                p = (pos[0] + j[0], pos[1] + j[1], pos[2] + j[2])
                rows.append(self._row(p, ARC, 0.16, 46.0, 20.0, _mix(c, (1, 1, 1), 0.55),
                                      1.0, now=now))
        elif kind == "frost":
            rows.append(self._row(pos, MOTE, 0.5, 20.0, 2.0, _mix(c, (1, 1, 1), 0.4), 0.8,
                                  (r.uniform(-20, 20), -30.0, r.uniform(-20, 20)), now=now))
            rows.append(self._row(pos, SHARDS, 0.3, 26.0, 8.0, c, 0.7, now=now))
        elif kind == "embers":
            for _ in range(2):
                rows.append(self._row(pos, MOTE, 0.45, 22.0, 3.0,
                                      _mix(c, (1.0, 0.85, 0.3), r.random()), 0.9,
                                      (r.uniform(-30, 30), r.uniform(20, 70),
                                       r.uniform(-30, 30)), now=now))
        else:
            rows.append(self._row(pos, MOTE, 0.4, 18.0, 2.0, c, 0.8,
                                  (r.uniform(-15, 15), r.uniform(-15, 15),
                                   r.uniform(-15, 15)), now=now))
        return rows

    def impact(self, pos, look, player_hit=False) -> None:
        """A spell strikes at *pos*: flash, shockwave, sparks, and for the
        heavy ones a lens. *player_hit*: it struck the player (screen wash)."""
        if player_hit:
            tint = HIT_TINTS.get(look.get("hit_tint"))
            if tint is not None:
                colour, peak, secs, style = tint
                self.tint(colour, peak, 0.04, secs * 0.25, secs * 0.75, style)
        if not self.near(pos):
            return
        now = self._clock()
        c = look["colour"]
        hot = _mix(c, (1.0, 1.0, 1.0), 0.45)
        ground = _lift(pos, GROUND_LIFT - BOLT_HEIGHT)
        rows = [self._row(pos, FLASH, 0.35, look["flash"] * 0.5, look["flash"], hot, 1.0,
                          now=now),
                self._row(ground, RING, 0.55, look["ring"], look["ring"], c, 1.0, flat=True,
                          now=now)]
        if look.get("shards"):
            rows.append(self._row(ground, SHARDS, 0.8, look["ring"] * 0.7,
                                  look["ring"] * 0.9, _mix(c, (1, 1, 1), 0.3), 1.0,
                                  flat=True, now=now))
        if look.get("rays"):
            rows.append(self._row(pos, RAYS, 0.5, look["flash"] * 0.8, look["flash"] * 1.6,
                                  hot, 1.0, now=now))
        self._emit(rows)
        self._burst(pos, look["sparks"], c, 420.0, 0.7, 16.0, now=now)
        self._lens(pos, look.get("lens", 0.0), look["ring"] * 0.9, c, now=now)

    def flames(self, pos, strength=1.0, size=1.0) -> None:
        """A moment of fire at *pos* (a burning body, a fire on the ground):
        tongues of flame licking upward, embers and a hot glow. Called a few
        dozen times a second for as long as it burns; *strength* (0..1)
        thins and shrinks the flames as the fire dies, so it fades out
        rather than going out at once."""
        strength = max(0.0, min(1.0, float(strength)))
        if strength <= 0.0 or not self.near(pos):
            return
        now = self._clock()
        r = self._rng
        rows = []
        for _ in range(1 + int(round(2 * strength))):
            j = (r.uniform(-18, 18) * size, r.uniform(-6, 10) * size, r.uniform(-18, 18) * size)
            p = (pos[0] + j[0], pos[1] + j[1], pos[2] + j[2])
            hot = _mix(FLAME_HOT, FLAME_DEEP, r.random())
            rows.append(self._row(p, MOTE, r.uniform(0.35, 0.6), 30.0 * size * (0.5 + strength / 2),
                                  4.0, hot, 0.95 * strength,
                                  (r.uniform(-12, 12), r.uniform(70, 130) * size,
                                   r.uniform(-12, 12)), grav=60.0, now=now))
        if r.random() < 0.35 * strength:
            rows.append(self._row((pos[0], pos[1] + 30.0 * size, pos[2]), MOTE, 1.1, 6.0, 1.0,
                                  FLAME_HOT, strength,
                                  (r.uniform(-40, 40), r.uniform(90, 170), r.uniform(-40, 40)),
                                  grav=-40.0, drag=0.8, now=now))
        if r.random() < 0.25:
            rows.append(self._row(pos, FLASH, 0.2, 60.0 * size, 80.0 * size, FLAME_DEEP,
                                  0.35 * strength, now=now))
        self._emit(rows)

    def heal(self, feet, colour=(120, 255, 150)) -> None:
        """Healing light: a ring at the *feet* and motes spiralling up."""
        if not self.near(feet):
            return
        pos = _lift(feet, BODY_LIFT)
        now = self._clock()
        c = _rgb(colour)
        foot = _lift(feet, GROUND_LIFT)
        rows = [self._row(foot, RING, 0.9, 120.0, 120.0, c, 0.9, flat=True, now=now),
                self._row(pos, ORB, 0.7, 60.0, 90.0, _mix(c, (1, 1, 1), 0.3), 0.55, now=now)]
        r = self._rng
        for i in range(26):
            a = r.uniform(0, math.tau)
            rad = r.uniform(15, 50)
            p = (feet[0] + math.cos(a) * rad, feet[1] + r.uniform(5, 35),
                 feet[2] + math.sin(a) * rad)
            v = (-math.sin(a) * 70.0, r.uniform(90, 170), math.cos(a) * 70.0)
            rows.append(self._row(p, MOTE, r.uniform(0.7, 1.2), r.uniform(10, 18), 2.0,
                                  _mix(c, (1, 1, 0.8), r.random() * 0.5), 1.0, v,
                                  grav=40.0, now=now))
        self._emit(rows)

    def drink(self, feet) -> None:
        """A potion drunk by whoever stands at *feet*: for a moment a green
        bubble round them, the world behind it bending as through a ward's
        glass, with a shimmer through it -- then gone."""
        if not self.near(feet):
            return
        now = self._clock()
        with self._lock:
            self._drinks.append([float(feet[0]), float(feet[1]), float(feet[2]), now])
            if len(self._drinks) > MAX_LENSES:
                self._drinks = self._drinks[-MAX_LENSES:]

    def summon(self, feet, colour=(170, 90, 255)) -> None:
        """A portal opens at *feet*: a wide rune ring, rays and a dark flash."""
        if not self.near(feet):
            return
        pos = _lift(feet, BODY_LIFT)
        now = self._clock()
        c = _rgb(colour)
        foot = _lift(feet, GROUND_LIFT)
        self._emit([self._row(foot, RUNES, 1.4, 200.0, 240.0, c, 1.0, flat=True, now=now),
                    self._row(pos, RAYS, 1.0, 120.0, 220.0, c, 0.9, now=now),
                    self._row(foot, RING, 0.8, 280.0, 280.0, c, 0.9, flat=True, now=now)])
        self._burst(pos, 30, c, 260.0, 0.9, 14.0, grav=60.0, up=1.0, now=now)
        self._lens(pos, 0.25, 220.0, c, life=0.8, now=now)

    def resurrection(self, feet) -> None:
        """A fallen soul returns: the whole screen goes dark red for three
        seconds while light pours up from the body at *feet*."""
        fade_in, hold, fade_out = RESURRECT_TINT
        self.tint((105, 0, 0), 0.62, fade_in, hold, fade_out, "blood")
        if not self.near(feet):
            return
        pos = _lift(feet, BODY_LIFT)
        now = self._clock()
        gold = (1.0, 0.85, 0.45)
        green = _rgb((120, 255, 170))
        foot = _lift(feet, GROUND_LIFT)
        self._emit([
            self._row(pos, RAYS, 2.6, 160.0, 520.0, gold, 1.0, now=now),
            self._row(foot, RUNES, 3.0, 260.0, 300.0, green, 1.0, flat=True, now=now),
            self._row(foot, RING, 1.2, 420.0, 420.0, gold, 1.0, flat=True, now=now),
            self._row(pos, FLASH, 0.6, 200.0, 360.0, (1.0, 0.95, 0.8), 1.0, now=now),
        ])
        r = self._rng
        rows = []
        for _ in range(70):
            a = r.uniform(0, math.tau)
            rad = r.uniform(0, 70)
            p = (feet[0] + math.cos(a) * rad, feet[1] + 10.0, feet[2] + math.sin(a) * rad)
            v = (r.uniform(-25, 25), r.uniform(160, 420), r.uniform(-25, 25))
            rows.append(self._row(p, MOTE, r.uniform(1.2, 2.6), r.uniform(12, 24), 3.0,
                                  _mix(gold, green, r.random()), 1.0, v, grav=-30.0,
                                  now=now + r.uniform(0.0, 1.2)))
        self._emit(rows)
        self._lens(pos, 0.5, 360.0, gold, life=1.4, now=now)

    def clear(self) -> None:
        with self._lock:
            self._p = np.zeros((0, COLUMNS), dtype=np.float32)
            self._bolts.clear()
            self._lenses = []
            self._tints = []
            self._drinks = []

    # -- what is alive now ----------------------------------------------------
    def frame(self, now=None):
        """``(sprites, lenses, tints)`` for this instant.

        *sprites*: ``(n, 12)`` float32 rows ``x, y, z, size, r, g, b, a, mode,
        progress, seed, flat``. *lenses*: ``[(x, y, z, strength, radius,
        progress, (r, g, b), shimmer)]``. *tints*: ``[((r, g, b), alpha, style,
        progress, envelope)]``, *alpha* being the peak scaled by the 0..1
        *envelope*.
        """
        now = self._clock() if now is None else now
        with self._lock:
            p = self._p
            if len(p):
                alive = (now - p[:, START]) < p[:, LIFE]
                if not alive.all():
                    p = self._p = p[alive | (p[:, START] > now)]
            bolts = [(e[0], e[1], e[2], e[3]) for e in self._bolts.values()
                     if e[1] is not None]
            self._lenses = [l for l in self._lenses if now - l[3] < l[4]]
            lenses = [list(l) for l in self._lenses]
            self._tints = [t for t in self._tints if now - t[0] < t[1] + t[2] + t[3]]
            tints = [list(t) for t in self._tints]
            self._drinks = [d for d in self._drinks if now - d[3] < DRINK_SECONDS]
            drinks = [list(d) for d in self._drinks]
        sprites = self._particles_now(p, now)
        extra = []
        for look, pos, vel, seen in bolts:
            dt = min(0.05, max(0.0, now - seen))
            at = (pos[0] + vel[0] * dt, pos[1] + vel[1] * dt, pos[2] + vel[2] * dt)
            c = look["colour"]
            extra.append([*at, look["orb"], *c, 1.0, ORB, 0.0, (hash(look["spell"]) % 97) / 97.0,
                          0.0])
            extra.append([*at, look["orb"] * 2.4, *c, 0.35, FLASH, 0.35, 0.0, 0.0])
        ward_lenses = []
        for at, look in (self.hands() if self.hands is not None else ()):
            colour = look["colour"]
            pulse = 1.0 + 0.10 * math.sin(now * 4.0)
            size = max(16.0, min(30.0, look["orb"])) * pulse
            extra.append([*at, size, *colour, 0.9, ORB, 0.25, 0.3, 0.0])
            extra.append([*at, size * 2.1, *colour, 0.24, FLASH, 0.35, 0.0, 0.0])
            mode = {"frost": SHARDS, "arcs": ARC}.get(look["trail"], MOTE)
            for i in range(3):
                phase = now * 2.4 + i * math.tau / 3
                orbit = (at[0] + math.cos(phase) * 10.0,
                         at[1] + math.sin(phase * 1.3) * 6.0,
                         at[2] + math.sin(phase) * 10.0)
                extra.append([*orbit, 10.0, *colour, 0.65, mode,
                              0.4, i / 3.0, 0.0])
        for pos, colour, kind in (self._wards_now() or ()):
            c = _rgb(colour)
            # The ward is a lens: the world behind it bulges as through glass,
            # its rim refracting (the shock ring, held at the edge), and it
            # breathes -- a gentle swell -- with a shimmer through the glass.
            breathe = 1.0 + WARD_PULSE * math.sin(now * math.tau * WARD_PULSE_HZ)
            size = WARD_SIZE * (0.88 if kind == "berserk" else 1.0) * breathe
            ward_lenses.append((float(pos[0]), float(pos[1]) + BODY_LIFT, float(pos[2]),
                                WARD_LENS, size * 0.5, WARD_RIM, c, WARD_SHIMMER))
            extra.append([float(pos[0]), float(pos[1]) + BODY_LIFT, float(pos[2]),
                          size, *c, 0.9, BUBBLE,
                          (now * 0.35) % 1.0, 0.5 if kind == "invisibility" else 0.0, 0.0])
        green = _rgb(DRINK_COLOUR)
        for x, y, z, start in drinks:
            # Swells in fast, then fades as it settles: momentary, not worn.
            age = now - start
            if age < 0:
                continue
            env = (min(1.0, age / DRINK_IN)
                   * (1.0 - max(0.0, age - DRINK_IN) / (DRINK_SECONDS - DRINK_IN)) ** 1.5)
            size = DRINK_SIZE * (0.8 + 0.2 * min(1.0, age / DRINK_IN))
            ward_lenses.append((x, y + BODY_LIFT, z, DRINK_LENS * env, size * 0.5,
                                WARD_RIM, green, WARD_SHIMMER))
            extra.append([x, y + BODY_LIFT, z, size, *green, 0.85 * env, BUBBLE,
                          (now * 0.6) % 1.0, 0.0, 0.0])
        if extra:
            sprites = np.concatenate((sprites, np.asarray(extra, dtype=np.float32)))
        out_lenses = []
        for x, y, z, start, life, strength, radius, cr, cg, cb in lenses:
            t = (now - start) / life
            if t < 0:
                continue
            env = min(1.0, (now - start) / 0.06) * (1.0 - t) ** 2
            out_lenses.append((x, y, z, strength * env, radius, t, (cr, cg, cb), 0.0))
        out_tints = []
        for start, fade_in, hold, fade_out, colour, peak, style in tints:
            t = now - start
            if t < fade_in:
                a = t / fade_in if fade_in > 0 else 1.0
            elif t < fade_in + hold:
                a = 1.0
            else:
                a = max(0.0, 1.0 - (t - fade_in - hold) / fade_out) if fade_out > 0 else 0.0
            out_tints.append((colour, peak * a, style, t / (fade_in + hold + fade_out), a))
        out_lenses = (ward_lenses + out_lenses)[:MAX_LENSES]
        return sprites, out_lenses, out_tints

    def _wards_now(self):
        if self.wards is None:
            return ()
        try:
            return self.wards()
        except Exception:
            return ()

    @staticmethod
    def _particles_now(p, now):
        if not len(p):
            return np.zeros((0, 12), dtype=np.float32)
        p = p[p[:, START] <= now]
        age = (now - p[:, START]).astype(np.float32)
        life = np.maximum(p[:, LIFE], 1e-3)
        t = np.clip(age / life, 0.0, 1.0)
        # Drag slows a spark (an exponential approach), gravity pulls it.
        k = np.maximum(p[:, DRAG], 1e-4)
        travel = (1.0 - np.exp(-k * age)) / k
        out = np.empty((len(p), 12), dtype=np.float32)
        out[:, 0] = p[:, PX] + p[:, VX] * travel
        out[:, 1] = p[:, PY] + p[:, VY] * travel + 0.5 * p[:, GRAV] * age * age
        out[:, 2] = p[:, PZ] + p[:, VZ] * travel
        out[:, 3] = p[:, SIZE0] + (p[:, SIZE1] - p[:, SIZE0]) * t
        out[:, 4:7] = p[:, CR:CB + 1]
        # Motes and sparks fade out; the shaped effects animate on *progress*.
        mode = p[:, MODE]
        fades = (mode == MOTE) | (mode == ARC)
        out[:, 7] = p[:, CA] * np.where(fades, 1.0 - t * t, 1.0)
        out[:, 8] = mode
        out[:, 9] = t
        out[:, 10] = p[:, SEED]
        out[:, 11] = p[:, FLAT]
        return out
