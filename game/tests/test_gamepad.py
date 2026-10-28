"""The gamepad plays MiniWind through the keyboard's and mouse's own events;
the prompts follow whichever was used last; pad buttons are rebindable, the
triggers are always the hands."""

from __future__ import annotations

import pytest

from .. import controls, keybinds
from ..gamepad import GamepadInput, PadState, TRIGGER_ON


@pytest.fixture(autouse=True)
def _defaults():
    keybinds.apply(None)
    controls.use(controls.KEYBOARD)
    yield
    keybinds.apply(None)
    controls.use(controls.KEYBOARD)


class _Source:
    def __init__(self):
        self.state = PadState()

    def set(self, *buttons, **axes):
        self.state = PadState(buttons, axes)

    def read(self):
        return self.state


class _Sink:
    def __init__(self, menu=False, keyboard_menu=False):
        self.events = []
        self.menu = menu
        self.kb_menu = keyboard_menu
        self.capturing = False

    def menu_open(self):
        return self.menu

    def keyboard_menu(self):
        return self.kb_menu

    def capturing_pad(self):
        return self.capturing

    def capture_pad(self, button):
        self.events.append(("capture", button))
        self.capturing = False

    def key(self, key, down):
        self.events.append(("key", key, down))

    def mouse(self, button, down, play):
        self.events.append(("mouse", button, down, play))

    def move(self, dx, dy, left_held=False):
        self.events.append(("move", round(dx), round(dy), left_held))

    def wheel(self, step):
        self.events.append(("wheel", step))

    def look(self, dx, dy):
        self.events.append(("look", dx, dy))

    def cycle_strip(self, step):
        self.events.append(("strip", step))

    def turn_tab(self, step):
        self.events.append(("tab", step))

    def take(self):
        out, self.events = self.events, []
        return out


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _pad(menu=False, keyboard_menu=False):
    source, sink, clock = _Source(), _Sink(menu, keyboard_menu), _Clock()
    pad = GamepadInput(source, sink, clock=clock)

    def step(*buttons, dt=1 / 60, **axes):
        source.set(*buttons, **axes)
        clock.t += dt
        pad.poll()
        return sink.take()
    return pad, sink, step


def _qt(name):
    from ..gamepad import _qt_key
    return _qt_key(name)


# ------------------------------------------------------------------ in play
def test_the_left_stick_walks_and_lets_go():
    _pad_, _sink, step = _pad()
    assert ("key", _qt("w"), True) in step(ly=-0.9)
    assert step(ly=-0.9) == []                         # held, not repeated
    assert ("key", _qt("w"), False) in step()
    events = step(lx=0.8, ly=0.8)
    assert ("key", _qt("d"), True) in events and ("key", _qt("s"), True) in events


def test_the_right_stick_is_the_mouse_look():
    _pad_, _sink, step = _pad()
    (look,) = [e for e in step(rx=1.0) if e[0] == "look"]
    assert look[1] > 0 and look[2] == 0
    assert [e for e in step(rx=0.1) if e[0] == "look"] == []   # inside the dead zone


def test_the_triggers_hold_the_left_and_right_hands():
    _pad_, _sink, step = _pad()
    assert step(lt=1.0) == [("mouse", "left", True, True)]
    assert step(lt=TRIGGER_ON - 0.05) == []           # not let go yet: no chatter
    assert step(lt=0.0) == [("mouse", "left", False, True)]
    assert step(rt=0.9) == [("mouse", "right", True, True)]
    assert step() == [("mouse", "right", False, True)]


