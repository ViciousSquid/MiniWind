"""
After the fire: what a grass fire leaves in the world, and in people.

A grass fire (:mod:`game.grass_fire`) is one **burn** from its first flame to
its last: where it burnt, when each cell burnt, and how much of it was wheat.

* **Everyone knows.** A fire is seen for miles: everyone within
  :data:`SEEN_RADIUS` knows of it, for certain, the moment it starts, and the
  news passes from mouth to mouth without losing any of its certainty -- an
  event kind tagged ``certain`` (:mod:`game.sim.rumours` tells it "It's true:
  ..."). When it is out, travellers carry it to other towns and the notice
  boards post it (the journey board's news).
* **The food is lost.** Wheat that burnt grows no grain: farmers reap
  nothing on scorched ground (:mod:`game.farm_work`), less wheat reaches the
  mill, less flour the shops, and the hungry go hungrier -- the food chain
  as it already runs (:mod:`game.windmills`, :mod:`game.flour_supply`).
* **The farmers.** A farmer whose field burnt is furious or terrified (by
  courage) for :data:`MOOD_HOURS`, and says so -- about the fire and the
  bread it cost -- when the player is near.
* **The ground recovers, then they sow.** The scorch lies for
  :data:`SCORCH_HOURS`; then it goes. Heath grows back by itself; a wheat
  field is left bare, turned earth, and its farmer works extra hard -- longer
  hours, a quicker step -- sowing it again, row by row: each row sown is
  wheat once more. A field nobody sows grows back on its own after
  :data:`WILD_REGROW_HOURS`.

Burns are kept in the state store per map, so the scorch, the bare fields,
the moods and the sowing all survive a save and a map change.
"""

from __future__ import annotations

import json

from .grass_fire import CELL, cell_of, centre_of

#: Within this distance of a fire everyone knows it is burning.
SEEN_RADIUS = 2500.0
#: Game hours the scorch lies before the ground recovers.
SCORCH_HOURS = 72.0
#: A farmer whose field burnt stays furious or terrified this long.
MOOD_HOURS = 48.0
#: How long a farmer works extra hard to sow again, once they can.
RESOW_HOURS = 48.0
#: A burnt field nobody sows grows back by itself after this long.
WILD_REGROW_HOURS = 24.0 * 7
#: A farmer sows the bare ground of their field within this distance of any
#: of their rows, and at each stop all of it within SOW_REACH.
FIELD_REACH = 260.0
SOW_REACH = 110.0
#: Wheat this thick (biome weight) in a burnt cell made it a field.
WHEAT_CELL = 0.5
#: Cells recovered per pass (each is a terrain paint change).
RECOVER_BATCH = 8
#: A farmer says something about it at most this often (game hours), and
#: only near enough to be heard.
SAY_EVERY_HOURS = 1.5
#: Farmers this courageous are furious; the rest are terrified.
FURY_COURAGE = 0.45
#: Paint for the stages after the scorch.
EARTH_ART = ("assets/sprites/miniwind/scorch/earth_0.png",
             "assets/sprites/miniwind/scorch/earth_1.png")
#: Cell stages.
SCORCHED, BARE, = 0, 1

_FURIOUS = (
    "My wheat! A whole season's bread, gone to ash.",
    "Whoever set that fire wants hanging. That was our winter.",
    "Ash, where my wheat stood. Ash!",
    "Months of work, and the fire had it in an afternoon.",
)
_TERRIFIED = (
    "Fire! It came right up to the door!",
    "If the wind had turned, we'd have burned with it.",
    "I can still smell the smoke. Gods, the smoke.",
    "I thought it would take the house. I thought it would take us.",
)
_LOST_FOOD = (
    "There'll be no flour from my field this year.",
    "Bread'll be dear this winter, you mark me.",
    "That was half the village's bread, burnt black.",
)
_SOWING = (
    "Sow it again, and quick, before the season's gone.",
    "Every row I get in now is bread at midwinter.",
    "No rest till it's all sown again.",
)
_FIRE_CRIES = ("Fire! Fire in the fields!", "Fire! Look at the smoke!", "The grass is burning!")


def _a_person(thing) -> bool:
    """Someone who can know and tell: an NPC, or a human creature (a bandit),
    not an animal."""
    p = getattr(thing, "properties", {}) or {}
    if str(p.get("type", "")) == "npc":
        return True
    return str(p.get("monster_type", "")).lower() == "human"


def _pick(options, *salt):
    import zlib
    return options[zlib.crc32("|".join(str(s) for s in salt).encode()) % len(options)]


def _register_kind():
    from .sim import events
    events.register_kind("grass_fire", tags=("notable", "certain", "fire"), loudness=SEEN_RADIUS,
                         severity=0.6, phrase="fire swept through {item}")


