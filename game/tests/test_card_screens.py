"""The spell tutor, the journal, the quest window, character creation, the
level-up page and the save slots show their choices as cards
(game/ui/cards.py). Each has a detail pane for the selected card, so the
cards carry no tooltip.

Run:  python -m pytest game/tests/test_card_screens.py -q
"""

from types import SimpleNamespace

import pytest

QtCore = pytest.importorskip("PyQt5.QtCore")
QtGui = pytest.importorskip("PyQt5.QtGui")
pytestmark = pytest.mark.qt

from game import host, keybinds
from game.rpg import quests as rq, skills as sk
from game.runtime import MiniwindSession
from game.ui import cards, hits, screens
from .fio_logic import FioLogic


class _Logic(FioLogic):
    def __init__(self, things=()):
        self.things = list(things)
        self.player = SimpleNamespace(pos=[0.0, 0.0, 0.0], properties={})


TUTOR = dict(type="npc", display_name="Morwen", name="morwen", aggression="passive",
             teaches_spells=["sp_detect", "summon_wolf", "frostbite", "flare",
                             "heal_minor", "sp_shield", "lightning", "sp_light"],
             guild="mages")


@pytest.fixture
def session(qt_app, monkeypatch):
    for _action, _label, constant, default in keybinds.ACTIONS:
        monkeypatch.setattr(host, constant, default)
    npc = SimpleNamespace(pos=[40.0, 0.0, 0.0], properties=dict(TUTOR))
    s = MiniwindSession(_Logic([npc]), cfg={})
    s.logic._miniwind = s
    s.needs_char_creation = False
    s.npc = npc
    c = s.game.character
    c.class_id = "necromancer"
    c.gold = 5000
    c.skills[sk.OCCULT] = 10
    monkeypatch.setattr(hits, "pointer", None)
    hits.clear()
    yield s
    hits.clear()


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
    return QtCore.QRect(*screens._panel_rect(w, h)) if full else QtCore.QRect(40, 50, w, h)


def _targets(prefix):
    return [(r, label) for r, label in hits.targets() if str(label).startswith(prefix)]


def _laid_out(rects, panel, portrait=True):
    assert rects
    for i, a in enumerate(rects):
        assert panel.contains(a), (a, panel)
        if portrait:
            assert a.height() > a.width()
        for b in rects[i + 1:]:
            assert not a.intersects(b)


@pytest.fixture
def drawn(monkeypatch):
    """Every card painted, with its rect; and no tooltip may be asked for."""
    out = []
    real = cards.draw_card
    monkeypatch.setattr(cards, "draw_card",
                        lambda p, r, card: out.append((QtCore.QRect(r), card))
                        or real(p, r, card))
    tips = []
    monkeypatch.setattr(cards, "draw_tooltip", lambda p, text, pos: tips.append(text))
    return SimpleNamespace(cards=out, tips=tips)


# ---------------------------------------------------------------------- tutor
def _tutor(session):
    session.trainer_npc = session.npc
    session.game.character.known_spells = ["flare", "heal_minor"]
    session.open_screen = "tutor"


@pytest.mark.parametrize("w,h,full", [(1280, 720, True), (1920, 1080, True),
                                      (820, 600, False)])
def test_tutor_cards_fit_without_overlap(session, w, h, full):
    _tutor(session)
    _paint(session, w, h, full)
    rects = [r for r, _l in _targets("tutor:")]
    assert len(rects) == len(TUTOR["teaches_spells"])
    _laid_out(rects, _panel(w, h, full))
    leave = next(r for r, label in hits.targets() if label == "Leave")
    assert all(not r.intersects(leave) for r in rects)


def test_tutor_cards_show_price_known_and_no_tooltip(session, drawn, monkeypatch):
    _tutor(session)
    _paint(session, 820, 600)
    by = {card.title: (r, card) for r, card in drawn.cards}
    flare = by["Flare"][1]
    assert flare.greyed and "known" in flare.badges
    frost = by["Frostbite"][1]
    assert not frost.greyed and any(b.endswith(" g") for b in frost.badges)
    assert frost.icon is not None
    # A click selects the card; Enter learns it. The detail pane says the rest.
    r = by["Frostbite"][0]
    monkeypatch.setattr(hits, "pointer", (r.center().x(), r.center().y()))
    assert screens.handle_click(session, r.center().x(), r.center().y())
    hits.run_clicks(session)
    _paint(session, 820, 600)
    assert not drawn.tips
    assert screens._sel(session)["tutor"]["row"] == 2
    screens.handle_key(session, "enter")
    assert "frostbite" in session.game.character.known_spells


def test_tutor_arrows_move_in_two_dimensions(session):
    _tutor(session)
    _paint(session, 820, 600)
    st = screens._sel(session)["tutor"]
    cols = st["cols"]
    assert cols >= 2
    st["row"] = 0
    screens.handle_key(session, "right")
    assert st["row"] == 1
    screens.handle_key(session, "down")
    assert st["row"] == 1 + cols
    screens.handle_key(session, "left")
    assert st["row"] == cols


# ------------------------------------------------------------ journal / quest
def _quests(session, n=7, done=3):
    ids = list(rq.QUESTS)[:n]
    log = session.game.quests
    for qid in ids:
        log.start(qid)
    for qid in ids[n - done:]:
        log.complete(qid)
    session.set_tracked_quest(ids[1])
    return ids


