"""The key hints after character creation (game/key_hints.py): the I key
over "Inventory", then -- for a character who starts with spells -- the P key over
"Spellbook"; 0.5 s in, 2 s held, 0.5 s out; never both at once; a hint's
key hides it at once."""

from __future__ import annotations

import configparser

import pytest

from game.rpg.classes import CREATION_CLASS_IDS

from .. import key_hints as kh
from .test_player_head import _Globals, _actor, _session

pytest.importorskip("PyQt5.QtGui")
pytestmark = pytest.mark.qt


def _new(klass="warrior"):
    s = _session([_actor("Villager")])
    s.begin_new_character("Tester", "valian", klass, "none", "male", head="head13")
    return s


def _alpha(hints, t):
    shown = hints.frame(t)
    return (shown[0], shown[2]) if shown else (None, 0.0)


# -- timeline ----------------------------------------------------------------
@pytest.mark.parametrize("t, alpha", [(0.0, 0.0), (0.25, 0.5), (0.5, 1.0),
                                      (2.5, 1.0), (2.75, 0.5), (3.0, 0.0)])
def test_the_timeline(t, alpha):
    assert kh.alpha_at(t) == pytest.approx(alpha)
    hints = kh.KeyHints(magic=False)
    hints.begin(0.0)
    action, a = _alpha(hints, t)
    assert a == pytest.approx(alpha)
    if alpha:
        assert action == "inventory"


def test_a_fighters_hints_end_after_the_inventory_key():
    hints = kh.KeyHints(magic=False)
    hints.begin(10.0)
    assert _alpha(hints, 11.0) == ("inventory", 1.0)
    assert _alpha(hints, 13.0) == (None, 0.0)
    assert hints.done
    assert all(_alpha(hints, t)[1] == 0.0 for t in (14.0, 16.0, 20.0))


def test_slow_time_does_not_stretch_a_hint():
    """Real time, not game time: the hint is over 3 s after it began whatever
    the world's time scale."""
    s = _new()
    s.logic.time_scale = 0.5
    assert kh.current(s, 100.0) is None              # first frame: begins now
    assert kh.current(s, 101.0)[2] == pytest.approx(1.0)
    assert kh.current(s, 103.01) is None


# -- the inventory key -------------------------------------------------------
def test_the_inventory_key_hides_it_at_once():
    hints = kh.KeyHints(magic=False)
    hints.begin(0.0)
    assert _alpha(hints, 1.0) == ("inventory", 1.0)
    hints.press("inventory", 1.0)
    assert _alpha(hints, 1.0) == (None, 0.0)          # gone, no fade
    assert _alpha(hints, 1.2) == (None, 0.0)
    assert hints.done


def test_the_host_hides_it_by_the_bound_key():
    import game.host as host
    s = _new()
    assert kh.current(s, 0.0) is None                 # begins: alpha 0
    assert kh.current(s, 1.0)[0] == "I"
    kh.note_keys(s, {host.K_INVENTORY}, {"inventory": host.K_INVENTORY,
                                         "spells": host.K_SPELLS}, 1.0)
    assert kh.current(s, 1.01) is None


def test_opening_the_inventory_any_way_hides_it():
    s = _new()
    kh.current(s, 0.0)
    assert kh.current(s, 1.0) is not None
    s.open_screen = "inventory"
    assert kh.current(s, 1.1) is None
    s.open_screen = None
    assert kh.current(s, 1.2) is None


# -- the spellbook key -------------------------------------------------------
def _queue(s):
    return [a for a, _c in s.key_hints.queue]


@pytest.mark.parametrize("klass", CREATION_CLASS_IDS)
def test_only_a_character_who_starts_with_spells_is_shown_the_spellbook(klass):
    s = _new(klass)
    has_spells = bool(s.game.character.known_spells)
    assert _queue(s) == (["inventory", "spells"] if has_spells else ["inventory"])


