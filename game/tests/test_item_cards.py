"""Chests, bodies and merchants show their things as cards (game/ui/cards.py),
and a right click splits a stack.

Run:  python -m pytest game/tests/test_item_cards.py -q
"""

from types import SimpleNamespace

import pytest

QtCore = pytest.importorskip("PyQt5.QtCore")
QtGui = pytest.importorskip("PyQt5.QtGui")
pytestmark = pytest.mark.qt

from PyQt5.QtCore import QPoint, Qt

from game import host, keybinds
from game.rpg import items, inventory as inv
from game.runtime import MiniwindSession
from game.ui import cards, drag, hits, screens, trade_anim
from .fio_logic import FioLogic

CHEST = ["iron_longsword", ("potion_heal", 3), ("bread", 5), "iron_helmet",
         "hunting_bow", ("iron_arrow", 18), ("gold", 35), "book_blade",
         "copper_ring", ("ingr_mushroom", 4)]


class _Thing:
    def __init__(self, name, pos=(0.0, 0.0, 0.0), **props):
        self.pos = list(pos)
        self.properties = {"name": name, "display_name": name, **props}


class _Logic(FioLogic):
    def __init__(self, things=()):
        self.things = list(things)
        self.player = _Thing("You", is_player=True)


def _stack(entry):
    iid, qty = entry if isinstance(entry, tuple) else (entry, 1)
    return items.make(iid, qty)


@pytest.fixture
def session(qt_app, monkeypatch):
    for _action, _label, constant, default in keybinds.ACTIONS:
        monkeypatch.setattr(host, constant, default)
    chest = _Thing("Old Chest", type="container",
                   inventory=[_stack(e) for e in CHEST])
    s = MiniwindSession(_Logic([chest]), cfg={})
    s.needs_char_creation = False
    c = s.game.character
    c.inventory[:] = [_stack(e) for e in ("iron_shortsword", ("potion_heal", 7),
                                          ("bread", 3), "leather_cuirass")]
    c.strip = []
    c._strip_seen = set()
    c.gold = 500
    s.open_container(chest)
    s.container_take_is_theft = lambda: False
    monkeypatch.setattr(hits, "pointer", None)
    hits.clear()
    drag.reset()
    yield s
    hits.clear()
    drag.reset()


def _paint(session, w, h, full=False):
    image = QtGui.QImage(w + 100, h + 100, QtGui.QImage.Format_ARGB32)
    image.fill(0)
    painter = QtGui.QPainter(image)
    hits.begin()
    try:
        if full:
            screens.draw(painter, session, w, h)
        else:
            screens.draw_in_rect(painter, session, 40, 50, w, h)
    finally:
        painter.end()
        hits.end()


def _panel(w, h, full):
    if full:
        return QtCore.QRect(*screens._panel_rect(w, h))
    return QtCore.QRect(40, 50, w, h)


def _no_overlap(rects, panel):
    for i, a in enumerate(rects):
        assert panel.contains(a), (a, panel)
        assert a.height() > a.width()                       # portrait cards
        for b in rects[i + 1:]:
            assert not a.intersects(b)


SIZES = [(1280, 720, True), (1920, 1080, True), (900, 560, False)]


# ----------------------------------------------------------------- container
@pytest.mark.parametrize("w,h,full", SIZES)
def test_container_cards_fit_the_panel_without_overlap(session, w, h, full):
    _paint(session, w, h, full)
    rects = [r for r, _src in screens.CONTAINER_DRAG["cells"]]
    _no_overlap(rects, _panel(w, h, full))
    close = next(r for r, label in hits.targets() if label == "Close")
    assert all(not r.intersects(close) for r in rects)
    contents = [src for _r, src in screens.CONTAINER_DRAG["cells"] if src[0] == "container"]
    assert len(contents) == len(CHEST)                  # ten things: one page
    # Both columns' cards are one size, in rows and columns.
    assert len({(r.width(), r.height()) for r in rects}) == 1
    assert len({r.y() for r in rects}) >= 2 and len({r.x() for r in rects}) >= 4


