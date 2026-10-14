"""Regression tests for mouse-look while the permanent inventory strip owns the cursor."""

import pytest

pytest.importorskip("PyQt5", reason="QtGameView requires PyQt5")

from engine.qt_game_view import _window_cursor_claim_is_inventory_strip


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

    def __init__(self, *windows):
        self.floating_windows = _Manager(*windows)


def test_inventory_strip_alone_does_not_disable_mouse_look():
    view = _View(_Window("strip"))
    assert _window_cursor_claim_is_inventory_strip(view)


def test_a_menu_or_dialog_still_suspends_mouse_look():
    view = _View(_Window("strip"), _Window("screen:inventory"))
    assert not _window_cursor_claim_is_inventory_strip(view)


def test_other_cursor_owners_do_not_enable_mouse_look():
    view = _View(_Window("dialogue"))
    assert not _window_cursor_claim_is_inventory_strip(view)


def test_inactive_windows_do_not_claim_the_cursor():
    view = _View(_Window("dialogue", active=False), _Window("strip"))
    assert _window_cursor_claim_is_inventory_strip(view)


def test_no_cursor_claimant_does_not_take_this_path():
    view = _View(_Window("strip", wants_cursor=False))
    assert not _window_cursor_claim_is_inventory_strip(view)