def test_a_build_given_spells_is_shown_it_and_one_without_is_not():
    s = _new("warrior")
    s.game.character.known_spells = ["flare"]
    kh.arm(s)
    assert _queue(s) == ["inventory", "spells"]
    s = _new("mage")
    s.game.character.known_spells = []
    kh.arm(s)
    assert _queue(s) == ["inventory"]


def test_the_spellbook_follows_once_the_inventory_hint_has_faded():
    hints = kh.KeyHints(magic=True)
    hints.begin(0.0)
    for t in (0.1, 0.5, 1.0, 2.0, 2.5, 2.9):
        assert _alpha(hints, t)[0] in ("inventory", None)
        assert hints.showing(t) == "inventory"
    assert _alpha(hints, 3.25) == ("spells", pytest.approx(0.5))
    assert _alpha(hints, 4.0) == ("spells", 1.0)
    assert _alpha(hints, 5.75) == ("spells", pytest.approx(0.5))
    assert _alpha(hints, 6.0) == (None, 0.0)
    assert hints.done


def test_never_both_at_once():
    hints = kh.KeyHints(magic=True)
    hints.begin(0.0)
    seen = set()
    t = 0.0
    while t < 8.0:
        action, a = _alpha(hints, t)
        if a:
            seen.add(action)
            assert hints.showing(t) == action
        t += 0.05
    assert seen == {"inventory", "spells"}


def test_hidden_early_the_spellbook_still_waits_three_seconds():
    """P starts at max(start + 3 s, the moment I ended)."""
    hints = kh.KeyHints(magic=True)
    hints.begin(0.0)
    hints.press("inventory", 1.0)
    assert _alpha(hints, 2.0) == (None, 0.0)
    assert _alpha(hints, 2.99) == (None, 0.0)
    assert _alpha(hints, 3.25) == ("spells", pytest.approx(0.5))


def test_the_spellbook_waits_for_the_inventory_hint_to_end():
    hints = kh.KeyHints(magic=True)
    hints.begin(0.0)
    # The inventory hint runs its full 3 s: P's start is when it ended.
    assert hints.showing(2.99) == "inventory"
    assert hints.showing(3.0) == "spells"
    assert hints.started == pytest.approx(3.0)


def test_the_spellbook_key_hides_its_hint():
    hints = kh.KeyHints(magic=True)
    hints.begin(0.0)
    assert _alpha(hints, 4.0) == ("spells", 1.0)
    hints.press("spells", 4.0)
    assert _alpha(hints, 4.0) == (None, 0.0)
    assert hints.done


def test_the_spellbook_key_pressed_first_skips_its_hint():
    hints = kh.KeyHints(magic=True)
    hints.begin(0.0)
    hints.press("spells", 1.0)                       # I still up: unaffected
    assert _alpha(hints, 1.5) == ("inventory", 1.0)
    assert all(_alpha(hints, t)[1] == 0.0 for t in (3.25, 4.0, 5.0))
    assert hints.done


def test_the_inventory_key_does_not_hide_the_spellbook_hint():
    hints = kh.KeyHints(magic=True)
    hints.begin(0.0)
    hints.press("inventory", 4.0)
    assert _alpha(hints, 4.1) == ("spells", 1.0)


# -- menus and pauses ----------------------------------------------------------
def test_waits_for_play_to_be_in_view():
    """The tutorial's pages (or any menu) up as play begins: the hint starts
    when they close."""
    s = _new("mage")
    s.open_screen = "tutorial"
    assert kh.current(s, 0.0) is None
    assert kh.current(s, 5.0) is None
    assert s.key_hints.showing(5.0) is None
    s.open_screen = None
    assert kh.current(s, 6.0) is None                 # starts now
    assert kh.current(s, 6.25)[1:] == ("Inventory", pytest.approx(0.5))


