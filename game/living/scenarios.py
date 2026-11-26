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

from ..sim import story_text
from . import journeys as jn
from . import scene_talk
from . import roads
from .scenario_modules import create_modules, MODULE_TYPES
from .scenario_modules.base import ScenarioContext

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
#: How often each scene is picked, against the others that fit the moment.
#: Cult rites, processions and ambushes are for the night; an ambush is half
#: as likely at dusk. Hostile scenes are scaled by STATE_HOSTILE.
SCENE_WEIGHTS = {"gratitude": 4.0, "waylaid": 3.0, "avenger": 3.0, "reckoning": 3.0,
                 "patrol": 1.5, "cult_rite": 3.0, "ambush": 2.0, "procession": 1.5}

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
SCENE_NAMES = {kind: scenario_type.scene_name for kind, scenario_type in MODULE_TYPES.items()}
PHASE_NAMES = {"build": "Building tension", "sustain": "At the peak",
               "fade": "Easing off", "relax": "Resting"}

PEACEFUL_KINDS = ("market", "trader", "caravan", "pilgrims", "courier", "minstrel")
OUTLAW_FACTIONS = ("bandits", "cultists", "monsters")
TOWNS = jn.TOWNS

#: How the director learns (storyteller_dynamic.ini [learning]): what it
#: nudges, by how much, and the bounds it never leaves. Scales multiply the
#: values above; 1 is as tuned.
LEARNING = {"enabled": True, "step": 0.1, "scene_step_up": 0.05, "scene_step_down": 0.1,
            "gap_min": 0.6, "gap_max": 1.8, "hostile_min": 0.5, "hostile_max": 1.5,
            "scene_min": 0.4, "scene_max": 2.0,
            "overwhelmed_health": 0.3, "breezed_health": 0.8}
#: Scenes the player chooses to step into or not (the others come to them).
CHOOSABLE = ("waylaid", "avenger", "cult_rite", "patrol", "ambush", "procession")
#: The save's store key for what the director has learned (minified JSON).
LEARNED_KEY = "living.scenarios.learned"

#: Every tunable value above, by its name in storyteller_dynamic.ini's
#: [director] section (game/sim/tuning_ini.py), and the module global it sets.
TUNABLE = {
    "peak": "PEAK", "relax_below": "RELAX_BELOW", "sustain_seconds": "SUSTAIN_SECONDS",
    "relax_seconds": "RELAX_SECONDS", "first_relax": "FIRST_RELAX", "build_gap": "BUILD_GAP",
    "damage_gain": "DAMAGE_GAIN", "engaged_gain": "ENGAGED_GAIN", "calm_decay": "CALM_DECAY",
    "tense_decay": "TENSE_DECAY", "threat_radius": "THREAT_RADIUS", "hurt": "HURT",
    "max_scenes": "MAX_SCENES", "stage_min": "STAGE_MIN", "stage_max": "STAGE_MAX",
    "on_road": "ON_ROAD", "town_clear": "TOWN_CLEAR", "quarry_gap": "QUARRY_GAP",
    "hold_hours": "HOLD_HOURS", "rite_hours": "RITE_HOURS", "hint_radius": "HINT_RADIUS",
    "thank_radius": "THANK_RADIUS", "grievance_days": "GRIEVANCE_DAYS",
}


def tuning():
    """The director's tuning as storyteller.ini names it, detached."""
    g = globals()
    return {"dynamic": {k: copy.deepcopy(g[name]) for k, name in TUNABLE.items()},
            "scene_weights": dict(SCENE_WEIGHTS),
            "state_gap": dict(STATE_GAP), "state_hostile": dict(STATE_HOSTILE),
            "learning": dict(LEARNING)}


def retune(values) -> None:
    """Set the director's tuning from *values* (shaped like :func:`tuning`)."""
    g = globals()
    for key, value in (values.get("dynamic") or {}).items():
        if key in TUNABLE:
            g[TUNABLE[key]] = value
    for table, target in (("scene_weights", SCENE_WEIGHTS), ("state_gap", STATE_GAP),
                          ("state_hostile", STATE_HOSTILE), ("learning", LEARNING)):
        target.update(values.get(table) or {})




