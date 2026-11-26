"""
What the storyteller is doing, in plain words -- one report, two places.

The ``storyteller`` console command opens a window that shows it
(:mod:`game.ui.storyteller_now`), and ``storyteller report`` prints the same
lines into the debug console under the **Storyteller** category. Both read
:meth:`game.sim.storyteller.Storyteller.summary` and the session's clock and
weather; nothing here samples the storyteller, appraises an actor or draws a
random number, so reading it -- even every frame -- changes nothing.

Pure Python (no Qt), so it is tested headless.
"""

from __future__ import annotations

#: Sections ``storyteller report <section>`` can print on their own, in the
#: order the full report shows them.
SECTIONS = ("time", "state", "why", "sensors", "roads", "weather", "recent", "activity")

#: How each pacing state reads at a glance (the window's badge colour).
STATE_COLOURS = {"CALM": (110, 190, 130), "RISING": (225, 180, 80),
                 "PEAK": (225, 95, 85), "RESPITE": (110, 160, 225)}

PRISTINE = "Pacing is off (pristine ecology): sensors idle, no overrides or biases."


def stamp(hours) -> str:
    """World hours as ``Day 9 14:30`` (``-`` before the first sample)."""
    if hours is None:
        return "-"
    day, minutes = divmod(int(round(float(hours) * 60.0)), 24 * 60)
    return f"Day {day} {minutes // 60:02d}:{minutes % 60:02d}"


def clock_line(session) -> str:
    """The date and time, with the season and the day's sunrise and sunset."""
    clock = getattr(session, "clock", None)
    if clock is None:
        return "No game clock."
    try:
        from . import calendar
        return calendar.describe(clock)
    except Exception:
        return f"Day {getattr(clock, 'day', '?')} {getattr(clock, 'time_text', '')}".strip()


def weather_line(session) -> str:
    weather = getattr(session, "weather", None)
    if weather is None:
        return "No weather."
    on = getattr(session, "weather_enabled", lambda: True)
    if callable(on) and not on():
        return "Weather is off in Settings: clear sky, never wet."
    snap = weather.snapshot()
    blizzard = getattr(weather, "blizzard", lambda: False)()
    kind = "BLIZZARD" if blizzard else snap["kind"].upper()
    forced = " (forced from the console)" if getattr(weather, "forced", False) else ""
    snow = (f" · snowfall {snap['snowfall']:.2f} · snow lying {snap['snow']:.2f}"
            if snap.get("snowfall", 0) > 0.01 or snap.get("snow", 0) > 0.01 else "")
    return (f"{kind}{forced}, {snap['left']:.1f} h left · rain {snap['rain']:.2f}{snow} · "
            f"ground wet {snap['wet']:.2f}. The storyteller does not steer the weather yet.")


def _hours(value) -> str:
    return "-" if value is None else f"{float(value):g}"


def _sensors(s) -> str:
    if not s:
        return "Not sampled yet."
    parts = [f"health {float(s.get('health', 0)):.0%}", f"tension {float(s.get('tension', 0)):.2f}",
             f"{s.get('attacks', 0)} attacks on you", f"{s.get('deaths', 0)} deaths",
             f"{s.get('hostiles', 0)} hostiles in sight",
             f"{s.get('loose_threads', 0)} unreported crimes remembered",
             f"{s.get('vendettas', 0)} kin vendettas",
             f"{s.get('justified', s.get('vendettas', 0))} justified journeys",
             "law pressure" if s.get("law_pressure") else "no law pressure"]
    if "hostile_arrivals_per_hour" in s:
        parts.append(f"{float(s['hostile_arrivals_per_hour']):.2f} hostile arrivals/h")
    return " · ".join(parts)


def _roads(summary) -> str:
    levers = summary.get("levers") or {}
    if not summary.get("enabled"):
        return "Authored defaults (pacing off)."
    weights = summary.get("local_weights") or levers.get("kind_weights") or {}
    pop = levers.get("population")
    cap = summary.get("population_cap")
    capped = f" (capped at {cap}: no arrivals)" if cap is not None and pop == cap else ""
    kinds = " · ".join(f"{k} {float(v):g}" for k, v in weights.items())
    bounty = summary.get("local_hunter_bounty", levers.get("hunter_bounty"))
    return (f"population {pop}{capped} · {kinds} · hunters at {float(bounty or 0):g}g bounty · "
            f"market trips {float(levers.get('market_chance', 0)):.0%} · "
            f"town bias ×{float(levers.get('destination_bias', 1)):g} · "
            f"vendetta bias ×{float(levers.get('vendetta_bias', 1)):g}")


