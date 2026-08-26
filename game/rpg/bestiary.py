"""
The bestiary — stat templates for every creature and NPC role.

Each role maps to a template: base health, melee/bow damage, **attack style**
(``melee`` or ``bow`` — never a gun), which loot table it drops, its faction and
its billboard scale. :class:`~game.entities.NPC` reads this so a
freshly-placed "wolf" or "bandit_archer" already fights and drops loot correctly,
and the engine's fantasy combat plays the right animation/sound.
"""

from __future__ import annotations

from typing import Dict, Optional

# attack styles understood by the engine's fantasy MonsterAI
MELEE = "melee"
BOW = "bow"


# Which editor entity a role belongs to. ``npc`` = a social townsperson / quest
# actor (schedule, dialogue, home/work); ``creature`` = a monster or wild animal
# (combat, loot, respawn). The two are authored as *separate* MiniWind entities
# even though both run on the same engine Monster + MonsterAI underneath.
NPC = "npc"
CREATURE = "creature"


class Creature:
    def __init__(self, role, name, health, damage, attack_style=MELEE,
                 faction="monsters", loot="", scale=112, aggression="hostile",
                 sight=1024, speed=90.0, level=1, xp=10, resistances=None,
                 kind=CREATURE):
        self.role = role
        self.name = name
        self.health = health
        self.damage = damage
        self.attack_style = attack_style
        self.faction = faction
        self.loot = loot
        self.scale = scale
        self.aggression = aggression
        self.sight = sight
        self.speed = speed
        self.level = level
        self.xp = xp
        self.resistances = resistances or {}
        #: 'npc' (townsperson/quest actor) or 'creature' (monster/animal).
        self.kind = kind


def _load_bestiary() -> Dict[str, Creature]:
    """Build the bestiary registry from ``game/data/bestiary.json`` (+ mods).

    The *content* (which creatures exist and their stats) is editable data; the
    :class:`Creature` template and everything that reads it stays code.
    """
    from game import data
    out: Dict[str, Creature] = {}
    for role, row in (data.load("bestiary") or {}).items():
        row = dict(row)
        out[role] = Creature(
            role,
            row.pop("name", role.title()),
            row.pop("health", 60),
            row.pop("damage", 6),
            attack_style=row.pop("attack_style", MELEE),
            faction=row.pop("faction", "monsters"),
            loot=row.pop("loot", ""),
            scale=row.pop("scale", 112),
            aggression=row.pop("aggression", "hostile"),
            sight=row.pop("sight", 1024),
            speed=row.pop("speed", 90.0),
            level=row.pop("level", 1),
            xp=row.pop("xp", 10),
            resistances=row.pop("resistances", None),
            kind=row.pop("kind", CREATURE),
        )
    return out


BESTIARY: Dict[str, Creature] = _load_bestiary()


def get(role: str) -> Optional[Creature]:
    return BESTIARY.get(str(role).lower())


def roles_of_kind(kind: str) -> list:
    """Role ids of a given kind ('npc' or 'creature'), in definition order."""
    return [r for r, c in BESTIARY.items() if c.kind == kind]


#: Roles the engine treats as genuinely hostile from the start.
HOSTILE_ROLES = {r for r, c in BESTIARY.items() if c.aggression == "hostile"}
