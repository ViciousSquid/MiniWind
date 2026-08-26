"""
Magic — spells, schools, magicka cost and cast resolution.

A spell is a static definition: a school (which magic skill governs it), a base
magicka cost, a delivery (self / touch / target / projectile) and a list of
effects. Casting scales the cost down with skill, rolls success against skill,
and — on a hit — applies the effects (to the caster for self spells, or hands a
projectile/touch payload back to the caller for the engine to deliver).

Effects use the same ``{"kind","magnitude","duration"}`` vocabulary as potions
so one applier serves both.
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional

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


class Spell:
    def __init__(self, sid, name, school, cost, delivery, effects, desc="",
                 element="magic", projectile_speed=900.0, color=None):
        self.id = sid
        self.name = name
        self.school = school          # a magic skill id (destruction, etc.)
        self.base_cost = float(cost)
        self.delivery = delivery
        self.effects = effects        # list of {"kind","magnitude","duration"}
        self.desc = desc
        self.element = element        # fire|frost|shock|magic (damage kind)
        self.projectile_speed = projectile_speed
        # Explicit projectile/light colour override (RGB 0-255) or None to use
        # the element default. Read via the ``color`` property.
        self._color = list(color) if color else None

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
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "Spell":
        return cls(
            d.get("id", ""), d.get("name", d.get("id", "Spell")),
            d.get("school", sk.DESTRUCTION), d.get("cost", 0),
            d.get("delivery", PROJECTILE), list(d.get("effects", []) or []),
            desc=d.get("desc", ""), element=d.get("element", "magic"),
            projectile_speed=d.get("projectile_speed", 900.0),
            color=d.get("color"))


SPELLS: Dict[str, Spell] = {}


def register(spell: Spell) -> Spell:
    SPELLS[spell.id] = spell
    return spell


def get(spell_id: str) -> Optional[Spell]:
    return SPELLS.get(str(spell_id))


# ---------------------------------------------------------------------------
# Spell book
# ---------------------------------------------------------------------------
# Destruction
register(Spell("flare", "Flare", sk.DESTRUCTION, 12, PROJECTILE,
               [{"kind": "damage_health", "magnitude": 14, "duration": 0}],
               "A bolt of fire.", element="fire", projectile_speed=1000))
register(Spell("firebolt", "Firebolt", sk.DESTRUCTION, 28, PROJECTILE,
               [{"kind": "damage_health", "magnitude": 30, "duration": 0}],
               "A searing bolt of flame.", element="fire", projectile_speed=1100))
register(Spell("frostbite", "Frostbite", sk.DESTRUCTION, 20, PROJECTILE,
               [{"kind": "damage_health", "magnitude": 18, "duration": 0},
                {"kind": "drain_stamina", "magnitude": 15, "duration": 0}],
               "Frost that saps the limbs.", element="frost", projectile_speed=950))
register(Spell("lightning", "Lightning Bolt", sk.DESTRUCTION, 30, PROJECTILE,
               [{"kind": "damage_health", "magnitude": 26, "duration": 0},
                {"kind": "damage_magicka", "magnitude": 15, "duration": 0}],
               "A crackling arc of shock.", element="shock", projectile_speed=1600))
# Instadeath — a bolt of pure annihilation. Its projectile is ALWAYS red (an
# explicit colour override, independent of element) and its damage is high enough
# to kill anything in one hit (and gib it, being far over the overkill threshold).
register(Spell("instadeath", "Instadeath", sk.DESTRUCTION, 60, PROJECTILE,
               [{"kind": "damage_health", "magnitude": 99999, "duration": 0}],
               "A bolt of pure annihilation — kills instantly on contact.",
               element="magic", projectile_speed=1400.0, color=[255, 0, 0]))
# Restoration
register(Spell("heal_minor", "Minor Healing", sk.RESTORATION, 15, SELF,
               [{"kind": "restore_health", "magnitude": 30, "duration": 0}],
               "Knit minor wounds.", element="magic"))
register(Spell("heal", "Healing", sk.RESTORATION, 34, SELF,
               [{"kind": "restore_health", "magnitude": 75, "duration": 0}],
               "Close deep wounds.", element="magic"))
register(Spell("heal_over_time", "Mending", sk.RESTORATION, 24, SELF,
               [{"kind": "restore_health", "magnitude": 8, "duration": 8}],
               "Steady regeneration over time.", element="magic"))
register(Spell("cure_disease_spell", "Cure Disease", sk.RESTORATION, 30, SELF,
               [{"kind": "cure_disease", "magnitude": 1, "duration": 0}],
               "Purge disease from your body.", element="magic"))
# Alteration
register(Spell("sp_shield", "Shield", sk.ALTERATION, 20, SELF,
               [{"kind": "shield", "magnitude": 20, "duration": 30}],
               "A protective ward.", element="magic"))
register(Spell("sp_dragonskin", "Dragon Skin", sk.ALTERATION, 60, SELF,
               [{"kind": "shield", "magnitude": 50, "duration": 30}],
               "A powerful magical hide.", element="magic"))
register(Spell("sp_feather", "Feather", sk.ALTERATION, 18, SELF,
               [{"kind": "feather", "magnitude": 100, "duration": 60}],
               "Lighten your burden.", element="magic"))
register(Spell("sp_nighteye", "Night Eye", sk.ALTERATION, 14, SELF,
               [{"kind": "night_eye", "magnitude": 1, "duration": 60}],
               "See in the dark.", element="magic"))
# Illusion
register(Spell("sp_light", "Light", sk.ILLUSION, 8, SELF,
               [{"kind": "light", "magnitude": 1, "duration": 60}],
               "Conjure a floating light.", element="magic"))
register(Spell("invisibility_minor", "Invisibility", sk.ILLUSION, 40, SELF,
               [{"kind": "invisibility", "magnitude": 1, "duration": 20}],
               "Vanish from sight for a while.", element="magic"))
register(Spell("sp_calm", "Calm", sk.ILLUSION, 22, TARGET,
               [{"kind": "calm", "magnitude": 30, "duration": 15}],
               "Soothe a foe into stopping its attack.", element="magic"))
register(Spell("sp_commandcreature", "Command Creature", sk.ILLUSION, 26, TARGET,
               [{"kind": "command", "magnitude": 30, "duration": 20}],
               "Bend a beast to your will.", element="magic"))
# Conjuration
register(Spell("summon_wolf", "Summon Wolf", sk.CONJURATION, 30, SELF,
               [{"kind": "summon", "magnitude": 1, "duration": 45, "creature": "wolf"}],
               "Call a spectral wolf to fight for you.", element="magic"))
register(Spell("wisp", "Wisp", sk.CONJURATION, 15, SELF,
               [{"kind": "wisp", "magnitude": 1, "duration": 120}],
               "Conjure a wandering fairy light that flits about you, lighting "
               "your way. Its hue is a whim of the moment.", element="magic"))
register(Spell("bound_blade", "Bound Blade", sk.CONJURATION, 25, SELF,
               [{"kind": "bound_weapon", "magnitude": 18, "duration": 60}],
               "Summon a blade of pure magicka.", element="magic"))
# Mysticism
register(Spell("sp_detect", "Detect Life", sk.MYSTICISM, 16, SELF,
               [{"kind": "detect_life", "magnitude": 1, "duration": 30}],
               "Sense living things nearby.", element="magic"))
register(Spell("sp_telekinesis", "Telekinesis", sk.MYSTICISM, 18, TARGET,
               [{"kind": "telekinesis", "magnitude": 1, "duration": 10}],
               "Grasp an object from afar.", element="magic"))
# Racial power spells (referenced by races.py)
register(Spell("sp_woad", "Woad", sk.ALTERATION, 0, SELF,
               [{"kind": "shield", "magnitude": 30, "duration": 30}], "Nord racial shield."))
register(Spell("sp_flameshield", "Ancestor's Wrath", sk.DESTRUCTION, 0, SELF,
               [{"kind": "fire_shield", "magnitude": 15, "duration": 20}], "Ashfolk flame cloak."))
register(Spell("sp_berserk", "Berserk", sk.RESTORATION, 0, SELF,
               [{"kind": "berserk", "magnitude": 30, "duration": 20}], "Orc rage."))
register(Spell("sp_adrenaline", "Adrenaline Rush", sk.RESTORATION, 0, SELF,
               [{"kind": "fortify_speed", "magnitude": 40, "duration": 20}], "Redguard surge."))
register(Spell("sp_restoremagicka", "Highborn", sk.MYSTICISM, 0, SELF,
               [{"kind": "restore_magicka", "magnitude": 100, "duration": 0}], "Highkin magicka burst."))
register(Spell("sp_histskin", "Histskin", sk.RESTORATION, 0, SELF,
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


def cast_success(character, spell: Spell, rng: Optional[random.Random] = None) -> bool:
    """Roll whether the cast succeeds (skill + willpower + luck vs difficulty)."""
    rng = rng or random
    if spell.base_cost <= 0:
        return True  # powers never fizzle
    skill = character.skill(spell.school)
    wil = character.attrs.get(attr.WILLPOWER, 40)
    luck = character.attrs.get(attr.LUCK, 40)
    chance = (skill * 1.2 + wil * 0.2 + luck * 0.1 - spell.base_cost * 0.4) / 100.0
    return rng.random() <= max(0.05, min(0.98, chance))


class CastResult:
    def __init__(self, cast=False, reason="", spell=None, magnitude=0.0):
        self.cast = cast
        self.reason = reason
        self.spell = spell
        self.magnitude = magnitude


def try_cast(character, spell_id: str, rng: Optional[random.Random] = None) -> CastResult:
    """Attempt to cast a known spell.

    Spends magicka, rolls success, and — for SELF spells — applies effects to the
    caster immediately. TARGET/PROJECTILE/TOUCH spells return a successful result
    for the caller (engine adapter) to deliver against a creature.
    """
    spell = get(spell_id)
    if spell is None:
        return CastResult(False, "unknown spell")
    if spell_id not in character.known_spells:
        return CastResult(False, "not known", spell)
    cost = cast_cost(character, spell)
    if not character.spend_magicka(cost):
        return CastResult(False, "not enough magicka", spell)
    if not cast_success(character, spell, rng):
        character.use_skill(spell.school, 1.0)
        return CastResult(False, "fizzle", spell)

    character.use_skill(spell.school, 1.0 + spell.base_cost / 40.0)

    if spell.delivery == SELF:
        apply_effects_to_character(character, spell.effects)
    mag = sum(float(e.get("magnitude", 0)) for e in spell.effects
              if e.get("kind", "").startswith("damage"))
    return CastResult(True, "", spell, mag)


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
        else:
            # buffs/utility (shield, night_eye, invisibility, feather, ...) just
            # live as timed effects the HUD/gameplay reads.
            character.add_effect(kind, mag, dur if dur > 0 else 1.0)
