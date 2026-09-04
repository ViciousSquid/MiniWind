"""
GameState — the player-facing controller that ties the RPG systems together.

The Fio session (`runtime.MiniwindSession`) owns one of these. It holds the
:class:`~game.rpg.character.Character`, a :class:`quests.QuestLog`
bound to the persistent store, and provides the high-level *verbs* the HUD/input
layer calls: pick up an item, use a potion, equip gear, cast the active spell,
reward a finished quest, and award kill XP + loot. Combat maths live in
:mod:`combat`/:mod:`magic`; this is the orchestration.
"""

from __future__ import annotations

import json
import random
from html import escape
from typing import Dict, List, Optional

try:
    from editor.debug_console import debug_log
except ImportError:
    def debug_log(_category, _message):
        pass

from . import items
from . import inventory as inv
from . import equipment as eq
from . import combat
from . import magic
from . import loot as loot_mod
from . import quests
from . import quests_content
from . import guilds
from . import bestiary
from .character import Character
from ..diceroll import DiceRoller

try:  # engine.gore is a tiny, Qt-free rule module; guard for non-engine contexts
    from engine import gore as _gore
except Exception:  # pragma: no cover
    _gore = None


def _mark_gibbed(props, damage, new_health) -> bool:
    """Flag *props* as gibbed on an overkill death, delegating to engine.gore.

    The single game-side entry point for the gib rule (an oversized killing blow
    switches the corpse to the gore sprite). Import-guarded so the RPG core still
    runs where engine.gore is unavailable — then it marks nothing and returns
    False."""
    if _gore is None:
        return False
    return _gore.mark_gibbed(props, damage, new_health)


#: Starting gear by class specialisation, granted at character creation.
STARTER_KITS = {
    "Combat": [("iron_longsword", 1), ("iron_shield", 1), ("leather_cuirass", 1),
               ("short_bow", 1), ("iron_arrow", 20), ("potion_heal_minor", 2)],
    "Magic": [("iron_dagger", 1), ("apprentice_staff", 1), ("potion_magicka", 2),
              ("potion_heal_minor", 1)],
    "Stealth": [("iron_shortsword", 1), ("hunting_bow", 1), ("iron_arrow", 15),
                ("leather_cuirass", 1), ("lockpick", 5), ("potion_heal_minor", 1)],
}


