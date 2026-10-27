"""
Books and notes everywhere: where they are found, who deals in them, reading
them where they lie, the world furnished with containers to find them in,
and those containers seen from above.

Run:  python -m pytest game/tests/test_library.py -q
"""

from __future__ import annotations

import glob
import json
import os
import random

import pytest

from .. import books, library
from ..rpg import items
from .fio_logic import FioLogic

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))


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
    return s


def _give(s, *ids):
    from ..rpg import inventory as inv
    for iid in ids:
        inv.add_item(s.game.character.inventory, items.make(iid, 1))


def _merchant(name, role="merchant", **props):
    return _Thing(name, display_name=name, npc_role=role, merchant=True, **props)


# ------------------------------------------------------------- the library
def test_every_book_and_note_has_its_text_and_says_where_it_is_found():
    writing = items.items_by_category(items.BOOK)
    assert len(writing) >= 40
    for d in writing:
        assert books.book_of_item(d.id) is not None, d.id
        found = d.get("found")
        assert found and set(found) <= set(library.PLACES), d.id
        if d.get("teaches_skill"):
            from ..rpg import skills
            assert d.get("teaches_skill") in vars(skills).values(), d.id


def test_notes_are_kept_apart_from_books_and_no_shop_sells_them():
    assert library.notes() and library.books()
    assert not set(library.notes()) & set(library.books())
    assert not set(library.notes()) & set(library.books(library.SHOP))


def test_half_of_what_lies_about_is_a_note():
    rng = random.Random(3)
    picks = [library.pick(rng, library.TOWN) for _ in range(2000)]
    share = sum(p in library.notes() for p in picks) / len(picks)
    assert abs(share - library.NOTE_SHARE) < 0.05


def test_a_note_keeps_its_lines_as_written():
    note = books.get("note_shopping_list")
    assert note.lines[0][:3] == ["Flour, 2 sacks", "Salt",
                                 "Lamp oil — NOT the cheap stuff from Dunstan, it smokes"]


# ------------------------------------------------------------ the merchants
@pytest.mark.parametrize("name,role,deals", [
    ("Dunstan the Pedlar", "merchant", True), ("Wynn the Innkeeper", "merchant", True),
    ("Elowen the Trader", "merchant", True), ("Thalen the Smith", "blacksmith", False),
    ("Oswin the Armourer", "merchant", False), ("Hollin Brewer", "merchant", False),
    ("Fenwick the Hunter", "merchant", False), ("Head Chef", "villager", False),
])
def test_who_deals_in_books_goes_by_their_trade(name, role, deals):
    assert library.deals_in_books({"display_name": name, "npc_role": role}) is deals


def test_an_authored_choice_decides_it():
    assert library.deals_in_books({"display_name": "Thalen the Smith",
                                   "npc_role": "blacksmith", "buys_books": True})
    assert not library.deals_in_books({"display_name": "Dunstan", "buys_books": False})


def test_each_bookish_merchant_keeps_titles_of_their_own():
    a = library.shop_books({"id": "a", "display_name": "Dunstan the Pedlar"})
    b = library.shop_books({"id": "b", "display_name": "Nell the Innkeeper"})
    assert len(a) == library.SHOP_TITLES and a != b
    assert a == library.shop_books({"id": "a", "display_name": "Dunstan the Pedlar"})
    assert library.shop_books({"display_name": "Hollin Brewer"}) == []


def test_a_bookish_merchants_shelf_has_books_and_a_smiths_has_none():
    from ..ui import screens
    pedlar = screens._merchant_stock(_merchant("Dunstan the Pedlar"))
    smith = screens._merchant_stock(_merchant("Thalen the Smith", role="blacksmith"))
    assert any(library.is_book(e["id"]) for e in pedlar)
    assert not any(library.is_book(e["id"]) for e in smith)


def test_a_merchant_with_no_use_for_books_will_not_buy_one():
    brewer = _merchant("Hollin Brewer")
    s = _session(brewer)
    _give(s, "book_long_table", "bread")
    s.merchant_npc = brewer
    said = []
    s.notify = lambda text, *a, **k: said.append(text)
    gold = s.game.character.gold
    assert s.sell("book_long_table") is False
    assert s.game.character.gold == gold
    assert said == [library.NOT_INTERESTED]
    assert s.sell("bread") is True                    # anything else, as before


def test_a_bookish_merchant_buys_books():
    pedlar = _merchant("Dunstan the Pedlar")
    s = _session(pedlar)
    _give(s, "book_long_table")
    s.merchant_npc = pedlar
    assert s.sell("book_long_table") is True


# ------------------------------------------------------ reading where it lies
def test_a_book_in_a_chest_is_read_without_taking_it():
    from ..ui import screens
    chest = _Thing("Chest", type="container",
                   inventory=[items.make("book_kingsfall", 1)])
    s = _session(chest)
    s.open_container(chest)
    screens._handle_container(s, "r")
    assert s.open_screen == "book" and s.reading["book"] == "crossing_kingsfall"
    assert [st["id"] for st in chest.properties["inventory"]] == ["book_kingsfall"]
    assert s.game.character.read_books == []          # read, not studied
    s.close_book()
    assert s.open_screen == "container"


def test_a_book_on_a_shelf_is_read_before_it_is_bought():
    from ..ui import screens
    pedlar = _merchant("Dunstan the Pedlar")
    s = _session(pedlar)
    s.merchant_npc, s.open_screen = pedlar, "trade"
    stock = screens._merchant_stock(pedlar)
    st = screens._sel(s).setdefault("trade", {"row": 0, "side": 0})
    st["row"] = next(i for i, e in enumerate(stock) if library.is_book(e["id"]))
    screens._handle_trade(s, "r")
    assert s.open_screen == "book"
    s.close_book()
    assert s.open_screen == "trade" and s.merchant_npc is pedlar


