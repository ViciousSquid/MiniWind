"""The experimental tutorial after character creation (game/tutorial.py).

Off unless settings.ini has ``[developer] enable_tutorial``; then the last
step of character creation shows a "Show tutorial" checkbox (ticked), and
Begin opens four pages -- moving, the two hands, quick slots, the inventory
-- naming the keyboard and mouse or the gamepad, whichever was used last.
"""

from __future__ import annotations

import configparser

import pytest

from .. import controls, runtime, tutorial
from ..ui import screens
from .test_player_head import _actor, _session


def _config(text=""):
    config = configparser.ConfigParser()
    config.read_string(text)
    return config


@pytest.fixture
def keyboard():
    controls.use(controls.KEYBOARD)
    yield
    controls.use(controls.KEYBOARD)


@pytest.fixture
def dev(monkeypatch):
    monkeypatch.setattr(runtime, "_editor_config", _config("[developer]\nenable_tutorial = true\n"))


def test_off_unless_the_developer_setting_is_on():
    assert not tutorial.enabled(None)
    assert not tutorial.enabled(_config(""))
    assert not tutorial.enabled(_config("[developer]\nenable_tutorial = false\n"))
    assert not tutorial.enabled(_config("[GAME]\nenable_tutorial = true\n"))
    assert tutorial.enabled(_config("[developer]\nenable_tutorial = true\n"))
    assert tutorial.enabled(_config("[Developer]\nenable_tutorial = 1\n"))


def test_four_pages_cover_moving_hands_quick_slots_and_inventory(keyboard):
    titles = [t for t, _lines in tutorial.pages()]
    assert titles == ["Moving", "Your two hands", "Quick slots", "Inventory"]


def test_the_pages_follow_the_last_input(keyboard):
    keys = dict(tutorial.pages())
    assert any("W A S D" in line for line in keys["Moving"])
    assert any("Left button" in line and "Right button" in line for line in keys["Your two hands"])
    assert any("1 - 9" in line for line in keys["Quick slots"])
    controls.use(controls.GAMEPAD)
    pad = dict(tutorial.pages())
    assert any("Left stick" in line for line in pad["Moving"])
    assert any("LT" in line and "RT" in line for line in pad["Your two hands"])
    assert any("D-pad" in line for line in pad["Quick slots"])
    assert not any("W A S D" in line for line in sum(pad.values(), []))
    assert "B skip" in tutorial.hint(0, 4)
    controls.use(controls.KEYBOARD)
    assert "Esc skip" in tutorial.hint(0, 4)
    assert "finish" in tutorial.hint(3, 4)


def test_the_pages_name_the_players_own_bindings(keyboard, monkeypatch):
    import game.keybinds as keybinds
    monkeypatch.setattr(keybinds, "key_binding", lambda action: "g" if action == "attack" else "e")
    hands = dict(tutorial.pages())["Your two hands"]
    assert any(line.startswith("G:") for line in hands)


def _creating(sess):
    sess.open_screen = "charcreate"
    cc = screens._cc(sess)
    cc.update(name="Tamsin", step=len(screens._CC_STEPS) - 1, rolls=None)
    return cc


def test_without_the_setting_begin_goes_straight_to_play(monkeypatch, keyboard):
    monkeypatch.setattr(runtime, "_editor_config", _config(""))
    sess = _session([_actor("Villager")])
    _creating(sess)
    assert screens.handle_key(sess, "t")          # consumed, but no checkbox
    assert "tutorial" not in screens._cc(sess)
    screens.handle_key(sess, "return")
    assert sess.open_screen is None


def test_begin_opens_the_tutorial_when_ticked(dev, keyboard):
    sess = _session([_actor("Villager")])
    _creating(sess)
    screens.handle_key(sess, "return")
    assert sess.open_screen == "tutorial"
    for _ in range(3):
        screens.handle_key(sess, "return")
        assert sess.open_screen == "tutorial"
    screens.handle_key(sess, "left")
    assert screens._sel(sess)["tutorial"]["page"] == 2
    screens.handle_key(sess, "return")
    screens.handle_key(sess, "return")              # Finish on the last page
    assert sess.open_screen is None


def test_untick_and_begin_skips_it(dev, keyboard):
    sess = _session([_actor("Villager")])
    cc = _creating(sess)
    screens.handle_key(sess, "t")
    assert cc["tutorial"] is False
    screens.handle_key(sess, "return")
    assert sess.open_screen is None


def test_escape_or_the_pads_b_skips_it(dev, keyboard):
    sess = _session([_actor("Villager")])
    _creating(sess)
    screens.handle_key(sess, "return")
    assert sess.open_screen == "tutorial"
    screens.handle_key(sess, "escape")
    assert sess.open_screen is None


# -- tips ---------------------------------------------------------------------
_SEEN = [{"x": 0.0, "z": 0.0, "name": "Bram", "identified": True, "reporting": True}]


def _played(dev_sess, ticked=True):
    sess = dev_sess
    cc = _creating(sess)
    if not ticked:
        screens.handle_key(sess, "t")
    screens.handle_key(sess, "return")
    screens._close_tutorial(sess)                     # done with the pages
    assert cc is not None and sess.open_screen is None
    return sess


def test_the_first_crime_seen_shows_a_tip_once(dev, keyboard, monkeypatch):
    sess = _played(_session([_actor("Villager")]))
    seen = []
    monkeypatch.setattr(sess, "witness_markers", lambda: list(seen), raising=False)
    sess._check_tutorial_tips(1.0)
    assert sess.open_screen is None                   # nobody saw anything yet
    seen[:] = _SEEN
    sess._check_tutorial_tips(1.0)
    assert sess.open_screen == "tutorial_tip"
    title, text = tutorial.tip(screens._sel(sess)["tutorial_tip"])
    assert text == ("Someone saw the crime you just committed! ({eye} on the minimap) "
                    "- They are running to report to a guard...")
    screens.handle_key(sess, "return")
    assert sess.open_screen is None
    sess._check_tutorial_tips(1.0)
    assert sess.open_screen is None                   # first time only


def test_no_tip_if_the_tutorial_was_unticked(dev, keyboard, monkeypatch):
    sess = _played(_session([_actor("Villager")]), ticked=False)
    monkeypatch.setattr(sess, "witness_markers", lambda: list(_SEEN), raising=False)
    sess._check_tutorial_tips(1.0)
    assert sess.open_screen is None


def test_the_eye_is_drawn_inside_the_line(qt_app):
    """The tip names the minimap's eye by drawing it, not by the word."""
    from PyQt5.QtGui import QFontMetrics
    from ..ui import theme as T
    metrics = QFontMetrics(T.font(13, False, False, "Georgia"))
    lines = screens._rich_lines(metrics, tutorial.tip("witness")[1], 520)
    words = [w for line in lines for w in line]
    assert "({eye}" in words and not any("eye" in w.replace("{eye}", "") for w in words)
