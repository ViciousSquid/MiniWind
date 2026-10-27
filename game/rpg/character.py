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
* **Levels come from training major skills, or from experience.** Every ten
  major-skill increases -- or :func:`xp_to_next` experience points, earned by
  kills and quests (:meth:`add_xp`) -- the character may :meth:`level_up`,
  which raises the two favoured attributes and a couple of the attributes
  governing the skills trained this level, and adds health from Endurance.
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
#: The three pools a level-up could grow (the older, pool-based level-up).
LEVEL_POOLS = ("health", "magicka", "stamina")
#: Stamina a second of sprinting costs (a fresh 100 lasts about eight seconds).
SPRINT_STAMINA_PER_SECOND = 12.0
#: How much the chosen pool grows per level.
LEVEL_POOL_GAIN = 10.0
#: The level-up choice: which attribute grows, by :data:`LEVEL_ATTR_GAIN`.
#: MAGICKA is the well of magic -- Intelligence underneath, which sets
#: maximum magicka -- and is only offered to those who work magic.
LEVEL_CHOICES = {"strength": attr.STRENGTH, "endurance": attr.ENDURANCE,
                 "charisma": attr.PERSONALITY, "magicka": attr.INTELLIGENCE}
LEVEL_ATTR_GAIN = 5
#: How many quick-weapon slots there are (keys 1-4).
QUICK_WEAPON_SLOTS = 4
#: Experience points (kills, quests) per level: level L needs L times this.
XP_PER_LEVEL = 100


def xp_to_next(level: int) -> int:
    """Experience points needed to go from *level* to the next one."""
    return XP_PER_LEVEL * max(1, int(level))


