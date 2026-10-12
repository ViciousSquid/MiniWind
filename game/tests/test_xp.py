"""
Experience points: earned by kills and quests, a second route to a level.

A creature's ``xp_value`` is awarded when the player kills it, and a quest's
``xp`` when it completes; each shows as "+N XP" floating over the player, the
way damage does. Experience fills a level track alongside major-skill
training: either track full lets the character level up.

Run:  python -m pytest game/tests/test_xp.py -q
"""

from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from ..rpg import quests
from ..rpg.character import SKILL_UPS_PER_LEVEL, Character, xp_to_next
from ..rpg.dialogue import DictStore
from ..rpg.game_state import GameState
from .fio_logic import FioLogic


def _character():
    return Character.create("T", "imperial", "warrior")


def test_experience_alone_earns_a_level():
    c = _character()
    assert not c.can_level_up
    c.add_xp(xp_to_next(1) - 1)
    assert not c.can_level_up
    c.add_xp(1)
    assert c.can_level_up
    c.level_up()
    assert c.level == 2 and c.xp == 0
    assert c.xp_needed == xp_to_next(2) == 2 * xp_to_next(1)


def test_skill_training_still_earns_a_level_and_keeps_the_experience():
    c = _character()
    c.add_xp(30)
    c.xp_progress = SKILL_UPS_PER_LEVEL
    assert c.can_level_up
    c.level_up()
    assert c.level == 2 and c.xp_progress == 0 and c.xp == 30


def test_experience_survives_a_save():
    c = _character()
    c.add_xp(42)
    assert Character.from_dict(c.to_dict()).xp == 42


def test_a_completed_quest_awards_its_experience_and_tells_listeners():
    quests.register(quests.Quest("xp_test", "XP Test",
                                 [quests.Stage(0, "Go.", objective="Go"),
                                  quests.Stage(10, "Done.", finishes=True)],
                                 xp=25))
    gs = GameState.new_game(DictStore(), "T", "imperial", "warrior",
                            rng=random.Random(1))
    heard = []
    gs.add_xp_listener(heard.append)
    gs.start_quest("xp_test")
    gs.complete_quest("xp_test")
    assert gs.character.xp == 25 and heard == [25]


# --- a kill ----------------------------------------------------------------
class _Thing:
    def __init__(self, xp):
        self.pos = [0.0, 0.0, 0.0]
        self.properties = {"type": "creature", "name": "Bandit_1",
                           "npc_role": "bandit", "xp_value": xp}


class _Logic(FioLogic):
    def __init__(self):
        self.things = []
        self.player = None


def _session():
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(), cfg={"start_hour": 12.0,
                                       "minutes_per_day": 999999.0})
    s.begin_new_character("T", "imperial", "warrior", "none", "male", head="head01")
    s.floaters = []
    return s


def test_a_kill_shows_plus_xp_over_the_player():
    s = _session()
    s._on_creature_killed(_Thing(14))
    assert s.game.character.xp == 14
    assert {"text": "+14 XP", "kind": "xp"}.items() <= s.floaters[-1].items()


def test_a_kill_worth_nothing_shows_no_xp():
    s = _session()
    s._on_creature_killed(_Thing(0))
    assert s.game.character.xp == 0
    assert not [f for f in s.floaters if f["kind"] == "xp"]
