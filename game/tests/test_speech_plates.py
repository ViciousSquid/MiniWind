"""What NPCs say and think fits in the plates over their heads."""
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5")

pytestmark = pytest.mark.qt

LONG = ("I've walked this road since before the old mill burned, and I'll walk "
        "it long after you're gone, stranger.")


class _Viewport:
    """Every head at the middle of a 1280 x 720 screen."""
    projection_matrix = view_matrix = None


@pytest.fixture
def painted(qt_app, monkeypatch):
    """Paint the barks and thoughts of one NPC; return what was drawn:
    ``[(kind, QRect, text)]``."""
    from PyQt5.QtGui import QImage, QPainter
    from ..ui import hud
    monkeypatch.setattr(hud, "_world_to_screen", lambda *a: (640.0, 400.0))
    monkeypatch.setattr(hud, "_has_roll_box", lambda s, t: False)

    def paint(said=None, thought=None):
        npc = SimpleNamespace(pos=[0.0, 0.0, 0.0], properties={"sprite_height": 112})
        session = SimpleNamespace(
            live_barks=lambda: [(npc, said, 3.0)] if said else [],
            live_thoughts=lambda: [(npc, thought, 3.0)] if thought else [])
        drawn = []
        img = QImage(1280, 720, QImage.Format_ARGB32)
        p = QPainter(img)
        real_rect, real_text = p.drawRoundedRect, p.drawText
        kind = {"now": None}

        def rect(r, *a):
            drawn.append([kind["now"], r, None, p.fontMetrics()])
            return real_rect(r, *a)

        def text(r, flags, words):
            drawn[-1][2] = words
            return real_text(r, flags, words)
        p.drawRoundedRect, p.drawText = rect, text
        import glm  # noqa: F401  (the HUD imports it)
        kind["now"] = "bark"
        hud.draw_barks(p, session, _Viewport(), 1280, 720)
        kind["now"] = "thought"
        hud.draw_thoughts(p, session, _Viewport(), 1280, 720)
        p.end()
        return drawn
    return paint


def _fits(rect, words, fm):
    from PyQt5.QtCore import Qt
    need = fm.boundingRect(rect.adjusted(2, 2, -2, -2), int(Qt.AlignCenter), words)
    return rect.contains(need) and need.height() <= rect.height() - 4


@pytest.mark.parametrize("kind", ["bark", "thought"])
def test_a_long_line_is_said_in_full_and_fits_its_plate(painted, kind):
    drawn = painted(said=LONG) if kind == "bark" else painted(thought=LONG)
    (_k, rect, words, fm), = drawn
    assert words.replace("\n", " ") == LONG               # nothing cut short
    assert _fits(rect, words, fm)


def test_only_a_very_long_line_is_cut_short():
    from PyQt5.QtGui import QFont, QFontMetrics
    from ..ui import hud
    fm = QFontMetrics(QFont())
    lines, _w, h = hud._plate_box(fm, " ".join([LONG] * 6), hud.BARK_PAD_X)
    assert len(lines) == hud.PLATE_MAX_LINES and lines[-1].endswith("…")
    assert h == 2 * hud.PLATE_PAD_Y + fm.lineSpacing() * hud.PLATE_MAX_LINES


def test_a_thought_sits_above_what_the_same_person_is_saying(painted):
    drawn = painted(said=LONG, thought="Hungry. Should have eaten at the inn.")
    (_b, bark, _bw, _bf), (_t, thought, _tw, _tf) = drawn
    assert thought.bottom() + 16 <= bark.top()            # its puffs too
