"""
Rewinding the simulation (debug tools).

While the Debug Tools window is open, the session keeps a short history of
the world -- every :data:`INTERVAL` seconds of *game* time, up to
:data:`HISTORY_SECONDS` of it: the player (where they stand and face, and
the whole character sheet), the clock, and every actor the simulation is
running (where each stands and all its state). Nothing is recorded while
the window is shut, so it costs nothing in play.

:meth:`Rewind.back` steps back through that history, pausing the world on
the moment it lands on; playing on from there carries on from that moment
and forgets what came after. Far-off actors that Big World has parked are not
recorded -- they were not moving anyway.
"""

from __future__ import annotations

import collections
import copy

from . import fio

INTERVAL = 0.5
HISTORY_SECONDS = 120.0
#: The world-pause request rewinding holds (its own owner).
PAUSE_OWNER = "debug_rewind"


def _copy_props(props):
    return {k: (copy.deepcopy(v) if isinstance(v, (list, dict, set)) else v)
            for k, v in props.items()}


class Rewind:
    def __init__(self, session):
        self.session = session
        self.recording = False
        self.history = collections.deque(maxlen=int(HISTORY_SECONDS / INTERVAL))
        self._since = 0.0
        #: Seconds stepped back from the newest moment (0 when live).
        self.behind = 0.0

    # -- recording ---------------------------------------------------------
    def start(self) -> None:
        self.recording = True

    def stop(self) -> None:
        self.recording = False
        self.history.clear()
        self.behind = 0.0

    def tick(self, delta: float) -> None:
        if not self.recording:
            return
        self._since += float(delta)
        if self._since < INTERVAL and self.history:
            return
        self._since = 0.0
        self.history.append(self._capture())
        self.behind = 0.0

    def seconds(self) -> float:
        return max(0.0, (len(self.history) - 1) * INTERVAL)

    def _capture(self):
        s = self.session
        player = fio.player(s.logic)
        pr = fio.player_runtime(s.logic)
        actors = []
        for t in list(getattr(s, "_actors", ())) + list(getattr(s, "_dead_actors", ())):
            p = getattr(t, "properties", None)
            if isinstance(p, dict) and not p.get("_bw_parked_hidden"):
                actors.append((t, list(t.pos), _copy_props(p)))
        return {
            "clock": (s.clock.day, s.clock.hour),
            "player": None if player is None else (
                (float(player.pos.x), float(player.pos.y), float(player.pos.z)),
                float(getattr(player, "angle", 0.0))),
            "player_health": getattr(pr, "player_health", None) if pr else None,
            "character": copy.deepcopy(s.game.character.to_dict()),
            "actors": actors,
        }

    # -- rewinding -----------------------------------------------------------
    def back(self, seconds: float = 1.0) -> bool:
        """Step back *seconds* through the history and restore that moment,
        paused. False when there is nothing to go back to."""
        steps = max(1, int(round(float(seconds) / INTERVAL)))
        if len(self.history) < 2:
            return False
        for _ in range(min(steps, len(self.history) - 1)):
            self.history.pop()
        self._restore(self.history[-1])
        self.behind += steps * INTERVAL
        self._since = 0.0
        fio.set_world_paused(self.session.logic, PAUSE_OWNER, True)
        return True

    def resume(self) -> None:
        fio.set_world_paused(self.session.logic, PAUSE_OWNER, False)

    def _restore(self, snap) -> None:
        s = self.session
        from engine.change_journal import touch
        for t, pos, props in snap["actors"]:
            t.properties.clear()
            t.properties.update(_copy_props(props))
            t.pos = list(pos)
            touch(t)
        day, hour = snap["clock"]
        s.clock.day, s.clock.hour = day, hour
        player = fio.player(s.logic)
        if player is not None and snap["player"] is not None:
            (x, y, z), angle = snap["player"]
            player.pos.x, player.pos.y, player.pos.z = x, y, z
            player.angle = angle
            vel = getattr(player, "velocity", None)
            if vel is not None:
                vel.x = vel.y = vel.z = 0.0
        try:
            from .rpg.character import Character
            restored = Character.from_dict(copy.deepcopy(snap["character"]))
            s.game.character.__dict__.update(restored.__dict__)
        except Exception as exc:
            print(f"[MiniWind] rewind: character not restored: {exc}")
        pr = fio.player_runtime(s.logic)
        if pr is not None and snap.get("player_health") is not None:
            pr.player_health = snap["player_health"]
        try:
            s._sync_engine_health(full=True)
        except Exception:
            pass
        s.arrows_in_flight = []
        fio.rebuild_entity_caches(s.logic)


def resurrect(session, thing) -> bool:
    """Bring *thing* back to life at full health, whatever killed it (a debug
    command: even a gibbed body). A living actor is simply healed."""
    p = getattr(thing, "properties", None)
    if not isinstance(p, dict):
        return False
    name = p.get("display_name") or p.get("name") or "It"
    was_dead = bool(p.get("dead"))
    p.pop("gibbed", None)
    p.pop("gib_sprite", None)
    p.pop("_death_noted", None)
    p.pop("_aggro_target", None)
    if not session._revive_actor(thing):
        return False
    # Back to how it behaves alive: a hostile hunts, others go about their day.
    if str(p.get("aggression")) == "hostile":
        p["triggered"] = False
        p["wake_on_sight"] = True
    else:
        p["triggered"] = True
    p["awake"] = False
    # Nothing remembers it as dead any more.
    if p.get("name"):
        session.store.set("dead." + str(p["name"]), "false")
    try:
        key = session.memory.actor_key(thing)
        session.memory.record["dead"].pop(key, None)
        session.memory._known_dead.discard(key)
        session.memory.save()
    except Exception:
        pass
    ai = getattr(session.logic, "monster_ai", None)
    states = getattr(ai, "monster_states", None)
    if isinstance(states, dict):
        states.pop(id(thing), None)
    session.notify(f"{name} {'rises again' if was_dead else 'is restored to full health'}", 2.5)
    return True