class Character:
    def __init__(self):
        # identity
        self.name = "Adventurer"
        self.race_id = "imperial"
        self.class_id = "warrior"
        self.birthsign_id = "none"
        self.gender = "male"
        #: "right" or "left" — the hand that wields the weapon, so the overhead
        #: weapon sprite is drawn on the correct side (chosen at creation).
        self.handed = "right"

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
        self.xp = 0                     # experience points toward the next level
        self._skill_xp: Dict[str, float] = {}  # fractional XP per skill
        # per-level: how many skill-ups happened under each governing attribute
        self._level_attr_gains: Dict[str, int] = {a: 0 for a in attr.ATTRIBUTES}
        #: Skill rises not yet announced, as (skill id, new value). Transient:
        #: the play session drains it (:meth:`pop_skill_raises`) and shows each
        #: as "Destruction increased to 12", so practice is visible.
        self._skill_raises: List = []
        #: Successful casts per spell id. Practice with one spell makes it
        #: steadier on top of the school skill (see magic.cast_chance).
        self.spell_practice: Dict[str, int] = {}
        #: The level the player has raised each known spell to (1 if absent);
        #: raised by spending experience (:meth:`upgrade_spell`).
        self.spell_levels: Dict[str, int] = {}
        #: The 3d6 totals rolled at creation ({"strength", "endurance",
        #: "personality"}), which write the character's bio (game.rpg.bios).
        self.rolls: Dict[str, int] = {}
        #: The four quick-weapon slots (Baldur's Gate's "Quick Weapons"): an
        #: item id or None each. Keys 1-4 draw the weapon in that slot; the
        #: inventory window fills them by drag and drop.
        self.quick_weapons: List[Optional[str]] = [None] * QUICK_WEAPON_SLOTS
        #: Books read (item ids): a skill book teaches only the first time.
        self.read_books: List[str] = []
        #: Weapon ids the slots have already been offered (transient). A weapon
        #: picked up for the first time drops into a free slot by itself; one
        #: the player has taken out of the slots stays out.
        self._quick_seen = set()
        #: The inventory strip along the bottom of the screen: an item id or
        #: None per slot, as long as the strip is wide. The ids are carried
        #: stacks, like the quick slots: the strip shows them, it holds nothing.
        #: A weapon carried twice is in two slots, one per copy.
        self.strip: List[Optional[str]] = []
        #: Item ids the strip has already been offered (transient), so a thing
        #: picked up for the first time takes a free slot by itself while one
        #: the player dragged out of the strip stays out.
        self._strip_seen = set()
        #: How many copies of each the strip has offered a slot (transient).
        self._strip_offered = {}

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
    def can_use_magic(self) -> bool:
        return cls.can_use_magic(self)

    @classmethod
    def create(cls_, name: str, race_id: str, class_id: str, birthsign_id: str = "none",
               gender: str = "male", custom_class: cls.CharClass = None) -> "Character":
        """Roll a fresh character from a race + class + birthsign."""
        c = cls_()
        c.name = (name[:1].upper() + name[1:]) if name else "Adventurer"
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

        # starting spells from race + birthsign + class (none for a class
        # that works no magic: a Warrior)
        for sp in ((list(race.starting_spells) + list(sign.spells)
                    + list(getattr(klass, "starting_spells", [])))
                   if getattr(klass, "magic", True) else []):
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
        intel = a.get(attr.INTELLIGENCE, 40)

        # Health: endurance-driven, plus accumulated per-level gains.
        base_health = end * 2.0 + self._accum_health
        self.max_health = base_health + sign_bonus.get("health", 0)
        # Magicka: intelligence-driven (+ birthsign, which can be large), plus
        # whatever levels were spent on it.
        self.max_magicka = (intel * 1.5 + self._accum_magicka
                            + sign_bonus.get("magicka", 0))
        # Stamina/fatigue: the "can I keep swinging/running" pool.
        self.max_stamina = ((stg + end * 3) * 0.5 + self._accum_stamina
                            + sign_bonus.get("stamina", 0))

        self.max_health = max(1.0, self.max_health)
        self.max_magicka = max(0.0, self.max_magicka)
        if not self.can_use_magic():
            # A Warrior has no magicka and no spells, whatever the birthsign.
            self.max_magicka = 0.0
            self.magicka = 0.0
            self.known_spells = []
            self.active_spell = None
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
    #: magicka and stamina chosen at level-ups (added on top of the attributes)
    _accum_magicka: float = 0.0
    _accum_stamina: float = 0.0

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
        self._skill_raises.append((skill_id, int(self.skills.get(skill_id, 0))))
        if len(self._skill_raises) > 16:
            del self._skill_raises[:-16]
        gov = sk.governing_attribute(skill_id)
        self._level_attr_gains[gov] = self._level_attr_gains.get(gov, 0) + 1
        # Athletics/heavy skills also nudge derived pools live.
        if skill_id in (sk.ATHLETICS,):
            self.max_stamina += 1
        if skill_id in self.major_skills:
            self.xp_progress += 1

    def pop_skill_raises(self) -> List:
        """The skill rises since the last call, oldest first, and forget them."""
        out = list(self._skill_raises)
        self._skill_raises.clear()
        return out

    def spell_level(self, spell_id: str) -> int:
        return int(self.spell_levels.get(str(spell_id), 1))

    def spell_upgrade_cost(self, spell_id: str) -> int:
        """Experience to raise *spell_id* one level (0 when it cannot rise)."""
        from . import magic
        spell = magic.get(spell_id)
        if spell is None or spell_id not in self.known_spells:
            return 0
        return spell.xp_to_level(self.spell_level(spell_id))

    def upgrade_spell(self, spell_id: str) -> bool:
        """Spend experience to raise a known spell one level. The same pool
        pays for character levels, so it is a real choice."""
        cost = self.spell_upgrade_cost(spell_id)
        if cost <= 0 or self.xp < cost:
            return False
        self.xp -= cost
        self.spell_levels[str(spell_id)] = self.spell_level(spell_id) + 1
        return True

    def add_xp(self, amount) -> int:
        """Earn *amount* experience points (kills, quests); returns it."""
        amount = max(0, int(amount or 0))
        self.xp += amount
        return amount

    @property
    def xp_needed(self) -> int:
        """Experience points needed for the next level."""
        return xp_to_next(self.level)

    @property
    def can_level_up(self) -> bool:
        """Either track full: ten major-skill increases, or enough experience."""
        return (self.xp_progress >= SKILL_UPS_PER_LEVEL
                or self.xp >= self.xp_needed)

    def level_choices(self) -> List[str]:
        """What this character may grow at a level-up: STRENGTH, ENDURANCE,
        CHARISMA and, for anyone who works magic, MAGICKA."""
        out = ["strength", "endurance", "charisma"]
        if self.can_use_magic():
            out.append("magicka")
        return out

    def level_up(self, chosen_attrs: Optional[List[str]] = None,
                 pool: Optional[str] = None, choice: Optional[str] = None) -> Dict:
        """Advance one character level.

        *choice* is the level-up screen's question: ``"strength"``,
        ``"endurance"``, ``"charisma"`` or ``"magicka"`` grows by :data:`LEVEL_ATTR_GAIN`
        (see :data:`LEVEL_CHOICES`), and health grows by a tenth of Endurance
        as every level. A *choice* the character may not make (MAGICKA for a
        Warrior) is ignored.

        *pool* is the older pool choice: ``"health"``, ``"magicka"`` or
        ``"stamina"`` grows by :data:`LEVEL_POOL_GAIN`. Attributes still rise
        as well, from what was actually trained: if
        *chosen_attrs* (up to 3) is given those are raised; otherwise the two
        favoured attributes plus the most-trained attribute this level. With no
        *pool* the old Endurance-based health gain applies. Returns a summary.
        """
        # The level is paid for by whichever track is full -- the skill
        # training first -- and the other keeps its progress. (A forced
        # level-up with neither full spends nothing.)
        if self.xp_progress >= SKILL_UPS_PER_LEVEL:
            self.xp_progress -= SKILL_UPS_PER_LEVEL
        elif self.xp >= self.xp_needed:
            self.xp -= self.xp_needed
        self.level += 1

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

        choice = str(choice or "").lower()
        choice_gain = 0
        if choice in self.level_choices():
            a = LEVEL_CHOICES[choice]
            new_val = attr.clamp(self.attrs[a] + LEVEL_ATTR_GAIN)
            choice_gain = new_val - self.attrs[a]
            raised[a] = raised.get(a, 0) + choice_gain
            self.attrs[a] = new_val
        else:
            choice = ""

        pool = str(pool or "").lower()
        gains = {"health": 0.0, "magicka": 0.0, "stamina": 0.0}
        if pool in LEVEL_POOLS:
            gains[pool] = LEVEL_POOL_GAIN
        else:
            # Health gain from endurance (classic: 10% of endurance per level).
            gains["health"] = self.attrs.get(attr.ENDURANCE, 40) * 0.1
        self._accum_health += gains["health"]
        self._accum_magicka += gains["magicka"]
        self._accum_stamina += gains["stamina"]
        self._level_attr_gains = {a: 0 for a in attr.ATTRIBUTES}
        self.recompute_derived(reset_current=False)
        # A level-up restores you fully.
        self.health = self.max_health
        self.magicka = self.max_magicka
        self.stamina = self.max_stamina
        return {"level": self.level, "attrs_raised": raised,
                "health_gain": gains["health"], "pool": pool if pool in LEVEL_POOLS else "",
                "pool_gain": gains.get(pool, 0.0) if pool in LEVEL_POOLS else 0.0,
                "choice": choice, "choice_gain": choice_gain}

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

    def regen(self, dt: float, sprinting: bool = False) -> None:
        """Passive per-second regeneration (magicka & stamina; not health).
        Sprinting spends stamina (:data:`SPRINT_STAMINA_PER_SECOND`) instead
        of regaining it."""
        if self.is_dead:
            return
        # Atronach sign: magicka does not regenerate.
        golem = self.birthsign_id == "golem"
        if not golem and self.max_magicka > 0:
            rate = self.max_magicka * 0.02 * (0.5 + self.attrs.get(attr.ENDURANCE, 40) / 100.0)
            self.restore_magicka(rate * dt)
        if sprinting:
            self.spend_stamina(SPRINT_STAMINA_PER_SECOND * dt)
            return
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
            "handed": self.handed,
            "attrs": dict(self.attrs), "skills": dict(self.skills),
            "major_skills": list(self.major_skills),
            "health": round(self.health, 2), "max_health": round(self.max_health, 2),
            "magicka": round(self.magicka, 2), "stamina": round(self.stamina, 2),
            "level": self.level, "xp_progress": self.xp_progress, "xp": self.xp,
            "skill_xp": dict(self._skill_xp),
            "level_attr_gains": dict(self._level_attr_gains),
            "accum_health": self._accum_health,
            "accum_magicka": self._accum_magicka,
            "accum_stamina": self._accum_stamina,
            "gold": self.gold, "inventory": list(self.inventory),
            "equipment": dict(self.equipment), "known_spells": list(self.known_spells),
            "active_spell": self.active_spell,
            "active_weapon_kind": self.active_weapon_kind,
            "head": self.head,
            "factions": dict(self.factions), "bounty": self.bounty,
            "sign_stat_bonuses": dict(getattr(self, "_sign_stat_bonuses", {})),
            "spell_practice": dict(self.spell_practice),
            "spell_levels": dict(self.spell_levels),
            "quick_weapons": list(self.quick_weapons),
            "strip": list(self.strip),
            "rolls": dict(self.rolls),
            "read_books": list(self.read_books),
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
        c.handed = "left" if str(data.get("handed", c.handed)).lower() == "left" else "right"
        if isinstance(data.get("attrs"), dict):
            c.attrs.update({k: int(v) for k, v in data["attrs"].items() if k in c.attrs})
        if isinstance(data.get("skills"), dict):
            # An old save's six magic schools fold into the two, keeping the best.
            loaded = {}
            for k, v in data["skills"].items():
                k = sk.fold(k)
                loaded[k] = max(loaded.get(k, 0), int(v))
            c.skills.update({k: v for k, v in loaded.items() if k in c.skills})
        majors = []
        for s in data.get("major_skills", c.major_skills):
            s = sk.fold(s)
            if s not in majors:
                majors.append(s)
        c.major_skills = majors
        c._skill_xp = {}
        for k, v in dict(data.get("skill_xp", {})).items():
            k = sk.fold(k)
            c._skill_xp[k] = max(c._skill_xp.get(k, 0.0), float(v))
        c._level_attr_gains = {a: int(data.get("level_attr_gains", {}).get(a, 0))
                               for a in attr.ATTRIBUTES}
        c._accum_health = float(data.get("accum_health", 0.0))
        c._accum_magicka = float(data.get("accum_magicka", 0.0))
        c._accum_stamina = float(data.get("accum_stamina", 0.0))
        c._sign_stat_bonuses = dict(data.get("sign_stat_bonuses", {}))
        c.level = int(data.get("level", 1))
        c.xp_progress = int(data.get("xp_progress", 0))
        c.xp = int(data.get("xp", 0))
        c.gold = int(data.get("gold", 25))
        c.inventory = list(data.get("inventory", []))
        c.equipment = dict(data.get("equipment", {}))
        c.known_spells = list(data.get("known_spells", []))
        c.active_spell = data.get("active_spell")
        c.active_weapon_kind = data.get("active_weapon_kind", "unarmed")
        c.head = data.get("head", "")
        c.factions = dict(data.get("factions", {}))
        c.bounty = int(data.get("bounty", 0))
        if isinstance(data.get("read_books"), list):
            c.read_books = [str(b) for b in data["read_books"]]
        if isinstance(data.get("rolls"), dict):
            c.rolls = {str(k): int(v) for k, v in data["rolls"].items()}
        quick = data.get("quick_weapons")
        if isinstance(quick, list):
            quick = [str(q) if q else None for q in quick[:QUICK_WEAPON_SLOTS]]
            c.quick_weapons = quick + [None] * (QUICK_WEAPON_SLOTS - len(quick))
            # Whatever was carried when saved has been offered already.
            c._quick_seen = {str(s.get("id")) for s in c.inventory
                             if isinstance(s, dict) and s.get("id")}
        strip = data.get("strip")
        if isinstance(strip, list):
            c.strip = [str(q) if q else None for q in strip]
            c._strip_seen = {str(s.get("id")) for s in c.inventory
                             if isinstance(s, dict) and s.get("id")}
            # Every copy carried (a weapon takes a slot per copy) was offered.
            c._strip_offered = {str(s.get("id")): int(s.get("qty", 1) or 1)
                                for s in c.inventory
                                if isinstance(s, dict) and s.get("id")}
        practice = data.get("spell_practice")
        if isinstance(practice, dict):
            c.spell_practice = {str(k): int(v) for k, v in practice.items()}
        levels = data.get("spell_levels")
        if isinstance(levels, dict):
            c.spell_levels = {str(k): max(1, int(v)) for k, v in levels.items()}
        c.recompute_derived(reset_current=False)
        c.health = float(data.get("health", c.max_health))
        c.magicka = float(data.get("magicka", c.max_magicka))
        c.stamina = float(data.get("stamina", c.max_stamina))
        return c
