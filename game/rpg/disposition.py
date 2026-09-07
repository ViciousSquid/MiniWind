"""
Per-NPC memory of the player — the missing social axis (§2 growth room).

:func:`game.rpg.guilds.disposition` answers "how does this NPC feel about the
player *right now*" from static inputs: a base, the player's Personality, the
NPC's faction, the player's bounty and an authored/persuade offset carried on the
NPC. What it deliberately does **not** model is a *durable, per-individual memory*
of what the player has actually done to or for this specific person.

This module adds exactly that. Every notable interaction — a first greeting, a
quest finished on their behalf, honest trade, a gift, or, on the other side, an
assault, a theft, or the murder of their kin — is folded into a signed
disposition *delta* stored in the persistent KV store, keyed by the NPC's stable
identity, exactly like the settlement's ``dead.<name>`` flags. The town no longer
only reacts to your bounty in the abstract: each person remembers *you*, and that
memory survives save/load and can be read back by dialogue, pricing and the
mental-state inspector.

Pure Python + a string KV store — safe everywhere and headlessly testable.
"""

from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from . import guilds

#: Clamp on the accumulated memory delta, so no single relationship can swing
#: disposition further than roughly "sworn enemy" ↔ "devoted friend".
DELTA_MIN = -100
DELTA_MAX = 100

#: Event catalogue: ``event -> (delta, once)``. ``once`` events are applied at
#: most a single time per NPC (a first greeting shouldn't compound every time
#: the player says hello). ``gift`` carries no fixed delta — the caller passes an
#: ``amount`` derived from the gift's value.
EVENTS: Dict[str, Tuple[int, bool]] = {
    "greeted": (2, True),          # first time the player speaks with them
    "traded": (1, False),          # honest business, small and repeatable
    "quest_accepted": (3, False),  # took on their errand
    "quest_helped": (15, False),   # finished a quest for them
    "gift": (0, False),            # amount supplied by the caller (value-scaled)
    "healed": (8, False),          # mended them with restorative magic
    "assaulted": (-30, False),     # struck them
    "robbed": (-20, False),        # stole from them / their home
    "kin_slain": (-35, False),     # the player killed one of their relatives
}

#: Events that stamp the durable "this person was wronged by the player" flag —
#: read by dialogue (``talk.wronged``) and the inspector.
_WRONGED_EVENTS = {"assaulted", "robbed", "kin_slain"}
#: Events that stamp the durable "this person owes the player kindness" flag.
_BEFRIENDED_EVENTS = {"quest_helped", "gift", "healed"}

#: Human phrases for the per-NPC memory log (inspector / dialogue flavour).
_EVENT_PHRASE = {
    "greeted": "you introduced yourself",
    "traded": "you did honest business",
    "quest_accepted": "you took on their errand",
    "quest_helped": "you did them a great service",
    "gift": "you gave them a gift",
    "healed": "you healed them",
    "assaulted": "you attacked them",
    "robbed": "you stole from them",
    "kin_slain": "you killed their kin",
}

#: Cap on the stored memory log length (most-recent kept).
_LOG_CAP = 12


def _slug(text) -> str:
    """Lowercase, alnum-only identity slug (mirrors runtime._slug)."""
    return "".join(ch.lower() if ch.isalnum() else "_"
                   for ch in str(text)).strip("_")


#: Where the computed key is cached on the actor's own properties. The key is
#: derived from identity fields that do not change during a session (the UUID,
#: failing that the name), so it is computed once per actor and read thereafter.
_MEM_KEY_CACHE = "_mem_key"


def mem_key(npc_props: Dict) -> str:
    """A stable per-NPC memory key.

    Prefers the entity's UUID (``properties['id']``) so two townsfolk who share
    a display name still remember the player separately; falls back to a slug of
    the name / display name / role for hand-built fixtures with no id.

    PERF: this is the identity every reactive-simulation pass files things
    under, so it is asked for every actor several times per settlement tick —
    and it used to rebuild the slug character by character each time. The answer
    is cached on the properties dict it was derived from; call
    :func:`forget_mem_key` if an actor is ever renamed at runtime.
    """
    if not isinstance(npc_props, dict):
        return ""
    cached = npc_props.get(_MEM_KEY_CACHE)
    if cached is not None:
        return cached
    key = ""
    for field in ("id", "name", "display_name", "npc_role"):
        v = npc_props.get(field)
        if v:
            key = _slug(v)
            break
    npc_props[_MEM_KEY_CACHE] = key
    return key


def forget_mem_key(npc_props: Dict) -> None:
    """Drop a cached identity key after renaming or re-identifying an actor."""
    if isinstance(npc_props, dict):
        npc_props.pop(_MEM_KEY_CACHE, None)


def _base(key: str) -> str:
    return f"npc.{key}"


