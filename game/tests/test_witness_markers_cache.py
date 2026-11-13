"""The minimap's witness markers come from a cache kept current by what
changed (beliefs, deaths, reported flags), and always equal the markers
derived from scratch."""

from __future__ import annotations

from types import SimpleNamespace

from game.law import SettlementLaw
from game.runtime import MiniwindSession, SessionMemory, StateStore
from game.sim import crime, knowledge
from game.sim.director import PLAYER_KEY, actor_key


class _Law(SettlementLaw):
    player_key = PLAYER_KEY
    _is_guard = staticmethod(MiniwindSession._is_guard)

    def __init__(self, npcs):
        self.store = StateStore(SessionMemory())
        self.bucket = list(npcs)

    def _things_of_type(self, kind):
        return self.bucket if kind == "npc" else ()


def _npc(name, **props):
    props.setdefault("name", name)
    return SimpleNamespace(pos=[0.0, 0.0, 0.0], properties=props)


def _saw(law, npc, event_id, certainty=0.9, **extra):
    fact = dict(actor=PLAYER_KEY, kind="assault", crime=True, e=event_id,
                certainty=certainty, day=1, hour=8.0, **extra)
    knowledge._write(law.store, actor_key(npc), [fact])


def _fresh(law):
    saved, law._witness_cache = getattr(law, "_witness_cache", None), None
    try:
        return law.witness_markers()
    finally:
        law._witness_cache = saved


def test_markers_follow_beliefs_deaths_and_reports_and_match_a_fresh_derivation():
    ada, bo, guard = _npc("Ada"), _npc("Bo"), _npc("Watch", npc_role="guard")
    law = _Law([ada, bo, guard])
    assert law.witness_markers() == [] == _fresh(law)

    _saw(law, ada, 7)
    _saw(law, guard, 7)                       # a guard is never a messenger
    marks = law.witness_markers()
    assert [m["name"] for m in marks] == ["Ada"] and marks == _fresh(law)

    ada.pos = [500.0, 0.0, -20.0]             # positions are read every call
    assert (law.witness_markers()[0]["x"], law.witness_markers()[0]["z"]) == (500.0, -20.0)

    _saw(law, bo, 8, certainty=0.1)           # too unsure to report
    assert [m["name"] for m in law.witness_markers()] == ["Ada"]
    _saw(law, bo, 8, certainty=0.8, identified=False)
    marks = law.witness_markers()
    assert [(m["name"], m["state"]) for m in marks] == [("Ada", "identified"),
                                                       ("Bo", "uncertain")]
    assert marks == _fresh(law)

    crime.mark_reported(law.store, 7)         # someone else reported event 7
    assert [m["name"] for m in law.witness_markers()] == ["Bo"] == [
        m["name"] for m in _fresh(law)]

    bo.properties["dead"] = True
    assert law.witness_markers() == [] == _fresh(law)


def test_a_new_npc_set_rebuilds_the_roster():
    ada = _npc("Ada")
    law = _Law([ada])
    assert law.witness_markers() == []
    cy = _npc("Cy")
    _saw(law, cy, 3)
    law.bucket = [ada, cy]
    assert [m["name"] for m in law.witness_markers()] == ["Cy"]
