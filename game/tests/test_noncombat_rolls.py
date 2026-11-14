"""Rolls outside a fight -- talking someone round, picking a lock, being
noticed while sneaking, searching for loot -- in the same roll box over the
roller as every combat roll (RULES.md §1), never a corner panel."""

from __future__ import annotations

import configparser
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5")

pytestmark = pytest.mark.qt

from .. import runtime
from .test_cast_controls import _Logic, _Thing


@pytest.fixture
def dice_shown():
    config = configparser.ConfigParser()
    config.read_dict({"GAME": {"visualise_dice_rolls": "True"}})
    previous = runtime._editor_config
    runtime.set_editor_config(config)
    yield config
    runtime.set_editor_config(previous)


def _session(*things):
    from ..runtime import MiniwindSession
    s = MiniwindSession(_Logic(things), cfg={})
    s.needs_char_creation = False
    s.open_screen = None
    return s


def _land(s):
    """Let the player's dice land and what waits on them be told."""
    s._tick_dice_animation(1.5)
    for entry in s.__dict__.get("_reveals") or []:
        entry_time, show = entry
        show()
    s._reveals = []


# ------------------------------------------------- shown over a conversation
def _layout(w=180, h=120):
    return {"w": w, "h": h}


def _own(label="Persuade Ann"):
    return {"result": {"label": label}, "side": "you"}


def test_roll_boxes_show_over_a_conversation_and_the_rolling_screens(qt_app):
    from ..ui import hud
    s = _session()
    assert hud.shows_roll_boxes(s)
    s.dialogue = object()
    assert hud.shows_roll_boxes(s)                       # persuading, charming
    s.dialogue = None
    for screen in ("trade", "container", "lockpicking"):
        s.open_screen = screen
        assert hud.shows_roll_boxes(s)
    for screen in ("inventory", "journal", "charcreate"):
        s.open_screen = screen
        assert not hud.shows_roll_boxes(s)
    s.open_screen = None
    s.game.character.health = 0
    assert s.game.character.is_dead and not hud.shows_roll_boxes(s)


def test_a_box_a_window_would_cover_moves_clear_of_it():
    """The conversation's window is drawn over the boxes: the player's own
    roll moves beside, above or below it, never under it."""
    from ..ui import hud
    window = (260, 180, 760, 340)
    anchored = [((640.0, 330.0), _own(), _layout(240, 110))]
    (group,) = hud._stack_roll_boxes(anchored, 1280, 720, avoid=[window])
    (x, y, _sp, _box, lay, pointer), = group
    wx, wy, ww, wh = window
    across = min(x + lay["w"], wx + ww) - max(x, wx)
    down = min(y + lay["h"], wy + wh) - max(y, wy)
    assert across <= lay["w"] * hud.ROLL_BOX_OVERLAP_OK or down <= lay["h"] * hud.ROLL_BOX_OVERLAP_OK
    assert pointer                                       # still pointing to the roller


def test_a_box_never_hides_a_toast():
    from ..ui import hud
    toast = (400, 40, 480, 90)
    anchored = [((640.0, 230.0), _own(), _layout(240, 110))]
    (group,) = hud._stack_roll_boxes(anchored, 1280, 720, avoid=[toast])
    (x, y, _sp, _box, lay, _pointer), = group
    assert y >= 40 + 90 or x >= 880 or x + lay["w"] <= 400


def test_without_a_window_the_box_stays_over_the_roller():
    from ..ui import hud
    anchored = [((640.0, 500.0), _own(), _layout(240, 110))]
    (group,) = hud._stack_roll_boxes(anchored, 1280, 720, avoid=[(0, 0, 100, 100)])
    (x, y, *_rest), = group
    assert x == 640 - 120 and y == int(500 - hud.ROLL_BOX_GAP_PX - 110)


def test_while_the_world_waits_a_roll_is_still_told_when_it_lands(qt_app):
    """A conversation pauses the world; what waits on a die is told all the
    same (tick_ui runs the reveals)."""
    s = _session()
    told = []
    s._after_dice(0.01, lambda: told.append(True))
    time.sleep(0.02)
    s.tick_ui(0.02)
    assert told == [True]


# ------------------------------------------------------------- persuasion
def test_persuade_is_a_d20_in_your_roll_box_naming_them_in_their_colour(qt_app, dice_shown):
    ann = _Thing("Ann", (60.0, 0.0, 40.0), type="npc")
    s = _session(ann)
    s._dialogue_action(ann, {"op": "persuade"})
    box = s.dice_animation
    roll = box["result"]
    assert roll["dice_notation"] == "1d20" and roll["target"] is not None
    assert roll["label"] == "Persuade Ann"
    assert box["actor"] is s.player_actor and box["side"] == "you"
    assert box["against"] == ("Ann", "ally")             # green: not a foe
    assert "Speechcraft" in roll["why"]
    assert s.roll_log[-1]["text"].startswith("Persuade Ann: ")


def test_persuasion_is_not_told_before_its_die_lands(qt_app, dice_shown):
    ann = _Thing("Ann", (60.0, 0.0, 40.0), type="npc")
    s = _session(ann)
    s._dialogue_action(ann, {"op": "persuade"})
    said = ("They warm to you.", "That didn't help.")
    assert not any(n["text"] in said for n in s.notifications)
    _land(s)
    won = s.dice_animation is None or s.dice_animation["result"]["success"]
    assert [n["text"] for n in s.notifications if n["text"] in said] == \
        [said[0] if won else said[1]]


