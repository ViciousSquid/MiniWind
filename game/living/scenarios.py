"""
Dynamic game mode: a director that authors scenes on the roads.

In **Normal** mode nothing here runs. The storyteller (``game/sim/storyteller``)
is only allowed to pace what the world already holds -- it samples and biases
journeys, intents and destinations that exist, and never makes anything up.

**Dynamic** mode (pause menu › Options › Game mode, ``[GAME] game_mode``)
licenses this module to *author*: it stages scenes on the road ahead of the
player so that they walk into them as if by chance -- a trader being robbed, a
townsperson out to settle a score with the gang that wronged them, a cult rite
with a captive at its centre, brigands lying in wait after dark. Authored is not
invented, though. Every scene is cast from the world as it stands:

* **The people are real.** Victims are travellers already on the board, or
  townsfolk (as themselves: the same name, face, dialogue and purse) taken off
  their schedule while out of sight. Gangs and patrols already on the roads are
  borrowed before any new party is made.
* **The motives are real.** An avenger goes out only over a grievance they
  actually hold: a death, an attack or a theft by an outlaw that they
  witnessed or were told of (``game/sim/knowledge``). Someone who comes to
  settle a score with the player does so over their own cached intent toward
  them, backed by their own memory (``storyteller.justification``) -- the
  director only decides that the meeting happens now, on this road.
* **The outcome is the world's.** A scene plays out whether or not the player
  steps in: actors in reach fight for real; unmet, the board resolves it with
  its ordinary dice, an avenger walks on toward their quarry, and a captive the
  cult is left with is lost. News of it spreads as any news does, and what the
  townsfolk learn feeds their own grievances in turn.

Every scene is written to the storyteller's activity feed, so what was authored
is always on the record.

Pacing follows an intensity meter fed by what the player is actually going
through -- health lost, hostiles fighting close by -- in four phases:

* ``build``   scenes are staged, one after another, until intensity peaks;
* ``sustain`` the peak is allowed to play out for a few seconds;
* ``fade``    nothing new is staged until intensity drops and the fighting ends;
* ``relax``   a real rest: only peaceful scenes (someone grateful), then build
  again.

A badly hurt player gets the relax rules whatever the phase. Threats are always
staged out of sight (beyond any actor's sight range) and ahead of the player,
on a road they are on. The storyteller's own state (``CALM`` … ``RESPITE``)
scales how often and how hard.

Pure Python apart from the session it is handed; tuning is in the constants.
"""

from __future__ import annotations

import copy
import json
import math
from typing import Dict, List, Optional

from . import journeys as jn
from . import roads

#: The store key the director's scenes are saved under.
STORE_KEY = "living.scenarios"

# -- pacing (real seconds unless stated) ------------------------------------
#: Intensity at which build-up stops and the peak is sustained.
PEAK = 0.8
#: Intensity below which a fade may turn into a rest.
RELAX_BELOW = 0.25
#: How long the peak is held, and how long a rest lasts.
SUSTAIN_SECONDS = (8.0, 15.0)
RELAX_SECONDS = (60.0, 120.0)
#: The first rest of a session (the world gets going first).
FIRST_RELAX = 40.0
#: Between two scenes staged during build-up.
BUILD_GAP = (45.0, 90.0)
#: Intensity gained per whole health bar lost, and per second per hostile
#: fighting near the player; lost per second when calm / while threatened.
DAMAGE_GAIN = 2.5
ENGAGED_GAIN = 0.02
CALM_DECAY = 0.04
TENSE_DECAY = 0.01
#: Hostiles nearer than this count toward intensity.
THREAT_RADIUS = 1500.0
#: A player below this fraction of health is spared new threats.
HURT = 0.45
#: Most scenes in play at once.
MAX_SCENES = 2
#: The storyteller's state scales the gap between scenes and hostile weights.
STATE_GAP = {"CALM": 1.0, "RISING": 0.8, "PEAK": 0.7, "RESPITE": 1.6}
STATE_HOSTILE = {"CALM": 1.0, "RISING": 1.3, "PEAK": 1.5, "RESPITE": 0.4}

# -- staging (world units; game hours) --------------------------------------
#: Staged this far from the player at least: out of every actor's sight.
STAGE_MIN = 1150.0
#: Staged no further than this (and within the region journeys go live in).
STAGE_MAX = 1900.0
#: The player must be this near a road for it to count as theirs.
ON_ROAD = 900.0
#: Hostile scenes are not staged this near a town.
TOWN_CLEAR = 900.0
#: How far down the road an avenger's quarry waits beyond them.
QUARRY_GAP = 750.0
#: A held party waits this long (game hours) before the world moves on.
HOLD_HOURS = 3.0
#: A cult holds its captive this long before the rite is finished.
RITE_HOURS = 2.5
#: The player is told of a scene once, from this near.
HINT_RADIUS = 1300.0
#: A rescued party thanks the player from this near.
THANK_RADIUS = 380.0
#: Grievances older than this (game days) no longer send anyone out.
GRIEVANCE_DAYS = 10
#: Decisions kept for the debug window (console ``storyteller``).
DECISION_CAP = 60

#: Each scene kind in plain words, for the decision log.
SCENE_NAMES = {"waylaid": "a traveller waylaid", "avenger": "a townsperson out for revenge",
               "reckoning": "someone settling a score with you",
               "gratitude": "someone grateful to you", "cult_rite": "a cult rite with a captive",
               "procession": "a cult procession", "ambush": "an ambush",
               "patrol": "the watch fighting brigands"}
PHASE_NAMES = {"build": "Building tension", "sustain": "At the peak",
               "fade": "Easing off", "relax": "Resting"}

PEACEFUL_KINDS = ("market", "trader", "caravan", "pilgrims", "courier", "minstrel")
OUTLAW_FACTIONS = ("bandits", "cultists", "monsters")
TOWNS = jn.TOWNS

HINTS = {
    "waylaid": ("Shouts carry from the road ahead.", "Someone is crying for help up the road."),
    "avenger": ("Someone waits by the road ahead, blade in hand.",),
    "cult_rite": ("A low chanting drifts through the dark.", "Torchlight flickers off the road ahead."),
    "procession": ("Hooded figures walk the road ahead.",),
    "ambush": ("The road ahead has gone very quiet.",),
    "patrol": ("Steel rings out on the road ahead.",),
    "reckoning": ("Someone is walking the road toward you with purpose.",),
    "gratitude": ("A familiar face is coming down the road.",),
}


def _hour(t):
    return float(t) % 24.0


def is_night(t) -> bool:
    h = _hour(t)
    return h >= 20.0 or h < 5.0


def is_dusk(t) -> bool:
    return 18.0 <= _hour(t) < 20.0


def _now_hours(clock) -> float:
    return float(clock.day) * 24.0 + float(clock.hour)


