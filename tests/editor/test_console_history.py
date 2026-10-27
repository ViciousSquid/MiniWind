"""Up repeats the last command, in every console.

The editor's Debug Console had command history; the Play console at the bottom
of the screen was a plain line edit, so Up did nothing there. Every command
input now keeps the same history, and Up starts from the newest command each
time a console opens.
"""

import pytest

pytest.importorskip("PyQt5", reason="the consoles are Qt widgets")

from PyQt5.QtCore import QEvent, Qt                          # noqa: E402
from PyQt5.QtGui import QKeyEvent                            # noqa: E402
from PyQt5.QtWidgets import QApplication                     # noqa: E402

from editor import debug_console                             # noqa: E402

pytestmark = pytest.mark.qt


@pytest.fixture(autouse=True)
def fresh_history():
    saved = list(debug_console.COMMAND_HISTORY)
    debug_console.COMMAND_HISTORY.clear()
    yield
    debug_console.COMMAND_HISTORY[:] = saved


def _press(widget, key):
    QApplication.sendEvent(widget, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))


def _enter(console, command):
    console.command_input.setText(command)
    console._on_command_entered()


def test_up_repeats_the_last_command_in_the_debug_console(main_window):
    console = main_window.debug_console
    _enter(console, "help")
    _enter(console, "fps")
    inp = console.command_input
    _press(inp, Qt.Key_Up)
    assert inp.text() == "fps"
    _press(inp, Qt.Key_Up)
    assert inp.text() == "help"
    _press(inp, Qt.Key_Down)
    assert inp.text() == "fps"


def test_up_repeats_the_last_command_in_the_play_console(main_window):
    view = main_window.view_3d
    view.play_mode = True
    try:
        view._open_console_overlay()
        view._console_input.setText("god")
        view._submit_console_command()           # run through the console, closed

        view._open_console_overlay()
        assert view._console_input.text() == ""
        _press(view._console_input, Qt.Key_Up)
        assert view._console_input.text() == "god"
    finally:
        view._close_console_overlay()
        view.play_mode = False


def test_up_in_the_play_console_repeats_a_command_typed_in_the_debug_console(main_window):
    _enter(main_window.debug_console, "noclip")
    view = main_window.view_3d
    view.play_mode = True
    try:
        view._open_console_overlay()
        _press(view._console_input, Qt.Key_Up)
        assert view._console_input.text() == "noclip"
    finally:
        view._close_console_overlay()
        view.play_mode = False


@pytest.mark.parametrize("console", ["viewport", "frame"])
def test_play_console_ignores_printable_autorepeat_without_losing_real_double_letters(main_window, console):
    """A brief key hold must not turn 'debug' into 'debbuug' in Play Mode."""
    view = main_window.view_3d
    view.play_mode = True
    if console == "viewport":
        view._open_console_overlay()
        line = view._console_input
    else:
        main_window._show_play_console_overlay()
        line = main_window._play_console_input
    try:
        for char in "debug":
            key = getattr(Qt, "Key_" + char.upper())
            QApplication.sendEvent(line, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, char))
            if char in "bu":
                QApplication.sendEvent(line, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, char, True))
            QApplication.sendEvent(line, QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier, char))
        assert line.text() == "debug"
        line.clear()
        for char in "coffee":
            key = getattr(Qt, "Key_" + char.upper())
            QApplication.sendEvent(line, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier, char))
            QApplication.sendEvent(line, QKeyEvent(QEvent.KeyRelease, key, Qt.NoModifier, char))
        assert line.text() == "coffee"
        # Editing/navigation keys retain their normal held-key behaviour.
        for repeat in (False, True, True):
            QApplication.sendEvent(line, QKeyEvent(QEvent.KeyPress, Qt.Key_Backspace,
                                                   Qt.NoModifier, "\b", repeat))
        assert line.text() == "cof"
    finally:
        main_window._hide_play_console_overlay()
        view.play_mode = False


def test_editor_console_keeps_normal_text_autorepeat(main_window):
    line = main_window.debug_console.command_input
    line.clear()
    for repeat in (False, True, True):
        QApplication.sendEvent(line, QKeyEvent(QEvent.KeyPress, Qt.Key_A, Qt.NoModifier, "a", repeat))
    assert line.text() == "aaa"
