"""The storyteller's two tuning files, in the game folder.

* **game/storyteller_normal.ini** -- the storyteller itself, in both game
  modes: sensing, tension, distances, how strongly grudges draw trips, and
  each pacing state (CALM, RISING, PEAK, RESPITE) with its levers.
* **game/storyteller_dynamic.ini** -- Dynamic mode's director only: pacing
  and staging, how often each scene is picked, how the storyteller's state
  scales it, and how it learns.

Each is a layer over what comes before it: the code's own defaults, then (for
the storyteller) ``game/data/storyteller.json`` and mods, then the file.
Every setting ships switched off (a ';' in front) at the value the game uses,
so nothing changes until a line is switched on. A value that cannot be read,
or an unknown key, is skipped and reported (console ``storyteller reload``).

What the director *learns* is not written here: it lives in the save, as
minified JSON (``game/living/scenarios.py``), on top of these values.

Pure Python: no engine, no Qt.
"""

from __future__ import annotations

import configparser
import copy
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#: Where the files live: the game folder.
GAME_DIR = Path(__file__).resolve().parents[1]
NORMAL_PATH = GAME_DIR / "storyteller_normal.ini"
DYNAMIC_PATH = GAME_DIR / "storyteller_dynamic.ini"

STATES = ("CALM", "RISING", "PEAK", "RESPITE")

#: [storyteller] keys and what they do (the values come from the tuning).
STORYTELLER_KEYS = {
    "enabled": "false = pristine ecology: no pacing, no overrides or biases",
    "sample_hours": "game hours between the storyteller's samples",
    "healthy": "health fraction at which the player counts as healthy",
    "danger_health": "health fraction below which the player is in danger",
    "peak_tension": "tension at which RISING may crest into PEAK",
    "recovered_tension": "tension below which RESPITE may end",
    "attack_tension": "tension one attack on the player adds",
    "death_tension": "tension a death adds",
    "hostile_tension": "tension each visible hostile adds",
    "pressure_bounty": "bounty at which law pressure counts toward rising",
    "sight_radius": "world units: how far the storyteller counts visible hostiles",
    "staging_distance": "world units: how near a justified journey must be to be weighted",
    "vendetta_trip_distance": "world units: the furthest a grudge-holder's market trip is redirected",
    "arrival_window_hours": "game hours over which hostile arrivals are counted",
    "unpaid_writ_hours": "game hours an unpaid writ waits before hunters come cheaper",
    "prosperity_bandit_bias": "how strongly the player's wealth draws brigands",
    "notoriety_hunter_scale": "how strongly the player's notoriety lowers the hunter bounty",
    "activity_cap": "entries kept in the activity feed",
    "observation_cap": "samples kept in the observation history",
}
LEVER_KEYS = {
    "min_hours": "game hours the state lasts at least",
    "max_hours": "game hours it lasts at most (none = no limit)",
    "population": "parties on the roads",
    "hunter_bounty": "bounty at which bounty hunters set out",
    "lair_refill_scale": "multiplier on how long a cleared lair takes to refill",
    "market_chance": "chance (0-1) a townsperson walks to market",
    "destination_bias": "how strongly remembered crimes draw trips to a town",
    "vendetta_bias": "how strongly a grudge draws its holder toward the player",
    "writ_hunter_scale": "hunter bounty multiplier once a writ is old",
}
DYNAMIC_KEYS = {
    "peak": "tension (0-1) at which build-up stops and the peak is held",
    "relax_below": "tension below which easing off may become a rest",
    "sustain_seconds": "real seconds the peak is held (min-max)",
    "relax_seconds": "real seconds a rest lasts (min-max)",
    "first_relax": "real seconds of rest when a session starts",
    "build_gap": "real seconds between scenes while building (min-max)",
    "damage_gain": "tension per whole health bar lost",
    "engaged_gain": "tension per second for each hostile fighting near the player",
    "calm_decay": "tension lost per second when calm",
    "tense_decay": "tension lost per second while threatened",
    "threat_radius": "world units: hostiles nearer than this raise tension",
    "hurt": "health fraction below which no new threats are staged",
    "max_scenes": "most scenes in play at once",
    "stage_min": "world units: scenes are staged at least this far ahead",
    "stage_max": "world units: and no further than this",
    "on_road": "world units: how near a road the player must be",
    "town_clear": "world units: hostile scenes keep this far from towns",
    "quarry_gap": "world units: how far beyond an avenger their quarry waits",
    "hold_hours": "game hours a staged party waits before the world moves on",
    "rite_hours": "game hours before an unbroken cult rite is finished",
    "hint_radius": "world units: the hint line shows from this near",
    "thank_radius": "world units: a rescued party thanks the player from this near",
    "grievance_days": "game days a grievance can still send an avenger out",
}
LEARNING_KEYS = {
    "enabled": "false = the director never learns and uses this file's values as they are",
    "step": "how far one nudge moves the pace (the gap and hostile scales below)",
    "scene_step_up": "how much a scene gains each time the player steps into one",
    "scene_step_down": "how much it loses each time the player passes one by",
    "gap_min": "the time between scenes never drops below this share of build_gap",
    "gap_max": "nor rises above this share",
    "hostile_min": "hostile scenes are never picked less than this share as often",
    "hostile_max": "nor more than this share",
    "scene_min": "no scene is ever picked less than this share as often",
    "scene_max": "nor more than this share",
    "overwhelmed_health": "a peak that left the player below this health was too hard",
    "breezed_health": "a peak the player came through above this health was too easy",
}
SCENE_KEYS = {
    "gratitude": "someone grateful to the player (also in rests)",
    "waylaid": "a traveller set upon by brigands",
    "avenger": "a townsperson out for revenge",
    "reckoning": "someone settling a score with the player",
    "patrol": "the watch fighting brigands",
    "cult_rite": "a cult rite with a captive (night only)",
    "ambush": "brigands lying in wait (night; half as likely at dusk)",
    "procession": "a cult procession (night only)",
}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def _parser(path) -> Tuple[Optional[configparser.ConfigParser], List[str]]:
    path = Path(path)
    if not path.exists():
        return None, []
    parser = configparser.ConfigParser(inline_comment_prefixes=("#",),
                                       comment_prefixes=(";", "#"))
    parser.optionxform = str                     # keep "weight.bandits", "gap.CALM"
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError) as exc:
        return None, [f"{path.name} could not be read ({exc}); its values were ignored."]
    return parser, []