def _get_int(store, key: str, default: int = 0) -> int:
    try:
        v = store.get(key, str(default))
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _truthy(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Recording memory
# ---------------------------------------------------------------------------
def remember(store, npc_props: Dict, event: str, amount: Optional[int] = None,
             note: str = "") -> int:
    """Fold *event* into this NPC's persistent memory and return the new delta.

    ``amount`` overrides the catalogue delta (used by ``gift``, whose weight is
    the gift's value). ``once`` events are ignored after the first time. Also
    stamps the durable ``wronged`` / ``befriended`` flags and appends a short
    line to the memory log. A no-op (returns the current delta unchanged) when
    the store or the NPC key is missing, or a ``once`` event already fired."""
    key = mem_key(npc_props)
    if store is None or not key:
        return 0
    spec = EVENTS.get(event)
    if spec is None:
        return delta(store, npc_props)
    weight, once = spec
    once_key = f"{_base(key)}.did.{event}"
    if once and _truthy(store.get(once_key, "false")):
        return delta(store, npc_props)
    change = int(amount) if amount is not None else int(weight)
    cur = _get_int(store, f"{_base(key)}.disp", 0)
    new = max(DELTA_MIN, min(DELTA_MAX, cur + change))
    store.set(f"{_base(key)}.disp", new)
    if once:
        store.set(once_key, "1")
    if event in _WRONGED_EVENTS:
        store.set(f"{_base(key)}.wronged", "1")
    if event in _BEFRIENDED_EVENTS:
        store.set(f"{_base(key)}.befriended", "1")
    _append_log(store, key, note or _EVENT_PHRASE.get(event, event))
    return new


def _append_log(store, key: str, line: str) -> None:
    log = _read_log(store, key)
    log.append(str(line))
    if len(log) > _LOG_CAP:
        log = log[-_LOG_CAP:]
    try:
        store.set(f"{_base(key)}.log", json.dumps(log))
    except (TypeError, ValueError):
        pass


def _read_log(store, key: str) -> List[str]:
    raw = store.get(f"{_base(key)}.log", "")
    if raw in (None, "", "false"):
        return []
    try:
        data = json.loads(raw)
        return [str(x) for x in data] if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


# ---------------------------------------------------------------------------
# Reading memory
# ---------------------------------------------------------------------------
def delta(store, npc_props: Dict) -> int:
    """The accumulated, persistent memory delta for this NPC (may be negative)."""
    key = mem_key(npc_props)
    if store is None or not key:
        return 0
    return _get_int(store, f"{_base(key)}.disp", 0)


def of(character, npc_props: Dict, store) -> int:
    """Effective 0-100 disposition of *npc_props* toward the player.

    :func:`guilds.disposition` (base + personality + faction + bounty + authored
    offset) plus this NPC's remembered memory delta, clamped to 0-100. This is
    the number gameplay should use whenever a store is on hand; ``guilds`` stays
    the store-less fallback."""
    base = guilds.disposition(character, npc_props)
    return max(0, min(100, base + delta(store, npc_props)))


def tier(value: int) -> str:
    """Coarse disposition band, for greetings, prices and the inspector."""
    if value < 10:
        return "hostile"
    if value < 30:
        return "unfriendly"
    if value < 55:
        return "neutral"
    if value < 80:
        return "friendly"
    return "devoted"


def has_flag(store, npc_props: Dict, flag: str) -> bool:
    """Whether a durable memory flag (``wronged`` / ``befriended`` / ``met``)
    is set for this NPC."""
    key = mem_key(npc_props)
    if store is None or not key:
        return False
    return _truthy(store.get(f"{_base(key)}.{flag}", "false"))


def memory_log(store, npc_props: Dict) -> List[str]:
    """The recent per-NPC memory lines (oldest first), for the inspector."""
    key = mem_key(npc_props)
    if store is None or not key:
        return []
    return _read_log(store, key)


def summary(character, npc_props: Dict, store) -> Dict:
    """A display-ready standing snapshot: ``{disposition, tier, wronged,
    befriended, log}`` — everything the inspector needs in one call."""
    disp = of(character, npc_props, store)
    return {
        "disposition": disp,
        "tier": tier(disp),
        "wronged": has_flag(store, npc_props, "wronged"),
        "befriended": has_flag(store, npc_props, "befriended"),
        "log": memory_log(store, npc_props),
    }


# ---------------------------------------------------------------------------
# Conversation-scoped convenience keys
# ---------------------------------------------------------------------------
def write_talk_keys(store, character, npc_props: Dict) -> None:
    """Publish the current conversation partner's standing under generic
    ``talk.*`` keys so authored dialogue can react to memory without knowing the
    NPC's private id.

    Mirrors how the settlement already keys grief off global ``dead.<name>`` /
    ``town.mourning`` flags: after this call a dialogue response can gate on
    ``{"key": "talk.wronged", "is_true": true}`` or ``{"key": "talk.tier",
    "equals": "devoted"}`` for *whoever the player is speaking with*."""
    if store is None:
        return
    disp = of(character, npc_props, store)
    store.set("talk.disp", disp)
    store.set("talk.tier", tier(disp))
    store.set("talk.met", "1" if has_flag(store, npc_props, "met") else "0")
    store.set("talk.wronged", "1" if has_flag(store, npc_props, "wronged") else "0")
    store.set("talk.befriended",
              "1" if has_flag(store, npc_props, "befriended") else "0")
    # Stamp "met" *after* publishing it, so the first conversation still reads as
    # a first meeting for this run's greeting logic.
    key = mem_key(npc_props)
    if key:
        store.set(f"{_base(key)}.met", "1")


def price_factor(character, npc_props: Dict, store) -> float:
    """A merchant-price multiplier from how much this trader likes the player.

    Centered on 1.0 at neutral (50), ranging about ±12% across the disposition
    band: a devoted merchant shaves coin off, a wary one marks it up. Callers
    multiply a buy price by this and divide a sell price by it, so being liked
    cuts what you pay and lifts what you're paid."""
    disp = of(character, npc_props, store)
    return max(0.85, min(1.15, 1.0 - (disp - 50) * 0.0035))
