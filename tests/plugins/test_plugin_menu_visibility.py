"""A disabled plugin's menu actions are hidden, not greyed out.

``_run_plugin_menu_action`` refuses to invoke a plugin-owned action whose
plugin is off, so a visible-but-dead entry is an offer the editor cannot
honour. Tidy's "Load Demo map" looked available with Tidy disabled and silently
did nothing when clicked.

MiniWind does not ship Tidy: the plugin with menu actions of its own here is
the ``menu_owner`` fixture (``tests/plugins/fixtures``), installed as the
process's plugin manager for the test.
"""

import pytest

pytest.importorskip("PyQt5", reason="the plugins menu is editor-tier")


from editor.ui import (_build_plugins_menu, _plugin_menu_name, _toggle_plugin) # noqa: E402
from plugins.manager import get_manager, load_plugins   # noqa: E402

pytestmark = pytest.mark.qt


def plugin_action_items(window, plugin):
    """The (label, visible, enabled) triples for one plugin's own actions."""
    for action in window.menuBar().actions():
        if action.text().replace("&", "") != "Plugins":
            continue
        for sub in action.menu().actions():
            if sub.text() != _plugin_menu_name(plugin) or sub.menu() is None:
                continue
            items = []
            for entry in sub.menu().actions():
                if entry.text() == "Enabled":
                    break          # plugin-owned actions all sit above this
                items.append((entry.text(), entry.isVisible(), entry.isEnabled()))
            return items
    return []


@pytest.fixture
def window(main_window):
    return main_window


@pytest.fixture
def menu_owner(plugin_manager, monkeypatch):
    """``(manager, plugin)``: a manager holding the ``menu_owner`` fixture
    plugin, standing in for the process's own while the test runs."""
    import plugins.manager as manager_module

    mgr = plugin_manager("menu_owner")
    monkeypatch.setattr(manager_module, "get_manager", lambda: mgr)
    return mgr, mgr.find_plugin("menu_owner")


def test_plugin_names_in_plugins_menu_start_with_a_capital(window):
    """The Plugins menu uses human-readable plugin labels, not raw module names."""
    load_plugins()
    _build_plugins_menu(window)

    for action in window.menuBar().actions():
        if action.text().replace("&", "") != "Plugins":
            continue
        labels = [
            sub.text()
            for sub in action.menu().actions()
            if sub.menu() is not None
        ]
        assert labels, "the Plugins menu contains no plugin submenus"
        assert all(label[:1].isupper() for label in labels), labels
        return

    pytest.fail("the Plugins menu was not created")


def test_a_disabled_plugins_actions_are_hidden(window, menu_owner):
    mgr, plugin = menu_owner
    was = mgr.is_enabled(plugin)
    try:
        mgr.set_enabled(plugin, False)
        _build_plugins_menu(window)
        items = plugin_action_items(window, plugin)
        assert items, "the plugin registered no menu actions; this test is looking in the wrong place"
        for label, visible, _enabled in items:
            assert not visible, (
                "'%s' is visible with the plugin disabled; clicking it does nothing"
                % label)
    finally:
        mgr.set_enabled(plugin, was)


def test_an_enabled_plugins_actions_are_shown(window, menu_owner):
    mgr, plugin = menu_owner
    was = mgr.is_enabled(plugin)
    try:
        mgr.set_enabled(plugin, True)
        _build_plugins_menu(window)
        items = plugin_action_items(window, plugin)
        assert any(label.startswith("Load Demo map") for label, _v, _e in items), (
            "the plugin's demo-map action is missing entirely: %r" % (items,))
        for label, visible, enabled in items:
            assert visible and enabled, (
                "'%s' is hidden or greyed with the plugin enabled" % label)
    finally:
        mgr.set_enabled(plugin, was)


def test_toggling_the_plugin_flips_its_actions_without_a_rebuild(window, menu_owner):
    """The Enabled checkbox updates the entries already on screen."""
    mgr, plugin = menu_owner
    was = mgr.is_enabled(plugin)
    try:
        mgr.set_enabled(plugin, True)
        _build_plugins_menu(window)
        before = plugin_action_items(window, plugin)
        assert all(v for _l, v, _e in before)

        _toggle_plugin(window, plugin, False,
                                   _live_actions(window, plugin))
        after = plugin_action_items(window, plugin)
        assert not any(v for _l, v, _e in after), (
            "toggling the plugin off left its actions on screen: %r" % (after,))
    finally:
        mgr.set_enabled(plugin, was)


