"""
Trainers and tutors: paying someone who knows more than you to teach you.

Two services an NPC can offer, each read from its properties:

* **Skill training** (``trainer``): ``{"skills": ["occult", ...], "rank": 50}``
  -- the skills it teaches and its own skill in them, as a number or a rank's
  name (Novice 0, Apprentice 25, Journeyman 50, Expert 75, Master 100). One
  session raises one skill one point, for gold. A trainer cannot teach anyone
  past its own skill, and nobody trains more than :data:`SESSIONS_PER_LEVEL`
  times a character level -- the count starts again at each level-up. A point
  bought counts as a point earned (:meth:`Character.train_skill`): toward the
  governing attribute's level-up bonus and, for a major skill, the next level.
  Learning by doing is still the way to grow; a trainer only hurries it.
* **Spell tutoring** (``teaches_spells``): the spell ids it sells. A spell
  costs gold by its rarity (:data:`SPELL_PRICES`). A tutor of the Arcane
  Circle (``"guild": "mages"``) sells its rarer spells only to members of
  standing (:data:`SPELL_RANKS`), gives members a discount, and every spell
  or school lesson bought from the Circle earns reputation in it, so a
  member rises through its ranks by studying. An independent tutor -- a
  hedge-witch, a hermit -- asks no standing.

Who teaches in the shipped world is data, ``game/data/teachers.json``, keyed by
an NPC's stable ``name``; an NPC's own authored properties win over it.

A Warrior, who works no magic, is turned away from every tutor and from
training in the three schools. Prices are a merchant's: the session passes
its own price function in (Mercantile, Charisma and the NPC's disposition).

Pure Python: the session (game/runtime.py) owns the dialogue and the screens.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Dict, List, Optional

from . import guilds
from . import magic
from . import skills as sk

#: Training sessions a character may buy between one level-up and the next.
SESSIONS_PER_LEVEL = 5
#: Gold for one point of training, before the merchant's adjustments: a base
#: and this much per point the skill already has (so 25 at 5, 160 at 50).
TRAIN_PRICE_BASE = 10
TRAIN_PRICE_PER_POINT = 3
#: Gold for a spell, by rarity, before the merchant's adjustments. The rarest
#: are a fortune: a legendary spell is the work of a career, not a purse.
SPELL_PRICES = {"common": 40, "uncommon": 120, "rare": 450, "epic": 1500,
                "legendary": 5000}
#: The guild whose tutors ask standing, and the rank in it each rarity needs
#: (-1: anyone; 0: a member, an Associate; 2: a Journeyman; 4: a Conjurer).
ARCANE_CIRCLE = "mages"
SPELL_RANKS = {"common": -1, "uncommon": -1, "rare": 0, "epic": 2, "legendary": 4}
#: What the Circle's tutors take off a member's price.
MEMBER_DISCOUNT = 0.9
#: Reputation earned with the Circle for a spell bought from it, by rarity,
#: and for a lesson in one of the schools.
SPELL_REPUTATION = {"common": 2, "uncommon": 3, "rare": 4, "epic": 6, "legendary": 8}
LESSON_REPUTATION = 1

#: Why a lesson or a spell cannot be had (the reason codes the functions give).
REASONS = {
    "not_taught": "I don't teach that.",
    "warrior": "The arcane means nothing to a warrior. I can teach you nothing of it.",
    "beyond": "You know as much of it as I do. Find a greater master than me.",
    "sessions": "You have trained all you can for now. Go and use what you've "
                "learned; come back when you've grown.",
    "mastered": "There is nothing left to teach you. You are a master.",
    "gold": "You can't afford my teaching.",
    "known": "You already know that spell.",
    "unknown": "That spell is lost to me.",
    "standing": "The Circle teaches that only to its own, and only those of standing.",
}


# ---------------------------------------------------------------------------
# Who teaches in the world (game/data/teachers.json)
# ---------------------------------------------------------------------------
#: The world's teachers, by NPC ``name``: loaded on first use.
_TEACHERS: Optional[Dict[str, Dict]] = None


def _teachers_path() -> str:
    return os.path.join(os.path.dirname(__file__), "..", "data", "teachers.json")


def teachers() -> Dict[str, Dict]:
    """Every NPC the data file makes a teacher, by name (empty if the file
    is missing or unreadable)."""
    global _TEACHERS
    if _TEACHERS is None:
        try:
            with open(_teachers_path(), "r", encoding="utf-8") as fh:
                rows = json.load(fh)
        except (OSError, ValueError):
            rows = {}
        _TEACHERS = {str(k): dict(v) for k, v in (rows or {}).items()
                     if not str(k).startswith("_") and isinstance(v, dict)}
    return _TEACHERS


def _field(props: Dict, key: str):
    """*props*' own *key*, else its entry in the world's teachers. Read live,
    so an NPC streamed in later (Big World) teaches like any other."""
    props = props or {}
    if props.get(key) not in (None, "", []):
        return props.get(key)
    return teachers().get(str(props.get("name", "")), {}).get(key)


def _ids(value) -> List[str]:
    """A list of ids from a list, or from the editor's comma-separated text."""
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    return [str(v).strip() for v in (value or ()) if str(v).strip()]


