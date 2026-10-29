"""
Rumours — the world's knowledge, said aloud to the player.

The knowledge store already records who believes what, how surely and from
whom. This module only *broadcasts* it: it turns a resident's facts, the news
heard in their town and the journeys that set out from it into the sentences
a tavern regular, a passer-by or a notice board would offer.

It is narration, not authoring. Nothing here creates an event, writes a
belief, changes an intention or draws a random number. A resident can only
tell what they actually believe; an unidentified culprit stays "someone"; the
certainty they hold it with is how they hedge it.

Pure Python. Place names come from a ``place_of(x, z) -> str`` callable so
tests and the editor can supply their own geography.
"""

from __future__ import annotations

import zlib
from typing import Callable, Dict, Iterable, List, Optional

from . import knowledge
from .events import kind_spec

#: The player's identity key (mirrors :data:`game.sim.director.PLAYER_KEY`,
#: which this module does not import so it stays dependency-free).
PLAYER_KEY = "player"

#: How much a resident must believe something before volunteering it.
VOLUNTEER_CERTAINTY = 0.3

#: How a rumour is opened, by how surely and from where the speaker knows it.
_OPENERS = {
    "witnessed": ("I saw it myself: {what}", "I was there when {what}"),
    "heard": ("I heard it happen: {what}", "There was a commotion: {what}"),
    "told": ("Word is {what}", "I heard {what}", "They're saying {what}"),
    "doubt": ("They say, though I can't swear to it, that {what}",
              "Only a rumour, mind, but {what}"),
}


def _pick(options, *salt):
    return options[zlib.crc32("|".join(str(s) for s in salt).encode()) % len(options)]


def when(day, today) -> str:
    """How long ago, as a resident would put it."""
    if today is None:
        return ""
    ago = int(today) - int(day or 0)
    if ago <= 0:
        return "today"
    if ago == 1:
        return "yesterday"
    if ago <= 3:
        return "a few days back"
    return "a while back"


def _who(fact, role: str, listener: str) -> str:
    key, name = fact.get(role, ""), fact.get(role + "_name", "")
    if role == "actor" and not fact.get("identified", True):
        return "someone"
    if key and key == listener:
        return "you"
    return str(name or key or "someone")


def phrase(fact: Dict, listener: str = PLAYER_KEY) -> str:
    """What the fact says happened, told to *listener*: names they would hear."""
    told = dict(fact)
    told["actor_name"] = _who(fact, "actor", listener)
    told["target_name"] = _who(fact, "target", listener)
    return knowledge.phrase(told)


def line(fact: Dict, place_of: Optional[Callable] = None, today=None,
         listener: str = PLAYER_KEY, speaker: str = "",
         place_name: Optional[Callable] = None) -> str:
    """One volunteered rumour: "Word is someone robbed Bram near the ford, yesterday."

    The opener follows the speaker's source and certainty; the place is the
    nearest named place to where the fact says it happened; a faction raid's
    remembered order explains why the party was there."""
    what = phrase(fact, listener)
    pos = fact.get("pos") or ()
    where = place_of(pos[0], pos[2]) if place_of is not None and len(pos) >= 3 else ""
    if where:
        what += f" near {where}"
    ago = when(fact.get("day", 0), today)
    if ago:
        what += f", {ago}"
    certainty = float(fact.get("certainty", 0.0))
    source = str(fact.get("source", knowledge.SOURCE_TOLD))
    if source == knowledge.SOURCE_TOLD and certainty < 0.5:
        source = "doubt"
    text = _pick(_OPENERS.get(source, _OPENERS["told"]), speaker, fact.get("e", 0)).format(what=what)
    cause = fact.get("cause")
    if isinstance(cause, dict) and cause.get("faction"):
        home = cause.get("home", "")
        home = place_name(home) if place_name is not None else home
        reason = cause.get("fact")
        why = f" over how {phrase(reason, listener)}" if isinstance(reason, dict) else ""
        text += f". Those were {cause['faction']} out of {home}{why}"
    return text[:1].upper() + text[1:] + "."


def worth_telling(fact: Dict) -> bool:
    """Whether a resident would volunteer this to a stranger: notable, and
    believed surely enough to say aloud."""
    return (isinstance(fact, dict)
            and "notable" in kind_spec(fact.get("kind", ""))["tags"]
            and float(fact.get("certainty", 0.0)) >= VOLUNTEER_CERTAINTY)


def interest(fact: Dict) -> float:
    """How much a fact is worth bringing up: certainty x how much it matters."""
    return float(fact.get("certainty", 0.0)) * float(kind_spec(fact.get("kind", ""))["severity"])


def pick(facts: Iterable[Dict], limit: int = 2, skip: Iterable[int] = ()) -> List[Dict]:
    """The most interesting things worth telling, newest breaking ties.

    Deterministic: the same beliefs always surface in the same order."""
    skip = set(int(e) for e in skip)
    pool = [f for f in facts or () if worth_telling(f) and int(f.get("e", 0) or 0) not in skip]
    pool.sort(key=lambda f: (-interest(f), -int(f.get("day", 0)), -float(f.get("hour", 0.0)),
                             -int(f.get("e", 0) or 0)))
    return pool[:max(0, int(limit))]


#: What a justified traveller's neighbours say about why they left
#: (kinds from :func:`game.sim.storyteller.justification`).
_PURPOSES = {
    "vendetta": "swore to find whoever killed {victim}",
    "reckoning": "has a score to settle",
    "restitution": "means to get back what was stolen",
    "gratitude": "wanted to thank someone",
}


def departure(name: str, dest: str, kind: str = "", victim: str = "",
              faction: str = "", target: str = "", reason_fact: Optional[Dict] = None,
              listener: str = PLAYER_KEY) -> str:
    """A neighbour's account of an actual journey that set out from here."""
    if faction:
        text = f"{faction.title()} set out from here for {dest}"
        if target:
            text += f", after {'you' if target == listener else target}"
        if isinstance(reason_fact, dict):
            text += f", over how {phrase(reason_fact, listener)}"
        return text + "."
    purpose = _PURPOSES.get(kind, "")
    text = f"{name} left for {dest}"
    if purpose:
        text += " — " + purpose.format(victim=victim or "kin")
    return text + "."


def notice(fact: Dict, place_of: Optional[Callable] = None, today=None,
           listener: str = PLAYER_KEY) -> str:
    """A reported crime as the watch posts it: an appeal, not gossip."""
    what = phrase(fact, listener)
    pos = fact.get("pos") or ()
    where = place_of(pos[0], pos[2]) if place_of is not None and len(pos) >= 3 else ""
    ago = when(fact.get("day", 0), today)
    return ("BY ORDER OF THE WATCH: " + what[:1].upper() + what[1:]
            + (f" near {where}" if where else "") + (f", {ago}" if ago else "")
            + ". Anyone with knowledge, come forward.")
