"""
Provenance: where an actor in the world came from, and why it is here.

Nothing in the Vale appears from nowhere, and the game can say so. Every
actor is one of:

* **a journey's** -- a party on the road board (``_journey``): a pack, a
  raid, a trader, a resident on a trip, a vendetta. The board knows its kind,
  where it set out from and where it is going; a faction order carries its
  cause; and the storyteller keeps a receipt of why it was routed here
  (:mod:`game.sim.storyteller`, ``_receipts``).
* **a spawn point's** (``_spawner``, ``_spawn_slot``): a lair or den the map
  fills, named by the spawner.
* **a resident's** -- someone who lives here (a home, a schedule).
* **authored** -- placed in the map by hand.

:func:`of` reads it, :func:`sentence` says it. Both only read: nothing here
creates, changes or rolls anything. Encounters (:mod:`game.encounters`)
record the provenance of everyone in a fight, so a remembered fight says
*why* the wolf pack was on that road.
"""

from __future__ import annotations

import math
from typing import Dict, Optional


def _name(props) -> str:
    return str(props.get("display_name") or props.get("name") or "someone")


#: A location marker names the ground within this many of its discovery
#: radii (and at least :data:`PLACE_MIN_REACH`); further out is the wilds.
PLACE_REACH = 2.0
PLACE_MIN_REACH = 1500.0


def _place(session, pos) -> str:
    """The named place *pos* is at: in a cave, the cave (its map's region
    name); else the nearest of the map's location markers whose ground it
    is on -- every camp, shrine and cave mouth, not only the road board's
    towns; else nowhere (""). A map without location markers asks the road
    board instead."""
    if getattr(session, "underground", False):
        return str(getattr(session, "region_name", "") or "")
    if pos is None:
        return ""
    things_of_type = getattr(session, "_things_of_type", None)
    markers = [m for m in (things_of_type("marker") if things_of_type is not None else ())
               if str(m.properties.get("marker_kind", "")).lower() == "location"
               and m.properties.get("place_name")]
    if markers:
        best, best_d = "", None
        for m in markers:
            d = math.hypot(float(pos[0]) - m.pos[0], float(pos[2]) - m.pos[2])
            reach = max(PLACE_MIN_REACH,
                        PLACE_REACH * float(m.properties.get("discover_radius", 0) or 0))
            if d <= reach and (best_d is None or d < best_d):
                best, best_d = str(m.properties["place_name"]), d
        return best
    living = getattr(session, "living", None)
    board = getattr(living, "board", None)
    if board is None:
        return ""
    try:
        key = board.nearest_place(float(pos[0]), float(pos[2]))
    except Exception:
        return ""
    places = getattr(living, "places", {}) or {}
    return str((places.get(key) or {}).get("name") or key or "")


def _place_name(session, key) -> str:
    places = getattr(getattr(session, "living", None), "places", {}) or {}
    return str((places.get(key) or {}).get("name") or key or "")


def _receipt(session, journey_id) -> Optional[Dict]:
    story = getattr(session, "storyteller", None)
    receipts = getattr(story, "_receipts", ()) or ()
    for receipt in reversed(receipts):
        if receipt.get("journey") == journey_id:
            return receipt
    return None


