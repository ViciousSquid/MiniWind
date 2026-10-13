"""
The inventory strip (I) and dragging things between it, the character
window (C), chests and bodies.

Run:  python -m pytest game/tests/test_inventory_strip.py -q
"""

from __future__ import annotations

import pytest

from .fio_logic import FioLogic


class _Thing:
    def __init__(self, name, pos=(0.0, 0.0, 0.0), **props):
        self.pos = list(pos)
        self.properties = {"name": name, "display_name": name, **props}


class _Logic(FioLogic):
    def __init__(self, things=()):
        self.things = list(things)
        self.player = _Thing("You", is_player=True)


def _session(*things):
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(things), cfg={})
    s.game.character.inventory[:] = []
    s.game.character.strip = []
    s.game.character._strip_seen = set()
    return s


def _give(s, *ids):
    from ..rpg import items, inventory as inv
    for iid in ids:
        inv.add_item(s.game.character.inventory, items.make(iid, 1))


def _ids(s):
    return [e["id"] if e else None for e in s.strip_slots()]


# ------------------------------------------------------------------ model

def test_things_picked_up_fill_the_strip_in_order():
    s = _session()
    _give(s, "iron_shortsword", "potion_heal_minor")
    assert _ids(s)[:3] == ["iron_shortsword", "potion_heal_minor", None]
    assert len(_ids(s)) == s.strip_size() == 9


def test_dragged_out_of_the_strip_stays_out_until_it_comes_back():
    s = _session()
    _give(s, "iron_shortsword", "potion_heal_minor")
    assert s.item_drop(("strip", 0, "iron_shortsword"), ("pack", None))
    assert "iron_shortsword" not in _ids(s)
    assert "iron_shortsword" not in _ids(s)          # not refilled
    from ..rpg import inventory as inv
    inv.remove_item(s.game.character.inventory, "iron_shortsword", 1)
    _ids(s)
    _give(s, "iron_shortsword")                       # picked up again
    assert "iron_shortsword" in _ids(s)


def test_slots_rearrange_by_swapping():
    s = _session()
    _give(s, "iron_shortsword", "potion_heal_minor")
    assert s.item_drop(("strip", 0, "iron_shortsword"), ("strip", 4))
    assert _ids(s)[0] is None and _ids(s)[4] == "iron_shortsword"
    assert s.item_drop(("strip", 1, "potion_heal_minor"), ("strip", 4))
    assert _ids(s)[1] == "iron_shortsword" and _ids(s)[4] == "potion_heal_minor"


def test_from_the_pack_onto_a_slot():
    s = _session()
    _give(s, "iron_shortsword")
    s.item_drop(("strip", 0, "iron_shortsword"), ("pack", None))
    assert s.item_drop(("pack", None, "iron_shortsword"), ("strip", 6))
    assert _ids(s)[6] == "iron_shortsword"


def test_the_strip_resizes_and_what_falls_off_stays_carried():
    s = _session()
    _give(s, "iron_shortsword", "potion_heal_minor", "ingr_wolf_pelt")
    assert s.set_strip_size(2) == 2
    assert _ids(s) == ["iron_shortsword", "potion_heal_minor"]
    assert any(st["id"] == "ingr_wolf_pelt" for st in s.game.character.inventory)
    assert s.set_strip_size(500) == 30
    assert len(_ids(s)) == 30


def test_a_chest_or_body_trades_with_the_strip():
    from ..rpg import items
    chest = _Thing("Chest", type="container",
                   inventory=[items.make("potion_heal_minor", 3), items.make("gold", 9)])
    s = _session(chest)
    _give(s, "iron_shortsword")
    s.open_container(chest)
    # Out of the chest straight onto slot 5.
    assert s.item_drop(("container", 0, "potion_heal_minor"), ("strip", 5))
    assert _ids(s)[5] == "potion_heal_minor"
    gold = s.game.character.gold
    assert s.item_drop(("container", 0, "gold"), ("strip", 2))
    assert s.game.character.gold == gold + 9 and _ids(s)[2] is None
    # And a worn sword from the strip into the chest: taken off first.
    s.game.equip("iron_shortsword")
    assert s.item_drop(("strip", 0, "iron_shortsword"), ("container", None))
    assert s.game.character.equipment.get("weapon") != "iron_shortsword"
    assert "iron_shortsword" not in _ids(s)
    assert [st["id"] for st in s.container_inventory()] == ["iron_shortsword"]


