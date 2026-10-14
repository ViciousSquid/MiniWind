"""
What killed the player, in words: "Stabbed to death by Kestrel the Guard".

The engine records what dealt each hit to the player
(``LogicPlayer.last_damage``: the attacker, how, and the damage kind); the
session keeps the last one that hurt (:attr:`Character.last_harm`). When the
player dies, :func:`describe` turns it into one line for the death screen:
a verb chosen for the weapon or the beast -- a dagger stabs, a mace
bludgeons, an axe hacks, a wolf mauls, a hen pecks -- and who did it, named
as the world names them ("a wolf", "Mara, a villager", "the Greenskin
Warboss"). Each death draws one of several phrasings at random.
"""

from __future__ import annotations

import random
import re

# ---------------------------------------------------------------------------
# The verbs. Each list is a pool to draw from; every entry reads as
# "<verb> by <attacker>".
# ---------------------------------------------------------------------------
WEAPON_VERBS = {
    "dagger": ["Stabbed to death", "Shanked", "Knifed in the back", "Gutted",
               "Stuck like a pig", "Opened up with a dagger", "Quietly knifed"],
    "sword": ["Run through", "Cut down", "Slashed to ribbons", "Put to the sword",
              "Skewered", "Stabbed to death", "Sliced open", "Hewn down",
              "Cut to pieces", "Impaled"],
    "saber": ["Sabred", "Slashed to ribbons", "Cut down with a flourish",
              "Carved up", "Sliced open"],
    "mace": ["Bludgeoned to death", "Mashed to a pulp", "Crushed",
             "Had their skull caved in", "Flattened", "Battered to death"],
    "hammer": ["Hammered flat", "Pounded into the dirt", "Crushed",
               "Nailed", "Had their skull caved in", "Flattened like a horseshoe"],
    "axe": ["Hacked to pieces", "Cleaved in two", "Chopped down", "Axed",
            "Split like firewood", "Felled like a tree"],
    "club": ["Clubbed to death", "Cudgelled", "Beaten black and blue",
             "Bonked one time too many", "Battered to death"],
    "pitchfork": ["Skewered on a pitchfork", "Forked to death",
                  "Tossed like hay", "Pitchforked"],
    "scythe": ["Reaped", "Mown down", "Harvested", "Cut down like wheat"],
    "shovel": ["Spaded to death", "Given a shovel to the face",
               "Flattened with a shovel", "Shovelled into an early grave"],
    "bucket": ["Bucketed to death", "Brained with a bucket",
               "Clonked with a bucket"],
    "fist": ["Beaten to death with bare fists", "Punched out for good",
             "Pummelled", "Throttled", "Punched into oblivion"],
    "staff": ["Thrashed with a staff", "Staved in", "Quarterstaffed"],
    "melee": ["Cut down", "Slain", "Struck down", "Beaten to death",
              "Done in", "Bested"],
}

PROJECTILE_VERBS = {
    "bow": ["Shot full of arrows", "Feathered with arrows", "Picked off with an arrow",
            "Pincushioned", "Shot dead", "Turned into a pincushion",
            "Shot through the heart"],
    "crossbow": ["Bolted", "Shot through with a crossbow bolt",
                 "Felled with a crossbow bolt", "Pinned to the ground",
                 "Punched through with a bolt"],
    "magic": ["Blasted apart", "Hexed to death", "Cursed into the grave",
              "Struck down with dark magic", "Unmade", "Smote"],
    "projectile": ["Shot dead", "Struck down from afar", "Picked off", "Brought down"],
}

