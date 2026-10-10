"""MiniWind's startup contract: the game and the plugins it is made of.

``main.py`` loads the game named by ``[Startup] game_module`` and refuses to
start when a plugin listed in ``[Plugins] mandatory`` is missing; a mandatory
plugin that is present is enabled whatever ``[Plugins] disabled`` says. These
pin that contract and the shipped settings.ini that relies on it.
"""

import configparser
import importlib.util
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _main_module():
    spec = importlib.util.spec_from_file_location("miniwind_main", os.path.join(ROOT, "main.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)          # the app itself runs under __main__ only
    return module


def _config(text):
    config = configparser.ConfigParser()
    config.read_string(text)
    return config


def test_the_shipped_settings_load_the_game_and_require_big_world():
    config = configparser.ConfigParser()
    config.read(os.path.join(ROOT, "settings.ini"))
    assert config.get("Startup", "game_module") == "game"
    assert "bigworld" in [n.strip() for n in config.get("Plugins", "mandatory").split(",")]


def test_a_present_mandatory_plugin_is_enabled():
    from plugins.manager import get_manager
    manager = get_manager()
    bigworld = manager.find_plugin("bigworld")
    manager.set_enabled(bigworld, False)
    assert _main_module()._missing_mandatory_plugins(
        _config("[Plugins]\nmandatory = bigworld\n")) == []
    assert manager.is_enabled(bigworld)


def test_a_missing_mandatory_plugin_is_reported_by_name():
    missing = _main_module()._missing_mandatory_plugins(
        _config("[Plugins]\nmandatory = bigworld, not_a_real_plugin\n"))
    assert missing == ["not_a_real_plugin"]


def test_no_mandatory_list_requires_nothing():
    assert _main_module()._missing_mandatory_plugins(_config("[Plugins]\n")) == []
