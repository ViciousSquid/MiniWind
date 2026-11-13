"""
A brief tutorial after character creation (experimental).

Four short pages, opened as Begin is pressed when the player has left "Show
tutorial" ticked: moving, the two hands, the quick slots, the inventory.
Each line names the controls the player is using *now* -- the keyboard and
mouse, or the gamepad -- by whichever sent the last input
(:mod:`game.controls`), and by the player's own bindings, so switching from
one to the other mid-page changes the page at once.

Experimental: nothing here appears unless settings.ini says so::

    [developer]
    enable_tutorial = true

The pages are plain data built per call (:func:`pages`); the window is
drawn by :mod:`game.ui.screens` (``"tutorial"``).
"""

from __future__ import annotations

from . import controls

#: settings.ini section and key that turn the tutorial on (either spelling
#: of the section: configparser's section names are case-sensitive).
SECTIONS = ("developer", "Developer", "DEVELOPER")
KEY = "enable_tutorial"


def enabled(config) -> bool:
    """Whether ``[developer] enable_tutorial`` is set (off when absent)."""
    if config is None:
        return False
    for section in SECTIONS:
        try:
            if config.has_option(section, KEY):
                return config.getboolean(section, KEY, fallback=False)
        except (AttributeError, TypeError, ValueError):
            return False
    return False


def _l(action: str) -> str:
    return controls.label(action)


def pages() -> list:
    """``[(title, [line, ...]), ...]`` in the controls in use this instant."""
    pad = controls.gamepad()
    if pad:
        moving = [
            "Left stick: walk. You face the way you go.",
            f"Click the left stick ({_l('sprint')}): sprint.",
            "Right stick: turn the camera.",
            f"{_l('sneak')}: sneak.   {_l('interact')}: talk, open, loot.",
        ]
        hands = [
            "Each hand has its own trigger.",
            "LT: your left hand.   RT: your right hand.",
            "Hold a trigger to draw a bow or wind up a blow; a shield's trigger holds block.",
            f"{_l('attack')}: strike with both hands.   {_l('block')}: block (hold).",
        ]
        quick = [
            "The strip along the bottom holds your quick items.",
            f"{_l('strip_prev')} / {_l('strip_next')}: pick a slot.   A: equip, drink or use it.",
            "To fill a slot: in the character window, highlight an item, press A to pick it up, "
            "and A again on a quick slot.",
            f"{_l('heal')}: drink a healing potion.",
        ]
        inventory = [
            f"{_l('character')}: the character window.   LB / RB: its tabs -- Inventory, Statistics...",
            "D-pad: move between items.   A: pick up and place them.",
            "B: close.",
        ]
    else:
        moving = [
            "W A S D: walk.   Shift: sprint.",
            "You face the mouse pointer.",
            "[ and ]: turn the camera.",
            f"{_l('sneak')}: sneak.   {_l('interact')}: talk, open, loot.",
        ]
        hands = [
            "Each hand has its own mouse button.",
            "Left button: your left hand.   Right button: your right hand.",
            "Hold a button to draw a bow or wind up a blow.",
            f"{_l('attack')}: strike with both hands.   {_l('block')}: block (hold).",
        ]
        quick = [
            "The strip along the bottom holds your quick items.",
            "1 - 9: take that slot in hand (hold Shift for the right hand).",
            "To fill a slot: drag an item onto it, or pick an item and press Assign.",
            f"{_l('heal')}: drink a healing potion.",
        ]
        inventory = [
            f"{_l('inventory')}: your inventory.   {_l('character')}: the character window.",
            "Drag things between your pack, your hands, your body and the strip.",
            "Double-click: use or equip.",
        ]
    return [("Moving", moving), ("Your two hands", hands),
            ("Quick slots", quick), ("Inventory", inventory)]


def hint(page: int, count: int) -> str:
    """The keys line along the window's foot."""
    nxt = "finish" if page >= count - 1 else "next"
    if controls.gamepad():
        return f"A {nxt}    D-pad ← back    B skip"
    return f"Enter {nxt}    ← back    Esc skip"
