"""Reusable, renderer-independent pathfinding reports (console ``paths``).

Schema version 1 is shared by the live overlay, console report and JSON export.
Capturing a report never calls the planner or changes an actor's destination.
See docs/PATHFINDING_DEBUG.md for investigation and comparison workflows.
"""

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import math
from pathlib import Path

from engine.spatial import TIER_ACTIVE, TIER_DORMANT, TIER_NAMES, tier_of
from .navigation import CLEAR_CHECK_SECONDS, RETRY_SECONDS, ROUTE_SECONDS

STATES = ("all", "route", "failed", "direct", "chase")
TIERS = ("all", "near", "active", "distant", "dormant")


@dataclass(frozen=True)
class Settings:
    state: str = "all"
    tier: str = "all"
    actor: str = ""
    radius: float = 3200.0
    labels: bool = True


def settings(session):
    return getattr(session, "path_debug_settings", Settings())


def configure(session, *, enabled=None, **changes):
    current = replace(settings(session), **changes)
    if current.state not in STATES:
        raise ValueError("state must be " + ", ".join(STATES))
    if current.tier not in TIERS:
        raise ValueError("tier must be " + ", ".join(TIERS))
    if not math.isfinite(current.radius) or current.radius <= 0:
        raise ValueError("radius must be a finite positive number")
    session.path_debug_settings = current
    if enabled is not None:
        session.show_paths = bool(enabled)
        session.nav.set_debug(enabled)
    return current


def actor_records(session):
    """Detached, filtered records for live actors; safe for UI and automation."""
    if not getattr(session, "show_paths", False):
        return []
    config = settings(session)
    actors = list(session._live_actors())
    by_id = {id(actor): actor for actor in actors}
    player = session._player_pos()
    snapshots = session.nav.debug_snapshot()
    stats = session.nav.search_stats()
    out = []
    for actor in actors:
        props = actor.properties
        if props.get("dead") or props.get("hidden"):
            continue
        tier = tier_of(actor)
        if tier >= TIER_DORMANT:
            continue  # Never enumerate parked/unloaded actors for debugging.
        tier_name = TIER_NAMES[tier]
        if config.tier != "all" and config.tier != tier_name.lower():
            continue
        key = id(actor)
        name = str(props.get("display_name") or props.get("name") or getattr(actor, "name", key))
        if config.actor and config.actor.casefold() not in name.casefold() and config.actor != str(key):
            continue
        pos = tuple(float(v) for v in actor.pos)
        if player is not None and math.hypot(pos[0] - player[0], pos[2] - player[2]) > config.radius:
            continue
        live_navigation = tier <= TIER_ACTIVE
        record = dict(snapshots.get(key, {})) if live_navigation else {}
        chasing = props.get("triggered") is False
        if not record:
            goal = props.get("_dest")
            if chasing:
                target = by_id.get(props.get("_aggro_target"))
                if target is not None:
                    goal = target.pos
                elif str(props.get("aggression")) == "hostile" and props.get("awake"):
                    goal = player
            if goal is None:
                continue
            record = {"goal": tuple(float(v) for v in goal), "points": (),
                      "state": "direct", "decision": "direct_goal" if live_navigation
                      else "bigworld_coarse", "route_age": None}
        record.update(stats.get(key, {}))
        if chasing and record["state"] == "direct":
            record["state"] = "chase"
        if config.state != "all" and record["state"] != config.state:
            continue
        record.update(key=key, name=name, pos=pos, movement="chase" if chasing else "schedule",
                      tier=tier_name, live_navigation=live_navigation)
        out.append(record)
    return out


def report(session):
    """JSON-compatible diagnostic API for future behavioural/performance work."""
    actors = actor_records(session)
    return {"schema_version": 1,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "enabled": bool(getattr(session, "show_paths", False)),
            "filters": asdict(settings(session)),
            "cadence": {"ai_hz": 30, "visibility_seconds": CLEAR_CHECK_SECONDS,
                        "failed_retry_seconds": RETRY_SECONDS, "route_seconds": ROUTE_SECONDS},
            "summary": {"actors": len(actors),
                        "searches": sum(a.get("searches", 0) for a in actors),
                        "failed_searches": sum(a.get("failed_searches", 0) for a in actors),
                        "search_ms": sum(a.get("search_ms", 0.0) for a in actors),
                        "cached_cells": len(session.nav._cells)},
            "actors": actors}


def export(session, filename="cache/pathfinding-debug.json"):
    path = Path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report(session), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return path
