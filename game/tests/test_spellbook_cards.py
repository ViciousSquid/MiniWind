"""The spellbook shows its spells as cards (game/ui/cards.py): a list of
wide row cards, one per line (cards.LAYOUT "list", the default), or a grid
of portrait cards (cards.LAYOUT "grid")."""

from types import SimpleNamespace

import pytest

QtCore = pytest.importorskip("PyQt5.QtCore")
QtGui = pytest.importorskip("PyQt5.QtGui")
pytestmark = pytest.mark.qt

from game import host, keybinds
from game.rpg import magic, items, equipment as eq, inventory as inv
from game.runtime import MiniwindSession
from game.ui import cards, hits, screens, spell_lock
from .fio_logic import FioLogic

TWELVE = ["flare", "firebolt", "frostbite", "lightning", "heal_minor", "heal",
          "sp_shield", "invisibility_minor", "sp_commandcreature", "summon_wolf",
          "disintegrate", "resurrection"]


class _Logic(FioLogic):
    def __init__(self):
        self.things = []
        self.player = SimpleNamespace(pos=[0.0, 0.0, 0.0], properties={})


@pytest.fixture
def session(qt_app, monkeypatch):
    for _action, _label, constant, default in keybinds.ACTIONS:
        monkeypatch.setattr(host, constant, default)
    s = MiniwindSession(_Logic(), cfg={})
    s.logic._miniwind = s
    s.needs_char_creation = False
    s.open_screen = "spells"
    s.game.character.class_id = "mage"
    s.game.character.known_spells = list(TWELVE)
    s.game.character.active_spell = "lightning"
    monkeypatch.setattr(hits, "pointer", None)
    hits.clear()
    yield s
    hits.clear()


def _paint(session, w, h, full=False):
    """Paint the spellbook; *full* draws it as the full-screen panel of a
    w x h view, else inside a (40, 50, w, h) body rect."""
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
    return image


def _panel(w, h, full):
    if full:
        x, y, bw, bh = screens._panel_rect(w, h)
        return QtCore.QRect(x, y, bw, bh)
    return QtCore.QRect(40, 50, w, h)


SIZES = [(1280, 720, True), (1920, 1080, True), (1100, 578, False)]


def _list_area():
    return next(r for r, t in screens._SPELL_HITS["targets"] if t == ("spells", None))


@pytest.mark.parametrize("w,h,full", SIZES)
def test_cards_are_a_list_inside_the_panel_without_overlap(session, w, h, full):
    _paint(session, w, h, full)
    cells = [rect for rect, _src in screens._SPELL_HITS["cells"]]
    assert len(cells) >= 3
    panel, area = _panel(w, h, full), _list_area()
    for i, a in enumerate(cells):
        assert panel.contains(a) and area.contains(a)
        # One wide card per row, the full width of the list.
        assert (a.x(), a.width()) == (area.x(), area.width())
        assert a.width() > 3 * a.height() and a.height() >= 80
        for b in cells[i + 1:]:
            assert not a.intersects(b) and b.y() > a.bottom()
    st = screens._sel(session)["spells"]
    assert st["cols"] == 1 and st["page_size"] == len(cells) < len(TWELVE)
    close = next(r for r, label in hits.targets() if label == "Close")
    assert all(not r.intersects(close) for r in cells)


@pytest.mark.parametrize("w,h,full", SIZES)
def test_the_grid_style_comes_back_with_one_switch(session, monkeypatch, w, h, full):
    monkeypatch.setattr(cards, "LAYOUT", "grid")
    _paint(session, w, h, full)
    cells = [rect for rect, _src in screens._SPELL_HITS["cells"]]
    assert len(cells) >= 4
    panel = _panel(w, h, full)
    for i, a in enumerate(cells):
        assert panel.contains(a)
        assert a.width() >= 110 and a.height() > a.width()        # portrait
        for b in cells[i + 1:]:
            assert not a.intersects(b)
    assert len({r.y() for r in cells}) >= 2                         # rows
    assert len({r.x() for r in cells}) >= 3                         # columns
    st = screens._sel(session)["spells"]
    assert st["page_size"] == len(cells) or len(cells) == len(TWELVE)
    # The grid leaves the detail column and its Raise / hands panel alone.
    close = next(r for r, label in hits.targets() if label == "Close")
    assert all(not r.intersects(close) for r in cells)