@pytest.mark.parametrize("screen,prefix", [("journal", "journal:"), ("quest", None)])
@pytest.mark.parametrize("w,h,full", [(1280, 720, True), (900, 540, False)])
def test_quest_cards_fit_without_overlap(session, screen, prefix, w, h, full):
    _quests(session)
    session.open_screen = screen
    _paint(session, w, h, full)
    rects = ([r for r, _l in _targets(prefix)] if prefix
             else [r for r, _i in screens._QUEST_HITS["rows"]])
    assert len(rects) >= 4
    _laid_out(rects, _panel(w, h, full))
    assert len({r.x() for r in rects}) >= 2                  # columns


def test_quest_cards_mark_tracked_and_completed(session, drawn):
    ids = _quests(session, n=5, done=2)
    session.open_screen = "journal"
    _paint(session, 1280, 720, True)
    by = {card.title: card for _r, card in drawn.cards}
    tracked = by[rq.get(ids[1]).name]
    assert tracked.active and tracked.mark == "▸" and not tracked.greyed
    assert tracked.summary == session.game.quests.current_objective(ids[1])
    done = by[rq.get(ids[-1]).name]
    assert done.greyed and done.glyph == "✓" and done.summary == "Completed"
    assert by[rq.get(ids[0]).name].glyph == "◈"
    assert all(not card.tooltip for card in by.values())


def test_quest_window_cards_are_click_targets_and_navigate(session):
    _quests(session)
    session.open_screen = "quest"
    _paint(session, 900, 540)
    st = screens._sel(session)["quest"]
    rect, idx = screens._QUEST_HITS["rows"][2]
    assert screens.handle_click(session, rect.center().x(), rect.center().y())
    assert st["row"] == idx == 2
    cols = st["cols"]
    st["row"] = 0
    screens.handle_key(session, "right")
    assert st["row"] == 1
    screens.handle_key(session, "down")
    assert st["row"] == 1 + cols
    # Enter still makes the highlighted (active) quest the tracked one.
    st["row"] = 0
    screens.handle_key(session, "enter")
    assert session.tracked_quest_id() == session.game.quests.active_quests()[0].id


def test_journal_cards_select_with_a_click(session):
    ids = _quests(session)
    session.open_screen = "journal"
    _paint(session, 900, 540)
    rect = next(r for r, label in _targets("journal:") if label == f"journal:{ids[2]}")
    assert hits.click(rect.center().x(), rect.center().y())
    hits.run_clicks(session)
    assert screens._sel(session)["journal"]["row"] == 2
    screens.handle_key(session, "left")
    assert screens._sel(session)["journal"]["row"] == 1


# --------------------------------------------------------- character creation
@pytest.mark.parametrize("step,field", [(2, "class"), (3, "birthsign")])
@pytest.mark.parametrize("w,h,full", [(1280, 720, True), (1920, 1080, True),
                                      (1000, 620, False)])
def test_creation_choices_are_cards(session, drawn, step, field, w, h, full):
    from game.rpg import classes, birthsigns
    ids = classes.CREATION_CLASS_IDS if field == "class" else birthsigns.CREATION_BIRTHSIGN_IDS
    label = (lambda i: classes.get(i).label) if field == "class" else \
        (lambda i: birthsigns.get(i).label)
    session.needs_char_creation = True
    session.open_screen = "charcreate"
    screens._cc(session).update(step=step, name="Ada")
    _paint(session, w, h, full)
    names = {label(i) for i in ids}
    rects = [r for r, lab in hits.targets() if lab in names]
    assert len(rects) == len(ids)                        # all on one page
    _laid_out(rects, _panel(w, h, full))
    back = next(r for r, lab in hits.targets() if lab == "Back")
    assert all(not r.intersects(back) for r in rects)
    shown = [card for _r, card in drawn.cards]
    assert all(card.icon is not None and card.summary and not card.tooltip
               for card in shown)
    # Arrows move by card and row; a click picks.
    cc = screens._cc(session)
    cc[field] = 0
    screens.handle_key(session, "right")
    assert cc[field] == 1
    screens.handle_key(session, "down")
    assert cc[field] == cards.navigate(1, "down", len(ids), cc[f"cols_{field}"]) != 1
    r = rects[-1]
    hits.click(r.center().x(), r.center().y())
    hits.run_clicks(session)
    assert cc[field] == len(ids) - 1


# ------------------------------------------------------------------- level up
@pytest.mark.parametrize("w,h,full", [(1280, 720, True), (1920, 1080, True),
                                      (820, 600, False)])
def test_level_up_choices_are_cards(session, drawn, w, h, full):
    c = session.game.character
    c.class_id = "mage"
    session.open_screen = "levelup"
    _paint(session, w, h, full)
    targets = _targets("levelup:")
    assert len(targets) == len(screens._level_rows(c)) == 4
    rects = [r for r, _l in targets]
    _laid_out(rects, _panel(w, h, full))
    assert len({r.y() for r in rects}) == 1                # one row
    confirm = next(r for r, lab in hits.targets() if str(lab).startswith("Increase "))
    assert all(not r.intersects(confirm) for r in rects)
    cards_ = [card for _r, card in drawn.cards]
    assert [card.title for card in cards_] == [r[1] for r in screens._level_rows(c)]
    assert all(card.icon is not None and card.badges[1] == "+5" and not card.tooltip
               for card in cards_)
    # Click the third card, then confirm with the button.
    r = next(r for r, lab in targets if lab == "levelup:charisma")
    hits.click(r.center().x(), r.center().y())
    hits.run_clicks(session)
    assert screens._levelup_state(session)["row"] == 2
    screens.handle_key(session, "right")
    assert screens._levelup_state(session)["row"] == 3
