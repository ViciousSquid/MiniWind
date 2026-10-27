"""
Alignment: how good or evil a soul has made itself, by what it has done.

Every living thing in the Vale -- the player and every NPC -- stands
somewhere from **-100 (Villainous)** to **+100 (Saintly)**, and moves along it
by its deeds: cutting down the brigands raiding a village and saving its
people lifts you; butchering that village sinks you. Each deed moves you less
the further you already are in its direction, so sainthood and true villainy
are earned, not stumbled into, while a single atrocity still costs a saint
dearly.

What it changes (see :func:`consequences`): how everyone feels about you
(like warms to like), what the watch charges you, how strong your magic is
(the good heal and ward more strongly, the wicked strike harder), whether
brigands treat you as one of their own, whether frightened townsfolk take
heart when you are near -- and an NPC who sinks far enough falls from grace
and turns outlaw.

Pure: values in, values out. The session records deeds and applies effects.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

MIN, MAX = -100.0, 100.0

#: (lowest value, name), best first.
TIERS = ((75, "Saintly"), (30, "Good"), (-29, "Neutral"), (-74, "Evil"),
         (-100, "Villainous"))

#: deed -> (alignment change, how the log puts it).
DEEDS: Dict[str, Tuple[float, str]] = {
    "slay_monster": (2.0, "slew a monster"),
    "slay_brigand": (3.0, "cut down a brigand"),
    "defend": (5.0, "defended the innocent"),
    "quest": (6.0, "helped someone in need"),
    "heal_other": (3.0, "healed another"),
    "gift": (2.0, "gave freely"),
    "atone": (4.0, "paid for your crimes"),
    "resurrect": (8.0, "brought someone back from death"),
    "spare": (3.0, "showed mercy"),
    "murder": (-20.0, "murdered an innocent"),
    "slay_guard": (-12.0, "killed a guard"),
    "assault": (-4.0, "attacked an innocent"),
    "theft": (-3.0, "stole"),
    "lockpick": (-1.0, "broke into what was not yours"),
    "slay_animal": (-1.0, "killed a harmless beast"),
}

#: Where a kind of creature starts (by npc_role / creature_role).
BASELINE = {
    "guard": 35, "guard_archer": 35, "villager": 20, "farmer": 20, "merchant": 10,
    "blacksmith": 15, "beggar": 15, "bandit": -45, "bandit_archer": -45,
    "bandit_chief": -65, "cultist": -60, "skeleton": -50, "skeleton_archer": -50,
    "wraith": -70, "monster": -40, "dragon": -60,
}
#: Factions whose members are evil by trade, and roles that are harmless beasts.
EVIL_FACTIONS = ("bandits", "cultists")
HARMLESS_ROLES = ("sheep", "cow", "hen")
#: Below this, an NPC who was not already an outlaw falls from grace.
FALL_FROM_GRACE = -60.0


def tier(value: float) -> str:
    v = float(value)
    for lo, name in TIERS:
        if v >= lo:
            return name
    return TIERS[-1][1]


def shift(value: float, delta: float) -> float:
    """*value* moved by *delta*, less the further it already is that way:
    nothing is lost near the middle, half is lost at +/-60, and a deed always
    moves you at least a little."""
    value, delta = float(value), float(delta)
    if delta == 0:
        return value
    toward = max(0.0, value if delta > 0 else -value)
    scaled = delta * max(0.15, 1.0 - toward / 120.0)
    return max(MIN, min(MAX, value + scaled))


def of_npc(props) -> float:
    """An NPC's alignment: authored, else its kind's baseline, written on so it
    can change and persist."""
    if not isinstance(props, dict):
        return 0.0
    if "alignment" not in props:
        role = str(props.get("npc_role") or props.get("creature_role") or "").lower()
        props["alignment"] = float(BASELINE.get(role, 0))
    try:
        return float(props["alignment"])
    except (TypeError, ValueError):
        return 0.0


def kill_deed(victim, *, hostile_to_killer: bool, crime: bool = False) -> Optional[str]:
    """What killing *victim* (its properties) counts as for the killer. A
    killing the law calls a crime is murder (or a guard's death) whatever
    the victim was doing."""
    if not isinstance(victim, dict):
        return None
    role = str(victim.get("npc_role") or victim.get("creature_role") or "").lower()
    if crime:
        return "slay_guard" if role.startswith("guard") else "murder"
    faction = str(victim.get("faction") or victim.get("team") or "").lower()
    if role in HARMLESS_ROLES:
        return "slay_animal"
    if faction in EVIL_FACTIONS or role.startswith(("bandit", "cultist")):
        return "slay_brigand"
    human = str(victim.get("monster_type", "human")) == "human"
    if not human or of_npc(victim) <= -30:
        return "slay_monster" if hostile_to_killer or of_npc(victim) <= -30 else "slay_animal"
    if hostile_to_killer:
        return None                       # a fair fight with an enemy
    if role.startswith("guard"):
        return "slay_guard"
    return "murder"


# ----------------------------------------------------------- consequences
def affinity(player_value: float, npc_value: float) -> int:
    """Disposition from alignment: like warms to like, and a villain is
    loathed by anyone decent. -20..+20."""
    p, n = float(player_value), float(npc_value)
    out = p * n / 400.0
    if p <= -75 and n > -30:
        out -= 8                          # a known butcher
    return int(max(-20, min(20, round(out))))


#: What the watch charges, by tier: the good get the benefit of the doubt.
BOUNTY_MULT = {"Saintly": 0.6, "Good": 0.8, "Neutral": 1.0, "Evil": 1.25,
               "Villainous": 1.5}


def bounty_mult(value: float) -> float:
    return BOUNTY_MULT[tier(value)]


def magic_power(value: float, school: str) -> float:
    """How alignment empowers a school: the good's Defensive magic (healing,
    wards) and the wicked's Offensive magic grow up to +25%."""
    v = float(value)
    if school == "defensive" and v > 0:
        return 1.0 + 0.25 * v / 100.0
    if school == "offensive" and v < 0:
        return 1.0 + 0.25 * -v / 100.0
    return 1.0