def _coerce(raw: str, like):
    """*raw* read as the same kind of value as *like*; ValueError if it can't be."""
    text = raw.strip()
    if isinstance(like, bool):
        low = text.lower()
        if low in ("1", "true", "yes", "on"):
            return True
        if low in ("0", "false", "no", "off"):
            return False
        raise ValueError("expected true or false")
    if isinstance(like, (tuple, list)) and len(like) == 2:
        parts = [p for p in text.replace(",", " ").replace("-", " ").split() if p]
        if len(parts) != 2:
            raise ValueError("expected two numbers, like 45-90")
        a, b = float(parts[0]), float(parts[1])
        if all(isinstance(v, int) and not isinstance(v, bool) for v in like) \
                and a.is_integer() and b.is_integer():
            a, b = int(a), int(b)
        return type(like)((a, b)) if isinstance(like, tuple) else [a, b]
    if like is None or isinstance(like, (int, float)):
        if text.lower() in ("none", ""):
            if like is None:
                return None
            raise ValueError("expected a number")
        value = float(text)
        if value < 0:
            raise ValueError("must not be negative")
        if isinstance(like, int) and not value.is_integer() and not isinstance(like, bool):
            return value                     # a weight may be fractional
        return int(value) if isinstance(like, int) else value
    raise ValueError("this value cannot be set here")


def _set(target: Dict, key: str, raw: str, like, where: str, problems: List[str]) -> None:
    try:
        target[key] = _coerce(raw, like)
    except ValueError as exc:
        problems.append(f"[{where}] {key} = {raw.strip()}: {exc}; kept {like!r}.")


