"""
The starting quests of Miniwind. Importing this module registers them.
"""

from __future__ import annotations

from .quests import Quest, Stage, register


def load() -> None:
    """Register all built-in quests (idempotent)."""

    register(Quest(
        "mill_bandits", "Trouble at the Old Mill",
        giver="Aldric", faction="town", xp=40,
        desc="Bandits have seized the old mill east of the village.",
        rewards={"gold": 150, "items": [("steel_longsword", 1)], "rep": ("town", 15)},
        stages=[
            Stage(0, "Aldric asked me to clear the bandits out of the old mill "
                     "east of Miniwind.", objective="Clear the old mill of bandits"),
            Stage(10, "The bandits at the mill are dead. I should return to Aldric.",
                  objective="Return to Aldric"),
            Stage(20, "Aldric thanked me and paid me for clearing the mill.",
                  finishes=True),
        ],
    ))

    register(Quest(
        "wolves", "A Culling of Wolves",
        giver="Bryn", faction="town", xp=20,
        desc="The shepherd Bryn is losing sheep to wolves.",
        rewards={"gold": 60, "items": [("hunting_bow", 1), ("iron_arrow", 20)],
                 "rep": ("town", 8)},
        stages=[
            Stage(0, "Bryn asked me to thin the wolf pack harassing his flock. "
                     "Kill five wolves.", objective="Kill 5 wolves (0/5)"),
            Stage(10, "The wolves are dealt with. Time to collect my reward from Bryn.",
                  objective="Return to Bryn"),
            Stage(20, "Bryn paid me for culling the wolves.", finishes=True),
        ],
    ))

    register(Quest(
        "fighters_join", "Proving Your Steel",
        giver="Grunn", faction="fighters", xp=25,
        desc="The Fighters Guild will take you on if you prove yourself.",
        rewards={"gold": 50, "rep": ("fighters", 10)},
        stages=[
            Stage(0, "Grunn of the Fighters Guild will admit me if I clear the "
                     "skeletons from the barrow.", objective="Clear the barrow"),
            Stage(10, "The barrow is cleared. I should report to Grunn.",
                  objective="Report to Grunn"),
            Stage(20, "I am now a member of the Fighters Guild.", finishes=True),
        ],
    ))

    register(Quest(
        "lost_amulet", "The Lost Amulet",
        giver="Elowen", faction="town", xp=15,
        desc="Elowen lost her grandmother's amulet somewhere in the woods.",
        rewards={"gold": 40, "items": [("potion_heal", 2)], "rep": ("town", 5)},
        stages=[
            Stage(0, "Elowen asked me to find her grandmother's amulet, lost in "
                     "the woods.", objective="Find the silver amulet"),
            Stage(10, "I found the amulet. I should bring it back to Elowen.",
                  objective="Return the amulet to Elowen"),
            Stage(20, "Elowen was overjoyed to have the amulet back.", finishes=True),
        ],
    ))
