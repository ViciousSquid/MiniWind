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

from typing import Dict, Optional


def _name(props) -> str:
    return str(props.get("display_name") or props.get("name") or "someone")


def _place(session, pos) -> str:
    living = getattr(session, "living", None)
    board = getattr(living, "board", None)
    if board is None or pos is None:
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
    for t in getattr(session, "_things_of_type", lambda _k: ())("creaturespawn"):
        p = t.properties
        if str(p.get("id") or p.get("name") or "") == str(spawner_id):
            near = _place(session, getattr(t, "pos", None))
            return f"{p.get('name', 'a spawn point')}" + (f" near {near}" if near else "")
    return str(spawner_id)


def sentence(prov: Dict) -> str:
    """*prov* (from :func:`of`) said plainly, for a record or a reader."""
    who = prov.get("who", "Someone")
    kind = prov.get("kind")
    if kind == "journey":
        what = prov.get("journey_kind") or "party"
        route = ""
        if prov.get("origin") and prov.get("destination"):
            route = f" on the road from {prov['origin']} to {prov['destination']}"
        why = prov.get("why") or ""
        cause = (prov.get("cause") or {}).get("reason")
        tail = f": {cause}" if cause else (f" ({why})" if why and why != "Ordinary authored destination sampling." else "")
        return f"{who}, of a {what}{route}{tail}."
    if kind == "spawn":
        return f"{who}, from {prov.get('spawner', 'a spawn point')}."
    if kind == "resident":
        home = prov.get("home") or prov.get("place")
        return f"{who}, who lives at {home}." if home else f"{who}, a resident."
    place = prov.get("place")
    return f"{who}, who belongs at {place}." if place else f"{who}."