def test_face_buttons_press_their_actions_keys():
    _pad_, _sink, step = _pad()
    e, f, b, shift = (_qt(k) for k in ("e", "f", "b", "shift"))
    assert step("a") == [("key", e, True), ("key", e, False)]      # interact: E
    step()
    assert step("x") == [("key", f, True), ("key", f, False)]      # attack: F
    step()
    assert step("b") == [("key", b, True)]                         # block: held
    assert step() == [("key", b, False)]
    assert step("ls") == [("key", shift, True)]                    # sprint: held
    step()
    assert step("start") == [("key", _qt("escape"), True), ("key", _qt("escape"), False)]
    step()
    assert step("rb") == [("strip", 1)]
    step()
    assert step("lb") == [("strip", -1)]


def test_a_rebound_button_presses_the_rebound_actions_key():
    keybinds.bind_pad(None, "interact", "x")          # swaps with attack
    _pad_, _sink, step = _pad()
    assert step("x")[0] == ("key", _qt("e"), True)
    step()
    assert step("a")[0] == ("key", _qt("f"), True)


def test_the_triggers_cannot_be_given_to_anything_but_the_hands():
    assert "lt" not in keybinds.PAD_BUTTONS and "rt" not in keybinds.PAD_BUTTONS
    assert keybinds.bind_pad(None, "interact", "lt") == ""
    assert keybinds.pad_binding("interact") == "a"
    _pad_, _sink, step = _pad()
    assert step(lt=1.0) == [("mouse", "left", True, True)]


def test_nothing_stays_held_when_the_pad_goes_away_or_a_menu_opens():
    pad, sink, step = _pad()
    step("b", ly=-1.0, rt=1.0)
    sink.menu = True
    events = step("b", ly=-1.0, rt=1.0)
    assert ("key", _qt("b"), False) in events and ("key", _qt("w"), False) in events
    assert ("mouse", "right", False, True) in events


# ------------------------------------------------------------------ in menus
def test_in_a_window_the_stick_is_the_pointer_and_a_clicks_and_drags():
    _pad_, _sink, step = _pad(menu=True)
    (move,) = step(lx=1.0, dt=0.1)
    assert move[0] == "move" and move[1] > 0 and move[3] is False
    assert step("a") == [("mouse", "left", True, False)]
    (drag,) = step("a", ly=1.0, dt=0.1)
    assert drag[0] == "move" and drag[2] > 0 and drag[3] is True       # dragging
    assert step() == [("mouse", "left", False, False)]
    assert step("x") == [("mouse", "right", True, False), ("mouse", "right", False, False)]
    step()
    assert step("b") == [("key", _qt("escape"), True), ("key", _qt("escape"), False)]


def test_shoulders_turn_the_statistics_tabs_and_the_dpad_is_the_arrows():
    _pad_, _sink, step = _pad(menu=True)
    assert step("rb") == [("tab", 1)]
    step()
    assert step("lb") == [("tab", -1)]
    step()
    assert step("dpad_down") == [("key", _qt("down"), True), ("key", _qt("down"), False)]
    assert step("dpad_down", dt=0.2) == []
    assert step("dpad_down", dt=0.3)[0] == ("key", _qt("down"), True)  # held: repeats


def test_the_right_stick_scrolls_in_a_window():
    _pad_, _sink, step = _pad(menu=True)
    events = [e for _ in range(5) for e in step(ry=-1.0, dt=0.1)]   # half a second
    assert ("wheel", 1) in events and ("wheel", -1) not in events


def test_in_the_pause_menu_a_is_enter():
    _pad_, _sink, step = _pad(menu=True, keyboard_menu=True)
    assert step("a") == [("key", _qt("return"), True), ("key", _qt("return"), False)]
    assert step(lx=1.0) == []                          # no pointer to move


def test_a_button_waited_for_in_the_bindings_is_handed_over():
    _pad_, sink, step = _pad(menu=True)
    sink.capturing = True
    assert step("y") == [("capture", "y")]


# ------------------------------------------------------------------ prompts
def test_prompts_name_the_control_last_used():
    assert controls.press("interact") == "Press E"
    _pad_, _sink, step = _pad()
    step("dpad_up")
    assert controls.gamepad()
    assert controls.press("interact") == "Press A"
    assert controls.label("quest") == "D-pad ↑"
    keybinds.bind_pad(None, "interact", "y")
    assert controls.press("interact") == "Press Y"     # follows the rebinding
    controls.use(controls.KEYBOARD)
    assert controls.press("interact") == "Press E"


