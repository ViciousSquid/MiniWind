"""
Dragon's breath, made of the engine's EFFECT primitive (FIRE).

A lair carries a pool of FIRE Effect entities (``dragon_fire: true``), parked
out of sight under the floor. An actor with ``breathes_fire: true`` that is
fighting the player and has them within :data:`BREATH_RANGE` breathes every
:data:`BREATH_COOLDOWN` seconds: for :data:`BREATH_SECONDS` the pool streams
out of its mouth in a widening cone toward the player, and anyone standing in
the cone burns (``breath_damage`` fire damage every :data:`BURN_EVERY`
seconds). Then the flames park again.

Which of the FIRE settings (``fire01..05.gif``) the flames use is chosen with
the console: ``dragonfire 1`` .. ``dragonfire 5``. The choice is kept in the
game's state store, so it holds across saves and visits.
"""

from __future__ import annotations

import math
import random

from engine.change_journal import touch

BREATH_RANGE = 1150.0
BREATH_SECONDS = 1.9
BREATH_COOLDOWN = 5.5
#: How fast the flames travel out of the mouth, and the cone's half-angle.
FLAME_SPEED = 900.0
CONE_HALF_ANGLE = math.radians(20.0)
BURN_EVERY = 0.3
#: Where the pool waits: well below the floor.
PARK_DEPTH = -3000.0
STORE_KEY = "dragonfire"
FIRE_SETTINGS = 5


def fire_texture(setting: int) -> str:
    return f"assets/textures/effects/fire{int(setting):02d}.gif"


class DragonFire:
    def __init__(self, session):
        self.session = session
        self.flames = []
        self.breathers = []
        self._breath = {}          # id(breather) -> breath state
        self._parked = False

    # -- setup ---------------------------------------------------------------
    def install(self, things) -> None:
        self.flames = [t for t in things
                       if isinstance(getattr(t, "properties", None), dict)
                       and t.properties.get("dragon_fire")]
        self.breathers = [t for t in things
                          if isinstance(getattr(t, "properties", None), dict)
                          and t.properties.get("breathes_fire")]
        for t in self.flames:
            self._desync(t)
        setting = self.session.store.get(STORE_KEY, None)
        try:
            if setting not in (None, "false"):
                self.set_setting(int(float(setting)), remember=False)
        except (TypeError, ValueError):
            pass
        self._park()

    def set_setting(self, setting: int, remember: bool = True) -> bool:
        """Every flame in the pool uses FIRE setting *setting* (1..5)."""
        if not 1 <= int(setting) <= FIRE_SETTINGS:
            return False
        path = fire_texture(setting)
        for t in self.flames:
            t.properties["fire_texture"] = path
            touch(t)
        if remember:
            self.session.store.set(STORE_KEY, int(setting))
        return True

    # -- per tick --------------------------------------------------------------
    def update(self, delta: float) -> None:
        if not self.flames or not self.breathers:
            return
        s = self.session
        ppos = s._player_pos()
        if ppos is None:
            return
        burning = False
        for dragon in self.breathers:
            p = dragon.properties
            key = id(dragon)
            state = self._breath.get(key)
            if p.get("dead"):
                self._breath.pop(key, None)
                continue
            if state is None:
                state = self._breath[key] = {"t": -1.0, "cool": 0.0, "burn": 0.0}
            state["cool"] = max(0.0, state["cool"] - delta)
            dx, dz = ppos[0] - dragon.pos[0], ppos[2] - dragon.pos[2]
            dist = math.hypot(dx, dz)
            fighting = (not p.get("triggered", True) and p.get("awake")
                        and str(p.get("aggression")) == "hostile")
            if state["t"] < 0.0:
                if fighting and dist <= BREATH_RANGE and state["cool"] <= 0.0:
                    state["t"] = 0.0
                    state["dir"] = math.atan2(dx, dz)
                    state["lap"] = {}
                    for t in self.flames:
                        self._desync(t)
                    s.notify(f"{p.get('display_name', 'The dragon')} breathes fire!", 1.5)
                continue
            # Breathing: the flames follow the player, a little behind.
            want = math.atan2(dx, dz)
            turn = (want - state["dir"] + math.pi) % (2 * math.pi) - math.pi
            state["dir"] += max(-1.2 * delta, min(1.2 * delta, turn))
            state["t"] += delta
            if state["t"] >= BREATH_SECONDS:
                state["t"] = -1.0
                state["cool"] = BREATH_COOLDOWN
                continue
            burning = True
            self._place(dragon, state)
            # Anyone in the cone burns.
            state["burn"] -= delta
            off = abs((want - state["dir"] + math.pi) % (2 * math.pi) - math.pi)
            reach = min(BREATH_RANGE, state["t"] * FLAME_SPEED + 200.0)
            if state["burn"] <= 0.0 and off <= CONE_HALF_ANGLE and dist <= reach:
                state["burn"] = BURN_EVERY
                self._burn(int(p.get("breath_damage", 14) or 14), dragon)
        if not burning:
            self._park()

    def _mouth(self, dragon, direction):
        size = float(dragon.properties.get("sprite_width", 128) or 128)
        r = size * 0.42
        return (dragon.pos[0] + math.sin(direction) * r,
                dragon.pos[2] + math.cos(direction) * r)

    def _place(self, dragon, state):
        direction = state["dir"]
        mx, mz = self._mouth(dragon, direction)
        fx, fz = math.sin(direction), math.cos(direction)
        px, pz = fz, -fx
        n = len(self.flames)
        span = BREATH_RANGE * 0.85
        travelled = state["t"] * FLAME_SPEED
        y = float(dragon.pos[1])
        for k, t in enumerate(self.flames):
            # Evenly spaced along the jet, all moving outward, wrapping back to
            # the mouth: a continuous stream.
            raw = travelled + k * span / n
            lap = int(raw // span)
            if state.setdefault("lap", {}).get(k) != lap:
                # Re-emitted from the mouth: a fresh puff, out of step with
                # the rest.
                state["lap"][k] = lap
                self._desync(t)
            d = raw % span
            if d > travelled:
                d = travelled * (k / max(1, n))
            wobble = math.sin(k * 2.39 + state["t"] * 7.0)
            side = wobble * math.tan(CONE_HALF_ANGLE) * d
            t.pos = [mx + fx * d + px * side, y + 20.0, mz + fz * d + pz * side]
            grow = 0.6 + 1.4 * min(1.0, d / span)
            t.properties["width"] = 60.0 * grow
            t.properties["height"] = 90.0 * grow
            touch(t)
        self._parked = False

    def _desync(self, t):
        """Start this flame's fire animation at its own random point (and give
        it its own seed), so the jet never flickers in lockstep."""
        t.properties["effect_seed"] = random.getrandbits(31) or 1
        t._effect_animation_phase = random.random()
        runtime = getattr(self.session.logic, "session_runtime", None)
        store = getattr(runtime, "effect_store", None)
        if store is not None:
            try:
                row = store.index_of(t)
                if row >= 0:
                    store.phase[row] = random.random()
                    store.generation += 1
            except Exception:
                pass
        touch(t)

    def _park(self):
        if self._parked:
            return
        for t in self.flames:
            t.pos = [t.pos[0], PARK_DEPTH, t.pos[2]]
            touch(t)
        self._parked = True

    def _burn(self, damage, dragon=None):
        trig = getattr(self.session.logic, "trigger_runtime", None)
        if trig is None:
            return
        try:
            trig._apply_player_damage(damage, "fire", source=dragon, cause="breath")
        except TypeError:
            trig._apply_player_damage(damage)