# ---------------------------------------------------------------------------
# What an NPC offers
# ---------------------------------------------------------------------------
def trainer_of(props: Dict) -> Optional[Dict]:
    """*props*' training, ``{"skills": [...], "rank": int}``, or None if it
    trains nobody. Old school names fold into their successors."""
    t = _field(props, "trainer")
    if not isinstance(t, dict) and str((props or {}).get("trainer_skills", "")).strip():
        # The editor's flat fields: "occult, defensive" and a rank's name.
        t = {"skills": _ids((props or {}).get("trainer_skills")),
             "rank": (props or {}).get("trainer_rank", 50)}
    if not isinstance(t, dict):
        return None
    skills = []
    for skill_id in _ids(t.get("skills", t.get("skill", []))):
        skill_id = sk.fold(str(skill_id).strip().lower())
        if skill_id in sk.SKILLS and skill_id not in skills:
            skills.append(skill_id)
    if not skills:
        return None
    return {"skills": skills, "rank": sk.rank_level(t.get("rank", 50))}


def spells_taught(props: Dict) -> List[magic.Spell]:
    """The spells *props* sells, in the order authored: real spells only, no
    racial powers."""
    out = []
    for sid in _ids(_field(props, "teaches_spells")):
        spell = magic.get(str(sid))
        if spell is not None and spell.base_cost > 0 and spell not in out:
            out.append(spell)
    return out


def is_trainer(props: Dict) -> bool:
    return trainer_of(props) is not None


def is_tutor(props: Dict) -> bool:
    return bool(spells_taught(props))


def guild_of(props: Dict) -> str:
    """The guild *props* teaches for ("" when independent)."""
    return str(_field(props, "guild") or "").strip().lower()


def _works_magic(character) -> bool:
    try:
        return bool(character.can_use_magic())
    except Exception:
        return True


# ---------------------------------------------------------------------------
# Skill training
# ---------------------------------------------------------------------------
def sessions_left(character) -> int:
    return max(0, SESSIONS_PER_LEVEL - int(getattr(character, "trained_this_level", 0)))


def lesson_price(character, skill_id: str) -> int:
    """Gold for the next point of *skill_id*, before the merchant's adjustments."""
    return TRAIN_PRICE_BASE + TRAIN_PRICE_PER_POINT * int(character.skill(skill_id))


def can_train(character, props: Dict, skill_id: str, price: Optional[int] = None) -> str:
    """Why *character* cannot train *skill_id* with *props* now, or "" when
    they can (and, given its *price*, afford it)."""
    t = trainer_of(props)
    skill_id = sk.fold(skill_id)
    if t is None or skill_id not in t["skills"]:
        return "not_taught"
    if skill_id in sk.SCHOOLS and not _works_magic(character):
        return "warrior"
    level = int(character.skill(skill_id))
    if level >= 100:
        return "mastered"
    if level >= t["rank"]:
        return "beyond"
    if sessions_left(character) <= 0:
        return "sessions"
    if price is not None and int(character.gold) < int(price):
        return "gold"
    return ""


