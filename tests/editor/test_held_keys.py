"""Held movement keys do not open macOS's press-and-hold accent picker."""

from types import SimpleNamespace

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QInputMethodQueryEvent
from PyQt5.QtWidgets import QApplication, QLineEdit, QTreeView, QVBoxLayout, QWidget

from editor.held_keys import HeldKeyInputMethodFilter

pytestmark = pytest.mark.qt


def _ime_enabled(widget):
    # The query macOS's QNSView sends the focus object before a key reaches it.
    query = QInputMethodQueryEvent(Qt.ImEnabled | Qt.ImHints)
    QApplication.sendEvent(widget, query)
    return bool(query.value(Qt.ImEnabled))


@pytest.fixture
def window(qt_app):
    window = QWidget()
    window.view_3d = SimpleNamespace(play_mode=False, mouselook_active=False)
    layout = QVBoxLayout(window)
    window.tree, window.text = QTreeView(), QLineEdit()
    layout.addWidget(window.tree)
    layout.addWidget(window.text)
    held = HeldKeyInputMethodFilter(window)
    qt_app.installEventFilter(held)
    yield window
    qt_app.removeEventFilter(held)
    window.deleteLater()


def test_editor_widgets_keep_their_input_method_outside_play(window):
    # An item view reports an input method (for its keyboard search).
    assert _ime_enabled(window.tree)
    assert _ime_enabled(window.text)


@pytest.mark.parametrize('mode', ['play_mode', 'mouselook_active'])
def test_only_text_fields_take_text_while_keys_drive_the_view(window, mode):
    setattr(window.view_3d, mode, True)
    assert not _ime_enabled(window.tree)
    # The consoles still type, accents included.
    assert _ime_enabled(window.text)
