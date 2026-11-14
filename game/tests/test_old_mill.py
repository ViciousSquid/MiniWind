"""Chapter one at the Old Mill (quests/mill_bandits.quest): Hal Corbin holds
the mill; killing him, taking his ledger and bringing it to Aldric finishes
the chapter; the Cross's stolen tolls, if handed back, are worth more pay;
and the Cross buys from its own mill again when it works."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PyQt5")

from .. import entities
from ..rpg import inventory as inv, items, quests
from .test_quest_files import _session

pytestmark = pytest.mark.qt


@pytest.fixture
def chapter():
    quests.register(quests.quest_from_dict(json.load(open("quests/mill_bandits.quest"))))
    s = _session([])
    s.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    if not s.game.quests.is_active("mill_bandits"):
        s.game.quests.start("mill_bandits")
    return s


def test_hal_corbin_his_ledger_and_aldric(chapter):
    s, log = chapter, chapter.game.quests
    log.set_stage("mill_bandits", 30)
    hal = entities.Creature(pos=[0, 0, 0], properties={"name": "Hal Corbin",
                                                       "npc_role": "bandit_chief"})
    s.record_kill(hal)
    s._tick_quests()
    assert log.stage_of("mill_bandits") == 40          # take his ledger
    inv.add_item(s.game.character.inventory, items.make("corbin_ledger"))
    s._tick_quests()
    assert log.stage_of("mill_bandits") == 50          # to Aldric
    st = quests.get("mill_bandits").stage(50)
    assert st.condition_kind() == "talk" and st.condition_target() == "Aldric"
    assert "Mirrormere" in st.say and "Old Maud" in st.say


def _finish(s):
    log = s.game.quests
    log.set_stage("mill_bandits", 50)
    s.store.set("quest.mill_bandits.talked.50", "1")
    s._tick_quests()
    assert log.is_complete("mill_bandits")


def test_handing_back_the_tolls_pays_more(chapter):
    s = chapter
    inv.add_item(s.game.character.inventory, items.make("toll_purse"))
    before = s.game.character.gold
    _finish(s)
    assert s.game.character.gold - before == 150 + 40
    assert not inv.has_item(s.game.character.inventory, "toll_purse")


def test_keeping_the_tolls_is_the_players_choice(chapter):
    s = chapter
    before = s.game.character.gold
    _finish(s)
    assert s.game.character.gold - before == 150
