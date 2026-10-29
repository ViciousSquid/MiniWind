"""Work counts for the simulation's hot paths, and batched == scalar.

Like tests/performance/test_hot_path_integrity.py these pin *how much work*
happens (parses, predicate calls, holders consulted), never wall-clock time,
and that every batched NumPy path decides exactly as the plain loop does.
"""

from __future__ import annotations

import copy
import json
import random
from types import SimpleNamespace

import pytest

from ..sim import director as director_mod, knowledge
from ..sim.director import Director, actor_key, peek_actor_key
from ..world_index import SCALAR_ROWS, WorldIndex
from .test_storyteller import Store, actor, rising, setup, vendetta


@pytest.fixture
def parses(monkeypatch):
    """Counts JSON parses of serialized beliefs."""
    calls = []
    real = json.loads

    def counted(raw, *args, **kwargs):
        calls.append(raw)
        return real(raw, *args, **kwargs)

    monkeypatch.setattr(knowledge.json, "loads", counted)
    return calls


def _belief(store, holder, eid=1, kind="theft", **extra):
    fact = dict(e=eid, kind=kind, actor="player", target="victim", certainty=0.9,
                identified=True, crime=True, day=0, hour=1.0, **extra)
    knowledge.learn(store, actor_key(holder), fact)
    return fact


def test_facts_view_parses_once_per_change_and_sees_every_write(parses):
    store, holder = Store(), actor("Holder")
    _belief(store, holder, 1)
    key = actor_key(holder)
    parses.clear()
    first = knowledge.facts_view(store, key)
    assert knowledge.facts_view(store, key) is first
    assert len(parses) == 1
    _belief(store, holder, 2)            # any write path invalidates the view
    assert [f["e"] for f in knowledge.facts_view(store, key)] == [1, 2]
    assert knowledge.facts_view(store, key) == knowledge.facts(store, key)
    assert knowledge.facts(store, key) is not knowledge.facts(store, key)   # still fresh copies


def test_derived_view_rebuilds_only_when_beliefs_change():
    store, holder = Store(), actor("Holder")
    _belief(store, holder, 1)
    key, builds = actor_key(holder), []

    def build(facts):
        builds.append(1)
        return [f["e"] for f in facts]

    assert knowledge.derived_view(store, key, build) == [1]
    assert knowledge.derived_view(store, key, build) == [1]
    _belief(store, holder, 2)
    assert knowledge.derived_view(store, key, build) == [1, 2]
    assert len(builds) == 2
    assert knowledge.derived_view(store, "nobody", build) == []


def test_peek_actor_key_matches_actor_key_without_writing_properties():
    for props in (dict(id="Bram_uuid"), dict(name="Old Bram"), dict(npc_role="guard"),
                  dict(_memory_identity="resident 7", id="proxy"), dict(is_player=True)):
        untouched = dict(props)
        thing = SimpleNamespace(properties=props)
        assert peek_actor_key(thing) == actor_key(SimpleNamespace(properties=dict(props)))
        assert props == untouched


def test_a_storyteller_sample_parses_unchanged_beliefs_at_most_once(parses):
    story, director, hooks, store = setup()
    for i in range(20):
        holder = actor(f"Holder {i}")
        hooks.cast.append(holder)
        _belief(store, holder, i + 1)
    story.tick(0)
    parses.clear()
    story.last_sample = None
    story.tick(1)
    assert parses == []                  # nothing changed: nothing re-parsed


def test_materialisation_weight_consults_only_the_journeys_own_members(monkeypatch):
    story, director, hooks, store = setup()
    kin, _intent = vendetta(story, director, hooks, store)
    hooks.cast.extend(actor(f"Bystander {i}") for i in range(200))
    rising(story)
    seen = []
    real = story._vendettas
    monkeypatch.setattr(story, "_vendettas", lambda holders: seen.append(set(holders)) or real(holders))
    story.materialisation_weight([actor_key(kin), "stranger"], 300)
    assert seen == [{actor_key(kin)}]


def _world(seed, n):
    rng = random.Random(seed)
    store = Store()
    d = Director(store=store, rng=random.Random(seed))
    cast = []
    for i in range(n):
        lawful = i % 3 == 0
        props = dict(id=f"a{i}", name=f"A{i}", type="npc",
                     faction="guards" if lawful else "villagers",
                     npc_role="guard" if lawful else "farmer",
                     sched_state=rng.choice(["", "", "SLEEPING"]))
        pos = None if i % 17 == 5 else [rng.uniform(-900, 900), 0, rng.uniform(-900, 900)]
        cast.append(SimpleNamespace(properties=props, pos=pos))
    for _ in range(30):
        ev = d.bus.make(rng.choice(["theft", "attack"]), actor="player",
                        target=f"a{rng.randrange(n)}", day=0, hour=1.0, data=dict(crime=True))
        for a in rng.sample(cast, 6):
            knowledge.learn(store, actor_key(a),
                            knowledge.fact_from_event(ev, rng.uniform(0.3, 1), "witnessed"))
    return d, store, cast


def _run(monkeypatch, vector_min, seed, n):
    monkeypatch.setattr(director_mod, "VECTOR_MIN", vector_min)
    d, store, cast = _world(seed, n)
    passes = [(d.spread_rumours(cast), d.resolve_reports(cast)) for _ in range(5)]
    return (passes, dict(store.d), d.rng.getstate(), sorted(d._dirty),
            [ev.to_dict() for ev in d.bus.history], [copy.deepcopy(c.properties) for c in cast])


@pytest.mark.parametrize("seed", range(4))
@pytest.mark.parametrize("n", [12, 90])
def test_batched_gossip_and_reports_decide_exactly_as_the_loop(monkeypatch, seed, n):
    scalar = _run(monkeypatch, 10 ** 9, seed, n)
    batched = _run(monkeypatch, 1, seed, n)
    assert batched == scalar
    assert scalar[0][0][0] > 0           # the worlds really gossip and charge
    assert any(charges for _, charges in scalar[0])


def _index_cast(n):
    rng = random.Random(4)
    return [SimpleNamespace(properties=dict(id=f"c{i}", _sim_tier=i % 3),
                            pos=[rng.uniform(-6000, 6000), 0, rng.uniform(-6000, 6000)])
            for i in range(n)]


@pytest.mark.parametrize("n", [SCALAR_ROWS // 2, SCALAR_ROWS * 8])
def test_counts_by_tier_near_matches_the_full_scan_and_skips_far_rows(n):
    index = WorldIndex()
    index.rebuild(_index_cast(n))
    asked = []

    def in_sight(a):
        asked.append(a)
        return a.pos[0] ** 2 + a.pos[2] ** 2 <= 1800.0 ** 2

    full = index.counts_by_tier(predicate=in_sight)
    asked.clear()
    near = index.counts_by_tier(predicate=in_sight, near=(0.0, 0.0, 1800.0 + 512.0))
    assert near == full
    if n >= SCALAR_ROWS:
        assert len(asked) < n // 2
