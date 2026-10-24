"""Latched editor look uses the real view/input/camera path without a button."""

import pytest

pytest.importorskip('PyQt5')
from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QFocusEvent, QKeyEvent, QMouseEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from editor.things import PlayerStart
from tests.helpers.worlds import level_data, make_thing, room

pytestmark = pytest.mark.qt


@pytest.fixture
def editing(fio_session, monkeypatch):
    import engine.qt_game_view as gv
    session = fio_session(level_data(
        brushes=room(), things=[make_thing(PlayerStart, 'start', (0, 8, 0))]))
    # Control the OS boundary; queued native warp events must not race the
    # synthetic movements below. Delayed macOS warps have their own test.
    monkeypatch.setattr(gv.QCursor, 'setPos', lambda *args: None)
    session.view.setFocus()
    return session


def press(widget, key=Qt.Key_Z, modifiers=Qt.NoModifier, repeat=False):
    QApplication.sendEvent(widget, QKeyEvent(
        QEvent.KeyPress, key, modifiers, 'z' if key == Qt.Key_Z else '', repeat))


def button(view, kind, down):
    view_event = QMouseEvent(kind, view.rect().center(), Qt.RightButton,
                            Qt.RightButton if down else Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(view, view_event)


def move(view, pos):
    QApplication.sendEvent(view, QMouseEvent(
        QEvent.MouseMove, pos, Qt.NoButton, Qt.NoButton, Qt.NoModifier))


def test_z_from_a_2d_view_toggles_look_once_per_physical_press(editing):
    view = editing.view
    press(editing.window.view_top)
    assert view.editor_freelook_active and view.mouselook_active
    assert view.hasFocus()
    assert view.cursor().shape() == Qt.BlankCursor
    assert view.mouseGrabber() is view
    press(view, repeat=True)
    QApplication.sendEvent(view, QKeyEvent(QEvent.KeyRelease, Qt.Key_Z, Qt.NoModifier))
    assert view.editor_freelook_active
    press(view)
    assert not view.editor_freelook_active and not view.mouselook_active
    assert view.cursor().shape() == Qt.ArrowCursor
    assert view.mouseGrabber() is not view


def test_mouse_without_buttons_rotates_the_editor_camera_only_while_enabled(editing):
    view, logic = editing.view, editing.logic
    press(view)
    center = view.rect().center()
    move(view, center)  # the capture warp lands
    camera = logic.camera.get_editor_camera()
    yaw, pitch = camera.yaw, camera.pitch
    move(view, center + QPoint(10, 4))
    logic._step_frame(1 / 60)
    assert camera.yaw == pytest.approx(yaw + 1.5)
    assert camera.pitch == pytest.approx(pitch - .6)
    press(view)
    yaw, pitch = camera.yaw, camera.pitch
    move(view, center + QPoint(20, 8))
    logic._step_frame(1 / 60)
    assert (camera.yaw, camera.pitch) == (yaw, pitch)


def test_right_button_and_toggle_have_independent_lifetimes(editing):
    view = editing.view
    button(view, QEvent.MouseButtonPress, True)
    assert view.mouselook_active and not view.editor_freelook_active
    button(view, QEvent.MouseButtonRelease, False)
    assert not view.mouselook_active
    press(view)
    button(view, QEvent.MouseButtonPress, True)
    button(view, QEvent.MouseButtonRelease, False)
    assert view.mouselook_active and view.editor_freelook_active
    button(view, QEvent.MouseButtonPress, True)
    press(view)  # unlatch while the right button is still held
    assert view.mouselook_active and not view.editor_freelook_active
    assert view.mouseGrabber() is view
    button(view, QEvent.MouseButtonRelease, False)
    assert not view.mouselook_active


@pytest.mark.parametrize('exit_kind', ['escape', 'focus_loss'])
def test_release_frees_the_cursor_and_does_not_clear_selection(editing, exit_kind):
    view, window = editing.view, editing.window
    selection = editing.state.brushes[0]
    window.set_selected_objects([selection])
    press(view)
    if exit_kind == 'escape':
        press(view, Qt.Key_Escape)
    else:
        window.keys_pressed.add(Qt.Key_W)
        editing.game_state.set_keys({Qt.Key_W})
        QApplication.sendEvent(view, QFocusEvent(QEvent.FocusOut, Qt.ActiveWindowFocusReason))
        assert not window.keys_pressed and not editing.game_state.get_keys()
    assert not view.editor_freelook_active and not view.mouselook_active
    assert view.mouseGrabber() is not view
    assert view.cursor().shape() == Qt.ArrowCursor
    assert editing.state.selected_objects == [selection]


def test_play_entry_clears_editor_look_and_z_is_left_to_the_game(editing):
    press(editing.view)
    editing.start_play()
    assert not editing.view.mouselook_active and not editing.view.editor_freelook_active
    press(editing.view)
    assert not editing.view.editor_freelook_active
    editing.stop_play()
    assert not editing.view.mouselook_active


def test_typing_and_modified_z_do_not_start_freelook(editing):
    search = editing.window.scene_hierarchy.search_box
    search.setFocus()
    QTest.keyClick(search, Qt.Key_Z)
    assert search.text() == 'z'
    assert not editing.view.editor_freelook_active
    for modifier_key, modifier in [(Qt.Key_Control, Qt.ControlModifier),
                                   (Qt.Key_Shift, Qt.ShiftModifier)]:
        QTest.keyPress(editing.view, modifier_key)
        QTest.keyClick(editing.view, Qt.Key_Z, modifier)
        QTest.keyRelease(editing.view, modifier_key)
    assert not editing.view.editor_freelook_active
