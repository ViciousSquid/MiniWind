"""Known spells on the shortcut bar (the inventory strip): dragged there from
the spellbook (or a hand), a number key takes the spell up in the main hand
and casts it at once, the main hand's weapon taking the spell's slot; a spell
casts only from a hand; slots swap when dragged onto each other; and the bar
survives a save."""

from types import SimpleNamespace

import pytest

from game import host
from game.rpg import equipment as eq, items, magic as rpg_magic
from game.rpg.character import Character
from game.runtime import MiniwindSession
from .test_cast_controls import _Logic


def _caster():
    c = Character.create("Mage", "valian", "mage")
    c.known_spells = ["flare", "heal_minor"]
    c.inventory = [items.make(iid) for iid in ("iron_shortsword", "potion_heal_minor")]
    c.equipment = {}
    c.strip = []
    c._strip_seen = set()
    c._strip_offered = {}
    c.magicka = c.max_magicka
    return c


def _session():
    s = MiniwindSession(_Logic(), cfg={})
    s.needs_char_creation = False
    s.open_screen = None
    s.game.character = _caster()
    return s


def _bar(s):
    return [e["id"] if e else None for e in s.strip_slots()]


def _press(s, key, shift=False):
    game = host.MiniwindGame.__new__(host.MiniwindGame)
    ctx = SimpleNamespace(key_down=lambda k: shift and k == "shift")
    game._handle_gameplay_input(s, {key}, ctx)


@pytest.fixture
def sure_casts(monkeypatch):
    """Every cast check succeeds, and a bolt is noted instead of flown."""
    monkeypatch.setattr(rpg_magic, "cast_check", lambda *a, **k: (True, {}))

    def install(s):
        s.bolts = []
        s._spawn_player_spell_projectile = lambda spell, aim=None: s.bolts.append(
            (spell.id, aim))
        s._magic_cast_fx = lambda *a, **k: None
        return s
    return install


def test_a_spell_dragged_from_the_spellbook_or_a_hand_lands_on_its_slot():
    s = _session()
    c = s.game.character
    assert s.item_drop(("spell", None, "flare"), ("strip", 3))
    slots = s.strip_slots()
    assert slots[3]["spell"] == "flare" and slots[3]["id"] == "spell:flare"
    eq.equip_spell(c, "heal_minor", "off")
    assert s.item_drop(("spell_hand", "off", "heal_minor"), ("strip", 7))
    assert _bar(s)[7] == "spell:heal_minor"
    assert not s.item_drop(("spell", None, "lightning"), ("strip", 4))   # not known
    assert _bar(s)[4] != "spell:lightning"


def test_the_number_key_equips_the_spell_casts_it_and_swaps_the_weapon_into_its_slot(
        sure_casts):
    s = sure_casts(_session())
    c = s.game.character
    assert _bar(s)[:2] == ["iron_shortsword", "potion_heal_minor"]
    _press(s, "1")                                       # the sword in hand
    assert eq.weapon(c).id == "iron_shortsword"
    s.set_strip_slot(4, "spell:flare")
    before = c.magicka
    _press(s, "5")
    # The spell is in the main hand, and cast straight away along the facing.
    assert eq.hand_spell(c, "main").id == "flare"
    assert eq.weapon(c) is None
    assert s.bolts == [("flare", "facing")]
    assert c.magicka < before
    # The sword took the spell's slot, and left its own.
    assert _bar(s)[4] == "iron_shortsword"
    assert "spell:flare" not in _bar(s)
    assert _bar(s).count("iron_shortsword") == 1 and _bar(s)[0] is None
    # It stays in hand: the hand's mouse button casts it again.
    s._cast_cooldown = 0.0
    s.fire_player_weapon(s.logic, "secondary" if c.handed == "right" else "primary")
    assert s.bolts == [("flare", "facing")] * 2
    assert eq.hand_spell(c, "main").id == "flare"
    # The same key takes the sword back, and the spell its slot again.
    _press(s, "5")
    assert eq.weapon(c).id == "iron_shortsword"
    assert eq.hand_spell(c, "main") is None
    assert _bar(s)[4] == "spell:flare"
    assert len(s.bolts) == 2


def test_a_spell_in_the_main_hand_is_swapped_for_another(sure_casts):
    s = sure_casts(_session())
    c = s.game.character
    s.set_strip_slot(2, "spell:flare")
    s.set_strip_slot(3, "spell:heal_minor")
    _press(s, "3")                    # empty hand: flare stays on its slot too
    assert eq.hand_spell(c, "main").id == "flare"
    assert _bar(s)[2] == "spell:flare"
    s._cast_cooldown = 0.0
    _press(s, "4")
    assert eq.hand_spell(c, "main").id == "heal_minor"
    assert _bar(s)[3] == "spell:flare" and "spell:heal_minor" not in _bar(s)
    assert [b for b in s.bolts] == [("flare", "facing")]   # heal is a self spell


def test_a_spell_already_in_the_main_hand_just_casts_again(sure_casts):
    s = sure_casts(_session())
    c = s.game.character
    s.set_strip_slot(2, "spell:flare")
    eq.equip_spell(c, "flare", "main")
    assert s.select_strip_slot(2)
    assert eq.hand_spell(c, "main").id == "flare" and _bar(s)[2] == "spell:flare"
    assert s.bolts == [("flare", "facing")]


def test_shift_readies_a_bar_spell_in_the_off_hand_without_casting(sure_casts):
    s = sure_casts(_session())
    c = s.game.character
    eq.equip(c, "iron_shortsword")
    s.set_strip_slot(6, "spell:flare")
    _press(s, "7", shift=True)
    assert eq.hand_spell(c, "off").id == "flare"
    assert eq.weapon(c).id == "iron_shortsword"
    assert _bar(s)[6] == "spell:flare" and not s.bolts


