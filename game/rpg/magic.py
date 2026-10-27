"""
Magic — spells, schools, magicka cost, spell levels and cast resolution.

There are two schools: **Offensive** (what harms or commands) and
**Defensive** (what heals, wards and aids). A spell is a definition: its
school, a base magicka cost, a delivery (self / touch / target / projectile),
a list of effects, a rarity, and how it grows. The player raises each known
spell's **level** by spending experience (:meth:`Character.upgrade_spell`); a
higher level is stronger and lasts longer, and costs a little more magicka
(:meth:`Spell.at_level`). Every value lives in ``game/data/spells.json``,
which the Spell Editor reads and writes. Casting scales the cost down with skill, rolls success against skill,
and — on a hit — applies the effects (to the caster for self spells, or hands a
projectile/touch payload back to the caller for the engine to deliver).

Effects use the same ``{"kind","magnitude","duration"}`` vocabulary as potions
so one applier serves both.
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..diceroll import DiceRoller

from ..diceroll import CHECK_DIE, roll_check  # noqa: F401  (CHECK_DIE re-exported)
from . import attributes as attr
from . import skills as sk

# delivery
SELF = "self"
TOUCH = "touch"
TARGET = "target"
PROJECTILE = "projectile"

#: Default projectile/light colour (RGB 0-255) for each damage element. A spell
#: with no explicit ``color`` shows its element's colour; the editor and the
#: engine both read :func:`element_color` so a bolt and its attached light match.
ELEMENT_COLORS = {
    "fire":  [255, 140, 50],
    "frost": [150, 210, 255],
    "shock": [230, 230, 120],
    "magic": [140, 160, 255],
}
#: Colour for an unknown element / plain arcane bolt.
DEFAULT_SPELL_COLOR = [140, 160, 255]


def element_color(element) -> list:
    """The default projectile colour (RGB 0-255) for a damage *element*."""
    return list(ELEMENT_COLORS.get(str(element or "").lower(), DEFAULT_SPELL_COLOR))


#: Rarity tiers, commonest first. Rarer spells are dearer to level up.
RARITIES = ("common", "uncommon", "rare", "epic", "legendary")
#: Experience per spell level, by rarity, when a spell does not set its own.
RARITY_XP = {"common": 30, "uncommon": 45, "rare": 60, "epic": 80, "legendary": 120}
#: How a spell grows when it does not say: the highest level, extra
#: magnitude per level above the first (+25%), extra duration (+12.5%), and
#: extra magicka cost (+10%).
DEFAULT_MAX_LEVEL = 5
DEFAULT_LEVEL_POWER = 0.25
DEFAULT_LEVEL_DURATION = 0.125
DEFAULT_LEVEL_COST = 0.10
#: Effect kinds whose magnitude is an on/off switch (or "kill outright"), not
#: an amount: a level never scales them.
_FLAG_KINDS = {"knock", "wisp", "summon", "resurrect", "light", "night_eye",
               "invisibility", "cure_disease", "detect_life", "telekinesis"}


def default_rarity(cost) -> str:
    """A rarity for a spell that names none, from how dear it is to cast."""
    cost = float(cost)
    if cost >= 90:
        return "legendary"
    if cost >= 50:
        return "epic"
    if cost >= 30:
        return "rare"
    if cost >= 18:
        return "uncommon"
    return "common"


class Spell:
    def __init__(self, sid, name, school, cost, delivery, effects, desc="",
                 element="magic", projectile_speed=900.0, color=None, visuals=None,
                 rarity=None, max_level=DEFAULT_MAX_LEVEL, xp_per_level=None,
                 level_power=DEFAULT_LEVEL_POWER, level_duration=DEFAULT_LEVEL_DURATION,
                 level_cost=DEFAULT_LEVEL_COST, level=1):
        self.id = sid
        self.name = name
        self.school = sk.fold(school)  # sk.OFFENSIVE or sk.DEFENSIVE
        self.base_cost = float(cost)
        self.delivery = delivery
        self.effects = effects        # list of {"kind","magnitude","duration"}
        self.desc = desc
        self.element = element        # fire|frost|shock|magic (damage kind)
        self.projectile_speed = projectile_speed
        # Explicit projectile/light colour override (RGB 0-255) or None to use
        # the element default. Read via the ``color`` property.
        self._color = list(color) if color else None
        # How it looks over its element's default (game/magic_fx.py: trail,
        # orb, flash, ring, sparks, shards, rays, lens, hit_tint, cast), as set
        # in the Spell Editor; empty for the plain look.
        self.visuals = dict(visuals) if isinstance(visuals, dict) else {}
        self.rarity = rarity if rarity in RARITIES else default_rarity(cost)
        self.max_level = max(1, int(max_level))
        self.xp_per_level = int(xp_per_level if xp_per_level is not None
                                else RARITY_XP[self.rarity])
        self.level_power = float(level_power)
        self.level_duration = float(level_duration)
        self.level_cost = float(level_cost)
        #: Which level these numbers are for (1 for the definition itself).
        self.level = int(level)

    def at_level(self, level: int) -> "Spell":
        """This spell as it is cast at *level* (1..max_level): each level above
        the first adds :attr:`level_power` to every amount (damage, healing,
        a shield's strength...), :attr:`level_duration` to every duration,
        and :attr:`level_cost` to the magicka it costs. Switch-like effects
        (knock, invisibility...) only last longer."""
        level = max(1, min(self.max_level, int(level)))
        if level == 1:
            return self
        steps = level - 1
        power = 1.0 + self.level_power * steps
        longer = 1.0 + self.level_duration * steps
        effects = []
        for e in self.effects or []:
            e = dict(e)
            mag = float(e.get("magnitude", 0))
            if e.get("kind") not in _FLAG_KINDS and 1 < mag < 99999:
                e["magnitude"] = round(mag * power, 1)
            if float(e.get("duration", 0)) > 0:
                e["duration"] = round(float(e["duration"]) * longer, 1)
            effects.append(e)
        d = self.to_dict()
        d["effects"] = effects
        d["cost"] = round(self.base_cost * (1.0 + self.level_cost * steps), 1)
        d["level"] = level
        return Spell.from_dict(d)

    def xp_to_level(self, level: int) -> int:
        """Experience it costs to raise this spell from *level* to the next
        (0 once it is at :attr:`max_level`)."""
        if int(level) >= self.max_level:
            return 0
        return self.xp_per_level * max(1, int(level))

    @property
    def color(self) -> list:
        """Projectile/light colour (RGB 0-255): explicit override or element default."""
        return list(self._color) if self._color else element_color(self.element)

    @property
    def damage(self) -> float:
        """Total direct damage this spell deals (sum of its damage effects)."""
        return sum(float(e.get("magnitude", 0)) for e in (self.effects or [])
                   if str(e.get("kind", "")).startswith("damage"))

    def to_dict(self) -> Dict:
        """Serialise for the spell editor / data file (round-trips via from_dict)."""
        return {
            "id": self.id, "name": self.name, "school": self.school,
            "cost": self.base_cost, "delivery": self.delivery,
            "effects": [dict(e) for e in (self.effects or [])],
            "desc": self.desc, "element": self.element,
            "projectile_speed": self.projectile_speed,
            "color": list(self._color) if self._color else None,
            "visuals": dict(self.visuals),
            "rarity": self.rarity, "max_level": self.max_level,
            "xp_per_level": self.xp_per_level, "level_power": self.level_power,
            "level_duration": self.level_duration, "level_cost": self.level_cost,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Spell":
        return cls(
            d.get("id", ""), d.get("name", d.get("id", "Spell")),
            d.get("school", sk.OFFENSIVE), d.get("cost", 0),
            d.get("delivery", PROJECTILE), list(d.get("effects", []) or []),
            desc=d.get("desc", ""), element=d.get("element", "magic"),
            projectile_speed=d.get("projectile_speed", 900.0),
            color=d.get("color"), visuals=d.get("visuals"),
            rarity=d.get("rarity"), max_level=d.get("max_level", DEFAULT_MAX_LEVEL),
            xp_per_level=d.get("xp_per_level"),
            level_power=d.get("level_power", DEFAULT_LEVEL_POWER),
            level_duration=d.get("level_duration", DEFAULT_LEVEL_DURATION),
            level_cost=d.get("level_cost", DEFAULT_LEVEL_COST),
            level=d.get("level", 1))


SPELLS: Dict[str, Spell] = {}


def register(spell: Spell) -> Spell:
    SPELLS[spell.id] = spell
    return spell


def get(spell_id: str) -> Optional[Spell]:
    return SPELLS.get(str(spell_id))


def for_caster(character, spell_id: str) -> Optional[Spell]:
    """*spell_id* as *character* casts it: at the level they have raised it to."""
    spell = get(spell_id)
    if spell is None:
        return None
    levels = getattr(character, "spell_levels", None) or {}
    return spell.at_level(int(levels.get(spell.id, 1)))


# ---------------------------------------------------------------------------
# Spell book
# ---------------------------------------------------------------------------
# Offensive: what harms or commands
register(Spell("flare", "Flare", sk.OFFENSIVE, 12, PROJECTILE,
               [{"kind": "damage_health", "magnitude": 14, "duration": 0}],
               "A bolt of fire.", element="fire", projectile_speed=1000))
register(Spell("firebolt", "Firebolt", sk.OFFENSIVE, 28, PROJECTILE,
               [{"kind": "damage_health", "magnitude": 30, "duration": 0}],
               "A searing bolt of flame.", element="fire", projectile_speed=1100))
register(Spell("frostbite", "Frostbite", sk.OFFENSIVE, 20, PROJECTILE,
               [{"kind": "damage_health", "magnitude": 18, "duration": 0},
                {"kind": "drain_stamina", "magnitude": 15, "duration": 0}],
               "Frost that saps the limbs.", element="frost", projectile_speed=950))
register(Spell("lightning", "Lightning Bolt", sk.OFFENSIVE, 30, PROJECTILE,
               [{"kind": "damage_health", "magnitude": 26, "duration": 0},
                {"kind": "damage_magicka", "magnitude": 15, "duration": 0}],
               "A crackling arc of shock.", element="shock", projectile_speed=1600))
# Disintegrate — a bolt of pure annihilation. Its projectile is ALWAYS red (an
# explicit colour override, independent of element) and its damage is high enough
# to kill anything in one hit (and gib it, being far over the overkill threshold).
register(Spell("disintegrate", "Disintegrate", sk.OFFENSIVE, 60, PROJECTILE,
               [{"kind": "damage_health", "magnitude": 99999, "duration": 0}],
               "A bolt of pure annihilation — kills instantly on contact.",
               element="magic", projectile_speed=1400.0, color=[255, 0, 0]))
# Defensive: what heals, wards and aids
register(Spell("heal_minor", "Minor Healing", sk.DEFENSIVE, 15, SELF,
               [{"kind": "restore_health", "magnitude": 30, "duration": 0}],
               "Knit minor wounds.", element="magic"))
register(Spell("heal", "Healing", sk.DEFENSIVE, 34, SELF,
               [{"kind": "restore_health", "magnitude": 75, "duration": 0}],
               "Close deep wounds.", element="magic"))
register(Spell("heal_over_time", "Mending", sk.DEFENSIVE, 24, SELF,
               [{"kind": "restore_health", "magnitude": 8, "duration": 8}],
               "Steady regeneration over time.", element="magic"))
register(Spell("cure_disease_spell", "Cure Disease", sk.DEFENSIVE, 30, SELF,
               [{"kind": "cure_disease", "magnitude": 1, "duration": 0}],
               "Purge disease from your body.", element="magic"))
register(Spell("knock", "Knock", sk.DEFENSIVE, 45, TOUCH,
               [{"kind": "knock", "magnitude": 1, "duration": 0}],
               "Open a nearby locked container. Frees even a lock jammed by a sheared pick.",
               color=[133, 203, 187]))
register(Spell("sp_shield", "Shield", sk.DEFENSIVE, 20, SELF,
               [{"kind": "shield", "magnitude": 20, "duration": 30}],
               "A protective ward.", element="magic"))
register(Spell("sp_dragonskin", "Dragon Skin", sk.DEFENSIVE, 60, SELF,
               [{"kind": "shield", "magnitude": 50, "duration": 30}],
               "A powerful magical hide.", element="magic"))
register(Spell("sp_feather", "Feather", sk.DEFENSIVE, 18, SELF,
               [{"kind": "feather", "magnitude": 100, "duration": 60}],
               "Lighten your burden.", element="magic"))
register(Spell("sp_nighteye", "Night Eye", sk.DEFENSIVE, 14, SELF,
               [{"kind": "night_eye", "magnitude": 1, "duration": 60}],
               "See in the dark.", element="magic"))
register(Spell("sp_light", "Light", sk.DEFENSIVE, 8, SELF,
               [{"kind": "light", "magnitude": 1, "duration": 60}],
               "Conjure a floating light.", element="magic"))
register(Spell("invisibility_minor", "Invisibility", sk.DEFENSIVE, 40, SELF,
               [{"kind": "invisibility", "magnitude": 1, "duration": 20}],
               "Vanish from sight for a while.", element="magic"))
register(Spell("sp_calm", "Calm", sk.DEFENSIVE, 22, TARGET,
               [{"kind": "calm", "magnitude": 30, "duration": 15}],
               "Soothe a foe into stopping its attack.", element="magic"))
register(Spell("sp_commandcreature", "Command Creature", sk.OFFENSIVE, 26, TARGET,
               [{"kind": "command", "magnitude": 30, "duration": 20}],
               "Bend a beast to your will.", element="magic"))
register(Spell("summon_wolf", "Summon Wolf", sk.OFFENSIVE, 30, SELF,
               [{"kind": "summon", "magnitude": 1, "duration": 45, "creature": "wolf"}],
               "Call a spectral wolf to fight for you.", element="magic"))
register(Spell("wisp", "Wisp", sk.DEFENSIVE, 15, SELF,
               [{"kind": "wisp", "magnitude": 1, "duration": 120}],
               "Conjure a wandering fairy light that flits about you, lighting "
               "your way. Its hue is a whim of the moment.", element="magic"))
register(Spell("bound_blade", "Bound Blade", sk.OFFENSIVE, 25, SELF,
               [{"kind": "bound_weapon", "magnitude": 18, "duration": 60}],
               "Summon a blade of pure magicka.", element="magic"))
# Resurrection — the Necromancer's signature. Cast near a fallen character to
# call it back to life. Special rules enforced by the caster (game.runtime):
# it drains ALL remaining magicka and can be worked only once per in-game day.
register(Spell("resurrection", "Resurrection", sk.DEFENSIVE, 100, TARGET,
               [{"kind": "resurrect", "magnitude": 1, "duration": 0}],
               "Call a fallen soul back into its body. Drains all your magicka "
               "and can be worked only once each day.",
               element="magic", color=[120, 255, 170]))
register(Spell("sp_detect", "Detect Life", sk.DEFENSIVE, 16, SELF,
               [{"kind": "detect_life", "magnitude": 1, "duration": 30}],
               "Sense living things nearby.", element="magic"))
register(Spell("sp_telekinesis", "Telekinesis", sk.DEFENSIVE, 18, TARGET,
               [{"kind": "telekinesis", "magnitude": 1, "duration": 10}],
               "Grasp an object from afar.", element="magic"))
# Racial power spells (referenced by races.py)
register(Spell("sp_woad", "Woad", sk.DEFENSIVE, 0, SELF,
               [{"kind": "shield", "magnitude": 30, "duration": 30}], "Nord racial shield."))
register(Spell("sp_flameshield", "Ancestor's Wrath", sk.DEFENSIVE, 0, SELF,
               [{"kind": "fire_shield", "magnitude": 15, "duration": 20}], "Ashfolk flame cloak."))
register(Spell("sp_berserk", "Berserk", sk.OFFENSIVE, 0, SELF,
               [{"kind": "berserk", "magnitude": 30, "duration": 20}], "Orc rage."))
register(Spell("sp_adrenaline", "Adrenaline Rush", sk.DEFENSIVE, 0, SELF,
               [{"kind": "fortify_speed", "magnitude": 40, "duration": 20}], "Redguard surge."))
register(Spell("sp_restoremagicka", "Highborn", sk.DEFENSIVE, 0, SELF,
               [{"kind": "restore_magicka", "magnitude": 100, "duration": 0}], "Highkin magicka burst."))
register(Spell("sp_histskin", "Histskin", sk.DEFENSIVE, 0, SELF,
               [{"kind": "restore_health", "magnitude": 10, "duration": 10}], "Marshborn regeneration."))


# ---------------------------------------------------------------------------
# Data-driven custom spells / overrides (edited by the Tools ▸ Spell Editor)
# ---------------------------------------------------------------------------
# Built-in spells above are code; a project can add new spells or override the
# built-ins by editing ``game/data/spells.json`` — a list of spell dicts in the
# Spell.to_dict() shape. This keeps designer content out of code while the Spell
# type and casting rules stay code.

def _spells_data_path() -> str:
    import os
    return os.path.join(os.path.dirname(__file__), "..", "data", "spells.json")


def load_custom_spells() -> int:
    """Load/override spells from ``game/data/spells.json`` (if present).

    Each entry is a :meth:`Spell.to_dict` dict; it registers a new spell or
    overrides a built-in with the same id. Returns how many were applied. Fully
    guarded — a missing or malformed file is ignored."""
    import json
    path = _spells_data_path()
    try:
        with open(path, "r") as f:
            rows = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return 0
    n = 0
    for row in rows if isinstance(rows, list) else []:
        try:
            if row.get("id"):
                register(Spell.from_dict(row))
                n += 1
        except Exception:
            continue
    return n


def save_custom_spells(spells: List[Dict]) -> bool:
    """Write a list of spell dicts to ``game/data/spells.json`` and re-load them.

    Used by the Spell Editor. Returns True on success. The written spells are
    applied to the live registry immediately so a play-test reflects edits."""
    import json
    import os
    path = _spells_data_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(list(spells), f, indent=2)
    except OSError:
        return False
    for row in spells:
        try:
            if isinstance(row, dict) and row.get("id"):
                register(Spell.from_dict(row))
        except Exception:
            continue
    return True


# Apply any project custom spells/overrides on import (guarded).
try:
    load_custom_spells()
except Exception:
    pass


def cast_cost(character, spell: Spell) -> float:
    """Magicka cost after the caster's skill discount (min 25% of base)."""
    if spell.base_cost <= 0:
        return 0.0
    skill = character.skill(spell.school)
    factor = max(0.25, 1.0 - skill / 150.0)
    return round(spell.base_cost * factor, 1)


#: Most a single spell's practice adds to its cast chance, and how much each
#: successful cast of it adds toward that.
PRACTICE_BONUS_MAX = 0.15
PRACTICE_PER_CAST = 0.005


def cast_chance(character, spell: Spell) -> float:
    """Probability [0.10, 0.98] that casting *spell* works.

    Learn-by-doing: the school skill carries most of it, so every point a
    caster earns by casting shows up as fewer fizzles. A novice (skill 5,
    average Endurance) lands a cheap spell a little under half the time; by
    skill 50 three casts in four; a master almost never fizzles. Endurance
    and Luck nudge it, an expensive spell is harder, and practice with one
    particular spell (successful casts of it) steadies it by up to
    :data:`PRACTICE_BONUS_MAX`.
    """
    if spell.base_cost <= 0:
        return 1.0
    skill = character.skill(spell.school)
    end = character.attrs.get(attr.ENDURANCE, 40)
    luck = character.attrs.get(attr.LUCK, 40)
    practice = int(getattr(character, "spell_practice", {}).get(spell.id, 0))
    chance = (0.42 + skill * 0.0065
              + (end - 40) * 0.004 + (luck - 40) * 0.002
              - spell.base_cost * 0.008
              + min(PRACTICE_BONUS_MAX, practice * PRACTICE_PER_CAST))
    return max(0.10, min(0.98, chance))


def cast_check(character, spell: Spell, rng: Optional[random.Random] = None,
               dice: Optional["DiceRoller"] = None):
    """Resolve a cast check and return ``(success, dice_result)``."""
    rng = rng or random
    if spell.base_cost <= 0:
        return True, None  # powers never fizzle
    chance = cast_chance(character, spell)
    # A d20 check, like every other chance in the game — there is no d100 die
    # to put on screen (see diceroll.CHECK_DIE). The cast succeeds on a roll at
    # or above check_target(chance).
    if dice is not None:
        result = roll_check(
            dice, chance, f"Roll to cast {spell.name}", source="magic.cast",
            why=f"{sk.label(spell.school)} {character.skill(spell.school)}, "
                f"spell difficulty {spell.base_cost} — {chance * 100:.0f}%",
            context={"spell_id": spell.id, "school": spell.school})
        return bool(result.get("success")), result
    return rng.random() <= chance, None


def cast_success(character, spell: Spell, rng: Optional[random.Random] = None,
                 dice: Optional["DiceRoller"] = None) -> bool:
    """Roll whether a cast succeeds (skill + endurance + luck vs difficulty)."""
    return cast_check(character, spell, rng=rng, dice=dice)[0]


class CastResult:
    def __init__(self, cast=False, reason="", spell=None, magnitude=0.0, roll=None):
        self.cast = cast
        self.reason = reason
        self.spell = spell
        self.magnitude = magnitude
        self.roll = roll


def try_cast(character, spell_id: str, rng: Optional[random.Random] = None,
             dice: Optional["DiceRoller"] = None) -> CastResult:
    """Attempt to cast a known spell.

    Spends magicka, rolls success, and — for SELF spells — applies effects to the
    caster immediately. TARGET/PROJECTILE/TOUCH spells return a successful result
    for the caller (engine adapter) to deliver against a creature.
    """
    spell = for_caster(character, spell_id)
    if spell is None:
        return CastResult(False, "unknown spell")
    if spell_id not in character.known_spells:
        return CastResult(False, "not known", spell)
    cost = cast_cost(character, spell)
    if not character.spend_magicka(cost):
        return CastResult(False, "not enough magicka", spell)
    success, roll = cast_check(character, spell, rng=rng, dice=dice)
    if not success:
        # A fizzle still teaches -- you learn as much from what goes wrong.
        character.use_skill(spell.school, 1.0 + spell.base_cost / 60.0)
        return CastResult(False, "fizzle", spell, roll=roll)

    character.use_skill(spell.school, 1.5 + spell.base_cost / 30.0)
    practice = getattr(character, "spell_practice", None)
    if isinstance(practice, dict):
        practice[spell.id] = int(practice.get(spell.id, 0)) + 1

    if spell.delivery == SELF:
        apply_effects_to_character(character, spell.effects)
    mag = sum(float(e.get("magnitude", 0)) for e in spell.effects
              if e.get("kind", "").startswith("damage"))
    return CastResult(True, "", spell, mag, roll=roll)


def apply_effects_to_character(character, effects: List[Dict]) -> None:
    """Apply a list of effects to *character* (heals, shields, buffs, damage)."""
    for e in effects or []:
        kind = e.get("kind")
        mag = float(e.get("magnitude", 0))
        dur = float(e.get("duration", 0))
        if kind == "restore_health":
            if dur > 0:
                character.add_effect("restore_health", mag, dur)
            else:
                character.heal(mag)
        elif kind == "restore_magicka":
            character.restore_magicka(mag)
        elif kind == "restore_stamina":
            character.stamina = min(character.max_stamina, character.stamina + mag)
        elif kind == "damage_health":
            character.damage(mag)
            character._last_harm = (None, "poison", "poison")   # for the death screen
        else:
            # buffs/utility (shield, night_eye, invisibility, feather, ...) just
            # live as timed effects the HUD/gameplay reads.
            character.add_effect(kind, mag, dur if dur > 0 else 1.0)
