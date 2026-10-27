"""
Charm & Luck: the conversations only the fair of face and the fortunate get.

A character's **fortune** is the mean of their CHARISMA and LUCK. At
:data:`UNLOCK` or more, conversations offer extra, marked responses -- talking
a merchant down, talking a watchman out of a writ, asking what the town says
about you, or simply catching someone in a generous mood. Each is a d20 check
the player watches (the odds are the fortune's, less the ask's difficulty),
each NPC entertains each one once a day, and the outcome is spoken in their
words. Pure: the session applies the effects.
"""

from __future__ import annotations

from typing import Dict, List

from . import attributes as attr

#: Fortune (mean of Charisma and Luck) at which the marked responses appear.
UNLOCK = 45
#: Prefix on every such response, so the player knows what is being tested.
TAG = "[Charm & Luck]"

#: id -> (response text, difficulty 0..1, success line, failure line).
OPTIONS: Dict[str, tuple] = {
    "haggle": (
        "Surely a friend of the house pays a friend's price?",
        0.10,
        "Ha! You've a silver tongue and the devil's own luck. For you -- the "
        "good price.",
        "Nice try. The price is the price, friend."),
    "pardon": (
        "Come now, officer. Must we spoil such a fine day with paperwork?",
        0.30,
        "...You know, I've a terrible memory for faces. Half of that writ "
        "just slipped my mind. Don't make me regret it.",
        "Flattery won't wash it, I'm afraid. The writ stands."),
    "rumours": (
        "You look like someone who hears things. What are they saying about me?",
        0.0,
        "",                            # the session fills in what they heard
        "Couldn't say. I keep my ears to myself."),
    "favour": (
        "Fortune smiles on us both today, wouldn't you say?",
        0.20,
        "Do you know, I think it does. Here -- take this, for luck.",
        "Does it? Not on me, it doesn't."),
}


def score(character) -> int:
    """The character's fortune: the mean of Charisma and Luck."""
    a = getattr(character, "attrs", {}) or {}
    return int(round((int(a.get(attr.PERSONALITY, 40)) + int(a.get(attr.LUCK, 40))) / 2))


def available(character, *, merchant=False, guard=False, bounty=0,
              knows_of_player=False) -> List[str]:
    """Which marked responses this conversation offers (none below
    :data:`UNLOCK`)."""
    if score(character) < UNLOCK:
        return []
    out = []
    if merchant:
        out.append("haggle")
    if guard and int(bounty) > 0:
        out.append("pardon")
    if knows_of_player:
        out.append("rumours")
    if not merchant and not guard:
        out.append("favour")
    return out


def chance(character, option: str) -> float:
    """The odds of *option* coming off: 45% at the threshold, 1.2% more per
    point of fortune above it, less the ask's difficulty."""
    difficulty = OPTIONS[option][1]
    return max(0.05, min(0.95, 0.45 + (score(character) - UNLOCK) * 0.012 - difficulty))


def why(character) -> str:
    a = getattr(character, "attrs", {}) or {}
    return (f"Charisma {int(a.get(attr.PERSONALITY, 40))} + Luck "
            f"{int(a.get(attr.LUCK, 40))} — fortune {score(character)}")