#: How someone come to settle a score opens the fight: a brief
#: introduction (what the player did), an insult, or a scream as they charge.
#: Each is followed at once by the fight. {victim}: whom it was done to.
OPENINGS = {
    "introduction": {
        "vendetta": ("You killed {victim}. I've come for you.",
                     "{Victim} was my blood. You'll answer for it.",
                     "Remember {victim}? I do."),
        "reckoning": ("You struck me and walked away. Not this time.",
                      "Remember me? I remember you."),
    },
    "insult": {
        "vendetta": ("Murdering filth!", "You gutless butcher!",
                     "Coward! {Victim} never stood a chance!"),
        "reckoning": ("You cowardly dog!", "Thug! Gutter-born thug!",
                      "You'll not lay a hand on me again, scum!"),
    },
    "scream": {
        "vendetta": ("MURDERER!", "For {victim}!", "AAARGH!"),
        "reckoning": ("YOU!", "AAARGH!", "Now you'll pay!"),
    },
}
#: How often each opening is chosen.
OPENING_WEIGHTS = {"introduction": 0.4, "insult": 0.3, "scream": 0.3}


def opening_line(rng, kind: str, victim: str = "") -> tuple:
    """``(style, line)``: how someone with a *kind* grudge ("vendetta",
    "reckoning") opens the fight -- an introduction, an insult or a scream."""
    styles = list(OPENING_WEIGHTS)
    style = rng.choices(styles, weights=[OPENING_WEIGHTS[s] for s in styles])[0]
    options = OPENINGS[style].get(kind) or OPENINGS[style]["reckoning"]
    if not victim:                       # nobody to name: lines that need no one
        options = tuple(o for o in options if "{" not in o) or OPENINGS[style]["reckoning"]
    victim = victim or "them"
    return style, rng.choice(options).format(victim=victim, Victim=victim[:1].upper() + victim[1:])


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
        self.context = ScenarioContext(self)
        self.modules = create_modules()
        #: scene id -> plain dict (persisted)
        self.scenes: Dict[str, Dict] = {}
        self.next_id = 1
        #: What it decided and why, oldest first: ``{"time", "kind", "text",
        #: "data"}`` -- *text* plain English, *data* the raw numbers.
        self.decisions: List[Dict] = []
        #: Called with each new decision (console ``storyteller watch on``).
        self.listeners: List = []
        self._why = ""
        self._was_on = None           # the mode last seen (None: not yet)
        #: What the director has learned about this player (saved with the
        #: game as minified JSON under LEARNED_KEY).
        self.learned = self.fresh_learning()
        self._cycle_low = 1.0         # lowest health since build-up began
        self.reset_pacing()

    def _decide(self, kind, text, merge="", result="", why="", **data):
        """Log a decision. *merge*: an entry with the same key replaces the
        newest one if that is also it (a wait counting down is one line)."""
        try:
            now = _now_hours(self.session.clock)
        except Exception:
            now = None
        raw = {"phase": self.phase, "intensity": round(self.intensity, 3)}
        raw.update(data)
        entry = {"time": now, "kind": kind, "text": str(text), "data": raw, "merge": merge}
        if result:
            entry["result"] = str(result)       # what was done, said apart
        if why:
            entry["why"] = str(why)             # why now: the moment and the choices
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

    # -- learning ------------------------------------------------------------
    @staticmethod
    def fresh_learning() -> Dict:
        return {"gap": 1.0, "hostile": 1.0, "scenes": {}, "peaks": 0, "nudges": 0}

    def learning_on(self) -> bool:
        return bool(LEARNING.get("enabled", True))

    def gap_scale(self) -> float:
        return float(self.learned["gap"]) if self.learning_on() else 1.0

    def hostile_scale(self) -> float:
        return float(self.learned["hostile"]) if self.learning_on() else 1.0

    def scene_scale(self, kind) -> float:
        return float(self.learned["scenes"].get(kind, 1.0)) if self.learning_on() else 1.0

    @staticmethod
    def _bounded(value, lo, hi):
        return round(max(float(lo), min(float(hi), float(value))), 3)

    def _learn_peak(self):
        """A peak has played out: was it too hard, too easy, or about right?"""
        if not self.learning_on():
            return
        low = self._cycle_low
        L = self.learned
        L["peaks"] = int(L.get("peaks", 0)) + 1
        too_hard, too_easy = LEARNING["overwhelmed_health"], LEARNING["breezed_health"]
        if low < too_hard:
            verdict = (f"the last peak was too hard: {story_text.PLAYER} fell to {low:.0%} health "
                       f"(below {too_hard:.0%})")
            gap, hostile = L["gap"] + LEARNING["step"], L["hostile"] - LEARNING["step"]
            change = "scenes now come further apart and hostile scenes less often"
        elif low >= too_easy:
            verdict = (f"the last peak was too easy: {story_text.PLAYER} never dropped below "
                       f"{low:.0%} health ({too_easy:.0%} or more)")
            gap, hostile = L["gap"] - LEARNING["step"], L["hostile"] + LEARNING["step"]
            change = "scenes now come closer together and hostile scenes more often"
        else:
            self._decide("learn", f"The storyteller judged the last peak about right: "
                         f"{story_text.PLAYER}'s health got as low as {low:.0%} (between "
                         f"{too_hard:.0%} and {too_easy:.0%}).",
                         result="No change to the pace.", low=round(low, 3))
            return
        gap = self._bounded(gap, LEARNING["gap_min"], LEARNING["gap_max"])
        hostile = self._bounded(hostile, LEARNING["hostile_min"], LEARNING["hostile_max"])
        before = (L["gap"], L["hostile"])
        if (gap, hostile) == before:
            result = (f"No change: the pace is already at the limit [learning] allows "
                      f"(gap ×{gap:g}, hostile ×{hostile:g}).")
        else:
            L["gap"], L["hostile"] = gap, hostile
            L["nudges"] = int(L.get("nudges", 0)) + 1
            result = (f"Nudged: {change} -- the time between scenes is now ×{gap:g} (was "
                      f"×{before[0]:g}) and hostile scenes are picked ×{hostile:g} as often "
                      f"(was ×{before[1]:g}).")
        self._decide("learn", f"The storyteller learned that {verdict}.", result=result,
                     low=round(low, 3), gap=[before[0], gap], hostile=[before[1], hostile])
        self._narrate(f"Learned: {verdict}. {result}", log=False)

    def _learn_scene(self, scene, stepped_in: bool, how: str):
        """The player stepped into a scene, or saw it and passed it by."""
        kind = scene.get("kind")
        if not self.learning_on() or kind not in CHOOSABLE or scene.get("learned"):
            return
        scene["learned"] = True
        L = self.learned
        before = float(L["scenes"].get(kind, 1.0))
        step = LEARNING["scene_step_up"] if stepped_in else -LEARNING["scene_step_down"]
        after = self._bounded(before + step, LEARNING["scene_min"], LEARNING["scene_max"])
        name = SCENE_NAMES.get(kind, kind)
        verdict = (f"{story_text.PLAYER} steps into {name}: {how}" if stepped_in else
                   f"{story_text.PLAYER} passes {name} by: {how}")
        if after == before:
            result = (f"No change: {name} is already picked ×{after:g} as often, the limit "
                      "[learning] allows.")
        else:
            L["scenes"][kind] = after
            L["nudges"] = int(L.get("nudges", 0)) + 1
            result = (f"Nudged: {name} is now picked ×{after:g} as often (was ×{before:g}).")
        self._decide("learn", f"The storyteller learned that {verdict}.", result=result,
                     scene=scene.get("id"), scene_kind=kind, weight=[before, after])
        self._narrate(f"Learned: {verdict}. {result}", log=False)

    def forget_learning(self):
        """Back to the values as tuned (console ``storyteller unlearn``)."""
        self.learned = self.fresh_learning()
        self._decide("learn", "The storyteller forgot what it had learned about the player.",
                     result="Pace and scene choice are back to storyteller_dynamic.ini's values.")
        self.persist(force=True)

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
        on = self.enabled()
        if on != self._was_on:
            # The mode can be switched at any moment of play: say when.
            if on and self._was_on is False:
                self.reset_pacing()
                self._narrate("Game mode switched to Dynamic: the director may now stage scenes "
                              f"on the roads, starting after a {FIRST_RELAX:g}-second rest.")
            elif on:
                self._narrate("Game mode is Dynamic: the director may stage scenes on the roads.")
            elif self._was_on is not None:
                self._narrate("Game mode switched to Normal: the director stages nothing more; "
                              "the storyteller only paces what the world already holds.")
            self._was_on = on
        if not on:
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
        gap = (self.session.rng.uniform(*BUILD_GAP) * STATE_GAP.get(self._story_state(), 1.0)
               * self.gap_scale())
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
        self._cycle_low = min(self._cycle_low, health)
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
        if phase == "build":
            self._cycle_low = self._health()
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
        if phase == "fade" and before == "sustain":
            self._learn_peak()                 # how did that peak go?

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
    def invoke(self, kind: str, t: float) -> Optional[Dict]:
        """Stage a named world scenario directly, without using Dynamic pacing.

        Other gameplay systems may request the same reusable implementation.
        Dynamic mode is only one consumer of the registered modules.
        """
        module = self.modules.get(str(kind))
        if module is None:
            raise ValueError(f"Unknown scenario: {kind}")
        self._why = ""
        return module.stage(self.context, t)

    def _cast(self, t: float, peaceful_only: bool) -> Optional[Dict]:
        rng = self.session.rng
        hostile = STATE_HOSTILE.get(self._story_state(), 1.0) * self.hostile_scale()
        night, dusk = is_night(t), is_dusk(t)
        w = {k: v * self.scene_scale(k) for k, v in SCENE_WEIGHTS.items()}
        options = [("gratitude", w["gratitude"])]
        if not peaceful_only:
            options += [(k, w[k] * hostile) for k in ("waylaid", "avenger", "reckoning", "patrol")]
            if night:
                options += [(k, w[k] * hostile) for k in ("cult_rite", "ambush", "procession")]
            elif dusk:
                options += [("ambush", w["ambush"] * 0.5 * hostile)]
        tried, rejected = set(), {}
        while len(tried) < len(options):
            left = [(k, w) for k, w in options if k not in tried and w > 0]
            if not left:
                break
            kind = rng.choices([k for k, _ in left], weights=[w for _, w in left])[0]
            tried.add(kind)
            self._why = ""
            scene = self.invoke(kind, t)
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
        why = (f"{SCENE_NAMES.get(scene['kind'], scene['kind'])[:1].upper()}"
               f"{SCENE_NAMES.get(scene['kind'], scene['kind'])[1:]}, now: "
               f"{moment}; it is {when}; the storyteller is {self._story_state()}.{passed}")
        self._decide("stage", scene.get("decision") or scene.get("text", ""),
                     result=scene.get("result", ""), why=why,
                     scene=scene["id"], scene_kind=scene["kind"],
                     options={k: round(w, 2) for k, w in options}, rejected=rejected,
                     storyteller_state=self._story_state(), position=[round(scene["x"]), round(scene["z"])],
                     journeys=dict(scene["journeys"]))

    # -- the road ahead --------------------------------------------------------
    def _road_keys(self):
        return list(self.board.network.place_node)

    def _road_ahead(self, hostile=True, min_d=None, max_d=None, rng_jitter=0.3):
        """A point on a road the player is on, ahead of them and out of sight:
        ``(route, cum, s_player, s_stage, dirn, start_key, end_key, x, z)``."""
        s = self.session
        ppos = s._player_pos()
        if ppos is None:
            return None
        px, pz = ppos[0], ppos[2]
        board = self.board
        min_d = STAGE_MIN if min_d is None else min_d
        max_d = min(STAGE_MAX if max_d is None else max_d, self.world.reach() * 0.92)
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

    def _hold(self, j, x, z, scene_id, role, t, hours=None, greeting="",
              wander=90.0, borrowed=False):
        """Stage *j* at (x, z): it waits there (as a rest) for *hours*."""
        hours = HOLD_HOURS if hours is None else hours
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
        """A townsperson as a road party's member: the same person, with their
        own things and their own purse (the gold in their inventory); what
        they come home with is reconciled then (world.SessionHooks.resident_home)."""
        from ..rpg import inventory as rpg_inventory
        p = thing.properties
        return {"role": p.get("npc_role", "villager"), "name": p.get("name", rid),
                "display": p.get("display_name", p.get("name", "Someone")),
                "health": p.get("health", 60), "max_health": p.get("max_health", p.get("health", 60)),
                "damage": p.get("damage", 5), "style": "melee", "alive": True,
                "gold": 0,                 # their real gold is in their inventory
                "inventory": copy.deepcopy(rpg_inventory.get_inventory(thing)),
                "own_purse": True, "head": p.get("head", ""), "resident": rid}

    def _purse(self, j, lead) -> int:
        """Gold the person who pays (*lead*, a live actor) actually holds."""
        from ..rpg import inventory as rpg_inventory
        return rpg_inventory.quantity(rpg_inventory.get_inventory(lead), "gold")

    def _pay(self, j, lead, amount) -> int:
        """Take up to *amount* gold from what *lead* holds; returns what was
        taken. A member whose inventory is not carried keeps its purse figure
        in step, so the gold is not there again when it next appears."""
        from ..rpg import inventory as rpg_inventory
        taken = rpg_inventory.remove_item(rpg_inventory.get_inventory(lead), "gold", int(amount))
        idx = lead.properties.get("_member")
        if j is not None and isinstance(idx, int) and idx < len(j.members):
            m = j.members[idx]
            if "inventory" not in m:
                m["gold"] = max(0, int(m.get("gold", 0) or 0) - taken)
        return taken

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
        if scene.get("decision"):
            scene["text"] = f"{scene['decision']} Result: {scene.get('result', '')}".strip()
        self.scenes[sid] = scene
        if scene.get("text"):
            self._narrate(scene["text"], log=False)   # _log_cast says it, with why
        return scene

    def _where(self, x, z):
        """"1,400 units up the road near Old Camp": where a scene was put."""
        ppos = self.session._player_pos()
        far = f"{math.hypot(x - ppos[0], z - ppos[2]):,.0f} units " if ppos else ""
        return f"{far}ahead of {story_text.PLAYER}, near {self.board.place_name(self._place_at(x, z))}"

    def _from(self, j, borrowed):
        """How a party came to be in the scene."""
        if j.resident:
            home = self.board.place_name(j.home)
            return f"taken from {home} while nobody could see"
        if borrowed:
            return f"already on the roads, {self.board.place_name(j.origin)} to {self.board.place_name(j.dest)}"
        return f"sent out from {self.board.place_name(j.home)}"

    def _camp(self, j) -> str:
        """The camp (or home) a gang came from, by name; "" when it has none."""
        home = getattr(j, "home", "") or ""
        return self.board.place_name(home) if home in self.board.places else ""

    @staticmethod
    def _lead(j):
        lead = j.leader() if j is not None else None
        return lead["display"] if lead else (j.describe() if j is not None else "someone")

    def _place_of(self, fact):
        pos = fact.get("pos") or ()
        return self.board.place_name(self._place_at(pos[0], pos[2])) if len(pos) >= 3 else ""

    @staticmethod
    def _keep_apart(*js):
        """Parties staged to meet live are not settled first by the board's dice."""
        for a in js:
            for b in js:
                if a is not b and b.id not in a.fought:
                    a.fought.append(b.id)

    # -- the scenes ------------------------------------------------------------
    def _stage_waylaid(self, t):
        return self.invoke("waylaid", t)

    def _side_offset(self, spot, d):
        route, cum, _sp, ss, _dirn = spot[:5]
        x0, z0, seg = roads.point_at(route, cum, ss)
        nxt = route[min(len(route) - 1, seg + 1)]
        dx, dz = nxt[0] - x0, nxt[1] - z0
        dl = math.hypot(dx, dz) or 1.0
        return dx / dl * d, dz / dl * d

    def _grievances(self):
        return self.modules["avenger"].grievances(self.context)

    def _culprit_member(self, fact):
        return self.modules["avenger"].culprit_member(self.context, fact)

    def _culprit_actor(self, fact):
        return self.modules["avenger"].culprit_actor(self.context, fact)

    def _stage_avenger(self, t):
        return self.invoke("avenger", t)

    def _avenger_quest(self, sid, member, target_name, target_display, culprit, what, whom,
                       purse, here=True, place=""):
        return self.modules["avenger"].avenger_quest(
            self.context, sid, member, target_name, target_display, culprit, what, whom,
            purse, here=here, place=place)

    def _justified_holders(self, kinds):
        return self.modules["reckoning"].justified_holders(self.context, kinds)

    def _meet(self, t, kinds, scene_kind, hostile):
        return self.modules["reckoning"].meet(self.context, t, kinds, scene_kind, hostile)

    def _stage_reckoning(self, t):
        return self.invoke("reckoning", t)

    def _stage_gratitude(self, t):
        return self.invoke("gratitude", t)

    def _stage_cult_rite(self, t):
        return self.invoke("cult_rite", t)

    def _stage_procession(self, t):
        return self.invoke("procession", t)

    def _stage_ambush(self, t):
        return self.invoke("ambush", t)

    def _stage_patrol(self, t):
        return self.invoke("patrol", t)
    def spawned(self, j, things) -> None:
        """A staged party became actors: give them the scene's conversation,
        thoughts and lines (game/living/scene_talk.py), and hand out its quest."""
        scene = self.scenes.get((j.stage or {}).get("scene", ""))
        if scene is None or not things:
            return
        self._give_talk(scene, j, things)
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

    def _give_talk(self, scene, j, things) -> None:
        role = (j.stage or {}).get("role", "")
        kind, talk = scene["kind"], scene.get("talk") or {}
        want = scene.get("justified", "")
        minds = scene_talk.thoughts(kind, role, talk, want)
        found = scene_talk.topic(kind, role, talk, want)
        for i, thing in enumerate(things):
            p = thing.properties
            p["_scene"] = scene["id"]
            p["_scene_role"] = role
            if minds:
                p["_scene_thoughts"] = minds
            if found is not None and i == 0 and not j.hostile:
                p["dialogue"] = scene_talk.add_topic(p.get("dialogue"), found)

    def _ambient(self, scene, px, pz) -> None:
        """Now and then, someone in an unresolved scene near the player says
        or thinks something that fits it (scene_talk.AMBIENT, THOUGHTS)."""
        import time as _time
        anchor = self._anchor(scene)
        if anchor is None or math.hypot(anchor[0] - px, anchor[1] - pz) > scene_talk.AMBIENT_RADIUS:
            return
        now = _time.monotonic()
        due = self.__dict__.setdefault("_ambient_at", {})   # not saved: real time
        if now < due.get(scene["id"], 0.0):
            return
        s = self.session
        rng = s.rng
        due[scene["id"]] = now + rng.uniform(*scene_talk.AMBIENT_GAP)
        talk, kind, want = scene.get("talk") or {}, scene["kind"], scene.get("justified", "")
        beats = []
        for role, jid in scene["journeys"].items():
            for thing in self._live_things(jid):
                p = thing.properties
                if p.get("dead") or str(p.get("sched_state", "")).upper() in ("COMBAT", "FLEE"):
                    continue
                lines = scene_talk.ambient(kind, role, talk)
                minds = scene_talk.thoughts(kind, role, talk, want).get("calm") or []
                if lines or minds:
                    beats.append((thing, lines, minds))
        if not beats:
            return
        thing, lines, minds = rng.choice(beats)
        think = getattr(s, "think", None)
        if minds and think is not None and (not lines or rng.random() < scene_talk.THOUGHT_CHANCE):
            think(thing, rng.choice(minds))
        elif lines:
            s.bark(thing, rng.choice(lines))

    def repaid(self, npc, scene_id, event, gold) -> None:
        return self.modules["reckoning"].repaid(self.context, npc, scene_id, event, gold)

    def stage_expired(self, j, t) -> bool:
        """A staged party waited out its time unmet; the world moves on."""
        stage = j.stage or {}
        scene = self.scenes.get(stage.get("scene", ""))
        role = stage.get("role")
        if scene is not None and not scene.get("resolved") and scene.get("hinted"):
            # They came near enough to know and went on their way.
            self._learn_scene(scene, False, "they came within sight of it and went on their way")
        if scene is not None and scene["kind"] == "cult_rite":
            handled = self.modules["cult_rite"].stage_expired(
                self.context, j, scene, role, t)
            if handled is not None:
                return handled
        handled = self.modules["avenger"].on_stage_expired(
            self.context, j, stage, scene, t)
        if handled is not None:
            return handled
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
        return self.modules["cult_rite"].sacrifice(self.context, scene, captive, t)

    def _tell_kin(self, captive, scene):
        return self.modules["cult_rite"].tell_kin(self.context, captive, scene)
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
                    module = self.modules.get(scene["kind"])
                    lines = module.hints if module is not None else ()
                    if lines:
                        s.notify(s.rng.choice(lines), 4.0)
            if scene["resolved"]:
                continue
            self._ambient(scene, px, pz)
            module = self.modules.get(scene["kind"])
            if module is not None and module.watch(self.context, scene, px, pz, t):
                continue
            js = scene["journeys"]
            has_friend = "victim" in js or "avenger" in js
            if "attacker" in js:
                if not has_friend or self._party_up(js["attacker"]):
                    continue
            elif "avenger" not in js:
                continue
            friend = js.get("victim") or js.get("avenger")
            things = self._live_things(friend)
            if not self._party_up(friend):
                scene["resolved"] = True
                self._narrate(f"Outcome: {SCENE_NAMES.get(scene['kind'], scene['kind'])} ended badly -- "
                              "the attackers won and nobody was left to save.", scene=scene["id"])
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
        module = self.modules.get(scene["kind"])
        line = (module.thank_line(scene) if module is not None else
                "Gods bless you, stranger -- they'd have had everything.")
        s.bark(lead, line)
        purse = self._purse(j, lead)
        amount = module.reward(self.context, scene, j, lead, purse) if module is not None else 0
        if amount:
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
        how = module.learned_intervention(name) if module is not None else f"they came to {name}'s aid"
        self._learn_scene(scene, True, how)
        paid = (f" They paid {amount} gold from their own purse." if amount else
                " They had no gold to give." if scene.get("reward") and not purse else "")
        self._narrate(f"Outcome: {story_text.PLAYER} stepped in -- the attackers are dead and {name} "
                      f"was saved.{paid} News of it spread from {self.board.place_name(place)}.",
                      scene=scene["id"], gold=amount)
    def _maybe_gift(self, scene, px, pz, t):
        return self.modules["gratitude"].maybe_gift(self.context, scene, px, pz, t)
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
    def persist(self, force=False) -> None:
        store = getattr(self.session, "store", None)
        if store is None:
            return
        # What it has learned rides in the save as minified JSON -- only once
        # there is something (Normal mode, and an untaught director, write nothing).
        if force or self.learned != self.fresh_learning() or store.get(LEARNED_KEY, ""):
            store.set(LEARNED_KEY, json.dumps(self.learned, separators=(",", ":"), sort_keys=True))
        if not self.scenes and not store.get(STORE_KEY, ""):
            return                          # Normal mode leaves the save as it was
        store.set(STORE_KEY, json.dumps({"scenes": list(self.scenes.values()),
                                         "next_id": self.next_id}))

    def restore(self) -> None:
        self.scenes = {}
        self.reset_pacing()
        self.learned = self.fresh_learning()
        store = getattr(self.session, "store", None)
        raw_learned = store.get(LEARNED_KEY, "") if store is not None else ""
        if raw_learned and raw_learned != "false":
            try:
                saved = json.loads(raw_learned)
            except (TypeError, ValueError):
                saved = None
            if isinstance(saved, dict):
                L = self.learned
                L["gap"] = self._bounded(saved.get("gap", 1.0), LEARNING["gap_min"], LEARNING["gap_max"])
                L["hostile"] = self._bounded(saved.get("hostile", 1.0), LEARNING["hostile_min"],
                                             LEARNING["hostile_max"])
                L["scenes"] = {k: self._bounded(v, LEARNING["scene_min"], LEARNING["scene_max"])
                               for k, v in (saved.get("scenes") or {}).items() if k in SCENE_WEIGHTS}
                L["peaks"] = int(saved.get("peaks", 0) or 0)
                L["nudges"] = int(saved.get("nudges", 0) or 0)
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
        line += " · in play: " + ", ".join(playing) if playing else " · nothing in play"
        return line

    def learned_text(self) -> str:
        """What it has learned, in one plain line."""
        if not self.learning_on():
            return "Learning is off ([learning] enabled = false): the values are used as tuned."
        L = self.learned
        if L == self.fresh_learning():
            return "Nothing yet: the values are as tuned."
        scenes = ", ".join(f"{SCENE_NAMES.get(k, k)} ×{v:g}" for k, v in sorted(L["scenes"].items())
                           if v != 1.0)
        return (f"After {L['peaks']} peak(s) and {L['nudges']} nudge(s): time between scenes "
                f"×{L['gap']:g}, hostile scenes ×{L['hostile']:g}"
                + (f"; {scenes}" if scenes else "") + ".")

    def raw(self) -> Dict:
        """Every number behind the decisions, detached (the debug Raw tab)."""
        return copy.deepcopy({
            "enabled": self.enabled(), "phase": self.phase,
            "phase_seconds_left": round(self.phase_left, 1),
            "intensity": round(self.intensity, 3), "gap_seconds_left": round(self.gap_left, 1),
            "peaceful_done": self._peaceful_done, "player_health": round(self._health(), 3),
            "storyteller_state": self._story_state(), "scenes": self.scenes,
            "learned": self.learned, "learning_on": self.learning_on(),
            "decisions": [{k: v for k, v in d.items() if k != "merge"}
                          for d in reversed(self.decisions)],
            "tuning": {"peak": PEAK, "relax_below": RELAX_BELOW, "hurt": HURT,
                       "max_scenes": MAX_SCENES, "stage_min": STAGE_MIN, "stage_max": STAGE_MAX,
                       "build_gap": BUILD_GAP, "relax_seconds": RELAX_SECONDS,
                       "sustain_seconds": SUSTAIN_SECONDS, "hold_hours": HOLD_HOURS,
                       "rite_hours": RITE_HOURS, "learning": dict(LEARNING)},
        })

    def summary(self) -> List[str]:
        """Plain lines for the console."""
        lines = [f"Dynamic director: {self.phase}, intensity {self.intensity:.2f}"
                 + ("" if self.enabled() else " (Normal mode: idle)")]
        for sc in self.scenes.values():
            lines.append(f"  {sc['id']} {sc['kind']}{' (resolved)' if sc['resolved'] else ''}: "
                         f"{sc.get('text', '')}")
        return lines


#: The values the code ships with, before storyteller.ini.
DEFAULTS = tuning()


def load_ini(path=None):
    """Read game/storyteller_dynamic.ini over the code's values.
    Returns the problems found (each a plain sentence); bad values are skipped."""
    from ..sim import tuning_ini
    values, problems = tuning_ini.director_values(DEFAULTS, path)
    retune(copy.deepcopy(DEFAULTS))
    retune(values)
    return problems


load_ini()
