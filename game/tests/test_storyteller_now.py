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
def test_window_opens_once_as_a_desktop_window_reads_live_and_opens_studio(qt_app):
    from engine.floating_windows import WindowManager
    from ..ui import storyteller_now
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
    before = copy.deepcopy(store.d)
    console.cmd_storyteller(ctx, "")
    win = storyteller_now._open[-1]
    try:
        assert isinstance(win, StorytellerNowWindow) and win.windowTitle() == TITLE
        assert win.isWindow() and win.isVisible()          # a window of its own
        console.cmd_storyteller(ctx, "")
        assert [w for w in storyteller_now._open if w.view is view] == [win]
        win.refresh(force=True)
        assert store.d == before                           # reading changes nothing
        rows = win.rows()
        assert any(heading and "Activity" in text for _l, text, heading in rows)
        assert any(label == "State" for label, _t, _h in rows)
        assert "State" in win.story.toPlainText()
        win.tab = "Raw"
        assert win.raw.rowCount() > 0
        keys = [win.raw.item(i, 0).text() for i in range(win.raw.rowCount())]
        assert "state" in keys and any("summary()" in k for k in keys)
        from ..ui import storyteller_window
        win.studio_button.click()
        studio = [w for w in storyteller_window._open if w.view is view]
        assert studio and isinstance(studio[0], StorytellerWindow)
        studio[0].close()
    finally:
        win.close()
    assert win not in storyteller_now._open

@pytest.mark.qt
def test_both_windows_collapse_to_their_strip_and_pin_on_top(qt_app):
    from PyQt5.QtCore import Qt
    from engine.floating_windows import WindowManager
    from ..ui.storyteller_now import StorytellerNowWindow
    from ..ui.storyteller_window import StorytellerWindow

    story = setup()[0]
    view = SimpleNamespace(logic_thread=SimpleNamespace(_miniwind=session_for(story)),
                           window_manager=WindowManager(), update=lambda: None)
    for cls in (StorytellerNowWindow, StorytellerWindow):
        win = cls(view)
        win.resize(600, 500)
        win.show()
        qt_app.processEvents()
        try:
            strip = win.strip
            assert strip.arrow.text() == "▼"
            strip.arrow.click()
            qt_app.processEvents()
            assert not win.body.isVisible() and strip.isVisible()
            assert win.height() < 120 and strip.arrow.text() == "▶"
            strip.arrow.click()
            qt_app.processEvents()
            assert win.body.isVisible() and win.height() == 500
            assert not win.windowFlags() & Qt.WindowStaysOnTopHint
            strip.pin.click()
            assert win.windowFlags() & Qt.WindowStaysOnTopHint and win.isVisible()
            strip.pin.click()
            assert not win.windowFlags() & Qt.WindowStaysOnTopHint
        finally:
            win.close()


@pytest.mark.qt
def test_debug_menu_storyteller_runs_the_console_command(qt_app, monkeypatch):
    from PyQt5.QtWidgets import QAction, QMainWindow
    from .. import integration

    window = QMainWindow()
    window.debug_menu = window.menuBar().addMenu("Debug")
    window.position_action = QAction("Position", window)
    window.debug_menu.addAction(window.position_action)
    window.debug_menu.addAction(QAction("Project Overview", window))
    logic = SimpleNamespace(_miniwind=None)
    window.view_3d = SimpleNamespace(play_mode=True, logic_thread=logic)
    integration._add_debug_menu_entries(window)
    integration._add_debug_menu_entries(window)              # added once
    labels = [a.text() for a in window.debug_menu.actions()]
    assert labels == ["Position", "Project Overview", "Storyteller", "World Map"]   # alphabetical
    calls = []
    monkeypatch.setattr(console, "cmd_storyteller", lambda ctx, args: calls.append((ctx, args)))
    window.storyteller_action.trigger()
    ctx, args = calls[-1]
    assert args == "" and ctx.play_mode is True and ctx.logic_thread is logic
    assert ctx.main_window is window
    window.close()


@pytest.mark.qt
def test_the_window_stays_open_with_its_last_report_when_play_mode_ends(qt_app):
    from engine.floating_windows import WindowManager
    from ..ui.storyteller_now import StorytellerNowWindow

    story = setup()[0]
    logic = SimpleNamespace(_miniwind=session_for(story))
    view = SimpleNamespace(logic_thread=logic, window_manager=WindowManager(), update=lambda: None)
    win = StorytellerNowWindow(view)
    win.show()
    try:
        story_text = win.story.toPlainText()
        win.tab = "Raw"
        raw_rows = win.raw.rowCount()
        win.tab = "Story"
        assert "State" in story_text and raw_rows > 0
        logic._miniwind = None                       # Play Mode stops
        win.refresh()
        assert win.isVisible() and win.ended
        assert win.story.toPlainText() == story_text # nothing deleted
        assert "Play Mode ended" in win.title.text() and "last report" in win.note.text()
        win.tab = "Raw"                              # both tabs kept
        assert win.raw.rowCount() == raw_rows
        logic._miniwind = session_for(story)         # playing again
        win.refresh()
        assert not win.ended and "pacing" in win.title.text()
    finally:
        win.close()
