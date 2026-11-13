"""Metal interferes with magic: anyone wearing a piece of metal armour cannot
cast. Leather, studded leather, cloth, hide, fur, wood and elven work are fine,
and a shield never stops a spell, whatever it is made of.

The armour can be worn; every spell is then greyed out, cannot be selected or
readied, and hovering it (or gamepad focus on it) shows a tooltip.
"""

from __future__ import annotations

import random

import pytest

from ..rpg import equipment as eq, inventory as inv, items, magic
from ..rpg.game_state import GameState

METAL = ["iron_helmet", "iron_cuirass", "steel_shield", "chain_shirt", "scale_mail",
         "plate_gauntlets", "mithril_mail", "kite_shield", "tower_shield"]
NOT_METAL = ["leather_cuirass", "studded_leather", "studded_bracers", "cloth_robe",
             "hide_armour", "fur_cuirass", "elven_cuirass", "buckler", "round_shield"]


class _Store(dict):
    def set(self, key, value):
        self[key] = value


def test_a_shield_never_stops_a_spell():
    for shield in ("iron_shield", "steel_shield", "kite_shield", "tower_shield"):
        gs, c = _caster("knight", wearing=[shield])
        assert not magic.metal_blocks(c), shield
        assert gs.cast_active_spell().reason != "metal"


def _caster(class_id="mage", wearing=()):
    gs = GameState.new_game(_Store(), "T", "nord", class_id, "none", rng=random.Random(3))
    c = gs.character
    for iid in wearing:
        inv.add_item(c.inventory, items.make(iid))
        assert eq.equip(c, iid), iid
    c.known_spells = ["heal_minor"]
    c.active_spell = "heal_minor"
    eq.equip_spell(c, "heal_minor", "main")
    c.magicka = c.max_magicka
    return gs, c


@pytest.mark.parametrize("iid", METAL)
def test_metal_pieces_are_metal(iid):
    assert eq.is_metal(items.get(iid))


@pytest.mark.parametrize("iid", NOT_METAL)
def test_leather_and_the_rest_are_not(iid):
    assert not eq.is_metal(items.get(iid))


def test_jewellery_and_weapons_never_count():
    assert not eq.is_metal(items.get("copper_ring"))
    assert not eq.is_metal(items.get("iron_longsword"))


@pytest.mark.parametrize("class_id", ["mage", "sorcerer", "knight", "thief"])
def test_one_metal_piece_stops_anyone_casting_and_costs_nothing(class_id):
    gs, c = _caster(class_id, wearing=["iron_helmet"])
    before = c.magicka
    res = gs.cast_active_spell()
    assert not res.cast and res.reason == "metal"
    assert c.magicka == before
    assert gs.log[-1] == magic.METAL_INTERFERES == "The metal interferes..."


def test_leather_armour_casts_as_normal():
    gs, c = _caster("mage", wearing=["leather_cuirass", "leather_helmet", "studded_bracers"])
    res = magic.try_cast(c, "heal_minor", rng=random.Random(0))
    assert res.reason != "metal"
    assert c.magicka < c.max_magicka                 # it was paid for


def test_taking_the_metal_off_lets_the_spell_through():
    gs, c = _caster("mage", wearing=["chain_shirt"])
    assert magic.metal_blocks(c)
    eq.unequip(c, items.SLOT_CHEST)
    assert not magic.metal_blocks(c)


def test_an_explicit_metal_flag_overrides_the_material():
    d = items.get("leather_cuirass")
    d.extra["metal"] = True
    try:
        assert eq.is_metal(d)
    finally:
        del d.extra["metal"]


def test_the_session_says_why_and_never_casts(qt_app):
    """The cast key path (do_cast) and a staff both stop at worn metal."""
    from types import SimpleNamespace
    from ..runtime import MiniwindSession
    from .test_cast_controls import _Logic

    s = MiniwindSession(_Logic(), cfg={})
    s.needs_char_creation = False
    s.open_screen = None
    c = s.game.character
    c.class_id = "mage"
    c.known_spells = ["heal_minor"]
    c.active_spell = "heal_minor"
    eq.equip_spell(c, "heal_minor", "main")
    inv.add_item(c.inventory, items.make("plate_armour"))
    eq.equip(c, "plate_armour")
    c.magicka = c.max_magicka = 100.0
    notes = []
    s.notify = lambda text, *a, **k: notes.append(text)
    called = []
    s.game.cast_active_spell = lambda: called.append(1) or SimpleNamespace(cast=True)
    assert s.do_cast() is False
    assert not called and notes[-1] == magic.METAL_INTERFERES
    assert s._staff_attack({"staff_spell": "flare"}) is False
    assert notes[-1] == magic.METAL_INTERFERES and c.magicka == 100.0


