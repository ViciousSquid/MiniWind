"""Character creation has no window chrome: no [X], no fold, no drag.

The [X] used to finish creation at once with every default, which made an
"Adventurer" for anyone who clicked the corner of the first screen they saw.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.qt


def _press(x, y):
    from PyQt5 import QtCore, QtGui
    return QtGui.QMouseEvent(QtCore.QEvent.MouseButtonPress, QtCore.QPoint(x, y),
                             QtCore.Qt.LeftButton, QtCore.Qt.LeftButton,
                             QtCore.Qt.NoModifier)


def test_the_creation_window_has_no_close_fold_or_drag(qt_app):
    from game.ui.creation_window import CreationWindow
    closed, clicks = [], []
    win = CreationWindow("screen:charcreate", "Create Your Character",
                         lambda *a: None, width=600, body_height=400, x=100, y=50,
                         on_close_cb=lambda: closed.append(1),
                         on_body_click_cb=lambda x, y: clicks.append((x, y)) or True)
    right, top = 100 + 600 - 5, 50 + 5
    assert win.handle_mouse_press(_press(right, top))         # where [X] would be
    assert win.active and not closed, "the corner must not close creation"
    assert clicks == [(right, top)], "the click belongs to the creation panel"
    assert win.handle_mouse_press(_press(100 + 600 - 40, top))  # where the fold was
    assert win.expanded
    assert not win.dragging
    assert win.handle_mouse_move(_press(10, 10), 1280, 720) is False
    assert win.window_rect.x() == 100 and win.window_rect.y() == 50
    assert not win.handle_mouse_press(_press(5, 5))           # outside: not its click


def test_the_creation_window_paints_only_its_body(qt_app):
    from PyQt5 import QtGui
    from game.ui.creation_window import CreationWindow
    seen = []
    win = CreationWindow("screen:charcreate", "Create Your Character",
                         lambda p, x, y, w, h: seen.append((x, y, w, h)),
                         width=600, body_height=400, x=100, y=50)
    pixmap = QtGui.QPixmap(1280, 720)
    painter = QtGui.QPainter(pixmap)
    try:
        win.draw(painter)
    finally:
        painter.end()
    assert seen == [(100, 50, 600, 400)], "the body fills the window: no title bar"