def test_every_container_card_is_a_click_target_and_a_drag_source(session):
    _paint(session, 900, 560)
    labels = {r.getRect(): label for r, label in hits.targets()}
    pack = session.game.character.inventory
    for rect, src in screens.CONTAINER_DRAG["cells"]:
        if src[0] == "container":
            i = src[1]
            assert src == ("container", i, session.container_inventory()[i]["id"])
            assert labels[rect.getRect()] == f"take:{i}"
        else:
            assert src[:2] == ("pack", None)
            i = next(k for k, st in enumerate(pack) if st["id"] == src[2])
            assert labels[rect.getRect()] == f"store:{i}"
    # A click on a contents card takes it.
    rect = next(r for r, src in screens.CONTAINER_DRAG["cells"] if src[2] == "iron_helmet")
    assert hits.click(rect.center().x(), rect.center().y())
    hits.run_clicks(session)
    assert inv.has_item(session.game.character.inventory, "iron_helmet")


def test_container_arrows_move_in_two_dimensions_and_across(session):
    _paint(session, 900, 560)
    st = screens._cont_state(session)
    cols = st["cols_c"]
    assert cols >= 3
    st.update(side=0, row_c=0)
    screens.handle_key(session, "right")
    assert (st["side"], st["row_c"]) == (0, 1)
    screens.handle_key(session, "down")
    assert st["row_c"] == 1 + cols
    screens.handle_key(session, "up")
    assert st["row_c"] == 1
    st["row_c"] = cols - 1                               # the row's last card
    screens.handle_key(session, "right")                 # across to your side
    assert st["side"] == 1 and st["row_p"] == 0
    screens.handle_key(session, "left")                  # and back
    assert st["side"] == 0 and st["row_c"] == cols - 1
    st["row_c"] = 0
    screens.handle_key(session, "left")                  # the outer edge: stays
    assert (st["side"], st["row_c"]) == (0, 0)
    screens.handle_key(session, "tab")
    assert st["side"] == 1
    screens.handle_key(session, "enter")                 # stores your first thing
    assert session.container_inventory()[-1]["id"] == "iron_shortsword"


def test_container_tooltips_carry_quantity_and_value(session, monkeypatch):
    tips = []
    monkeypatch.setattr(cards, "draw_tooltip", lambda p, text, pos: tips.append(text))
    _paint(session, 900, 560)
    rect = next(r for r, src in screens.CONTAINER_DRAG["cells"]
                if src[0] == "container" and src[2] == "bread")
    monkeypatch.setattr(hits, "pointer", (rect.center().x(), rect.center().y()))
    _paint(session, 900, 560)
    assert tips and tips[-1].startswith("Bread")
    assert "Quantity 5" in tips[-1] and "Value" in tips[-1] and "Weight" in tips[-1]


def test_container_cards_show_the_stack_count(session, monkeypatch):
    drawn = []
    real = cards.draw_card
    monkeypatch.setattr(cards, "draw_card",
                        lambda p, r, card: drawn.append(card) or real(p, r, card))
    _paint(session, 900, 560)
    arrows = next(card for card in drawn if card.title == "Iron Arrow")
    assert arrows.quantity == 18 and arrows.icon is not None


def test_a_long_chest_pages(session):
    session.container_inventory()[:] = [items.make("bread", 1) for _ in range(40)]
    _paint(session, 900, 560)
    st = screens._cont_state(session)
    shown = [src for _r, src in screens.CONTAINER_DRAG["cells"] if src[0] == "container"]
    assert len(shown) == st["size_c"] < 40
    turn = next(r for r, label in hits.targets() if label == "▸")
    hits.click(turn.center().x(), turn.center().y())
    hits.run_clicks(session)
    assert st["row_c"] == st["size_c"]
    _paint(session, 900, 560)
    assert screens.CONTAINER_DRAG["cells"][0][1][1] == st["size_c"]


