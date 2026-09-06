"""
Off-screen daily resolution + a persistent settlement event log (§13 growth).

MiniWind deliberately does **not** simulate off-screen NPCs frame-by-frame — the
low-power brief means an unloaded townsperson snaps to its scheduled spot rather
than being ticked in the background (see ``PLAN.md`` §13). But "persistent NPC
behaviour" implies that *something happened while the player was away*, not that
the world froze between visits. This module fills that gap the cheap way: at each
in-game **day boundary** it resolves one day of settlement life in a single pass
— merchants restock, debts are chipped away, the town's grief fades, farmers
bring in a harvest, and remembered slights soften a little — and records what
happened as a durable, human-readable **day log**.

Everything is written through the same string KV store the rest of the game
persists into, so the resolution runs exactly once per day even across save/load
(guarded by ``world.last_resolved_day``) and the log round-trips like any other
world state. Pure functions over the store plus a list of NPC property dicts —
no live scene, no Qt, fully headless-testable.
"""

from __future__ import annotations

import json
from typing import Dict, Iterable, List, Optional

from . import disposition

#: A newly-seeded debt (in coin) when relationships imply one but none is stored.
_DEFAULT_DEBT = 3
#: Most a debtor pays down in a single day.
_DEBT_PAYMENT = 1
#: Days after the last death before the town's active mourning quiets.
_MOURNING_DAYS = 2
#: Never resolve more than this many days in one catch-up pass (a pathological
#: clock jump shouldn't spin for thousands of iterations).
_MAX_CATCHUP = 30
#: Rolling day-log cap (most recent kept).
_LOG_CAP = 40


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _get_int(store, key: str, default: int = 0) -> int:
    try:
        return int(float(store.get(key, str(default))))
    except (TypeError, ValueError):
        return default


def _name(props: Dict) -> str:
    return str(props.get("display_name") or props.get("name") or "Someone")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def resolve_pending(store, day, actors: Iterable[Dict], rng=None) -> List[str]:
    """Resolve every in-game day elapsed since the last pass; return log lines.

    On the very first call it only records the baseline day (nothing has
    "passed" yet) and returns ``[]``. Thereafter each new day is resolved once,
    its events appended to the persistent day log, and ``world.last_resolved_day``
    advanced. Safe to call on every day-change tick — a no-op when no day has
    turned over."""
    if store is None:
        return []
    day = int(day)
    actors = list(actors)
    raw = store.get("world.last_resolved_day", None)
    if raw in (None, "", "false"):
        store.set("world.last_resolved_day", day)
        return []
    try:
        last = int(float(raw))
    except (TypeError, ValueError):
        store.set("world.last_resolved_day", day)
        return []
    if day <= last:
        return []

    all_events: List[str] = []
    first = last + 1
    stop = min(day, last + _MAX_CATCHUP)
    for d in range(first, stop + 1):
        events = _resolve_one_day(store, d, actors, rng)
        if events:
            _append_log(store, d, events)
            all_events.extend(events)
    store.set("world.last_resolved_day", day)
    return all_events


# ---------------------------------------------------------------------------
# One day's resolution
# ---------------------------------------------------------------------------
def _resolve_one_day(store, day: int, actors: List[Dict], rng=None) -> List[str]:
    events: List[str] = []
    events += _restock_merchants(store, actors)
    events += _settle_debts(store, actors, rng)
    events += _bring_in_harvest(store, actors)
    events += _fade_mourning(store, day)
    disposition_daily_decay(store)
    return events


def _restock_merchants(store, actors: List[Dict]) -> List[str]:
    """Top a merchant's coin purse back up to its baseline overnight."""
    events: List[str] = []
    for p in actors:
        if not p.get("merchant") or p.get("dead"):
            continue
        base = p.get("merchant_gold_base")
        cur = int(p.get("merchant_gold", 0) or 0)
        if base is None:
            base = max(cur, 1)
            p["merchant_gold_base"] = base
        base = int(base)
        if cur < base:
            p["merchant_gold"] = base
            events.append(f"{_name(p)} restocked the shop and counted out fresh coin.")
    return events


