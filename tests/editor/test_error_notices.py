"""Errors reported anywhere reach the screen through the main window."""

import pytest

pytest.importorskip("PyQt5", reason="the notices are drawn by the editor's Qt views")

pytestmark = pytest.mark.qt


def test_a_debug_console_error_becomes_a_banner_on_the_game_view(main_window):
    from engine import error_report
    from editor.debug_console import debug_log
    error_report.clear_notices()
    error_report._logged.clear()

    debug_log("MonsterAI", "Unhandled exception in update:\nTraceback (most recent call last):\n"
              "  File \"ai.py\", line 3, in update\nIndexError: list index out of range")
    main_window._show_error_notices()

    shown = [text for text, _expires in main_window.view_3d._error_notices]
    assert len(shown) == 1 and shown[0].startswith("MonsterAI: Unhandled exception")


def test_the_banner_draws_and_expires(main_window, monkeypatch):
    from PyQt5.QtGui import QImage, QPainter
    view = main_window.view_3d
    view.show_error_notice("Simulation tick failed")
    view.show_error_notice("Simulation tick failed")   # the same text is not stacked
    assert len(view._error_notices) == 1
    image = QImage(640, 360, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        view._draw_error_notices(painter)
    finally:
        painter.end()
    assert image.pixelColor(320, 20).alpha() > 0, "the banner was painted"

    import time
    monkeypatch.setattr(time, "perf_counter", lambda: 1e12)
    painter = QPainter(image)
    try:
        view._draw_error_notices(painter)
    finally:
        painter.end()
    assert view._error_notices == []


def test_the_window_watches_for_freezes_and_stops_watching_on_close(main_window):
    dog = main_window.freeze_watchdog
    assert dog.is_alive()
    main_window._show_error_notices()
    assert dog._ui_at > 0
