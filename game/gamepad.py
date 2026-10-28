"""
MiniWind controller input through SDL's portable game-controller mapping.

The pad is read through SDL's game-controller layer (``pygame._sdl2.
controller``, part of pygame-ce -- the same SDL the engine already runs, in
the same process), which names the buttons the same on every pad: A B X Y,
the shoulders, the triggers, the sticks, the D-pad. Movement is published to
the logic thread; game and menu actions are queued through the same path as
clicks. Qt events serve the engine's pause menu and mouse fire controls.
Keyboard and controller work side by side; prompts follow whichever was used last
(:mod:`game.controls`).

**In play** (no window wanting the pointer):

* left stick: analog camera-relative walking, facing the direction of travel;
  left stick click: sprint (Shift, held);
* right stick: orbit the camera, unless GAME.camera_rotation is false;
* LT / RT: the left / right hand's attack -- the left / right mouse button,
  held as long as the trigger is, so a bow draws and a fist gathers its
  blow. A shield's trigger holds block instead of bashing;
* the face buttons, D-pad, Back and the right stick click: the actions bound
  to them in Options -> Key bindings (:data:`game.keybinds.PAD`), each
  dispatching its action -- A talks, opens and loots, B blocks,
  X attacks, Y opens the inventory...;
* D-pad left / right: highlight the previous / next occupied quickbar slot;
  A equips, consumes or uses it. Browsing takes priority over nearby interaction;
* Start: the pause menu (Esc).

**In a menu or window** (the Statistics window, a conversation, a chest, the
pause menu, character creation...): D-pad navigates, A confirms, B goes back.
Dialogs highlight responses; inventory highlights the painted slots and actions,
with A picking up and placing items. LB / RB turn the Statistics window's tabs.
The sticks still move the pointer and scroll in other windows. In the pause menu
and on the death screen A is Enter. Picking a lock, the left stick lifts
the pick, RT held is tension, Y the guide and B leaves; the pad shakes when
the pick finds a pin's sweet spot.

Testable without a pad or a window: :class:`GamepadInput` reads a *source*
(anything with ``read() -> PadState or None``) and sends through a *sink*
(``key``, ``mouse``, ``move``, ``wheel``, ``look`` and the mode queries);
:class:`QtSink` is the real one, :class:`SdlPad` the real pad.
"""

from __future__ import annotations

import math
import time
from typing import Dict, FrozenSet, Optional

from . import controls, keybinds

#: Stick dead zone, and how far a trigger must go to count as pressed.
DEAD_ZONE = 0.22
TRIGGER_ON = 0.45
TRIGGER_OFF = 0.3
#: How far the left stick must lean to walk that way.
WALK_ON = 0.38
#: The triggers: the left- and right-hand attack, and only that (they are
#: not bindable: game.keybinds).
TRIGGER_HANDS = {"lt": "left_hand", "rt": "right_hand"}
#: Look speed (mouse pixels a second at full lean), and the curve that keeps
#: small leans fine.
LOOK_SPEED = 900.0
LOOK_CURVE = 1.6
#: How fast the left stick lifts a lock pick at full lean (degrees a
#: second; the arrow keys' rate is 36).
LOCKPICK_SPEED = 60.0
#: Pointer speed in menus (pixels a second at full lean).
CURSOR_SPEED = 900.0
#: Scroll: wheel notches a second at full lean.
SCROLL_RATE = 8.0
#: Held D-pad repeats like a held key.
REPEAT_DELAY = 0.4
REPEAT_RATE = 0.09


class PadState:
    """One reading of the pad: the buttons down, and the axes in -1..1
    (triggers 0..1)."""

    __slots__ = ("buttons", "axes")

    def __init__(self, buttons=(), axes=None):
        self.buttons: FrozenSet[str] = frozenset(buttons)
        self.axes: Dict[str, float] = dict(axes or {})

    def axis(self, name) -> float:
        return float(self.axes.get(name, 0.0))


