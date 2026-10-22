"""Play-mode mouse look on a platform whose cursor warp lands late (macOS).

``QCursor.setPos`` there takes effect after mouse events already queued, so
those events still report positions near the old spot.  Mouse look measures
each event from the previous one, so they must not pile up into a runaway
turn; the first event after the warp lands is measured from the centre.
"""

import pytest

pytest.importorskip("PyQt5", reason="mouse look is part of the Qt game view")

from PyQt5.QtCore import QEvent, QPoint, Qt                  # noqa: E402
from PyQt5.QtGui import QMouseEvent                          # noqa: E402

from editor.things import PlayerStart                        # noqa: E402
from tests.helpers.worlds import level_data, make_thing, room  # noqa: E402

pytestmark = pytest.mark.qt


@pytest.fixture
def playing(fio_session):
    start = make_thing(PlayerStart, "start", (0.0, 8.0, 0.0))
    session = fio_session(level_data(brushes=room(), things=[start]))
    session.start_play()
    session.step(30)
    return session


def _move(view, x, y):
    view.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPoint(x, y),
                                    Qt.NoButton, Qt.NoButton, Qt.NoModifier))


def test_events_queued_before_a_late_warp_do_not_stack(playing, monkeypatch):
    import engine.qt_game_view as gv
    view = playing.view
    view.resize(800, 600)
    warps = []
    monkeypatch.setattr(gv.QCursor, "setPos", lambda *a: warps.append(a))
    view._capture_play_cursor()
    cx, cy = view.rect().center().x(), view.rect().center().y()
    _move(view, cx, cy)                                # the capture warp lands
    playing.game_state.consume_mouse_delta()
    warps.clear()

    turned = []
    for step in range(1, 20):                          # a steady 10 px per event
        _move(view, cx + 10 * step, cy)
        turned.append(playing.game_state.consume_mouse_delta()[0])
    assert len(warps) == 1, "one warp once the cursor strayed, not one per event"

    # Events still queued from before the warp, then the warp lands.
    for step in range(20, 23):
        _move(view, cx + 10 * step, cy)
        turned.append(playing.game_state.consume_mouse_delta()[0])
    _move(view, cx + 5, cy)
    turned.append(playing.game_state.consume_mouse_delta()[0])
    assert turned == [10.0] * 22 + [5.0]
    assert len(warps) == 1
