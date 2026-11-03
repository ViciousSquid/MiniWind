"""Party cards occupy a compact column below the minimap at every resolution."""

import pytest

pytest.importorskip("PyQt5")

from game.multiplayer.presentation import party_rects
from game.ui import hud_frame

pytestmark = pytest.mark.qt


@pytest.mark.parametrize("width,height", [(800, 600), (1280, 720), (1952, 1226)])
def test_party_column_sits_below_minimap(width, height):
    frame = hud_frame.layout(width, height)
    rects = party_rects(width, height, 4)
    assert all(r.x() == 12 and r.width() <= 224 and r.height() == 52 for r in rects)
    assert rects[0].top() > frame.cy + frame.R
    assert rects[-1].bottom() < height
    assert all(a.bottom() < b.top() for a, b in zip(rects, rects[1:]))