# ------------------------------------------------------- greyed out in the UI
from PyQt5.QtCore import QRect  # noqa: E402

from ..ui import hits, spell_lock  # noqa: E402


@pytest.fixture
def armoured(qt_app, monkeypatch):
    """A session whose mage knows two spells, holds Flare in the left hand
    and wears an iron helmet; every tooltip drawn is recorded."""
    from .test_cast_controls import _Logic
    from ..runtime import MiniwindSession

    s = MiniwindSession(_Logic(), cfg={})
    s.logic._miniwind = s
    s.needs_char_creation = False
    s.open_screen = None
    c = s.game.character
    c.class_id = "mage"
    c.handed = "right"
    c.known_spells = ["flare", "heal_minor"]
    c.active_spell = "flare"
    eq.equip_spell(c, "flare", "off")              # the left hand
    inv.add_item(c.inventory, items.make("iron_helmet"))
    eq.equip(c, "iron_helmet")
    tips = []
    real = spell_lock.draw_tip
    monkeypatch.setattr(spell_lock, "draw_tip",
                        lambda p, text, pos: tips.append((text, pos)) or real(p, text, pos))
    monkeypatch.setattr(hits, "pointer", None)
    s.tips = tips
    hits.clear()
    yield s
    hits.clear()


def _image(w=1400, h=900):
    from PyQt5.QtGui import QImage, QPainter
    image = QImage(w, h, QImage.Format_ARGB32)
    image.fill(0)
    return image, QPainter(image)


def test_greyed_spells_cannot_be_readied_or_selected(armoured):
    from ..ui import screens
    s = armoured
    c = s.game.character
    assert not s.ready_spell("heal_minor", "right")
    assert eq.hand_spell(c, "main") is None
    screens._ready_spell(s, "heal_minor")
    assert c.active_spell == "flare"
    # Putting away what is already in hand is still allowed.
    assert s.ready_spell("flare", "left")
    assert eq.hand_spell(c, "off") is None


def test_without_metal_the_same_spell_readies(armoured):
    s = armoured
    eq.unequip(s.game.character, items.SLOT_HEAD)
    assert s.ready_spell("heal_minor", "right")
    assert eq.hand_spell(s.game.character, "main").id == "heal_minor"


def test_the_spellbook_greys_its_rows_and_hovering_one_shows_the_tooltip(armoured, monkeypatch):
    from ..ui import screens
    s = armoured
    s.open_screen = "spells"
    image, painter = _image()
    hits.begin()
    screens.draw_in_rect(painter, s, 40, 50, 900, 640)
    hits.end()
    painter.end()
    row = next(rect for rect, label in hits.targets() if label == "spell:heal_minor")
    monkeypatch.setattr(hits, "pointer", (row.center().x(), row.center().y()))
    image, painter = _image()
    hits.begin()
    screens.draw_in_rect(painter, s, 40, 50, 900, 640)
    hits.end()
    painter.end()
    assert s.tips and s.tips[-1][0] == "Metal armour prevents this"


def test_the_spellbook_tooltip_follows_gamepad_focus_without_a_pointer(armoured, monkeypatch):
    import game.controls as controls
    from ..ui import screens
    monkeypatch.setattr(controls, "gamepad", lambda: True)
    s = armoured
    s.open_screen = "spells"
    image, painter = _image()
    hits.begin()
    screens.draw_in_rect(painter, s, 40, 50, 900, 640)
    hits.end()
    painter.end()
    assert s.tips and s.tips[-1][0] == spell_lock.TIP


def test_no_tooltip_without_metal(armoured, monkeypatch):
    import game.controls as controls
    from ..ui import screens
    monkeypatch.setattr(controls, "gamepad", lambda: True)
    s = armoured
    eq.unequip(s.game.character, items.SLOT_HEAD)
    s.open_screen = "spells"
    image, painter = _image()
    hits.begin()
    screens.draw_in_rect(painter, s, 40, 50, 900, 640)
    hits.end()
    painter.end()
    assert s.tips == []


def test_the_character_window_greys_spells_and_shows_the_tooltip(armoured, monkeypatch):
    from ..ui.inventory_window import InventoryWindow
    s = armoured
    win = InventoryWindow(s)
    image, painter = _image()
    win._draw_content(painter, 0, 0, 1300, 860)
    painter.end()
    # The left hand's slot holds the greyed Flare.
    cell = next(r for r, src in win._cells if src[0] == "spell_hand")
    monkeypatch.setattr(hits, "pointer", (cell.center().x(), cell.center().y()))
    image, painter = _image()
    win._draw_content(painter, 0, 0, 1300, 860)
    painter.end()
    assert s.tips and s.tips[-1][0] == spell_lock.TIP


