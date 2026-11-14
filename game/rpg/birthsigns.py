"""
Birthsigns — a small permanent bonus chosen at character creation.

Each sign grants a flat stat bonus and/or a granted spell/power -- the star
you were born under. Kept intentionally light:
one meaningful pick, no ongoing bookkeeping.
"""

from __future__ import annotations

from typing import Dict, List

from . import attributes as attr


#: Damage kinds a spell deals: what "weaker to magic" covers.
SPELL_DAMAGE_KINDS = ("magic", "fire", "frost", "shock")


class Birthsign:
    """One sign. Its description is its flavour line followed by exactly what
    it gives, written from the same data the rules read (:meth:`gifts`), so
    the two can never disagree."""

    __slots__ = ("id", "label", "flavour", "attr_bonuses", "stat_bonuses", "spells",
                 "resistances", "drawbacks")

    def __init__(self, sid, label, flavour, attr_bonuses=None, stat_bonuses=None,
                 spells=None, resistances=None, drawbacks=None):
        self.id = sid
        self.label = label
        self.flavour = flavour
        self.attr_bonuses = attr_bonuses or {}
        #: flat additions to derived pools, e.g. {"magicka": 50} or {"health": 25}
        self.stat_bonuses = stat_bonuses or {}
        self.spells = spells or []
        #: {damage_kind: fraction resisted}, as a race's; negative is a weakness
        #: (combat.resolve_incoming adds it to the race's)
        self.resistances = resistances or {}
        #: drawbacks the rules apply by the sign's id, in words (the Golem's)
        self.drawbacks = list(drawbacks or [])

    def gifts(self) -> str:
        """Exactly what the sign gives, in one sentence: "+10 Strength,
        +5 Endurance." -- or "No bonus." for none."""
        parts = [f"{int(self.attr_bonuses[a]):+d} {attr.label(a)}"
                 for a in attr.ATTRIBUTES if self.attr_bonuses.get(a)]
        for pool in ("health", "magicka", "stamina"):
            if self.stat_bonuses.get(pool):
                parts.append(f"{int(self.stat_bonuses[pool]):+d} {pool}")
        if self.spells:
            import game.rpg.magic as magic
            names = [magic.get(sp).name if magic.get(sp) else sp for sp in self.spells]
            parts.append("the " + _and(names) + (" spell" if len(names) == 1 else " spells"))
        bad = []
        for frac in sorted(set(self.resistances.values())):
            kinds = [k for k, v in self.resistances.items() if v == frac]
            if frac < 0:
                bad.append(f"{round(-frac * 100)}% more damage from {_and(kinds)}")
            elif frac > 0:
                parts.append(f"resist {round(frac * 100)}% of {_and(kinds)}")
        bad += self.drawbacks
        if not parts and not bad:
            return "No bonus."
        text = ", ".join(parts)
        if bad:
            text = (text + ", but " if text else "") + ", ".join(bad)
        text += "."
        if self.spells or self.stat_bonuses.get("magicka"):
            text += " Magicka and spells only for a class that works magic."
        return text

    @property
    def desc(self) -> str:
        return f"{self.flavour} {self.gifts()}"


def _and(words) -> str:
    words = list(words)
    if len(words) <= 1:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


BIRTHSIGNS: Dict[str, Birthsign] = {b.id: b for b in [
    Birthsign("warrior", "The Warrior",
              "The warrior's fortune favours those who live by the blade.",
              attr_bonuses={attr.STRENGTH: 10, attr.ENDURANCE: 5}),
    Birthsign("mage", "The Mage",
              "Magicka runs deeper in those born under the Mage.",
              attr_bonuses={attr.INTELLIGENCE: 10}, stat_bonuses={"magicka": 50}),
    Birthsign("thief", "The Thief",
              "The hardy and the lucky are the Thief's children.",
              attr_bonuses={attr.ENDURANCE: 10, attr.SPEED: 5, attr.LUCK: 5}),
    Birthsign("lady", "The Lady",
              "Grace and vigour.",
              attr_bonuses={attr.ENDURANCE: 10, attr.PERSONALITY: 10}),
    Birthsign("steed", "The Steed",
              "The restless are born under the Steed.",
              attr_bonuses={attr.SPEED: 15}),
    Birthsign("lord", "The Lord",
              "Slow to fall, quick to mend.",
              stat_bonuses={"health": 25}, spells=["heal_minor"]),
    Birthsign("apprentice", "The Apprentice",
              "Great power, and great risk.",
              stat_bonuses={"magicka": 100}, attr_bonuses={attr.INTELLIGENCE: 5},
              resistances={kind: -0.5 for kind in SPELL_DAMAGE_KINDS}),
    Birthsign("golem", "The Golem",
              "A vessel of raw power.",
              stat_bonuses={"magicka": 150},
              drawbacks=["magicka never regenerates"]),
    Birthsign("shadow", "The Shadow",
              "Born to slip away unseen.",
              spells=["invisibility_minor"], attr_bonuses={attr.ENDURANCE: 5}),
    Birthsign("none", "No Sign",
              "You were born under no particular star.",),
]}

BIRTHSIGN_IDS: List[str] = list(BIRTHSIGNS.keys())

#: Half the birthsigns, for the simplified character creator (the full table is
#: kept so existing saves / content that reference the others still resolve).
CREATION_BIRTHSIGN_IDS: List[str] = ["warrior", "mage", "thief", "lord", "shadow"]


def get(sign_id: str) -> Birthsign:
    return BIRTHSIGNS.get(str(sign_id).lower(), BIRTHSIGNS["none"])