def test_a_started_hint_keeps_its_clock_under_a_menu_but_is_not_drawn():
    s = _new()
    kh.current(s, 0.0)
    assert kh.current(s, 1.0) is not None
    s.open_screen = "journal"
    assert kh.current(s, 1.5) is None
    s.open_screen = None
    assert kh.current(s, 2.0)[2] == pytest.approx(1.0)
    assert kh.current(s, 3.1) is None


# -- new characters only ---------------------------------------------------------
def test_not_shown_after_loading_a_save():
    """CONTINUE / a loaded save: the character is the save's, not new."""
    stored = _Globals()
    made = _session([_actor("Villager")], globals_store=stored)
    made.begin_new_character("Tester", "valian", "mage", "none", "male", head="head13")
    assert made.key_hints is not None
    made.game.save_to_store()

    loaded = _session([_actor("Villager")], globals_store=stored)
    loaded.restore()
    assert not loaded.needs_char_creation
    assert loaded.game.character.name == "Tester"
    assert loaded.key_hints is None
    assert all(kh.current(loaded, t) is None for t in (0.0, 1.0, 4.0))


def test_a_new_session_has_none_until_a_character_is_made():
    s = _session([_actor("Villager")])
    assert s.key_hints is None
    assert kh.current(s, 1.0) is None


# -- rebinding -----------------------------------------------------------------
def test_rebinding_changes_the_letter():
    import game.host as host
    import game.keybinds as keybinds
    config = configparser.ConfigParser()
    config.read_string("[KEYS]\ninventory = g\nspells = k\n")
    try:
        keybinds.apply(config)
        assert kh.key_letter("inventory") == "G"
        assert kh.key_letter("spells") == "K"
        s = _new("mage")
        kh.current(s, 0.0)
        assert kh.current(s, 1.0)[:2] == ("G", "Inventory")
        kh.note_keys(s, {"i"}, {"inventory": host.K_INVENTORY, "spells": host.K_SPELLS}, 1.05)
        assert kh.current(s, 1.1) is not None         # I is not the key now
        kh.note_keys(s, {"g"}, {"inventory": host.K_INVENTORY, "spells": host.K_SPELLS}, 1.15)
        assert kh.current(s, 1.2) is None
        assert kh.current(s, 4.0)[:2] == ("K", "Spellbook")
    finally:
        keybinds.apply(None)
    assert kh.key_letter("inventory") == "I"


# -- drawing ---------------------------------------------------------------------
def test_the_key_is_drawn_in_the_middle_with_its_word_under_it(qt_app):
    from PyQt5.QtGui import QImage, QPainter
    from game.ui import hud
    s = _new("mage")
    w, h = 640, 400
    kh.current(s, 0.0)
    img = QImage(w, h, QImage.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    hud.draw_key_hints(painter, s, w, h, now=1.5)
    painter.end()

    rect = hud.key_hint_rect(w, h)
    assert (rect.width(), rect.height()) == (128, 128)
    assert rect.center().x() == pytest.approx(w / 2) and rect.center().y() == pytest.approx(h / 2)
    # The keycap's slate fills the middle of the screen...
    centre = img.pixelColor(w // 2, h // 2)
    assert centre.alpha() == 255
    assert centre.blue() > centre.red() and 60 < centre.green() < 140
    # ...nothing far to the sides...
    assert img.pixelColor(20, h // 2).alpha() == 0
    # ...and the word sits under the key, centred.
    below = [(x, y) for y in range(int(rect.bottom()) + 2, min(h, int(rect.bottom()) + 50))
             for x in range(w) if img.pixelColor(x, y).alpha()]
    assert below
    xs = [x for x, _y in below]
    assert abs((min(xs) + max(xs)) / 2 - w / 2) < 6
    whites = [img.pixelColor(x, y) for x, y in below]
    assert any(c.red() > 240 and c.green() > 240 and c.blue() > 240 for c in whites)


def test_a_key_without_a_picture_is_drawn(qt_app):
    from game.ui import hud
    image = hud.key_hint_image("Q")
    assert image is not None and not image.isNull()
    assert hud.key_hint_image("I").width() == 256       # the committed picture
