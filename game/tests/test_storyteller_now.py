"""What the storyteller is doing: its activity feed, the shared report, the
console's ``storyteller report`` / ``watch``, and the live window."""

import copy
import random
from types import SimpleNamespace

import pytest

from .. import console
from .. import storyteller_report as report
from ..rpg.gametime import GameClock
from ..sim.storyteller import TUNING, Storyteller
from ..weather import Weather
from .test_storyteller import rising, setup


def session_for(story, hour=14.5, day=9):
    return SimpleNamespace(storyteller=story, clock=GameClock(hour=hour, day=day),
                           weather=Weather(random.Random(3)), weather_enabled=lambda: True)


# -- the activity feed ---------------------------------------------------------
def test_state_changes_are_noted_newest_first_and_survive_save_and_load():
    story, director, hooks, store = setup()
    rising(story)
    feed = story.activity
    assert feed[0]["kind"] == "state" and feed[0]["text"].startswith("CALM → RISING")
    assert feed[0]["time"] == TUNING["states"]["CALM"]["max_hours"]
    assert Storyteller(store, director, hooks).activity == feed
    story.reset()
    assert story.activity == []


def test_studio_drags_merge_into_one_activity_line_and_switch_is_noted():
    story, *_ = setup()
    for value in (27, 28, 29):
        story.edit_lever("CALM", ("population",), value, persist=False)
    edits = [e for e in story.activity if e["kind"] == "edit"]
    assert len(edits) == 1 and edits[0]["text"].endswith("to 29.")
    story.set_enabled(False)
    assert story.activity[0]["kind"] == "switch" and "off" in story.activity[0]["text"]


def test_activity_is_bounded_and_listeners_hear_each_entry():
    story, *_ = setup()
    heard = []
    story.listeners.append(heard.append)
    story.listeners.append(lambda entry: 1 / 0)      # a broken listener is ignored
    for i in range(TUNING["activity_cap"] + 5):
        story._note("edit", f"line {i}", i)
    assert len(story.activity) == TUNING["activity_cap"]
    assert story.activity[0]["text"] == f"line {TUNING['activity_cap'] + 4}"
    assert len(heard) == TUNING["activity_cap"] + 5


def test_summary_is_detached_and_reading_changes_nothing():
    story, _director, _hooks, store = setup()
    rising(story)
    before = copy.deepcopy(store.d), story.observations, story.activity
    summary = story.summary()
    summary["levers"]["population"] = -1
    summary["activity"].clear()
    report.rows(story, session_for(story))
    assert (store.d, story.observations, story.activity) == before
    assert story.levers["population"] != -1
    assert summary["state"] == "RISING" and summary["next"] == "PEAK"


# -- the report ----------------------------------------------------------------
def test_report_rows_cover_every_section_with_labels():
    story, *_ = setup()
    rising(story)
    rows = report.rows(story, session_for(story))
    labels = [label for label, _ in rows]
    for want in ("Time", "State", "Purpose", "Why", "Sensing", "Roads", "Weather", "Recent"):
        assert want in labels
    text = dict(rows)
    assert text["State"].startswith("RISING") and "→ next PEAK" in text["State"]
    assert "health" in text["Sensing"] and "population" in text["Roads"]
    assert "does not steer the weather" in text["Weather"]
    assert any("CALM → RISING" in t for label, t in rows if label.startswith("Day "))


def test_report_sections_and_pristine_mode():
    story, *_ = setup()
    assert [label for label, _ in report.rows(story, None, "weather")] == ["Weather"]
    with pytest.raises(ValueError):
        report.rows(story, None, "bogus")
    story.set_enabled(False)
    why = dict(report.rows(story, None, "why"))["Why"]
    assert why == report.PRISTINE
    assert "pacing OFF" in report.header(story)
    assert report.rows(None) == [("Storyteller", "No active MiniWind storyteller.")]


