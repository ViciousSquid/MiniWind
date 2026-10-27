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


# ---------------------------------------------------------------------------
# What fortune does for a character, said plainly
# ---------------------------------------------------------------------------
#: How much faster rumours of the player's crimes fade -- and how much slower
#: their kindnesses -- by how they look (game.rpg.charisma tiers).
RUMOUR_CHARM = {"repulsive": 0.5, "ugly": 0.75, "plain": 1.0, "fair": 1.3,
                "striking": 1.6}


def lucky_escape_chance(character) -> float:
    """The chance, once a day, that a blow which would kill survives on a
    sliver of health: 1% per point of fortune over 40, up to 60%."""
    return max(0.0, min(0.60, (score(character) - 40) * 0.01))


def benefits(character):
    """``[(name, value, why, good)]``: everything Charisma and Luck are doing
    for (or against) *character* right now, in numbers -- the Fortune page
    lists these, so a fortunate player can see why the Vale is kinder to them.
    *good* is True for an advantage, False for a handicap, None for neutral."""
    from . import charisma as cha
    from . import combat
    a = getattr(character, "attrs", {}) or {}
    charm = int(a.get(attr.PERSONALITY, 40))
    luck = int(a.get(attr.LUCK, 40))
    looks = cha.tier(charm)
    out = []

    def sign(v):
        return None if abs(v) < 1e-9 else v > 0

    buy = cha.price_multiplier(charm, True)
    out.append(("Merchant prices", f"x{buy:.2f}", f"Charisma {charm}: you look {looks}",
                sign(1.0 - buy)))
    greet = {"repulsive": "they recoil", "ugly": "they wince", "plain": "no remark",
             "fair": "a warm welcome", "striking": "they want to help"}[looks]
    out.append(("Strangers' first words", greet, f"Charisma {charm}",
                sign({"repulsive": -1, "ugly": -1, "plain": 0}.get(looks, 1))))
    repel = cha.repel_chance(charm)
    if repel > 0:
        out.append(("Brigands who won't fight you", f"{repel * 100:.0f}%",
                    f"Charisma {charm}: some want no part of a face like that", True))
    fade = RUMOUR_CHARM.get(looks, 1.0)
    out.append(("Rumours of your crimes fade", f"x{fade:.2f}",
                f"Charisma {charm}: people doubt ill of the charming", sign(fade - 1.0)))
    crit = combat.critical_chance(character)
    out.append(("Critical hits", f"{crit * 100:.0f}%", f"Luck {luck}", sign(luck - 40)))
    out.append(("Loot drop chance", f"{(luck - 40) * 0.2:+.0f}%", f"Luck {luck}",
                sign(luck - 40)))
    out.append(("Special finds", f"{(luck - 40) * 0.1:+.0f}%", f"Luck {luck}",
                sign(luck - 40)))
    out.append(("Learning skills", f"{(luck - 40) * 0.2:+.0f}% skill experience",
                f"Luck {luck}", sign(luck - 40)))
    fortune = score(character)
    out.append(("Charm & Luck conversations",
                "open" if fortune >= UNLOCK else f"closed (need {UNLOCK})",
                f"Fortune {fortune} = (Charisma {charm} + Luck {luck}) / 2",
                fortune >= UNLOCK))
    escape = lucky_escape_chance(character)
    out.append(("Lucky escape from a killing blow",
                f"{escape * 100:.0f}% once a day" if escape else "none",
                f"Fortune {fortune}", True if escape else None))
    return out
