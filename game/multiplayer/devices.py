"""Independent SDL controller ownership; co-op never synthesises global keys."""

from __future__ import annotations

import math
import time

from .model import InputFrame


def available_pads():
    try:
        import pygame
        from pygame._sdl2 import controller

        from engine.sdl_runtime import init_input

        init_input()
        controller.init()
        pygame.event.pump()
        out = []
        for index in range(pygame.joystick.get_count()):
            if controller.is_controller(index):
                joystick = pygame.joystick.Joystick(index)
                out.append(
                    (
                        f"pad:{joystick.get_instance_id()}",
                        f"Gamepad {len(out) + 1}: {joystick.get_name()}",
                    )
                )
        return out
    except (ImportError, RuntimeError, OSError):
        return []


class AssignedPad:
    def __init__(self, device):
        self.device = device
        self.controller = None
        self.guid = None
        self.instance = device

    def read(self, reserved=()):
        from ..gamepad import PadState, SdlPad

        try:
            import pygame
            from pygame._sdl2 import controller

            pygame.event.pump()
            if self.controller is not None and not self.controller.attached():
                self.controller = None
            if self.controller is None:
                for index in range(pygame.joystick.get_count()):
                    if controller.is_controller(index):
                        joystick = pygame.joystick.Joystick(index)
                        instance = f"pad:{joystick.get_instance_id()}"
                        if instance == self.device or (
                            self.guid is not None
                            and joystick.get_guid() == self.guid
                            and instance not in reserved
                        ):
                            self.controller = controller.Controller(index)
                            self.guid = joystick.get_guid()
                            self.instance = instance
                            break
            if self.controller is None:
                return None
            buttons = [
                name
                for name, constant in SdlPad._BUTTONS
                if self.controller.get_button(getattr(pygame, constant))
            ]
            axes = {
                name: max(
                    -1.0,
                    min(
                        1.0,
                        self.controller.get_axis(getattr(pygame, constant)) / 32767.0,
                    ),
                )
                for name, constant in SdlPad._AXES
            }
            return PadState(buttons, axes)
        except (ImportError, RuntimeError, OSError, AttributeError):
            self.controller = None
            return None


