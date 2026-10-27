"""
Rolling a character's body and face, and what the face does to the world.

At character creation the player rolls **3d6** three times — for STRENGTH,
ENDURANCE and CHARISMA — and may roll again as often as they like. Each total
(3..18) moves that attribute up or down from the class/race baseline by
:func:`delta_for`, so an 18 is a gift and a 3 a curse.

CHARISMA is the game's Personality attribute under the name players know it
by. It already feeds disposition and persuasion; this module adds what a face
does on its own:

* **Greetings** — strangers react to how you look before anything else
  (:func:`greeting_line`).
* **Prices** — merchants charge the ill-favoured more and the handsome less
  (:func:`price_multiplier`).
* **Refusal** — a merchant may not deal with someone truly repulsive unless
  they already like them (:func:`merchant_refuses`).
* **Repulsion** — some brigands and cultists want no part of a fight with
  something that looks like *that* (:func:`repel_chance`).

Pure Python, deterministic given the rng it is handed.
"""

from __future__ import annotations

import random
from typing import Dict, List

from . import attributes as attr

#: The three rolled stats, in order, with the names shown to the player.
ROLLED = (
    (attr.STRENGTH, "STRENGTH"),
    (attr.ENDURANCE, "ENDURANCE"),
    (attr.PERSONALITY, "CHARISMA"),
)
#: Attribute points per pip away from the 3d6 average of 10.5.
POINTS_PER_PIP = 4.0

REPULSIVE = "repulsive"
UGLY = "ugly"
PLAIN = "plain"
FAIR = "fair"
STRIKING = "striking"


def roll_3d6(rng=None) -> List[int]:
    """Three six-sided dice."""
    rng = rng or random
    return [rng.randint(1, 6) for _ in range(3)]


def delta_for(total: int) -> int:
    """How far a 3d6 *total* moves its attribute from the baseline: -30 at 3,
    +30 at 18, nothing for an average roll."""
    return int(round((int(total) - 10.5) * POINTS_PER_PIP))


def apply_rolls(character, rolls: Dict[str, List[int]]) -> Dict[str, int]:
    """Apply rolled dice to *character*'s attributes; returns the deltas."""
    out = {}
    for attr_id, _label in ROLLED:
        dice = rolls.get(attr_id)
        if not dice:
            continue
        delta = delta_for(sum(int(d) for d in dice))
        character.attrs[attr_id] = attr.clamp(int(character.attrs.get(attr_id, 40)) + delta)
        out[attr_id] = delta
        if isinstance(getattr(character, "rolls", None), dict):
            character.rolls[attr_id] = sum(int(d) for d in dice)
    character.recompute_derived(reset_current=True)
    return out


def charisma_of(character) -> int:
    return int(getattr(character, "attrs", {}).get(attr.PERSONALITY, 40))


def tier(charisma: int) -> str:
    c = int(charisma)
    if c < 15:
        return REPULSIVE
    if c < 30:
        return UGLY
    if c < 55:
        return PLAIN
    if c < 72:
        return FAIR
    return STRIKING


#: First words from a stranger, by how the player looks. Plain folk get no
#: comment at all -- the world only remarks on the remarkable.
_GREETINGS = {
    REPULSIVE: (
        "Gods above -- keep back! What happened to your face?",
        "Don't... don't come any closer. Say what you want from there.",
        "Ugh. I'll talk, but I'm not looking at you while I do it.",
        "Is that a face or a punishment? State your business and be quick.",
    ),
    UGLY: (
        "Hm. You've a face only a mother could tolerate.",
        "Not the prettiest traveller I've seen. Well -- what is it?",
        "You look like you lost a fight with a mule. What do you want?",
    ),
    FAIR: (
        "Well met! You've an honest sort of face.",
        "Ah, a friendly face. What can I do for you?",
    ),
    STRIKING: (
        "Well! It isn't every day someone like you walks up to me.",
        "My, my. And what can I do for you, friend?",
        "You've a look about you that makes a body want to help.",
    ),
}


def greeting_line(charisma: int, key: str = "") -> str:
    """A stranger's reaction to the player's looks, or "" for a plain face.
    *key* picks the line stably per NPC, so the same person says the same."""
    lines = _GREETINGS.get(tier(charisma))
    if not lines:
        return ""
    return lines[sum(map(ord, str(key))) % len(lines)]