def test_casting_a_spell_not_held_in_a_hand_is_refused(sure_casts):
    s = sure_casts(_session())
    c = s.game.character
    eq.equip(c, "iron_shortsword")
    c.active_spell = "flare"                     # selected in the spellbook
    before = c.magicka
    assert not s.do_cast(aim="facing")
    assert not s.do_cast(aim="facing", hand="main")
    assert not s.cast_key()
    assert not s.game.cast_active_spell().cast
    s.attack_with_both = lambda: None
    s.fire_player_weapon(s.logic, "primary")
    s.fire_player_weapon(s.logic, "secondary")
    assert c.magicka == before and not s.bolts
    # On the bar, the number key equips it first -- then it casts.
    s.set_strip_slot(0, "spell:flare")
    _press(s, "1")
    assert eq.hand_spell(c, "main").id == "flare" and s.bolts


def test_a_class_without_magic_cannot_cast_from_the_bar(sure_casts):
    s = sure_casts(_session())
    c = s.game.character
    eq.equip(c, "iron_shortsword")
    s.set_strip_slot(4, "spell:flare")
    c.can_use_magic = lambda: False
    assert not s.select_strip_slot(4)
    assert eq.weapon(c).id == "iron_shortsword" and not c.hand_spells
    assert _bar(s)[4] == "spell:flare" and not s.bolts


def test_a_slot_dragged_onto_an_occupied_slot_swaps_and_onto_an_empty_one_moves():
    s = _session()
    s.set_strip_slot(5, "spell:flare")
    assert _bar(s)[:2] == ["iron_shortsword", "potion_heal_minor"]
    # A spell onto an item: the two change places.
    assert s.item_drop(("strip", 5, "spell:flare"), ("strip", 0))
    assert _bar(s)[0] == "spell:flare" and _bar(s)[5] == "iron_shortsword"
    # An item onto a spell: likewise.
    assert s.item_drop(("strip", 1, "potion_heal_minor"), ("strip", 0))
    assert _bar(s)[0] == "potion_heal_minor" and _bar(s)[1] == "spell:flare"
    # An item onto an item.
    assert s.item_drop(("strip", 5, "iron_shortsword"), ("strip", 0))
    assert _bar(s)[0] == "iron_shortsword" and _bar(s)[5] == "potion_heal_minor"
    # A spell onto a spell.
    s.set_strip_slot(8, "spell:heal_minor")
    assert s.item_drop(("strip", 8, "spell:heal_minor"), ("strip", 1))
    assert _bar(s)[1] == "spell:heal_minor" and _bar(s)[8] == "spell:flare"
    # Onto an empty slot: moved, its old slot left empty.
    assert s.item_drop(("strip", 8, "spell:flare"), ("strip", 3))
    assert _bar(s)[3] == "spell:flare" and _bar(s)[8] is None
    assert s.item_drop(("strip", 0, "iron_shortsword"), ("strip", 7))
    assert _bar(s)[7] == "iron_shortsword" and _bar(s)[0] is None


def test_bar_spells_and_the_swapped_weapon_survive_a_save(sure_casts):
    s = sure_casts(_session())
    c = s.game.character
    eq.equip(c, "iron_shortsword")
    s.set_strip_slot(4, "spell:flare")
    s.set_strip_slot(6, "spell:heal_minor")
    _press(s, "5")                     # flare in hand, the sword on slot 5
    bar = _bar(s)
    s.game.save_to_store()             # the game's own save of the character
    t = sure_casts(_session())
    t.game.store = s.game.store
    assert t.game.load_from_store()
    loaded = t.game.character
    assert loaded is not c
    assert _bar(t) == bar
    assert _bar(t)[4] == "iron_shortsword" and _bar(t)[6] == "spell:heal_minor"
    assert eq.hand_spell(loaded, "main").id == "flare"
    assert eq.weapon(loaded) is None
    # And it all still works after loading: 7 swaps flare out for heal.
    _press(t, "7")
    assert eq.hand_spell(loaded, "main").id == "heal_minor"
    assert _bar(t)[6] == "spell:flare"


@pytest.mark.qt
def test_a_spell_dragged_out_of_the_open_spellbook_lands_on_the_bar(qt_app):
    from ..ui import drag, hits
    from ..ui.inventory_strip import InventoryStrip
    from ..ui.pack_window import PackWindow
    from .test_inventory_strip import _paint, _drag
    drag.reset()
    hits.clear()
    s = _session()
    s.open_screen = "spells"
    book = PackWindow(s, x=40, y=10)
    assert book.screen == "spells"
    strip = InventoryStrip(s)
    strip.place(1280, 800)
    _paint(book, strip)
    row = next(r for r, src in book._cells if src == ("spell", None, "heal_minor"))
    _drag(book, row.center(), strip._rects[8].center())
    hits.run_clicks(s)
    assert _bar(s)[8] == "spell:heal_minor"
    drag.reset()
    hits.clear()


def test_an_empty_bar_slot_names_the_spellbook_key(monkeypatch):
    from ..ui import inventory_strip
    s = _session()
    assert inventory_strip._spellbook_hint(s) == "Spellbook (P): drag a spell here"
    monkeypatch.setattr(host, "K_SPELLS", "k")         # rebound
    assert "(K)" in inventory_strip._spellbook_hint(s)
    s.game.character.known_spells = []
    assert inventory_strip._spellbook_hint(s) == ""