class LocalDevices:
    """Read on the Qt thread, publish value-only frames to the logic thread."""

    def __init__(self, coop, view):
        self.coop, self.view = coop, view
        self.pads = {}
        self.last = {}
        self.repeat = {}
        self.menu_owner = None

    def _game_menu_key(self, name):
        # Call this view's menu directly. No application-wide key injection,
        # and no other local character's RPG panel receives the event.
        from PyQt5.QtCore import QEvent, Qt
        from PyQt5.QtGui import QKeyEvent

        key = {
            "return": Qt.Key_Return,
            "escape": Qt.Key_Escape,
            "up": Qt.Key_Up,
            "down": Qt.Key_Down,
            "left": Qt.Key_Left,
            "right": Qt.Key_Right,
        }.get(name)
        if key is not None:
            self.view.handle_pause_menu_key(
                QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
            )

    def poll(self):

        import game.keybinds as keybinds
        from ..gamepad import _stick

        if not getattr(self.view, "play_mode", False):
            return
        active = self.view.window().isActiveWindow() and not getattr(
            self.view, "console_overlay_active", False
        )
        self.coop._game_menu_open = bool(
            getattr(self.view, "pause_menu", None) is not None
            or getattr(getattr(self.view, "play_menu", None), "active", False)
        )
        if not self.coop._game_menu_open:
            self.menu_owner = None
        for context in self.coop.local_players:
            device = context.profile["device"]
            if device == "keyboard":
                from PyQt5.QtGui import QCursor

                pointer = getattr(self.view, "game_pointer", None)
                if pointer is not None and active:
                    pos = self.view.mapFromGlobal(QCursor.pos())
                    point = pointer.ground_point(
                        pos.x(), pos.y(), feet=context.session._player_pos()
                    )
                    if point is not None:
                        body = context.physics.pos
                        self.view.game_state.set_aim(
                            yaw=math.atan2(point[0] - body[0], point[2] - body[2])
                        )
                continue  # Key edges/held state come through Fio's input queue.
            source = self.pads.setdefault(device, AssignedPad(device))
            reserved = {
                p.profile["device"] for p in self.coop.local_players if p is not context
            }
            reserved.update(p.instance for p in self.pads.values() if p is not source)
            state = source.read(reserved) if active else None
            if state is None:
                self.coop.local_input(context.player_id, InputFrame(), ())
                self.last[device] = frozenset()
                continue
            buttons = set(state.buttons)
            if state.axis("lt") > 0.45:
                buttons.add("lt")
            if state.axis("rt") > 0.45:
                buttons.add("rt")
            pressed = buttons - self.last.get(device, frozenset())
            self.last[device] = frozenset(buttons)
            now = time.monotonic()
            repeats = self.repeat.setdefault(device, {})
            for button in ("dpad_up", "dpad_down", "dpad_left", "dpad_right"):
                if button not in buttons:
                    repeats.pop(button, None)
                elif button in pressed:
                    repeats[button] = now + 0.4
                elif now >= repeats.get(button, now + 1):
                    pressed.add(button)
                    repeats[button] = now + 0.09
            if "start" in pressed and "back" in buttons:
                self.coop.local_input(context.player_id, InputFrame(), [("pause", [])])
                continue
            if "start" in pressed and not self.coop._game_menu_open:
                self.menu_owner = context.player_id
                self.view.open_pause_menu()
                self.coop._game_menu_open = True
                self.coop.local_input(context.player_id, InputFrame(), ())
                continue
            if self.coop._game_menu_open and (
                self.menu_owner in (None, context.player_id)
            ):
                if self.menu_owner is None:
                    self.menu_owner = context.player_id
                for button in pressed:
                    name = {
                        "a": "return",
                        "b": "escape",
                        "start": "escape",
                        "dpad_up": "up",
                        "dpad_down": "down",
                        "dpad_left": "left",
                        "dpad_right": "right",
                    }.get(button)
                    if name:
                        self._game_menu_key(name)
                self.coop.local_input(context.player_id, InputFrame(), ())
                continue
            lx, ly = _stick(state.axis("lx"), state.axis("ly"))
            rx, ry = _stick(state.axis("rx"), state.axis("ry"))
            heading = self.coop.heading
            # Screen right/up agree with Fio's overhead input convention.
            x = -lx * math.cos(heading) - ly * math.sin(heading)
            z = lx * math.sin(heading) - ly * math.cos(heading)
            aim = None
            if rx or ry:
                aim = math.atan2(
                    -rx * math.cos(heading) - ry * math.sin(heading),
                    rx * math.sin(heading) - ry * math.cos(heading),
                )
            actions = []
            held = set()
            for button in buttons:
                action = {"lt": "left_hand", "rt": "right_hand"}.get(
                    button
                ) or keybinds.pad_action(button)
                if action in ("sprint", "block", "left_hand", "right_hand", "interact"):
                    held.add(action)
            session = context.session
            menu = session.open_screen is not None or session.dialogue is not None
            for button in pressed:
                if menu:
                    name = {
                        "a": "return",
                        "b": "escape",
                        "dpad_up": "up",
                        "dpad_down": "down",
                        "dpad_left": "left",
                        "dpad_right": "right",
                        "lb": "tab_prev",
                        "rb": "tab_next",
                    }.get(button)
                    if name:
                        window = getattr(session, "_overlay_win", None)
                        handler = getattr(window, "handle_gamepad", None)
                        if handler is not None and handler(name):
                            continue
                        actions.append(("menu_key", [name]))
                else:
                    action = keybinds.pad_action(button)
                    if (
                        action
                        and button not in ("lt", "rt")
                        and action not in ("block", "sprint")
                    ):
                        actions.append((action, []))
            if menu:
                x = z = 0
                held.clear()
                if session.open_screen == "lockpicking":
                    if ly:
                        actions.append(("lockpick_action", ["lift", -ly * 3.0]))
                    actions.append(
                        ("lockpick_action", ["tension", state.axis("rt") > 0.45])
                    )
            self.coop.local_input(
                context.player_id, InputFrame(x, z, aim, frozenset(held)), actions
            )

    def close(self):
        self.timer.stop()
        self.timer.deleteLater()
        for source in self.pads.values():
            if source.controller is not None:
                source.controller.quit()
        if getattr(self.view, "_coop_devices", None) is self:
            self.view._coop_devices = None


def install(coop, view):
    from PyQt5.QtCore import QTimer

    previous = getattr(view, "_coop_devices", None)
    if previous is not None:
        previous.timer.stop()
    devices = LocalDevices(coop, view)
    timer = QTimer(view)
    timer.timeout.connect(devices.poll)
    timer.start(16)
    devices.timer = timer
    view._coop_devices = devices
    coop._device_reader = devices
    return devices