def test_a_note_opens_as_a_note():
    s = _session()
    _give(s, "note_poem_heron", "book_kingsfall")
    s.inventory_use("note_poem_heron")
    assert s.reading["note"] is True
    s.close_book()
    s.inventory_use("book_kingsfall")
    assert s.reading["note"] is False


def test_a_byline_reads_as_written_when_it_says_how_the_book_came_to_be():
    from ..ui.book_window import byline
    assert byline("Edda Reedwife") == "By Edda Reedwife"
    assert byline("As told by the Coldharbour family") == "As told by the Coldharbour family"
    assert byline("(on the back of a feed bill)") == "(on the back of a feed bill)"


@pytest.mark.qt
def test_a_note_is_laid_out_line_by_line_and_a_long_byline_wraps(qt_app):
    from ..ui import fonts
    from ..ui.book_window import paginate, paginate_note
    f = (fonts.dialogue_font(26), fonts.dialogue_font(14), fonts.dialogue_font(15))
    pages = paginate_note(books.get("note_shopping_list"), f, 600, 900)
    body = [text for kind, text, _y in pages[0] if kind == "body"]
    assert body[:2] == ["Flour, 2 sacks", "Salt"]
    pages = paginate(books.get("crossing_kingsfall"), f, 260, 600)
    from PyQt5.QtGui import QFontMetrics
    for kind, text, _y in pages[0]:
        if kind == "author":
            assert QFontMetrics(f[1]).horizontalAdvance(text) <= 260


def test_trade_thumbnails_are_half_the_inventory_icons():
    from ..ui import inventory_window, screens
    assert screens.TRADE_THUMB == (inventory_window.CELL - 10) // 2


# ------------------------------------------------------- the world furnished
def test_contents_are_rolled_the_same_way_every_time_and_never_empty():
    from ..tools import furnish_world as fw
    for theme in fw.TABLES:
        a = fw.roll_contents(theme, library.seeded("t", theme))
        b = fw.roll_contents(theme, library.seeded("t", theme))
        assert a and [s["id"] for s in a] == [s["id"] for s in b]


def test_a_cave_is_furnished_on_open_floor_and_a_second_run_changes_nothing():
    from ..tools import furnish_world as fw
    path = sorted(glob.glob(os.path.join(REPO, "maps", "cave[0-9][0-9].json")))[0]
    with open(path) as f:
        cave = json.load(f)
    fw.furnish_cave(cave, "cave01", report=lambda *_: None)
    first = json.dumps(cave, sort_keys=True)
    fw.furnish_cave(cave, "cave01", report=lambda *_: None)
    assert json.dumps(cave, sort_keys=True) == first
    floor = fw.cave_floor(cave)
    added = [t for t in cave["things"] if t["properties"].get(fw.TAG)]
    assert sum(t["type"] == "container" for t in added) >= fw.CAVE_CONTAINERS[0]
    cells = {(round(x), round(z)) for x, z in floor.values()}
    for t in added:
        assert (round(t["pos"][0]), round(t["pos"][2])) in cells


def test_the_maps_carry_the_furnishing():
    with open(os.path.join(REPO, "maps", "village_walled_source.json")) as f:
        world = json.load(f)
    added = [t for t in world["things"] if t["properties"].get("_furnished")]
    owned = [t for t in added if t["properties"].get("owner")]
    assert len([t for t in added if t["type"] == "container"]) > 200
    assert len(owned) > 50
    assert all("angle" in t["properties"] for t in added)


# ------------------------------------------------------- seen from above
def test_containers_and_pickups_near_the_player_are_drawn_from_above():
    from ..ui import world_objects as wo
    chest = _Thing("Chest", (100.0, 0.0, 0.0), type="container", container_kind="barrel",
                   id="c1")
    far = _Thing("Far", (99999.0, 0.0, 0.0), type="container", id="c2")
    gone = _Thing("Gone", (50.0, 0.0, 0.0), type="itempickup", item_id="book_lore",
                  dead=True)
    book = _Thing("Book", (60.0, 0.0, 40.0), type="itempickup", item_id="note_iou",
                  angle=90.0)
    s = _session(chest, far, gone, book)
    s._player_pos = lambda: [0.0, 0.0, 0.0]
    drawn = wo.visible(s)
    assert len(drawn) == 2
    (pos, _turn, art, _size, layer), (_p2, turn, icon, _s2, _l2) = drawn
    assert pos[1] == 0.0 and layer > 0          # on the floor, layered by depth
    assert art.endswith(os.path.join("topdown", "barrel.png")) and os.path.isfile(art)
    assert icon.endswith("note_iou.png") and turn == pytest.approx(1.5707963)


def test_every_container_kind_has_top_down_art():
    from ..entities import CONTAINER_KINDS
    from ..ui import world_objects as wo
    for kind in CONTAINER_KINDS:
        assert os.path.isfile(wo.container_art(kind))
        assert wo.container_art(kind).endswith(f"{kind}.png")


def test_blood_lies_on_the_floor_it_fell_on():
    from .. import gore_fx
    g = gore_fx.GoreFX()
    g.ground = lambda x, y, z: 208.0
    g._splat((0.0, 150.0, 0.0), 40.0)
    (pos, *_rest), = g.floor_decals()
    assert pos[1] == 208.0