def of(session, thing) -> Dict:
    """Where *thing* came from: ``{"who", "role", "faction", "kind", ...}``.

    ``kind`` is ``journey``, ``spawn``, ``resident`` or ``authored``; the
    other keys depend on it (``journey_kind``, ``origin``, ``destination``,
    ``why``, ``cause`` for a journey; ``spawner`` for a spawn point; ``home``
    for a resident). ``place`` is the nearest named place to where it stands.
    """
    props = getattr(thing, "properties", {}) or {}
    out = {"who": _name(props), "role": str(props.get("npc_role") or ""),
           "faction": str(props.get("faction") or ""),
           "place": _place(session, getattr(thing, "pos", None))}
    jid = props.get("_journey")
    if jid:
        out["kind"] = "journey"
        out["journey"] = jid
        board = getattr(getattr(session, "living", None), "board", None)
        journey = (getattr(board, "journeys", {}) or {}).get(jid) if board is not None else None
        if journey is not None:
            out["journey_kind"] = str(journey.kind)
            out["origin"] = _place_name(session, journey.origin)
            out["destination"] = _place_name(session, journey.dest)
            if getattr(journey, "cause", None):
                cause = journey.cause
                out["cause"] = {k: cause.get(k) for k in ("faction", "home", "reason") if k in cause}
        receipt = _receipt(session, jid)
        if receipt is not None:
            out["why"] = str(receipt.get("reason") or "")
            out["storyteller"] = str(receipt.get("state") or "")
        return out
    spawner = props.get("_spawner")
    if spawner:
        out["kind"] = "spawn"
        out["spawner"] = _spawner_name(session, spawner)
        out["slot"] = props.get("_spawn_slot")
        return out
    if str(props.get("type", "")) == "npc" and (props.get("schedule") or props.get("home")):
        out["kind"] = "resident"
        home = props.get("home")
        if isinstance(home, (list, tuple)) and len(home) >= 3:
            out["home"] = _place(session, home)
        return out
    out["kind"] = "authored"
    return out


def _spawner_name(session, spawner_id) -> str:
    """The spawn point as a reader would put it: its own ``display_name`` if
    the map gives one, else the lair of what it spawns ("the wolf lair"),
    with the nearest place. Never the editor's name ("Spawn_wolf_571")."""
    for t in getattr(session, "_things_of_type", lambda _k: ())("creaturespawn"):
        p = t.properties
        if str(p.get("id") or p.get("name") or "") == str(spawner_id):
            near = _place(session, getattr(t, "pos", None))
            what = str(p.get("display_name") or "") or _lair(p.get("creature_role"))
            return what + (f" near {near}" if near else "")
    return "a lair"


def _lair(role) -> str:
    try:
        from .rpg import bestiary
        tmpl = bestiary.get(str(role or ""))
    except Exception:
        tmpl = None
    return f"the {tmpl.name.lower()} lair" if tmpl is not None else "a lair"


#: Each journey kind (game/living/journeys.KINDS) as the party it makes.
PARTIES = {"trader": "a trading party", "caravan": "a caravan",
           "pilgrims": "a band of pilgrims", "adventurers": "a band of adventurers",
           "patrol": "a patrol", "courier": "a courier's run",
           "minstrel": "a minstrel's tour", "bandits": "a bandit gang",
           "wolves": "a wolf pack", "greenskins": "a greenskin warband",
           "hunters": "a band of bounty hunters", "market": "a market trip",
           "faction_raid": "a raid"}


def _party(kind: str) -> str:
    kind = str(kind or "")
    return PARTIES.get(kind) or (f"a {kind.replace('_', ' ')} party" if kind else "a party")


def sentence(prov: Dict) -> str:
    """*prov* (from :func:`of`) said plainly, for a record or a reader."""
    who = prov.get("who", "Someone")
    kind = prov.get("kind")
    if kind == "journey":
        what = _party(prov.get("journey_kind"))
        route = ""
        if prov.get("origin") and prov.get("destination"):
            route = f" on the road from {prov['origin']} to {prov['destination']}"
        why = prov.get("why") or ""
        cause = (prov.get("cause") or {}).get("reason")
        tail = f": {cause}" if cause else (f" ({why})" if why and why != "Ordinary authored destination sampling." else "")
        return f"{who}, of {what}{route}{tail}."
    if kind == "spawn":
        return f"{who}, from {prov.get('spawner') or 'a lair'}."
    if kind == "resident":
        home = prov.get("home") or prov.get("place")
        return f"{who}, who lives at {home}." if home else f"{who}, a resident."
    place = prov.get("place")
    return f"{who}, who belongs at {place}." if place else f"{who}."
