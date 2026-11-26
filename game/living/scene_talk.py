"""Shared presentation and restitution helpers for world-scenario dialogue.

Scenario-specific conversation topics, thoughts and ambient lines live alongside
their implementations in game/living/scenario_modules. This module retains
the common formatting, conversation integration and repayment vocabulary.
"""

from __future__ import annotations

import zlib
from typing import Dict, List, Optional

#: Heard from this near (world units) while a scene is unresolved.
AMBIENT_RADIUS = 1100.0
#: Real seconds between two ambient lines from one scene.
AMBIENT_GAP = (6.0, 11.0)
#: The chance an ambient beat is a thought rather than a spoken line.
THOUGHT_CHANCE = 0.4

_HOW_KNOWN = {"witnessed": "I saw it with my own eyes.",
              "heard": "I heard it happen.",
              "told": "Folk told me -- and I believe them."}


def _pick(options, *salt) -> str:
    return options[zlib.crc32("|".join(str(s) for s in salt).encode()) % len(options)]


def _first(name: str) -> str:
    return str(name or "").split(" ")[0] or "them"


def _near(place: str) -> str:
    return f" near {place}" if place else ""


def _fmt(lines, talk) -> List[str]:
    """*lines* with the scene's facts filled in; a line naming a fact the
    scene does not have is dropped rather than said with a blank."""
    out = []
    for line in lines:
        try:
            text = line.format(**talk)
        except (KeyError, IndexError):
            continue
        if "{}" not in text and " ''" not in text:
            out.append(text)
    return out


def _known(talk) -> Dict[str, str]:
    """*talk* without its empty facts, so a line needing one is dropped."""
    return {k: v for k, v in (talk or {}).items() if v not in (None, "")}


# Scenario-specific lines and conversations live with their scenario modules.
def _scenario_module(kind):
    from .scenario_modules import dialogue_module
    return dialogue_module(kind)


def thoughts(kind: str, role: str, talk: Dict, want: str = "") -> Dict[str, List[str]]:
    """Return calm, fleeing or combat thoughts supplied by the owning scenario."""
    module = _scenario_module(kind)
    return module.thoughts(role, talk, want) if module is not None else {}


def ambient(kind: str, role: str, talk: Dict) -> List[str]:
    """Return ambient dialogue supplied by the owning scenario."""
    module = _scenario_module(kind)
    return module.ambient(role, talk) if module is not None else []


def topic(kind: str, role: str, talk: Dict, want: str = "") -> Optional[Dict]:
    """Return a conversation topic supplied by the owning scenario."""
    module = _scenario_module(kind)
    return module.topic(role, talk, want) if module is not None else None


def add_topic(tree, found: Optional[Dict]):
    """*tree* (a conversation) with the scene's topic offered first on its
    opening. Returns a new tree; the person's own conversation is kept."""
    import copy
    if not found:
        return tree
    tree = copy.deepcopy(tree) if isinstance(tree, dict) else {}
    nodes = tree.setdefault("nodes", {})
    start = tree.get("start") or ""
    if start not in nodes:
        start = "greet"
        nodes.setdefault(start, {"text": "Yes?", "responses": [
            {"text": "Farewell.", "goto": "END"}]})
        tree["start"] = start
    for nid, node in found["nodes"].items():
        node = copy.deepcopy(node)
        for r in node.get("responses", []):
            if r.get("goto") == "@start":
                r["goto"] = start
        nodes[nid] = node
    responses = nodes[start].setdefault("responses", [])
    if not any(r.get("goto") == found["first"] for r in responses):
        responses.insert(0, {"text": found["prompt"], "goto": found["first"]})
    return tree


# --------------------------------------------------------- will they take it?
#: How likely someone this angry is to take the gold (before Speechcraft).
ACCEPT_CHANCE = {"infuriated": 0.35, "resentful": 0.6}
#: Speechcraft adds this much per point (0.2 at 100).
SPEECH_BONUS = 0.002
#: What they say on taking the gold, calm or angry, and on refusing it.
ACCEPTED = ("That squares it. We're done, you and I.",)
ACCEPTED_GRUDGINGLY = ("...Fine. That squares it. Don't cross me again.",
                       "Hmph. It'll do. Now get out of my sight.")
REFUSED = ("Gold? You think gold mends this?", "Keep your coin. This isn't about money.",
           "I don't want your money. I want you to answer for it.")
REFUSED_AGAIN = ("I told you. Keep your coin.",)
#: Refused, a d6 + the player's Luck bonus at least this keeps their gold;
#: less and the seeker takes it anyway (and still attacks), taunting.
KEEP_GOLD_TARGET = 4
SNATCHED = ("Pathetic!", "Ha! Too slow!", "Mine now, fool!", "Pathetic. Truly pathetic.",
            "Thanks for the coin -- now die!")


def temper(disposition: int, furious: bool = False) -> str:
    """How angry someone come for repayment is with the player:
    "infuriated" (hostile toward them, or furious over a burnt field),
    "resentful" (unfriendly), or "" (calm enough to take the gold)."""
    if furious or disposition < 10:
        return "infuriated"
    if disposition < 30:
        return "resentful"
    return ""


def accept_chance(mood: str, speechcraft: float = 0.0) -> float:
    """The chance someone in *mood* takes the gold: 1 when calm."""
    base = ACCEPT_CHANCE.get(mood)
    if base is None:
        return 1.0
    return max(0.05, min(0.95, base + float(speechcraft) * SPEECH_BONUS))


# ------------------------------------------------------------ deeds, in brief
#: What a lock picked open is owed, when nothing was taken (gold).
LOCKPICK_OWED = 10
#: The least a theft is owed, whatever the thing was worth (gold).
LEAST_OWED = 5


def owed(kind: str, item_id: str = "") -> int:
    """The gold that settles a theft (what the thing was worth) or a picked
    lock; 0 for anything else."""
    if kind == "lockpick":
        return LOCKPICK_OWED
    if kind != "theft":
        return 0
    worth = 0
    try:
        from ..rpg import items as rpg_items
        info = rpg_items.get(item_id) if item_id else None
        worth = int(getattr(info, "value", 0) or 0) if info is not None else 0
    except Exception:
        worth = 0
    return max(LEAST_OWED, worth)
def deed(kind: str, item: str = "", victim: str = "", place: str = "") -> str:
    """What the player did, said to their face: "stole a loaf of bread from
    me near Ashby", "saved my brother Aldo near Low Farm"."""
    whom = victim or "me"
    verb = {"theft": f"took {item or 'what was mine'} from {whom}",
            "attack": f"struck {whom}", "death": f"killed {whom}",
            "lockpick": f"picked the lock on {'my' if whom == 'me' else whom + chr(39) + 's'} things",
            "heal": f"healed {whom}", "gift": f"gave {whom} help when nobody else would"}.get(kind, "")
    return f"{verb}{_near(place)}" if verb else ""