class SdlPad:
    """The first game controller SDL knows -- found again whenever one is
    plugged in, during play as at startup, and let go when it is unplugged.

    SDL only notices a pad arriving or leaving when its events are pumped.
    The engine pumps them only if it found a pad at startup, so this pumps
    them itself on every read (pumping twice is harmless). It looks for a pad
    only when there may be a new one -- at startup, and when SDL reports a
    device added or one removed -- never on a timer; the other pad events it
    throws away, since nothing reads SDL's queue (the pad's state is read
    directly) and they would only pile up."""

    _BUTTONS = (("a", "CONTROLLER_BUTTON_A"), ("b", "CONTROLLER_BUTTON_B"),
                ("x", "CONTROLLER_BUTTON_X"), ("y", "CONTROLLER_BUTTON_Y"),
                ("lb", "CONTROLLER_BUTTON_LEFTSHOULDER"),
                ("rb", "CONTROLLER_BUTTON_RIGHTSHOULDER"),
                ("back", "CONTROLLER_BUTTON_BACK"), ("start", "CONTROLLER_BUTTON_START"),
                ("ls", "CONTROLLER_BUTTON_LEFTSTICK"), ("rs", "CONTROLLER_BUTTON_RIGHTSTICK"),
                ("dpad_up", "CONTROLLER_BUTTON_DPAD_UP"),
                ("dpad_down", "CONTROLLER_BUTTON_DPAD_DOWN"),
                ("dpad_left", "CONTROLLER_BUTTON_DPAD_LEFT"),
                ("dpad_right", "CONTROLLER_BUTTON_DPAD_RIGHT"))
    _AXES = (("lx", "CONTROLLER_AXIS_LEFTX"), ("ly", "CONTROLLER_AXIS_LEFTY"),
             ("rx", "CONTROLLER_AXIS_RIGHTX"), ("ry", "CONTROLLER_AXIS_RIGHTY"),
             ("lt", "CONTROLLER_AXIS_TRIGGERLEFT"), ("rt", "CONTROLLER_AXIS_TRIGGERRIGHT"))
    def __init__(self):
        self._pad = None
        #: A pad may have arrived: look for one on the next read.
        self._look = True
        self._ok = False
        try:
            import pygame
            from pygame._sdl2 import controller
            pygame.joystick.init()       # the engine's view has, too: harmless
            controller.init()
            self._pygame, self._controller = pygame, controller
            self._buttons = [(name, getattr(pygame, const)) for name, const in self._BUTTONS]
            def kinds(*names):
                return [getattr(pygame, n) for n in names if hasattr(pygame, n)]
            #: Devices coming and going: the only time a pad is looked for.
            self._device_events = kinds("JOYDEVICEADDED", "JOYDEVICEREMOVED",
                                        "CONTROLLERDEVICEADDED", "CONTROLLERDEVICEREMOVED")
            self._pad_events = kinds("JOYAXISMOTION", "JOYBALLMOTION", "JOYHATMOTION",
                                     "JOYBUTTONDOWN", "JOYBUTTONUP", "CONTROLLERAXISMOTION",
                                     "CONTROLLERBUTTONDOWN", "CONTROLLERBUTTONUP",
                                     "CONTROLLERDEVICEREMAPPED")
            self._axes = [(name, getattr(pygame, const)) for name, const in self._AXES]
            self._ok = True
        except Exception as exc:          # no SDL game-controller support
            print(f"[MiniWind] gamepad unavailable: {exc}")

    @property
    def name(self) -> str:
        try:
            return str(self._pad.name) if self._pad is not None else ""
        except Exception:
            return ""

    def _find(self) -> None:
        self._look = False
        try:
            # The device list is current as of the engine's last event pump.
            for index in range(self._pygame.joystick.get_count()):
                if self._controller.is_controller(index):
                    self._pad = self._controller.Controller(index)
                    print(f"[MiniWind] gamepad: {self.name}")
                    return
        except Exception:
            self._pad = None

    def _pump(self) -> None:
        try:
            self._pygame.event.pump()
            if self._pygame.event.get(self._device_events):
                self._look = True
            self._pygame.event.clear(self._pad_events)
        except Exception:
            pass

    def read(self) -> Optional[PadState]:
        if not self._ok:
            return None
        self._pump()
        if self._pad is not None and not self._attached():
            print("[MiniWind] gamepad disconnected")
            self._pad = None
            self._look = True               # another may still be plugged in
        if self._pad is None:
            if not self._look:
                return None
            self._find()
            if self._pad is None:
                return None
        try:
            buttons = [name for name, b in self._buttons if self._pad.get_button(b)]
            axes = {}
            for name, a in self._axes:
                value = self._pad.get_axis(a) / 32767.0
                axes[name] = max(-1.0, min(1.0, value))
            return PadState(buttons, axes)
        except Exception:
            self._pad = None
            return None

    def rumble(self, low: float, high: float, ms: int) -> bool:
        """Shake the pad (*low* / *high* motor strength 0..1) for *ms*
        milliseconds; False when it cannot."""
        try:
            return bool(self._pad is not None and self._pad.rumble(low, high, int(ms)))
        except Exception:
            return False

    def _attached(self) -> bool:
        try:
            return bool(self._pad.attached())
        except Exception:
            return False