def test_every_card_is_a_drag_source_and_a_click_target(session):
    _paint(session, 1100, 578)
    sources = {src for _rect, src in screens._SPELL_HITS["cells"]}
    labels = {label for _rect, label in hits.targets()}
    page = screens._sel(session)["spells"]["page_size"]
    for sid in TWELVE[:page]:
        assert ("spell", None, sid) in sources
        assert f"spell:{sid}" in labels
    # A card's click target is the card itself.
    for rect, src in screens._SPELL_HITS["cells"]:
        assert any(r == rect and label == f"spell:{src[2]}" for r, label in hits.targets())


def test_arrows_move_up_and_down_the_list_across_pages(session):
    _paint(session, 1100, 578)
    st = screens._sel(session)["spells"]
    size = st["page_size"]
    assert st["cols"] == 1 and 2 <= size < len(TWELVE)
    st["row"] = 0
    screens.handle_key(session, "down")
    assert st["row"] == 1
    screens.handle_key(session, "s")
    assert st["row"] == 2
    screens.handle_key(session, "up")
    assert st["row"] == 1
    screens.handle_key(session, "left")                 # left / right step too
    assert st["row"] == 0
    screens.handle_key(session, "right")
    assert st["row"] == 1
    st["row"] = 0
    screens.handle_key(session, "up")                   # wraps to the last card
    assert st["row"] == len(TWELVE) - 1
    screens.handle_key(session, "down")                 # and back to the first
    assert st["row"] == 0
    st["row"] = size - 1                                # the page's last row
    screens.handle_key(session, "down")                 # onto the next page
    assert st["row"] == size and st["row"] // size == 1
    _paint(session, 1100, 578)
    assert screens._SPELL_HITS["cells"][0][1][2] == TWELVE[size]
    screens.handle_key(session, "pageup")
    assert st["row"] == 0
    screens.handle_key(session, "pagedown")
    assert st["row"] == size
    st["row"] = 0
    screens.handle_key(session, "enter")
    assert session.game.character.active_spell == "flare"


def test_arrows_move_by_card_and_by_row_in_the_grid_style(session, monkeypatch):
    monkeypatch.setattr(cards, "LAYOUT", "grid")
    _paint(session, 1100, 578)
    st = screens._sel(session)["spells"]
    cols, size = st["cols"], st["page_size"]
    assert cols >= 3 and size < len(TWELVE)
    st["row"] = 0
    screens.handle_key(session, "right")
    assert st["row"] == 1
    screens.handle_key(session, "down")
    assert st["row"] == 1 + cols
    screens.handle_key(session, "left")
    assert st["row"] == cols
    screens.handle_key(session, "up")
    assert st["row"] == 0
    screens.handle_key(session, "left")                 # wraps to the last card
    assert st["row"] == len(TWELVE) - 1
    st["row"] = size - 1                                # the page's last card
    screens.handle_key(session, "down")                 # onto the next page
    assert st["row"] // size == 1
    screens.handle_key(session, "pageup")
    assert st["row"] == 0
    screens.handle_key(session, "enter")
    assert session.game.character.active_spell == "flare"


