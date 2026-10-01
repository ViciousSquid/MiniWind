"""
Character creation, trading and conversations take the mouse.

The menus are painted with QPainter, so they say where their buttons are while
they draw (:mod:`game.ui.hits`); the view shows the cursor while there is
anything to click and queues clicks, and the game tick carries them out. These
tests paint the real screens against a real session, click where the buttons
were drawn and run the tick's half, as play does.

Run:  python -m pytest game/tests/test_menu_clicks.py -q
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

QtCore = pytest.importorskip("PyQt5.QtCore")
QtGui = pytest.importorskip("PyQt5.QtGui")

from ..ui import hits, screens, dialogue_ui    # noqa: E402

W, H = 1280, 800


class _Player:
    def __init__(self):
        self.pos = [0.0, 0.0, 0.0]
        self.properties = {}


class _Logic:
    def __init__(self):
        self.things = []
        self.player = _Player()


class _Merchant:
    def __init__(self):
        self.pos = [10.0, 0.0, 0.0]
        self.properties = {"display_name": "Bryn", "merchant": True,
                           "npc_role": "merchant", "name": "bryn"}


@pytest.fixture
def session(qt_app):
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(), cfg={})
    hits.clear()
    yield s
    hits.clear()


def _paint(session):
    """One overlay frame: begin, draw the open screen, publish its targets."""
    pixmap = QtGui.QPixmap(W, H)
    painter = QtGui.QPainter(pixmap)
    hits.begin()
    try:
        if session.dialogue is not None:
            dialogue_ui.draw(painter, session, W, H)
        else:
            screens.draw(painter, session, W, H)
    finally:
        hits.end()
        painter.end()


def _click(session, label):
    """Click the centre of the target labelled *label*, then run the tick."""
    _paint(session)
    found = [rect for rect, lab in hits.targets() if lab == label]
    assert found, f"no {label!r} among {[lab for _, lab in hits.targets()]}"
    centre = found[-1].center()
    assert hits.click(centre.x(), centre.y())
    assert hits.run_clicks(session) == 1


def _labels(session):
    _paint(session)
    return [label for _, label in hits.targets()]


# ---------------------------------------------------------- character creation

def test_character_creation_can_be_done_with_the_mouse(session):
    session.open_screen = "charcreate"
    cc = screens._cc(session)
    for letter in "Ada":                                 # the name is typed
        screens.handle_key(session, letter.lower())

    head = cc["head"]
    _click(session, ">")
    assert cc["head"] == head + 1
    _click(session, "<")
    assert cc["head"] == head

    hand = cc["handed"]
    _click(session, next(lab for lab in _labels(session) if "handed" in str(lab)))
    assert cc["handed"] != hand

    _click(session, "Next")
    assert screens._CC_STEPS[cc["step"]] == "class"
    third_class = [lab for lab in _labels(session)
                   if lab not in ("Back", "Next", "Begin")][2]
    _click(session, third_class)
    assert cc["class"] == 2

    _click(session, "Back")
    assert screens._CC_STEPS[cc["step"]] == "identity"
    _click(session, "Next")
    _click(session, "Next")                              # class -> birthsign
    _click(session, "Next")                              # -> confirm
    assert screens._CC_STEPS[cc["step"]] == "confirm"
    _click(session, "Begin")
    assert not session.needs_char_creation
    assert session.game.character.name == "Ada"


def test_next_needs_a_name_first(session):
    session.open_screen = "charcreate"
    assert "Next" not in _labels(session)                # disabled: not clickable
    screens.handle_key(session, "b")
    assert "Next" in _labels(session)


# --------------------------------------------------------------------- trading

def test_trading_with_the_mouse(session):
    session.merchant_npc = _Merchant()
    session.open_screen = "trade"
    c = session.game.character
    c.gold = 1000
    stock = screens._merchant_stock(session.merchant_npc)
    second = stock[1]["id"]

    _click(session, f"buy:{second}")
    st = screens._sel(session)["trade"]
    assert (st["side"], st["row"]) == (0, 1)

    buy = next(lab for lab in _labels(session) if str(lab).startswith("Buy "))
    gold = c.gold
    _click(session, buy)
    assert c.gold < gold
    assert any(s.get("id") == second for s in c.inventory)

    _click(session, f"sell:{second}")
    assert st["side"] == 1
    sell = next(lab for lab in _labels(session) if str(lab).startswith("Sell "))
    _click(session, sell)
    assert not any(s.get("id") == second for s in c.inventory)

    _click(session, "Leave")
    assert session.open_screen is None


def test_buying_without_the_gold_is_not_offered(session):
    session.merchant_npc = _Merchant()
    session.open_screen = "trade"
    session.game.character.gold = 0
    assert not any(str(lab).startswith("Buy ") for lab in _labels(session))


# ------------------------------------------------------------- conversations

def test_a_reply_can_be_clicked(session):
    chosen = []
    session.dialogue = object()
    session.current_view = lambda: {"text": "Well met.", "responses": [
        {"text": "Hello."}, {"text": "Goodbye."}]}
    session.choose = chosen.append
    _click(session, "Goodbye.")
    assert chosen == [1]


# --------------------------------------------------------------- the pointer

class _View:
    def __init__(self, session):
        self.logic_thread = type("L", (), {"_miniwind": session})()
        self.updates = 0

    def update(self):
        self.updates += 1


def test_the_cursor_is_wanted_only_while_a_menu_has_targets(session):
    pointer = hits.GamePointer(_View(session))
    session.needs_char_creation = False
    session.open_screen = None
    hits.clear()
    assert not pointer.wants_pointer()               # free play: mouse-look
    session.open_screen = "charcreate"
    _paint(session)
    assert pointer.wants_pointer()
    session.open_screen = None
    assert not pointer.wants_pointer()


def test_a_click_off_every_target_is_ignored(session):
    session.open_screen = "charcreate"
    _paint(session)
    assert not hits.click(1, 1)
    assert hits.run_clicks(session) == 0


# ------------------------------------------------------------ trade motion

def test_a_bought_item_flies_across_and_its_new_row_waits_for_it(session, monkeypatch):
    import types
    from ..ui import trade_anim
    clock = [50.0]
    monkeypatch.setattr(trade_anim, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    trade_anim.reset()
    session.merchant_npc = _Merchant()
    session.open_screen = "trade"
    session.game.character.gold = 1000
    iid = screens._merchant_stock(session.merchant_npc)[0]["id"]

    _click(session, f"buy:{iid}")
    _click(session, next(lab for lab in _labels(session) if str(lab).startswith("Buy ")))
    assert trade_anim.active()
    # The sell-side row exists already (the item is owned) but is still empty:
    _paint(session)
    assert trade_anim.landing_hidden(1, iid)

    clock[0] += trade_anim.FLIGHT_SECONDS + 0.01
    assert not trade_anim.landing_hidden(1, iid)       # landed
    clock[0] += trade_anim.GOLD_SECONDS
    assert not trade_anim.active()


def test_selling_onto_a_row_the_merchant_already_lists_shows_both(session, monkeypatch):
    import types
    from ..ui import trade_anim
    clock = [80.0]
    monkeypatch.setattr(trade_anim, "time", types.SimpleNamespace(monotonic=lambda: clock[0]))
    trade_anim.reset()
    session.merchant_npc = _Merchant()
    session.open_screen = "trade"
    session.game.character.gold = 1000
    iid = screens._merchant_stock(session.merchant_npc)[0]["id"]
    _click(session, f"buy:{iid}")
    _click(session, next(lab for lab in _labels(session) if str(lab).startswith("Buy ")))
    clock[0] += 5
    _click(session, f"sell:{iid}")
    _click(session, next(lab for lab in _labels(session) if str(lab).startswith("Sell ")))
    assert trade_anim.active()
    assert not trade_anim.landing_hidden(0, iid)       # the stock row stays put


def test_no_paint_no_motion_but_the_trade_still_happens(session):
    from ..ui import trade_anim
    trade_anim.reset()
    session.merchant_npc = _Merchant()
    session.open_screen = "trade"
    session.game.character.gold = 1000
    gold = session.game.character.gold
    screens._handle_trade(session, "return")           # never painted
    assert session.game.character.gold < gold
    assert not any(True for _ in trade_anim._flights)