# ---------------------------------------------------------------------- trade
class _Merchant:
    def __init__(self):
        self.pos = [10.0, 0.0, 0.0]
        self.properties = {"display_name": "Bryn", "merchant": True,
                           "npc_role": "merchant", "name": "bryn"}


@pytest.fixture
def trading(session):
    session.close_container()
    session.merchant_npc = _Merchant()
    session.open_screen = "trade"
    trade_anim.reset()
    return session


def _trade_cards():
    return [(r, label) for r, label in hits.targets()
            if str(label).startswith(("buy:", "sell:"))]


@pytest.mark.parametrize("w,h,full", [(1280, 720, True), (1920, 1080, True),
                                      (960, 600, False)])
def test_trade_cards_fit_the_panel_without_overlap(trading, w, h, full):
    _paint(trading, w, h, full)
    rects = [r for r, _l in _trade_cards()]
    assert any(str(l).startswith("buy:") for _r, l in _trade_cards())
    assert any(str(l).startswith("sell:") for _r, l in _trade_cards())
    _no_overlap(rects, _panel(w, h, full))
    leave = next(r for r, label in hits.targets() if label == "Leave")
    assert all(not r.intersects(leave) for r in rects)


def test_the_price_shows_on_the_card_in_its_tip_and_on_the_button(trading, monkeypatch):
    drawn = []
    real = cards.draw_card
    monkeypatch.setattr(cards, "draw_card",
                        lambda p, r, card: drawn.append((QtCore.QRect(r), card))
                        or real(p, r, card))
    stock = screens._merchant_stock(trading.merchant_npc)
    iid = stock[1]["id"]
    d = items.get(iid)
    price = trading._price(d.value, True, npc=trading.merchant_npc, item_id=iid)
    rect = next(r for r, label in (_paint(trading, 960, 600) or _trade_cards())
                if label == f"buy:{iid}")
    hits.click(rect.center().x(), rect.center().y())
    hits.run_clicks(trading)
    drawn.clear()
    _paint(trading, 960, 600)
    card = next(c for r, c in drawn if r == rect)
    assert card.selected and f"{price} g" in card.badges
    assert f"Buy for {price} g" in card.tooltip
    # Before confirming, the button says what it will cost.
    assert f"Buy {d.name} for {price}g" in {label for _r, label in hits.targets()}


def test_trade_arrows_move_in_two_dimensions_and_across(trading):
    _paint(trading, 960, 600)
    st = screens._sel(trading)["trade"]
    cols = st["cols"][0]
    assert cols >= 3
    st.update(side=0, row=0)
    screens.handle_key(trading, "right")
    assert (st["side"], st["row"]) == (0, 1)
    screens.handle_key(trading, "down")
    assert st["row"] == 1 + cols
    st["row"] = cols - 1
    screens.handle_key(trading, "right")
    assert (st["side"], st["row"]) == (1, 0)
    screens.handle_key(trading, "left")
    assert (st["side"], st["row"]) == (0, cols - 1)
    screens.handle_key(trading, "tab")
    assert st["side"] == 1


