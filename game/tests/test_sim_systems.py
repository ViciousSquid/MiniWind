"""The director owns the simulation's subsystems: the storyteller is one of them."""

from __future__ import annotations

import random

import pytest

from ..sim import SimSystem
from ..sim.director import Director, actor_key
from ..sim.storyteller import Storyteller, TUNING
from .test_sim import _Clock, _FakeGlobals, _FakeLogic, _Store, _Thing, _player
from .test_storyteller import rising


class Recorder(SimSystem):
    def __init__(self, name, log, director=None):
        self.name, self.log, self.director = name, log, director

    def reset(self):
        self.log.append((self.name, "reset", len(self.director.bus.recent(limit=100))))

    def tick(self, now):
        self.log.append((self.name, "tick", now, self.director.sim_time))

    def persist(self):
        self.log.append((self.name, "persist"))

    def restore(self):
        # The history is already loaded when a subsystem restores.
        self.log.append((self.name, "restore", len(self.director.bus.recent(limit=100))))
        return True


def _director(store=None, clock=None):
    return Director(store=store or _Store(), clock=clock or _Clock(), rng=random.Random(7))


def test_subsystems_tick_after_the_pipeline_on_absolute_world_time_in_attachment_order():
    d, log = _director(clock=_Clock(day=2, hour=0.0)), []
    first = d.attach(Recorder("first", log, d))
    d.attach(Recorder("second", log, d))
    assert d.system("first") is first and d.systems[0] is first
    d.tick([], 0.5)
    # Hour 0 is midnight, not the director's 12.0 fallback for a missing hour.
    assert log == [("first", "tick", 48.0, 0.5), ("second", "tick", 48.0, 0.5)]


def test_subsystem_names_are_unique_and_required():
    d = _director()
    d.attach(Recorder("pacing", [], d))
    with pytest.raises(ValueError):
        d.attach(Recorder("pacing", [], d))
    with pytest.raises(ValueError):
        d.attach(Recorder("", [], d))
    assert d.system("missing") is None


def test_lifecycle_fans_out_after_the_history():
    store, log = _Store(), []
    d = _director(store)
    d.attach(Recorder("pacing", log, d))
    d.emit("theft", actor="player", target="victim")
    d.persist()
    assert log == [("pacing", "persist")]

    loaded = _director(store)
    loaded.attach(Recorder("pacing", log, loaded))
    assert loaded.restore() == 1
    assert log[-1] == ("pacing", "restore", 1)

    loaded.reset()
    assert log[-1] == ("pacing", "reset", 0)
    assert loaded.bus.recent(limit=100) == []


def test_cached_intents_read_decisions_without_making_them(monkeypatch):
    d = _director()
    npc = _Thing("Guard")
    key = actor_key(npc)
    revision = d.knowledge_revision
    monkeypatch.setattr(d, "evaluate", lambda thing: pytest.fail("sampling appraised"))
    assert d.cached_intents(key) is None
    assert d.knowledge_revision == revision
    monkeypatch.undo()

    decided = d.intents(npc)
    assert d.cached_intents(key) == decided
    assert d.cached_intents(key) is not d._intents[key]     # a detached list
    d.invalidate(npc)
    assert d.cached_intents(key) is None


def test_the_storyteller_is_a_session_subsystem_ticked_by_the_simulation():
    from ..runtime import MiniwindSession

    session = MiniwindSession(_FakeLogic([], _player()), globals_store=_FakeGlobals())
    assert isinstance(session.storyteller, Storyteller)
    assert session.director.system("storyteller") is session.storyteller
    assert session.director.system("factions") is session.faction_spine
    assert session.storyteller.director is session.director

    session.clock.hour = (session.clock.hour + 0.5) % 24.0
    session._tick_sim(0.0)
    now = float(session.clock.day) * 24.0 + float(session.clock.hour)
    assert session.storyteller.last_sample == pytest.approx(now)
    assert session.storyteller.observations[0]["time"] == pytest.approx(now)


def test_a_new_game_resets_the_storyteller_with_the_world_history():
    from ..runtime import MiniwindSession

    session = MiniwindSession(_FakeLogic([], _player()), globals_store=_FakeGlobals())
    rising(session.storyteller)
    session.emit_event("theft", target="victim")
    assert session.director.bus.recent(limit=100)
    session.reset_progress()
    assert session.storyteller.state == "CALM"
    assert session.storyteller.levers == TUNING["states"]["CALM"]["levers"]
    assert session.director.bus.recent(limit=100) == []