def apply_storyteller(tuning: Dict, path=None) -> List[str]:
    """Write storyteller_normal.ini over *tuning* (in place)."""
    parser, problems = _parser(path or NORMAL_PATH)
    if parser is None:
        return problems
    from ..living.journeys import KINDS
    if parser.has_section("storyteller"):
        for key, raw in parser.items("storyteller"):
            if key not in STORYTELLER_KEYS or key not in tuning:
                problems.append(f"[storyteller] {key}: unknown key, skipped.")
                continue
            _set(tuning, key, raw, tuning[key], "storyteller", problems)
    if parser.has_section("justified journeys"):
        table = tuning.setdefault("justified_journeys", {})
        for key, raw in parser.items("justified journeys"):
            if key not in table:
                problems.append(f"[justified journeys] {key}: unknown kind, skipped.")
                continue
            _set(table, key, raw, float(table[key]), "justified journeys", problems)
    for state in STATES:
        if not parser.has_section(state) or state not in tuning.get("states", {}):
            continue
        row = tuning["states"][state]
        levers = row["levers"]
        for key, raw in parser.items(state):
            if key in ("min_hours", "max_hours"):
                if raw.strip().lower() == "none":
                    if key == "max_hours":
                        row.pop(key, None)           # no limit
                    else:
                        problems.append(f"[{state}] min_hours needs a number; kept.")
                    continue
                _set(row, key, raw, 0.0, state, problems)
            elif key.startswith("weight."):
                kind = key[7:]
                if kind not in KINDS:
                    problems.append(f"[{state}] {key}: unknown party kind, skipped.")
                    continue
                weights = levers.setdefault("kind_weights", {})
                _set(weights, kind, raw, weights.get(kind, KINDS[kind]["weight"]), state, problems)
            elif key.startswith("hours."):
                kind = key[6:]
                if kind not in KINDS:
                    problems.append(f"[{state}] {key}: unknown party kind, skipped.")
                    continue
                hours = levers.setdefault("kind_hours", {})
                _set(hours, kind, raw, list(hours.get(kind, KINDS[kind]["hours"])), state, problems)
                if kind in hours and any(not 0 <= h <= 24 for h in hours[kind]):
                    problems.append(f"[{state}] {key}: hours must be 0-24; skipped.")
                    hours.pop(kind)
            elif key in LEVER_KEYS and key in levers:
                _set(levers, key, raw, levers[key], state, problems)
                if key == "market_chance" and levers[key] > 1:
                    problems.append(f"[{state}] market_chance must be 0-1; set to 1.")
                    levers[key] = 1.0
            else:
                problems.append(f"[{state}] {key}: unknown key, skipped.")
    return problems


def director_values(defaults: Dict, path=None) -> Tuple[Dict, List[str]]:
    """The director's tuning from storyteller_dynamic.ini, shaped like
    ``scenarios.tuning()``: only the keys the file switches on."""
    parser, problems = _parser(path or DYNAMIC_PATH)
    values = {"dynamic": {}, "scene_weights": {}, "state_gap": {}, "state_hostile": {},
              "learning": {}}
    if parser is None:
        return values, problems
    for section, table in (("director", "dynamic"), ("scene weights", "scene_weights"),
                           ("learning", "learning")):
        if not parser.has_section(section):
            continue
        for key, raw in parser.items(section):
            if key not in defaults[table]:
                problems.append(f"[{section}] {key}: unknown key, skipped.")
                continue
            like = defaults[table][key]
            _set(values[table], key, raw, float(like) if table == "scene_weights" else like,
                 section, problems)
    if parser.has_section("storyteller states"):
        for key, raw in parser.items("storyteller states"):
            table, _, state = key.partition(".")
            target = {"gap": "state_gap", "hostile": "state_hostile"}.get(table)
            if target is None or state not in defaults[target]:
                problems.append(f"[storyteller states] {key}: unknown key, skipped.")
                continue
            _set(values[target], state, raw, float(defaults[target][state]),
                 "storyteller states", problems)
    return values, problems


# ---------------------------------------------------------------------------
# Writing (the shipped files, from the values the game actually uses)
# ---------------------------------------------------------------------------
def _fmt(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (tuple, list)):
        return "-".join(_fmt(v) for v in value)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


_HOW = [
    "# Every setting is listed with the value the game uses now, switched off by",
    "# the ';' in front of it. Delete the ';' to make a setting yours, then change",
    "# its value. A value that cannot be read is skipped and reported.",
    "#",
    "# Read when the game starts and each time Play starts. In Play, the console",
    "# command `storyteller reload` applies an edit at once.",
    "#",
    "# Units: world units (a player is about 64 tall); game hours (one game hour",
    "# is a real minute at the usual clock); real seconds where it says seconds.",
]


