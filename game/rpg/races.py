"""
Playable races.

Each race shifts the base attribute block, gives a few skill bonuses, may grant
resistances/weaknesses and a once-a-day racial power. Values are deltas applied
on top of :data:`attributes.BASE_ATTRIBUTE` / the base skill block during
character creation.

Ten races drawing on the broad well of fantasy RPGs (a little of the Elder
Scrolls, a little of Gothic and D&D), recast for the world of Miniwind.
"""

from __future__ import annotations

from typing import Dict, List

from . import attributes as attr
from . import skills as sk


class Race:
    __slots__ = ("id", "label", "desc", "attr_bonuses", "skill_bonuses",
                 "resistances", "power", "male_height", "starting_spells")

    def __init__(self, rid, label, desc, attr_bonuses=None, skill_bonuses=None,
                 resistances=None, power=None, starting_spells=None):
        self.id = rid
        self.label = label
        self.desc = desc
        self.attr_bonuses = attr_bonuses or {}
        self.skill_bonuses = skill_bonuses or {}
        #: {damage_kind: fraction_resisted}, e.g. {"fire": 0.5} = 50% less fire.
        self.resistances = resistances or {}
        #: {"name","desc","effect": spell-id or callable-key} — a daily power.
        self.power = power
        self.starting_spells = starting_spells or []