def _settle_debts(store, actors: List[Dict], rng=None) -> List[str]:
    """Chip away debts implied by relationships (a "creditor" tie = money owed).

    An NPC whose ``relationships`` names someone as their *creditor* owes that
    person; each day a little is paid down. Debts are seeded once into the store
    (``debt.<debtor>.<creditor>``) and clearing one warms the pair's standing —
    a durable consequence of simply time passing."""
    events: List[str] = []
    for p in actors:
        debtor = str(p.get("name") or "")
        rels = p.get("relationships")
        if not debtor or not isinstance(rels, dict) or p.get("dead"):
            continue
        for creditor, role in rels.items():
            if str(role).lower() != "creditor":
                continue
            key = f"debt.{debtor}.{creditor}"
            raw = store.get(key, None)
            if raw in (None, "", "false"):
                owed = _DEFAULT_DEBT
                store.set(key, owed)
            else:
                try:
                    owed = int(float(raw))
                except (TypeError, ValueError):
                    owed = 0
            if owed <= 0:
                continue
            pay = min(_DEBT_PAYMENT, owed)
            owed -= pay
            store.set(key, owed)
            if owed <= 0:
                events.append(f"{debtor} finally cleared the coin owed to {creditor}.")
            else:
                events.append(f"{debtor} paid {creditor} a little of what they owe.")
    return events


def _bring_in_harvest(store, actors: List[Dict]) -> List[str]:
    """A farmer's day in the fields adds to the settlement's stores."""
    events: List[str] = []
    for p in actors:
        if p.get("dead"):
            continue
        role = str(p.get("npc_role") or "").lower()
        if role != "farmer":
            continue
        name = str(p.get("name") or "farmer")
        key = f"stock.{name}"
        store.set(key, _get_int(store, key, 0) + 2)
        events.append(f"{_name(p)} brought in the day's harvest.")
    return events


def _fade_mourning(store, day: int) -> List[str]:
    """Let active grief quiet a couple of days after the last death.

    The dead are still remembered (``dead.<name>`` stays set); only the raw,
    town-wide ``town.mourning`` alert lifts, so daily life resumes."""
    if not _truthy(store.get("town.mourning", "false")):
        return []
    last_death_day = _get_int(store, "town.last_death_day", day)
    if day - last_death_day < _MOURNING_DAYS:
        return []
    store.set("town.mourning", "0")
    who = store.get("town.last_death", "")
    who = "" if who in (None, "false", "") else str(who)
    if who:
        return [f"The town's grief for {who} has quieted, though none forget."]
    return ["The town's grief has quieted, though none forget."]


def disposition_daily_decay(store) -> None:
    """Nudge every remembered per-NPC disposition delta one step toward zero.

    Time softens both grudges and goodwill: a slight the player never repeats
    fades, and so does a single good turn. Iterates the memory keys already in
    the store, so it costs nothing on a world where the player has met no one."""
    try:
        items = store.all()
    except Exception:
        return
    for key, value in list(items.items()):
        if not (key.startswith("npc.") and key.endswith(".disp")):
            continue
        try:
            d = int(float(value))
        except (TypeError, ValueError):
            continue
        if d > 0:
            store.set(key, d - 1)
        elif d < 0:
            store.set(key, d + 1)


# ---------------------------------------------------------------------------
# The persistent day log
# ---------------------------------------------------------------------------
def _append_log(store, day: int, lines: List[str]) -> None:
    recent = recent_log(store)
    for line in lines:
        recent.append({"day": int(day), "text": str(line)})
    if len(recent) > _LOG_CAP:
        recent = recent[-_LOG_CAP:]
    try:
        store.set("daylog.recent", json.dumps(recent))
        store.set(f"daylog.{int(day)}", json.dumps([str(x) for x in lines]))
    except (TypeError, ValueError):
        pass


def recent_log(store) -> List[Dict]:
    """The rolling settlement log as ``[{"day", "text"}, …]`` (oldest first)."""
    if store is None:
        return []
    raw = store.get("daylog.recent", "")
    if raw in (None, "", "false"):
        return []
    try:
        data = json.loads(raw)
        return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


def log_for_day(store, day: int) -> List[str]:
    """The event lines recorded for a specific day (empty if none)."""
    if store is None:
        return []
    raw = store.get(f"daylog.{int(day)}", "")
    if raw in (None, "", "false"):
        return []
    try:
        data = json.loads(raw)
        return [str(x) for x in data] if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []
