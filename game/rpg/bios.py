"""
Who your dice say you are.

At character creation the player rolls 3d6 for STRENGTH, ENDURANCE and
CHARISMA (:mod:`game.rpg.charisma`). This module turns those three totals into
a short **bio**: a title and a paragraph that tell the player what kind of body
and face they have just been dealt, before they commit to it.

Each roll falls into one of five bands. The bio is built from a sentence per
stat, but the most memorable combinations -- the hulking brute nobody can bear
to look at, the frail beauty, the luckless wretch who rolled low across the
board -- have their own title and their own opening, so the extremes read as
characters rather than as a sum of parts.

Pure data and string assembly; no Qt.
"""

from __future__ import annotations

from typing import Dict, Tuple

#: Bands of a 3d6 total.
DIRE, POOR, AVERAGE, GOOD, HEROIC = "dire", "poor", "average", "good", "heroic"


def band(total: int) -> str:
    t = int(total)
    if t <= 5:
        return DIRE
    if t <= 8:
        return POOR
    if t <= 12:
        return AVERAGE
    if t <= 15:
        return GOOD
    return HEROIC


_STRENGTH = {
    DIRE: "Your arms are thin as kindling; a full waterskin is a burden and a sword "
          "a serious undertaking.",
    POOR: "You are on the slight side -- you'll want a light blade, and help with "
          "anything heavier than a sack of flour.",
    AVERAGE: "You have the honest strength of anyone who has worked for a living.",
    GOOD: "Years of labour have put real muscle on you; you swing a blade with "
          "weight behind it and carry a full pack without complaint.",
    HEROIC: "You are built like a smithy door. Men step aside in doorways, and "
            "you could carry a calf across a river.",
}
_ENDURANCE = {
    DIRE: "You catch every cough going and tire before the morning is out; a "
          "single bad wound could finish you.",
    POOR: "You bruise easily and your breath runs short on a steep road.",
    AVERAGE: "You can walk all day and take a knock or two.",
    GOOD: "You are hard to tire and harder to hurt -- the kind who shrugs off a "
          "fever in a day.",
    HEROIC: "You have the constitution of an old oak. Blows that would fell "
            "another merely annoy you.",
}
_CHARISMA = {
    DIRE: "And your face... people flinch. Children hide. Dogs bark. Merchants "
          "lock their stalls when they see you coming, and some will not deal "
          "with you at all -- though the odd cutthroat has been known to lose "
          "his nerve at the sight of you.",
    POOR: "You are no beauty, and folk let you know it -- expect cold greetings "
          "and higher prices.",
    AVERAGE: "Your face is unremarkable: nobody stares, nobody remembers.",
    GOOD: "You have a likeable, open face, and strangers warm to you quickly.",
    HEROIC: "You are striking. Doors open, prices soften and people find "
            "themselves wanting to help you.",
}

#: (strength band(s), endurance band(s), charisma band(s)) -> (title, opening).
#: Checked in order; the first match wins. A band set of None matches anything.
_ARCHETYPES: Tuple = (
    ((DIRE, POOR), (DIRE, POOR), (DIRE, POOR), "The Wretch",
     "The gods were not watching the day you were born -- or they were, and "
     "laughed. You will have to be clever, because you will never be anything "
     "else."),
    ((HEROIC, GOOD), (HEROIC, GOOD), (HEROIC, GOOD), "The Paragon",
     "Strong, hale and fair to look upon: the kind of hero the ballads are "
     "written about, and the kind the jealous never forgive."),
    ((HEROIC, GOOD), (HEROIC, GOOD), (DIRE,), "The Brute",
     "A great hulking thing with a face like a dropped pie. Few will love you, "
     "but fewer still will dare to tell you so."),
    ((HEROIC, GOOD), None, (DIRE, POOR), "The Ogre's Cousin",
     "Strong enough to frighten, ugly enough to be blamed for it."),
    ((DIRE, POOR), (DIRE, POOR), (HEROIC, GOOD), "The Frail Beauty",
     "Lovely and breakable. People will move mountains for you -- which is "
     "fortunate, because you cannot move them yourself."),
    ((DIRE, POOR), None, (HEROIC,), "The Silver Tongue",
     "What you lack in arm you make up in charm. You will talk your way out of "
     "more fights than you will ever win."),
    (None, (HEROIC,), (DIRE, POOR), "The Cockroach",
     "Unlovely and unkillable. Whatever the world throws at you, you are still "
     "there in the morning."),
    ((HEROIC,), (DIRE, POOR), None, "The Glass Giant",
     "Mighty in the arm and brittle as a dropped jug: hit first, because you "
     "cannot afford to be hit back."),
    ((AVERAGE,), (AVERAGE,), (AVERAGE,), "The Everyman",
     "Middling in every way that can be measured. Nobody expects anything of "
     "you -- which is its own kind of freedom."),
)


