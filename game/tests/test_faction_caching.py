"""Work-count pins for board-scoped projections and dirty intent invalidation."""

import copy
from collections import Counter

import pytest

from .. import footprint
from ..sim import appraisal, factions, knowledge, moods
from ..sim.director import Director
from .test_faction_spine import actor, fact, identity, world


@pytest.mark.perf
def test_resident_queries_share_one_faction_ledger_and_one_mood_per_actor_per_board_update(monkeypatch):
    s, living, spine, cast = world(20)
    counts = Counter()
    read, account, feeling, traffic = knowledge.facts, factions.ledger, moods.evaluate, footprint.market_traffic
    def facts(store, key):
        counts['facts', key] += 1
        return read(store, key)
    def ledger(*args):
        counts['ledger'] += 1
        return account(*args)
    def mood(*args):
        counts['mood'] += 1
        return feeling(*args)
    def markets(*args):
        counts['traffic'] += 1
        return traffic(*args)
    monkeypatch.setattr(knowledge, 'facts', facts)
    monkeypatch.setattr(factions, 'ledger', ledger)
    monkeypatch.setattr(moods, 'evaluate', mood)
    monkeypatch.setattr(footprint, 'market_traffic', markets)
    for _ in range(4):
        for resident in cast:
            assert living.board.hooks.resident_can_leave(resident.properties['id'])
            s.director.evaluate(resident)
    assert counts['ledger'] == 1
    assert counts['mood'] == len(cast)
    assert counts['traffic'] == 1
    assert all(counts['facts', identity(a)] == 1 for a in cast)
    assert counts['facts', next(iter(spine.entities))] == 1
    # Next board update samples world conditions again, rather than retaining
    # stale prosperity or repeatedly recomputing inside this update.
    spine.begin_tick()
    for resident in cast:
        living.board.hooks.resident_can_leave(resident.properties['id'])
    assert counts['ledger'] == 2 and counts['traffic'] == 2
    assert counts['mood'] == 2 * len(cast)
    assert all(counts['facts', identity(a)] == 2 for a in cast)


def test_mood_provider_does_not_disable_ordinary_intent_cache(monkeypatch):
    s, _living, spine, cast = world()
    calls = []
    evaluate = s.director.evaluate
    def counted(actor):
        calls.append(identity(actor))
        return evaluate(actor)
    monkeypatch.setattr(s.director, 'evaluate', counted)
    first = s.director.intents(cast[0])
    for _ in range(5):
        assert s.director.intents(cast[0]) is first
    assert len(calls) == 1
    s.director.intents(cast[0], refresh=True)
    assert len(calls) == 2
    s.director.invalidate(cast[0])
    s.director.intents(cast[0])
    assert len(calls) == 3
    spine.begin_tick()
    current = s.director.intents(cast[0])
    assert s.director.intents(cast[0]) is current and len(calls) == 4


def test_plain_mood_callable_keeps_original_dirty_cache_contract():
    d = Director()
    resident = actor('Resident')
    calls = []
    d.mood_context = lambda *_args: calls.append(True) or None
    first = d.intents(resident)
    assert d.intents(resident) is first and calls == [True]
    d.invalidate(resident)
    d.intents(resident)
    assert calls == [True, True]


def test_dirty_member_changes_cached_mood_and_intent_before_next_board_tick():
    s, _living, spine, cast = world()
    member, observer = cast
    # An observer at the stand/flee boundary remembers identified enemy
    # violence. Another member learning about a crime changes faction morale.
    observer.properties['courage'] = 0.55
    threat = fact(1, 'attack', actor_faction='bandits', crime=False)
    knowledge.learn(s.store, identity(observer), threat)
    s.director.invalidate(observer)
    initial = s.director.intents(observer)
    assert initial[0].reaction == appraisal.FLEE
    before_tick = spine._cache_tick
    knowledge.learn(s.store, identity(member), fact(2))
    s.director.invalidate(member)
    # Even if the changed actor's ordinary decision consumes the dirty flag,
    # the faction's new knowledge must invalidate other residents' moods.
    s.director.intents(member)
    assert identity(member) not in s.director._dirty
    assert spine.goodwill('villagers', 'player') == -40
    changed = s.director.intents(observer)
    assert changed[0].reaction == appraisal.FIGHT and changed is not initial
    assert spine._cache_tick == before_tick
    knowledge.forget_all(s.store, identity(member))
    s.director.invalidate(member)
    assert spine.goodwill('villagers', 'player') == 0
    assert s.director.intents(observer)[0].reaction == appraisal.FLEE


def test_repeated_dirty_adds_invalidate_even_when_the_flag_was_already_set():
    s, _living, spine, cast = world()
    key = identity(cast[0])
    knowledge.learn(s.store, key, fact())
    s.director._dirty.add(key)
    assert spine.goodwill('villagers', 'player') == -40
    first = s.director.knowledge_revision
    knowledge.learn(s.store, key, fact(2, 'heal', crime=False))
    s.director._dirty.add(key)
    assert s.director.knowledge_revision > first
    assert spine.goodwill('villagers', 'player') == -28
    assert key in s.director._dirty  # sampling cannot consume an actor's dirty flag


