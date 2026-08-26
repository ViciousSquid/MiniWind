"""
Loot tables & leveled lists.

When a creature dies or a container is opened, a loot table is rolled to produce
item stacks. Tables are *leveled*: entries can gate on the player level so that
higher-level foes drop better gear, in the Elder-Scrolls tradition. Gold ranges
and drop chances are per entry.
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

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
             luck: int = 40) -> Tuple[List[Dict], int]:
        """Return (item_stacks, gold) produced by this table."""
        rng = rng or random
        stacks: List[Dict] = []
        luck_bonus = (luck - 40) * 0.002
        for e in self.entries:
            if player_level < e.min_level:
                continue
            if rng.random() > min(1.0, e.chance + luck_bonus):
                continue
            qty = rng.randint(e.qty[0], e.qty[1])
            stack = items.make(e.item_id, qty)
            if stack:
                _roll_rarity(stack, player_level, rng, luck)
                stacks.append(stack)
        lo, hi = self.gold_range
        gold = rng.randint(lo, hi) if hi > 0 else 0
        return stacks, gold


def _roll_rarity(stack, player_level, rng, luck):
    """Give weapons/armour a small, level- and luck-scaled chance to be special."""
    d = items.get(stack.get("id"))
    if not d or d.category not in (items.WEAPON, items.ARMOUR):
        return
    chance = 0.06 + player_level * 0.01 + (luck - 40) * 0.001
    roll = rng.random()
    if roll < chance * 0.15:
        items.apply_rarity(stack, items.EPIC)
    elif roll < chance * 0.5:
        items.apply_rarity(stack, items.RARE)
    elif roll < chance:
        items.apply_rarity(stack, items.FINE)


TABLES: Dict[str, LootTable] = {}


def register(table: LootTable) -> LootTable:
    TABLES[table.id] = table
    return table


def get(table_id: str) -> Optional[LootTable]:
    return TABLES.get(str(table_id))


def roll(table_id: str, player_level: int = 1, rng=None, luck: int = 40):
    t = get(table_id)
    if t is None:
        return [], 0
    return t.roll(player_level, rng, luck)


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
