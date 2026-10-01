"""
The quest editor's ⌖ buttons: jump to a quest's item (or place, NPC,
monster) in the editor's 2D views, 3D view or both, in a world far too big to
scroll around looking.

Run:  python -m pytest game/tests/test_quest_jump.py -q
"""

from __future__ import annotations

import configparser
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from .. import quest_editor as qe     # noqa: E402


class _Thing:
    def __init__(self, pos, **props):
        self.pos = list(pos)
        self.properties = dict(props)


def _world():
    tome = _Thing((25600, 790, -26400), type="spellbook", name="Ember_Tome",
                  quest_item="ember_tome")
    chest = _Thing((10, 0, 10), type="container", name="Chest",
                   inventory=[{"id": "iron_mace", "qty": 1}, {"id": "ember_tome"}])
    pickup = _Thing((50, 0, 50), type="itempickup", name="Pickup", item_id="iron_mace")
    cave = _Thing((900, 0, 900), type="marker", marker_kind="location",
                  name="cave_marker", place_name="Old Cave")
    bob = _Thing((5, 0, 5), type="npc", name="bob", display_name="Bob", npc_role="farmer")
    wolf = _Thing((70, 0, 70), type="creature", name="Wolf_1", creature_type="wolf")
    return [tome, chest, pickup, cave, bob, wolf]


def test_an_item_is_found_wherever_it_is_in_the_world():
    things = _world()
    names = [t.properties["name"] for t in qe.find_item_holders(things, "ember_tome")]
    assert names == ["Ember_Tome", "Chest"]          # the book that gives it, a chest
    names = [t.properties["name"] for t in qe.find_item_holders(things, "iron_mace")]
    assert names == ["Chest", "Pickup"]
    assert qe.find_item_holders(things, "nothing_like_it") == []


@pytest.mark.parametrize("kind, target, expected", [
    ("visit", "old cave", ["cave_marker"]),
    ("talk", "Bob", ["bob"]),
    ("talk", "farmer", ["bob"]),
    ("kill", "wolf", ["Wolf_1"]),
    ("roll", "1d20", []),
])
def test_every_kind_of_goal_points_somewhere(kind, target, expected):
    found = qe.find_quest_targets(_world(), kind, target)
    assert [t.properties["name"] for t in found] == expected


class _Editor:
    """The editor window, as a jump sees it."""

    def __init__(self, things):
        self.state = type("S", (), {"things": things})()
        self.config = configparser.ConfigParser()
        self.selected = None
        self.framed = []
        self.toasts = []
        self.saved = 0

    def set_selected_object(self, thing):
        self.selected = thing

    @staticmethod
    def _object_focus_target(thing):
        return list(thing.pos), 48.0

    def focus_on_bounds(self, centre, radius, views="both"):
        self.framed.append((tuple(centre), views))

    def show_toast(self, text, is_error=False):
        self.toasts.append((text, is_error))

    def save_config(self):
        self.saved += 1


def test_a_jump_selects_the_thing_and_moves_the_chosen_views():
    things = _world()
    editor = _Editor(things)
    assert qe.jump_views(editor) == "both"                  # the default
    qe.jump_to(editor, things[0], qe.jump_views(editor))
    assert editor.selected is things[0]
    assert editor.framed[-1] == ((25600, 790, -26400), "both")

    qe.set_jump_views(editor, "3d")
    assert qe.jump_views(editor) == "3d" and editor.saved == 1
    qe.jump_to(editor, things[3], qe.jump_views(editor))
    assert editor.framed[-1][1] == "3d"


# ------------------------------------------------------------------ the widget

@pytest.fixture
def classes(qt_app):
    pytest.importorskip("PyQt5.QtWidgets")
    built = qe._classes()
    if built is None:
        pytest.skip("Qt unavailable")
    return built


def test_the_stage_cards_button_steps_through_every_place_the_item_is(classes):
    things = _world()
    editor = _Editor(things)
    stage = {"index": 0, "objective": "Find the tome",
             "condition": {"kind": "fetch", "target": "ember_tome", "count": 1}}
    card = classes["StageCard"](stage, [])
    card.editor_getter = lambda: editor
    card._sync()
    assert card.jump.isEnabled()

    card.jump.jump()
    card.jump.jump()
    card.jump.jump()                                       # wraps round
    assert [c for c, _v in editor.framed] == [(25600, 790, -26400), (10, 0, 10),
                                              (25600, 790, -26400)]
    assert editor.toasts[0][0].startswith("ember_tome: 1 of 2")


def test_the_button_says_so_when_the_item_is_not_in_the_map(classes):
    editor = _Editor(_world())
    stage = {"index": 0, "condition": {"kind": "fetch", "target": "dragon_egg"}}
    card = classes["StageCard"](stage, [])
    card.editor_getter = lambda: editor
    card.jump.jump()
    assert editor.framed == []
    assert editor.toasts == [("dragon_egg: not in this map", True)]


def test_a_scripted_stage_has_nothing_to_jump_to(classes):
    card = classes["StageCard"]({"index": 0, "condition": {"kind": "none"}}, [])
    card._sync()
    assert not card.jump.isEnabled()
