"""
Simulation LOD and camera-region culling, end to end through a live LogicThread.

The rule this pins down: *the engine must not spend CPU simulating, preparing or
rendering things the player cannot meaningfully observe* — and, just as
importantly, it must not skip anything the player **can** observe.

Covered here:
  * the world index classifies a real play session's actors into tiers;
  * the combat AI only touches actors in the player's vicinity;
  * the render-state builder snapshots only actors the camera can reach, and
    submits only brushes in the camera's region;
  * a Show/Hide still lands on the very next frame despite the whole-world
    non-hidden brush list being cached between frames;
  * turning LOD off restores the pre-LOD behaviour exactly.

Run:  python -m pytest engine/tests/test_sim_lod.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import conftest
conftest.install_gl_stubs()

import glm
import pytest

from engine.render_cull import CAMERA_RENDER_CULL_DISTANCE
from engine.threaded_game_state import ThreadedGameState
from engine.world_index import (TIER_ACTIVE, TIER_ACTIVE_RADIUS, TIER_DISTANT,
                                TIER_DORMANT, TIER_NEAR, TIER_NEAR_RADIUS)

try:
    from editor.things import Monster
except Exception:                       # pragma: no cover - needs PyQt5
    Monster = None

pytestmark = pytest.mark.skipif(Monster is None, reason="editor.things needs PyQt5")


class _EditorState:
    def __init__(self, brushes, things):
        self.brushes = brushes
        self.things = things


class _Player:
    def __init__(self, pos=(0.0, 64.0, 0.0)):
        self.pos = glm.vec3(*pos)
        self.angle = 0.0
        self.pitch = 0.0
        self.camera_height = 56.0
        self.in_water = False
        self.eye_underwater = False
        self.water_tint = [0.0, 0.4, 0.6]
        self.properties = {}

    def update(self, *a, **k):
        pass


def _monster(name, x, z, team="bandits"):
    m = Monster()
    m.pos = [float(x), 64.0, float(z)]
    m.properties.update({
        "name": name, "type": "monster", "team": team,
        "awake": True, "triggered": False, "wake_on_sight": True,
        "monster_type": "human", "health": 30, "sprite_height": 128,
    })
    return m


def _brush(x, z, **extra):
    b = {"id": f"b{x}_{z}", "pos": [float(x), 0.0, float(z)],
         "size": [64.0, 64.0, 64.0], "textures": {}}
    b.update(extra)
    return b


def _logic(things=(), brushes=()):
    from engine.logic_thread import LogicThread
    brushes = list(brushes)
    things = list(things)
    lt = LogicThread(ThreadedGameState(), _EditorState(brushes, things))
    lt.play_mode = True
    lt.player = _Player()
    lt.set_camera_mode("Overhead")
    lt._build_entity_caches()
    lt._build_cull_cache()
    # These tests are about the tiering path itself, so they opt in regardless
    # of scene size. On a real settlement-sized map the engine skips it — see
    # test_a_tiny_cast_is_simulated_whole_rather_than_classified.
    lt.sim_lod_min_actors = 0
    return lt


# --- tiering through a real session ---------------------------------------

def test_a_play_tick_tiers_every_actor_by_distance_from_the_player():
    near = _monster("near", TIER_NEAR_RADIUS * 0.5, 0)
    active = _monster("active", (TIER_NEAR_RADIUS + TIER_ACTIVE_RADIUS) * 0.5, 0)
    far = _monster("far", TIER_ACTIVE_RADIUS * 5, 0)
    lt = _logic([near, active, far])
    lt._rebuild_world_index()
    assert lt.world_index.tier_of(near) == TIER_NEAR
    assert lt.world_index.tier_of(active) == TIER_ACTIVE
    assert lt.world_index.tier_of(far) == TIER_DISTANT
    # The tier is also stamped on the actor, which is how the AI thread reads it
    # without touching the index's arrays across threads.
    assert far.properties["_sim_tier"] == TIER_DISTANT


def test_the_combat_ai_only_touches_actors_in_the_players_vicinity():
    near = _monster("near", 200, 0)
    far = _monster("far", TIER_ACTIVE_RADIUS * 6, 0)
    lt = _logic([near, far])
    lt._rebuild_world_index()
    lt.monster_ai.update(1.0 / 30.0)
    seen = {id(t) for t in lt.monster_ai._active_buf}
    assert id(near) in seen
    assert id(far) not in seen


def test_switching_lod_off_restores_the_pre_lod_behaviour():
    far = _monster("far", TIER_ACTIVE_RADIUS * 6, 0)
    lt = _logic([far])
    lt.sim_lod_enabled = False
    lt._rebuild_world_index()
    assert lt.world_index.tier_of(far) == TIER_NEAR
    lt.monster_ai.update(1.0 / 30.0)
    assert id(far) in {id(t) for t in lt.monster_ai._active_buf}


# --- render-state culling --------------------------------------------------

def _render_things(lt):
    lt._rebuild_world_index()
    lt._prepare_render_state()
    return lt.game_state.get_write_state()


def test_only_actors_the_camera_can_reach_are_snapshotted():
    near = _monster("near", 100, 0)
    far = _monster("far", CAMERA_RENDER_CULL_DISTANCE * 2, 0)
    lt = _logic([near, far])
    names = {s.get("name") for s in _render_things(lt).visible_things
             if isinstance(s, dict)}
    ids = {s.get("id") for s in _render_things(lt).visible_things
           if isinstance(s, dict)}
    assert id(near) in ids
    assert id(far) not in ids


def test_the_full_entity_list_still_holds_the_whole_world():
    """Culling is for the main camera pass. Lighting, shadows and portals still
    get the world, so nothing loses a light because it walked off screen."""
    near = _monster("near", 100, 0)
    far = _monster("far", CAMERA_RENDER_CULL_DISTANCE * 2, 0)
    lt = _logic([near, far])
    ws = _render_things(lt)
    assert set(ws.all_things) == {near, far}


def test_only_brushes_in_the_cameras_region_reach_the_draw_list():
    here = _brush(0, 0)
    away = _brush(CAMERA_RENDER_CULL_DISTANCE * 3, 0)
    # Enough brushes that the spatial pre-cull engages rather than testing all.
    filler = [_brush(20000 + i * 600, 20000) for i in range(600)]
    lt = _logic([], [here, away] + filler)
    ws = _render_things(lt)
    ids = {b["id"] for b in ws.visible_brushes}
    assert here["id"] in ids
    assert away["id"] not in ids
    assert all(b["id"] not in ids for b in filler)


def test_hiding_a_brush_lands_on_the_very_next_frame():
    """The whole-world non-hidden list is cached between frames, so a runtime
    Show/Hide has to invalidate it — otherwise geometry would linger."""
    b = _brush(0, 0)
    lt = _logic([], [b] + [_brush(i * 600, 0) for i in range(1, 600)])
    ws = _render_things(lt)
    assert b["id"] in {x["id"] for x in ws.all_brushes}
    b["hidden"] = True
    lt.notify_visibility_changed()
    ws = _render_things(lt)
    assert b["id"] not in {x["id"] for x in ws.all_brushes}
    assert b["id"] not in {x["id"] for x in ws.visible_brushes}
    b["hidden"] = False
    lt.notify_visibility_changed()
    ws = _render_things(lt)
    assert b["id"] in {x["id"] for x in ws.all_brushes}


def test_a_moving_door_keeps_a_fresh_snapshot_in_the_cached_world_list():
    """all_brushes is cached, but a mover's per-frame render snapshot must not
    be — the shadow pass reads its position from that list."""
    door = _brush(0, 0, is_door=True)
    lt = _logic([], [door] + [_brush(i * 600, 0) for i in range(1, 600)])
    _render_things(lt)
    door["pos"] = [0.0, 128.0, 0.0]
    ws = _render_things(lt)
    snap = next(x for x in ws.all_brushes if x["id"] == door["id"])
    assert snap["pos"][1] == pytest.approx(128.0)


def test_a_streamed_out_actor_is_dormant_and_never_simulated():
    parked = _monster("parked", 100, 0)
    parked.properties["disabled"] = True
    lt = _logic([parked])
    lt._rebuild_world_index()
    assert lt.world_index.tier_of(parked) == TIER_DORMANT
    lt.monster_ai.update(1.0 / 30.0)
    assert id(parked) not in {id(t) for t in lt.monster_ai._active_buf}


# --- streaming as a core engine subsystem ---------------------------------

def test_a_map_with_a_settings_entity_streams_without_any_plugin():
    """The whole point of the move: the logic thread owns the streaming session
    and drives it from its own tick — no plugin discovery, no per-frame plugin
    dispatch, no `getattr` probing between the engine and its world manager."""
    from editor.things import BigWorldSettings

    settings = BigWorldSettings()
    settings.properties.update({"id": "bw", "enabled": True,
                                "activation_radius": 1024.0,
                                "deactivation_radius": 1024.0,
                                "show_cell_debug": False})
    near = _brush(0, 0)
    far = _brush(40000, 0)
    lt = _logic([settings], [near, far])
    lt.set_play_mode(True)
    try:
        assert lt.streaming is not None, "the map opted in, so a session exists"
        assert not near.get("hidden", False), "local geometry stays live"
        assert far.get("hidden", False), "distant geometry is parked"
        # Streaming's radius is now the simulation-LOD outer band too: one
        # answer to 'how far out is the world live'.
        assert lt.sim_active_radius == 1024.0
    finally:
        lt.set_play_mode(False)
    assert lt.streaming is None
    assert not far.get("hidden", False), "play stop restores the world exactly"


def test_a_map_without_a_settings_entity_never_pays_for_streaming():
    b = _brush(40000, 0)
    lt = _logic([], [b])
    lt.set_play_mode(True)
    try:
        assert lt.streaming is None
        assert not b.get("hidden", False)
    finally:
        lt.set_play_mode(False)


def test_a_parked_entity_is_dormant_so_streaming_and_simulation_agree():
    """Streaming decides what is loaded; the world index decides the tier. The
    link between them is the `disabled` flag, not a second distance test."""
    from editor.things import BigWorldSettings

    settings = BigWorldSettings()
    settings.properties.update({"id": "bw", "enabled": True,
                                "activation_radius": 1024.0,
                                "deactivation_radius": 1024.0,
                                "show_cell_debug": False})
    far_actor = _monster("far", 40000, 0)
    lt = _logic([settings, far_actor], [_brush(0, 0)])
    lt.set_play_mode(True)
    try:
        assert far_actor.properties.get("disabled") is True
        lt._rebuild_world_index()
        assert lt.world_index.tier_of(far_actor) == TIER_DORMANT
    finally:
        lt.set_play_mode(False)


# --- lights and the shadow pass -------------------------------------------

def _light(x, z, radius=512.0, casts=False, name=None):
    from editor.things import Light
    l = Light()
    l.pos = [float(x), 128.0, float(z)]
    l.properties.update({"id": name or f"l{x}_{z}_{radius:.0f}",
                         "radius": float(radius),
                         "state": "on", "casts_shadows": casts})
    return l


def test_a_light_survives_exactly_as_far_as_it_reaches():
    """Not a guess: a light contributes to the view iff its influence sphere
    reaches it, so the test is its radius, not a fixed distance."""
    near = _light(0, 0, radius=512.0)
    reaching = _light(6000, 0, radius=8000.0)     # far away but very wide
    tiny = _light(6000, 0, radius=64.0)           # far away and small
    lt = _logic([near, reaching, tiny], [_brush(0, 0)])
    ws = _render_things(lt)
    ids = {t.properties["id"] for t in ws.visible_things if hasattr(t, "properties")}
    assert near.properties["id"] in ids
    assert reaching.properties["id"] in ids
    assert tiny.properties["id"] not in ids


def test_no_shadow_casting_light_means_no_caster_geometry_is_gathered():
    lt = _logic([_light(0, 0, casts=False)],
                [_brush(i * 600, 0) for i in range(600)])
    ws = _render_things(lt)
    assert ws.shadow_brushes == []


def test_the_shadow_pass_gets_the_lights_reach_and_not_the_whole_world():
    reach = 1024.0
    lt = _logic([_light(0, 0, radius=reach, casts=True)],
                [_brush(i * 600, 0) for i in range(600)])
    ws = _render_things(lt)
    assert ws.shadow_brushes, "a shadow caster needs geometry to cast from"
    assert len(ws.shadow_brushes) < len(ws.all_brushes)
    # Everything within the light's reach of the view must still be there —
    # a missing caster is a missing shadow, which is a visible bug.
    box = ws.camera_relevance_box
    for b in ws.all_brushes:
        x, z = b["pos"][0], b["pos"][2]
        if (box[0] - reach <= x <= box[2] + reach
                and box[1] - reach <= z <= box[3] + reach):
            assert b in ws.shadow_brushes, f"caster at {x},{z} was dropped"


def test_a_tiny_cast_is_simulated_whole_rather_than_classified():
    """Relevance is not free. Below a measured crossover, sorting a handful of
    actors into tiers costs more than simulating all of them — so the engine
    does not, and every scalar path the gameplay layer had before is what runs.
    MiniWind's authored settlement lives on this side of the line."""
    from engine.logic_thread import SIM_LOD_MIN_ACTORS

    actors = [_monster(f"m{i}", i * 10, 0) for i in range(3)]
    far = _monster("far", TIER_ACTIVE_RADIUS * 8, 0)
    lt = _logic(actors + [far], [_brush(0, 0)])
    lt.sim_lod_min_actors = SIM_LOD_MIN_ACTORS      # the shipped policy
    lt._rebuild_world_index()
    assert lt.world_index.n == 0, "no index is built for a cast this small"
    assert "_sim_tier" not in far.properties
    lt.monster_ai.update(1.0 / 30.0)
    assert id(far) in {id(t) for t in lt.monster_ai._active_buf}, \
        "with no tiers, everything is simulated — the pre-LOD behaviour"


def test_falling_below_the_crossover_clears_stale_tier_stamps():
    """A stamp left over from a larger scene would silently stop an actor being
    simulated, so switching to the whole-cast path must wipe them."""
    a = _monster("a", 0, 0)
    far = _monster("far", TIER_ACTIVE_RADIUS * 8, 0)
    lt = _logic([a, far], [_brush(0, 0)])
    lt._rebuild_world_index()
    assert far.properties["_sim_tier"] == TIER_DISTANT
    lt.sim_lod_min_actors = 100                     # scene is now "tiny"
    lt._rebuild_world_index()
    assert "_sim_tier" not in far.properties
