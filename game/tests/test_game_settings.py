"""Settings > Game: MiniWind's [GAME] options, edited and read live.

The play session reads ``[GAME] visualise_dice_rolls`` and
``[GAME] show_dialogue_heads`` from the editor's own config, which the editor
integration hands it as the 3D view is built; Settings has a Game tab that
loads and saves them with the rest of settings.ini.
"""

from __future__ import annotations

import configparser

import pytest

from .. import runtime
from .test_ember_tome import _FakePlayer, _session


@pytest.fixture
def config():
    config = configparser.ConfigParser()
    previous = runtime._editor_config
    runtime.set_editor_config(config)
    yield config
    runtime.set_editor_config(previous)


def _a_session():
    return _session([], _FakePlayer([0, 0, 0]))


def test_without_an_editor_the_defaults_apply():
    previous = runtime._editor_config
    runtime.set_editor_config(None)
    try:
        s = _a_session()
        assert s._visualise_dice_rolls_enabled() is False
        assert s.dialogue_heads_enabled() is True
    finally:
        runtime.set_editor_config(previous)


def test_the_session_reads_the_editors_settings_live(config):
    s = _a_session()
    assert s._visualise_dice_rolls_enabled() is False      # defaults
    assert s.dialogue_heads_enabled() is True
    config.read_dict({"GAME": {"visualise_dice_rolls": "True",
                               "show_dialogue_heads": "False"}})
    assert s._visualise_dice_rolls_enabled() is True
    assert s.dialogue_heads_enabled() is False


def test_a_roll_is_shown_only_when_dice_visuals_are_on(config):
    s = _a_session()
    s.game.request_roll("1d20", source="test")
    assert s.dice_animation is None
    config.read_dict({"GAME": {"visualise_dice_rolls": "True"}})
    s.game.request_roll("1d20", source="test")
    assert s.dice_animation is not None


@pytest.mark.qt
def test_settings_has_a_game_tab_that_loads_and_saves(qt_app):
    from .. import integration
    from editor.SettingsWindow import SettingsWindow
    integration._patch_settings_window()
    config = configparser.ConfigParser()
    config.read_dict({"GAME": {"visualise_dice_rolls": "True",
                               "show_dialogue_heads": "False"}})
    window = SettingsWindow(config)
    try:
        labels = [window.tabs.tabText(i) for i in range(window.tabs.count())]
        assert "Game" in labels
        boxes = window._miniwind_game_boxes
        assert boxes["visualise_dice_rolls"].isChecked()
        assert not boxes["show_dialogue_heads"].isChecked()
        boxes["visualise_dice_rolls"].setChecked(False)
        boxes["show_dialogue_heads"].setChecked(True)
        window._save_settings()
        assert config.getboolean("GAME", "visualise_dice_rolls") is False
        assert config.getboolean("GAME", "show_dialogue_heads") is True
    finally:
        window.deleteLater()