def _sub_route(route, cum, s, toward_start):
    """The road from *s* along *route* to one end, as a fresh route."""
    x, z, seg = roads.point_at(route, cum, s)
    tail = list(reversed(route[:seg + 1])) if toward_start else list(route[seg + 1:])
    pts = [(x, z)]
    for p in tail:
        if math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 1.0:
            pts.append(tuple(p))
    if len(pts) < 2:
        end = route[0] if toward_start else route[-1]
        pts.append((end[0] + 1.0, end[1] + 1.0))
    return pts


class ScenarioDirector:
    """Dynamic mode's scene author (module docstring). Owned by LivingWorld."""

    def __init__(self, world):
        self.world = world
        #: scene id -> plain dict (persisted)
        self.scenes: Dict[str, Dict] = {}
        self.next_id = 1
        #: What it decided and why, oldest first: ``{"time", "kind", "text",
        #: "data"}`` -- *text* plain English, *data* the raw numbers.
        self.decisions: List[Dict] = []
        #: Called with each new decision (console ``storyteller watch on``).
        self.listeners: List = []
        self._why = ""
        self.reset_pacing()

    def _decide(self, kind, text, merge="", **data):
        """Log a decision. *merge*: an entry with the same key replaces the
        newest one if that is also it (a wait counting down is one line)."""
        try:
            now = _now_hours(self.session.clock)
        except Exception:
            now = None
        raw = {"phase": self.phase, "intensity": round(self.intensity, 3)}
        raw.update(data)
        entry = {"time": now, "kind": kind, "text": str(text), "data": raw, "merge": merge}
        if merge and self.decisions and self.decisions[-1].get("merge") == merge:
            if self.decisions[-1]["text"] == entry["text"]:
                self.decisions[-1].update(time=now, data=raw)
                return
            self.decisions[-1] = entry
        else:
            self.decisions.append(entry)
            del self.decisions[:-DECISION_CAP]
        for listener in tuple(self.listeners):
            try:
                listener(dict(entry))
            except Exception:
                pass

    def _no(self, why):
        """A scene could not be cast: remember why, for the log."""
        self._why = why
        return None

    def reset_pacing(self):
        self.phase = "relax"
        self.phase_left = FIRST_RELAX
        self.intensity = 0.0
        self.gap_left = 0.0
        self._last_health = None
        self._peaceful_done = False

    # -- the switch ----------------------------------------------------------
    @property
    def session(self):
        return self.world.session

    @property
    def board(self):
        return self.world.board

    def enabled(self) -> bool:
        check = getattr(self.session, "dynamic_mode_enabled", None)
        try:
            return bool(check()) if check is not None else False
        except Exception:
            return False

    # -- the clock -------------------------------------------------------------
    def tick(self, t: float, dt: float = 1.0) -> None:
        """Once per board update: pace, and perhaps stage a scene."""
        if self.board is None:
            return
        if not self.enabled():
            if self.scenes:
                self._stand_down_all(t)
            self._last_health = None
            return
        self._forget_finished()
        self._pace(dt)
        if len(self.scenes) >= MAX_SCENES:
            self._decide("wait", f"Waiting: {len(self.scenes)} scenes are already in play "
                         f"(at most {MAX_SCENES}).", merge="wait", scenes=list(self.scenes))
            return
        if self.phase in ("sustain", "fade"):
            return                          # the phase change said why
        if self.gap_left > 0.0:
            self._decide("wait", f"Waiting: the next scene in about {math.ceil(self.gap_left / 10) * 10:.0f} "
                         "seconds.", merge="wait", gap_seconds=round(self.gap_left, 1))
            return
        # Resting, or badly hurt: at most one peaceful scene per rest.
        hurt = self._health() < HURT
        peaceful_only = self.phase == "relax" or hurt
        if peaceful_only and self._peaceful_done:
            why = (f"you are badly hurt ({self._health():.0%} health), so no new threats"
                   if hurt else "resting; the one peaceful meeting a rest allows has been tried")
            self._decide("wait", f"Holding back: {why}.", merge="wait", health=round(self._health(), 3))
            return
        scene = self._cast(t, peaceful_only)
        if peaceful_only:
            self._peaceful_done = True      # one peaceful try per rest, met or not
        if scene is None:
            self.gap_left = 10.0            # nothing fits here: look again soon
            return
        gap = self.session.rng.uniform(*BUILD_GAP) * STATE_GAP.get(self._story_state(), 1.0)
        self.gap_left = gap

    def _health(self) -> float:
        try:
            c = self.session.game.character
            return float(c.health) / max(1.0, float(c.max_health))
        except Exception:
            return 1.0

    def _engaged_hostiles(self) -> int:
        s = self.session
        ppos = s._player_pos()
        if ppos is None:
            return 0
        count = 0
        npcs = getattr(s, "npcs", None)
        try:
            actors = list(npcs()) if npcs is not None else []
        except Exception:
            actors = []
        for x in actors:
            p = x.properties
            if p.get("dead") or x.pos is None:
                continue
            if p.get("faction") not in OUTLAW_FACTIONS and str(p.get("aggression")) != "hostile":
                continue
            if p.get("triggered") is not False:
                continue
            if math.hypot(x.pos[0] - ppos[0], x.pos[2] - ppos[2]) <= THREAT_RADIUS:
                count += 1
        return count

    def _pace(self, dt: float) -> None:
        """The intensity meter and the four phases."""
        health = self._health()
        if self._last_health is not None and health < self._last_health:
            gain = (self._last_health - health) * DAMAGE_GAIN
            self.intensity += gain
            self._decide("intensity", f"You were hurt (lost {self._last_health - health:.0%} of your "
                         f"health): tension up {min(gain, 1.0):.0%}.", merge="hurt",
                         health=round(health, 3), gain=round(gain, 3))
        self._last_health = health
        engaged = self._engaged_hostiles()
        self.intensity += engaged * ENGAGED_GAIN * dt
        self.intensity -= (TENSE_DECAY if engaged else CALM_DECAY) * dt
        self.intensity = max(0.0, min(1.0, self.intensity))
        self.gap_left = max(0.0, self.gap_left - dt)
        rng = self.session.rng
        if self.phase == "build":
            if self.intensity >= PEAK:
                self._enter("sustain", rng.uniform(*SUSTAIN_SECONDS))
        elif self.phase == "sustain":
            self.phase_left -= dt
            if self.phase_left <= 0.0:
                self._enter("fade", 0.0)
        elif self.phase == "fade":
            if self.intensity < RELAX_BELOW and not engaged:
                self._enter("relax", rng.uniform(*RELAX_SECONDS))
        elif self.phase == "relax":
            self.phase_left -= dt
            if self.phase_left <= 0.0:
                self._enter("build", 0.0)

    def _enter(self, phase, seconds):
        before = self.phase
        self.phase, self.phase_left = phase, float(seconds)
        if phase == "relax":
            self._peaceful_done = False
        if phase == "build":
            self.gap_left = 0.0
        text = {
            "sustain": (f"Tension peaked ({self.intensity:.0%}): letting it play out for "
                        f"{seconds:.0f} seconds before easing off."),
            "fade": ("Easing off: nothing new until tension drops below "
                     f"{RELAX_BELOW:.0%} and the fighting near you ends."),
            "relax": (f"Things have calmed down: a rest of {seconds:.0f} seconds, "
                      "with at most one peaceful meeting."),
            "build": "The rest is over: building tension again, one scene at a time.",
        }[phase]
        self._decide("phase", text, previous=before, seconds=round(float(seconds), 1))

    def _story_state(self) -> str:
        story = getattr(self.session, "storyteller", None)
        return str(getattr(story, "state", "CALM") or "CALM") if story is not None else "CALM"

    def _narrate(self, text: str, log=True, **data) -> None:
        if log:
            self._decide("world", text, **data)
        story = getattr(self.session, "storyteller", None)
        narrate = getattr(story, "narrate", None)
        if narrate is not None:
            try:
                narrate("dynamic", text, _now_hours(self.session.clock))
            except Exception:
                pass

    # -- choosing a scene ------------------------------------------------------
    def _cast(self, t: float, peaceful_only: bool) -> Optional[Dict]:
        rng = self.session.rng
        hostile = STATE_HOSTILE.get(self._story_state(), 1.0)
        night, dusk = is_night(t), is_dusk(t)
        options = [("gratitude", 4.0)]
        if not peaceful_only:
            options += [("waylaid", 3.0 * hostile), ("avenger", 3.0 * hostile),
                        ("reckoning", 3.0 * hostile), ("patrol", 1.5 * hostile)]
            if night:
                options += [("cult_rite", 3.0 * hostile), ("ambush", 2.0 * hostile),
                            ("procession", 1.5 * hostile)]
            elif dusk:
                options += [("ambush", 1.0 * hostile)]
        tried, rejected = set(), {}
        while len(tried) < len(options):
            left = [(k, w) for k, w in options if k not in tried and w > 0]
            if not left:
                break
            kind = rng.choices([k for k, _ in left], weights=[w for _, w in left])[0]
            tried.add(kind)
            self._why = ""
            scene = getattr(self, "_stage_" + kind)(t)
            if scene is not None:
                self._log_cast(scene, options, rejected, peaceful_only, night, dusk)
                return scene
            rejected[kind] = self._why or "it did not fit here"
        why = "; ".join(f"{SCENE_NAMES.get(k, k)}: {r}" for k, r in rejected.items())
        self._decide("skip", f"Nothing could be staged here. {why[:1].upper() + why[1:]}.",
                     merge="skip", options=dict(options), rejected=rejected,
                     peaceful_only=peaceful_only, night=night)
        return None

    def _log_cast(self, scene, options, rejected, peaceful_only, night, dusk):
        """Say why this scene, now: the moment, the choices, the casting."""
        moment = ("resting, so only a peaceful meeting" if self.phase == "relax" else
                  "you are hurt, so only a peaceful meeting" if peaceful_only else
                  f"building tension ({self.intensity:.0%})")
        when = "night, so cults and ambushes were possible" if night else (
            "dusk, so an ambush was possible" if dusk else "daytime, so no cult scenes")
        passed = ""
        if rejected:
            passed = " Passed over: " + "; ".join(
                f"{SCENE_NAMES.get(k, k)} ({r})" for k, r in rejected.items()) + "."
        text = (f"{scene.get('text', '')} Why {SCENE_NAMES.get(scene['kind'], scene['kind'])}: "
                f"{moment}; it is {when}; the storyteller is {self._story_state()}.{passed}")
        self._decide("stage", text, scene=scene["id"], scene_kind=scene["kind"],
                     options={k: round(w, 2) for k, w in options}, rejected=rejected,
                     storyteller_state=self._story_state(), position=[round(scene["x"]), round(scene["z"])],
                     journeys=dict(scene["journeys"]))

    # -- the road ahead --------------------------------------------------------
    def _road_keys(self):
        return list(self.board.network.place_node)

    def _road_ahead(self, hostile=True, min_d=STAGE_MIN, max_d=STAGE_MAX, rng_jitter=0.3):
        """A point on a road the player is on, ahead of them and out of sight:
        ``(route, cum, s_player, s_stage, dirn, start_key, end_key, x, z)``."""
        s = self.session
        ppos = s._player_pos()
        if ppos is None:
            return None
        px, pz = ppos[0], ppos[2]
        board = self.board
        max_d = min(max_d, self.world.reach() * 0.92)
        if max_d <= min_d:
            return None
        keys = self._road_keys()
        if len(keys) < 2:
            return None
        keys.sort(key=lambda k: math.hypot(board.places[k]["x"] - px, board.places[k]["z"] - pz))
        fwd = s._player_forward() if hasattr(s, "_player_forward") else (0.0, 0.0, 1.0)
        fx, fz = float(fwd[0]), float(fwd[2])
        fl = math.hypot(fx, fz) or 1.0
        fx, fz = fx / fl, fz / fl
        towns = [k for k in keys if board.places[k].get("kind") in TOWNS]
        best, best_score = None, -math.inf
        for a in keys[:2]:
            for b in keys[:9]:
                if a == b:
                    continue
                route = board._route(a, b)
                if route is None:
                    continue
                cum = roads.cumulative(route)
                sp = roads.project(route, cum, px, pz)
                rx, rz, _ = roads.point_at(route, cum, sp)
                if math.hypot(rx - px, rz - pz) > ON_ROAD:
                    continue
                for dirn in (1, -1):
                    for step in range(6):
                        d = min_d + (max_d - min_d) * step / 5.0
                        ss = sp + dirn * d
                        if ss <= 0.0 or ss >= cum[-1]:
                            continue
                        x, z, _ = roads.point_at(route, cum, ss)
                        dist = math.hypot(x - px, z - pz)
                        if dist < min_d * 0.85 or dist > max_d:
                            continue
                        if hostile and any(math.hypot(board.places[k]["x"] - x,
                                                      board.places[k]["z"] - z) < TOWN_CLEAR
                                           for k in towns):
                            continue
                        ahead = ((x - px) * fx + (z - pz) * fz) / max(1.0, dist)
                        score = ahead + s.rng.uniform(0.0, rng_jitter)
                        if score > best_score:
                            best_score = score
                            best = (route, cum, sp, ss, dirn, a, b, x, z)
        return best

    def _toward_player(self, spot):
        """Route from the staged point back toward (and past) the player."""
        route, cum, _sp, ss, dirn, a, b, _x, _z = spot
        return _sub_route(route, cum, ss, toward_start=dirn > 0), (a if dirn > 0 else b)

    def _away_from_player(self, spot, extra=0.0):
        route, cum, _sp, ss, dirn, a, b, _x, _z = spot
        s2 = max(0.0, min(cum[-1], ss + dirn * extra))
        return _sub_route(route, cum, s2, toward_start=dirn < 0), (b if dirn > 0 else a)

    # -- making and borrowing parties -----------------------------------------
    def _new_id(self) -> str:
        sid = f"dyn{self.next_id}"
        self.next_id += 1
        return sid

    def _new_journey(self, kind, members, route, dest, t, home=None) -> jn.Journey:
        board = self.board
        jid = f"j{board.next_id}"
        board.next_id += 1
        speed = board.walk_per_hour * float(jn.kind_spec(kind).get("speed", 1.0))
        origin = self._place_at(*route[0])
        j = jn.Journey(jid, kind, members, origin, dest, route, t, speed, 1, home or origin)
        j.news = list(board.heard.get(origin, []))[-8:]
        j.quest = {}
        board.journeys[jid] = j
        return j

    def _place_at(self, x, z):
        keys = self._road_keys()
        board = self.board
        return min(keys, key=lambda k: math.hypot(board.places[k]["x"] - x,
                                                  board.places[k]["z"] - z)) if keys else ""

    def _hold(self, j, x, z, scene_id, role, t, hours=HOLD_HOURS, greeting="",
              wander=90.0, borrowed=False):
        """Stage *j* at (x, z): it waits there (as a rest) for *hours*."""
        stage = {"x": float(x), "z": float(z), "scene": scene_id, "role": role,
                 "wander": float(wander), "borrowed": bool(borrowed)}
        if greeting:
            stage["greeting"] = greeting
        if borrowed and j.stage is None:
            stage["was_dest"] = j.dest
        j.stage = stage
        j.state = "rest"
        j.rest_until = float(t) + float(hours)
        j.route = [(float(x), float(z)), (float(x) + 1.0, float(z) + 1.0)]
        j.cum = roads.cumulative(j.route)
        j.fought = []

    def _walking(self, j, route, dest, scene_id, role, t, greeting="", borrowed=False):
        """Stage *j* walking *route* (toward *dest*) from now."""
        stage = {"x": float(route[0][0]), "z": float(route[0][1]), "scene": scene_id,
                 "role": role, "walking": True, "borrowed": bool(borrowed)}
        if greeting:
            stage["greeting"] = greeting
        j.stage = stage
        j.route = [tuple(p) for p in route]
        j.cum = roads.cumulative(j.route)
        j.depart_t = float(t)
        j.dest = dest
        j.state = "travel"
        j.fought = []

    def _borrow(self, kinds, near_xz, max_dist=9000.0):
        """The nearest journey of *kinds* that is off screen and unstaged."""
        x, z = near_xz
        t = _now_hours(self.session.clock)
        best, best_d = None, max_dist
        for j in self.board.journeys.values():
            if j.kind not in kinds or j.live or j.stage is not None or j.state == "done" \
                    or not j.alive() or j.cause or j.resident and j.kind != "market":
                continue
            if getattr(self.world, "flour_roads", None) is not None and self.world.flour_roads.handles(j):
                continue
            jx, jz = self.world._abstract_pos(j, t)
            d = math.hypot(jx - x, jz - z)
            if d < best_d:
                best, best_d = j, d
        return best

    def _gang(self, near_xz, t, kind="bandits"):
        """A gang for a scene: borrowed from the roads if one is about, else
        set out from the nearest camp. ``(journey, borrowed)``."""
        j = self._borrow((kind,), near_xz)
        if j is not None:
            return j, True
        if kind == "cultists":
            members = [self.board._member("cult_leader")]
            members += [self.board._member("cultist") for _ in range(self.session.rng.randint(2, 3))]
        else:
            spec = jn.KINDS[kind]
            members = [self.board._member(role) for role, (lo, hi) in spec["members"]
                       for _ in range(self.session.rng.randint(lo, hi))]
        camps = self.board.places_of(jn.CAMPS) or self._road_keys()
        if not camps or not members:
            return None, False
        x, z = near_xz
        home = min(camps, key=lambda k: math.hypot(self.board.places[k]["x"] - x,
                                                   self.board.places[k]["z"] - z))
        j = self._new_journey(kind, members, [(x, z), (x + 1.0, z + 1.0)], home, t, home=home)
        return j, False

    def _resident_member(self, thing, rid) -> Dict:
        p = thing.properties
        return {"role": p.get("npc_role", "villager"), "name": p.get("name", rid),
                "display": p.get("display_name", p.get("name", "Someone")),
                "health": p.get("health", 60), "max_health": p.get("max_health", p.get("health", 60)),
                "damage": p.get("damage", 5), "style": "melee", "alive": True,
                "gold": self.session.rng.randint(15, 45), "head": p.get("head", ""),
                "resident": rid}

    def _can_take(self, rid) -> bool:
        board = self.board
        return (rid not in board.residents_on_trips
                and board.hooks.resident_can_leave(rid))

    def _take_resident(self, j, rid):
        """Townsperson *rid* is away from home as party *j* (hidden at home)."""
        j.resident = rid
        self.board.residents_on_trips[rid] = j.id
        self.board.hooks.resident_left(rid, j)

    def _record(self, sid, kind, journeys: Dict[str, str], x, z, t, **extra) -> Dict:
        scene = {"id": sid, "kind": kind, "journeys": journeys, "x": float(x), "z": float(z),
                 "t": float(t), "hinted": False, "resolved": False}
        scene.update(extra)
        self.scenes[sid] = scene
        if scene.get("text"):
            self._narrate(scene["text"], log=False)   # _log_cast says it, with why
        return scene

    @staticmethod
    def _keep_apart(*js):
        """Parties staged to meet live are not settled first by the board's dice."""
        for a in js:
            for b in js:
                if a is not b and b.id not in a.fought:
                    a.fought.append(b.id)

    # -- the scenes ------------------------------------------------------------
    def _stage_waylaid(self, t):
        """A real traveller on the roads, set upon by a real gang ahead."""
        spot = self._road_ahead(hostile=True)
        if spot is None:
            return self._no("no road the player is on has a free spot out of sight ahead")
        x, z = spot[7], spot[8]
        victim = self._borrow(PEACEFUL_KINDS, (x, z))
        if victim is None:
            return self._no("no peaceful traveller off screen within reach to be waylaid")
        gang, borrowed = self._gang((x, z), t)
        if gang is None:
            return self._no("no gang on the roads and no camp to send one from")
        sid = self._new_id()
        self._hold(victim, x, z, sid, "victim", t, borrowed=True, wander=40.0)
        ux, uz = self._side_offset(spot, 130.0)
        self._hold(gang, x + ux, z + uz, sid, "attacker", t, borrowed=borrowed, wander=60.0)
        self._keep_apart(victim, gang)
        who = victim.describe()
        near = self.board.place_name(self._place_at(x, z))
        return self._record(sid, "waylaid", {"victim": victim.id, "attacker": gang.id}, x, z, t,
                            reward=True,
                            text=f"Staged an attack on {who} by {gang.describe()} on the road near {near}.")

    def _side_offset(self, spot, d):
        route, cum, _sp, ss, _dirn = spot[:5]
        x0, z0, seg = roads.point_at(route, cum, ss)
        nxt = route[min(len(route) - 1, seg + 1)]
        dx, dz = nxt[0] - x0, nxt[1] - z0
        dl = math.hypot(dx, dz) or 1.0
        return dx / dl * d, dz / dl * d

    def _grievances(self):
        """Townsfolk who hold a real grievance against an outlaw:
        ``[(thing, rid, fact, tie)]``, freshest first."""
        s = self.session
        from ..sim import appraisal, knowledge
        from ..sim.director import actor_key
        store = getattr(s, "store", None)
        if store is None:
            return []
        day = int(getattr(s.clock, "day", 0) or 0)
        out = []
        for rid, thing in list(self.world._residents.items()):
            p = thing.properties
            if p.get("dead") or str(p.get("type", "npc")) != "npc" \
                    or p.get("faction") not in ("villagers", None, ""):
                continue
            key = actor_key(thing)
            try:
                facts = knowledge.facts_view(store, key)
            except Exception:
                continue
            for f in facts:
                if f.get("kind") not in ("death", "attack", "theft"):
                    continue
                if f.get("actor_faction") not in OUTLAW_FACTIONS:
                    continue
                if float(f.get("certainty", 0)) < 0.5 or day - int(f.get("day", 0) or 0) > GRIEVANCE_DAYS:
                    continue
                victim = f.get("target", "")
                tie = "" if victim == key else appraisal.relationship_to(
                    p, victim, f.get("target_name", ""))
                if victim != key and tie not in appraisal.WARM_TIES:
                    continue
                out.append((thing, rid, f, tie))
        out.sort(key=lambda row: (-int(row[2].get("day", 0) or 0), -float(row[2].get("hour", 0) or 0)))
        return out

    def _culprit_gang(self, fact):
        """The very party the culprit rides with, if they are on the roads."""
        from ..sim.director import actor_key
        culprit = fact.get("actor", "")
        for j in self.board.journeys.values():
            if j.live or j.stage is not None or j.state == "done" or not j.alive():
                continue
            if j.faction != fact.get("actor_faction"):
                continue
            for m in j.alive():
                if culprit and culprit in (actor_key(m.get("id") or ""), actor_key(m.get("name") or "")):
                    return j
        return None

    def _stage_avenger(self, t):
        """A townsperson out to settle a real score with an outlaw gang."""
        done = {sc.get("fact_e") for sc in self.scenes.values()}
        for thing, rid, fact, tie in self._grievances():
            if fact.get("e") in done or not self._can_take(rid):
                continue
            spot = self._road_ahead(hostile=True)
            if spot is None:
                return self._no("no road the player is on has a free spot out of sight ahead")
            x, z = spot[7], spot[8]
            route, dest = self._away_from_player(spot, QUARRY_GAP)
            gx, gz = route[0]
            gang = self._culprit_gang(fact)
            borrowed = gang is not None
            if gang is None:
                kind = "cultists" if fact.get("actor_faction") == "cultists" else "bandits"
                gang, borrowed = self._gang((gx, gz), t, kind)
            if gang is None:
                return self._no("no outlaw party to be the avenger's quarry")
            sid = self._new_id()
            member = self._resident_member(thing, rid)
            member["armed"] = True
            name = member["display"]
            what = {"death": "killed", "attack": "attacked", "theft": "robbed"}[fact["kind"]]
            whom = (f"my {tie} {fact.get('target_name', '')}".strip() if tie else "me")
            culprit = fact.get("actor_name") or "Outlaws"
            greeting = (f"{culprit} {what} {whom}. They're camped up the road -- "
                        "I'm going after them, with or without you.")
            j = self._new_journey("avenger", [member], [(x, z), (x + 1.0, z + 1.0)], dest, t,
                                  home=self.board.nearest_place(thing.pos[0], thing.pos[2], jn.HOMES))
            self._take_resident(j, rid)
            self._hold(j, x, z, sid, "avenger", t, hours=HOLD_HOURS * 0.5, greeting=greeting,
                       wander=50.0)
            j.stage["onward"] = [list(p) for p in route]
            j.stage["onward_dest"] = dest
            self._hold(gang, gx, gz, sid, "attacker", t, borrowed=borrowed, wander=110.0)
            self._keep_apart(j, gang)
            chief = gang.leader()
            quest = self._avenger_quest(sid, j, member, chief, culprit, what, whom)
            return self._record(sid, "avenger", {"avenger": j.id, "attacker": gang.id}, x, z, t,
                                fact_e=fact.get("e"), quest=quest, reward=False,
                                text=(f"{name} set out after {culprit}, who {what} {whom}; "
                                      f"staged on the road ahead with the gang beyond."))
        return self._no("no townsperson holds a fresh, certain grievance against outlaws "
                        "(and is out of sight, free to leave)")

    def _avenger_quest(self, sid, j, member, chief, culprit, what, whom):
        if chief is None:
            return None
        qid = f"dyn_avenge_{sid}"
        reward = 40 + int(member.get("gold", 0)) * 2
        quest = {"id": qid, "name": f"{member['display']}'s Score",
                 "giver": member["name"],
                 "offer": (f"{culprit} {what} {whom}. {chief['display']} leads them, "
                           f"just up the road. Help me end it and what I have is yours -- "
                           f"{reward} gold."),
                 "xp": 50, "rewards": {"gold": reward},
                 "stages": [
                     {"index": 0, "journal": f"Help {member['display']} deal with "
                                             f"{chief['display']}'s band, camped up the road.",
                      "objective": f"Kill {chief['display']}",
                      "condition": {"kind": "kill", "target": chief["name"], "count": 1},
                      "waypoint": chief["name"]},
                     {"index": 10, "journal": f"{chief['display']} is dead. "
                                              f"{member['display']} has their score settled.",
                      "finishes": True}]}
        self.world._register(quest)
        return qid

    def _justified_holders(self, kinds):
        """Townsfolk with a real, evidenced intent toward the player:
        ``[(thing, rid, kind, fact)]`` (storyteller.justification)."""
        s = self.session
        director = getattr(s, "director", None)
        store = getattr(s, "store", None)
        if director is None or store is None:
            return []
        from ..sim import knowledge
        from ..sim.director import actor_key
        from ..sim.storyteller import justification
        out = []
        for rid, thing in list(self.world._residents.items()):
            p = thing.properties
            if p.get("dead") or str(p.get("type", "npc")) != "npc":
                continue
            key = actor_key(thing)
            cached = director.cached_intents(key)
            if not cached:
                continue
            known = None
            for intent in cached:
                if known is None:
                    known = {f.get("e"): f for f in knowledge.facts_view(store, key)}
                fact = known.get(intent.event_id)
                kind = justification(p, key, intent, fact)
                if kind in kinds:
                    out.append((thing, rid, kind, fact))
                    break
        return out

    def _meet(self, t, kinds, scene_kind, hostile):
        done = {sc.get("fact_e") for sc in self.scenes.values()}
        import game.chatter as chatter
        for thing, rid, kind, fact in self._justified_holders(kinds):
            if fact.get("e") in done or not self._can_take(rid):
                continue
            spot = self._road_ahead(hostile=hostile)
            if spot is None:
                return self._no("no road the player is on has a free spot out of sight ahead")
            route, dest = self._toward_player(spot)
            sid = self._new_id()
            member = self._resident_member(thing, rid)
            if kind in ("vendetta", "reckoning"):
                member["armed"] = True
                member["grudge"] = True
            victim = fact.get("target_name", "") if fact.get("target") != rid else ""
            line = chatter.justified_line(kind, victim, member["display"]) or ""
            j = self._new_journey("avenger", [member], route, dest, t,
                                  home=self.board.nearest_place(thing.pos[0], thing.pos[2], jn.HOMES))
            self._take_resident(j, rid)
            self._walking(j, route, dest, sid, "seeker", t, greeting=line)
            text = {"vendetta": f"{member['display']} comes for the player over a death they mourn.",
                    "reckoning": f"{member['display']} comes for the player over an attack they suffered.",
                    "restitution": f"{member['display']} comes to collect what the player took.",
                    "gratitude": f"{member['display']} comes down the road, grateful to the player."}[kind]
            return self._record(sid, scene_kind, {"seeker": j.id}, spot[7], spot[8], t,
                                fact_e=fact.get("e"), justified=kind,
                                gift=kind == "gratitude", reward=False,
                                text=text + " Staged a meeting on the road ahead.")
        return self._no("nobody holds a cached, evidenced intent of this kind toward the player "
                        f"({', '.join(kinds)}) and is free to leave")

    def _stage_reckoning(self, t):
        return self._meet(t, ("vendetta", "reckoning", "restitution"), "reckoning", True)

    def _stage_gratitude(self, t):
        return self._meet(t, ("gratitude",), "gratitude", False)

    def _stage_cult_rite(self, t):
        """A cult holds a real townsperson at a rite by the road."""
        spot = self._road_ahead(hostile=True)
        if spot is None:
            return self._no("no road the player is on has a free spot out of sight ahead")
        x, z = spot[7], spot[8]
        pool = [r for r in self.board.resident_pool if self._can_take(r["id"])]
        if not pool:
            return self._no("no townsperson out of sight and free to be taken captive")
        home = self._place_at(x, z)
        hx, hz = self.board.places[home]["x"], self.board.places[home]["z"]
        pool.sort(key=lambda r: math.hypot(self.board.places.get(r["home"], {}).get("x", hx) - hx,
                                           self.board.places.get(r["home"], {}).get("z", hz) - hz))
        r = pool[0]
        thing = self.world.resident_thing(r["id"])
        if thing is None:
            return self._no("the chosen captive is not in the scene")
        cult, borrowed = self._gang((x, z), t, "cultists")
        if cult is None:
            return self._no("no cult on the roads and no camp to send one from")
        sid = self._new_id()
        member = self._resident_member(thing, r["id"])
        captive = self._new_journey("captive", [member], [(x, z), (x + 1.0, z + 1.0)],
                                    r["home"], t, home=r["home"])
        self._take_resident(captive, r["id"])
        self._hold(captive, x, z, sid, "victim", t, hours=RITE_HOURS,
                   greeting="Please -- cut me loose before they come back!", wander=8.0)
        self._hold(cult, x + 70.0, z + 40.0, sid, "attacker", t, hours=RITE_HOURS,
                   borrowed=borrowed, wander=140.0)
        self._keep_apart(captive, cult)
        return self._record(sid, "cult_rite", {"victim": captive.id, "attacker": cult.id}, x, z, t,
                            reward=True,
                            text=(f"Staged a cult rite by the road with {member['display']} "
                                  f"of {self.board.place_name(r['home'])} held captive."))

    def _stage_procession(self, t):
        spot = self._road_ahead(hostile=True)
        if spot is None:
            return self._no("no road the player is on has a free spot out of sight ahead")
        cult, borrowed = self._gang((spot[7], spot[8]), t, "cultists")
        if cult is None:
            return self._no("no cult on the roads and no camp to send one from")
        route, dest = self._toward_player(spot)
        sid = self._new_id()
        self._walking(cult, route, dest, sid, "attacker", t, borrowed=borrowed)
        return self._record(sid, "procession", {"attacker": cult.id}, spot[7], spot[8], t,
                            reward=False, text="Sent a cult procession down the road toward the player.")

    def _stage_ambush(self, t):
        spot = self._road_ahead(hostile=True)
        if spot is None:
            return self._no("no road the player is on has a free spot out of sight ahead")
        gang, borrowed = self._gang((spot[7], spot[8]), t)
        if gang is None:
            return self._no("no gang on the roads and no camp to send one from")
        sid = self._new_id()
        self._hold(gang, spot[7], spot[8], sid, "attacker", t, borrowed=borrowed, wander=70.0)
        return self._record(sid, "ambush", {"attacker": gang.id}, spot[7], spot[8], t,
                            reward=False, text=f"{gang.describe()} lie in wait on the road ahead.")

    def _stage_patrol(self, t):
        spot = self._road_ahead(hostile=True)
        if spot is None:
            return self._no("no road the player is on has a free spot out of sight ahead")
        x, z = spot[7], spot[8]
        patrol = self._borrow(("patrol",), (x, z))
        if patrol is None:
            return self._no("no patrol of the watch off screen within reach")
        gang, borrowed = self._gang((x, z), t)
        if gang is None:
            return self._no("no gang on the roads and no camp to send one from")
        sid = self._new_id()
        self._hold(patrol, x, z, sid, "victim", t, borrowed=True, wander=60.0)
        ux, uz = self._side_offset(spot, 170.0)
        self._hold(gang, x + ux, z + uz, sid, "attacker", t, borrowed=borrowed, wander=60.0)
        self._keep_apart(patrol, gang)
        return self._record(sid, "patrol", {"victim": patrol.id, "attacker": gang.id}, x, z, t,
                            reward=True, text=f"The watch meets {gang.describe()} on the road ahead.")

    # -- hooks from the living world -------------------------------------------
    def spawned(self, j, things) -> None:
        """A staged party became actors: hand out its scene's quest."""
        scene = self.scenes.get((j.stage or {}).get("scene", ""))
        if scene is None or not things:
            return
        qid = scene.get("quest")
        if qid and j.stage.get("role") == "avenger":
            from ..rpg import quests as rpg_quests
            q = rpg_quests.get(qid)
            giver = things[0]
            if q is not None:
                tree = copy.deepcopy(giver.properties.get("dialogue"))
                tree, _ = rpg_quests.offer_dialogue_branch(tree, qid, q.name, q.desc
                                                           if getattr(q, "desc", "") else "")
                giver.properties["dialogue"] = tree

    def stage_expired(self, j, t) -> bool:
        """A staged party waited out its time unmet; the world moves on."""
        stage = j.stage or {}
        scene = self.scenes.get(stage.get("scene", ""))
        role = stage.get("role")
        if scene is not None and scene["kind"] == "cult_rite" and not scene.get("resolved"):
            # Whichever party's time runs out first, the rite is finished if
            # the cult is still there and nobody broke it up.
            cult = self.board.journeys.get(scene["journeys"].get("attacker", ""))
            captive = self.board.journeys.get(scene["journeys"].get("victim", ""))
            if cult is not None and cult.alive() and captive is not None \
                    and captive.alive() and not captive.live:
                self._sacrificed(scene, captive, t)
                captive.state = "done"
                if role == "victim":
                    return False
        if role == "avenger" and stage.get("onward"):
            # Nobody came: they go after their quarry alone.
            lead = j.leader()
            self._narrate(f"{lead['display'] if lead else 'The avenger'} waited, but nobody came: "
                          "they have gone after their quarry alone.", journey=j.id)
            route = [tuple(p) for p in stage["onward"]]
            self._walking(j, route, stage.get("onward_dest") or j.dest, scene["id"] if scene else "",
                          "avenger", t)
            j.stage.pop("greeting", None)
            j.fought = []                     # now the board's dice may settle it
            return True
        if stage.get("borrowed") or j.resident:
            self._decide("world", f"{j.describe()} waited out the scene unmet and went back "
                         "to ordinary life.", journey=j.id, scene=stage.get("scene"))
            return self._release(j, t)
        self._decide("world", f"{j.describe()} waited out the scene unmet and left the roads.",
                     journey=j.id, scene=stage.get("scene"))
        return False

    def _release(self, j, t, dest=None) -> bool:
        """Back to ordinary life: on toward where they were going (a borrowed
        party) or home (a townsperson)."""
        board = self.board
        stage = j.stage or {}
        if j.live:
            things = [x for x in self.world.live.get(j.id, {}).get("things", [])
                      if not x.properties.get("dead")]
            x, z = (things[0].pos[0], things[0].pos[2]) if things else (stage.get("x", 0.0), stage.get("z", 0.0))
        else:
            x, z = stage.get("x", 0.0), stage.get("z", 0.0)
        if dest is None:
            dest = j.home if j.resident else (stage.get("was_dest") or j.dest)
        here = self._place_at(x, z)
        if dest not in board.network.place_node or dest == here:
            dest = j.home if j.home in board.network.place_node and j.home != here else None
        route = board._route(here, dest) if dest else None
        j.stage = None
        j.fought = []
        if route is None:
            j.state = "done"
            return False
        j.route = [(float(x), float(z))] + [tuple(p) for p in route]
        j.cum = roads.cumulative(j.route)
        j.origin, j.dest, j.depart_t, j.state = here, dest, float(t), "travel"
        if j.resident:
            j.legs = 0
            j.home = dest
        return True

    def _sacrificed(self, scene, captive, t):
        """The rite was finished: the captive is lost, and word goes round."""
        board = self.board
        for m in captive.members:
            m["alive"] = False
            m["health"] = 0
        name = captive.members[0]["display"] if captive.members else "a traveller"
        place = self._place_at(scene["x"], scene["z"])
        nid = board.say(f"{name} was taken by cultists and never came home; they were found "
                        f"by the road near {board.place_name(place)}.", t, place, "death")
        captive.news.append(nid)
        scene["resolved"] = True
        self._narrate(f"Nobody came for {name}: the rite was finished.")
        self._tell_kin(captive, scene)

    def _tell_kin(self, captive, scene):
        """Kin of the lost hear of it (a real death fact, told them), so their
        own grievance -- and perhaps an avenger -- follows from it."""
        s = self.session
        director = getattr(s, "director", None)
        store = getattr(s, "store", None)
        if director is None or store is None or not captive.members:
            return
        from ..sim import appraisal, knowledge
        from ..sim.director import actor_key
        m = captive.members[0]
        rid = m.get("resident") or m.get("name")
        cult = self.board.journeys.get(scene["journeys"].get("attacker", ""))
        lead = cult.leader() if cult is not None else None
        try:
            event = director.emit("death", actor=(lead or {}).get("name", "cultists"), target=rid,
                                  pos=(scene["x"], 0.0, scene["z"]), observers=(),
                                  actor_faction="cultists", target_faction="villagers")
        except Exception:
            return
        for kin_id, thing in list(self.world._residents.items()):
            if kin_id == rid or thing.properties.get("dead"):
                continue
            tie = appraisal.relationship_to(thing.properties, actor_key(rid), m.get("display", ""))
            if tie not in appraisal.WARM_TIES:
                continue
            fact = knowledge.fact_from_event(event, 0.9, knowledge.SOURCE_HEARD, told_by="news")
            knowledge.learn(store, actor_key(thing), fact)
            director.invalidate(thing)

    # -- watching scenes play out ----------------------------------------------
    def _live_things(self, jid):
        entry = self.world.live.get(jid or "")
        return [x for x in entry["things"] if not x.properties.get("dead")] if entry else []

    def _party_up(self, jid) -> bool:
        j = self.board.journeys.get(jid or "")
        if j is None or j.state == "done":
            return False
        if j.live:
            return bool(self._live_things(jid))
        return bool(j.alive())

    def watch(self) -> None:
        """Hints as the player nears a scene; thanks and rewards once it is won."""
        if not self.scenes or self.board is None:
            return
        s = self.session
        ppos = s._player_pos()
        if ppos is None:
            return
        px, pz = ppos[0], ppos[2]
        t = _now_hours(s.clock)
        for scene in list(self.scenes.values()):
            if not scene["hinted"]:
                anchor = self._anchor(scene)
                if anchor is not None and math.hypot(anchor[0] - px, anchor[1] - pz) <= HINT_RADIUS:
                    scene["hinted"] = True
                    lines = HINTS.get(scene["kind"])
                    if lines:
                        s.notify(s.rng.choice(lines), 4.0)
            if scene["resolved"]:
                continue
            js = scene["journeys"]
            if scene.get("gift"):
                self._maybe_gift(scene, px, pz, t)
                continue
            if "attacker" not in js or "victim" not in js and "avenger" not in js:
                continue
            if self._party_up(js["attacker"]):
                continue
            friend = js.get("victim") or js.get("avenger")
            things = self._live_things(friend)
            if not self._party_up(friend):
                scene["resolved"] = True
                self._narrate(f"The {scene['kind']} scene ended badly: nobody was left to save.")
                continue
            if not things:
                continue
            lead = things[0]
            if math.hypot(lead.pos[0] - px, lead.pos[2] - pz) > THANK_RADIUS:
                continue
            self._thank(scene, friend, lead, t)

    def _anchor(self, scene):
        for jid in scene["journeys"].values():
            things = self._live_things(jid)
            if things:
                return things[0].pos[0], things[0].pos[2]
        return scene["x"], scene["z"]

    def _thank(self, scene, jid, lead, t):
        s = self.session
        scene["resolved"] = True
        j = self.board.journeys.get(jid)
        name = lead.properties.get("display_name") or lead.properties.get("name") or "The traveller"
        kind = scene["kind"]
        line = {"cult_rite": "You came for me... I thought I was done for. Thank you.",
                "patrol": "Good work, citizen. The watch won't forget it.",
                "avenger": "It's done. I couldn't have -- thank you."}.get(
            kind, "Gods bless you, stranger -- they'd have had everything.")
        s.bark(lead, line)
        if scene.get("reward") and j is not None:
            purse = sum(int(m.get("gold", 0) or 0) for m in j.alive())
            amount = max(10, min(120, purse // 2 + s.rng.randint(5, 25)))
            for m in j.alive():
                m["gold"] = max(0, int(m.get("gold", 0) or 0) - amount // max(1, len(j.alive())))
            credit = getattr(s, "_credit_found_gold", None)
            if credit is not None:
                credit(amount, "Rewarded")
        place = self._place_at(scene["x"], scene["z"])
        who = self.board.hooks.player_name()
        nid = self.board.say(f"{who} came to the aid of {name} on the road near "
                             f"{self.board.place_name(place)}.", t, place, "deed")
        if j is not None:
            j.news.append(nid)
            if j.resident or (j.stage or {}).get("borrowed"):
                self._release(j, t)
        self._narrate(f"{name} was saved; the player stepped in.")

    def _maybe_gift(self, scene, px, pz, t):
        jid = scene["journeys"].get("seeker")
        things = self._live_things(jid)
        if not things:
            return
        lead = things[0]
        if math.hypot(lead.pos[0] - px, lead.pos[2] - pz) > THANK_RADIUS:
            return
        s = self.session
        scene["resolved"] = True
        j = self.board.journeys.get(jid)
        amount = 0
        if j is not None and j.alive():
            m = j.alive()[0]
            amount = max(5, min(40, int(m.get("gold", 0) or 0) // 2))
            m["gold"] = max(0, int(m.get("gold", 0) or 0) - amount)
        s.bark(lead, "I never thanked you properly. Here -- it isn't much.")
        credit = getattr(s, "_credit_found_gold", None)
        if credit is not None and amount:
            credit(amount, "Given")
        if j is not None:
            self._release(j, t)

    # -- housekeeping ------------------------------------------------------------
    def _forget_finished(self):
        board = self.board
        for sid, scene in list(self.scenes.items()):
            alive = [jid for jid in scene["journeys"].values()
                     if jid in board.journeys and board.journeys[jid].state != "done"
                     and (board.journeys[jid].stage or {}).get("scene") == sid]
            if not alive:
                self.scenes.pop(sid, None)

    def _stand_down_all(self, t):
        """Back to Normal: every staged party not on screen returns to
        ordinary life at once; ones on screen finish as they are."""
        self._decide("phase", "Game mode is Normal again: staged parties off screen went back "
                     "to ordinary life; ones in view finish as they are.", scenes=list(self.scenes))
        for scene in list(self.scenes.values()):
            for jid in scene["journeys"].values():
                j = self.board.journeys.get(jid)
                if j is None or j.stage is None or j.live:
                    continue
                if j.stage.get("borrowed") or j.resident:
                    self._release(j, _now_hours(self.session.clock))
                else:
                    j.stage = None
                    j.state = "done"
        self.scenes = {sid: sc for sid, sc in self.scenes.items()
                       if any((self.board.journeys.get(jid) and self.board.journeys[jid].stage)
                              for jid in sc["journeys"].values())}
        self.reset_pacing()

    # -- persistence --------------------------------------------------------------
    def persist(self) -> None:
        store = getattr(self.session, "store", None)
        if store is None:
            return
        if not self.scenes and not store.get(STORE_KEY, ""):
            return                          # Normal mode leaves the save as it was
        store.set(STORE_KEY, json.dumps({"scenes": list(self.scenes.values()),
                                         "next_id": self.next_id}))

    def restore(self) -> None:
        self.scenes = {}
        self.reset_pacing()
        store = getattr(self.session, "store", None)
        raw = store.get(STORE_KEY, "") if store is not None else ""
        if not raw or raw == "false":
            return
        try:
            d = json.loads(raw)
        except (TypeError, ValueError):
            return
        if not isinstance(d, dict):
            return
        self.next_id = int(d.get("next_id", self.next_id) or self.next_id)
        for sc in d.get("scenes", []):
            if isinstance(sc, dict) and sc.get("id"):
                self.scenes[sc["id"]] = sc

    def status(self) -> str:
        """One plain sentence: what the director is doing right now."""
        if not self.enabled():
            return "Idle: the game mode is Normal."
        phase = PHASE_NAMES.get(self.phase, self.phase)
        line = f"{phase} · tension {self.intensity:.0%}"
        if self.phase == "build" and self.gap_left > 0:
            line += f" · next scene in about {math.ceil(self.gap_left):.0f} s"
        elif self.phase in ("sustain", "relax") and self.phase_left > 0:
            line += f" · {math.ceil(self.phase_left):.0f} s left"
        playing = [SCENE_NAMES.get(sc["kind"], sc["kind"]) for sc in self.scenes.values()
                   if not sc.get("resolved")]
        return line + (" · in play: " + ", ".join(playing) if playing else " · nothing in play")

    def raw(self) -> Dict:
        """Every number behind the decisions, detached (the debug Raw tab)."""
        return copy.deepcopy({
            "enabled": self.enabled(), "phase": self.phase,
            "phase_seconds_left": round(self.phase_left, 1),
            "intensity": round(self.intensity, 3), "gap_seconds_left": round(self.gap_left, 1),
            "peaceful_done": self._peaceful_done, "player_health": round(self._health(), 3),
            "storyteller_state": self._story_state(), "scenes": self.scenes,
            "decisions": [{k: v for k, v in d.items() if k != "merge"}
                          for d in reversed(self.decisions)],
            "tuning": {"peak": PEAK, "relax_below": RELAX_BELOW, "hurt": HURT,
                       "max_scenes": MAX_SCENES, "stage_min": STAGE_MIN, "stage_max": STAGE_MAX,
                       "build_gap": BUILD_GAP, "relax_seconds": RELAX_SECONDS,
                       "sustain_seconds": SUSTAIN_SECONDS, "hold_hours": HOLD_HOURS,
                       "rite_hours": RITE_HOURS},
        })

    def summary(self) -> List[str]:
        """Plain lines for the console."""
        lines = [f"Dynamic director: {self.phase}, intensity {self.intensity:.2f}"
                 + ("" if self.enabled() else " (Normal mode: idle)")]
        for sc in self.scenes.values():
            lines.append(f"  {sc['id']} {sc['kind']}{' (resolved)' if sc['resolved'] else ''}: "
                         f"{sc.get('text', '')}")
        return lines
