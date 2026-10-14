"""Regression tests for mouse-look while the permanent inventory strip is visible."""

import pytest

pytest.importorskip("PyQt5", reason="QtGameView requires PyQt5")

from engine.qt_game_view import _window_wants_cursor


class _Window:
    def __init__(self, key, *, active=True, wants_cursor=True):
        self.key = key
        self.active = active
        self.wants_cursor = wants_cursor


class _Manager:
    def __init__(self, *windows):
        self.windows = list(windows)


class _View:
    play_mode = True
    console_overlay_active = False
    _actor_pick = None
    pause_menu = None
    play_menu = None

    def __init__(self, *windows):
        self.floating_windows = _Manager(*windows)


def test_inventory_strip_alone_keeps_mouse_look_captured():
    view = _View(_Window("strip"))
    assert not _window_wants_cursor(view)


def test_inventory_or_dialogue_window_releases_cursor():
    view = _View(_Window("strip"), _Window("screen:inventory"))
    assert _window_wants_cursor(view)


def test_other_cursor_owners_still_release_cursor():
    view = _View(_Window("dialogue"))
    assert _window_wants_cursor(view)


def test_inactive_windows_do_not_claim_the_cursor():
    view = _View(_Window("dialogue", active=False), _Window("strip"))
    assert not _window_wants_cursor(view)


def test_non_play_mode_never_releases_cursor_for_game_windows():
    view = _View(_Window("screen:inventory"))
    view.play_mode = False
    assert not _window_wants_cursor(view)


def test_console_suppresses_floating_window_cursor_claims():
    view = _View(_Window("screen:inventory"))
    view.console_overlay_active = True
    assert not _window_wants_cursor(view)
