"""Click an item to pick it up -- every slot it fits lights up -- then click
a slot to put it there. Dragging still works as before."""

from __future__ import annotations

from PyQt5 import QtCore, QtGui
import pytest

from game.rpg import equipment as eq, items
from game.ui import drag, hits
from game.ui.inventory_strip import InventoryStrip
from .test_menu_clicks import _Press
from .test_statistics_window import _paint, _tab, ui  # noqa: F401  (fixture)

pytestmark = pytest.mark.qt


class _Right(_Press):
    def button(self):
        return QtCore.Qt.RightButton


def _click(window, point, event=_Press):
    window.handle_mouse_press(event(point))
    window.handle_mouse_release(event(point))


def _strip(session):
    strip = InventoryStrip(session)
    strip.place(1280, 800)
    image = QtGui.QImage(1280, 800, QtGui.QImage.Format_ARGB32)
    painter = QtGui.QPainter(image)
    try:
        strip.draw(painter)
    finally:
        painter.end()
    return strip


def _cell(window, source):
    _paint(window)
    return next(rect.center() for rect, src in window._cells if src == source)


def _target(window, target):
    _paint(window)
    return next(rect.center() for rect, dst in window._targets if dst == target)


def test_a_spell_clicked_in_the_book_goes_to_the_bar_slot_clicked(ui):
    _game, session, _view, window = ui
    _tab(ui, "spells")
    _click(window, _cell(window, ("spell", None, "lightning")))
    hits.run_clicks(session)
    assert drag.picked_source() == ("spell", None, "lightning")
    assert drag.offered() == ("spell", None, "lightning")
    strip = _strip(session)
    _click(strip, strip._rects[5].center())
    hits.run_clicks(session)
    assert session.strip_slots()[5]["spell"] == "lightning"
    assert drag.picked_source() is None
    assert not session.game.character.hand_spells      # on the bar, not in hand


def test_an_item_picked_in_the_pack_is_worn_by_a_click_on_its_slot(ui):
    _game, session, _view, window = ui
    c = session.game.character
    c.inventory.append(items.make("iron_shortsword"))
    session.open_screen = "character"
    _tab(ui, "character")
    _click(window, _cell(window, ("pack", None, "iron_shortsword")))
    assert drag.picked_source() == ("pack", None, "iron_shortsword")
    _click(window, _target(window, ("equip", "weapon")))
    hits.run_clicks(session)
    assert eq.weapon(c).id == "iron_shortsword"
    assert drag.picked_source() is None


def test_a_slot_it_does_not_fit_does_not_take_it(ui):
    _game, session, _view, window = ui
    c = session.game.character
    c.inventory.append(items.make("iron_shortsword"))
    _tab(ui, "character")
    _click(window, _cell(window, ("pack", None, "iron_shortsword")))
    window.handle_mouse_press(_Press(_target(window, ("equip", "head"))))
    window.handle_mouse_release(_Press(_target(window, ("equip", "head"))))
    hits.run_clicks(session)
    assert eq.equipped_id(c, "head") is None
    assert eq.weapon(c) is None


def test_clicking_it_again_or_a_right_click_puts_it_back_down(ui):
    _game, session, _view, window = ui
    c = session.game.character
    c.inventory.append(items.make("iron_shortsword"))
    _tab(ui, "character")
    point = _cell(window, ("pack", None, "iron_shortsword"))
    _click(window, point)
    assert drag.picked_source() is not None
    window._last_click = (0.0, None)                   # not a double click
    _click(window, point)
    assert drag.picked_source() is None
    window._last_click = (0.0, None)
    _click(window, point)
    assert drag.picked_source() is not None
    window.handle_mouse_press(_Right(point))
    assert drag.picked_source() is None


def test_a_strip_item_is_picked_and_moved_to_another_slot(ui):
    _game, session, _view, _window = ui
    c = session.game.character
    c.inventory[:] = [items.make("potion_heal_minor", 1)]
    c.strip = []
    c._strip_seen = set()
    strip = _strip(session)
    assert session.strip_slots()[0]["id"] == "potion_heal_minor"
    _click(strip, strip._rects[0].center())
    assert drag.picked_source() == ("strip", 0, "potion_heal_minor")
    strip = _strip(session)                            # every slot lit as open
    _click(strip, strip._rects[7].center())
    hits.run_clicks(session)
    assert session.strip_slots()[7]["id"] == "potion_heal_minor"
    assert session.strip_slots()[0] is None
