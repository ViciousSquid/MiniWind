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


def test_game_settings_has_no_second_sky_image_property():
    from ..entities import GameSettings

    settings = GameSettings(properties={})
    assert "void_background" not in settings.properties
    editor_properties = getattr(GameSettings, "EDITOR_PRIMARY_PROPERTIES", None)
    if editor_properties is not None:
        assert "void_background" not in editor_properties


def test_legacy_game_settings_sky_value_is_retained_for_editor_migration():
    from ..entities import GameSettings

    path = "assets/backgrounds/space-panorama.jpg"
    settings = GameSettings(properties={"void_background": path})
    assert settings.properties["void_background"] == path
    editor_properties = getattr(GameSettings, "EDITOR_PRIMARY_PROPERTIES", None)
    if editor_properties is not None:
        assert "void_background" not in editor_properties


def test_play_session_does_not_own_a_second_sky_image_setting():
    from ..runtime import MiniwindSession
    from .test_ember_tome import _FakeLogic, _Globals

    session = MiniwindSession(
        _FakeLogic([], _FakePlayer([0, 0, 0])),
        cfg={"void_background": "assets/backgrounds/space-panorama.jpg"},
        globals_store=_Globals(),
    )
    assert not hasattr(session, "void_background")


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