def test_navigate_helper():
    nav = cards.navigate
    assert nav(0, "up", 10, 4) == 8                     # far end of the column
    assert nav(3, "up", 10, 4) == 7                     # short last row
    assert nav(5, "down", 10, 4) == 9
    assert nav(6, "down", 10, 4) == 9                   # into the short row
    assert nav(9, "down", 10, 4) == 1                   # wraps to the top
    assert nav(1, "pagedown", 10, 4, 8) == 8
    assert nav(9, "pageup", 10, 4, 8) == 0
    assert nav(0, "left", 0, 4) == 0
    # A list is one column: up / down step and wrap, pages turn.
    assert nav(0, "down", 10, 1) == 1 and nav(9, "down", 10, 1) == 0
    assert nav(0, "up", 10, 1) == 9 and nav(5, "up", 10, 1) == 4
    assert nav(3, "pagedown", 10, 1, 4) == 4 and nav(9, "pageup", 10, 1, 4) == 4
    assert nav(8, "pagedown", 10, 1, 4) == 8                # the last page


def test_layout_grid_and_compact_size():
    area = QtCore.QRect(0, 0, 700, 450)
    grid = cards.layout_grid(area, 20)
    assert (grid.cols, grid.rows) == (4, 2) and grid.card_size == cards.SIZE
    small = cards.layout_grid(area, 40, cards.COMPACT, cards.COMPACT_GAP)
    assert small.page_size > grid.page_size
    for g in (grid, small):
        assert all(area.contains(r) for r in g.slots)
    # Too short for two rows: the cards shrink so two fit.
    short = cards.layout_grid(QtCore.QRect(0, 0, 700, 380), 20)
    assert short.rows == 2 and short.card_size[1] < cards.SIZE[1]


def test_layout_list_rows():
    area = QtCore.QRect(10, 20, 600, 460)
    lst = cards.layout_list(area, 20)
    assert lst.cols == 1 and lst.page_size == lst.rows == len(lst.slots) >= 4
    for i, r in enumerate(lst.slots):
        assert area.contains(r) and (r.x(), r.width()) == (area.x(), area.width())
        assert r.height() == lst.card_size[1] >= cards.ROW_H * cards.ROW_FILL_SCALE
        if i:
            assert r.y() == lst.slots[i - 1].bottom() + 1 + cards.ROW_GAP
    # Room for most of one more row: the rows give a little to fit it.
    roomy = cards.layout_list(QtCore.QRect(0, 0, 600, 4 * 114 + 80), 20)
    assert roomy.rows == 5 and roomy.card_size[1] < cards.ROW_H
    # Few enough: rows keep their height; fit_all squeezes a long list onto
    # one page only as far as ROW_MIN_SCALE.
    few = cards.layout_list(area, 2)
    assert few.card_size[1] == cards.ROW_H and few.rows >= 2
    six = cards.layout_list(QtCore.QRect(0, 0, 600, 500), 6, fit_all=True)
    assert six.rows == 6 and six.bounds().height() <= 500
    many = cards.layout_list(QtCore.QRect(0, 0, 600, 500), 30, fit_all=True)
    assert many.rows < 30 and many.card_size[1] >= cards.ROW_H * cards.ROW_FILL_SCALE
    # Too short for one row: one row that fits.
    tiny = cards.layout_list(QtCore.QRect(0, 0, 300, 50), 3)
    assert tiny.rows == 1 and tiny.slots[0].height() == 50
    # cards.layout follows the switch; compact rows are shorter.
    assert cards.layout(area, 20).cols == 1
    assert cards.layout(area, 20, compact=True).card_size[1] < cards.ROW_H
    same = cards.layout(area, 20, compact=True, size=(1, 70))
    assert same.card_size[1] == 70


def test_layout_switch_restores_the_grid(monkeypatch):
    monkeypatch.setattr(cards, "LAYOUT", "grid")
    area = QtCore.QRect(0, 0, 700, 450)
    grid = cards.layout(area, 20)
    assert grid.cols >= 3 and grid.card_size == cards.SIZE


