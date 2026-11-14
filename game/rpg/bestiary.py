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


#: Body sizes, D&D's categories, and how much body each is beside a person
#: (1.0). Health is toughness, not bulk: a veteran guard has more of it than
#: a farmer and is no bigger, a bear more than both and is.
TINY, SMALL, MEDIUM, LARGE, HUGE = "tiny", "small", "medium", "large", "huge"
SIZES = {TINY: 0.12, SMALL: 0.4, MEDIUM: 1.0, LARGE: 2.2, HUGE: 3.0}


class Creature:
    def __init__(self, role, name, health, damage, attack_style=MELEE,
                 faction="monsters", loot="", scale=112, aggression="hostile",
                 sight=1024, speed=90.0, level=1, xp=10, resistances=None,
                 kind=CREATURE, weapon="", produces="",
                 produce_every_hours=0.0, produce_into="world",
                 produce_quantity=1, size=MEDIUM):
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
        self.weapon = weapon
        #: 'npc' (townsperson/quest actor) or 'creature' (monster/animal).
        self.kind = kind
        #: Production (see :mod:`game.sim.production`): an item id this role
        #: yields on a clock, and how. Authored as ordinary bestiary content, so
        #: a cow, a hen or an alchemist's still is a data row, not a system.
        self.produces = produces
        self.produce_every_hours = produce_every_hours
        self.produce_into = produce_into
        self.produce_quantity = produce_quantity
        #: How big a body it is (:data:`SIZES`): how much there is of it to
        #: blow apart, whatever its health.
        self.size = size if size in SIZES else MEDIUM


def _load_bestiary() -> Dict[str, Creature]:
    """Build the bestiary registry from ``game/data/bestiary.json`` (+ mods).

    The *content* (which creatures exist and their stats) is editable data; the
    :class:`Creature` template and everything that reads it stays code.
    """
    import game.data as data
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
            weapon=row.pop("weapon", ""),
            produces=row.pop("produces", ""),
            produce_every_hours=row.pop("produce_every_hours", 0.0),
            produce_into=row.pop("produce_into", "world"),
            produce_quantity=row.pop("produce_quantity", 1),
            size=row.pop("size", MEDIUM),
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


def body_size(props) -> str:
    """How big the actor with *props* is: its own ``body_size`` when the map
    says, else its kind's (the bestiary, by role), else a person's."""
    props = props or {}
    own = str(props.get("body_size") or "").lower()
    if own in SIZES:
        return own
    for key in ("npc_role", "creature_role", "monster_type"):
        tmpl = get(props.get(key) or "")
        if tmpl is not None:
            return tmpl.size
    return MEDIUM


def body_mass(props) -> float:
    """How much body the actor with *props* is, a person being 1.0."""
    return SIZES[body_size(props)]
