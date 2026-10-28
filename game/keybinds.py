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

**Gamepad buttons** are bound the same way, beside the keys (``[PAD]``): each
action has a pad button as well as its key, and a few controls only a pad
needs (sprint on a stick click, the strip on D-pad left/right) are listed with
them. The triggers are the hands' attacks and nothing else, so they are not
offered. :mod:`game.gamepad` presses an action's key
when its button is pressed, so a rebinding of either takes effect for both.
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
PAD_SECTION = "PAD"

#: The gamepad's buttons an action may be bound to, by the names the
#: bindings use (SDL's standard controller layout, written as on an Xbox
#: pad). The triggers are not among them: LT and RT are only ever the left-
#: and right-hand attack (game.gamepad).
PAD_BUTTONS = ("a", "b", "x", "y", "lb", "rb", "back", "start", "ls", "rs",
               "dpad_up", "dpad_down", "dpad_left", "dpad_right")
#: Controls only a gamepad needs: (action, label, default button).
PAD_ONLY = (
    ("sprint", "Sprint (hold)", "ls"),
    ("strip_prev", "Previous strip slot", "dpad_left"),
    ("strip_next", "Next strip slot", "dpad_right"),
    ("pause", "Pause menu", "start"),
)
#: Y opens Statistics on the character sheet; LB / RB reach its other tabs.
#: An empty button leaves an action off the pad's direct shortcuts.
PAD_DEFAULTS = {
    "attack": "x", "block": "b", "next_spell": "lb", "heal": "dpad_down",
    "sneak": "rs", "interact": "a", "inventory": "", "character": "y",
    "journal": "", "spells": "", "levelup": "rb", "map": "back",
    "quest": "dpad_up",
    **{action: button for action, _label, button in PAD_ONLY},
}
#: The pad's own state (applied from the config by :func:`apply`).
PAD = dict(PAD_DEFAULTS)


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
    """Point the host's key constants at the bindings in *config*, and the
    pad's buttons (:data:`PAD`)."""
    from . import host
    keys = current(config)
    for action, _label, const, _default in ACTIONS:
        setattr(host, const, keys[action])
    PAD.clear()
    PAD.update(current_pad(config))


def current_pad(config) -> dict:
    """``{action: button}``: the player's pad choices over the defaults."""
    buttons = dict(PAD_DEFAULTS)
    if config is None:
        return buttons
    for action in buttons:
        try:
            value = config.get(PAD_SECTION, action, fallback=None)
        except Exception:
            value = None
        if value is not None and (value in PAD_BUTTONS or value == ""):
            buttons[action] = value
    return buttons


def bind_pad(config, action, button, save=None) -> str:
    """Bind *action* to pad *button*; an action already on it swaps onto this
    one's old button (or goes unbound). Returns the action swapped, or ''."""
    if action not in PAD_DEFAULTS or button not in PAD_BUTTONS:
        return ""
    buttons = current_pad(config)
    old = buttons.get(action, "")
    swapped = next((a for a, b in buttons.items() if b == button and a != action), "")
    if config is not None:
        if not config.has_section(PAD_SECTION):
            config.add_section(PAD_SECTION)
        config.set(PAD_SECTION, action, button)
        if swapped:
            config.set(PAD_SECTION, swapped, old)
        if save is not None:
            try:
                save()
            except Exception:
                pass
    else:
        PAD[action] = button
        if swapped:
            PAD[swapped] = old
        return swapped
    apply(config)
    return swapped


def key_binding(action) -> str:
    """The key *action* is on now."""
    from . import host
    const = next((c for a, _l, c, _d in ACTIONS if a == action), None)
    return getattr(host, const, "") if const else ""


def pad_binding(action) -> str:
    """The pad button *action* is on now ('' for none)."""
    return PAD.get(action, "")


def pad_action(button) -> str:
    """The action pad *button* is bound to, or ''."""
    return next((a for a, b in PAD.items() if b == button), "")


def pad_label(action) -> str:
    """Every pad-bindable action's label, for the bindings page."""
    for a, lab, _c, _d in ACTIONS:
        if a == action:
            return lab
    return next((lab for a, lab, _b in PAD_ONLY if a == action), action)


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
    """Every action back on its default key and pad button."""
    if config is not None and (config.has_section(SECTION)
                               or config.has_section(PAD_SECTION)):
        for section in (SECTION, PAD_SECTION):
            if config.has_section(section):
                config.remove_section(section)
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
