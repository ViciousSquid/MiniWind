"""The HUD draws "*fizzled*" over a caster's head -- and the player, seeing
from inside their own head, still sees theirs."""

from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5.QtGui")
pytestmark = pytest.mark.qt


def _drawn(thing, text="*fizzled*"):
    import glm
    from PyQt5.QtGui import QImage, QPainter
    from game.ui import hud
    view = glm.lookAt(glm.vec3(0, 0, 0), glm.vec3(0, 0, -1), glm.vec3(0, 1, 0))
    viewport = SimpleNamespace(projection_matrix=glm.perspective(1.2, 1.5, 1.0, 9000.0),
                               view_matrix=view)
    session = SimpleNamespace(live_floats=lambda: [(thing, text, 1.0, 1.6)])
    img = QImage(300, 200, QImage.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    hud.draw_floats(painter, session, viewport, 300, 200)
    painter.end()
    return any(img.pixel(x, y) >> 24 for x in range(0, 300, 2) for y in range(0, 200, 2))


@pytest.mark.parametrize("text", ["*fizzled*", "+1 wheat"])
def test_an_npcs_float_is_drawn_over_it(qt_app, text):
    assert _drawn(SimpleNamespace(pos=[0.0, 0.0, -600.0], properties={}), text)


def test_the_first_person_player_sees_their_own(qt_app):
    assert _drawn(SimpleNamespace(pos=[0.0, 0.0, 0.0], properties={"is_player": True}))


def test_someone_behind_the_camera_is_not_drawn(qt_app):
    assert not _drawn(SimpleNamespace(pos=[0.0, 0.0, 600.0], properties={}))