def test_the_fists_never_go_in_a_chest():
    s = _session()
    chest = _Thing("Chest", type="container", inventory=[])
    s.logic.things.append(chest)
    _give(s, "fist")
    s.open_container(chest)
    assert not s.item_drop(("strip", 0, "fist"), ("container", None))
    assert s.container_inventory() == []


def test_the_strip_survives_a_save():
    from ..rpg.character import Character
    s = _session()
    _give(s, "iron_shortsword", "potion_heal_minor")
    s.item_drop(("strip", 0, "iron_shortsword"), ("strip", 3))
    c = Character.from_dict(s.game.character.to_dict())
    assert c.strip[3] == "iron_shortsword" and c.strip[0] is None
    assert "iron_shortsword" in c._strip_seen


# ---------------------------------------------------------------- the keys

def test_i_toggles_the_strip_and_c_opens_the_character_window():
    from ..host import MiniwindGame, K_INVENTORY, K_CHARACTER

    class _Ctx:
        def key_down(self, _k):
            return False

    s = _session()
    s.needs_char_creation = False
    game = MiniwindGame.__new__(MiniwindGame)
    game._handle_gameplay_input(s, {K_INVENTORY}, _Ctx())
    assert s.show_strip and s.open_screen is None
    assert MiniwindGame._strip_wanted(s)
    game._handle_gameplay_input(s, {K_INVENTORY}, _Ctx())
    assert not s.show_strip and not MiniwindGame._strip_wanted(s)
    game._handle_gameplay_input(s, {K_CHARACTER}, _Ctx())
    assert s.open_screen == "character"
    assert MiniwindGame._strip_wanted(s)              # up over the C window


# ----------------------------------------------------------------- console

def test_the_console_sets_and_saves_the_strip_size():
    import configparser
    from plugins.api import EditorAPI
    from plugins.manager import PluginManager
    from .. import console

    class _Window:
        def __init__(self):
            self.config = configparser.ConfigParser()
            self.saved = 0
            self.toasts = []

        def save_config(self):
            self.saved += 1

        def show_toast(self, text):
            self.toasts.append(text)

    mgr = PluginManager()
    console.register(EditorAPI(mgr, None))
    s = _session()
    logic = type("L", (), {"_miniwind": s})()
    window = _Window()
    handled, _ = mgr.dispatch_console_command("inventory_strip_size", "12", logic,
                                              main_window=window, play_mode=True)
    assert handled
    assert s.strip_size() == 12
    assert window.config.get("GAME", "inventory_strip_size") == "12"
    assert window.saved == 1
    mgr.dispatch_console_command("inventory_strip_size", "0", logic,
                                 main_window=window, play_mode=True)
    assert s.strip_size() == 12                       # out of range: refused


# ------------------------------------------------------------- the mouse

class _Ev:
    def __init__(self, point, button=None):
        from PyQt5.QtCore import Qt
        self._p = point
        self._b = Qt.LeftButton if button is None else button

    def pos(self):
        return self._p

    def x(self):
        return self._p.x()

    def y(self):
        return self._p.y()

    def button(self):
        return self._b


def _paint(*windows):
    from PyQt5 import QtGui
    pixmap = QtGui.QPixmap(1280, 800)
    painter = QtGui.QPainter(pixmap)
    for w in windows:
        w.draw(painter)
    painter.end()


def _drag(win, a, b):
    win.handle_mouse_press(_Ev(a))
    win.handle_mouse_move(_Ev(b), 1280, 800)
    win.handle_mouse_release(_Ev(b))


