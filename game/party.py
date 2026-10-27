"""
The player's raised followers travel with them from map to map.

A map is loaded from its file every time the player enters it, and the game
session is rebuilt with it, so an actor belongs to the map it was authored
in. A body the player raised (necromancy, game/runtime.py ``_do_resurrect``)
is theirs, though, and goes where they go:

* **Leaving** a map (:func:`depart`, as play stops for the level change),
  every living raised follower in it joins the party, written to the game's
  store with all it carries and knows. One raised in this map is taken out
  of it for good (its map's memory marks it *departed*, game/map_memory.py),
  so it is never also standing at home. It keeps its id (a uuid, unique
  across every map) wherever it goes: it is the same actor in every map.
* **Entering** a map (:func:`arrive`, on the first frame the player stands
  in it), the party is set down around the player, still the caster's.

A follower that dies on the road is not in the party when the player next
leaves: its body stays in that map until then, and it travels no more.
"""

from __future__ import annotations

import copy
import json
import math
import uuid

from . import fio

STORE_KEY = "party.members"
ACTOR_TYPES = ("npc", "creature", "monster")
#: How far from the player the party is set down, one after another round them.
ARRIVE_RADIUS = 140.0
#: Runtime fields a member keeps on the road (others, ``_...``, are scratch).
KEEP = ("_ward_rolled", "_second_weapon_rolled", "_caster_sidearm_rolled")


def _kind(t) -> str:
    return str(t.properties.get("type", "")).replace("_", "").lower()


def is_traveller(p) -> bool:
    """Whether the actor *p* goes with the player: a living raised follower."""
    return (p.get("resurrected_by") == "player" and bool(p.get("follow_player"))
            and not p.get("dead") and not p.get("hidden"))


def _portable(props) -> dict:
    """*props* fit to travel: no runtime scratch, nothing the store cannot hold."""
    out = {}
    for k, v in props.items():
        if str(k).startswith("_") and k not in KEEP:
            continue
        try:
            json.dumps(v)
        except (TypeError, ValueError):
            continue
        out[k] = copy.deepcopy(v)
    return out


def depart(session) -> int:
    """The player leaves this map: its living raised followers go with them.
    Returns how many."""
    memory = getattr(session, "memory", None)
    members = []
    for t in list(fio.things(session.logic) or ()):
        if _kind(t) not in ACTOR_TYPES or not is_traveller(t.properties):
            continue
        p = t.properties
        if not p.get("travelling") and memory is not None:
            memory.departed(t)               # gone from its home map for good
        if not p.get("id"):
            p["id"] = str(uuid.uuid4())
        # It is the same actor wherever it goes: its id (uuid) never changes.
        props = _portable(p)
        props["travelling"] = True
        members.append({"kind": _kind(t), "props": props})
    session.store.set(STORE_KEY, json.dumps(members, separators=(",", ":")))
    return len(members)


def members(session) -> list:
    try:
        out = json.loads(session.store.get(STORE_KEY, "[]") or "[]")
    except (TypeError, ValueError):
        return []
    return [m for m in out if isinstance(m, dict) and isinstance(m.get("props"), dict)]


def arrive(session) -> int:
    """Set the party down around the player in the map just entered. One
    already here (restored with a saved game) is not set down twice. Returns
    how many arrived."""
    ppos = session._player_pos()
    if ppos is None:
        return 0
    things = fio.things(session.logic)
    here = {str(t.properties.get("id")) for t in things if t.properties.get("id")}
    from .entities import NPC, Creature
    made = 0
    party = [m for m in members(session) if str(m["props"].get("id")) not in here]
    for i, m in enumerate(party):
        props = copy.deepcopy(m["props"])
        for k in ("home", "work_location", "patrol_route"):
            props.pop(k, None)               # the last map's places
        session._bind_raised(props)
        props.update(dead=False, hidden=False)
        ang = (i / max(1, len(party))) * math.tau + math.pi
        x = ppos[0] + math.sin(ang) * ARRIVE_RADIUS
        z = ppos[2] + math.cos(ang) * ARRIVE_RADIUS
        g = fio.ground_height(session.logic, x, z, below=ppos[1] + 60.0)
        y = float(g) if g is not None else ppos[1]
        cls = NPC if m.get("kind") == "npc" else Creature
        try:
            things.append(cls(pos=[x, y, z], properties=props))
            made += 1
        except Exception as exc:
            print(f"[MiniWind] a follower could not arrive: {exc}")
    if made:
        fio.rebuild_entity_caches(session.logic)
    return made