def _stick(x, y, dead=DEAD_ZONE):
    """A stick reading with its dead zone taken out, rescaled to 0..1."""
    mag = math.hypot(x, y)
    if mag <= dead:
        return 0.0, 0.0
    scale = min(1.0, (mag - dead) / (1.0 - dead)) / mag
    return x * scale, y * scale


#: Qt key names the pad presses for a bound action's key.
def _qt_key(name: str):
    from PyQt5.QtCore import Qt
    if len(name) == 1:
        return getattr(Qt, f"Key_{name.upper()}")
    return {"space": Qt.Key_Space, "tab": Qt.Key_Tab, "escape": Qt.Key_Escape,
            "return": Qt.Key_Return, "shift": Qt.Key_Shift, "up": Qt.Key_Up,
            "down": Qt.Key_Down, "left": Qt.Key_Left, "right": Qt.Key_Right}[name]


class GamepadInput:
    """Turns pad readings into the keyboard's and mouse's events (see the
    module docstring). :meth:`poll` once a frame."""

    #: Bound actions that are held as long as their button is (the rest are
    #: one press per press of the button).
    HELD = ("block", "sprint")

    def __init__(self, source, sink, clock=time.monotonic):
        self.source = source
        self.sink = sink
        self._clock = clock
        self._last = PadState()
        self._last_time = None
        self._held_keys = set()          # Qt keys this layer holds down
        self._held_mouse = set()         # "left" / "right" held in play
        self._menu_mouse = False         # A holding the left button in a menu
        self._triggers = {"lt": False, "rt": False}
        self._repeat = {}                # D-pad button -> next repeat time
        self._scroll = 0.0
        self._was_menu = None
        self._lockpick_tension = False

    # -- the loop -----------------------------------------------------------
    def poll(self) -> None:
        now = self._clock()
        # A frame's worth on the first reading, so it already counts.
        dt = (1.0 / 60.0 if self._last_time is None
              else max(0.0, min(0.1, now - self._last_time)))
        self._last_time = now
        state = self.source.read()
        if state is None:
            self.release_all()
            self._last = PadState()
            return
        state = self._with_triggers(state)
        enabled = getattr(self.sink, "enabled", lambda: True)()
        if not enabled:
            self.release_all()
            self._last = state
            return
        if self._active(state):
            controls.use(controls.GAMEPAD)
        menu = self.sink.menu_open()
        context = getattr(self.sink, "context", lambda: menu)()
        if context != self._was_menu:
            self.release_all()           # nothing held carries across
            self._was_menu = context
        pressed = state.buttons - self._last.buttons
        released = self._last.buttons - state.buttons
        if menu:
            self._menu(state, pressed, released, dt, now)
        else:
            self._play(state, pressed, released, dt, now)
        self._last = state

    def _with_triggers(self, state) -> PadState:
        """The triggers as buttons ``lt`` / ``rt``: down past
        :data:`TRIGGER_ON`, up again only below :data:`TRIGGER_OFF`, so a
        trigger held near the line does not chatter."""
        for name in ("lt", "rt"):
            value = state.axis(name)
            if self._triggers[name]:
                self._triggers[name] = value > TRIGGER_OFF
            else:
                self._triggers[name] = value >= TRIGGER_ON
        extra = {name for name, on in self._triggers.items() if on}
        return PadState(state.buttons | extra, state.axes) if extra else state

    @staticmethod
    def _active(state) -> bool:
        if state.buttons:
            return True
        lx, ly = _stick(state.axis("lx"), state.axis("ly"))
        rx, ry = _stick(state.axis("rx"), state.axis("ry"))
        return bool(lx or ly or rx or ry)

    def release_all(self) -> None:
        cancel = getattr(self.sink, "cancel_hands", None)
        if cancel is not None:
            cancel()
        walk = getattr(self.sink, "walk", None)
        if walk is not None:
            walk(None)
        for key in list(self._held_keys):
            self._key(key, False)
        for button in list(self._held_mouse):
            self._hand(button, False)
        self._held_mouse.clear()
        if self._menu_mouse:
            self.sink.mouse("left", False, play=False)
            self._menu_mouse = False
        self._repeat.clear()
        if self._lockpick_tension:
            self.sink.lockpick("tension_off")
            self._lockpick_tension = False

    def _key(self, key, down) -> None:
        if down:
            if key in self._held_keys:
                return
            self._held_keys.add(key)
        else:
            if key not in self._held_keys:
                return
            self._held_keys.discard(key)
        self.sink.key(key, down)

    def _tap(self, key) -> None:
        self.sink.key(key, True)
        self.sink.key(key, False)

    # -- in play -------------------------------------------------------------
    def _play(self, state, pressed, released, dt, now) -> None:
        # The native sink keeps analog movement independent of sprite facing.
        lx, ly = _stick(state.axis("lx"), state.axis("ly"))
        walk = getattr(self.sink, "walk", None)
        if walk is not None:
            walk((lx, ly))
        else:
            for key, on in (("w", ly < -WALK_ON), ("s", ly > WALK_ON),
                            ("a", lx < -WALK_ON), ("d", lx > WALK_ON)):
                self._key(_qt_key(key), on)
        # Look: the right stick is the mouse.
        rx, ry = _stick(state.axis("rx"), state.axis("ry"))
        if rx or ry:
            def curve(v):
                return math.copysign(abs(v) ** LOOK_CURVE, v)
            self.sink.look(curve(rx) * LOOK_SPEED * dt, curve(ry) * LOOK_SPEED * dt)
        # The triggers are the hands' attacks, always: each holds its mouse
        # button as long as it is pulled. The other buttons do what they are
        # bound to.
        for button in sorted(pressed, key=lambda b: (b == "a", b)):
            action = TRIGGER_HANDS.get(button) or keybinds.pad_action(button)
            self._action(action, True)
            if action in ("strip_prev", "strip_next"):
                self._repeat[button] = now + REPEAT_DELAY
        for button in released:
            self._action(TRIGGER_HANDS.get(button) or keybinds.pad_action(button), False)
        for button, due in list(self._repeat.items()):
            if button not in state.buttons:
                del self._repeat[button]
            elif now >= due:
                self._action(keybinds.pad_action(button), True)
                self._repeat[button] = now + REPEAT_RATE

    def _action(self, action, down) -> None:
        if not action:
            return
        handler = getattr(self.sink, "play_action", None)
        if handler is not None and handler(action, down):
            return
        if action in ("left_hand", "right_hand"):
            button = "left" if action == "left_hand" else "right"
            if down:
                self._held_mouse.add(button)
            elif button not in self._held_mouse:
                return
            else:
                self._held_mouse.discard(button)
            self._hand(button, down)
            return
        if action in ("strip_prev", "strip_next"):
            if down:
                self.sink.cycle_strip(-1 if action == "strip_prev" else 1)
            return
        if action == "pause":
            if down:
                self._tap(_qt_key("escape"))
            return
        if action == "sprint":
            self._key(_qt_key("shift"), down)
            return
        if action == "interact" and down:
            activate = getattr(self.sink, "activate_strip", None)
            if activate is not None and activate():
                return
        key = keybinds.key_binding(action)
        if not key:
            return
        qt = _qt_key(key)
        if action in self.HELD:
            self._key(qt, down)
        elif down:
            self._tap(qt)
            if action == "interact" and key != "e":
                self._tap(_qt_key("e"))  # the engine's own use key, for doors

    def _hand(self, button, down):
        handler = getattr(self.sink, "hand", None)
        if handler is not None:
            handler(button, down)
        else:
            self.sink.mouse(button, down, play=True)

    def _menu_key(self, name):
        handler = getattr(self.sink, "menu_action", None)
        if handler is not None and handler(name):
            return True
        return False

    # -- in a menu ------------------------------------------------------------
    def _lockpicking(self, state, pressed, released, dt) -> None:
        """The lockpicking minigame: the left stick lifts the pick (a light
        lean for fine work), RT held is tension, Y the guide, B leaves."""
        _lx, ly = _stick(state.axis("lx"), state.axis("ly"))
        if ly:
            self.sink.lockpick("move", -ly * LOCKPICK_SPEED * dt)
        if "rt" in pressed:
            self.sink.lockpick("tension_on")
            self._lockpick_tension = True
        if "rt" in released:
            self.sink.lockpick("tension_off")
            self._lockpick_tension = False
        if "y" in pressed:
            self.sink.lockpick("assist")
        if pressed & {"b", "start"}:
            if not self._menu_key("escape"):
                self._tap(_qt_key("escape"))

    def _menu(self, state, pressed, released, dt, now) -> None:
        if self.sink.lockpicking():
            self._lockpicking(state, pressed, released, dt)
            return
        if self.sink.capturing_pad():
            # Options -> Key bindings is waiting for a button: this is it.
            for button in sorted(pressed):
                self.sink.capture_pad(button)
                return
            return
        keyboard_menu = self.sink.keyboard_menu()
        lx, ly = _stick(state.axis("lx"), state.axis("ly"))
        if (lx or ly) and not keyboard_menu:
            self.sink.move(lx * CURSOR_SPEED * dt, ly * CURSOR_SPEED * dt,
                           left_held=self._menu_mouse)
        _rx, ry = _stick(state.axis("rx"), state.axis("ry"))
        if ry:
            self._scroll += -ry * SCROLL_RATE * dt
            while abs(self._scroll) >= 1.0:
                step = 1 if self._scroll > 0 else -1
                self._scroll -= step
                self.sink.wheel(step)
        else:
            self._scroll = 0.0
        for button in sorted(pressed, key=lambda b: (b == "a", b)):
            if button == "a":
                if self._menu_key("return"):
                    pass
                elif keyboard_menu:
                    self._tap(_qt_key("return"))
                else:
                    self._menu_mouse = True
                    self.sink.mouse("left", True, play=False)
            elif button == "x" and not keyboard_menu:
                self.sink.mouse("right", True, play=False)
                self.sink.mouse("right", False, play=False)
            elif button in ("b", "start"):
                if not self._menu_key("escape"):
                    self._tap(_qt_key("escape"))
            elif button in ("lb", "rb"):
                self.sink.turn_tab(-1 if button == "lb" else 1)
            elif button.startswith("dpad_"):
                if not self._menu_key(button[5:]):
                    self._tap(_qt_key(button[5:]))
                self._repeat[button] = now + REPEAT_DELAY
            elif button == keybinds.pad_binding("inventory"):
                # The button that opened the inventory closes it again.
                if not self._menu_key("escape"):
                    self._tap(_qt_key(keybinds.key_binding("inventory")))
        if "a" in released and self._menu_mouse:
            self._menu_mouse = False
            self.sink.mouse("left", False, play=False)
        for button, due in list(self._repeat.items()):
            if button not in state.buttons:
                del self._repeat[button]
            elif now >= due:
                if not self._menu_key(button[5:]):
                    self._tap(_qt_key(button[5:]))
                self._repeat[button] = now + REPEAT_RATE


