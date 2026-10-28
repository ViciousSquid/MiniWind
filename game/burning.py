"""
Fire that stays: what a Flare leaves behind.

A spell with a ``burn`` effect (``{"kind": "burn", "magnitude": 2,
"duration": 5}`` -- Flare's) sets alight what it strikes:

* the actor it hits **burns** for the effect's ``duration`` seconds, taking
  its ``magnitude`` in fire damage a second (Flare's is 2 a second for each
  level of the spell, :data:`game.rpg.magic._PER_LEVEL_KINDS`). The flames
  use the same engine FIRE effect as the dragon's breath and die down over
  the last :data:`FADE_SECONDS`. The player burns too, when an enemy's Flare
  finds them: through the player's own damage path, so fire resistance counts,
  with the edges of the screen aglow.
* a bolt that strikes no one -- a wall, the floor -- starts a **small fire**
  where it lands. It burns for :data:`GROUND_FIRE_SECONDS`, fading out the
  same way, and sets alight anyone who walks into it.

The flames are the engine's FIRE effect (:data:`FIRE_TEXTURE`, fire02), one
per fire, moved with whoever is burning and shrunk as it fades. No separate
procedural flame particles are layered over the engine effect.
Burning is transient: nothing of it is saved.
"""

from __future__ import annotations

import math

from . import fio
from engine.effect_entity import EFFECT_DEFAULTS

#: Use the same default FIRE effect texture as the dragon's breath.
FIRE_TEXTURE = EFFECT_DEFAULTS["fire_texture"]
#: Over its last this-many seconds a fire dies down rather than going out.
FADE_SECONDS = 1.5
#: Burn damage is dealt this often (seconds), in that share of a second's.
BURN_TICK = 0.5
#: A fire on the ground: how long it burns, how near it sets someone alight,
#: and how long that burn lasts and how hard it bites (a second's damage).
GROUND_FIRE_SECONDS = 8.0
GROUND_FIRE_RADIUS = 60.0
#: How high on a burning body the flames sit, as a share of its sprite.
BODY_FLAME_LIFT = 0.15
#: Flare's fires are smaller than the dragon's, but use the same FIRE
#: texture, tint and lighting defaults.
BODY_FLAME_SIZE = (54.0, 80.0)
GROUND_FLAME_SIZE = (40.0, 58.0)
#: The screen's edges glow while the player burns.
PLAYER_TINT = ((1.0, 0.45, 0.1), 0.3)
#: The key the player's own burn is kept under.
PLAYER = "player"


def burn_of(spell):
    """``(damage a second, seconds)`` of *spell*'s ``burn`` effect, or None."""
    for e in getattr(spell, "effects", None) or ():
        if isinstance(e, dict) and e.get("kind") == "burn":
            dps, secs = float(e.get("magnitude", 0) or 0), float(e.get("duration", 0) or 0)
            if dps > 0 and secs > 0:
                return dps, secs
    return None


def strength(left, total) -> float:
    """How fiercely a fire with *left* of its *total* seconds still burns:
    full until its last :data:`FADE_SECONDS`, then dying to nothing."""
    fade = min(FADE_SECONDS, max(0.01, float(total)))
    return max(0.0, min(1.0, float(left) / fade))