def price_multiplier(charisma: int, buying: bool) -> float:
    """What a merchant's prices do on account of the player's face. Buying,
    the ugly pay more; selling, they are offered less."""
    t = tier(charisma)
    buy = {REPULSIVE: 1.5, UGLY: 1.22, PLAIN: 1.0, FAIR: 0.96, STRIKING: 0.9}[t]
    return buy if buying else 1.0 / buy


def merchant_refuses(charisma: int, disposition: int) -> bool:
    """A truly repulsive customer is turned away unless the merchant already
    likes them (or has been talked round)."""
    return tier(charisma) == REPULSIVE and int(disposition) < 60


def repel_chance(charisma: int) -> float:
    """Chance a hostile humanoid decides a fight with this face isn't worth it:
    nothing above Charisma 20, up to 70% at Charisma 0."""
    c = int(charisma)
    if c >= 20:
        return 0.0
    return max(0.0, min(0.7, (20 - c) / 20.0 * 0.7))


# ---------------------------------------------------------------------------
# Every living thing has the same three
# ---------------------------------------------------------------------------
#: The property names the three core attributes live under on an actor.
CORE_KEYS = {attr.STRENGTH: "strength", attr.ENDURANCE: "endurance",
             attr.PERSONALITY: "charisma"}

#: (STRENGTH, ENDURANCE, CHARISMA) a kind of creature is rolled around, by
#: role. Anything unlisted is an ordinary 40 / 40 / 40.
CORE_BASELINE = {
    "guard": (55, 55, 45), "guard_archer": (50, 50, 45),
    "bandit": (50, 45, 30), "bandit_archer": (45, 45, 30), "bandit_chief": (65, 60, 40),
    "cultist": (40, 40, 35), "merchant": (35, 40, 60), "blacksmith": (65, 55, 40),
    "farmer": (50, 50, 45), "villager": (40, 40, 45), "beggar": (30, 30, 25),
    "skeleton": (45, 50, 5), "skeleton_archer": (40, 45, 5), "wraith": (40, 60, 5),
    "monster": (55, 55, 10), "dragon": (100, 100, 40),
    "wolf": (45, 40, 10), "bear": (75, 70, 10), "boar": (55, 55, 10),
    "mudcrab": (30, 60, 5), "sheep": (25, 30, 25), "cow": (55, 50, 20),
    "hen": (10, 20, 20),
}

#: How far a creature's 3d6 moves each attribute: half what a player's does,
#: so a wolf is still a wolf.
CREATURE_PIP = POINTS_PER_PIP * 0.5


def _kind(props) -> str:
    return str(props.get("npc_role") or props.get("creature_role") or "").lower()


def core(props, attr_id) -> int:
    """STRENGTH, ENDURANCE or CHARISMA of any living thing, player aside.

    An authored value wins. Otherwise the creature rolls 3d6 for each, once,
    around the baseline for its kind (:data:`CORE_BASELINE`) -- the same roll
    the player makes at character creation, at half the swing -- and the
    result is written onto it, so it persists with the world and a save.
    Stable: the roll is seeded by who and where the creature is.
    """
    key = CORE_KEYS.get(attr_id)
    if key is None or not isinstance(props, dict):
        return attr.BASE_ATTRIBUTE
    if key == "charisma" and "charisma" not in props and "personality" in props:
        props["charisma"] = props["personality"]
    if key not in props:
        _roll_core(props)
    try:
        return attr.clamp(int(props[key]))
    except (TypeError, ValueError):
        return attr.BASE_ATTRIBUTE


def _roll_core(props) -> None:
    import zlib
    base = CORE_BASELINE.get(_kind(props), (40, 40, 40))
    seed = "|".join(str(props.get(k, "")) for k in ("name", "display_name", "npc_role",
                                                    "creature_role", "home"))
    rng = random.Random(zlib.crc32(seed.encode()))
    for (attr_id, key), value in zip(CORE_KEYS.items(), base):
        total = sum(roll_3d6(rng))
        if key not in props:
            props[key] = attr.clamp(int(round(value + (total - 10.5) * CREATURE_PIP)))
