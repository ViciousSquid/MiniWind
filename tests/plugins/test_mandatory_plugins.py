"""Plugins this build cannot run without.

MiniWind is built on Big World, so ``bigworld`` is not an optional extra a map
opts into: it is part of the product. That promise has three halves, and each
one is a way it could quietly be broken:

  * it **loads**, whatever ``settings.ini`` or ``FIO_DISABLED_PLUGINS`` say;
  * it **starts enabled** and stays that way — no menu toggle, stale config,
    missing dependency or scene reset can switch it off;
  * if it is **missing**, the application refuses to start, with the message a
    user can act on rather than an exception from deep in a map load.

The mandatory list itself is the only thing faked here: the tests point
``MANDATORY_PLUGINS`` at a fixture plugin so the real manager runs its real
load/enable/refuse paths against a plugin the suite owns.
"""

import pytest

import plugins.manager as manager_module
from plugins.manager import (MANDATORY_PLUGINS, MandatoryPluginMissing,
                             PluginManager, is_mandatory_name)


@pytest.fixture
def mandatory(monkeypatch):
    """Declare *names* mandatory for the duration of one test."""
    def _set(*names):
        monkeypatch.setattr(manager_module, "MANDATORY_PLUGINS", tuple(names))
    return _set


# ---------------------------------------------------------------------------
# What this build declares
# ---------------------------------------------------------------------------

def test_bigworld_is_mandatory_for_this_build():
    assert "bigworld" in MANDATORY_PLUGINS, (
        "this build is built on Big World; the mandatory list is %s"
        % (MANDATORY_PLUGINS,))


def test_the_shipped_bigworld_plugin_ships_enabled():
    from plugins.bigworld.plugin import BigWorldPlugin
    assert BigWorldPlugin.enabled is True, (
        "bigworld must start enabled; it declares enabled=%r"
        % (BigWorldPlugin.enabled,))


def test_mandatory_names_are_matched_case_insensitively():
    assert is_mandatory_name("BigWorld") and is_mandatory_name("BIGWORLD")
    assert not is_mandatory_name("tidy")


# ---------------------------------------------------------------------------
# Always on
# ---------------------------------------------------------------------------

def test_a_mandatory_plugin_is_enabled_even_when_it_ships_disabled(
        mandatory, plugin_manager):
    mandatory("disabled_by_default")
    manager = plugin_manager("disabled_by_default")
    plugin = manager.find_plugin("disabled_by_default")
    assert manager.is_enabled(plugin), (
        "a mandatory plugin declaring enabled=False must be forced on at load")


def test_an_ordinary_plugin_still_honours_its_own_default(plugin_manager):
    manager = plugin_manager("disabled_by_default")
    plugin = manager.find_plugin("disabled_by_default")
    assert not manager.is_enabled(plugin), (
        "forcing mandatory plugins on must not switch on every plugin")


def test_a_mandatory_plugin_cannot_be_disabled(mandatory, plugin_manager):
    mandatory("well_behaved")
    manager = plugin_manager("well_behaved")
    plugin = manager.find_plugin("well_behaved")

    manager.set_enabled(plugin, False)

    assert manager.is_enabled(plugin), (
        "set_enabled(False) turned off a mandatory plugin; the Plugins menu "
        "toggle goes through this path")


def test_a_mandatory_plugin_survives_a_scene_reset(mandatory, plugin_manager):
    mandatory("well_behaved")
    manager = plugin_manager("well_behaved")
    plugin = manager.find_plugin("well_behaved")

    # File ▸ New reverts level-driven enables; a mandatory plugin is not one.
    manager._auto_enabled.add(plugin)
    reverted = manager.disable_auto_enabled()

    assert manager.is_enabled(plugin)
    assert plugin not in reverted, (
        "disable_auto_enabled() reported a plugin it did not actually disable")


def test_the_disable_env_var_is_ignored_for_a_mandatory_plugin(monkeypatch):
    monkeypatch.setenv("FIO_DISABLED_PLUGINS", "bigworld, tidy")
    manager = PluginManager()
    assert "bigworld" not in manager._disabled, (
        "FIO_DISABLED_PLUGINS must not be able to drop a mandatory plugin")
    assert "tidy" in manager._disabled, (
        "the env var must still work for ordinary plugins; disabled=%s"
        % (manager._disabled,))


def test_a_mandatory_plugin_is_not_disabled_by_a_missing_requirement(
        mandatory, plugin_manager):
    mandatory("well_behaved")
    manager = plugin_manager("well_behaved")
    plugin = manager.find_plugin("well_behaved")
    plugin.requires = ["nothing_like_this"]
    try:
        manager._verify_requirements()
        assert manager.is_enabled(plugin), (
            "a mandatory plugin must stay on even with an unmet 'requires'")
    finally:
        del plugin.requires


# ---------------------------------------------------------------------------
# Refusing to start
# ---------------------------------------------------------------------------

def test_a_missing_mandatory_plugin_is_reported(mandatory, plugin_manager):
    mandatory("bigworld")
    manager = plugin_manager("well_behaved")
    assert manager.missing_mandatory() == ["bigworld"]


def test_requiring_a_missing_mandatory_plugin_refuses_with_its_message(
        mandatory, plugin_manager):
    mandatory("bigworld")
    manager = plugin_manager("well_behaved")

    with pytest.raises(MandatoryPluginMissing) as caught:
        manager.require_mandatory_plugins()

    assert str(caught.value) == "Bigworld plugin is mandatory: could not be located", (
        "the startup refusal message changed; users and docs quote it verbatim")


def test_requiring_a_present_mandatory_plugin_passes(mandatory, plugin_manager):
    mandatory("well_behaved")
    manager = plugin_manager("well_behaved")
    assert manager.missing_mandatory() == []
    manager.require_mandatory_plugins()   # must not raise