class GameState:
    def __init__(self, store, character: Optional[Character] = None,
                 rng: Optional[random.Random] = None):
        quests_content.load()
        self.store = store
        self.character = character or Character()
        self.quests = quests.QuestLog(store)
        self.rng = rng or random.Random()
        self.dice = DiceRoller(rng=self.rng)
        self.log: List[str] = []          # recent game messages (for the HUD log)
        self.sneaking = False

    # ------------------------------------------------------------------ setup
    @classmethod
    def new_game(cls, store, name, race_id, class_id, birthsign_id="none",
                 gender="male", custom_class=None, rng=None, head="") -> "GameState":
        char = Character.create(name, race_id, class_id, birthsign_id, gender, custom_class)
        if head:
            from . import heads
            char.head = heads.normalise(head)
        gs = cls(store, char, rng)
        gs.grant_starter_kit()
        return gs

    def grant_starter_kit(self) -> None:
        from . import classes as cls
        klass = cls.get(self.character.class_id)
        for iid, qty in STARTER_KITS.get(klass.specialisation, STARTER_KITS["Combat"]):
            stack = items.make(iid, qty)
            if stack:
                inv.add_item(self.character.inventory, stack)
        # auto-equip the best obvious pieces
        for iid, _ in STARTER_KITS.get(klass.specialisation, []):
            d = items.get(iid)
            if d and d.category in (items.WEAPON, items.ARMOUR, items.AMMO):
                if d.category == items.WEAPON and eq.weapon(self.character) is None:
                    eq.equip(self.character, iid)
                elif d.category == items.ARMOUR and eq.equipped_id(self.character, d.get("slot")) is None:
                    eq.equip(self.character, iid)
                elif d.category == items.AMMO and eq.ammo(self.character) is None:
                    eq.equip(self.character, iid)

    def message(self, text: str) -> None:
        self.log.append(text)
        if len(self.log) > 40:
            self.log = self.log[-40:]

    # -------------------------------------------------------------- inventory
    def pick_up(self, item_id: str, qty: int = 1) -> bool:
        stack = items.make(item_id, qty)
        if not stack:
            # unknown id: still store a bare stack so nothing is lost
            stack = inv.make_item(item_id, qty=qty)
        inv.add_item(self.character.inventory, stack)
        self.message(f"Picked up {stack.get('name', item_id)}"
                     + (f" ({qty})" if qty > 1 else ""))
        return True

    def add_gold(self, amount: int) -> None:
        self.character.gold += int(amount)
        if amount:
            self.message(f"{'Gained' if amount>0 else 'Lost'} {abs(int(amount))} gold")

    def use_item(self, item_id: str) -> bool:
        """Use/consume or equip an item from the inventory."""
        d = items.get(item_id)
        if d is None:
            return False
        if d.category == items.POTION:
            if inv.remove_item(self.character.inventory, item_id, 1) <= 0:
                return False
            magic.apply_effects_to_character(self.character, d.get("effects", []))
            self.message(f"Drank {d.name}")
            return True
        if d.category == items.BOOK:
            skill_id = d.get("teaches_skill")
            if skill_id:
                self.character.use_skill(skill_id, 5.0)
                self.message(f"You study {d.name}.")
            else:
                self.message(f"You read {d.name}.")
            return True
        if d.category in (items.WEAPON, items.ARMOUR, items.AMMO):
            return self.equip(item_id)
        return False

    def equip(self, item_id: str) -> bool:
        if eq.equip(self.character, item_id):
            self.message(f"Equipped {items.get(item_id).name}")
            return True
        return False

    def unequip(self, slot: str) -> bool:
        return eq.unequip(self.character, slot)

    def drop(self, item_id: str, qty: int = 1) -> int:
        return inv.remove_item(self.character.inventory, item_id, qty)

    def add_roll_listener(self, listener) -> None:
        """Subscribe to every dice result produced by this game state."""
        self.dice.add_roll_listener(listener)

    def remove_roll_listener(self, listener) -> None:
        """Remove a game-state dice result listener."""
        self.dice.remove_roll_listener(listener)

    def request_roll(self, dice_notation: str, target: Optional[int] = None,
                     source: str = "gameplay", context: Optional[Dict] = None) -> Dict:
        """Request a roll from the session-owned dice service."""
        result = self.dice.request_roll(dice_notation, target=target,
                                         source=source, context=context)
        details = ", ".join(str(value) for value in result["roll_details"])
        self.message(f"{result['dice_notation']}: {result['roll_result']} [{details}]")
        return result

    def roll_for_event(self, dice_notation: str, target: Optional[int] = None,
                       event: str = "gameplay", context: Optional[Dict] = None) -> Dict:
        """Roll for a named gameplay event and return the complete result."""
        return self.request_roll(dice_notation, target=target, source=event,
                                  context=context)

    def roll_for_quest(self, qid: str, dice_notation: Optional[str] = None,
                       target: Optional[int] = None) -> Dict:
        """Roll for an active quest and persist the result for its stage."""
        if not self.quests.is_active(qid):
            raise ValueError(f"Quest is not active: {qid}")
        stage_index = self.quests.stage_of(qid)
        quest = quests.get(qid)
        stage = quest.stage(stage_index) if quest is not None else None
        if stage is None or stage.condition_kind() != quests.COND_ROLL:
            raise ValueError(f"Quest stage is not a dice objective: {qid}:{stage_index}")
        notation = dice_notation or stage.condition_notation()
        if target is None and stage is not None:
            target = stage.condition_target_value()
        result = self.request_roll(notation, target=target,
                                   source=f"quest:{qid}",
                                   context={"quest_id": str(qid), "stage": stage_index})
        self.quests.record_roll(qid, stage_index, result)
        return result

    def roll_dice(self, dice_notation: str, target: Optional[int] = None) -> Dict:
        """Roll a tabletop expression through the session-owned dice service."""
        return self.request_roll(dice_notation, target=target, source="hud")

    # ----------------------------------------------------------------- combat
    def select_next_spell(self) -> Optional[str]:
        known = self.character.known_spells
        if not known:
            return None
        cur = self.character.active_spell
        if cur in known:
            i = (known.index(cur) + 1) % len(known)
        else:
            i = 0
        self.character.active_spell = known[i]
        return self.character.active_spell

    def attack_creature(self, target_props: Dict, distance: float = 0.0,
                        draw: float = 1.0, guaranteed: bool = False) -> Dict:
        """Resolve a melee attack on a creature. Returns the combat result.

        Spends stamina, applies damage to the target's ``health`` property,
        trains the weapon skill and handles the kill (XP + loot) if it dies.

        ``guaranteed`` forces a melee swing to connect (see
        :func:`combat.player_attack`) — set by the caller once it has already
        confirmed the target is in range and faced.

        Bow shots go through :meth:`fire_arrow` / :meth:`resolve_arrow_hit`
        instead, since a real flying arrow's damage is resolved when it
        physically lands, not the instant the string is released.
        """
        char = self.character
        res = combat.player_attack(char, target_props, sneaking=self.sneaking,
                                   draw=draw, rng=self.rng, dice=self.dice,
                                   guaranteed_hit=guaranteed)
        if res.get("no_ammo"):
            self.message("Out of arrows!")
            return res
        char.spend_stamina(6.0)
        return self._apply_hit(target_props, res)

    def fire_arrow(self, draw: float = 1.0) -> bool:
        """Loose a nocked arrow right now: spends stamina and consumes the
        arrow from inventory. Returns False (and messages "Out of arrows!")
        if there's nothing nocked.

        The shot's actual outcome — hit chance, damage, crit/sneak, skill
        training and any kill — is resolved later by :meth:`resolve_arrow_hit`,
        at the moment the physical arrow projectile actually lands. This
        split lets the arrow travel as a real object that can miss by flying
        past a target, get blocked by a wall, or land a beat after the shot
        was loosed, rather than resolving instantly on release.
        """
        char = self.character
        if eq.ammo(char) is None:
            self.message("Out of arrows!")
            return False
        a = eq.ammo(char)
        inv.remove_item(char.inventory, a.id, 1)
        if inv.quantity(char.inventory, a.id) <= 0:
            eq.unequip(char, items.SLOT_AMMO)
        char.spend_stamina(6.0)
        return True

    def resolve_arrow_hit(self, target_props: Dict, draw: float = 1.0) -> Dict:
        """Resolve an already-fired arrow's impact on a creature.

        Mirrors :meth:`attack_creature` but assumes :meth:`fire_arrow` already
        spent the stamina and consumed the ammo when the shot was loosed —
        this only rolls the hit/damage/crit/sneak outcome and applies it.
        """
        char = self.character
        res = combat.player_attack(char, target_props, sneaking=self.sneaking,
                                   draw=draw, rng=self.rng, dice=self.dice)
        return self._apply_hit(target_props, res)

    def _apply_hit(self, target_props: Dict, res: Dict) -> Dict:
        """Shared tail end of a resolved player attack: apply damage, train
        the weapon skill, message the hit, and handle a kill. ``res`` is a
        :func:`combat.player_attack` result; a miss (``res["hit"]`` false) is
        returned unchanged."""
        char = self.character
        if not res["hit"]:
            return res
        hp = int(target_props.get("health", 30))
        hp -= int(round(res["damage"]))
        target_props["health"] = hp
        char.use_skill(res["skill"], res["difficulty"])
        if res["sneak"]:
            char.use_skill("sneak", 1.5)
        tag = " SNEAK!" if res["sneak"] else (" CRIT!" if res["crit"] else "")
        self.message(f"Hit {target_props.get('display_name', target_props.get('name','foe'))}"
                     f" for {int(res['damage'])}{tag}")
        if hp <= 0:
            res["killed"] = True
            target_props["health"] = 0
            target_props["dead"] = True
            self.on_kill(target_props)
        return res

    def cast_active_spell(self) -> magic.CastResult:
        char = self.character
        if not char.active_spell:
            return magic.CastResult(False, "no spell selected")
        res = magic.try_cast(char, char.active_spell, self.rng, dice=self.dice)
        spell = res.spell
        if res.cast:
            if spell and spell.delivery == magic.SELF:
                self.message(f"Cast {spell.name}")
            # summons
            for e in (spell.effects if spell else []):
                if e.get("kind") == "summon":
                    self.message(f"Summoned a {e.get('creature','creature')}!")
        elif res.reason == "not enough magicka":
            self.message("Not enough magicka")
        elif res.reason == "fizzle":
            spell_name = spell.name if spell else "Spell"
            roll = res.roll or {}
            if roll:
                notation = escape(str(roll.get("dice_notation", "1d100")))
                rolled = escape(str(roll.get("roll_result", "?")))
                target = escape(str(roll.get("target", "?")))
                debug_log(
                    "Magic",
                    f'<span style="color: #42A5F5; font-weight: bold;">'
                    f'{escape(str(spell_name))}</span> '
                    f'<span style="color: #FF7043; font-weight: bold;">fizzled</span>: '
                    f'dice roll too low — '
                    f'<span style="color: #FFFFFF;">{notation}</span> = '
                    f'<span style="color: #69F0AE; font-weight: bold;">{rolled}</span> '
                    f'(target ≥ <span style="color: #FFEE58; font-weight: bold;">'
                    f'{target}</span>)')
                self.message(f"{spell_name} fizzles: rolled {rolled}; target {target}.")
            else:
                self.message(f"{spell_name} fizzles!")
        return res

    def resolve_spell_on_creature(self, spell: magic.Spell, target_props: Dict) -> Dict:
        """Apply a delivered TARGET/PROJECTILE spell's effects to a creature."""
        result = {"damage": 0.0, "killed": False}
        for e in spell.effects:
            k = e.get("kind")
            mag = float(e.get("magnitude", 0))
            if k == "damage_health":
                # elemental resistance on the creature
                resist = float(target_props.get("resist_" + spell.element, 0.0))
                dealt = mag * (1.0 - max(-1.0, min(1.0, resist)))
                hp = int(target_props.get("health", 30)) - int(round(dealt))
                target_props["health"] = hp
                result["damage"] += dealt
                if hp <= 0:
                    target_props["health"] = 0
                    target_props["dead"] = True
                    result["killed"] = True
                    self.on_kill(target_props)
        return result

    # ------------------------------------------------------------------- kills
    def on_kill(self, target_props: Dict) -> None:
        role = str(target_props.get("npc_role") or target_props.get("monster_role") or "").lower()
        creature = bestiary.get(role)
        name = target_props.get("display_name", target_props.get("name", "foe"))
        self.message(f"{name} slain!")
        # XP toward... skills already trained on hit; award a small luck bump via loot
        table = target_props.get("loot") or (creature.loot if creature else "")
        if table:
            stacks, gold = loot_mod.roll(table, self.character.level, self.rng,
                                         self.character.attrs.get("luck", 40),
                                         dice=self.dice)
            for s in stacks:
                inv.add_item(self.character.inventory, s)
            if stacks:
                self.message("Looted: " + ", ".join(s.get("name", "?") for s in stacks))
            if gold:
                self.add_gold(gold)
        # quest kill counters
        self._count_kill(role)

    def _count_kill(self, role: str) -> None:
        # generic per-role kill counter in the store for quest logic
        key = f"kills.{role}"
        try:
            n = int(self.store.get(key, "0"))
        except (TypeError, ValueError):
            n = 0
        n += 1
        self.store.set(key, n)
        # wolves quest auto-progress
        if role == "wolf" and self.quests.is_active("wolves"):
            if n >= 5 and self.quests.stage_of("wolves") < 10:
                self.quests.set_stage("wolves", 10)
                self.message("Quest updated: A Culling of Wolves")

    # ------------------------------------------------------------------ quests
    def start_quest(self, qid: str) -> bool:
        if self.quests.start(qid):
            q = quests.get(qid)
            self.message(f"New quest: {q.name}")
            return True
        return False

    def complete_quest(self, qid: str) -> None:
        q = quests.get(qid)
        if q is None or self.quests.is_complete(qid):
            return
        self.quests.complete(qid)
        r = q.rewards
        if r.get("gold"):
            self.add_gold(int(r["gold"]))
        for iid, qty in r.get("items", []):
            self.pick_up(iid, qty)
        if r.get("rep"):
            fac, amt = r["rep"]
            guilds.add_reputation(self.character, fac, amt)
        self.message(f"Quest complete: {q.name}")

    # ---------------------------------------------------------- per-tick regen
    def tick(self, dt: float) -> None:
        self.character.regen(dt)
        self.character.tick_effects(dt)

    # ------------------------------------------------------------- persistence
    def save_to_store(self, key: str = "_character") -> None:
        try:
            self.store.set(key, json.dumps(self.character.to_dict()))
        except Exception:
            pass

    def load_from_store(self, key: str = "_character") -> bool:
        raw = self.store.get(key, None)
        if raw in (None, "false", ""):
            return False
        try:
            self.character = Character.from_dict(json.loads(raw))
            return True
        except Exception:
            return False
