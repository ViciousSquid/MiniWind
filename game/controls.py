"""
Which controls the player is using, and what to call each control.

Keyboard and mouse and a gamepad both work at all times. What the game
*shows* -- "Press E to talk", "Press A to talk" -- follows whichever of them
sent the last input: a pad button or a stick pushed past its dead zone makes
the prompts the pad's (:func:`use` ``GAMEPAD``, from :mod:`game.gamepad`), a
key press, a click or a real mouse move makes them the keyboard's again (the
application-wide filter :func:`install_tracker` installs). A pad that is only
plugged in changes nothing until it is used.

The names follow the player's own bindings (:mod:`game.keybinds`): an action
moved to another key or button is shown on its new one.
"""

from __future__ import annotations

KEYBOARD = "keyboard"
GAMEPAD = "gamepad"

_mode = KEYBOARD
#: Set while :mod:`game.gamepad` is delivering the Qt events it synthesises,
#: so they do not count as the keyboard and mouse being used.
synthesizing = 0
#: Where the gamepad last put the mouse cursor (global x, y): the window
#: system's move event for it is not the mouse being used either.
warped_to = None

#: Gamepad buttons as the prompts write them (Xbox names, the commonest).
PAD_LABELS = {
    "a": "A", "b": "B", "x": "X", "y": "Y",
    "lb": "LB", "rb": "RB", "lt": "LT", "rt": "RT",
    "back": "Back", "start": "Start", "ls": "L3", "rs": "R3",
    "dpad_up": "D-pad ↑", "dpad_down": "D-pad ↓",
    "dpad_left": "D-pad ←", "dpad_right": "D-pad →",
}

#: Controls that are fixed rather than bound, by name: the keyboard's and the
#: pad's word for each.
FIXED = {
    "confirm": ("Enter", "A"),
    "back": ("Esc", "B"),
    "click": ("Click", "A"),
    "right_click": ("Right-click", "X"),
    "scroll": ("Wheel", "R-stick"),
    "pan": ("Drag", "L-stick"),
    "home": ("Space", "Y"),
    "tabs": ("I / C / J / P / M", "LB / RB"),
    "select": ("↑ / ↓", "D-pad"),
}


#: Shakes the pad: ``rumble(low, high, ms)`` (set by game.gamepad.install).
_rumbler = None


def set_rumbler(fn) -> None:
    global _rumbler
    _rumbler = fn


def rumble(low: float, high: float, ms: int) -> bool:
    """Shake the pad, if it is what the player is using (a pad lying idle
    while the keyboard plays stays still). True if it shook."""
    if _rumbler is None or not gamepad():
        return False
    try:
        return bool(_rumbler(low, high, ms))
    except Exception:
        return False


def mode() -> str:
    return _mode


def gamepad() -> bool:
    return _mode == GAMEPAD


def use(which: str) -> None:
    """The last input came from *which* (:data:`KEYBOARD` or :data:`GAMEPAD`)."""
    global _mode
    _mode = GAMEPAD if which == GAMEPAD else KEYBOARD


def label(action: str) -> str:
    """What to press for a bound *action* (``"interact"``, ``"quest"`` ...), on
    the controls in use: its key (``E``) or its pad button (``A``); for a
    fixed control (:data:`FIXED`), that control's name."""
    if action in FIXED:
        key, pad = FIXED[action]
        return pad if gamepad() else key
    from . import keybinds
    if gamepad():
        button = keybinds.pad_binding(action)
        return PAD_LABELS.get(button, button.upper()) if button else "—"
    return keybinds.label(keybinds.key_binding(action))


def press(action: str) -> str:
    """``"Press E"`` / ``"Press A"``: the start of a prompt."""
    return f"Press {label(action)}"


def install_tracker(app) -> object:
    """Watch *app*'s real keyboard and mouse input: any of it makes the
    prompts the keyboard's. Returns the filter (keep a reference)."""
    from PyQt5.QtCore import QEvent, QObject

    kinds = {QEvent.KeyPress, QEvent.MouseButtonPress, QEvent.MouseButtonDblClick,
             QEvent.Wheel, QEvent.MouseMove}

    class _Tracker(QObject):
        last = None

        def eventFilter(self, obj, event):
            kind = event.type()
            if kind not in kinds or synthesizing or _mode == KEYBOARD:
                if kind == QEvent.MouseMove and not synthesizing:
                    self.last = _global(event)
                return False
            if kind == QEvent.KeyPress and event.isAutoRepeat():
                return False
            if kind == QEvent.MouseMove:
                # Only a real move of the mouse: not the cursor the pad moved,
                # not the view re-centring a captured one.
                here = _global(event)
                if here is None:
                    return False
                if warped_to is not None and abs(here[0] - warped_to[0]) <= 2 \
                        and abs(here[1] - warped_to[1]) <= 2:
                    return False
                last, self.last = self.last, here
                if last is None or abs(here[0] - last[0]) + abs(here[1] - last[1]) < 6:
                    return False
            use(KEYBOARD)
            return False

    tracker = _Tracker(app)
    app.installEventFilter(tracker)
    return tracker


def _global(event):
    try:
        p = event.globalPos()
        return (p.x(), p.y())
    except Exception:
        return None