def train(character, props: Dict, skill_id: str,
          price_of: Callable[[int], int] = int) -> Dict:
    """Buy one session: *character* pays ``price_of(lesson_price)`` and
    *skill_id* rises one point. Returns ``{"ok", "reason", "skill", "level",
    "price", "promoted"}``."""
    skill_id = sk.fold(skill_id)
    price = int(price_of(lesson_price(character, skill_id))) if skill_id in sk.SKILLS else 0
    reason = can_train(character, props, skill_id, price)
    out = {"ok": False, "reason": reason, "skill": skill_id, "price": price,
           "level": int(character.skill(skill_id)) if skill_id in sk.SKILLS else 0,
           "promoted": False}
    if reason:
        return out
    character.gold -= price
    character.train_skill(skill_id)
    character.trained_this_level = int(getattr(character, "trained_this_level", 0)) + 1
    if skill_id in sk.SCHOOLS and guild_of(props) == ARCANE_CIRCLE \
            and guilds.is_member(character, ARCANE_CIRCLE):
        out["promoted"] = guilds.add_reputation(
            character, ARCANE_CIRCLE, LESSON_REPUTATION)["promoted"]
    out.update(ok=True, level=int(character.skill(skill_id)))
    return out


# ---------------------------------------------------------------------------
# Spell tutoring
# ---------------------------------------------------------------------------
def spell_price(character, props: Dict, spell: magic.Spell) -> int:
    """Gold for *spell* from *props*, before the merchant's adjustments: by
    rarity, less the Circle's discount for its members."""
    price = SPELL_PRICES.get(spell.rarity, SPELL_PRICES["common"])
    if guild_of(props) == ARCANE_CIRCLE and guilds.is_member(character, ARCANE_CIRCLE):
        price = int(round(price * MEMBER_DISCOUNT))
    return price


def rank_needed(props: Dict, spell: magic.Spell) -> int:
    """The Arcane Circle rank *props* asks before selling *spell* (-1: none)."""
    if guild_of(props) != ARCANE_CIRCLE:
        return -1
    return SPELL_RANKS.get(spell.rarity, -1)


def can_learn(character, props: Dict, spell_id: str, price: Optional[int] = None) -> str:
    """Why *character* cannot buy *spell_id* from *props* now, or ""."""
    spell = magic.get(str(spell_id))
    if spell is None:
        return "unknown"
    if spell not in spells_taught(props):
        return "not_taught"
    if not _works_magic(character):
        return "warrior"
    if spell.id in character.known_spells:
        return "known"
    need = rank_needed(props, spell)
    if need >= 0 and (not guilds.is_member(character, ARCANE_CIRCLE)
                      or guilds.rank(character, ARCANE_CIRCLE) < need):
        return "standing"
    if price is not None and int(character.gold) < int(price):
        return "gold"
    return ""


def learn(character, props: Dict, spell_id: str,
          price_of: Callable[[int], int] = int) -> Dict:
    """Buy *spell_id* from *props*: *character* pays and knows it. Returns
    ``{"ok", "reason", "spell", "price", "promoted"}``."""
    spell = magic.get(str(spell_id))
    price = int(price_of(spell_price(character, props, spell))) if spell is not None else 0
    reason = can_learn(character, props, spell_id, price)
    out = {"ok": False, "reason": reason, "spell": spell, "price": price,
           "promoted": False}
    if reason:
        return out
    character.gold -= price
    character.known_spells.append(spell.id)
    if not character.active_spell:
        character.active_spell = spell.id
    if guild_of(props) == ARCANE_CIRCLE and guilds.is_member(character, ARCANE_CIRCLE):
        out["promoted"] = guilds.add_reputation(
            character, ARCANE_CIRCLE, SPELL_REPUTATION.get(spell.rarity, 2))["promoted"]
    out["ok"] = True
    return out


def standing_note(props: Dict, spell: magic.Spell) -> str:
    """What the spell list says of a spell's standing ("" when none is asked):
    "Circle: Journeyman"."""
    need = rank_needed(props, spell)
    if need < 0:
        return ""
    g = guilds.get(ARCANE_CIRCLE)
    return f"Circle: {g.rank_title(need) if g else need}"


def explain(reason: str) -> str:
    return REASONS.get(reason, "")
