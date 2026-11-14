"""HUD pieces painted once and blitted (game/ui/theme.py sprite)."""

import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtGui  # noqa: E402

from ..ui import theme as T  # noqa: E402


def _draw(painter, key, slot=None):
    return T.sprite(painter, key, 20, 10, lambda p: p.fillRect(0, 0, 20, 10, QtGui.QColor("red")),
                    slot=slot)


def test_a_slot_keeps_only_its_newest_picture(qt_app, monkeypatch):
    """The clock has a new face every game minute: only the newest is kept,
    so old faces neither pile up nor fill the cache (whose emptying makes
    every other panel be painted again in the same frame)."""
    monkeypatch.setattr(T, "_SPRITES", {})
    monkeypatch.setattr(T, "_SPRITE_SLOTS", {})
    target = QtGui.QPixmap(64, 64)
    painter = QtGui.QPainter(target)
    try:
        panel = _draw(painter, ("panel", 20, 10))
        for minute in range(300):                      # five game hours
            _draw(painter, ("clock", 8, minute), slot="clock")
        assert len(T._SPRITES) == 2                    # one face, one panel
        assert _draw(painter, ("panel", 20, 10)) is panel
        newest = _draw(painter, ("clock", 8, 299), slot="clock")
        assert newest is _draw(painter, ("clock", 8, 299), slot="clock")
    finally:
        painter.end()
