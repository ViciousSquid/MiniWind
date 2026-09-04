"""
Tests for external .quest file storage, the shared quest-offer dialogue helper,
and the runtime auto-wiring that makes a quest's giver actually offer it in play.

All headless: no Qt, no OpenGL.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game import entities
from game.rpg import quest_files
from game.rpg import quests


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
class _FakeLogic:
    def __init__(self, things):
        self.things = things
        self.player = None

    def _build_entity_caches(self):
        pass


def _session(things):
    from game.runtime import MiniwindSession
    return MiniwindSession(_FakeLogic(things), cfg={})


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


def test_wire_quest_givers_shows_available_quest_bubble():
    quests.register(quests.quest_from_dict(
        {"id": "wire_bubble", "name": "A Bubble Quest", "giver": "Mara",
         "desc": "Bubble.", "stages": [{"index": 0, "journal": "Bubble"}]}))
    npc = entities.NPC(pos=[0, 0, 0], properties={"name": "Mara"})
    session = _session([npc])
    session._wire_quest_givers()
    # An un-started offered quest shows the '!' available-quest cue.
    assert session.bubble_kind(npc) == "quest"
