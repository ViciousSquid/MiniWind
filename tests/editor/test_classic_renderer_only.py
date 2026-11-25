"""Classic is the only renderer, and nothing offers another.

The HD_High renderer has been removed. A settings.ini written while it
existed may still say ``[Renderer] renderer = HD_High`` (or any other value):
it must start Classic, not fail. No dialog, menu or console listing offers
HD_High any more, and asking the view or the console for it leaves Classic
drawing.
"""

import configparser

import pytest

from engine.renderer import (
    CLASSIC, DEFAULT_RENDERER, available_renderers, canonical_name, is_classic,
    renderer_factory, renderer_from_settings)

# Qt tier: the dialog and editor tests need PyQt5 (offscreen; no GL).
pytestmark = pytest.mark.qt


def _asking_for(value):
    config = configparser.ConfigParser()
    config.add_section("Renderer")
    config.set("Renderer", "renderer", value)
    return config


@pytest.mark.parametrize("value", [
    "HD_High", "hd_high", "HD High", "hd-high", "HDHigh", "hd",
    "Classic", "classic", "Forward", "Ultra", "", "  "])
def test_any_renderer_setting_resolves_to_classic(value):
    assert renderer_from_settings(_asking_for(value)) == DEFAULT_RENDERER == "Forward"
    assert canonical_name(CLASSIC) == DEFAULT_RENDERER


def test_no_setting_at_all_is_classic_too():
    assert renderer_from_settings(None) == DEFAULT_RENDERER
    assert renderer_from_settings(configparser.ConfigParser()) == DEFAULT_RENDERER


def test_the_registry_holds_no_hd_high():
    assert "HD_High" not in available_renderers()
    assert renderer_factory("HD_High") is None
    assert not is_classic("HD_High")
    assert is_classic("Classic") and is_classic("forward")


def test_the_view_starts_classic_whatever_settings_ini_asks_for():
    from engine.qt_game_view import QtGameView
    for value in ("HD_High", "Classic", "nonsense"):
        assert QtGameView._configured_renderer(_asking_for(value)) == DEFAULT_RENDERER


def test_the_view_refuses_to_switch_away_from_classic():
    from engine.qt_game_view import QtGameView

    class View:
        renderer = object()
        _renderer_mode = DEFAULT_RENDERER

        def makeCurrent(self):  # a refusal must not even touch GL
            raise AssertionError("switch_renderer went on to make a renderer")

    view = View()
    for name in ("HD_High", "hd_high", "Stub"):
        assert QtGameView.switch_renderer(view, name) is False
        assert view._renderer_mode == DEFAULT_RENDERER


def test_r_renderer_lists_only_classic_and_refuses_hd_high(main_window, monkeypatch):
    import editor.console_commands as console
    lines = []
    monkeypatch.setattr(console, "debug_log", lambda level, text: lines.append(text))
    switched = []
    monkeypatch.setattr(main_window.view_3d, "switch_renderer",
                        lambda name: switched.append(name) or True)
    handler = main_window.console_handler

    handler.cmd_renderer("")
    assert CLASSIC in lines[-1] and "HD" not in lines[-1]
    handler.cmd_renderer("HD_High")
    assert switched == [] and "HD_High" in lines[-1] and CLASSIC in lines[-1]
    handler.cmd_renderer("classic")
    assert switched == [DEFAULT_RENDERER]


def _texts(widget):
    """Every piece of text the widget tree shows: labels, buttons, tooltips,
    actions and combo box items."""
    from PyQt5.QtWidgets import QAbstractButton, QAction, QComboBox, QLabel, QWidget
    texts = []
    for child in [widget] + widget.findChildren(QWidget):
        texts.append(child.toolTip())
        if isinstance(child, (QLabel, QAbstractButton)):
            texts.append(child.text())
        if isinstance(child, QComboBox):
            texts.extend(child.itemText(i) for i in range(child.count()))
    for action in widget.findChildren(QAction):
        texts.extend((action.text(), action.toolTip()))
    return texts


def _mentions_hd(texts):
    return [text for text in texts
            if "HD_High" in text or "HD High" in text or "HD preview" in text
            or "HD Readiness" in text or "HD Sky" in text]


def test_the_settings_dialog_offers_no_hd_high(qt_app):
    from editor.SettingsWindow import SettingsWindow
    dialog = SettingsWindow(_asking_for("HD_High"))
    try:
        assert not hasattr(dialog, "renderer_combo")
        assert _mentions_hd(_texts(dialog)) == []
    finally:
        dialog.deleteLater()


def test_saving_settings_puts_an_hd_high_file_back_on_classic(qt_app):
    from editor.SettingsWindow import SettingsWindow
    config = _asking_for("HD_High")
    dialog = SettingsWindow(config)
    try:
        dialog._save_settings()
    finally:
        dialog.deleteLater()
    assert config.get("Renderer", "renderer") == CLASSIC


def test_the_editor_window_offers_no_hd_high(main_window):
    for name in ("action_hd_preview", "hd_readiness_action", "set_hd_preview",
                 "hd_sky_properties_from_map", "canonicalize_hd_sky_ownership"):
        assert not hasattr(main_window, name), name
    assert _mentions_hd(_texts(main_window)) == []
    assert main_window.view_3d.switch_renderer("HD_High") is False

