"""MiniWind's Play: a real left click attacks, even with the hidden pointer
over the Play button.

Fio's native-input test (tests/native/test_play_click_native.py) plays its
own showcase with its shotgun; this is the same test on MiniWind's own Play
-- its world, its game, a new character -- with a left click
sent through the window system's own input (XTest on X11, CGEventPost on
macOS, mouse_event on Windows, a virtual pointer on Wayland -- Fio's
helpers). The click must reach the game as an attack -- a shot queued, then
taken by the logic tick -- and must not press Stop. A control with Play's
mouse grab switched off must see the bug come back, so a pass here means the
test exercises it. Moves the real pointer, so it runs only with
``FIO_NATIVE_INPUT=1``.
"""

import os

import pytest

pytest.importorskip('PyQt5')

from tests.native.test_play_click_native import (  # noqa: F401  (fixture)
    PressCounter, WaylandPointer, _activate_macos_app, _swaymsg, _wayland,
    clear_shots, click_editor_view, in_view_point, macos_first_window,
    move_pointer, os_click, platform_name, pump, pump_until, report,
    shots_queued, warm_up_input)

pytestmark = [
    pytest.mark.qt,
    pytest.mark.gl,
    pytest.mark.skipif(os.environ.get('FIO_NATIVE_INPUT') != '1',
                       reason='moves the real pointer; set FIO_NATIVE_INPUT=1'),
]


@pytest.fixture
def armed(fio_session, qt_app, monkeypatch):
    """MiniWind's own Play on its world: the game registered, a character
    made, the window active and the player at rest."""
    import random

    import game
    from game.tools.soak import profiles
    from plugins.manager import get_manager
    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    get_manager().register_builtin_game(game.GAME)
    session = fio_session('maps/miniwind_world.json', size=(800, 450))
    window = session.window
    if platform_name() != 'wayland':
        available = window.screen().availableGeometry()
        frame = window.frameGeometry().size() - window.size()
        window.resize(window.size().boundedTo(available.size() - frame))
        window.move(available.topLeft())
        pump(qt_app, 0.5)
    if platform_name() == 'wayland':
        _wayland['pointer'] = WaylandPointer()
        _swaymsg('fullscreen', 'enable')
        screen = window.screen().geometry()
        pump_until(qt_app, lambda: window.size() == screen.size(), 5.0)
        assert window.size() == screen.size(), \
            f'the editor did not go full screen: {window.size()} on {screen}'
    if platform_name() == 'cocoa':
        _activate_macos_app()
    window.raise_()
    window.activateWindow()
    warm_up_input(qt_app, session.view)
    if not pump_until(qt_app, window.isActiveWindow, 5.0):
        click_editor_view(qt_app, session.view)
        pump_until(qt_app, window.isActiveWindow, 5.0)
    assert window.isActiveWindow(), 'the editor window could not be made active'

    session.start_play()
    p = profiles(random.Random(7), 1)[0]
    session.logic.game_session.begin_new_character(
        p["name"], p["race"], p["class"], p["birthsign"], p["gender"],
        head=p["head"], handed=p["handed"])
    session.step(30)
    session.view.setFocus()
    pump(qt_app, 0.5)
    report('armed', session)
    assert session.view.play_mode
    assert session.view._mouse_look_captured(), 'Play does not hold the mouse'
    session.presses = PressCounter()
    qt_app.installEventFilter(session.presses)
    yield session
    qt_app.removeEventFilter(session.presses)
    pointer = _wayland.pop('pointer', None)
    if pointer is not None:
        pointer.close()


def assert_click_attacked(session, qt_app, label):
    """After a real click: it reached the app, Play goes on, and the game
    took it as an attack -- a shot queued, then taken by the next tick."""
    pump(qt_app, 0.3)
    report(label, session)
    assert session.presses.presses, (
        'no left press reached the application: the window system did not '
        'deliver the synthetic click (input permission?)')
    assert session.view.play_mode, 'the click left Play'
    assert shots_queued(session.game_state) >= 1, 'the click did not attack'
    session.step(1)
    assert shots_queued(session.game_state) == 0, 'the game did not take the attack'


def test_left_click_attacks(armed, qt_app):
    session = armed
    view = session.view
    move_pointer(view, in_view_point(view))
    clear_shots(session.game_state)
    os_click()
    assert_click_attacked(session, qt_app, 'click in the view')


def test_left_click_attacks_even_with_the_hidden_pointer_over_the_play_button(armed, qt_app):
    """The reported bug: the pointer is on Play/Stop when the player clicks."""
    session = armed
    button = session.window.play_button
    assert button.isVisible()
    clear_shots(session.game_state)
    stops = []
    button.clicked.connect(lambda *_: stops.append(True))
    move_pointer(button, button.rect().center())
    os_click()
    pump(qt_app, 0.3)
    assert not stops, 'the click pressed the Play/Stop button'
    assert_click_attacked(session, qt_app, 'click over the Play button')


def test_control_without_plays_mouse_grab_the_click_presses_stop(armed, qt_app, monkeypatch):
    """The control: with Play's mouse grab switched off the same click must
    press Stop -- the reported bug -- or the test above proves nothing here."""
    session = armed
    view, button = session.view, session.window.play_button
    monkeypatch.setattr(view, '_sync_play_mouse_grab', lambda held: None)
    if view.mouseGrabber() is view:
        view.releaseMouse()
    pump(qt_app, 0.1)
    clear_shots(session.game_state)
    stops = []
    button.clicked.connect(lambda *_: stops.append(True))
    move_pointer(button, button.rect().center())
    os_click()
    pump(qt_app, 0.3)
    report('control: click over the Play button, no grab', session)
    assert session.presses.presses, 'no left press reached the application'
    assert stops and not view.play_mode, (
        'without the grab the click should have pressed Stop (the reported '
        'bug); it did not, so this platform does not exercise the bug')
    assert shots_queued(session.game_state) == 0