#: A beast with no weapon: its own way of killing.
CREATURE_VERBS = {
    "wolf": ["Mauled", "Torn apart", "Savaged", "Eaten alive", "Ripped to shreds",
             "Hunted down", "Run down"],
    "bear": ["Mauled", "Torn limb from limb", "Hugged to death",
             "Swatted like a fly", "Eaten", "Bear-handled"],
    "boar": ["Gored", "Tusked", "Trampled", "Run down", "Gored and trampled"],
    "mudcrab": ["Pinched to death", "Snipped to bits", "Clawed to death",
                "Humiliated", "Nipped to death"],
    "skeleton": ["Rattled to death", "Clawed to death", "Dragged into the dark",
                 "Dragged to the grave", "Pulled into the grave"],
    "wraith": ["Drained of life", "Chilled to the soul", "Frozen to the soul",
               "Haunted to death", "Withered away"],
    "monster": ["Torn apart", "Devoured", "Ripped to pieces", "Mangled", "Eaten alive"],
    "cow": ["Trampled", "Gored", "Udderly destroyed", "Butted to death", "Stampeded over"],
    "hen": ["Pecked to death", "Clucked out of this world", "Flogged to death",
            "Pecked into oblivion", "Henpecked to death"],
    "sheep": ["Butted to death", "Rammed", "Fleeced", "Trampled underhoof"],
    "cultist": ["Sacrificed", "Hexed to death", "Cursed into the grave",
                "Offered to something old"],
    "dragon": ["Clawed to ribbons", "Bitten in half", "Swallowed whole", "Crushed underfoot"],
}

BITE_VERBS = ["Bitten to death", "Chewed up", "Devoured", "Eaten alive", "Gnawed to death"]

FIRE_VERBS = ["Burned to a crisp", "Roasted alive", "Incinerated", "Reduced to ash",
              "Flame-grilled", "Cooked through", "Turned to cinders", "Charred beyond recognition"]

FROST_VERBS = ["Frozen solid", "Turned to ice", "Frozen to death"]
SHOCK_VERBS = ["Fried", "Electrocuted", "Lightning-struck", "Shocked to death"]
POISON_VERBS = ["Poisoned", "Done in with poison", "Choked on poison", "Withered away"]
TRAP_VERBS = ["Met a grisly end", "Fell foul of a trap", "Walked into the wrong place",
              "Found the sharp end of a trap", "Should have watched their step"]
#: A trap with a name ("{}" is "a spike pit").
TRAP_NAMED = ["Met a grisly end in {}", "Fell foul of {}", "Found the sharp end of {}",
              "Undone by {}", "Walked into {}, fatally"]
GENERIC_VERBS = ["Slain", "Killed", "Struck down", "Felled", "Done in",
                 "Sent to the afterlife", "Put in the ground"]

#: Weapon id/name words -> the WEAPON_VERBS pool they draw from, first match wins.
_WEAPON_WORDS = (
    ("crossbow", "crossbow"), ("bow", "bow"), ("dagger", "dagger"), ("knife", "dagger"),
    ("saber", "saber"), ("sabre", "saber"), ("scimitar", "saber"),
    ("warhammer", "hammer"), ("hammer", "hammer"), ("mace", "mace"),
    ("battleaxe", "axe"), ("axe", "axe"), ("club", "club"), ("pitchfork", "pitchfork"),
    ("scythe", "scythe"), ("shovel", "shovel"), ("bucket", "bucket"),
    ("fist", "fist"), ("staff", "staff"), ("sword", "sword"), ("blade", "sword"),
)

#: Roles whose name is said with "the" (there is only one of them about).
_CHIEF_ROLES = {"bandit_chief"}
_TITLE_WORDS = {"captain", "chief", "warboss", "boss", "king", "queen", "lord",
                "lady", "warlord", "elder"}


def _weapon_word(item_id) -> str:
    """The WEAPON_VERBS / PROJECTILE_VERBS key for a weapon id, or ''."""
    text = str(item_id or "").lower()
    if not text:
        return ""
    try:
        from .rpg import items
        d = items.get(text)
        if d is not None:
            kind = str(d.get("kind", "")).lower()
            if kind == "crossbow":
                return "crossbow"
            if kind == "bow":
                return "bow"
            text = f"{text} {d.name.lower()}"
    except Exception:
        pass
    for word, key in _WEAPON_WORDS:
        if word in text:
            return key
    return "melee"


def _article(noun: str) -> str:
    return "an" if noun[:1].lower() in "aeiou" else "a"


