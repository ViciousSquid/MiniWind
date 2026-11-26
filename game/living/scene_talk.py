"""
What people in a Dynamic mode scene say and think -- built from the scene.

The director (``game/living/scenarios.py``) records, as it stages a scene, the
real facts it was cast from: who the victim is and where they were bound, the
gang's leader and the camp it came from, the captive's home, the avenger's
culprit and what they did, the deed someone has come to settle. This module
turns those facts into three things, and makes nothing else up:

* **Conversation**: a topic added to the person's own conversation ("What
  happened to you?", "Tell me about Black Rook."), answered from the scene's
  facts. The person's ordinary conversation is all still there.
* **Thoughts**: thought bubbles that fit the moment -- calm (waiting, held,
  circling), fleeing, or fighting -- shown through the game's thought system
  (``game/mental_state.thought``) in place of a generic one.
* **Ambient lines**: what is heard on the approach while the scene plays out:
  brigands taunting their victim, cult chanting around the captive, the
  avenger muttering.

Normal mode stages no scenes, so none of this is ever seen there.

Pure Python; no Qt, no engine.
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


# --------------------------------------------------------------------- lines
# By scene kind, then role ("victim", "attacker", "avenger", "seeker"). A
# seeker's lines go one level deeper, by what they want of the player.

THOUGHTS = {
    "waylaid": {
        "victim": {"calm": ("Keep still. Don't look at them.", "Not here... not now.",
                            "We should have stayed in {origin}."),
                   "flee": ("My purse... my life...", "Someone, please!", "Run! Just run!"),
                   "combat": ("Not without a fight!",)},
        "attacker": {"calm": ("Easy pickings.", "Fat purse on that one.",
                              "{victim_first} won't miss it.")},
    },
    "avenger": {
        "avenger": {"calm": ("{culprit} will pay for {whom_first}.", "For {whom_first}.",
                             "Steady. Wait for them."),
                    "combat": ("This is for {whom_first}!",)},
    },
    "cult_rite": {
        "victim": {"calm": ("Someone, please...", "I don't want to die here.",
                            "I should be home in {home}.")},
        "attacker": {"calm": ("The night is hungry.", "Soon. The rite is nearly ready.",
                              "One more for the dark.")},
    },
    "procession": {
        "attacker": {"calm": ("Walk in silence. Walk in shadow.", "The dark goes with us.")},
    },
    "ambush": {
        "attacker": {"calm": ("Quiet now. Wait for it.", "Here they come...",
                              "Nobody move till they're close.")},
    },
    "patrol": {
        "victim": {"calm": ("Brigands about. Stay sharp.",),
                   "combat": ("Hold the line!", "For the watch!")},
        "attacker": {"combat": ("Cut them down!",)},
    },
    "reckoning": {
        "seeker": {
            "vendetta": {"calm": ("{victim_first} deserved better.", "Today it ends.")},
            "reckoning": {"calm": ("Not this time.", "I won't be beaten twice.")},
            "restitution": {"calm": ("I want what's mine.", "They'll pay, one way or another.")},
        },
    },
    "gratitude": {
        "seeker": {"gratitude": {"calm": ("There they are. I owe them.",
                                          "I never thanked them properly.")}},
    },
}

AMBIENT = {
    "waylaid": {
        "victim": ("Please, we've nothing worth killing for!", "Take it -- just let us go!",
                   "We're only bound for {dest}!", "Help! Somebody, help!"),
        "attacker": ("Hand it over, {victim_first}!", "Your purse or your life!",
                     "Nobody's coming to help you.", "Empty the packs. All of it."),
    },
    "avenger": {
        "avenger": ("For {whom_first}.", "Steady... steady.", "{culprit}. I'll find you."),
    },
    "cult_rite": {
        "victim": ("Help! Somebody!", "Please... my family are in {home}!",
                   "Let me go -- I've done nothing!"),
        "attacker": ("By ash and by ember, the old dark wakes.", "Bind them tighter.",
                     "Another for the altar.", "Sing, brothers. The night is listening."),
    },
    "procession": {
        "attacker": ("By ash and by ember...", "Walk in shadow. Walk in silence.",
                     "The dark goes before us."),
    },
    "patrol": {
        "victim": ("In the name of the watch, lay down your arms!", "Form up! Form up!"),
        "attacker": ("Come on then, tin-hats!", "Not so brave without your walls!"),
    },
}


def thoughts(kind: str, role: str, talk: Dict, want: str = "") -> Dict[str, List[str]]:
    """``{"calm" | "flee" | "combat": [lines]}`` for someone in the scene."""
    table = (THOUGHTS.get(kind) or {}).get(role) or {}
    if role == "seeker":
        table = table.get(want) or {}
    known = _known(talk)
    out = {}
    for situation, lines in table.items():
        said = _fmt(lines, known)
        if said:
            out[situation] = said
    return out


def ambient(kind: str, role: str, talk: Dict) -> List[str]:
    """What someone in the scene is heard saying on the approach."""
    return _fmt((AMBIENT.get(kind) or {}).get(role) or (), _known(talk))


# ------------------------------------------------------------- conversation
def topic(kind: str, role: str, talk: Dict, want: str = "") -> Optional[Dict]:
    """The scene's topic for someone the player can talk to:
    ``{"prompt": str, "nodes": {id: node}, "first": id}``, or None.

    Every answer is made from the scene's own facts."""
    t = _known(talk)
    nodes: Dict[str, Dict] = {}
    back = {"text": "I see.", "goto": "@start"}

    if kind == "waylaid" and role == "victim":
        camp = t.get("camp")
        text = (f"{t.get('gang', 'Brigands')} and their lot came at us on the road"
                f"{_near(t.get('here', ''))}. They wanted everything we carry.")
        if t.get("dest"):
            text += f" We were only bound for {t['dest']}."
        replies = [back]
        if camp:
            nodes["scene_from"] = {"text": f"From the {camp} way. That's where they'll run back to.",
                                   "responses": [back]}
            replies = [{"text": "Where did they come from?", "goto": "scene_from"}, back]
        nodes["scene"] = {"text": text, "responses": replies}
        return {"prompt": "What happened here?", "nodes": nodes, "first": "scene"}

    if kind == "patrol" and role == "victim":
        text = f"{t.get('gang', 'Brigands')}'s gang, bold as you like, on the open road."
        if t.get("camp"):
            text += f" They came from {t['camp']}."
        nodes["scene"] = {"text": text, "responses": [back]}
        return {"prompt": "What happened here?", "nodes": nodes, "first": "scene"}

    if kind == "cult_rite" and role == "victim":
        text = (f"They took me on the road outside {t['home']}." if t.get("home")
                else "They took me off the road.")
        count = int(t.get("count", 0) or 0)
        if t.get("cult"):
            text += (f" {t['cult']} and {count - 1} others." if count > 1 else f" {t['cult']}.")
        text += " They said I was chosen."
        who = (f"{t['cult']} leads them." if t.get("cult") else "I never heard a name.")
        if t.get("camp"):
            who += f" They spoke of {t['camp']}."
        nodes["scene_who"] = {"text": who, "responses": [back]}
        go_home = (f"Thank you. I'll go straight back to {t['home']}." if t.get("home")
                   else "Thank you. I'll go home.")
        nodes["scene_home"] = {"text": go_home, "responses": [{"text": "Go.", "goto": "END"}]}
        nodes["scene"] = {"text": text, "responses": [
            {"text": "Who did this?", "goto": "scene_who"},
            {"text": "Get home. I'll deal with them.", "goto": "scene_home"}, back]}
        return {"prompt": "What happened to you?", "nodes": nodes, "first": "scene"}

    if kind == "avenger" and role == "avenger" and t.get("culprit"):
        text = f"{t['culprit']} {t.get('what', 'wronged')} {t.get('whom', 'me')}{_near(t.get('place', ''))}."
        how = _HOW_KNOWN.get(t.get("source", ""))
        if how:
            text += " " + how
        if t.get("where"):
            text += f" {t['where']}."
        nodes["scene_alone"] = {"text": "Because nobody else will. Somebody has to answer for it.",
                                "responses": [back]}
        nodes["scene"] = {"text": text, "responses": [
            {"text": "Why go alone?", "goto": "scene_alone"}, back]}
        return {"prompt": f"Tell me about {t['culprit']}.", "nodes": nodes, "first": "scene"}

    if role == "seeker" and want in ("restitution", "gratitude") and t.get("deed"):
        if want == "restitution":
            text = f"You {t['deed']}. I want it back -- or its worth, in gold."
            prompt = "What do you want?"
            owed = int(t.get("owed", 0) or 0)
            if owed > 0:
                nodes["scene_paid"] = {"text": "That squares it. We're done, you and I.",
                                       "responses": [{"text": "Farewell.", "goto": "END"}]}
                nodes["scene_short"] = {"text": "Then find it. I'll not wait forever.",
                                        "responses": [back]}
                nodes["scene_refuse"] = {"text": "Then we'll settle it some other way.",
                                         "responses": [{"text": "...", "goto": "END"}]}
                nodes["scene"] = {"text": f"{text} {owed} gold squares it.", "responses": [
                    {"text": f"Here: {owed} gold.", "goto": "scene_paid",
                     "condition": {"has_item": "gold", "qty": owed},
                     "actions": [{"op": "scene_repay", "scene": t.get("scene", ""),
                                  "event": t.get("event", 0), "gold": owed}]},
                    {"text": f"I haven't got {owed} gold.", "goto": "scene_short",
                     "condition": {"lacks_item": "gold", "qty": owed}},
                    {"text": "I'm not paying you.", "goto": "scene_refuse"}]}
                return {"prompt": prompt, "nodes": nodes, "first": "scene"}
        else:
            text = f"You {t['deed']}. I've not forgotten it."
            prompt = "Do I know you?"
        nodes["scene"] = {"text": text, "responses": [back]}
        return {"prompt": prompt, "nodes": nodes, "first": "scene"}
    return None


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