class QtSink:
    """Delivers :class:`GamepadInput`'s events to the game view as Qt events,
    marked as the pad's (:data:`game.controls.synthesizing`)."""

    def __init__(self, view):
        self.view = view
        self._buttons = 0
        self._cursor = None
        self._hand_modes = {}

    # -- what is open ----------------------------------------------------------
    def _session(self):
        return getattr(getattr(self.view, "logic_thread", None), "_miniwind", None)

    def menu_open(self) -> bool:
        from engine import qt_game_view as qv
        view = self.view
        if not getattr(view, "play_mode", False):
            return True
        if (qv._play_menu_open(view) or getattr(view, "pause_menu", None) is not None
                or qv._game_pointer_open(view) or qv._window_wants_cursor(view)
                or self._death_menu_open()):
            return True
        session = self._session()
        return bool(session is not None and (
            session.open_screen is not None or session.dialogue is not None
            or session.needs_char_creation))

    def keyboard_menu(self) -> bool:
        """A menu driven by the keyboard (arrows and Enter) rather than the
        pointer: the pause menu, the death screen."""
        from engine import qt_game_view as qv
        return bool(qv._play_menu_open(self.view) or self._death_menu_open())

    def context(self):
        session = self._session()
        return (self.menu_open(), self.keyboard_menu(),
                getattr(session, "open_screen", None),
                id(getattr(session, "dialogue", None)))

    def enabled(self):
        return (bool(getattr(self.view, "play_mode", False))
                and self.view.window().isActiveWindow()
                and not getattr(self.view, "console_overlay_active", False))

    def _death_menu_open(self) -> bool:
        view = self.view
        try:
            return bool(getattr(view, "death_menu", None) is not None
                        and view.game_state.published("player_dead", False))
        except Exception:
            return False

    # -- delivering -----------------------------------------------------------
    def _send(self, event) -> None:
        from PyQt5.QtWidgets import QApplication
        controls.synthesizing += 1
        try:
            QApplication.sendEvent(self.view, event)
        finally:
            controls.synthesizing -= 1

    def key(self, qt_key, down) -> None:
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtGui import QKeyEvent
        modifiers = Qt.ShiftModifier if qt_key == Qt.Key_Shift and down else Qt.NoModifier
        text = chr(qt_key).lower() if 0x41 <= qt_key <= 0x5A else ""
        self._send(QKeyEvent(QEvent.KeyPress if down else QEvent.KeyRelease,
                             qt_key, modifiers, text))

    def _pointer(self):
        from PyQt5.QtCore import QPoint
        from PyQt5.QtGui import QCursor
        if self._cursor is None:
            here = self.view.mapFromGlobal(QCursor.pos())
            if not self.view.rect().contains(here):
                here = self.view.rect().center()
            self._cursor = QPoint(here)
        return self._cursor

    def mouse(self, button, down, play) -> None:
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtGui import QMouseEvent
        qt_button = Qt.LeftButton if button == "left" else Qt.RightButton
        if down:
            self._buttons |= int(qt_button)
        else:
            self._buttons &= ~int(qt_button)
        pos = self.view.rect().center() if play else self._pointer()
        event = QMouseEvent(QEvent.MouseButtonPress if down else QEvent.MouseButtonRelease,
                            pos, self.view.mapToGlobal(pos), qt_button,
                            Qt.MouseButtons(self._buttons), Qt.NoModifier)
        self._send(event)

    def move(self, dx, dy, left_held=False) -> None:
        from PyQt5.QtCore import QEvent, QPoint, Qt
        from PyQt5.QtGui import QCursor, QMouseEvent
        p = self._pointer()
        rect = self.view.rect()
        x = max(rect.left(), min(rect.right(), p.x() + dx))
        y = max(rect.top(), min(rect.bottom(), p.y() + dy))
        self._cursor = QPoint(int(round(x)), int(round(y)))
        global_pos = self.view.mapToGlobal(self._cursor)
        controls.warped_to = (global_pos.x(), global_pos.y())
        QCursor.setPos(global_pos)
        buttons = Qt.MouseButtons(self._buttons | (int(Qt.LeftButton) if left_held else 0))
        self._send(QMouseEvent(QEvent.MouseMove, self._cursor, global_pos, Qt.NoButton,
                               buttons, Qt.NoModifier))

    def wheel(self, step) -> None:
        from PyQt5.QtCore import QPoint, QPointF, Qt
        from PyQt5.QtGui import QWheelEvent
        p = self._pointer()
        event = QWheelEvent(QPointF(p), QPointF(self.view.mapToGlobal(p)), QPoint(0, 0),
                            QPoint(0, 120 * int(step)), Qt.NoButton, Qt.NoModifier,
                            Qt.NoScrollPhase, False)
        self._send(event)

    def look(self, dx, dy) -> None:
        state = getattr(self.view, "game_state", None)
        session = self._session()
        if state is not None and (session is None or session.camera_rotation_enabled()):
            state.add_gamepad_look(dx, dy)

    def walk(self, move):
        state = getattr(self.view, "game_state", None)
        if state is not None:
            state.set_gamepad_move(move if controls.gamepad() else None)

    def hand(self, button, down):
        """A trigger holds a shield up, or uses its physical hand's item."""
        from .rpg import equipment as eq
        from .ui import hits
        session = self._session()
        if down:
            c = session.game.character if session is not None else None
            hand = eq.relative_hand(c, button) if c is not None else None
            shield = eq.equipped_def(c, "shield") if c is not None else None
            blocking = (hand == "off" and shield is not None
                        and shield.category == "armour" and eq.hand_spell(c, hand) is None)
            self._hand_modes[button] = "block" if blocking else "fire"
        mode = self._hand_modes.get(button)
        if mode == "block":
            hits.queue(lambda s, on=down: setattr(s, "_pad_blocking", on))
        elif mode == "fire":
            if not down and self.menu_open() and session is not None:
                session.bow_draw_input("cancel")
            self.mouse(button, down, play=True)
        if not down:
            self._hand_modes.pop(button, None)

    def cancel_hands(self):
        session = self._session()
        if session is not None and self._hand_modes:
            session.bow_draw_input("cancel")

    def menu_action(self, name):
        """Queue game UI verbs; a fast A tap must survive between logic ticks."""
        if self.keyboard_menu():
            return False
        session = self._session()
        if session is None:
            return False
        from .ui import hits, drag, screens
        if session.dialogue is not None:
            hits.queue(lambda s: s.dialogue_key(name))
            return True
        if session.open_screen is None:
            return False
        window = getattr(session, "_overlay_win", None)
        handler = getattr(window, "handle_gamepad", None)
        if handler is not None and handler(name):
            return True
        if name == "escape" and session.open_screen in screens.STATISTICS_SCREENS:
            drag.unpick()
            hits.queue(lambda s: setattr(s, "open_screen", None))
        else:
            hits.queue(lambda s: screens.handle_key(s, name))
        return True

    # -- lockpicking ---------------------------------------------------------
    def lockpicking(self) -> bool:
        session = self._session()
        return bool(session is not None and session.open_screen == "lockpicking")

    def lockpick(self, action, value=0.0) -> None:
        from .ui import hits
        hits.queue(lambda s: s.lockpick_action(action, value))

    # -- binding a button ------------------------------------------------------
    def _options(self):
        menu = getattr(self.view, "play_menu", None)
        return getattr(menu, "options", None) if getattr(menu, "active", False) else None

    def capturing_pad(self) -> bool:
        options = self._options()
        return bool(options is not None and getattr(options, "capture_pad", None))

    def capture_pad(self, button) -> None:
        options = self._options()
        if options is not None:
            options.capture_pad_button(button)

    # -- the game's own ---------------------------------------------------------
    def play_action(self, action, down):
        """One-shot actions are queued instead of relying on held-key snapshots."""
        from .ui import hits
        if action == "interact":
            if down and not self.activate_strip():
                self.view.game_state.set_use_key_pressed()
            return True
        methods = {"attack": "attack_with_both", "next_spell": "next_spell",
                   "heal": "use_health_potion", "sneak": "toggle_sneak"}
        screens = {"inventory", "character", "journal", "spells", "levelup", "quest"}
        if action not in methods and action not in screens and action != "map":
            return False
        if down:
            def run(s):
                if s.modal_input_active():
                    return
                if action in methods:
                    getattr(s, methods[action])()
                elif action == "map":
                    s.map_request = "player"
                elif action != "levelup" or s.game.character.can_level_up:
                    if action == "spells":
                        s.cancel_spell_aim()
                    s.open_screen = action
            hits.queue(run)
        return True

    def cycle_strip(self, step) -> None:
        session = self._session()
        if session is None:
            return
        from .ui import hits
        hits.queue(lambda s: s.cycle_strip(step))

    def activate_strip(self):
        session = self._session()
        if session is None:
            return False
        from . import fio
        from .ui import hits
        def activate(s):
            if s.modal_input_active():
                return
            # Decide after earlier queued D-pad presses have moved selection.
            if (not getattr(s, "_strip_confirm_pending", False)
                    and (s.interact_prompt or fio.interaction_prompt(s.logic))):
                self.view.game_state.set_use_key_pressed()
                return
            s._strip_confirm_pending = False
            s.select_strip_slot(s.strip_selected)
        hits.queue(activate)
        return True

    def turn_tab(self, step) -> None:
        """The Statistics window's tabs, left (LB) or right (RB)."""
        session = self._session()
        if session is None:
            return
        from .ui import hits, screens
        hits.queue(lambda s: setattr(s, "open_screen",
                                     screens.next_statistics_tab(s.open_screen, step)))


def install(view):
    """Read the pad every frame and play the game with it (see the module
    docstring); keyboard and mouse carry on as ever. Returns the input, or
    None without SDL controller support."""
    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication
    old = getattr(view, "_miniwind_gamepad", None)
    if old is not None:
        return old
    pad = SdlPad()
    if not pad._ok:
        return None
    gamepad = GamepadInput(pad, QtSink(view))
    controls.set_rumbler(pad.rumble)
    timer = QTimer(view)
    timer.timeout.connect(gamepad.poll)
    timer.start(16)
    gamepad.timer = timer
    view._miniwind_gamepad = gamepad
    app = QApplication.instance()
    if app is not None and getattr(app, "_miniwind_input_tracker", None) is None:
        app._miniwind_input_tracker = controls.install_tracker(app)
    return gamepad