def name_of(thing) -> str:
    """How a death line names *thing*: "a wolf", "Mara, a villager",
    "Kestrel the Guard", "the Greenskin Warboss"."""
    if thing is None:
        return "something"
    p = getattr(thing, "properties", {}) or {}
    role = str(p.get("npc_role") or "").lower()
    label = ""
    kind = ""
    try:
        from .rpg import bestiary
        c = bestiary.get(role) if role else None
        if c is not None:
            label, kind = c.name, c.kind
    except Exception:
        pass
    name = str(p.get("display_name") or p.get("name") or "").strip()
    if not name or re.search(r"_\d+$", name):
        name = label or role.replace("_", " ").title() or "Something"
    lowered = name.lower()
    if "dragon" in lowered and " " not in name.strip():
        return "the dragon"
    if role in _CHIEF_ROLES or any(w in _TITLE_WORDS for w in lowered.split()):
        return name if lowered.startswith("the ") else f"the {name}"
    if kind == "npc" or str(p.get("type", "")).lower() == "npc":
        if label and lowered == label.lower():
            return f"{_article(label)} {label.lower()}"
        # A personal name: say who they are, unless the name already does.
        if label and " the " not in f" {lowered} " and label.lower() not in lowered:
            return f"{name}, {_article(label)} {label.lower()}"
        return name
    # A beast or a brigand: one of many.
    return f"{_article(name)} {lowered}"


def _creature_pool(thing):
    p = getattr(thing, "properties", {}) or {}
    role = str(p.get("npc_role") or "").lower()
    name = str(p.get("display_name") or p.get("name") or "").lower()
    if role in CREATURE_VERBS:
        return CREATURE_VERBS[role]
    for key in CREATURE_VERBS:
        if key in name:
            return CREATURE_VERBS[key]
    return None


def _weapon_of(thing):
    p = getattr(thing, "properties", {}) or {}
    weapon = p.get("_active_weapon") or p.get("equipped_weapon") or ""
    if not weapon:
        try:
            from .rpg import bestiary
            c = bestiary.get(str(p.get("npc_role") or "").lower())
            weapon = getattr(c, "weapon", "") if c is not None else ""
        except Exception:
            weapon = ""
    return weapon


def _verbs(thing, cause, kind):
    """The pool of verbs for this death."""
    kind = str(kind or "physical").lower()
    cause = str(cause or "").lower()
    if kind == "fire" or cause == "breath":
        return FIRE_VERBS
    if kind in ("frost", "cold", "ice"):
        return FROST_VERBS
    if kind in ("shock", "lightning"):
        return SHOCK_VERBS
    if kind == "poison" or cause == "poison":
        return POISON_VERBS
    if cause == "trigger":
        return TRAP_VERBS
    if thing is None:
        return GENERIC_VERBS
    weapon = _weapon_word(_weapon_of(thing))
    if cause == "projectile":
        p = getattr(thing, "properties", {}) or {}
        if weapon in PROJECTILE_VERBS:
            return PROJECTILE_VERBS[weapon]
        if str(p.get("attack_style", "")).lower() == "magic" or \
                str(p.get("npc_role", "")).lower() == "cultist":
            return PROJECTILE_VERBS["magic"]
        return PROJECTILE_VERBS["projectile"]
    if cause == "bite":
        return _creature_pool(thing) or BITE_VERBS
    if weapon and weapon not in ("bow", "crossbow"):
        return WEAPON_VERBS.get(weapon, WEAPON_VERBS["melee"])
    return _creature_pool(thing) or WEAPON_VERBS["melee"]


def describe(thing, cause=None, kind=None, rng=None, trap_name="") -> str:
    """One line saying how the player died. *thing* is the attacker (or
    None), *cause* how ("attack", "bite", "projectile", "breath",
    "trigger", "poison"), *kind* the damage kind ("physical", "fire", ...)."""
    rng = rng or random
    trap_name = str(trap_name or "").strip()
    if re.search(r"_\d+$", trap_name) or trap_name.lower().startswith("trigger"):
        trap_name = ""                        # an editor's auto-name says nothing
    if str(cause or "").lower() == "trigger" and trap_name and str(kind or "physical") == "physical":
        return rng.choice(TRAP_NAMED).format(f"{_article(trap_name)} {trap_name.lower()}")
    verb = rng.choice(_verbs(thing, cause, kind))
    if thing is None:
        return verb
    return f"{verb} by {name_of(thing)}"