class Burning:
    """Every fire burning in one session (see the module doc)."""

    def __init__(self, session):
        self.session = session
        #: key -> {"thing", "left", "total", "dps", "by", "tick", "flame"}
        self.burns = {}
        #: [{"pos", "left", "total", "dps", "secs", "by", "flame"}]
        self.fires = []

    # -- starting fires --------------------------------------------------------
    def landed(self, spell, pos, target=None, by=None) -> None:
        """A bolt of *spell* came down at *pos*, on *target* (None: on no one).
        *by* is who cast it (None: the player)."""
        burn = burn_of(spell)
        if burn is None:
            return
        dps, secs = burn
        if target is not None:
            if not (getattr(target, "properties", None) or {}).get("dead"):
                self.ignite(target, dps, secs, by)
            return
        if pos is not None:
            self.start_fire(pos, dps, secs, by)

    def ignite(self, thing, dps, seconds, by=None) -> None:
        """Set *thing* (an actor, or the player) alight for *seconds*. Lit
        again while it burns, it burns on from now -- the harder of the two."""
        is_player = thing is PLAYER or bool((getattr(thing, "properties", None) or {})
                                            .get("is_player"))
        key = PLAYER if is_player else id(thing)
        burn = self.burns.get(key)
        if burn is None:
            burn = self.burns[key] = {"thing": PLAYER if is_player else thing,
                                      "tick": BURN_TICK, "flame": None, "dps": 0.0}
            if is_player:
                self._player_tint(seconds)
            else:
                burn["flame"] = self._flame(self._body(thing), BODY_FLAME_SIZE)
        burn.update(left=float(seconds), total=float(seconds),
                    dps=max(float(dps), burn["dps"]), by=by)

    def start_fire(self, pos, dps, seconds, by=None) -> None:
        """A small fire on the ground at *pos* (see the module doc)."""
        ground = fio.ground_height(self.session.logic, pos[0], pos[2], below=pos[1] + 40.0) \
            if self.session.logic is not None else None
        y = float(ground) if ground is not None else float(pos[1]) - 40.0
        at = [float(pos[0]), y, float(pos[2])]
        self.fires.append({"pos": at, "left": GROUND_FIRE_SECONDS,
                           "total": GROUND_FIRE_SECONDS, "dps": float(dps),
                           "secs": float(seconds), "by": by,
                           "flame": self._flame([at[0], at[1] + GROUND_FLAME_SIZE[1] * 0.4, at[2]],
                                                GROUND_FLAME_SIZE)})

    def burning(self, thing) -> bool:
        if thing is PLAYER or (getattr(thing, "properties", None) or {}).get("is_player"):
            return PLAYER in self.burns
        return id(thing) in self.burns

    # -- per tick --------------------------------------------------------------
    def update(self, delta: float) -> None:
        if not self.burns and not self.fires:
            return
        delta = max(0.0, float(delta))
        for key, burn in list(self.burns.items()):
            thing = burn["thing"]
            alive = self._alive(thing)
            burn["left"] -= delta if alive else max(delta, FADE_SECONDS)
            if burn["left"] <= 0.0:
                self._put_out(burn["flame"])
                del self.burns[key]
                continue
            burn["tick"] -= delta
            if alive and burn["tick"] <= 0.0:
                burn["tick"] += BURN_TICK
                self._hurt(thing, burn["dps"] * BURN_TICK, burn["by"])
            k = strength(burn["left"], burn["total"])
            if thing is not PLAYER:
                pos = self._body(thing)
                self._place(burn["flame"], pos, BODY_FLAME_SIZE, k)
        ppos = self.session._player_pos()
        for fire in list(self.fires):
            fire["left"] -= delta
            if fire["left"] <= 0.0:
                self._put_out(fire["flame"])
                self.fires.remove(fire)
                continue
            k = strength(fire["left"], fire["total"])
            self._place(fire["flame"], [fire["pos"][0], fire["pos"][1] + GROUND_FLAME_SIZE[1] * 0.4,
                                        fire["pos"][2]], GROUND_FLAME_SIZE, k)
            if k < 1.0:
                continue                     # dying down: it no longer catches
            if ppos is not None and math.hypot(ppos[0] - fire["pos"][0],
                                               ppos[2] - fire["pos"][2]) <= GROUND_FIRE_RADIUS:
                if not self.burning(PLAYER):
                    self.ignite(PLAYER, fire["dps"], fire["secs"], fire["by"])
            for actor in (*self.session._things_of_type("npc"),
                          *self.session._things_of_type("creature")):
                p = actor.properties
                if p.get("dead") or p.get("hidden") or self.burning(actor):
                    continue
                if math.hypot(actor.pos[0] - fire["pos"][0],
                              actor.pos[2] - fire["pos"][2]) <= GROUND_FIRE_RADIUS:
                    self.ignite(actor, fire["dps"], fire["secs"], fire["by"])

    def clear(self) -> None:
        """Put every fire out at once (a map change)."""
        for burn in self.burns.values():
            self._put_out(burn["flame"])
        for fire in self.fires:
            self._put_out(fire["flame"])
        self.burns.clear()
        self.fires.clear()

    # -- internals ---------------------------------------------------------------
    def _alive(self, thing) -> bool:
        if thing is PLAYER:
            return not self.session.game.character.is_dead
        return not thing.properties.get("dead")

    @staticmethod
    def _body(thing):
        h = float(thing.properties.get("sprite_height", 112) or 112)
        return [float(thing.pos[0]), float(thing.pos[1]) - h * BODY_FLAME_LIFT,
                float(thing.pos[2])]

    def _hurt(self, thing, damage, by) -> None:
        s = self.session
        if thing is PLAYER:
            trig = getattr(s.logic, "trigger_runtime", None)
            if trig is not None:
                try:
                    trig._apply_player_damage(damage, "fire", source=by, cause="burning")
                    return
                except Exception:
                    pass
            s.game.character.damage(damage)
            return
        ai = getattr(s.logic, "monster_ai", None)
        if ai is not None:
            try:
                ai._apply_monster_damage(thing, damage, attacker=by)
                return
            except Exception:
                pass
        p = thing.properties
        p["health"] = float(p.get("health", 0) or 0) - damage
        if p["health"] <= 0:
            p["dead"] = True

    def _player_tint(self, seconds) -> None:
        fx = getattr(self.session, "magic_fx", None)
        if fx is not None:
            colour, peak = PLAYER_TINT
            fx.tint(colour, peak, 0.15, max(0.0, seconds - FADE_SECONDS), FADE_SECONDS,
                    "vignette")

    def _flame(self, pos, size):
        """A FIRE effect at *pos* (None where the engine's Effect is missing)."""
        logic = self.session.logic
        try:
            from engine.effect_entity import Effect
        except Exception:
            return None
        props = {"type": "effect", "name": "Burning", "effect_type": "FIRE",
                 "fire_texture": FIRE_TEXTURE, "preview": False, "silent": True,
                 "width": size[0], "height": size[1]}
        try:
            effect = Effect(pos=list(pos), properties=props)
            fio.things(logic).append(effect)
            fio.rebuild_entity_caches(logic)
            store = getattr(getattr(logic, "session_runtime", None), "effect_store", None)
            if store is not None:
                store.sync_authored(effect)
        except Exception:
            return None
        return effect

    @staticmethod
    def _place(effect, pos, size, k) -> None:
        """Move *effect* to *pos* at *k* (0..1) of its full *size* and light."""
        if effect is None:
            return
        effect.pos = [float(pos[0]), float(pos[1]), float(pos[2])]
        p = effect.properties
        p["width"] = size[0] * (0.25 + 0.75 * k)
        p["height"] = size[1] * (0.25 + 0.75 * k)
        p["light_intensity"] = EFFECT_DEFAULTS["light_intensity"] * k
        try:
            from engine.change_journal import touch
            touch(effect)
        except Exception:
            pass

    def _put_out(self, effect) -> None:
        if effect is None:
            return
        logic = self.session.logic
        try:
            things = fio.things(logic)
            if effect in things:
                things.remove(effect)
            fio.rebuild_entity_caches(logic)
        except Exception:
            pass
