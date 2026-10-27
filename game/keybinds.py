"""
Rebindable keys: every game action the keyboard drives, its default key, and
the player's own choice from the pause menu's Options -> Key bindings.

Choices are kept in the editor's settings (``[KEYS]``, one ``action = key``
line each) and applied by rebinding the host's key constants
(:mod:`game.host` reads ``K_ATTACK`` and the rest at the moment it handles
input, so a change takes effect at once). Keys are named as the host names
them: a letter, a digit, or ``space`` / ``tab``.

Movement (W A S D), sprint (Shift), use (E, the engine's), the number keys of
the inventory strip and Escape are not listed: they are the engine's or fixed.
"""

from __future__ import annotations

#: (action, label, host constant, default key), in the order they are listed.
ACTIONS = (
    ("attack", "Attack (both hands)", "K_ATTACK", "f"),
    ("block", "Block (hold)", "K_BLOCK", "b"),
    ("next_spell", "Next spell", "K_NEXT_SPELL", "x"),
    ("heal", "Drink a healing potion", "K_HEAL", "h"),
    ("sneak", "Sneak", "K_SNEAK", "v"),
    ("interact", "Talk / trade / open", "K_INTERACT", "e"),
    ("inventory", "Inventory", "K_INVENTORY", "i"),
    ("character", "Character sheet", "K_CHARACTER", "c"),
    ("journal", "Journal", "K_JOURNAL", "j"),
    ("spells", "Spellbook", "K_SPELLS", "p"),
    ("levelup", "Level up", "K_LEVELUP", "l"),
    ("map", "Map", "K_MAP", "m"),
    ("quest", "Current quest", "K_QUEST", "q"),
)

#: Keys that may be bound: the host knows these names.
BINDABLE = tuple("abcdefghijklmnopqrstuvwxyz") + tuple(str(d) for d in range(10)) + ("space", "tab")
#: Keys never offered: they walk.
RESERVED = ("w", "a", "s", "d")

SECTION = "KEYS"


def defaults() -> dict:
    return {action: key for action, _label, _const, key in ACTIONS}


def current(config) -> dict:
    """``{action: key}``: the player's choices over the defaults."""
    keys = defaults()
    if config is None:
        return keys
    for action in keys:
        try:
            value = config.get(SECTION, action, fallback=None)
        except Exception:
            value = None
        if value and value in BINDABLE and value not in RESERVED:
            keys[action] = value
    return keys


def apply(config) -> None:
    """Point the host's key constants at the bindings in *config*."""
    from . import host
    keys = current(config)
    for action, _label, const, _default in ACTIONS:
        setattr(host, const, keys[action])


def bind(config, action, key, save=None) -> str:
    """Bind *action* to *key* (a bindable name). An action already on that key
    swaps onto this one's old key, so no key ever does two things. Returns
    the action it swapped with, or ''."""
    if key not in BINDABLE or key in RESERVED:
        return ""
    keys = current(config)
    old = keys.get(action)
    swapped = next((a for a, k in keys.items() if k == key and a != action), "")
    if config is not None:
        if not config.has_section(SECTION):
            config.add_section(SECTION)
        config.set(SECTION, action, key)
        if swapped and old:
            config.set(SECTION, swapped, old)
        if save is not None:
            try:
                save()
            except Exception:
                pass
    apply(config)
    return swapped


def reset(config, save=None) -> None:
    """Every action back on its default key."""
    if config is not None and config.has_section(SECTION):
        config.remove_section(SECTION)
        if save is not None:
            try:
                save()
            except Exception:
                pass
    apply(config)


def key_name(qt_key) -> str:
    """The bindable name of a Qt key code, or ''."""
    if 0x41 <= qt_key <= 0x5A:
        return chr(qt_key).lower()
    if 0x30 <= qt_key <= 0x39:
        return chr(qt_key)
    return {0x20: "space", 0x01000001: "tab"}.get(qt_key, "")


def label(key) -> str:
    return key.upper() if len(key) == 1 else key.capitalize()