def test_dragging_one_slot_onto_another(qt_app):
    from ..ui import drag, hits
    from ..ui.inventory_strip import InventoryStrip
    drag.reset()
    hits.clear()
    s = _session()
    _give(s, "iron_shortsword", "potion_heal_minor")
    strip = InventoryStrip(s)
    strip.place(1280, 800)
    _paint(strip)
    _drag(strip, strip._rects[0].center(), strip._rects[7].center())
    assert hits.run_clicks(s) == 1
    assert _ids(s)[7] == "iron_shortsword" and _ids(s)[0] is None
    assert drag.current is None


def test_dragging_from_the_strip_into_an_open_chest(qt_app):
    from ..ui import drag, hits, screens
    from ..ui.container_window import ContainerWindow
    from ..ui.inventory_strip import InventoryStrip
    drag.reset()
    hits.clear()
    chest = _Thing("Chest", type="container", inventory=[])
    s = _session(chest)
    _give(s, "potion_heal_minor")
    s.open_container(chest)
    bw, bh = screens.window_body_size("container")
    box = ContainerWindow("screen:container", "Chest",
                          lambda p, x, y, w, h: screens.draw_in_rect(p, s, x, y, w, h),
                          width=bw, body_height=bh, x=40, y=20)
    strip = InventoryStrip(s)
    strip.place(1280, 800)
    _paint(box, strip)
    contents = next(r for r, t in screens.CONTAINER_DRAG["zones"] if t == ("container", None))
    _drag(strip, strip._rects[0].center(), contents.center())
    hits.run_clicks(s)
    assert [st["id"] for st in s.container_inventory()] == ["potion_heal_minor"]
    # ...and back out of the chest onto slot 3.
    _paint(box, strip)
    row = screens.CONTAINER_DRAG["cells"][0][0]
    _drag(box, row.center(), strip._rects[3].center())
    hits.run_clicks(s)
    assert s.container_inventory() == [] and _ids(s)[3] == "potion_heal_minor"
    drag.reset()
    hits.clear()


def test_dragging_from_the_character_window_onto_the_strip_and_back(qt_app):
    from ..ui import drag, hits
    from ..ui.inventory_strip import InventoryStrip
    from ..ui.inventory_window import InventoryWindow
    drag.reset()
    hits.clear()
    s = _session()
    _give(s, "potion_heal_minor")
    s.item_drop(("strip", 0, "potion_heal_minor"), ("pack", None))
    win = InventoryWindow(s, x=40, y=10, view="character")
    strip = InventoryStrip(s)
    strip.place(1280, 800)
    _paint(win, strip)
    cell = next(r for r, src in win._cells if src[2] == "potion_heal_minor")
    _drag(win, cell.center(), strip._rects[5].center())
    hits.run_clicks(s)
    assert _ids(s)[5] == "potion_heal_minor"
    # Out of the strip onto the pack grid takes it off the strip.
    _paint(win, strip)
    grid = next(r for r, t in win._targets if t == ("pack", None) and r.width() > 200)
    _drag(strip, strip._rects[5].center(), grid.center())
    hits.run_clicks(s)
    assert "potion_heal_minor" not in _ids(s)
    drag.reset()
    hits.clear()


def test_the_console_toggles_torch_shadows_and_saves_it():
    import configparser
    from plugins.api import EditorAPI
    from plugins.manager import PluginManager
    from .. import console, runtime

    class _Window:
        def __init__(self):
            self.config = configparser.ConfigParser()
            self.saved = 0

        def save_config(self):
            self.saved += 1

    mgr = PluginManager()
    console.register(EditorAPI(mgr, None))
    window = _Window()
    previous = runtime._editor_config
    runtime.set_editor_config(window.config)
    try:
        s = _session()
        logic = type("L", (), {"_miniwind": s})()

        def run(arg=""):
            handled, _ = mgr.dispatch_console_command("torch_shadows", arg, logic,
                                                      main_window=window, play_mode=True)
            assert handled
            return s.torch_shadows_enabled()

        assert s.torch_shadows_enabled() is False
        assert run() is True                       # toggles on
        assert run() is False                      # and off
        assert run("on") is True and run("on") is True
        assert run("off") is False
        assert run("sideways") is False            # refused, unchanged
        assert window.config.get("GAME", "torch_shadows") == "False"
        assert window.saved == 5
    finally:
        runtime.set_editor_config(previous)