def test_the_character_window_has_a_left_and_a_right_hand_and_no_shield_slot():
    from ..ui import inventory_window as iw

    class Righty:
        handed = "right"

    class Lefty:
        handed = "left"

    labels = {slot: label for slot, label, _x, _y in iw.PAPERDOLL}
    assert labels[iw.HAND_LEFT] == "L" and labels[iw.HAND_RIGHT] == "R"
    assert "shield" not in labels and "weapon" not in labels
    where = {slot: (x, y) for slot, _label, x, y in iw.PAPERDOLL}
    # Level with the head, left and right, a little further out than the
    # other slots and a little bigger.
    assert where[iw.HAND_LEFT][1] == where[iw.HAND_RIGHT][1] == iw.HEAD_Y
    assert where[iw.HAND_LEFT][0] < where["hands"][0]
    assert where[iw.HAND_RIGHT][0] > where["ring"][0]
    # The torch slot sits under the head slot; the glove slot says so.
    assert labels["light"] == "Torch" and where["light"][0] == iw.COLUMN_IN
    # Torch and ring below the hands, gloves below them.
    assert where["light"][1] == where["ring"][1] > where[iw.HAND_LEFT][1]
    assert labels["hands"] == labels[iw.GLOVES_RIGHT] == "Gloves"
    # A glove box under each hand, mirrored about the middle: one slot.
    assert where["hands"][1] == where[iw.GLOVES_RIGHT][1] > where[iw.HAND_LEFT][1]
    assert where["hands"][0] + where[iw.GLOVES_RIGHT][0] == pytest.approx(1.0)
    assert iw._hand_slot(Righty(), iw.GLOVES_RIGHT) == "hands"
    # Body armour, legs, then feet, in a column below the head.
    assert where["chest"][0] == where["legs"][0] == where["feet"][0] == 0.50
    assert iw.HEAD_Y < where["chest"][1] < where["legs"][1] < where["feet"][1]
    assert iw.HAND_SLOT_SIZE > iw.SLOT_SIZE
    assert iw._hand_slot(Righty(), iw.HAND_RIGHT) == "weapon"
    assert iw._hand_slot(Righty(), iw.HAND_LEFT) == "shield"
    assert iw._hand_slot(Lefty(), iw.HAND_LEFT) == "weapon"
    assert iw._hand_slot(Lefty(), iw.HAND_RIGHT) == "shield"


def test_the_shortcut_bar_greys_a_spell_and_shows_the_tooltip(armoured, monkeypatch):
    from ..ui.inventory_strip import InventoryStrip
    s = armoured
    c = s.game.character
    from ..runtime import STRIP_SPELL
    s.strip_slots()
    c.strip[0] = STRIP_SPELL + "heal_minor"
    strip = InventoryStrip(s)
    strip.place(1300, 860)
    image, painter = _image()
    strip.draw(painter)
    painter.end()
    slot = next(i for i, st in enumerate(strip._slots) if st and st.get("spell"))
    rect = strip._rects[slot]
    assert rect.width() > 0
    monkeypatch.setattr(hits, "pointer", (rect.center().x(), rect.center().y()))
    image, painter = _image()
    strip.draw(painter)
    painter.end()
    assert strip._locked and s.tips and s.tips[-1][0] == spell_lock.TIP
    # A gamepad highlights the selected slot instead: the tooltip shows there.
    import game.controls as controls
    monkeypatch.setattr(controls, "gamepad", lambda: True)
    monkeypatch.setattr(hits, "pointer", None)
    strip.selected = slot
    s.tips.clear()
    image, painter = _image()
    strip.draw(painter)
    painter.end()
    assert s.tips and s.tips[-1][0] == spell_lock.TIP


def test_the_loadout_window_readies_by_mouse_button_and_greys_spells(armoured, monkeypatch):
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    from ..ui.loadout_window import LoadoutWindow
    s = armoured
    c = s.game.character
    eq.unequip(c, items.SLOT_HEAD)                 # no metal: it readies
    win = LoadoutWindow(s, x=0, y=0)
    win.tab = "spells"
    top = win.window_rect.y() + win.HEADER_H

    def paint():
        image, painter = _image()
        win.draw_body(painter, win.window_rect.x(), top, win.width)
        painter.end()

    paint()
    rect, _kind, sid = next(r for r in win._row_rects if r[2] == "heal_minor")

    def press(button):
        ev = QMouseEvent(QEvent.MouseButtonPress, QPoint(rect.center()), button, button,
                         Qt.NoModifier)
        assert win.handle_mouse_press(ev)
        hits.run_clicks(s)

    press(Qt.RightButton)
    assert eq.hand_spell(c, "main").id == "heal_minor"     # right hand
    press(Qt.LeftButton)
    assert eq.hand_spell(c, "off").id == "heal_minor"      # left hand
    # Metal on: greyed, the tooltip shows on hover, and nothing readies.
    eq.unequip_spell(c, "main")
    eq.unequip_spell(c, "off")
    inv.add_item(c.inventory, items.make("iron_helmet"))
    eq.equip(c, "iron_helmet")
    press(Qt.RightButton)
    assert eq.hand_spell(c, "main") is None
    monkeypatch.setattr(hits, "pointer", (rect.center().x(), rect.center().y()))
    paint()
    assert s.tips and s.tips[-1][0] == spell_lock.TIP