RACES: Dict[str, Race] = {r.id: r for r in [
    Race("nord", "Highlander",
         "Hardy folk of the frozen north; born warriors with frost in their blood.",
         attr_bonuses={attr.STRENGTH: 10, attr.ENDURANCE: 10, attr.WILLPOWER: 5,
                       attr.INTELLIGENCE: -10, attr.PERSONALITY: -5},
         skill_bonuses={sk.BLUNT: 10, sk.BLADE: 5, sk.HEAVY_ARMOR: 10, sk.BLOCK: 5},
         resistances={"frost": 0.5, "shock": 0.25},
         power={"name": "Woad", "desc": "Shield yourself for a short time.",
                "spell": "sp_woad"}),
    Race("imperial", "Valian",
         "Disciplined folk of the old Vale realm; silver-tongued and well-rounded.",
         attr_bonuses={attr.WILLPOWER: 5, attr.PERSONALITY: 10},
         skill_bonuses={sk.BLADE: 5, sk.BLUNT: 5, sk.HEAVY_ARMOR: 5,
                        sk.SPEECHCRAFT: 10, sk.MERCANTILE: 10},
         power={"name": "Silver Tongue", "desc": "Calm a nearby foe.",
                "spell": "sp_calm"}),
    Race("breton", "Wyrfolk",
         "Half-elven scholars with magic woven into their bones.",
         attr_bonuses={attr.INTELLIGENCE: 10, attr.WILLPOWER: 10,
                       attr.STRENGTH: -10, attr.ENDURANCE: -5},
         skill_bonuses={sk.CONJURATION: 10, sk.MYSTICISM: 5, sk.RESTORATION: 10,
                        sk.ALCHEMY: 5, sk.ALTERATION: 5},
         resistances={"magic": 0.5},
         power={"name": "Dragon Skin", "desc": "A strong magical shield.",
                "spell": "sp_dragonskin"},
         starting_spells=["heal_minor"]),
    Race("dunmer", "Ashfolk",
         "Grey-skinned exiles of the ash wastes, equally at home with blade and flame.",
         attr_bonuses={attr.AGILITY: 5, attr.SPEED: 10, attr.STRENGTH: 5,
                       attr.PERSONALITY: -5, attr.WILLPOWER: -5},
         skill_bonuses={sk.BLADE: 10, sk.DESTRUCTION: 10, sk.LIGHT_ARMOR: 5,
                        sk.MARKSMAN: 5, sk.MYSTICISM: 5, sk.ATHLETICS: 5},
         resistances={"fire": 0.75},
         power={"name": "Ancestor's Wrath", "desc": "Wreathe yourself in flame.",
                "spell": "sp_flameshield"}),
    Race("bosmer", "Woodkin",
         "Lithe forest-elves; unmatched with a bow and at ease among beasts.",
         attr_bonuses={attr.AGILITY: 10, attr.SPEED: 10, attr.STRENGTH: -10,
                       attr.WILLPOWER: -10, attr.PERSONALITY: 5},
         skill_bonuses={sk.MARKSMAN: 15, sk.SNEAK: 10, sk.LIGHT_ARMOR: 5,
                        sk.ALCHEMY: 5, sk.ACROBATICS: 5},
         resistances={"disease": 0.75, "poison": 0.75},
         power={"name": "Beast Tongue", "desc": "Command a nearby animal.",
                "spell": "sp_commandcreature"}),
    Race("altmer", "Highkin",
         "Tall golden-skinned elves of towering intellect and magicka — and its risks.",
         attr_bonuses={attr.INTELLIGENCE: 10, attr.WILLPOWER: 10,
                       attr.STRENGTH: -5, attr.ENDURANCE: -5, attr.SPEED: -5},
         skill_bonuses={sk.DESTRUCTION: 10, sk.ALTERATION: 10, sk.ILLUSION: 5,
                        sk.CONJURATION: 5, sk.MYSTICISM: 5, sk.ALCHEMY: 5},
         resistances={"disease": 0.75, "fire": -0.25, "frost": -0.25, "shock": -0.25},
         power={"name": "Highborn", "desc": "Restore a burst of magicka.",
                "spell": "sp_restoremagicka"},
         starting_spells=["flare", "heal_minor"]),
    Race("orc", "Orc",
         "Stout mountain orcs whose smiths and berserkers are feared everywhere.",
         attr_bonuses={attr.STRENGTH: 5, attr.ENDURANCE: 10, attr.WILLPOWER: 10,
                       attr.AGILITY: -5, attr.PERSONALITY: -10, attr.INTELLIGENCE: -5},
         skill_bonuses={sk.HEAVY_ARMOR: 15, sk.BLUNT: 10, sk.BLOCK: 5, sk.BLADE: 5},
         resistances={"magic": 0.25},
         power={"name": "Berserk", "desc": "Rage: more damage, less defence.",
                "spell": "sp_berserk"}),
    Race("redguard", "Sunborn",
         "Sun-dark warriors of the far reaches, born with steel in hand.",
         attr_bonuses={attr.STRENGTH: 5, attr.ENDURANCE: 10, attr.AGILITY: 5,
                       attr.INTELLIGENCE: -10, attr.WILLPOWER: -5},
         skill_bonuses={sk.BLADE: 10, sk.BLUNT: 5, sk.HEAVY_ARMOR: 5,
                        sk.LIGHT_ARMOR: 5, sk.ATHLETICS: 10},
         resistances={"poison": 0.75, "disease": 0.5},
         power={"name": "Adrenaline Rush", "desc": "A surge of speed and strength.",
                "spell": "sp_adrenaline"}),
    Race("khajiit", "Tehani",
         "Cat-folk caravaners; quick, clawed and light on their feet.",
         attr_bonuses={attr.AGILITY: 10, attr.SPEED: 5, attr.PERSONALITY: 5,
                       attr.ENDURANCE: -5, attr.WILLPOWER: -5},
         skill_bonuses={sk.SNEAK: 5, sk.LIGHT_FINGERS: 10, sk.ACROBATICS: 5,
                        sk.SECURITY: 5, sk.LIGHT_ARMOR: 5, sk.BLADE: 5},
         power={"name": "Eye of Night", "desc": "See in the dark for a while.",
                "spell": "sp_nighteye"}),
    Race("argonian", "Marshborn",
         "Reptilian folk of the black marsh; immune to poison and at home in deep water.",
         attr_bonuses={attr.AGILITY: 5, attr.SPEED: 5, attr.INTELLIGENCE: 5,
                       attr.STRENGTH: -5, attr.WILLPOWER: -5},
         skill_bonuses={sk.ALCHEMY: 5, sk.ILLUSION: 5, sk.MYSTICISM: 5,
                        sk.SNEAK: 5, sk.SECURITY: 5, sk.BLADE: 5, sk.SPEECHCRAFT: 5},
         resistances={"poison": 1.0, "disease": 0.75},
         power={"name": "Histskin", "desc": "Rapidly regenerate health.",
                "spell": "sp_histskin"}),
]}

RACE_IDS: List[str] = list(RACES.keys())


def get(race_id: str) -> Race:
    return RACES.get(str(race_id).lower(), RACES["imperial"])