def test_dirty_projections_remain_read_only_and_detached(monkeypatch):
    s, living, spine, cast = world()
    knowledge.learn(s.store, identity(cast[0]), fact())
    s.director.invalidate(cast[0])
    before = copy.deepcopy((s.store.d, s.director._intents, s.director._intent_context,
                            s.director._dirty, s.director.knowledge_revision, spine.snapshot(),
                            [a.properties for a in cast]))
    rng = living.board.rng.getstate()
    def forbidden(*_args, **_kwargs):
        pytest.fail('A projection authored state')
    monkeypatch.setattr(s.director, 'intents', forbidden)
    monkeypatch.setattr(knowledge, '_write', forbidden)
    first = s.director.evaluate(cast[0])
    first[0].fact['certainty'] = 0
    mood = spine.mood(cast[0], spine.facts(identity(cast[0])))
    mood['events'].append(999)
    for _ in range(3):
        assert s.director.evaluate(cast[0])[0].fact['certainty'] == 1
        assert 999 not in spine.mood(cast[0], spine.facts(identity(cast[0])))['events']
        living.board.hooks.resident_can_leave(cast[0].properties['id'])
    assert (s.store.d, s.director._intents, s.director._intent_context,
            s.director._dirty, s.director.knowledge_revision, spine.snapshot(),
            [a.properties for a in cast]) == before
    assert living.board.rng.getstate() == rng


@pytest.mark.perf
def test_hourly_member_communication_skips_unchanged_accounts_and_unchanged_events(monkeypatch):
    s, _living, spine, cast = world()
    for i, resident in enumerate(cast):
        knowledge.learn(s.store, identity(resident), fact(i + 1, 'trade', crime=False, pos=[0, 0, 0]))
    calls = []
    tell = knowledge.tell
    def counted(store, holder, listener, f, **kwargs):
        calls.append((holder, listener, f['e']))
        return tell(store, holder, listener, f, **kwargs)
    monkeypatch.setattr(knowledge, 'tell', counted)
    spine.decide(8)
    assert len(calls) == len(cast)
    calls.clear()
    for t in (9, 10, 11):
        spine.begin_tick()
        spine.decide(t)
    assert calls == []
    knowledge.learn(s.store, identity(cast[0]), fact(3, 'heal', crime=False, pos=[0, 0, 0]))
    s.director.invalidate(cast[0])
    spine.decide(12)
    entity = next(iter(spine.entities))
    assert calls == [(identity(cast[0]), entity, 3)]
    assert knowledge.knows(s.store, entity, 3)['from'] == identity(cast[0])
    assert entity in s.director._dirty


def test_bind_prunes_old_scene_and_dead_home_entities_from_goodwill():
    s, living, spine, cast = world()
    old = next(iter(spine.entities))
    knowledge.learn(s.store, old, fact())
    assert spine.goodwill('villagers', 'player') == -40
    visitor = actor('New home', id='new', faction='villagers', type='npc')
    visitor.pos = [2000, 0, 0]
    dead = actor('Dead home', id='dead', faction='villagers', type='npc', dead=True)
    spine.bind(living.board, [visitor, dead])
    assert old not in spine.entities and set(spine.entities) == {'faction_villagers_b'}
    assert spine.goodwill('villagers', 'player') == 0
    assert knowledge.knows(s.store, old, 1)  # history survives pruning active entities


def test_board_update_clears_projection_caches_before_actor_decisions(monkeypatch):
    s, living, spine, cast = world()
    old = spine._cache_tick
    order = []
    monkeypatch.setattr(spine, 'decide', lambda _t: order.append(('decide', spine._cache_tick)))
    monkeypatch.setattr(living.board, 'update', lambda _t: order.append(('board', spine._cache_tick)) or [])
    for name in ('_enforce_away', '_stream', '_stream_remains', 'persist'):
        monkeypatch.setattr(living, name, lambda: None)
    living.tick(1)
    assert order == [('decide', old + 1), ('board', old + 1)]


def test_restore_and_reset_drop_transient_projection_and_transfer_caches():
    s, _living, spine, cast = world()
    knowledge.learn(s.store, identity(cast[0]), fact(kind='trade', crime=False))
    spine.decide(8)
    spine.goodwill('villagers', 'player')
    s.director.evaluate(cast[0])
    spine.persist()
    saved = spine.snapshot()
    assert spine._goodwill_cache and spine._mood_cache and spine._member_sources
    old = spine._cache_tick
    assert spine.restore()
    assert spine.snapshot() == saved and spine._cache_tick > old
    assert not spine._goodwill_cache and not spine._mood_cache and not spine._fact_cache
    assert not spine._member_sources
    assert not any(k.startswith('_') for k in spine.snapshot())


def test_moving_residents_reuse_mood_and_intents_until_the_next_board_update(monkeypatch):
    s, _living, spine, cast = world()
    calls = []
    feeling = moods.evaluate
    def counted(*args):
        calls.append(True)
        return feeling(*args)
    monkeypatch.setattr(moods, 'evaluate', counted)
    resident = cast[0]
    cached = s.director.intents(resident)
    for i in range(1, 21):
        resident.pos[0] = i * 5
        resident.properties['health'] -= 1
        assert s.director.intents(resident) is cached
        s.director.evaluate(resident)
    assert calls == [True]
    spine.begin_tick()
    s.director.intents(resident)
    assert calls == [True, True]
