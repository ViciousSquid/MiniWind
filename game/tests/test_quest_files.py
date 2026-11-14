"""
Tests for external .quest file storage, the shared quest-offer dialogue helper,
and the runtime auto-wiring that makes a quest's giver actually offer it in play.

All headless: no Qt, no OpenGL.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from .. import entities
from ..rpg import quest_files
from ..rpg import quests
from .fio_logic import FioLogic


# --- .quest file storage ---------------------------------------------------
def _quest(qid="demo", giver="Bob"):
    return {
        "id": qid, "name": "Demo Quest", "giver": giver, "faction": "town",
        "desc": "Do the thing.", "xp": 10,
        "rewards": {"gold": 5, "items": [["potion_heal", 1]], "rep": ["town", 2]},
        "stages": [
            {"index": 0, "journal": "Start.", "objective": "Go",
             "finishes": False, "condition": {"kind": "talk", "target": giver, "count": 1}},
            {"index": 10, "journal": "Done.", "objective": "Report", "finishes": True},
        ],
    }


def test_quest_file_roundtrip(tmp_path):
    root = str(tmp_path)
    path = quest_files.save_quest_def(_quest("roundtrip"), root=root)
    assert path and path.endswith("roundtrip.quest")
    assert os.path.isfile(path)
    defs = quest_files.load_quest_defs(root=root)
    assert len(defs) == 1
    assert defs[0]["id"] == "roundtrip"
    assert defs[0]["rewards"]["gold"] == 5
    # The file is human-readable JSON.
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    assert '"id": "roundtrip"' in text


def test_load_skips_bad_files(tmp_path):
    root = str(tmp_path)
    quest_files.ensure_dir(root)
    # a valid quest, a non-JSON file and a JSON file missing an id
    quest_files.save_quest_def(_quest("good"), root=root)
    with open(os.path.join(quest_files.quests_dir(root), "bad.quest"), "w") as fh:
        fh.write("not json {{{")
    with open(os.path.join(quest_files.quests_dir(root), "noid.quest"), "w") as fh:
        fh.write('{"name": "nameless"}')
    defs = quest_files.load_quest_defs(root=root)
    assert [d["id"] for d in defs] == ["good"]


def test_sync_writes_new_and_deletes_removed(tmp_path):
    root = str(tmp_path)
    quest_files.sync_quest_files([_quest("a"), _quest("b")], root=root)
    ids = sorted(d["id"] for d in quest_files.load_quest_defs(root=root))
    assert ids == ["a", "b"]
    # Removing 'b' from the set deletes its file.
    quest_files.sync_quest_files([_quest("a")], root=root)
    assert not os.path.exists(quest_files.quest_path("b", root=root))
    ids = sorted(d["id"] for d in quest_files.load_quest_defs(root=root))
    assert ids == ["a"]


def test_project_root_contains_quests_folder():
    # The shipped quests/ folder resolves and holds the seeded .quest files.
    root = quest_files.project_root()
    assert os.path.isdir(quest_files.quests_dir(root))
    ids = {d["id"] for d in quest_files.load_quest_defs(root)}
    assert "lost_amulet" in ids


# --- shared offer-dialogue helper -----------------------------------------
def test_offer_dialogue_branch_builds_start_node_from_nothing():
    dlg, changed = quests.offer_dialogue_branch(None, "q1", "Quest One", "Help me.")
    assert changed
    assert dlg["start"] in dlg["nodes"]
    # An accept response somewhere starts the quest.
    actions = []
    for node in dlg["nodes"].values():
        for r in node.get("responses", []):
            actions.extend(r.get("actions", []))
    assert {"op": "start_quest", "quest": "q1"} in actions


def test_offer_dialogue_branch_is_idempotent():
    dlg = {"start": "greet", "nodes": {"greet": {"text": "Hi", "responses": []}}}
    dlg, changed1 = quests.offer_dialogue_branch(dlg, "q1", "Quest One")
    assert changed1
    n_responses = len(dlg["nodes"]["greet"]["responses"])
    dlg, changed2 = quests.offer_dialogue_branch(dlg, "q1", "Quest One")
    assert not changed2
    assert len(dlg["nodes"]["greet"]["responses"]) == n_responses  # no duplicate


def test_offer_dialogue_branch_preserves_existing_dialogue():
    dlg = {"start": "hello",
           "nodes": {"hello": {"text": "Welcome", "responses": [
               {"text": "Bye", "goto": "END"}]}}}
    dlg, changed = quests.offer_dialogue_branch(dlg, "q2", "Quest Two")
    assert changed
    # The original response is kept, and a new offer response is appended.
    texts = [r["text"] for r in dlg["nodes"]["hello"]["responses"]]
    assert "Bye" in texts
    assert any("Quest Two" in t for t in texts)


# --- runtime auto-wiring of givers ----------------------------------------
class _FakeLogic(FioLogic):
    def __init__(self, things):
        self.things = things
        self.player = None

    def _build_entity_caches(self):
        pass


class _G:
    """A minimal GlobalStore-like backing so StateStore actually persists."""
    def __init__(self):
        self.d = {}

    def get(self, k, default=None, store="plugins"):
        return self.d.get((store, k), default)

    def set(self, k, v, store="plugins"):
        self.d[(store, k)] = str(v)

    def all(self, store="plugins"):
        return {k[1]: v for k, v in self.d.items() if k[0] == store}


def _session(things):
    from ..runtime import MiniwindSession, StateStore
    s = MiniwindSession(_FakeLogic(things), cfg={})
    store = StateStore(_G(), "miniwind")
    s.store = store
    s.game.store = store
    return s


def test_wire_quest_givers_makes_named_giver_offer_quest():
    quests.register(quests.quest_from_dict(
        {"id": "wire_named", "name": "The Named Errand", "giver": "Aldric",
         "desc": "A task.", "stages": [{"index": 0, "journal": "Go"}]}))
    giver = entities.NPC(pos=[0, 0, 0], properties={"name": "Aldric"})
    bystander = entities.NPC(pos=[0, 0, 0], properties={"name": "Someone Else"})
    session = _session([giver, bystander])
    session._wire_quest_givers()

    # The giver can now be talked to and offers the quest.
    assert giver.properties.get("dialogue")
    qids = session._quest_ids_in_dialogue(giver.properties["dialogue"])
    assert "wire_named" in qids
    # A bystander is untouched.
    assert not session._quest_ids_in_dialogue(bystander.properties.get("dialogue") or {})


def test_wire_quest_givers_matches_role_and_is_talkable():
    quests.register(quests.quest_from_dict(
        {"id": "wire_role", "name": "Smithing Work", "giver": "blacksmith",
         "desc": "Forge it.", "stages": [{"index": 0, "journal": "Forge"}]}))
    smith = entities.NPC(pos=[10, 0, 10], properties={"name": "Thalen",
                                                      "npc_role": "blacksmith"})
    session = _session([smith])
    session._wire_quest_givers()
    # nearest_talkable finds the giver now that it has dialogue.
    assert session.nearest_talkable([10, 0, 10]) is smith
    assert "wire_role" in session._quest_ids_in_dialogue(smith.properties["dialogue"])


def test_wire_quest_givers_matches_by_entity_id():
    # Two NPCs share the name "Guard"; assigning the quest by entity id targets
    # exactly one of them.
    quests.register(quests.quest_from_dict(
        {"id": "wire_by_id", "name": "Id Assigned", "giver": "GUARD-UUID-2",
         "desc": "For the second guard.", "stages": [{"index": 0, "journal": "Go"}]}))
    guard1 = entities.NPC(pos=[0, 0, 0],
                          properties={"name": "Guard", "id": "guard-uuid-1"})
    guard2 = entities.NPC(pos=[0, 0, 0],
                          properties={"name": "Guard", "id": "guard-uuid-2"})
    session = _session([guard1, guard2])
    session._wire_quest_givers()
    assert "wire_by_id" in session._quest_ids_in_dialogue(guard2.properties["dialogue"])
    assert "wire_by_id" not in session._quest_ids_in_dialogue(
        guard1.properties.get("dialogue") or {})


def test_record_talk_records_entity_id():
    npc = entities.NPC(pos=[0, 0, 0], properties={"name": "Bob", "id": "bob-uuid-9"})
    session = _session([npc])
    session.record_talk(npc)
    # Both the name and the id are marked talked-to, so a talk objective keyed by
    # either completes.
    assert session.store.get("talked.bob", "") == "1"
    assert session.store.get("talked.bob_uuid_9", "") == "1"


def test_wire_quest_givers_shows_available_quest_bubble():
    quests.register(quests.quest_from_dict(
        {"id": "wire_bubble", "name": "A Bubble Quest", "giver": "Mara",
         "desc": "Bubble.", "stages": [{"index": 0, "journal": "Bubble"}]}))
    npc = entities.NPC(pos=[0, 0, 0], properties={"name": "Mara"})
    session = _session([npc])
    session._wire_quest_givers()
    # An un-started offered quest shows the '!' available-quest cue.
    assert session.bubble_kind(npc) == "quest"


# --- precedence: the files win over the built-ins, in a new game too -------
def test_a_new_character_keeps_the_quest_files_not_the_built_ins():
    """Making a character builds a new GameState, whose constructor loads the
    built-in quests. It used to register them again over the ``.quest`` files
    the session had already loaded, so every new game played the built-in Old
    Mill quest -- whose first stage never completes."""
    session = _session([])
    on_disk = {d["id"]: d for d in quest_files.load_quest_defs()}
    assert "mill_bandits" in on_disk
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    for qid, data in on_disk.items():
        running = quests.get(qid)
        assert running is not None, qid
        assert [s.index for s in running.stages] == [s["index"] for s in data["stages"]], qid
        assert [s.objective for s in running.stages] == \
            [s.get("objective", "") for s in data["stages"]], qid


def test_a_return_to_the_giver_stage_points_at_the_giver():
    """'Return to Aldric' has no condition (the giver's dialogue advances it),
    and used to have no arrow either -- with Aldric 12 km away."""
    quests.register(quests.quest_from_dict(
        {"id": "arrow_home", "name": "Arrow Home", "giver": "Aldric",
         "stages": [{"index": 0, "journal": "Go", "objective": "Go",
                     "condition": {"kind": "visit", "target": "Nowhere"}},
                    {"index": 10, "journal": "Back", "objective": "Return to Aldric"},
                    {"index": 20, "journal": "Paid", "finishes": True}]}))
    aldric = entities.NPC(pos=[9000, 0, 6000], properties={"name": "Aldric"})
    session = _session([aldric])
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    session.game.quests.start("arrow_home")
    session.game.quests.set_stage("arrow_home", 10)
    q = quests.get("arrow_home")
    assert session._objective_world_pos(q) == [9000, 0, 6000]
    session.game.quests.set_stage("arrow_home", 20)
    assert session._objective_world_pos(q) is None


def test_a_bandit_archer_counts_toward_killing_bandits():
    """'Kill 4 bandits at the mill': the camp's archers are bandits too. Only
    the plain 'bandit' role used to count, so an archer read SLAIN on screen
    and the objective stayed at 0/4."""
    session = _session([])
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    session.game.quests.start("mill_bandits")
    session.game.quests.set_stage("mill_bandits", 30)
    stage = quests.get("mill_bandits").stage(30)
    assert stage.condition_target() == "bandits"
    archer = entities.Creature(pos=[0, 0, 0], properties={"npc_role": "bandit_archer"})
    assert archer.properties["faction"] == "bandits"
    session.record_kill(archer)
    assert session.store.get("kills.bandits") in (1, "1")


# --- chapter one: the opening ------------------------------------------------
def _speak(session, npc):
    """The line *npc* opens a conversation with, and the talk recorded."""
    tree = session._with_quest_lines(npc.properties.get("dialogue") or
                                     {"start": "greet", "nodes": {"greet": {"text": "Hello.", "responses": []}}},
                                     npc)
    session.record_talk(npc)
    return tree["nodes"][tree["start"]]["text"]


def test_a_new_character_begins_with_elowen_and_the_flour():
    """Trouble at the Old Mill starts with a new game: talk to Elowen, who
    reads her own shelf, then Mara, who reads her windmill's stock."""
    elowen = entities.NPC(pos=[0, 0, 0], properties={"name": "Elowen", "display_name": "Elowen the Trader",
                                                      "inventory": [{"id": "flour", "qty": 2}]})
    mara = entities.NPC(pos=[10, 0, 0], properties={"name": "Mara"})
    session = _session([elowen, mara])
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    log = session.game.quests
    assert log.is_active("mill_bandits") and log.stage_of("mill_bandits") == 0
    assert log.current_objective("mill_bandits") == "Talk to Elowen"

    # Talking to Mara first does nothing for a stage that isn't hers yet.
    assert "hopper" not in _speak(session, mara)
    line = _speak(session, elowen)
    assert "2 sacks of flour on the shelf" in line
    session._tick_quests()
    assert log.stage_of("mill_bandits") == 10

    # Mara was spoken to before: this stage still wants a word now.
    session._tick_quests()
    assert log.stage_of("mill_bandits") == 10
    line = _speak(session, mara)
    assert "no wheat in the hopper" in line          # no windmill in this scene
    session._tick_quests()
    assert log.stage_of("mill_bandits") == 20
    assert log.current_objective("mill_bandits") == "Find the Old Mill"


def test_an_empty_shelf_is_said_plainly():
    elowen = entities.NPC(pos=[0, 0, 0], properties={"name": "Elowen"})
    session = _session([elowen])
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    assert "Today I've no flour on the shelf" in _speak(session, elowen)


def test_elowen_calls_out_and_the_chapter_has_a_card():
    import time
    elowen = entities.NPC(pos=[0, 0, 0], properties={"name": "Elowen"})
    session = _session([elowen])
    session._player_pos = lambda: [0.0, 0.0, 50.0]
    session.begin_new_character("Tamsin", "valian", "warrior", "warrior")
    queued = [text for _at, thing, text in session.__dict__.get("_bark_queue", [])
              if thing is elowen]
    assert queued == ["You! New face! Have you got a minute?"]
    q = quests.get("mill_bandits")
    assert (q.chapter, q.chapter_title) == (1, "The Old Mill")
    session._quest_completed(q)
    assert session.title_card["kicker"] == "Chapter One complete"
    assert session.title_card["title"] == "The Old Mill"
    assert session.title_card["t0"] <= time.monotonic()