def kinship(value: float) -> bool:
    """Evil enough that brigands and cultists take you for one of their own."""
    return float(value) <= -50


def heartens(value: float) -> float:
    """How a nearby player steadies (+) or frightens (-) townsfolk facing a
    threat: up to +/-0.3 confidence."""
    v = float(value)
    if v >= 30:
        return 0.3 * v / 100.0
    if v <= -30:
        return 0.3 * v / 100.0
    return 0.0


def greeting(player_value: float, npc_value: float) -> str:
    """What someone says about your reputation before anything else ("" when
    it is unremarkable)."""
    pt, good_npc = tier(player_value), float(npc_value) > -30
    if pt == "Saintly":
        return ("The whole Vale speaks of your kindness. It is an honour." if good_npc
                else "You. The famous do-gooder. What do you want?")
    if pt == "Good":
        return "I've heard good things about you." if good_npc else ""
    if pt == "Evil":
        return ("I know what you've done. Keep your hands where I can see them."
                if good_npc else "Heh. I've heard of you. My kind of trouble.")
    if pt == "Villainous":
        return ("Gods... it's you. Please -- I don't want any trouble."
                if good_npc else "Our people speak your name with respect. And fear.")
    return ""


def consequences(value: float) -> List[str]:
    """Everything the player's alignment is doing right now, in plain words,
    for the Alignment page."""
    t = tier(value)
    v = float(value)
    out = []
    mult = bounty_mult(v)
    if mult != 1.0:
        out.append(f"The watch charges you x{mult:.2f} for every crime"
                   + (" -- they give you the benefit of the doubt." if mult < 1
                      else " -- they know your kind."))
    if v > 0:
        out.append(f"Defensive magic (healing, wards) works x{magic_power(v, 'defensive'):.2f}.")
    elif v < 0:
        out.append(f"Offensive magic strikes x{magic_power(v, 'offensive'):.2f}.")
    a_good, a_evil = affinity(v, 30), affinity(v, -45)
    if a_good:
        out.append(f"Decent folk feel {a_good:+d} toward you (prices, persuasion, "
                   "what they will say).")
    if a_evil:
        out.append(f"Brigands and cultists feel {a_evil:+d} toward you.")
    if kinship(v):
        out.append("Brigands and cultists take you for one of their own and "
                   "leave you be unless you strike first.")
    h = heartens(v)
    if h > 0:
        out.append("Frightened townsfolk take heart when you are near, and stand "
                   "instead of running.")
    elif h < 0:
        out.append("Townsfolk are more afraid when you are near, and flee sooner.")
    if t == "Neutral":
        out.append("No one has made up their mind about you yet.")
    return out


def player_deed(character, deed: str, day: int = 0, note: str = "") -> float:
    """Apply *deed* to the player character; returns how far it moved them."""
    if deed not in DEEDS:
        return 0.0
    before = float(getattr(character, "alignment", 0.0))
    after = shift(before, DEEDS[deed][0])
    character.alignment = after
    record(character.alignment_log, deed, before, after, day, note)
    return after - before


def npc_deed(props, deed: str) -> Tuple[float, bool]:
    """Apply *deed* to an NPC. Returns ``(new value, fell)`` -- *fell* is True
    the moment someone who was not an outlaw sinks below
    :data:`FALL_FROM_GRACE`."""
    if deed not in DEEDS or not isinstance(props, dict):
        return of_npc(props), False
    before = of_npc(props)
    after = shift(before, DEEDS[deed][0])
    props["alignment"] = after
    outlaw = str(props.get("faction") or "").lower() in EVIL_FACTIONS
    return after, (after < FALL_FROM_GRACE <= before and not outlaw)


def record(log: List, deed: str, before: float, after: float, day: int = 0,
           note: str = "", limit: int = 30) -> None:
    """Append a deed to an alignment log (newest last)."""
    log.append({"deed": deed, "text": note or DEEDS.get(deed, (0, deed))[1],
                "delta": round(after - before, 1), "day": int(day)})
    del log[:-limit]
