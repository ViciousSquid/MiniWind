"""
The player character — the beating heart of the RPG.

A :class:`Character` owns everything that makes "you" you: attributes, skills
(which improve with use), the three derived pools (health / magicka / stamina),
level and level-up progress, gold, known spells, active magical effects, faction
standing, and equipment. It is engine-agnostic and fully serialisable, so the
Fio adapter just holds one on the play session and the stock save system stores
it as a blob in the KV store.

Progression model (learn-by-doing, in the tradition of many fantasy RPGs):

* **Skills improve by use.** ``use_skill(id, difficulty)`` grants skill XP; when
  it crosses the threshold the skill rises by a point. Raising a *major* skill
  also advances a hidden level-up counter.
* **Levels come from training major skills.** Every ten major-skill increases the
  character may :meth:`level_up`, which raises the two favoured attributes and a
  couple of the attributes governing the skills trained this level, and adds
  health from Endurance.
* **Derived pools** are recomputed from attributes whenever those change.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from . import attributes as attr
from . import skills as sk
from . import races
from . import classes as cls
from . import birthsigns

#: Major-skill increases needed to earn one character level.
SKILL_UPS_PER_LEVEL = 10


class Character:
    def __init__(self):
        # identity
        self.name = "Adventurer"
        self.race_id = "imperial"
        self.class_id = "warrior"
        self.birthsign_id = "none"
        self.gender = "male"

        # stats
        self.attrs: Dict[str, int] = attr.new_attribute_block()
        self.skills: Dict[str, int] = sk.new_skill_block(cls.MINOR_SKILL_START)
        self.major_skills: List[str] = []

        # derived pools (current / max)
        self.health = 100.0
        self.max_health = 100.0
        self.magicka = 100.0
        self.max_magicka = 100.0
        self.stamina = 100.0
        self.max_stamina = 100.0

        # progression
        self.level = 1
        self.xp_progress = 0            # major-skill-ups since last level
        self._skill_xp: Dict[str, float] = {}  # fractional XP per skill
        # per-level: how many skill-ups happened under each governing attribute
        self._level_attr_gains: Dict[str, int] = {a: 0 for a in attr.ATTRIBUTES}

        # wealth & gear
        self.gold = 25
        self.inventory: List[Dict] = []   # list of item-stack dicts
        self.equipment: Dict[str, Optional[str]] = {}  # slot -> item id
        self.known_spells: List[str] = []
        self.active_spell: Optional[str] = None
        self.active_weapon_kind = "unarmed"  # 'melee' | 'bow' | 'unarmed' | 'spell'
        #: Chosen head id (e.g. "head07") — the player's whole appearance and a
        #: future audio key. Set at character creation; no NPC reuses it.
        self.head = ""

        # live magical/combat effects: list of dicts
        # {"kind": "shield"|"fire"|..., "magnitude": x, "remaining": secs}
        self.effects: List[Dict] = []

        # faction standing: faction id -> {"rank": int, "reputation": int}
        self.factions: Dict[str, Dict] = {}
        self.bounty = 0        # crime bounty
        self.disposition_base = 40

        self.recompute_derived(reset_current=True)

    # ------------------------------------------------------------------ build
    @classmethod
    def create(cls_, name: str, race_id: str, class_id: str, birthsign_id: str = "none",
               gender: str = "male", custom_class: cls.CharClass = None) -> "Character":
        """Roll a fresh character from a race + class + birthsign."""
        c = cls_()
        c.name = name or "Adventurer"
        c.gender = gender
        race = races.get(race_id)
        klass = custom_class or cls.get(class_id)
        sign = birthsigns.get(birthsign_id)
        c.race_id = race.id
        c.class_id = klass.id
        c.birthsign_id = sign.id
        c.major_skills = list(klass.major_skills)

        # attributes: base + race + favoured-class + birthsign
        block = attr.new_attribute_block()
        block = attr.apply_bonuses(block, race.attr_bonuses)
        for fav in klass.favored_attrs:
            block[fav] = attr.clamp(block.get(fav, attr.BASE_ATTRIBUTE) + 10)
        block = attr.apply_bonuses(block, sign.attr_bonuses)
        c.attrs = block

        # skills: minors at 5, majors at 25, +5 to specialisation, + race bonuses
        skills = sk.new_skill_block(cls.MINOR_SKILL_START)
        for sid in klass.major_skills:
            skills[sid] = cls.MAJOR_SKILL_START
        for sid, sd in sk.SKILLS.items():
            if sd.spec == klass.specialisation:
                skills[sid] = min(100, skills[sid] + cls.SPECIALISATION_BONUS)
        for sid, delta in race.skill_bonuses.items():
            if sid in skills:
                skills[sid] = min(100, skills[sid] + int(delta))
        c.skills = skills

        # starting spells from race + birthsign + class
        for sp in (list(race.starting_spells) + list(sign.spells)
                   + list(getattr(klass, "starting_spells", []))):
            if sp not in c.known_spells:
                c.known_spells.append(sp)
        # Safety net: a spellcasting class (Mage, Sorcerer, Healer, Nightblade,
        # or a custom magic-specialised class) must never start with no spell.
        if klass.specialisation == sk.MAGIC and not c.known_spells:
            c.known_spells.append("flare")
        # Ready the first known spell so right-mouse can cast immediately.
        if c.known_spells and not c.active_spell:
            c.active_spell = c.known_spells[0]

        c.recompute_derived(reset_current=True)
        # birthsign flat pool bonuses (after recompute so they stick as bonuses)
        c._sign_stat_bonuses = dict(sign.stat_bonuses)
        c.recompute_derived(reset_current=True)
        return c

    # ------------------------------------------------------------ derived pools
    _sign_stat_bonuses: Dict[str, int] = {}

    def recompute_derived(self, reset_current: bool = False) -> None:
        a = self.attrs
        sign_bonus = getattr(self, "_sign_stat_bonuses", {}) or {}
        end = a.get(attr.ENDURANCE, 40)
        stg = a.get(attr.STRENGTH, 40)
        wil = a.get(attr.WILLPOWER, 40)
        agi = a.get(attr.AGILITY, 40)
        intel = a.get(attr.INTELLIGENCE, 40)

        # Health: endurance-driven, plus accumulated per-level gains.
        base_health = end * 2.0 + self._accum_health
        self.max_health = base_health + sign_bonus.get("health", 0)
        # Magicka: intelligence-driven (+ birthsign, which can be large).
        self.max_magicka = intel * 1.5 + sign_bonus.get("magicka", 0)
        # Stamina/fatigue: the "can I keep swinging/running" pool.
        self.max_stamina = (stg + wil + agi + end) * 0.5 + sign_bonus.get("stamina", 0)

        self.max_health = max(1.0, self.max_health)
        self.max_magicka = max(0.0, self.max_magicka)
        self.max_stamina = max(1.0, self.max_stamina)
        if reset_current:
            self.health = self.max_health
            self.magicka = self.max_magicka
            self.stamina = self.max_stamina
        else:
            self.health = min(self.health, self.max_health)
            self.magicka = min(self.magicka, self.max_magicka)
            self.stamina = min(self.stamina, self.max_stamina)

    #: health accumulated from levelling (added on top of endurance*2)
    _accum_health: float = 0.0

    @property
    def carry_capacity(self) -> float:
        """Maximum weight (encumbrance) before you're over-loaded."""
        return self.attrs.get(attr.STRENGTH, 40) * 5.0

    @property
    def is_overencumbered(self) -> bool:
        from . import inventory as inv
        return inv.total_weight(self.inventory) > self.carry_capacity

    # ----------------------------------------------------------- skill use / xp
    def skill(self, skill_id: str) -> int:
        return int(self.skills.get(skill_id, 0))

    def use_skill(self, skill_id: str, difficulty: float = 1.0) -> bool:
        """Record a use of *skill_id*; returns True if the skill levelled up.

        *difficulty* scales the XP gained (a tough lock, a strong foe → more).
        """
        if skill_id not in self.skills:
            return False
        cur = self.skills[skill_id]
        if cur >= 100:
            return False
        gain = sk.SKILL_XP_BASE * max(0.1, float(difficulty))
        # Luck gives a tiny universal bonus to learning.
        gain *= 1.0 + (self.attrs.get(attr.LUCK, 40) - 40) * 0.002
        self._skill_xp[skill_id] = self._skill_xp.get(skill_id, 0.0) + gain
        leveled = False
        while self._skill_xp[skill_id] >= sk.xp_to_raise(self.skills[skill_id]):
            self._skill_xp[skill_id] -= sk.xp_to_raise(self.skills[skill_id])
            self.skills[skill_id] += 1
            leveled = True
            self._on_skill_raised(skill_id)
            if self.skills[skill_id] >= 100:
                self._skill_xp[skill_id] = 0.0
                break
        return leveled

    def _on_skill_raised(self, skill_id: str) -> None:
        gov = sk.governing_attribute(skill_id)
        self._level_attr_gains[gov] = self._level_attr_gains.get(gov, 0) + 1
        # Athletics/heavy skills also nudge derived pools live.
        if skill_id in (sk.ATHLETICS,):
            self.max_stamina += 1
        if skill_id in self.major_skills:
            self.xp_progress += 1

    @property
    def can_level_up(self) -> bool:
        return self.xp_progress >= SKILL_UPS_PER_LEVEL

    def level_up(self, chosen_attrs: Optional[List[str]] = None) -> Dict:
        """Advance one character level.

        If *chosen_attrs* (up to 3) is given those attributes are raised;
        otherwise the two favoured attributes plus the most-trained attribute
        this level are chosen automatically. Returns a summary dict.
        """
        if self.xp_progress < SKILL_UPS_PER_LEVEL:
            # allow forced level-up too, but normally gated
            pass
        self.level += 1
        self.xp_progress = max(0, self.xp_progress - SKILL_UPS_PER_LEVEL)

        if not chosen_attrs:
            klass = cls.get(self.class_id)
            picks = list(klass.favored_attrs)
            # add the attribute with the most skill-ups this level
            ranked = sorted(attr.ATTRIBUTES,
                            key=lambda a: self._level_attr_gains.get(a, 0), reverse=True)
            for a in ranked:
                if a not in picks:
                    picks.append(a)
                if len(picks) >= 3:
                    break
            chosen_attrs = picks[:3]

        raised = {}
        for a in chosen_attrs:
            if a not in self.attrs:
                continue
            gains = self._level_attr_gains.get(a, 0)
            # multiplier 1..5 based on how much you trained governed skills
            mult = 1 + min(4, gains // 2)
            new_val = attr.clamp(self.attrs[a] + mult)
            raised[a] = new_val - self.attrs[a]
            self.attrs[a] = new_val

        # Health gain from endurance (classic: 10% of endurance per level).
        hp_gain = self.attrs.get(attr.ENDURANCE, 40) * 0.1
        self._accum_health += hp_gain
        self._level_attr_gains = {a: 0 for a in attr.ATTRIBUTES}
        self.recompute_derived(reset_current=False)
        self.health = self.max_health  # full heal on level up
        return {"level": self.level, "attrs_raised": raised, "health_gain": hp_gain}

    # --------------------------------------------------------------- pools help
    def damage(self, amount: float) -> float:
        amount = max(0.0, float(amount))
        self.health = max(0.0, self.health - amount)
        return self.health

    def heal(self, amount: float) -> None:
        self.health = min(self.max_health, self.health + max(0.0, float(amount)))

    def restore_magicka(self, amount: float) -> None:
        self.magicka = min(self.max_magicka, self.magicka + max(0.0, amount))

    def spend_magicka(self, amount: float) -> bool:
        if self.magicka + 1e-6 < amount:
            return False
        self.magicka -= amount
        return True

    def spend_stamina(self, amount: float) -> bool:
        self.stamina = max(0.0, self.stamina - max(0.0, amount))
        return True

    @property
    def is_dead(self) -> bool:
        return self.health <= 0.0

    def regen(self, dt: float) -> None:
        """Passive per-second regeneration (magicka & stamina; not health)."""
        if self.is_dead:
            return
        # Atronach sign: magicka does not regenerate.
        golem = self.birthsign_id == "golem"
        if not golem and self.max_magicka > 0:
            rate = self.max_magicka * 0.02 * (0.5 + self.attrs.get(attr.WILLPOWER, 40) / 100.0)
            self.restore_magicka(rate * dt)
        st_rate = self.max_stamina * 0.15
        self.stamina = min(self.max_stamina, self.stamina + st_rate * dt)

    # ------------------------------------------------------------------ effects
    def add_effect(self, kind: str, magnitude: float, duration: float) -> None:
        self.effects.append({"kind": kind, "magnitude": float(magnitude),
                             "remaining": float(duration)})

    def effect_magnitude(self, kind: str) -> float:
        return sum(e["magnitude"] for e in self.effects if e.get("kind") == kind)

    def tick_effects(self, dt: float) -> None:
        for e in self.effects:
            e["remaining"] -= dt
            k = e.get("kind")
            if k == "restore_health":
                self.heal(e["magnitude"] * dt)
            elif k == "damage_health":
                self.damage(e["magnitude"] * dt)
        self.effects = [e for e in self.effects if e["remaining"] > 0.0]

    # ----------------------------------------------------------- serialisation
    def to_dict(self) -> Dict:
        return {
            "name": self.name, "race": self.race_id, "class": self.class_id,
            "birthsign": self.birthsign_id, "gender": self.gender,
            "attrs": dict(self.attrs), "skills": dict(self.skills),
            "major_skills": list(self.major_skills),
            "health": round(self.health, 2), "max_health": round(self.max_health, 2),
            "magicka": round(self.magicka, 2), "stamina": round(self.stamina, 2),
            "level": self.level, "xp_progress": self.xp_progress,
            "skill_xp": dict(self._skill_xp),
            "level_attr_gains": dict(self._level_attr_gains),
            "accum_health": self._accum_health,
            "gold": self.gold, "inventory": list(self.inventory),
            "equipment": dict(self.equipment), "known_spells": list(self.known_spells),
            "active_spell": self.active_spell,
            "active_weapon_kind": self.active_weapon_kind,
            "head": self.head,
            "factions": dict(self.factions), "bounty": self.bounty,
            "sign_stat_bonuses": dict(getattr(self, "_sign_stat_bonuses", {})),
        }

    @classmethod
    def from_dict(cls_, data: Dict) -> "Character":
        c = cls_()
        if not data:
            return c
        c.name = data.get("name", c.name)
        c.race_id = data.get("race", c.race_id)
        c.class_id = data.get("class", c.class_id)
        c.birthsign_id = data.get("birthsign", c.birthsign_id)
        c.gender = data.get("gender", c.gender)
        if isinstance(data.get("attrs"), dict):
            c.attrs.update({k: int(v) for k, v in data["attrs"].items() if k in c.attrs})
        if isinstance(data.get("skills"), dict):
            c.skills.update({k: int(v) for k, v in data["skills"].items() if k in c.skills})
        c.major_skills = list(data.get("major_skills", c.major_skills))
        c._skill_xp = dict(data.get("skill_xp", {}))
        c._level_attr_gains = {a: int(data.get("level_attr_gains", {}).get(a, 0))
                               for a in attr.ATTRIBUTES}
        c._accum_health = float(data.get("accum_health", 0.0))
        c._sign_stat_bonuses = dict(data.get("sign_stat_bonuses", {}))
        c.level = int(data.get("level", 1))
        c.xp_progress = int(data.get("xp_progress", 0))
        c.gold = int(data.get("gold", 25))
        c.inventory = list(data.get("inventory", []))
        c.equipment = dict(data.get("equipment", {}))
        c.known_spells = list(data.get("known_spells", []))
        c.active_spell = data.get("active_spell")
        c.active_weapon_kind = data.get("active_weapon_kind", "unarmed")
        c.head = data.get("head", "")
        c.factions = dict(data.get("factions", {}))
        c.bounty = int(data.get("bounty", 0))
        c.recompute_derived(reset_current=False)
        c.health = float(data.get("health", c.max_health))
        c.magicka = float(data.get("magicka", c.max_magicka))
        c.stamina = float(data.get("stamina", c.max_stamina))
        return c
