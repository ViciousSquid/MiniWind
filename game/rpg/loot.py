"""
Loot tables & leveled lists.

When a creature dies or a container is opened, a loot table is rolled to produce
item stacks. Tables are *leveled*: entries can gate on the player level so that
higher-level foes drop better gear, in the Elder-Scrolls tradition. Gold ranges
and drop chances are per entry.
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..diceroll import DiceRoller

from ..diceroll import CHECK_NOTATION, DICE_TYPES, check_threshold
from . import items


class LootEntry:
    def __init__(self, item_id, chance=1.0, qty=(1, 1), min_level=1, gold=False):
        self.item_id = item_id
        self.chance = chance
        self.qty = qty            # (min, max)
        self.min_level = min_level
        self.gold = gold


class LootTable:
    def __init__(self, tid, entries: List[LootEntry], gold_range=(0, 0)):
        self.id = tid
        self.entries = entries
        self.gold_range = gold_range

    def roll(self, player_level: int = 1, rng: Optional[random.Random] = None,
             luck: int = 40, dice: Optional["DiceRoller"] = None) -> Tuple[List[Dict], int]:
        """Return (item_stacks, gold), using the shared dice service when bound."""
        rng = rng or random
        stacks: List[Dict] = []
        luck_bonus = (luck - 40) * 0.002
        for e in self.entries:
            if player_level < e.min_level:
                continue
            if dice is not None:
                # d20, like every other chance in the game — there is no d100
                # die to show the player (see diceroll.CHECK_DIE).
                chance_roll = dice.request_roll(
                    CHECK_NOTATION, source="loot.drop",
                    context={"table": self.id, "item_id": e.item_id})
                if chance_roll["roll_result"] > check_threshold(e.chance + luck_bonus):
                    continue
            elif rng.random() > min(1.0, e.chance + luck_bonus):
                continue
            qty = _roll_range(e.qty[0], e.qty[1], rng, dice, self.id, e.item_id)
            stack = items.make(e.item_id, qty)
            if stack:
                _roll_rarity(stack, player_level, rng, luck, dice=dice, table_id=self.id)
                stacks.append(stack)
        lo, hi = self.gold_range
        gold = _roll_range(lo, hi, rng, dice, self.id, "gold") if hi > 0 else 0
        return stacks, gold


def _roll_range(lo: int, hi: int, rng, dice, table_id: str, item_id: str) -> int:
    """Roll an inclusive integer range through the shared service."""
    lo, hi = int(lo), int(hi)
    if hi <= lo:
        return lo
    span = hi - lo + 1
    # Only roll this through the shared service when the span *is* one of the
    # real dice: every roll is put on screen, and a 37-sided die is not one
    # anybody owns. Odd spans fall back to a plain random pick, unshown.
    if dice is not None and span in DICE_TYPES:
        result = dice.request_roll(
            f"1d{span}", source="loot.quantity",
            context={"table": table_id, "item_id": item_id})
        return lo + result["roll_result"] - 1
    return rng.randint(lo, hi)


def _roll_rarity(stack, player_level, rng, luck, dice=None, table_id=""):
    """Give weapons/armour a small, level- and luck-scaled chance to be special.

    The die only answers *is this item special at all* — an epic is one part in
    a few hundred, which no real die can express, and the point of rolling here
    in front of the player is the moment of "is it something good?". Once the
    die says yes, which grade it is (epic / rare / fine) is picked off the
    ordinary random stream, keeping the original 15 / 35 / 50 split.
    """
    d = items.get(stack.get("id"))
    if not d or d.category not in (items.WEAPON, items.ARMOUR):
        return
    chance = 0.06 + player_level * 0.01 + (luck - 40) * 0.001
    if dice is not None:
        rarity_roll = dice.request_roll(
            CHECK_NOTATION, source="loot.rarity",
            context={"table": table_id, "item_id": stack.get("id")})
        if rarity_roll["roll_result"] > check_threshold(chance):
            return
    elif rng.random() >= chance:
        return
    grade = rng.random()
    if grade < 0.15:
        items.apply_rarity(stack, items.EPIC)
    elif grade < 0.5:
        items.apply_rarity(stack, items.RARE)
    else:
        items.apply_rarity(stack, items.FINE)


TABLES: Dict[str, LootTable] = {}


def register(table: LootTable) -> LootTable:
    TABLES[table.id] = table
    return table


def get(table_id: str) -> Optional[LootTable]:
    return TABLES.get(str(table_id))


def roll(table_id: str, player_level: int = 1, rng=None, luck: int = 40, dice=None):
    t = get(table_id)
    if t is None:
        return [], 0
    return t.roll(player_level, rng, luck, dice=dice)


# ---------------------------------------------------------------------------
# Standard tables
# ---------------------------------------------------------------------------
register(LootTable("wolf", [
    LootEntry("ingr_wolf_pelt", 0.8, (1, 2)),
    LootEntry("potion_heal_minor", 0.1),
], gold_range=(0, 3)))

register(LootTable("bandit", [
    LootEntry("iron_shortsword", 0.35, min_level=1),
    LootEntry("steel_longsword", 0.15, min_level=4),
    LootEntry("short_bow", 0.2),
    LootEntry("iron_arrow", 0.5, (3, 12)),
    LootEntry("leather_cuirass", 0.25),
    LootEntry("iron_helmet", 0.15),
    LootEntry("potion_heal_minor", 0.25),
    LootEntry("lockpick", 0.3, (1, 3)),
], gold_range=(2, 25)))

register(LootTable("bandit_chief", [
    LootEntry("steel_longsword", 0.5, min_level=3),
    LootEntry("elven_saber", 0.1, min_level=8),
    LootEntry("steel_cuirass", 0.4),
    LootEntry("potion_heal", 0.5),
    LootEntry("long_bow", 0.3),
    LootEntry("steel_arrow", 0.6, (5, 15)),
], gold_range=(25, 120)))

register(LootTable("cultist", [
    LootEntry("apprentice_staff", 0.2),
    LootEntry("potion_magicka", 0.4),
    LootEntry("ingr_nightshade", 0.3, (1, 2)),
    LootEntry("scroll_flare" if items.get("scroll_flare") else "book_lore", 0.15),
    LootEntry("iron_dagger", 0.3),
], gold_range=(5, 40)))

register(LootTable("skeleton", [
    LootEntry("iron_shortsword", 0.3),
    LootEntry("ingr_bonemeal", 0.7, (1, 3)),
    LootEntry("iron_shield", 0.2),
], gold_range=(0, 10)))

register(LootTable("chest_common", [
    LootEntry("potion_heal_minor", 0.4),
    LootEntry("lockpick", 0.5, (1, 4)),
    LootEntry("iron_dagger", 0.2),
    LootEntry("book_lore", 0.1),
], gold_range=(5, 40)))

register(LootTable("chest_rich", [
    LootEntry("steel_longsword", 0.3, min_level=3),
    LootEntry("elven_saber", 0.08, min_level=8),
    LootEntry("potion_heal", 0.5),
    LootEntry("silver_sword", 0.15, min_level=5),
    LootEntry("elven_arrow", 0.3, (5, 20)),
], gold_range=(40, 200)))
