"""Console-driven floating inspector: live, complete, scrollable and read-only."""

from types import SimpleNamespace

import pytest
from engine.floating_windows import WindowManager
from ..console import ConsoleContext, cmd_storyteller
from ..living.journeys import KINDS
from ..ui.storyteller_window import StorytellerWindow, open_storyteller, rows_for
from .test_storyteller import rising, setup


pytestmark = pytest.mark.qt


class View:
    def __init__(self, story, width=1280, height=720):
        self.logic_thread = SimpleNamespace(_miniwind=SimpleNamespace(storyteller=story))
        self.window_manager = WindowManager()
        self.updates = 0
        self.size = width, height

    def width(self):
        return self.size[0]

    def height(self):
        return self.size[1]

    def update(self):
        self.updates += 1


@pytest.fixture(autouse=True)
def _close_windows(qt_app):
    yield
    from ..ui import storyteller_window
    for win in list(storyteller_window._open):
        win.close()


def test_command_opens_one_desktop_window_and_raises_it_on_repeat(qt_app):
    from ..ui import storyteller_window
    story, _director, _hooks, _store = setup()
    view = View(story)
    ctx = ConsoleContext(logic_thread=view.logic_thread, play_mode=True,
                         main_window=SimpleNamespace(view_3d=view))
    cmd_storyteller(ctx, "studio")
    win = storyteller_window._open[-1]
    assert isinstance(win, StorytellerWindow) and win.isWindow() and win.isVisible()
    assert win.windowTitle() == "Storyteller Studio"
    cmd_storyteller(ctx, "studio")
    assert [w for w in storyteller_window._open if w.view is view] == [win]
    win.close()
    assert open_storyteller(view) is not win


def test_all_effective_levers_and_ten_observations_are_live_and_read_only(qt_app):
    story, _director, hooks, store = setup()
    rising(story)
    for i in range(12):
        hooks.health = 0.8
        story.tick(9 + i)
    before = dict(store.d)
    observations = story.observations
    rows = rows_for(story)
    text = "\n".join(text for _kind, text in rows)
    assert f"State: {story.state}" in text
    assert all(f"{kind}: weight" in text for kind in KINDS)
    assert "Road population" in text and "Hunter bounty threshold" in text
    assert "New lair refill delay multiplier" in text and "Market trip chance" in text
    assert "Town destination multiplier" in text and "Vendetta arrival multiplier" in text
    assert text.count("health 80%") == 10
    assert all(o["reason"] in text for o in observations)
    assert [text.index(o["reason"]) for o in observations] == sorted(text.index(o["reason"]) for o in observations)
    assert store.d == before
    story.reset()
    text = "\n".join(text for _kind, text in rows_for(story))
    assert "State: CALM" in text and "No observations yet" in text
    assert f"trader: weight {KINDS['trader']['weight']}" in text  # inherited defaults are visible
    rising(story)
    assert "bandits: weight 6; departs 18:00–06:00 (overnight)" in "\n".join(t for _, t in rows_for(story))


def test_the_live_tab_shows_the_report_and_reading_changes_nothing(qt_app):
    story, _director, _hooks, store = setup()
    for i in range(12):
        story.tick(i)
    before = dict(store.d)
    win = open_storyteller(View(story))
    win.refresh(force=True)
    assert f"State: {story.state}" in win.live.toPlainText()
    assert win.live_state.text() == f"Live: {story.state}"
    assert store.d == before


def test_studio_keeps_its_contents_when_play_mode_ends_and_goes_live_again(qt_app):
    story, _director, _hooks, _store = setup()
    view = View(story)
    win = open_storyteller(view)
    win.tab = "Levers"                               # its table, built while live
    win.tab = "Live"
    win.refresh(force=True)
    shown = win.live.toPlainText()
    assert f"State: {story.state}" in shown
    view.logic_thread._miniwind = None               # Play Mode stops
    win.refresh(force=True)
    assert win.isVisible() and win.live.toPlainText() == shown
    assert win.live_state.text() == "Play Mode ended"
    win.tab = "World"                                # the other tab was kept too
    assert win.world.toPlainText()
    win.tab = "Levers"
    assert not win.form_area.widget().isEnabled()    # nothing to edit, still shown
    win.tab = "Live"
    assert open_storyteller(view) is None
    replacement = setup()[0]
    view.logic_thread._miniwind = SimpleNamespace(storyteller=replacement)
    assert open_storyteller(view) is win
    assert win._storyteller() is replacement


def test_studio_lever_boxes_edit_live_board_data_and_retain_edits(qt_app):
    from ..sim.storyteller import Storyteller
    from .test_storyteller import board

    story, director, hooks, store = setup()
    win = open_storyteller(View(story))
    win.tab = "Levers"
    win.choose_state("CALM")
    spin = win._spins[("population",)]
    value = spin.value()
    spin.setValue(value + 3)
    spin.editingFinished.emit()
    assert story.levers["population"] == value + 3
    assert board(story)._lever("population", 0) == value + 3
    assert Storyteller(store, director, hooks).levers == story.levers
    assert "Studio edit" in dict(story.inspector_rows())
    assert ("market_chance",) in win._spins and win._spins[("market_chance",)].maximum() == 1
    assert win._spins[("kind_hours", "bandits", 0)].maximum() == 24
    text = " ".join(w.text() for w in win.form_area.widget().findChildren(type(win.status)))
    assert "Drag a value" not in text                    # the long notes are gone
    win.reset_state()
    assert story.levers["population"] == value


def test_studio_switches_pacing_and_the_state_being_edited(qt_app):
    story, _director, _hooks, _store = setup()
    win = open_storyteller(View(story))
    win.tab = "Levers"
    win.choose_state("PEAK")
    assert win._state_buttons["PEAK"].isChecked() and not win._state_buttons["CALM"].isChecked()
    on = story.enabled
    win.pacing_button.click()
    assert story.enabled is (not on)


def test_studio_world_tab_and_causal_history_share_read_only_evidence(qt_app, monkeypatch):
    from .. import sim_editor
    from .test_storyteller import actor, remember

    story, director, hooks, store = setup()
    witness = actor(town="b")
    hooks.cast = [witness]
    ev, _fact = remember(store, director.bus, witness)
    rising(story)
    view = View(story)
    win = open_storyteller(view)
    win.tab = "World"
    before = dict(store.d), story.observations
    win.refresh(force=True)
    assert win.world.toPlainText()
    from PyQt5 import QtCore, QtWidgets
    window = sim_editor._WorldWindow(None, QtWidgets, QtCore)
    window._timer.stop()
    session = SimpleNamespace(storyteller=story)
    window._refresh_history(session, director)
    window._refresh_pacing(session)
    threads = next(window.pacing.topLevelItem(i) for i in range(window.pacing.topLevelItemCount())
                   if window.pacing.topLevelItem(i).text(0) == "Unreported threads")
    item = threads.child(0)
    assert "b" in item.text(0) and "theft" in item.text(1)
    assert item.data(0, QtCore.Qt.UserRole) == [ev.id]
    window.pacing.setCurrentItem(item)
    assert window.history.currentItem().data(0, QtCore.Qt.UserRole) == ev.id
    assert (store.d, story.observations) == before
    window.close()