def test_stamp_formats_world_hours():
    assert report.stamp(None) == "-"
    assert report.stamp(9 * 24 + 14.5) == "Day 9 14:30"
    assert report.stamp(23.9999) == "Day 1 00:00"


# -- the console ---------------------------------------------------------------
def _ctx(story):
    session = session_for(story)
    return console.ConsoleContext(logic_thread=SimpleNamespace(_miniwind=session), play_mode=True)


def test_console_report_is_labelled_storyteller(monkeypatch):
    story, *_ = setup()
    rising(story)
    lines = []
    monkeypatch.setattr(console, "debug_log", lambda category, message: lines.append((category, message)))
    console.cmd_storyteller(_ctx(story), "report")
    assert lines and all(category == "Storyteller" for category, _ in lines)
    assert lines[0][1].startswith("═══ STORYTELLER ═══")
    assert any(message.startswith("State ") for _, message in lines)
    lines.clear()
    console.cmd_storyteller(_ctx(story), "report sensing")
    assert len(lines) == 1 and lines[0][1].startswith("Sensing")
    lines.clear()
    console.cmd_storyteller(_ctx(story), "report nonsense")
    assert lines[0][0] == "Error"


def test_console_watch_logs_activity_live_and_stops(monkeypatch):
    story, *_ = setup()
    lines = []
    monkeypatch.setattr(console, "debug_log", lambda category, message: lines.append((category, message)))
    ctx = _ctx(story)
    console.cmd_storyteller(ctx, "watch on")
    console.cmd_storyteller(ctx, "watch on")          # twice is still one listener
    assert len(story.listeners) == 1
    lines.clear()
    rising(story)
    assert any(c == "Storyteller" and "CALM → RISING" in m for c, m in lines)
    console.cmd_storyteller(ctx, "watch off")
    assert story.listeners == []
    lines.clear()
    story._note("edit", "after watch", 1.0)
    assert not lines


# -- the window ----------------------------------------------------------------
@pytest.mark.qt
def test_window_opens_once_paints_live_and_opens_studio(qt_app):
    from PyQt5.QtCore import QPoint
    from PyQt5.QtGui import QImage, QPainter

    from engine.floating_windows import WindowManager
    from ..ui.storyteller_now import TITLE, StorytellerNowWindow
    from ..ui.storyteller_window import StorytellerWindow

    story, _director, _hooks, store = setup()
    rising(story)
    for i in range(12):
        story.tick(TUNING["states"]["CALM"]["max_hours"] + i)

    class View:
        def __init__(self):
            self.logic_thread = SimpleNamespace(_miniwind=session_for(story))
            self.window_manager = WindowManager()

        def width(self):
            return 640

        def height(self):
            return 360

        def update(self):
            pass

    view = View()
    ctx = console.ConsoleContext(logic_thread=view.logic_thread, play_mode=True,
                                 main_window=SimpleNamespace(view_3d=view))
    console.cmd_storyteller(ctx, "")
    win = view.window_manager.windows[0]
    assert isinstance(win, StorytellerNowWindow) and win.title == TITLE
    console.cmd_storyteller(ctx, "")
    assert view.window_manager.windows == [win]
    before = copy.deepcopy(store.d)
    image = QImage(640, 360, QImage.Format_ARGB32)
    painter = QPainter(image)
    try:
        win.draw(painter)
    finally:
        painter.end()
    assert store.d == before
    assert win._full_rect().right() < 640 and win._full_rect().bottom() < 360
    rows = win.rows()
    assert any(heading and "Activity" in text for _l, text, heading in rows)
    assert any(label == "State" for label, _t, _h in rows)
    assert win._scroll_max > 0
    win.handle_wheel(SimpleNamespace(angleDelta=lambda: QPoint(0, -120)))
    assert win._scroll > 0
    rect, action = win._buttons[0]
    assert action == "studio"
    assert win.handle_body_click(rect.center().x(), rect.center().y())
    assert any(isinstance(w, StorytellerWindow) for w in view.window_manager.windows)