def rows(story, session=None, section=None, *, history=5, activity=12):
    """``[(label, text), ...]`` for the report, or only *section* (a name or a
    tuple of names) of it.

    ``label`` is a short capitalised word (the left column); an activity row's
    label is its time. Raises ``ValueError`` for an unknown section."""
    chosen = SECTIONS if section is None else (section,) if isinstance(section, str) else tuple(section)
    unknown = [name for name in chosen if name not in SECTIONS]
    if unknown:
        raise ValueError(f"Unknown section {unknown[0]!r}; one of: {', '.join(SECTIONS)}")
    want = chosen.__contains__
    out = []
    if story is None:
        return [("Storyteller", "No active MiniWind storyteller.")]
    s = story.summary()
    if want("time"):
        out.append(("Time", clock_line(session)))
    if want("state"):
        age = s.get("age")
        limits = f"min {_hours(s.get('min_hours'))} h" + (
            f", max {_hours(s.get('max_hours'))} h" if s.get("max_hours") is not None else ", no maximum")
        held = "not sampled yet" if age is None else f"for {age:.1f} h"
        out.append(("State", f"{s['state']} {held} ({limits}) → next {s['next']}"))
        out.append(("Purpose", s["purpose"]))
    if want("why"):
        out.append(("Why", s.get("decision") or (PRISTINE if not s["enabled"] else
                                                   "Waiting for the first sample.")))
        if s.get("arrivals"):
            out.append(("Arrivals", s["arrivals"]))
    if want("sensors"):
        out.append(("Sensing", _sensors(s.get("sensors"))))
    if want("roads"):
        out.append(("Roads", _roads(s)))
    if want("weather"):
        out.append(("Weather", weather_line(session)))
    if want("recent"):
        obs = s.get("observations") or []
        text = " · ".join(f"{stamp(o['time'])[-5:]} {o['state']}" for o in obs[:history])
        out.append(("Recent", text or "No samples yet."))
    if want("activity"):
        feed = s.get("activity") or []
        if not feed:
            out.append(("Activity", "Nothing yet: state changes, caps, edits and biased journeys appear here."))
        for entry in feed[:activity]:
            out.append((stamp(entry.get("time")), entry["text"]))
    return out


def header(story) -> str:
    """The report's title line."""
    if story is None:
        return "═══ STORYTELLER ═══"
    return (f"═══ STORYTELLER ═══  {story.state} · "
            f"{'pacing ON' if story.enabled else 'pacing OFF (pristine ecology)'}")


# ---------------------------------------------------------------------------
# Dynamic game mode's director (game/living/scenarios.py)
# ---------------------------------------------------------------------------
def director_of(session):
    """The session's Dynamic-mode director, or None."""
    living = getattr(session, "living", None)
    return getattr(living, "scenarios", None)


def dynamic_shown(session) -> bool:
    """Whether the director has anything to show: Dynamic mode is on, or
    scenes it staged are still playing out. Normal mode shows nothing."""
    director = director_of(session)
    if director is None:
        return False
    return bool(director.enabled() or director.scenes)


def dynamic_rows(session, limit=15):
    """``[(label, text)]``: the director's state and its decisions, newest
    first, in plain words. Empty in Normal mode."""
    if not dynamic_shown(session):
        return []
    director = director_of(session)
    out = [("Director", director.status()), ("Learned", director.learned_text())]
    for scene in director.scenes.values():
        state = "played out" if scene.get("resolved") else "in play"
        out.append(("Scene", f"{scene.get('text', scene['kind'])} ({state})"))
    decisions = list(reversed(director.decisions))[:limit]
    if not decisions:
        out.append(("Decided", "Nothing yet: every choice, and why, appears here."))
    for entry in decisions:
        out.append((stamp(entry.get("time")), entry["text"]))
        if entry.get("result"):
            out.append(("Result", entry["result"]))
        if entry.get("why"):
            out.append(("Why now", entry["why"]))
    return out


def _flat(prefix, value, out, depth=0):
    """Nested data as ``(key path, value)`` rows: short values on one line."""
    import json
    if isinstance(value, dict) and value and depth < 2:
        for key, inner in value.items():
            _flat(f"{prefix}.{key}" if prefix else str(key), inner, out, depth + 1)
        return
    if prefix in ("decisions", "activity", "observations") and isinstance(value, list):
        for i, inner in enumerate(value):        # one row per entry, newest first
            out.append((f"{prefix}[{i}]", json.dumps(inner, ensure_ascii=False, default=str)))
        if not value:
            out.append((prefix, "[]"))
        return
    out.append((prefix, json.dumps(value, ensure_ascii=False, default=str)))


def raw_rows(story, session=None, *, decisions=20, observations=5):
    """``[(heading or None, key, value text)]``: the raw data behind the
    report -- the storyteller's summary and, in Dynamic mode, the director's
    numbers -- for the debug window's Raw tab and ``storyteller report raw``."""
    out = []
    if story is not None:
        s = story.summary()
        s["observations"] = s.get("observations", [])[:observations]
        s["activity"] = s.get("activity", [])[:decisions]
        rows = []
        _flat("", s, rows)
        out.append(("Storyteller · summary()", None, None))
        out += [(None, key, value) for key, value in rows]
    if dynamic_shown(session):
        raw = director_of(session).raw()
        raw["decisions"] = raw["decisions"][:decisions]
        rows = []
        _flat("", raw, rows)
        out.append(("Dynamic director · raw()", None, None))
        out += [(None, key, value) for key, value in rows]
    return out
