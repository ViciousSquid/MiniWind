"""Talking to a trainer or a tutor opens their page: a parchment training
sheet (trainer's rank, your skill, times trained this level) and a list of
spells for sale, each bought by clicking (game/ui/teaching.py)."""

from types import SimpleNamespace

import pytest

QtGui = pytest.importorskip("PyQt5.QtGui")
pytestmark = pytest.mark.qt

from game.rpg import skills as sk, training
from game.runtime import JOIN_CIRCLE_PROMPT, MiniwindSession, TRAIN_PROMPT, TUTOR_PROMPT
from game.ui import hits, screens
from .fio_logic import FioLogic


class _Logic(FioLogic):
    def __init__(self, things):
        self.things = list(things)
        self.player = SimpleNamespace(pos=[0.0, 0.0, 0.0], properties={})


class _Npc:
    def __init__(self, **props):
        self.pos = [40.0, 0.0, 0.0]
        self.properties = {"type": "npc", "display_name": "Morwen", "name": "morwen",
                           "aggression": "passive", **props}


TEACHER = dict(trainer={"skills": ["occult", "defensive"], "rank": "Journeyman"},
               teaches_spells=["sp_detect", "summon_wolf", "frostbite"], guild="mages")


@pytest.fixture
def session(qt_app):
    npc = _Npc(**TEACHER)
    s = MiniwindSession(_Logic([npc]), cfg={})
    s.logic._miniwind = s
    s.needs_char_creation = False
    s.open_screen = None
    c = s.game.character
    c.class_id = "necromancer"
    c.gold = 5000
    c.skills[sk.OCCULT] = 10
    hits.clear()
    yield s, npc
    hits.clear()


def _paint(s, width=760, height=600):
    image = QtGui.QImage(width + 80, height + 100, QtGui.QImage.Format_ARGB32)
    painter = QtGui.QPainter(image)
    hits.begin()
    try:
        screens.draw_in_rect(painter, s, 40, 50, width, height)
    finally:
        painter.end()
        hits.end()
    return hits.targets()


def _click(s, targets, label):
    rect = next(rect for rect, text in targets if text == label)
    assert screens.handle_click(s, rect.center().x(), rect.center().y())
    assert hits.run_clicks(s) == 1


def _say(s, prompt):
    view = s.dialogue.view()
    index = next(i for i, r in enumerate(view["responses"]) if r["text"] == prompt)
    s.choose(index)


def test_a_teacher_offers_training_spells_and_the_circle(session):
    s, npc = session
    assert s.start_dialogue(npc, None)
    texts = [r["text"] for r in s.dialogue.view()["responses"]]
    assert texts[:3] == [TRAIN_PROMPT, TUTOR_PROMPT, JOIN_CIRCLE_PROMPT]
    _say(s, JOIN_CIRCLE_PROMPT)
    from game.rpg import guilds
    assert guilds.is_member(s.game.character, "mages")
    s.start_dialogue(npc, None)
    assert JOIN_CIRCLE_PROMPT not in [r["text"] for r in s.dialogue.view()["responses"]]


def test_the_training_sheet_trains_with_a_click(session):
    s, npc = session
    s.start_dialogue(npc, None)
    _say(s, TRAIN_PROMPT)
    assert s.open_screen == "training" and s.trainer_npc is npc
    gold = s.game.character.gold
    _click(s, _paint(s), "Train")
    c = s.game.character
    assert c.skills[sk.OCCULT] == 11 and c.trained_this_level == 1 and c.gold < gold
    # The second tab trains the other skill.
    _click(s, _paint(s), "train:defensive")
    before = c.skills[sk.DEFENSIVE]
    _click(s, _paint(s), "Train")
    assert c.skills[sk.DEFENSIVE] == before + 1
    _click(s, _paint(s), "Leave")
    assert s.open_screen is None and s.trainer_npc is None


def test_out_of_sessions_the_train_button_is_gone(session):
    s, npc = session
    s.game.character.trained_this_level = training.SESSIONS_PER_LEVEL
    s.open_teaching(npc, "training")
    assert "Train" not in [label for _r, label in _paint(s)]


def test_the_tutor_sells_a_spell_with_a_click(session):
    s, npc = session
    s.start_dialogue(npc, None)
    _say(s, TUTOR_PROMPT)
    assert s.open_screen == "tutor"
    targets = _paint(s, 820)
    assert {"tutor:sp_detect", "tutor:summon_wolf", "tutor:frostbite"} <= \
        {label for _r, label in targets}
    learn = next(label for _r, label in targets if label.startswith("Learn"))
    _click(s, targets, learn)
    assert "sp_detect" in s.game.character.known_spells
    # A rare spell of the Circle needs membership: no Learn button.
    _click(s, _paint(s, 820), "tutor:summon_wolf")
    assert not any(label.startswith("Learn") for _r, label in _paint(s, 820))


def test_a_warrior_is_sent_away_from_magic(session):
    s, npc = session
    s.game.character.class_id = "warrior"
    assert not s.open_teaching(npc, "tutor")
    assert s.open_screen is None
    assert any("warrior" in n["text"] for n in s.notifications)