def test_locked_cards_are_greyed_and_say_why(session, monkeypatch):
    c = session.game.character
    c.known_spells = ["flare", "heal_minor"]
    c.active_spell = "flare"
    inv.add_item(c.inventory, items.make("iron_helmet"))
    eq.equip(c, "iron_helmet")
    assert spell_lock.locked(c)
    drawn = []
    real = cards.draw_card
    monkeypatch.setattr(cards, "draw_card",
                        lambda p, r, card: drawn.append(card) or real(p, r, card))
    tips = []
    monkeypatch.setattr(spell_lock, "draw_tip", lambda p, text, pos: tips.append(text))
    _paint(session, 1100, 578)
    assert drawn and all(card.locked for card in drawn)
    rect = next(r for r, src in screens._SPELL_HITS["cells"] if src[2] == "heal_minor")
    monkeypatch.setattr(hits, "pointer", (rect.center().x(), rect.center().y()))
    _paint(session, 1100, 578)
    assert tips[-1] == spell_lock.TIP
    screens._ready_spell(session, "heal_minor")
    assert c.active_spell == "flare"


def test_cards_show_selection_active_and_no_tooltip(session, monkeypatch):
    drawn = []
    real = cards.draw_card
    monkeypatch.setattr(cards, "draw_card",
                        lambda p, r, card: drawn.append((QtCore.QRect(r), card))
                        or real(p, r, card))
    screens._sel(session)["spells"] = {"row": 2}
    _paint(session, 1100, 578)
    by_title = {card.title: card for _r, card in drawn}
    assert by_title["Frostbite"].selected and not by_title["Flare"].selected
    assert by_title["Lightning Bolt"].active and not by_title["Flare"].active
    assert by_title["Flare"].icon is not None and not by_title["Flare"].icon.isNull()
    assert "Level" in by_title["Flare"].tooltip and "mp" in by_title["Flare"].badges[1]
    tips = []
    monkeypatch.setattr(cards, "draw_tooltip", lambda p, text, pos: tips.append(text))
    rect = next(r for r, card in drawn if card.title == "Firebolt")
    monkeypatch.setattr(hits, "pointer", (rect.center().x(), rect.center().y()))
    drawn.clear()
    _paint(session, 1100, 578)
    assert tips == []              # the pane on the right shows the spell instead
    assert next(card for _r, card in drawn if card.title == "Firebolt").hovered


