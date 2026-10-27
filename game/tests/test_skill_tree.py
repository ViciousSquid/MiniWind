"""The skill tree page of the inventory window (I ▸ Skills)."""

import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtGui  # noqa: E402

from ..rpg import skills as sk  # noqa: E402
from ..rpg.character import Character  # noqa: E402
from ..ui import skill_tree  # noqa: E402

pytestmark = pytest.mark.qt


def test_ranks_and_progress():
    assert skill_tree.rank(0) == (0, "Novice")
    assert skill_tree.rank(49) == (1, "Apprentice")
    assert skill_tree.rank(100) == (4, "Master")
    c = Character()
    c.skills[sk.BLADE] = 20
    c._skill_xp[sk.BLADE] = sk.xp_to_raise(20) / 2
    assert skill_tree.progress(c, sk.BLADE) == pytest.approx(0.5)


def _window():
    from .test_ember_tome import _FakePlayer, _session
    from ..ui.pack_window import PackWindow
    s = _session([], _FakePlayer([0, 0, 0]))
    return PackWindow(s, 10, 10)


def _paint(win):
    image = QtGui.QImage(1060, 700, QtGui.QImage.Format_ARGB32)
    painter = QtGui.QPainter(image)
    try:
        win.draw(painter)
    finally:
        painter.end()


def test_the_skills_tab_shows_every_skill_and_a_click_picks_one(qt_app):
    win = _window()
    _paint(win)
    skills_tab = next(act for r, act in win._buttons
                      if getattr(act, "__qualname__", "").startswith("PackWindow._set_page"))
    skills_tab()
    assert win.showing == "skills"
    _paint(win)
    assert {sid for _r, sid in win._skill_nodes} == set(sk.SKILLS)
    rect, sid = win._skill_nodes[0]
    action = next(act for r, act in win._buttons if r == rect)
    action()
    assert win.selected_skill == sid
    _paint(win)                                     # with its detail line