def test_a_bought_item_flies_as_a_card(trading, monkeypatch):
    import types
    clock = [10.0]
    monkeypatch.setattr(trade_anim, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    trading.game.character.gold = 1000
    _paint(trading, 960, 600)
    screens._handle_trade(trading, "return")
    assert trade_anim.active()
    titles = []
    real = cards.draw_card
    monkeypatch.setattr(cards, "draw_card",
                        lambda p, r, card: titles.append((card.title, card.badges))
                        or real(p, r, card))
    clock[0] += trade_anim.FLIGHT_SECONDS / 2
    _paint(trading, 960, 600)
    first = screens._merchant_stock(trading.merchant_npc)[0]["id"]
    name = items.get(first).name
    assert sum(1 for t, _b in titles if t == name) >= 2      # its card, and the flight


# -------------------------------------------------------------------- splitting
class _Ev:
    def __init__(self, point, button=Qt.LeftButton):
        self._p = QPoint(point)
        self._b = button

    def pos(self):
        return self._p

    def x(self):
        return self._p.x()

    def y(self):
        return self._p.y()

    def button(self):
        return self._b


def _window(session):
    from game.ui.container_window import ContainerWindow
    bw, bh = screens.window_body_size("container")
    return ContainerWindow("screen:container", "Loot",
                           lambda p, x, y, w, h: screens.draw_in_rect(p, session, x, y, w, h),
                           width=bw, body_height=bh, x=40, y=20)


def _draw(*windows):
    pixmap = QtGui.QPixmap(1400, 900)
    painter = QtGui.QPainter(pixmap)
    hits.begin()
    for w in windows:
        w.draw(painter)
    hits.end()
    painter.end()


def _card(source_kind, iid):
    return next(r for r, src in screens.CONTAINER_DRAG["cells"]
                if src[0] == source_kind and src[2] == iid)


def _contents_space():
    """A point in the contents column clear of every card."""
    zone = next(r for r, t in screens.CONTAINER_DRAG["zones"] if t == ("container", None))
    cards_ = [r for r, src in screens.CONTAINER_DRAG["cells"] if src[0] == "container"]
    for y in range(zone.bottom() - 4, zone.top(), -6):
        for x in range(zone.left() + 4, zone.right(), 6):
            p = QPoint(x, y)
            if not any(r.contains(p) for r in cards_):
                return p
    raise AssertionError("no free space")


def _qtys(lst, iid):
    return [int(st.get("qty", 1)) for st in lst if st.get("id") == iid]


def test_right_click_picks_up_the_larger_half(session):
    win = _window(session)
    _draw(win)
    win.handle_mouse_press(_Ev(_card("container", "bread").center(), Qt.RightButton))
    assert drag.picked_source() == ("container", 2, "bread", 3)       # of five
    # The card shows what is left while the half rides on the pointer.
    shown = []
    real = cards.draw_card
    import unittest.mock as mock
    with mock.patch.object(cards, "draw_card",
                           lambda p, r, card: shown.append(card) or real(p, r, card)):
        _draw(win)
    assert next(c for c in shown if c.title == "Bread" and c.quantity == 2)


def test_a_split_put_down_on_empty_space_is_a_new_stack(session):
    win = _window(session)
    _draw(win)
    win.handle_mouse_press(_Ev(_card("container", "bread").center(), Qt.RightButton))
    win.handle_mouse_press(_Ev(_contents_space()))
    assert drag.picked_source() is None
    hits.run_clicks(session)
    assert _qtys(session.container_inventory(), "bread") == [2, 3]


def test_a_split_put_down_on_the_same_thing_joins_it(session):
    session.container_inventory().append(items.make("bread", 1))
    win = _window(session)
    _draw(win)
    first, last = [r for r, src in screens.CONTAINER_DRAG["cells"]
                   if src[0] == "container" and src[2] == "bread"]
    win.handle_mouse_press(_Ev(first.center(), Qt.RightButton))
    win.handle_mouse_press(_Ev(last.center()))
    hits.run_clicks(session)
    assert _qtys(session.container_inventory(), "bread") == [2, 4]


def test_a_split_taken_to_your_side_goes_in_the_pack(session):
    win = _window(session)
    _draw(win)
    win.handle_mouse_press(_Ev(_card("container", "iron_arrow").center(), Qt.RightButton))
    assert drag.picked_source()[3] == 9
    win.handle_mouse_press(_Ev(_card("pack", "leather_cuirass").center()))
    hits.run_clicks(session)
    assert _qtys(session.container_inventory(), "iron_arrow") == [9]
    assert inv.quantity(session.game.character.inventory, "iron_arrow") == 9


def test_right_click_while_holding_puts_it_back(session):
    win = _window(session)
    _draw(win)
    before = [dict(st) for st in session.container_inventory()]
    win.handle_mouse_press(_Ev(_card("container", "bread").center(), Qt.RightButton))
    win.handle_mouse_press(_Ev(_card("container", "bread").center(), Qt.RightButton))
    assert drag.picked_source() is None
    assert hits.run_clicks(session) == 0
    assert session.container_inventory() == before


def test_right_click_on_a_single_thing_picks_nothing(session):
    win = _window(session)
    _draw(win)
    win.handle_mouse_press(_Ev(_card("container", "iron_helmet").center(), Qt.RightButton))
    assert drag.picked_source() is None


def test_half_your_stack_stored_in_the_chest(session):
    win = _window(session)
    _draw(win)
    win.handle_mouse_press(_Ev(_card("pack", "potion_heal").center(), Qt.RightButton))
    assert drag.picked_source() == ("pack", None, "potion_heal", 4)    # of seven
    win.handle_mouse_press(_Ev(_contents_space()))
    hits.run_clicks(session)
    assert inv.quantity(session.game.character.inventory, "potion_heal") == 3
    assert _qtys(session.container_inventory(), "potion_heal") == [3, 4]


def test_a_split_from_the_character_window_and_the_strip(session):
    from game.ui.inventory_window import InventoryWindow
    from game.ui.inventory_strip import InventoryStrip
    box = _window(session)
    win = InventoryWindow(session, x=40, y=620, view="character")
    strip = InventoryStrip(session)
    strip.place(1400, 900)
    _draw(win, box, strip)
    # A pack cell of five healing potions (seven carried: 5 and 2).
    cell = next(r for r, src in win._cells if src[2] == "potion_heal")
    win.handle_mouse_press(_Ev(cell.center(), Qt.RightButton))
    assert drag.picked_source() == ("pack", None, "potion_heal", 3)
    box.handle_mouse_press(_Ev(_contents_space()))
    hits.run_clicks(session)
    assert inv.quantity(session.game.character.inventory, "potion_heal") == 4
    # The strip: a right click on a stack picks up half; on a spell it still
    # readies it in the off hand.
    _draw(win, box, strip)
    i = next(k for k, st in enumerate(session.strip_slots()) if st and st["id"] == "bread")
    strip.handle_mouse_press(_Ev(strip._rects[i].center(), Qt.RightButton))
    assert drag.picked_source() == ("strip", i, "bread", 2)            # of three
    box.handle_mouse_press(_Ev(_card("container", "bread").center()))
    hits.run_clicks(session)
    assert inv.quantity(session.game.character.inventory, "bread") == 1
    assert _qtys(session.container_inventory(), "bread") == [7]        # joined


def test_runtime_split_rules(session):
    import game.sim.ownership as own
    items_ = session.container_inventory()
    # Moving within a container: a whole stack onto empty space is no split.
    assert not session.split_container_stack(1, 3)
    assert session.split_container_stack(1, 1)
    assert _qtys(items_, "potion_heal") == [2, 1]
    # Stolen goods never join honest ones.
    own.mark_stolen(items_[-1], "bryn", "Bryn")
    assert not session.split_container_stack(1, 1, len(items_) - 1)
    # A whole drop (no count) still moves the whole stack.
    assert session.item_drop(("container", 2, "bread"), ("pack", None))
    assert inv.quantity(session.game.character.inventory, "bread") == 8
    # Half a worn pair stored: the off hand lets go, the main hand keeps its blade.
    c = session.game.character
    inv.add_item(c.inventory, items.make("iron_shortsword"))
    session.game.equip("iron_shortsword")
    session.game.equip("iron_shortsword", items.SLOT_SHIELD)
    assert session.item_drop(("pack", None, "iron_shortsword", 1), ("container", None))
    assert inv.quantity(c.inventory, "iron_shortsword") == 1
    assert c.equipment.get(items.SLOT_WEAPON) == "iron_shortsword"
    assert c.equipment.get(items.SLOT_SHIELD) != "iron_shortsword"
