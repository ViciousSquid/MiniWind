"""Play-mode mouse look is read once a frame from the live cursor, never from
the positions in mouse-move events (Fio 3.5, QtGameView._poll_mouse_look).

That is what makes a late cursor warp harmless: on macOS ``QCursor.setPos``
lands behind moves already queued, so measuring events against the centre
counted them several times over. Polled, each movement counts once; on macOS
the cursor is detached and the turn is each native event's own movement.
"""

import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5", reason="mouse look is part of the Qt game view")

from PyQt5.QtCore import QEvent, QPoint, Qt                  # noqa: E402
from PyQt5.QtGui import QMouseEvent                          # noqa: E402

from editor.things import PlayerStart                        # noqa: E402
from tests.helpers.worlds import level_data, make_thing, room  # noqa: E402

pytestmark = pytest.mark.qt


@pytest.fixture
def playing(fio_session, monkeypatch):
    start = make_thing(PlayerStart, "start", (0.0, 8.0, 0.0))
    session = fio_session(level_data(brushes=room(), things=[start]))
    session.start_play()
    session.step(30)
    view = session.view
    view.resize(800, 600)
    monkeypatch.setattr(view, "_mouse_look_captured", lambda: True)
    monkeypatch.setattr(type(view.window()), "isActiveWindow", lambda self: True)
    session.game_state.consume_mouse_delta()
    return session


def _move(view, x, y):
    view.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPoint(x, y),
                                    Qt.NoButton, Qt.NoButton, Qt.NoModifier))


def test_each_poll_counts_the_cursor_offset_once_and_recentres(playing, monkeypatch):
    import engine.qt_game_view as gv
    view = playing.view
    centre = view.mapToGlobal(view.rect().center())
    cursor, warps = [QPoint(centre)], []

    def set_pos(*args):
        warps.append(QPoint(args[-1]))
        cursor[0] = QPoint(args[-1])           # Windows/X11: the warp is immediate
    monkeypatch.setattr(gv.QCursor, "pos", staticmethod(lambda: QPoint(cursor[0])))
    monkeypatch.setattr(gv.QCursor, "setPos", staticmethod(set_pos))
    monkeypatch.setattr(view, "_mac_mouse", None)

    view._skip_next_look_poll = True
    view._poll_mouse_look()                    # capture: centre the cursor, no turn
    assert warps == [centre] and playing.game_state.consume_mouse_delta() == (0.0, 0.0)

    for step in range(1, 6):                   # move events alone never turn
        _move(view, 400 + 10 * step, 300)
    assert playing.game_state.consume_mouse_delta() == (0.0, 0.0)

    for dx in (10, 25, -7):
        cursor[0] = centre + QPoint(dx, 3)
        view._poll_mouse_look()
        assert playing.game_state.consume_mouse_delta() == (float(dx), 3.0)
        assert warps[-1] == centre
    view._poll_mouse_look()                    # nothing moved since: no turn
    assert playing.game_state.consume_mouse_delta() == (0.0, 0.0)


def test_macos_turns_by_native_deltas_with_the_cursor_detached(playing, monkeypatch):
    import engine.qt_game_view as gv
    view = playing.view
    pending = [0.0, 0.0]

    def take():
        out = tuple(pending)
        pending[:] = [0.0, 0.0]
        return out
    follows = []
    monkeypatch.setitem(sys.modules, "macos_app", SimpleNamespace(
        set_cursor_follows_mouse=lambda on: follows.append(on) or True))
    monkeypatch.setattr(view, "_mac_mouse", SimpleNamespace(take=take))
    monkeypatch.setattr(view, "_mac_cursor_detached", False)
    monkeypatch.setattr(gv.QCursor, "setPos", staticmethod(lambda *a: None))

    view._skip_next_look_poll = True
    view._poll_mouse_look()                    # centre the cursor
    pending[:] = [99.0, 0.0]                   # moves made before it was detached
    view._poll_mouse_look()                    # detach; those moves are dropped
    assert follows == [False] and playing.game_state.consume_mouse_delta() == (0.0, 0.0)

    # Events queued however late a warp would land: each counts once.
    pending[:] = [10.0 * 3, 0.0]
    view._poll_mouse_look()
    assert playing.game_state.consume_mouse_delta() == (30.0, 0.0)
    view._poll_mouse_look()
    assert playing.game_state.consume_mouse_delta() == (0.0, 0.0)