def render_normal(tuning: Dict) -> str:
    """storyteller_normal.ini for *tuning*, documented."""
    from ..living.journeys import KINDS
    out = ["# MiniWind -- storyteller_normal.ini",
           "#",
           "# The storyteller, in both game modes. It paces what the world already",
           "# holds: it samples and biases journeys, destinations and grudges that exist,",
           "# and never makes anything up. Settings switched on here win over the code",
           "# and over game/data/storyteller.json (and mods). A loaded save keeps the",
           "# levers it was saved with until its next state change (or a reload).",
           "# Dynamic mode's director is tuned in storyteller_dynamic.ini.",
           "# See docs/storyteller.md and docs/game_modes.md.",
           "#", *_HOW, "", "[storyteller]"]
    for key, note in STORYTELLER_KEYS.items():
        if key in tuning:
            out.append(f"# {note}")
            out.append(f";{key} = {_fmt(tuning[key])}")
    out += ["", "[justified journeys]",
            "# how strongly each kind of grudge draws its holder's trip toward the player",
            "# (share of the state's vendetta_bias; 0 = an ordinary trip)"]
    for key, value in tuning.get("justified_journeys", {}).items():
        out.append(f";{key} = {_fmt(float(value))}")
    for state in STATES:
        row = tuning["states"][state]
        levers = row["levers"]
        out += ["", f"[{state}]", f"# {row.get('reason', '')}",
                f"# next: {row.get('next', '')}"]
        for key in ("min_hours", "max_hours"):
            out.append(f"# {LEVER_KEYS[key]}")
            out.append(f";{key} = {_fmt(float(row[key])) if row.get(key) is not None else 'none'}")
        for key, note in LEVER_KEYS.items():
            if key in levers:
                out.append(f"# {note}")
                out.append(f";{key} = {_fmt(levers[key])}")
        out.append("# road party weights (0 = none set out); unset kinds use their usual weight:")
        out.append("# " + ", ".join(f"{k} {_fmt(float(s['weight']))}" for k, s in KINDS.items()))
        for kind, value in levers.get("kind_weights", {}).items():
            out.append(f";weight.{kind} = {_fmt(float(value))}")
        out.append("# hours a party kind sets out (from-until, may cross midnight); unset kinds")
        out.append("# use their usual hours, e.g. hours.bandits = 17-24")
        for kind, value in levers.get("kind_hours", {}).items():
            out.append(f";hours.{kind} = {_fmt([float(v) for v in value])}")
    return "\n".join(out) + "\n"


def render_dynamic(director: Dict) -> str:
    """storyteller_dynamic.ini for *director* (``scenarios.tuning()``), documented."""
    out = ["# MiniWind -- storyteller_dynamic.ini",
           "#",
           "# Dynamic game mode's director only: it stages scenes on the roads, cast from",
           "# the world's own people and grudges (game/living/scenarios.py). Normal mode",
           "# ignores this file. See docs/game_modes.md.",
           "#",
           "# The director also learns: it nudges the time between scenes, how often",
           "# hostile scenes come and how often each scene is picked, in small steps",
           "# within the limits in [learning], and explains every nudge. What it learns",
           "# lives in the save, on top of the values here.",
           "#", *_HOW, "", "[director]"]
    for key, note in DYNAMIC_KEYS.items():
        out.append(f"# {note}")
        out.append(f";{key} = {_fmt(director['dynamic'][key])}")
    out += ["", "[scene weights]",
            "# how often each scene is picked against the others that fit the moment"]
    for key, note in SCENE_KEYS.items():
        out.append(f"# {note}")
        out.append(f";{key} = {_fmt(float(director['scene_weights'][key]))}")
    out += ["", "[storyteller states]",
            "# how the storyteller's state scales the director:",
            "# gap = the time between scenes, hostile = how often hostile scenes are picked"]
    for state in STATES:
        out.append(f";gap.{state} = {_fmt(float(director['state_gap'][state]))}")
        out.append(f";hostile.{state} = {_fmt(float(director['state_hostile'][state]))}")
    out += ["", "[learning]",
            "# how the director tunes itself to the player, a small step at a time"]
    for key, note in LEARNING_KEYS.items():
        out.append(f"# {note}")
        out.append(f";{key} = {_fmt(director['learning'][key])}")
    return "\n".join(out) + "\n"


def write_default(normal_path=None, dynamic_path=None) -> Tuple[Path, Path]:
    """Write both files from the values the code (and storyteller.json) give,
    ignoring any existing files (for shipping, or to start over)."""
    from . import storyteller
    from ..living import scenarios
    normal = Path(normal_path) if normal_path else NORMAL_PATH
    dynamic = Path(dynamic_path) if dynamic_path else DYNAMIC_PATH
    normal.write_text(render_normal(storyteller.load_tuning(use_ini=False)), encoding="utf-8")
    dynamic.write_text(render_dynamic(copy.deepcopy(scenarios.DEFAULTS)), encoding="utf-8")
    return normal, dynamic
