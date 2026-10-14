"""
Entities created after a session starts are registered at the cache rebuild.

Big World indexes the world when play starts; everything the game creates
afterwards -- creatures from spawn points, travellers off the journey board,
torches lit at dusk -- arrives later. Those entities had UUIDs but were never
filed: no cell, so no crossing could park them, and no tier stamp, so they read
NEAR and were fully simulated wherever they stood. The engine's entity-cache
rebuild is the boundary every spawn and despawn goes through, and these tests
pin that the registry follows the scene across it.
"""

import pytest

pytest.importorskip("PyQt5", reason="Big World machinery uses the real editor/logic owners")

pytestmark = pytest.mark.qt

from editor.editor_state import EditorState
from editor.things import Thing
from engine.logic_thread import LogicThread
from engine.spatial import (PARKED_HIDDEN_KEY, SIM_TIER_KEY, TIER_ACTIVE,
                            TIER_DORMANT, TIER_NEAR, tier_of)
from engine.threaded_game_state import ThreadedGameState
from plugins.bigworld.runtime import BigWorldSession


def make_thing(x, z, type_name="monster", **props):
    properties = {"type": type_name}
    properties.update(props)
    return Thing(pos=[float(x), 0.0, float(z)], properties=properties)


def started_session(things, at=(0.0, 0.0)):
    state = EditorState()
    state.things = list(things)
    logic = LogicThread(ThreadedGameState(), state)
    if logic.player_runtime.player is None:
        from engine.player import Player
        logic.player_runtime.player = Player(0.0, 0.0)
    logic.player_runtime.player.pos = [float(at[0]), 0.0, float(at[1])]
    logic.world_runtime.build_entity_caches()
    session = BigWorldSession(logic, activation_radius=2048.0,
                              deactivation_radius=2304.0, sim_near_radius=1024.0)
    session.start()
    return session


def authored_world():
    return [make_thing(i * 512.0 + 64.0, 64.0) for i in range(-8, 9)]


def test_entities_spawned_after_start_are_filed_and_tiered():
    s = started_session(authored_world())
    try:
        things = s.logic.editor_state.things
        near, active, far = (make_thing(100, 300), make_thing(1600, 64),
                             make_thing(9000, 9000))
        things.extend([near, active, far])
        assert len(s.manager.unregistered_things(things)) == 3

        s.sync_world()

        assert s.manager.unregistered_things(things) == []
        for t in (near, active, far):
            assert SIM_TIER_KEY in t.properties, "a spawned entity was left unstamped"
        assert tier_of(near) == TIER_NEAR
        assert tier_of(active) == TIER_ACTIVE
        assert tier_of(far) == TIER_DORMANT
        assert far.properties.get("disabled") is True, "a distant spawn was not parked"
    finally:
        s.stop()


def test_a_spawn_into_an_empty_cell_in_range_is_live():
    """A cell that held nothing until now was never a candidate for the active
    set; a spawn there next to the player must not be parked."""
    s = started_session(authored_world())
    try:
        spawned = make_thing(300, -1500)          # nothing was ever filed at z<0
        s.logic.editor_state.things.append(spawned)
        s.sync_world()
        assert s.manager.is_thing_active(spawned)
        assert not spawned.properties.get("disabled")
        assert tier_of(spawned) != TIER_DORMANT
    finally:
        s.stop()


def test_despawned_entities_are_unfiled_and_handed_back_clean():
    s = started_session(authored_world())
    try:
        things = s.logic.editor_state.things
        far = make_thing(9000, 9000)
        things.append(far)
        s.sync_world()
        assert far.properties.get("hidden") is True

        things.remove(far)
        delta = s.sync_world()

        assert far in delta.unregistered
        assert not s.manager.registered(far)
        assert all(far not in cell.things for cell in s.manager.cells.values())
        for key in (PARKED_HIDDEN_KEY, SIM_TIER_KEY, "bw_active"):
            assert key not in far.properties
        assert far.properties.get("hidden") is False
    finally:
        s.stop()


def test_the_engine_cache_rebuild_drives_registration():
    """Spawn code only calls the engine's rebuild; the plugin must hear it."""
    from plugins.manager import get_manager, load_plugins
    s = started_session(authored_world())
    load_plugins()
    mgr = get_manager()
    plugin = next(p for p in mgr.plugins if p.name == "bigworld")
    logic = s.logic
    was_enabled = plugin.enabled
    logic.plugins = mgr
    mgr.bind_host(logic)
    plugin.enabled = True
    plugin._sessions[logic] = s
    try:
        late = make_thing(1600, 64)
        logic.editor_state.things.append(late)
        logic.world_runtime.build_entity_caches()
        assert s.manager.registered(late)
        assert tier_of(late) == TIER_ACTIVE
    finally:
        plugin._sessions.pop(logic, None)
        plugin.enabled = was_enabled
        s.stop()


def test_a_carried_light_is_refiled_and_stays_lit():
    """A torch follows its holder; it must not be parked when the cells it was
    first filed in fall behind."""
    s = started_session(authored_world())
    try:
        torch = make_thing(50, 50, "light", radius=300.0)
        s.logic.editor_state.things.append(torch)
        s.sync_world()
        player = s.logic.player_runtime.player
        for x in range(0, 12001, 400):
            player.pos = [float(x), 0.0, 0.0]
            torch.pos = [float(x) + 50.0, 0.0, 50.0]
            s.tick()
            assert s.manager.is_thing_active(torch), "torch parked at x=%d" % x
            assert not torch.properties.get("hidden")
    finally:
        s.stop()


def test_stop_leaves_no_markers_on_spawned_entities():
    s = started_session(authored_world())
    things = s.logic.editor_state.things
    things.extend([make_thing(100, 300), make_thing(9000, 9000)])
    s.sync_world()
    s.stop()
    for t in things:
        for key in ("bw_active", SIM_TIER_KEY, PARKED_HIDDEN_KEY):
            assert key not in t.properties