def test_a_resting_pad_does_not_take_the_prompts():
    _pad_, _sink, step = _pad()
    step(lx=0.05, ry=-0.1)                             # drift inside the dead zone
    assert not controls.gamepad()


@pytest.mark.qt
def test_real_keyboard_and_mouse_take_the_prompts_back_but_the_pads_own_events_do_not(qt_app):
    from PyQt5.QtCore import QEvent, Qt
    from PyQt5.QtGui import QKeyEvent
    from PyQt5.QtWidgets import QWidget
    tracker = controls.install_tracker(qt_app)
    try:
        widget = QWidget()
        controls.use(controls.GAMEPAD)
        controls.synthesizing += 1
        try:
            qt_app.sendEvent(widget, QKeyEvent(QEvent.KeyPress, Qt.Key_E, Qt.NoModifier, "e"))
        finally:
            controls.synthesizing -= 1
        assert controls.gamepad()                      # the pad's own key press
        qt_app.sendEvent(widget, QKeyEvent(QEvent.KeyPress, Qt.Key_E, Qt.NoModifier, "e"))
        assert not controls.gamepad()                  # a real one
    finally:
        qt_app.removeEventFilter(tracker)


# --------------------------------------------------------------- the game's
def test_statistics_tabs_wrap_round():
    from ..ui import screens
    first, last = screens.STATISTICS_SCREENS[0], screens.STATISTICS_SCREENS[-1]
    assert screens.next_statistics_tab(first, -1) == last
    assert screens.next_statistics_tab(last, 1) == first
    assert screens.next_statistics_tab("trade", 1) == "trade"


def test_the_shoulders_ready_a_weapon_on_the_strip_but_never_put_it_away():
    from .test_inventory_strip import _give, _session
    from ..rpg import equipment as eq
    s = _session()
    _give(s, "iron_shortsword", "potion_heal_minor")
    s.strip_selected = 1
    assert s.cycle_strip(1)                            # wraps to the sword
    assert s.strip_selected == 0 and eq.weapon(s.game.character).id == "iron_shortsword"
    s.cycle_strip(1)                                   # the potion: only selected
    assert s.strip_selected == 1 and s.game.character.inventory
    s.cycle_strip(1)                                   # the sword again: kept in hand
    assert eq.weapon(s.game.character).id == "iron_shortsword"


@pytest.mark.qt
def test_the_qt_sink_delivers_real_key_and_mouse_events_marked_as_the_pads(qt_app):
    from PyQt5.QtWidgets import QWidget
    from ..gamepad import QtSink

    seen = []

    class _View(QWidget):
        play_mode = True

        def keyPressEvent(self, event):
            seen.append(("key", event.key(), controls.synthesizing > 0))

        def mousePressEvent(self, event):
            seen.append(("press", int(event.button()), (event.x(), event.y())))

        def mouseMoveEvent(self, event):
            seen.append(("move", int(event.buttons())))

    view = _View()
    view.resize(400, 300)
    sink = QtSink(view)
    sink.key(_qt("e"), True)
    sink.mouse("left", True, play=True)
    sink.move(10, 0, left_held=True)
    from PyQt5.QtCore import Qt
    assert seen[0] == ("key", Qt.Key_E, True)
    assert seen[1][0] == "press" and seen[1][1] == int(Qt.LeftButton)
    assert seen[1][2] == (view.rect().center().x(), view.rect().center().y())
    assert seen[2] == ("move", int(Qt.LeftButton))


def test_the_sdl_pad_reads_nothing_without_a_pad_and_does_not_raise():
    from ..gamepad import SdlPad
    pad = SdlPad()
    assert pad.read() is None