_register_kind()


class FireAftermath:
    def __init__(self, session):
        self.session = session
        #: Burns: {"id", "start", "end", "x", "z", "place", "cells": {key: [t, stage, wheat]}}
        self.burns = []
        self.current = None
        #: chunk -> the terrain paint before it was first scorched.
        self._snapshots = {}
        self._dirty = False
        self._next_id = 1

    # -- the store -------------------------------------------------------------
    def _key(self):
        memory = getattr(self.session, "memory", None)
        return f"fire.aftermath.{getattr(memory, 'key', '') or 'map'}"

    def persist(self) -> None:
        if not self._dirty:
            return
        out = []
        for b in self.burns:
            cells = [[k[0], k[1], round(c[0], 2), c[1], int(c[2])] for k, c in b["cells"].items()]
            if cells or b.get("end") is None:
                out.append({k: b[k] for k in ("id", "start", "end", "x", "z", "place")} | {"cells": cells})
        try:
            self.session.store.set(self._key(), json.dumps({"next": self._next_id, "burns": out},
                                                           separators=(",", ":")))
        except Exception:
            return
        self._dirty = False

    def restore(self) -> int:
        """Bring back this map's burns: scorch and bare fields painted again,
        the burnt cells unburnable until they recover. Returns cells painted."""
        self.burns, self.current, self._snapshots = [], None, {}
        try:
            raw = json.loads(self.session.store.get(self._key(), "") or "{}")
        except (TypeError, ValueError):
            raw = {}
        self._next_id = int(raw.get("next", 1) or 1)
        painted = 0
        fire = getattr(self.session, "grass_fire", None)
        for b in raw.get("burns", []) or []:
            cells = {(int(c[0]), int(c[1])): [float(c[2]), int(c[3]), bool(c[4])]
                     for c in b.get("cells", [])}
            burn = {k: b.get(k) for k in ("id", "start", "end", "x", "z", "place")}
            burn["end"] = burn["end"] if burn["end"] is not None else burn["start"]
            burn["cells"] = cells
            self.burns.append(burn)
            for key, (_t, stage, _w) in cells.items():
                if fire is not None:
                    fire.burnt.add(key)
                painted += self._paint(key, stage)
        return painted

    # -- the fire's own hooks --------------------------------------------------
    def ignited(self, x, z) -> None:
        """Grass caught at (*x*, *z*): a burn begins, if none is under way."""
        if self.current is not None:
            return
        now = self._now()
        self.current = {"id": self._next_id, "start": now, "end": None, "x": float(x),
                        "z": float(z), "place": self._place(x, z), "cells": {}}
        self._next_id += 1
        self.burns.append(self.current)
        self._dirty = True
        self._tell_everyone(x, z, "the grass")
        self._cry_fire(x, z)

    def burnt(self, key) -> None:
        """Cell *key* has burnt out (it is about to be scorched)."""
        burn = self.current
        if burn is None:
            return
        burn["cells"][key] = [self._now(), SCORCHED, self._is_wheat(key)]
        self._dirty = True

    def before_scorch(self, x, z, radius) -> None:
        """The ground at (*x*, *z*) is about to be painted with scorch: keep
        how its chunks were first, to give them back when it recovers."""
        ter = self._terrain()
        if ter is None:
            return
        bounds = (x - radius, z - radius, x + radius, z + radius)
        if all(k in self._snapshots for k in ter._chunks_in_bounds(bounds)):
            return
        for key, paint in ter.snapshot_texture_paint(bounds).items():
            self._snapshots.setdefault(key, paint)

    # -- per tick --------------------------------------------------------------
    def update(self) -> None:
        s = self.session
        now = self._now()
        fire = getattr(s, "grass_fire", None)
        if self.current is not None and (fire is None or not fire.burning):
            self._ended(self.current, now)
            self.current = None
        self._recover(now)
        self._speak(now)

    def _ended(self, burn, now) -> None:
        burn["end"] = now
        self._dirty = True
        wheat = sum(1 for c in burn["cells"].values() if c[2])
        if not burn["cells"]:
            return
        what = "the wheat" if wheat * 3 >= len(burn["cells"]) else "the heath"
        self._tell_everyone(burn["x"], burn["z"], what)
        living = getattr(self.session, "living", None)
        board = getattr(living, "board", None)
        if board is not None:
            try:
                place = board.nearest_place(burn["x"], burn["z"])
                text = (f"Fire took the wheat near {burn['place']}." if what == "the wheat"
                        else f"Fire swept the heath near {burn['place']}.")
                board.say(text, t=now, place=place, kind="fire")
            except Exception:
                pass
        if wheat:
            self._grieve(burn, now)

    # -- who knows -------------------------------------------------------------
    def _tell_everyone(self, x, z, what) -> None:
        """Everyone near enough to see the smoke knows, for certain."""
        s = self.session
        director = getattr(s, "director", None)
        if director is None:
            return
        try:
            from .sim import knowledge
            from .sim.director import actor_key
            y = s._fire_ground(x, z) if hasattr(s, "_fire_ground") else 0.0
            ev = director.emit("grass_fire", pos=[float(x), float(y), float(z)], observers=(),
                               item=f"{what} near {self._place(x, z)}")
            fact = knowledge.fact_from_event(ev, 1.0, knowledge.SOURCE_WITNESSED)
            r2 = SEEN_RADIUS * SEEN_RADIUS
            for actor in s._sim_actors():
                if actor.pos is None or (actor.pos[0] - x) ** 2 + (actor.pos[2] - z) ** 2 > r2:
                    continue
                if not _a_person(actor):
                    continue                       # hens see smoke, but don't gossip
                knowledge.learn(s.store, actor_key(actor), dict(fact))
                director.invalidate(actor)
        except Exception:
            pass

    def _cry_fire(self, x, z) -> None:
        s = self.session
        near = []
        for npc in s.npcs():
            p = npc.properties
            if p.get("dead") or npc.pos is None:
                continue
            if (npc.pos[0] - x) ** 2 + (npc.pos[2] - z) ** 2 <= 1400.0 ** 2:
                near.append(npc)
        for k, npc in enumerate(near[:3]):
            s.bark_later(npc, _pick(_FIRE_CRIES, npc.properties.get("name"), k), 0.4 + 0.7 * k)

    # -- the farmers -----------------------------------------------------------
    def _grieve(self, burn, now) -> None:
        from . import farm_work
        cells = burn["cells"]
        for npc in self.session.npcs():
            p = npc.properties
            if p.get("dead") or not farm_work.is_farmer(p):
                continue
            rows = self._rows(npc)
            lost = [r for r in rows if cell_of(r[0], r[1]) in cells]
            if not lost:
                continue
            courage = float(p.get("courage", 0.5) or 0.5)
            p["fire_mood"] = "furious" if courage >= FURY_COURAGE else "terrified"
            p["fire_mood_until"] = now + MOOD_HOURS
            p["fire_burn"] = burn["id"]
            p["resow_from"] = now + SCORCH_HOURS
            p["resow_until"] = now + SCORCH_HOURS + RESOW_HOURS
            p["fire_said"] = now - SAY_EVERY_HOURS          # free to speak at once

    def _rows(self, npc):
        p = npc.properties
        rows = p.get("_farm_rows")
        if rows is None:
            from . import farm_work
            try:
                anchor = farm_work.FarmWork()._work_spot(self.session, npc)
                rows = p["_farm_rows"] = farm_work.field_rows(self._terrain(), anchor)
            except Exception:
                rows = []
        return rows or []

    def _speak(self, now) -> None:
        s = self.session
        ppos = s._player_pos() if hasattr(s, "_player_pos") else None
        if ppos is None:
            return
        for npc in s.npcs():
            p = npc.properties
            mood = p.get("fire_mood")
            if not mood or p.get("dead") or npc.pos is None:
                continue
            if now >= float(p.get("fire_mood_until", 0.0)) and now >= float(p.get("resow_until", 0.0)):
                for k in ("fire_mood", "fire_mood_until", "fire_burn", "fire_said",
                          "resow_from", "resow_until"):
                    p.pop(k, None)
                continue
            if now - float(p.get("fire_said", -1e9)) < SAY_EVERY_HOURS:
                continue
            if (npc.pos[0] - ppos[0]) ** 2 + (npc.pos[2] - ppos[2]) ** 2 > 900.0 ** 2:
                continue
            p["fire_said"] = now
            salt = (p.get("name"), int(now))
            if self.sowing(p, now):
                line = _pick(_SOWING, *salt)
            elif now < float(p.get("fire_mood_until", 0.0)):
                pool = (_FURIOUS if mood == "furious" else _TERRIFIED) + _LOST_FOOD
                line = _pick(pool, *salt)
            else:
                line = _pick(_LOST_FOOD, *salt)
            s.bark(npc, line)

    @staticmethod
    def sowing(props, now) -> bool:
        """Whether a farmer is in the days of sowing again after a fire."""
        return float(props.get("resow_from", 1e18)) <= now < float(props.get("resow_until", -1.0))

    def sow_points(self, npc, now):
        """Where *npc* still has bare ground to sow after a fire (the scorch
        gone): the bare cells of the burnt field around their rows, as
        ``[x, z]``; empty when there are none."""
        if not self.sowing(npc.properties, now):
            return []
        rows = self._rows(npc)
        if not rows:
            return []
        reach = FIELD_REACH * FIELD_REACH
        out = []
        for b in self.burns:
            for key, c in b["cells"].items():
                if c[1] != BARE:
                    continue
                x, z = centre_of(key)
                if any((x - r[0]) ** 2 + (z - r[1]) ** 2 <= reach for r in rows):
                    out.append([x, z])
        return out

    def sow(self, x, z) -> int:
        """A farmer sows where they stand at (*x*, *z*): the bare ground
        within :data:`SOW_REACH` is wheat again. Returns cells sown."""
        sown = 0
        r2 = SOW_REACH * SOW_REACH
        for b in self.burns:
            for key in [k for k, c in b["cells"].items() if c[1] == BARE]:
                cx, cz = centre_of(key)
                if (cx - x) ** 2 + (cz - z) ** 2 <= r2:
                    self._restore(key)
                    del b["cells"][key]
                    sown += 1
        if sown:
            self._dirty = True
        return sown

    # -- the ground ------------------------------------------------------------
    def _recover(self, now) -> None:
        """The scorch goes where it has lain long enough: heath grows back,
        a wheat field is left bare for sowing; an unsown field grows back
        wild in the end. A batch at a time."""
        done = 0
        for b in self.burns:
            if b is self.current:
                continue
            for key in list(b["cells"]):
                if done >= RECOVER_BATCH:
                    return
                t, stage, wheat = b["cells"][key]
                if stage == SCORCHED and now - t >= SCORCH_HOURS:
                    if wheat:
                        b["cells"][key][1] = BARE
                        self._restore(key)
                        self._paint(key, BARE)
                    else:
                        self._restore(key)
                        del b["cells"][key]
                    done += 1
                    self._dirty = True
                elif stage == BARE and now - t >= SCORCH_HOURS + WILD_REGROW_HOURS:
                    self._restore(key)
                    del b["cells"][key]
                    done += 1
                    self._dirty = True
        self.burns = [b for b in self.burns if b["cells"] or b is self.current]

    def _restore(self, key) -> None:
        """The cell's ground as it was before the fire; it can burn again."""
        fire = getattr(self.session, "grass_fire", None)
        if fire is not None:
            fire.burnt.discard(key)
        ter = self._terrain()
        if ter is None:
            return
        cx, cz = centre_of(key)
        r = CELL * 0.95
        bounds = (cx - r, cz - r, cx + r, cz + r)
        if not all(k in self._snapshots for k in ter._chunks_in_bounds(bounds)):
            return
        try:
            ter.restore_texture_paint(bounds, self._snapshots)
        except Exception:
            pass

    def _paint(self, key, stage) -> int:
        ter = self._terrain()
        if ter is None:
            return 0
        cx, cz = centre_of(key)
        self.before_scorch(cx, cz, CELL)
        seed = (key[0] * 73856093) ^ (key[1] * 19349663)
        if stage == SCORCHED:
            art = self.session.SCORCH_ART[seed % len(self.session.SCORCH_ART)]
        else:
            art = EARTH_ART[seed % len(EARTH_ART)]
        opacity = 1.0           # solid in the middle: no grass grows through it
        try:
            return int(bool(ter.paint_texture_at(cx, cz, CELL * 0.9, art, feather=0.55,
                                                 opacity=opacity, angle=(seed % 628) / 100.0)))
        except Exception:
            return 0

    # -- helpers ---------------------------------------------------------------
    def _terrain(self):
        from . import fio
        logic = getattr(self.session, "logic", None)
        return fio.terrain(logic) if logic is not None else None

    def _now(self) -> float:
        clock = getattr(self.session, "clock", None)
        return float(clock.day) * 24.0 + float(clock.hour) if clock is not None else 0.0

    def _place(self, x, z) -> str:
        living = getattr(self.session, "living", None)
        board = getattr(living, "board", None)
        if board is None:
            return "the fields"
        try:
            key = board.nearest_place(float(x), float(z))
            return str((getattr(living, "places", {}) or {}).get(key, {}).get("name") or key or "the fields")
        except Exception:
            return "the fields"

    def _is_wheat(self, key) -> bool:
        ter = self._terrain()
        if ter is None:
            return False
        try:
            from engine import terrain_biomes as tb
            cx, cz = centre_of(key)
            w = ter.biome_weights_batch([cx], [cz])
            return bool(w.shape[1] > tb.WHEAT and w[0, tb.WHEAT] >= WHEAT_CELL)
        except Exception:
            return False
