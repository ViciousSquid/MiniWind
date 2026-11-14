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


def test_aldric_has_heard_if_the_news_got_there_first(chapter):
    """Aldric's first line changes if word of Hal Corbin's death reached him
    before the player did (he saw it, or someone told him)."""
    from ..sim import knowledge
    from ..sim.director import actor_key
    s, log = chapter, chapter.game.quests
    log.set_stage("mill_bandits", 50)
    aldric = entities.NPC(pos=[0, 0, 0], properties={"name": "Aldric", "display_name": "Aldric the Reeve"})
    tree = {"start": "greet", "nodes": {"greet": {"text": "Hello.", "responses": []}}}
    first = s._with_quest_lines(tree, aldric)
    assert first["nodes"][first["start"]]["text"].startswith("Corbin's book?")
    knowledge.learn(s.store, actor_key(aldric), {
        "e": 7, "kind": "death", "actor": "player", "target": "hal", "target_name": "Hal Corbin",
        "certainty": 0.8, "day": 1, "hour": 9.0})
    told = s._with_quest_lines(tree, aldric)
    assert told["nodes"][told["start"]]["text"].startswith("Word got here before you did")
