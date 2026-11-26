"""Who did what to whom, and what came of it -- in plain words.

Both pacing layers explain their decisions with these sentences: the
storyteller in either game mode, and Dynamic mode's director
(``game/living/scenarios.py``). Each sentence is built only from a stored
memory (a knowledge fact, ``game/sim/knowledge.py``) and the people it names,
so an explanation can never claim more than the world holds.

A decision reads::

    The storyteller decided that Francis has a vendetta against the player
    because the player killed their brother Aldo near Ashby on day 3.

and its result is said separately, by whoever acted -- in Normal mode only
what the storyteller may do (weight a trip someone was already making); in
Dynamic mode what the director staged.

Pure Python; no Qt, no engine.
"""

from __future__ import annotations

from typing import Dict, Optional

PLAYER = "the player"

#: How each justified journey kind reads after "<holder> ...".
STANCE = {
    "vendetta": "has a vendetta against",
    "reckoning": "wants a reckoning with",
    "restitution": "wants repayment from",
    "gratitude": "is grateful to",
}


def item_name(item_id: str) -> str:
    """An item's name in lower case ("a loaf of bread"), or ""."""
    if not item_id:
        return ""
    try:
        from ..rpg import items as rpg_items
        info = rpg_items.get(item_id)
        name = getattr(info, "name", "") if info is not None else ""
    except Exception:
        name = ""
    return (name or str(item_id).replace("_", " ")).lower()


def whom(fact: Dict, holder_key: str, holder_props: Optional[Dict] = None) -> str:
    """The deed's victim from the holder's side: "them", "their brother
    Aldo", or just "Aldo" when there is no tie."""
    target = str(fact.get("target", "") or "")
    name = str(fact.get("target_name", "") or target or "someone")
    if target and target == holder_key:
        return "them"
    tie = ""
    if holder_props:
        try:
            from .appraisal import relationship_to
            tie = relationship_to(holder_props, target, name)
        except Exception:
            tie = ""
    return f"their {tie} {name}" if tie else name


def deed(fact: Dict, holder_key: str, holder_props: Optional[Dict] = None,
         doer: str = PLAYER, place: str = "") -> str:
    """What was done, as remembered: "the player stole flour from them at
    Low Farm on day 3"."""
    kind = str(fact.get("kind", "") or "")
    victim = whom(fact, holder_key, holder_props)
    item = item_name(str(fact.get("item", "") or ""))
    possessive = "their" if victim == "them" else f"{victim}'s"
    verb = {
        "death": f"killed {victim}",
        "attack": f"attacked {victim}",
        "theft": f"stole {item or 'something'} from {victim}",
        "lockpick": f"picked the lock on {possessive} things",
        "trespass": f"trespassed on {possessive} property",
        "heal": f"healed {victim}",
        "gift": f"gave {victim} {item or 'a gift'}",
        "give": f"gave {victim} {item or 'something'}",
    }.get(kind, f"did something ({kind or 'unknown'}) to {victim}")
    where = f" near {place}" if place else ""
    day = fact.get("day")
    when = f" on day {int(day)}" if isinstance(day, (int, float)) and day else ""
    return f"{doer} {verb}{where}{when}"


def how_known(fact: Dict) -> str:
    """How the holder came to know: ", which they saw" / "heard"."""
    source = str(fact.get("source", "") or "")
    if source == "witnessed":
        return ", which they saw for themselves"
    if source in ("heard", "told"):
        told = str(fact.get("from", "") or "")
        return f", which they were told{' by ' + told if told and told != 'news' else ''}"
    return ""


def justified(kind: str, holder: str, fact: Dict, holder_key: str,
              holder_props: Optional[Dict] = None, place: str = "") -> str:
    """"The storyteller decided that <holder> has a vendetta against the
    player because the player killed their brother Aldo near Ashby."""
    stance = STANCE.get(kind, f"has a reason ({kind}) to seek out")
    return (f"The storyteller decided that {holder} {stance} {PLAYER} because "
            f"{deed(fact, holder_key, holder_props, PLAYER, place)}{how_known(fact)}.")


def grievance(holder: str, fact: Dict, holder_key: str,
              holder_props: Optional[Dict] = None, place: str = "") -> str:
    """"The storyteller decided that Edda wants revenge on Black Rook
    because Black Rook killed their brother Aldo near Ashby."""
    culprit = str(fact.get("actor_name", "") or "outlaws")
    return (f"The storyteller decided that {holder} wants revenge on {culprit} because "
            f"{deed(fact, holder_key, holder_props, culprit, place)}{how_known(fact)}.")


def remembered(holder: str, fact: Dict, holder_key: str,
               holder_props: Optional[Dict] = None, place: str = "") -> str:
    """"Mabel remembers that Rook stole flour from them near Ashby on day
    2, and has not reported it." -- an unreported crime someone holds."""
    doer = str(fact.get("actor_name", "") or "someone")
    if doer.lower() in ("player", PLAYER):
        doer = PLAYER
    unreported = "" if fact.get("reported") else ", and has not reported it"
    return f"{holder} remembers that {deed(fact, holder_key, holder_props, doer, place)}{unreported}."
