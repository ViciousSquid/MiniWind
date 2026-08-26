"""
Guilds, reputation and NPC disposition.

Beyond the low-level team relationships in the top-level ``factions`` module
(which drive who the AI attacks), this layer models the *social* RPG: joinable
guilds with a ladder of ranks, a numeric reputation with each, and how much any
given NPC likes you (disposition), which gates dialogue, prices and whether a
guard turns a blind eye.

Reputation/ranks are stored on the :class:`~game.rpg.character.Character`
so they persist with the character blob.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import attributes as attr


class Guild:
    def __init__(self, gid, name, ranks, desc=""):
        self.id = gid
        self.name = name
        self.ranks: List[str] = ranks   # ordered, index 0 = lowest
        self.desc = desc

    def rank_title(self, rank: int) -> str:
        if not self.ranks:
            return "Member"
        return self.ranks[max(0, min(len(self.ranks) - 1, rank))]


GUILDS: Dict[str, Guild] = {g.id: g for g in [
    Guild("fighters", "The Iron Company",
          ["Associate", "Apprentice", "Journeyman", "Swordsman", "Protector",
           "Guardian", "Champion", "Master"],
          "Sell-swords and monster-hunters for honest coin."),
    Guild("mages", "The Arcane Circle",
          ["Associate", "Apprentice", "Journeyman", "Evoker", "Conjurer",
           "Magician", "Warlock", "Wizard", "Master Wizard", "Arch-Mage"],
          "Scholars of the arcane arts."),
    Guild("thieves", "The Grey Hands",
          ["Toe", "Footpad", "Bandit", "Prowler", "Cat Burglar", "Shadowfoot",
           "Master Thief", "Guildmaster"],
          "Whisper the right word in the right ear and doors open."),
    Guild("wardens", "The Wardens",
          ["Recruit", "Sentinel", "Watchman", "Guardian", "Knight",
           "Paladin", "Commander"],
          "Sworn protectors of the realm."),
    Guild("town", "Townsfolk of Miniwind",
          ["Stranger", "Known", "Friend", "Hero of Miniwind"],
          "Standing among the ordinary people of the vale."),
]}


def get(guild_id: str) -> Optional[Guild]:
    return GUILDS.get(str(guild_id))


# ---------------------------------------------------------------------------
# Character-facing helpers (operate on character.factions)
# ---------------------------------------------------------------------------
def standing(character, guild_id: str) -> Dict:
    return character.factions.setdefault(guild_id, {"rank": -1, "reputation": 0,
                                                    "member": False})


def is_member(character, guild_id: str) -> bool:
    return bool(standing(character, guild_id).get("member"))


def join(character, guild_id: str) -> bool:
    st = standing(character, guild_id)
    if st.get("member"):
        return False
    st["member"] = True
    st["rank"] = max(0, st.get("rank", -1))
    return True


def rank(character, guild_id: str) -> int:
    return int(standing(character, guild_id).get("rank", -1))


def rank_title(character, guild_id: str) -> str:
    g = get(guild_id)
    r = rank(character, guild_id)
    if g is None or r < 0:
        return "Non-member"
    return g.rank_title(r)


def add_reputation(character, guild_id: str, amount: int) -> Dict:
    """Change reputation; auto-promote when reputation crosses rank thresholds."""
    g = get(guild_id)
    st = standing(character, guild_id)
    st["reputation"] = int(st.get("reputation", 0)) + int(amount)
    promoted = False
    if g is not None and st.get("member"):
        # every 10 reputation is worth a rank, capped at the ladder length
        target = min(len(g.ranks) - 1, st["reputation"] // 10)
        if target > st.get("rank", 0):
            st["rank"] = target
            promoted = True
    return {"reputation": st["reputation"], "rank": st.get("rank", -1),
            "promoted": promoted}


# ---------------------------------------------------------------------------
# Disposition — how a specific NPC feels about the player right now
# ---------------------------------------------------------------------------
def disposition(character, npc_props: Dict) -> int:
    """0-100 disposition of an NPC toward the player.

    Base + the player's Personality, + any per-NPC stored offset, + a bonus if
    the player belongs to the NPC's faction, - the player's bounty.
    """
    base = int(npc_props.get("disposition_base", character.disposition_base))
    pers = character.attrs.get(attr.PERSONALITY, 40)
    disp = base + int((pers - 40) * 0.5)
    disp += int(npc_props.get("disposition_offset", 0))
    fac = str(npc_props.get("faction", "")).lower()
    if fac and is_member(character, fac):
        disp += 15
    disp -= min(40, character.bounty // 20)
    return max(0, min(100, disp))


def persuade(character, npc_props: Dict, rng=None) -> Dict:
    """A speechcraft check that nudges an NPC's disposition up (or down on fail)."""
    import random
    rng = rng or random
    from . import skills as sk
    speech = character.skill(sk.SPEECHCRAFT)
    luck = character.attrs.get(attr.LUCK, 40)
    chance = (speech + luck * 0.2) / 100.0
    character.use_skill(sk.SPEECHCRAFT, 1.0)
    if rng.random() <= max(0.05, min(0.95, chance)):
        npc_props["disposition_offset"] = int(npc_props.get("disposition_offset", 0)) + 8
        return {"success": True, "disposition": disposition(character, npc_props)}
    npc_props["disposition_offset"] = int(npc_props.get("disposition_offset", 0)) - 4
    return {"success": False, "disposition": disposition(character, npc_props)}