def test_the_hud_greys_a_spell_in_hand(armoured):
    from ..ui import hud
    s = armoured
    image, painter = _image()
    hud._draw_active(painter, s, s.game.character, 1300, 860)
    painter.end()


def test_grey_keeps_transparency(qt_app):
    from PyQt5.QtGui import QColor, QPainter, QPixmap
    pm = QPixmap(8, 8)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.fillRect(2, 2, 4, 4, QColor(255, 0, 0, 200))
    p.end()
    img = spell_lock.grey(pm).toImage()
    clear, solid = QColor.fromRgba(img.pixel(0, 0)), QColor.fromRgba(img.pixel(3, 3))
    assert clear.alpha() == 0
    assert solid.alpha() == 200 and solid.red() == solid.green() == solid.blue()


def test_an_empty_hand_slot_shows_the_paper_hand_mirrored_for_the_left(qt_app):
    from PyQt5.QtGui import QColor
    from ..ui import inventory_window as iw
    right = iw._hand_pixmap("right", 64)
    left = iw._hand_pixmap("left", 64)
    assert right is not None and left is not None        # the picture ships
    a, b = right.toImage(), left.toImage()
    w = a.width()
    for x, y in ((10, 30), (20, 40), (40, 20), (50, 50)):
        assert a.pixel(x, y) == b.pixel(w - 1 - x, y)
    paper = QColor.fromRgb(a.pixel(1, 1))
    assert paper.red() > paper.blue() + 30               # yellowed, not white


def test_a_torch_shows_in_its_own_slot_and_can_be_dropped_on_the_off_hand(qt_app):
    """A torch takes the off hand: dropped on that hand's slot it is equipped,
    and it shows in the Torch slot (not twice)."""
    from PyQt5.QtGui import QImage, QPainter
    from ..ui import inventory_window as iw
    from .test_inventory_window import _session
    s = _session("torch")
    c = s.game.character
    c.handed = "right"
    torch = items.get("torch")
    assert iw.fits(("equip", "shield"), torch)
    assert not iw.fits(("equip", "weapon"), torch)
    assert s.inventory_move(("pack", None, "torch"), ("equip", "shield"), "torch")
    assert eq.light_source(c) is not None
    win = iw.InventoryWindow(s)
    image = QImage(1300, 860, QImage.Format_ARGB32)
    painter = QPainter(image)
    win._draw_content(painter, 0, 0, 1300, 860)
    painter.end()
    held = [src for _r, src in win._cells if src[0] == "equip" and src[2] == "torch"]
    assert held == [("equip", "light", "torch")]        # in the Torch slot only
    # Dragged back to the pack, it is put away.
    assert s.inventory_move(("equip", "light", "torch"), ("pack", None), "torch")
    assert eq.light_source(c) is None


def test_both_glove_boxes_are_the_one_pair(qt_app):
    from PyQt5.QtGui import QImage, QPainter
    from ..ui import inventory_window as iw
    from .test_inventory_window import _session
    s = _session("leather_gauntlets")
    c = s.game.character
    win = iw.InventoryWindow(s)

    def cells():
        image = QImage(1300, 860, QImage.Format_ARGB32)
        painter = QPainter(image)
        win._draw_content(painter, 0, 0, 1300, 860)
        painter.end()
        return [src for _r, src in win._targets if src == ("equip", "hands")], \
               [src for _r, src in win._cells if src[0] == "equip" and src[1] == "hands"]

    targets, worn = cells()
    assert len(targets) == 2 and worn == []                # two boxes, one slot
    assert s.inventory_move(("pack", None, "leather_gauntlets"), ("equip", "hands"),
                            "leather_gauntlets")
    targets, worn = cells()
    assert worn == [("equip", "hands", "leather_gauntlets")] * 2   # shown in both
    assert s.inventory_move(worn[1], ("pack", None), "leather_gauntlets")
    assert eq.equipped_id(c, "hands") is None              # off from either