@pytest.mark.parametrize("size", [cards.SIZE, cards.COMPACT, (90, 120)])
def test_draw_card_paints_every_variant(qt_app, size):
    image = QtGui.QImage(400, 400, QtGui.QImage.Format_ARGB32)
    image.fill(0)
    painter = QtGui.QPainter(image)
    pm = QtGui.QPixmap(64, 64)
    pm.fill(QtGui.QColor(200, 40, 40))
    try:
        for flags in ({}, {"selected": True, "active": True}, {"locked": True},
                      {"greyed": True, "hovered": True}):
            card = cards.Card(title="An Exceedingly Long Spell Name Indeed", icon=pm,
                              subtitle="Occult · Target", summary="17 damage for 3s",
                              accent=QtGui.QColor(176, 140, 240),
                              frame=QtGui.QColor(245, 165, 70), badges=("Lv 2/5", "12 mp"),
                              quantity=3, price="25 g", pips=(2, 5),
                              tooltip="Tip\nline", **flags)
            cards.draw_card(painter, QtCore.QRect(20, 20, *size), card)
        cards.draw_tooltip(painter, "Heading\nA line\nAnother", (100, 100))
    finally:
        painter.end()
    # Something was painted inside the card.
    assert QtGui.QColor(image.pixel(20 + size[0] // 2, 20 + size[1] // 2)).alpha() > 0


STATES = [{}, {"selected": True}, {"hovered": True}, {"active": True},
          {"selected": True, "active": True}, {"locked": True},
          {"greyed": True, "hovered": True}]


@pytest.mark.parametrize("height", [cards.ROW_H, cards.COMPACT_ROW_H, 64, 44])
@pytest.mark.parametrize("flags", STATES)
def test_draw_row_card_paints_every_state(qt_app, height, flags):
    w = 560
    image = QtGui.QImage(w + 40, height + 40, QtGui.QImage.Format_ARGB32)
    image.fill(0)
    painter = QtGui.QPainter(image)
    pm = QtGui.QPixmap(64, 64)
    pm.fill(QtGui.QColor(200, 40, 40))
    accent = QtGui.QColor(60, 200, 90)
    try:
        card = cards.Card(title="An Exceedingly Long Spell Name Indeed", icon=pm,
                          subtitle="Occult · Target", summary="17 damage for 3s",
                          desc="A long description that has to wrap onto more than one "
                               "line beside the picture, and then some more words after.",
                          accent=accent, frame=QtGui.QColor(245, 165, 70),
                          badges=("sold out", "12 mp"), quantity=3, price="25 g",
                          pips=(2, 5) if height > 60 else None, tooltip="Tip", **flags)
        cards.draw_row_card(painter, QtCore.QRect(20, 20, w, height), card)
    finally:
        painter.end()
    mid = 20 + height // 2
    grey = flags.get("locked") or flags.get("greyed")
    # The accent strip down the left edge (grey when locked / greyed).
    strip = QtGui.QColor(image.pixel(23, mid))
    assert strip.alpha() > 0
    if not grey:
        assert strip.green() > strip.red() and strip.green() > strip.blue()
    # The icon well, left, holds the picture (red, or grey when locked).
    well = QtGui.QColor(image.pixel(20 + 7 + height // 2, 20 + height // 3))
    assert (well.red() > 120 and well.green() < 90) != bool(grey)
    # The text runs across the middle; the right edge is painted body.
    assert QtGui.QColor(image.pixel(20 + w - 6, mid)).alpha() > 0


def test_row_card_title_is_never_cut_short(qt_app, monkeypatch):
    """The title shrinks to fit; it is never elided."""
    drawn = []
    real = QtGui.QPainter.drawText

    def spy(self, *args):
        drawn.append(args[-1] if isinstance(args[-1], str) else None)
        return real(self, *args)

    monkeypatch.setattr(QtGui.QPainter, "drawText", spy)
    image = QtGui.QImage(420, 120, QtGui.QImage.Format_ARGB32)
    painter = QtGui.QPainter(image)
    title = "The Duellist's Companion, Revised and Enlarged"
    try:
        cards.draw_row_card(painter, QtCore.QRect(0, 0, 400, 80),
                            cards.Card(title=title, desc="Words.", price="250 g"))
    finally:
        painter.end()
    assert title in drawn


def test_draw_card_picks_the_style_by_the_rect(qt_app, monkeypatch):
    seen = []
    monkeypatch.setattr(cards, "draw_row_card", lambda p, r, c: seen.append("row"))
    monkeypatch.setattr(cards, "draw_portrait_card", lambda p, r, c: seen.append("portrait"))
    card = cards.Card(title="x")
    cards.draw_card(None, QtCore.QRect(0, 0, 500, 100), card)
    cards.draw_card(None, QtCore.QRect(0, 0, 150, 210), card)
    assert seen == ["row", "portrait"]


def test_every_known_spell_paints_at_both_screen_sizes(session):
    session.game.character.known_spells = list(magic.SPELLS)
    for w, h in ((1280, 720), (1920, 1080)):
        screens._sel(session).pop("spells", None)
        _paint(session, w, h, full=True)
        st = screens._sel(session)["spells"]
        st["row"] = 0
        seen = set()
        for _ in range(len(magic.SPELLS)):
            _paint(session, w, h, full=True)
            seen.update(src[2] for _r, src in screens._SPELL_HITS["cells"])
            if st["row"] + st["page_size"] >= len(magic.SPELLS):
                break
            screens.handle_key(session, "pagedown")
        assert seen == set(magic.SPELLS)
