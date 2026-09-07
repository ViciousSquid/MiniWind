"""
What an actor can actually fight with, and which of those it should use now.

An NPC's ``attack_style`` used to be a single authored string: a guard with a
sword and a bow in its pack fought the whole battle one way, whichever way the
map happened to say. This module lets an actor switch — close in and draw the
blade, back off and loose an arrow or a spell — but only between the things it
genuinely carries: a weapon in its inventory (or equipped), or a spell in its
assigned list.

Performance is the constraint that shapes it. There is deliberately **no
per-tick decision**:

* :func:`build_loadout` scans the inventory and spells. That is the expensive
  part, and it only runs when an actor crosses the melee-range boundary — a
  handful of times in a fight, not thirty times a second. Rebuilding on that
  edge (rather than caching forever) also means a kit change mid-fight is picked
  up on its own, with no invalidation bookkeeping and no polling.
* :func:`choose_style` is a few dict lookups on the already-built loadout.
* The AI's per-tick cost is one comparison: has the distance band changed?

The authored style always wins when there is nothing to choose between — an
actor with one option keeps behaving exactly as the map said.
"""

from __future__ import annotations

MELEE = "melee"
BOW = "bow"
MAGIC = "magic"

#: Ranged styles, best first. A caster with both a staff and a bow leads with
#: the spell — it is the more characterful choice and usually the stronger one.
RANGED_PREFERENCE = (MAGIC, BOW)

#: Weapon ``kind`` (from the item database) → the attack style it drives.
_KIND_STYLES = {
    "melee": MELEE,
    "bow": BOW,
    "staff": MAGIC,
}


def _item_style(item_id):
    """The attack style a weapon id drives, or None if it is not a weapon.

    Resolved through the game's item database when there is one. The engine runs
    without it (a map with no MiniWind game layer), in which case no inventory
    weapon is recognised and the actor simply keeps its authored style.
    """
    if not item_id:
        return None
    try:
        from game.rpg import items
    except Exception:
        return None
    definition = items.get(str(item_id))
    if definition is None or definition.category != items.WEAPON:
        return None
    return _KIND_STYLES.get(str(definition.get("kind", "")).lower())


def _stack_id(stack):
    """The item id out of an inventory entry, which may be a dict or a bare id."""
    if isinstance(stack, dict):
        return stack.get("id") or stack.get("item_id")
    if isinstance(stack, str):
        return stack
    return None


def build_loadout(properties):
    """Everything *properties* describes an actor as being able to fight with.

    Returns ``{style: weapon_id_or_None, ...}`` for each style available, plus
    a ``"default"`` key holding the authored style to fall back on. A style maps
    to None when the actor has it without a weapon behind it — spells need no
    weapon, and a creature's claws are its authored melee.

    The cold path: an inventory scan. Called only on a distance-band change, see
    the module docstring.
    """
    if not isinstance(properties, dict):
        return {"default": MELEE}

    authored = str(properties.get("attack_style", "") or "").lower()
    loadout = {"default": authored or MELEE}
    # The authored style is always available: it is what the map promised this
    # actor can do, whether or not an item backs it (claws, fangs, a hex).
    if authored in (MELEE, BOW, MAGIC):
        loadout[authored] = properties.get("equipped_weapon") or None

    # Assigned spells make magic available with no weapon needed.
    spells = properties.get("spells")
    if isinstance(spells, list) and spells:
        loadout.setdefault(MAGIC, properties.get("equipped_weapon")
                           if _item_style(properties.get("equipped_weapon")) == MAGIC
                           else None)

    # Anything carried that is a weapon: what is equipped, then the pack.
    equipped = properties.get("equipped_weapon")
    style = _item_style(equipped)
    if style:
        loadout[style] = equipped

    inventory = properties.get("inventory")
    if isinstance(inventory, list):
        for stack in inventory:
            item_id = _stack_id(stack)
            style = _item_style(item_id)
            # Don't demote a weapon already in hand for the same style.
            if style and loadout.get(style) is None:
                loadout[style] = item_id
            elif style and style not in loadout:
                loadout[style] = item_id
    return loadout


def has_choice(loadout):
    """True when this actor has more than one way to fight.

    An actor with a single option is left exactly as authored — there is nothing
    to switch to, so nothing about its behaviour should change.
    """
    return sum(1 for style in (MELEE, BOW, MAGIC) if style in loadout) > 1


def choose_style(loadout, in_melee):
    """Which style to use at this range: the warm path, a few dict lookups.

    Inside melee reach an actor draws whatever it can hit with; outside it, it
    reaches for a spell or a bow. Where it has no such option — an archer shoved
    to point-blank range, a swordsman whose target is across the square — it
    keeps what it has and closes or shoots as before.
    """
    if not has_choice(loadout):
        return loadout.get("default", MELEE)
    if in_melee:
        if MELEE in loadout:
            return MELEE
    else:
        for style in RANGED_PREFERENCE:
            if style in loadout:
                return style
    # Nothing suited to this range: fall back to anything it does carry, the
    # authored style first so a map's intent still shows through.
    default = loadout.get("default", MELEE)
    if default in loadout:
        return default
    for style in (MELEE,) + RANGED_PREFERENCE:
        if style in loadout:
            return style
    return default


def weapon_for(loadout, style):
    """The weapon id backing *style*, or '' when the style needs none."""
    return loadout.get(style) or ""