def _live_actions(window, plugin):
    for action in window.menuBar().actions():
        if action.text().replace("&", "") != "Plugins":
            continue
        for sub in action.menu().actions():
            if sub.text() == _plugin_menu_name(plugin) and sub.menu() is not None:
                out = []
                for entry in sub.menu().actions():
                    if entry.text() == "Enabled":
                        break
                    out.append(entry)
                return out
    return []


def test_a_persisted_disable_really_stops_the_plugin(window, monkeypatch, menu_owner):
    """settings.ini's ``[Plugins] disabled`` must turn the plugin off for real.

    Building the menu used to write ``plugin.enabled = False`` directly. The
    manager caches the list of plugins it dispatches to, keyed on a generation
    that only ``set_enabled`` bumps, so a plugin that had already been
    dispatched to kept ticking with its menu toggle showing it off.
    """
    import configparser
    mgr, plugin = menu_owner
    assert mgr._overrides(plugin, "on_tick"), "fixture: the plugin should tick"
    ticks = []
    monkeypatch.setattr(plugin, "on_tick", lambda logic, ctx: ticks.append(1))
    was = mgr.is_enabled(plugin)
    logic = window.view_3d.logic_thread
    try:
        mgr.set_enabled(plugin, True)
        mgr.tick(logic)
        assert ticks == [1], "fixture: an enabled plugin should tick"

        window.config = configparser.ConfigParser()
        window.config["Plugins"] = {"disabled": "menu_owner"}
        _build_plugins_menu(window)

        assert not mgr.is_enabled(plugin)
        mgr.tick(logic)
        assert ticks == [1], "a plugin disabled in settings.ini still ticked"
    finally:
        mgr.set_enabled(plugin, was)


def _enabled_toggle(window, plugin):
    for action in window.menuBar().actions():
        if action.text().replace("&", "") != "Plugins":
            continue
        for sub in action.menu().actions():
            if sub.text() == _plugin_menu_name(plugin) and sub.menu() is not None:
                for entry in sub.menu().actions():
                    if entry.text() == "Enabled":
                        return action.menu(), entry
    return None, None


def test_the_toggle_shows_a_plugin_a_level_auto_enabled(window):
    """The menu is built at startup; a map loaded later auto-enables its
    plugin. Opening the menu must show that plugin as on -- it used to keep
    showing Big World unticked while its session ran."""
    load_plugins()
    mgr = get_manager()
    bigworld = mgr.find_plugin("bigworld")
    assert bigworld is not None, "MiniWind ships the Big World plugin"
    was = mgr.is_enabled(bigworld)
    try:
        mgr.set_enabled(bigworld, False)
        _build_plugins_menu(window)
        menu, toggle = _enabled_toggle(window, bigworld)
        assert toggle is not None and not toggle.isChecked()

        mgr.auto_enable_for_map(
            {"things": [{"type": "bigworldsettings", "properties": {}}]})
        assert mgr.is_enabled(bigworld)

        menu.aboutToShow.emit()
        assert toggle.isChecked(), "the menu still shows Big World as off"
        # Reflecting the state is not a manual toggle: the level still owns
        # the enable, so File > New can switch it back off.
        assert bigworld in mgr._auto_enabled
    finally:
        mgr.set_enabled(bigworld, was)


def _plugin_submenu(window, plugin):
    for action in window.menuBar().actions():
        if action.text().replace("&", "") != "Plugins":
            continue
        for sub in action.menu().actions():
            if sub.text() == _plugin_menu_name(plugin) and sub.menu() is not None:
                return sub.menu()
    return None


def test_add_entity_at_origin_places_the_entity(window, menu_owner):
    """The Plugins menu's "Add entity (at origin)" entries place an entity.

    The menu moved into editor.ui while its placement helper stayed behind in
    the deleted monkey-patch module, so every entry raised NameError on click.
    """
    mgr, plugin = menu_owner
    was = mgr.is_enabled(plugin)
    try:
        mgr.set_enabled(plugin, True)
        _build_plugins_menu(window)
        menu = _plugin_submenu(window, plugin)
        assert menu is not None, "the plugin has no Plugins submenu"
        entries = [a for a in menu.actions() if a.text() == "   Menu Owner Goal"]
        assert entries, "Menu Owner Goal is not offered under Add entity"
        before = len(window.state.things)
        entries[0].trigger()
        assert len(window.state.things) == before + 1
        placed = window.state.things[-1]
        assert placed.properties.get("type") == "menuownergoal"
        assert list(placed.pos) == [0.0, 40.0, 0.0]
    finally:
        mgr.set_enabled(plugin, was)