def _matches(want, got):
    return want is None or got in want


def bio_for(strength: int, endurance: int, charisma: int) -> Dict[str, str]:
    """``{"title", "text"}`` for three 3d6 totals."""
    s, e, c = band(strength), band(endurance), band(charisma)
    title, opening = None, ""
    for ws, we, wc, t, o in _ARCHETYPES:
        if _matches(ws, s) and _matches(we, e) and _matches(wc, c):
            title, opening = t, o
            break
    if title is None:
        title = _plain_title(s, e, c)
    body = " ".join(x for x in (opening, _STRENGTH[s], _ENDURANCE[e], _CHARISMA[c]) if x)
    return {"title": title, "text": body}


def _plain_title(s, e, c) -> str:
    """A title for a combination with no archetype of its own, from whichever
    of the three stands out most."""
    score = {DIRE: -2, POOR: -1, AVERAGE: 0, GOOD: 1, HEROIC: 2}
    ranked = sorted((("strength", s), ("endurance", e), ("charisma", c)),
                    key=lambda kv: abs(score[kv[1]]), reverse=True)
    stat, b = ranked[0]
    names = {
        ("strength", GOOD): "The Strong Arm", ("strength", HEROIC): "The Ox",
        ("strength", POOR): "The Slight", ("strength", DIRE): "The Feeble",
        ("endurance", GOOD): "The Hardy", ("endurance", HEROIC): "The Unbreakable",
        ("endurance", POOR): "The Sickly", ("endurance", DIRE): "The Ailing",
        ("charisma", GOOD): "The Charmer", ("charisma", HEROIC): "The Radiant",
        ("charisma", POOR): "The Homely", ("charisma", DIRE): "The Unsightly",
    }
    return names.get((stat, b), "The Wayfarer")


def bio_from_rolls(rolls) -> Dict[str, str]:
    """:func:`bio_for` from a creator's ``{attr_id: [d, d, d]}`` rolls."""
    def total(key):
        dice = rolls.get(key) or [3, 4, 4]
        return sum(int(d) for d in dice)
    return bio_for(total("strength"), total("endurance"), total("personality"))


# ---------------------------------------------------------------------------
# NPCs: everyone in the world has the same three numbers
# ---------------------------------------------------------------------------
#: Typical 3d6 leanings by role: (strength, endurance, charisma) added to the
#: roll before it is clamped to 3..18. A smith is strong, a guard is hardy, a
#: merchant has a face you trust.
ROLE_LEAN = {
    "blacksmith": (3, 2, 0), "guard": (2, 2, 0), "guard_archer": (1, 2, 0),
    "farmer": (1, 2, -1), "merchant": (-1, 0, 3), "villager": (0, 0, 0),
    "beggar": (-2, -1, -3), "bandit": (1, 1, -2), "bandit_archer": (0, 1, -2),
    "bandit_chief": (3, 2, -1), "cultist": (-1, 0, -1), "innkeeper": (0, 1, 2),
    "pilgrim": (-1, 1, 1), "adventurer": (2, 2, 0), "mercenary": (2, 2, -1),
    "courier": (-1, 2, 1), "minstrel": (-2, 0, 4), "bounty_hunter": (2, 2, -2),
}


def npc_rolls(name: str, role: str) -> Tuple[int, int, int]:
    """Deterministic 3d6 totals for an NPC: the same person always rolls the
    same, seeded by their name, nudged by what their trade makes of them."""
    import random
    rng = random.Random(f"mw-npc-{name}")
    lean = ROLE_LEAN.get(str(role or "").lower(), (0, 0, 0))
    out = []
    for k in range(3):
        total = sum(rng.randint(1, 6) for _ in range(3)) + lean[k]
        out.append(max(3, min(18, total)))
    return tuple(out)