def test_persuade_follows_the_dice(qt_app):
    from ..diceroll import DiceRoller
    from ..rpg import guilds
    from ..rpg.character import Character
    import random
    c = Character()
    for seed in range(30):
        props = {"name": "Ann"}
        r = guilds.persuade(c, props, dice=DiceRoller(rng=random.Random(seed)))
        assert r["success"] == r["roll"]["success"]
        assert props["disposition_offset"] == (8 if r["success"] else -4)


# ---------------------------------------------------------- Charm & Luck
def test_charm_and_luck_rolls_in_your_box_and_answers_when_it_lands(qt_app, dice_shown):
    from ..rpg import fortune
    merchant = _Thing("Mabel", (60.0, 0.0, 40.0), type="npc", merchant=True)
    s = _session(merchant)
    node = {"text": "...", "responses": []}
    s.dialogue = SimpleNamespace(tree={"nodes": {"_fortune": node}})
    s._fortune_action(merchant, "haggle")
    box = s.dice_animation
    assert box["result"]["label"] == "Charm & Luck: haggle with Mabel"
    assert box["against"] == ("Mabel", "ally")
    assert node["text"] == "..."                          # not before the die lands
    _land(s)
    _text, _difficulty, win, lose = fortune.OPTIONS["haggle"]
    assert node["text"] == (win if box["result"]["success"] else lose)


def test_the_box_names_what_charm_tries(qt_app):
    from ..ui import hud
    assert hud._box_action("Charm & Luck: haggle with Mabel", "Mabel") == "HAGGLE WITH"
    assert hud._box_action("Charm & Luck: charm a pardon from Bors", "Bors") == "CHARM A PARDON FROM"
    assert hud._box_action("Persuade Ann", "Ann") == "PERSUADE"


# ------------------------------------------------------------- a snapped pick
class _Die:
    """Dice that always land on *face*."""
    def __init__(self, face):
        self.face = face

    def randint(self, low, high):
        return max(low, min(high, self.face))

    def random(self):
        return 0.5


def _snapping(skill, face):
    from ..diceroll import DiceRoller
    from ..rpg import items, skills
    from .test_corpse_loot import _Thing as Box, _Logic as BoxLogic
    from .test_sim import _FakeGlobals
    from ..runtime import MiniwindSession
    chest = Box("Old lockbox", (40, 0, 0), type="container", locked=True,
                lock_difficulty="novice", owner="", inventory=[])
    s = MiniwindSession(BoxLogic([chest]), cfg={}, globals_store=_FakeGlobals())
    s.needs_char_creation = False
    s.game.character.skills[skills.SECURITY] = skill
    s.game.character.inventory = [items.make("lockpick", 3)]
    s.game.dice = DiceRoller(rng=_Die(face))
    s.game.add_roll_listener(s._on_dice_roll)
    s.open_container(chest)
    a = s.lockpick_attempt
    a.angle = 80 if a.target < 0 else -80
    a.strain, a.binding_time = .999, 1
    a.set_tension(True)
    s.tick_lockpicking(.1)
    return s, chest


@pytest.mark.parametrize("face, jammed", [(1, True), (20, False)])
def test_a_snapped_pick_is_a_save_in_your_roll_box(qt_app, dice_shown, face, jammed):
    from ..rpg.lockpicking import keep_chance
    from ..diceroll import check_target
    s, chest = _snapping(0, face)
    box = s.dice_animation
    roll = box["result"]
    assert roll["label"] == "Roll to save the snapped pick"
    assert roll["target"] == check_target(keep_chance(0))
    assert box["actor"] is s.player_actor and box["side"] == "you"
    assert bool(chest.properties.get("lock_jammed")) is jammed
    # Told once the die lands, not before.
    assert not any("pick" in n["text"].lower() for n in s.notifications)
    _land(s)
    assert any(("sheared" if jammed else "snapped") in n["text"] for n in s.notifications)


def test_a_practised_hand_rolls_nothing_when_a_pick_snaps(qt_app, dice_shown):
    s, chest = _snapping(15, 1)
    assert s.dice_animation is None and not chest.properties.get("lock_jammed")


def test_the_lock_window_shows_the_odds_the_die_rolls():
    from ..diceroll import CHECK_DIE, check_threshold
    from ..rpg.lockpicking import keep_chance, shear_chance, shear_risk
    assert shear_risk(15) == 0.0
    for security in range(15):
        faces_lost = CHECK_DIE - check_threshold(keep_chance(security))
        assert shear_risk(security) == pytest.approx(faces_lost / CHECK_DIE)
        assert abs(shear_risk(security) - shear_chance(security)) <= 0.05 + 1e-9


def test_beside_a_window_that_fills_the_middle_the_box_goes_narrow():
    """The lock window leaves only strips at the edges: the player's box
    takes its narrow, two-line form there instead of hiding under it."""
    from ..ui import hud
    lock = (230, 57, 820, 585)
    lay = {"w": 262, "h": 110, "visuals": [{}]}
    (group,) = hud._stack_roll_boxes([((640.0, 330.0), _own(), lay)], 1280, 720, avoid=[lock])
    (x, y, _sp, _box, placed, _pointer), = group
    assert placed["docked"] and placed["w"] == hud.ROLL_DOCK_W
    assert x + placed["w"] <= 230 or x >= 230 + 820
