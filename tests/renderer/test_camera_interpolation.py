"""A fixed-rate simulation must produce uniform motion at display refresh rates."""

import math

import glm
import numpy as np
import pytest

from engine.render_camera import CameraHistory, interpolate_camera
from engine.threaded_game_state import RenderState, ThreadedGameState


TICK = 1.0 / 60.0


def pose(x, angle=0.0, *, split=False):
    state = RenderState()
    state.is_play_mode = True
    state.player_pos = glm.vec3(x, 0, 0)
    state.player_angle = angle
    eye = state.player_pos + glm.vec3(0, 40, 0)
    state.camera_view_matrix = glm.lookAt(
        eye, eye + glm.vec3(math.sin(angle), 0, math.cos(angle)), glm.vec3(0, 1, 0))
    state.splitscreen_active = split
    state.player2_pos = glm.vec3(-x, 0, 0)
    eye2 = state.player2_pos + glm.vec3(0, 40, 0)
    state.player2_view_matrix = glm.lookAt(eye2, eye2 + glm.vec3(0, 0, 1), glm.vec3(0, 1, 0))
    return state


@pytest.mark.parametrize('refresh', [60, 120, 144])
def test_constant_walking_is_uniform_at_display_refresh(refresh):
    history = CameraHistory()
    serial = -1
    positions = []
    # Allow the first two simulation samples to arrive before measuring motion.
    for frame in range(math.ceil(refresh / 60), refresh * 2):
        now = 10.0 + frame / refresh + 0.003
        tick = int((now - 10.0) / TICK)
        for i in range(serial + 1, tick + 1):
            state = pose(i * 2.0)
            history.capture(state, i, 10.0 + i * TICK, 'play')
        serial = tick
        # Extra projection with no simulation step must not restart the blend.
        history.capture(state, serial, now, 'play')
        drawn = object.__new__(RenderState)
        drawn.__dict__ = state.__dict__.copy()
        interpolate_camera(drawn, now, TICK)
        positions.append(float(drawn.player_pos.x))
        eye = glm.vec3(glm.inverse(drawn.camera_view_matrix)[3])
        assert eye.x == pytest.approx(drawn.player_pos.x, abs=1e-4)
    assert np.diff(positions) == pytest.approx(np.full(len(positions) - 1, 120.0 / refresh), abs=3e-5)


def test_turning_uses_the_short_arc_and_preserves_a_rigid_camera():
    history = CameraHistory()
    before, after = pose(0, math.radians(359)), pose(0, math.radians(1))
    history.capture(before, 0, 10.0, 'play')
    history.capture(after, 1, 10.0 + TICK, 'play')
    interpolate_camera(after, 10.0 + 1.5 * TICK, TICK)
    view = np.array(after.camera_view_matrix)
    assert math.cos(after.player_angle) == pytest.approx(1.0)
    assert view[:3, :3] @ view[:3, :3].T == pytest.approx(np.eye(3), abs=1e-5)
    assert glm.determinant(after.camera_view_matrix) == pytest.approx(1.0)


@pytest.mark.parametrize('change', ['teleport', 'pause', 'new_session', 'camera_cut', 'stall'])
def test_discontinuities_snap_instead_of_blending(change):
    history = CameraHistory()
    history.capture(pose(0), 0, 10.0, 'play')
    state = pose(1000 if change == 'teleport' else 2)
    context = None if change == 'pause' else change if change in ('new_session', 'camera_cut') else 'play'
    history.capture(state, 1, 11.0 if change == 'stall' else 10.0 + TICK, context)
    assert state.camera_frames is None
    before = glm.vec3(state.player_pos)
    interpolate_camera(state, 10.0 + 1.5 * TICK, TICK)
    assert state.player_pos == before


def test_both_split_screen_poses_blend_without_mutating_the_published_frame():
    game = ThreadedGameState()
    history = CameraHistory()
    history.capture(pose(0, split=True), 0, 10.0, 'split')
    source = pose(8, split=True)
    history.capture(source, 1, 10.0 + TICK, 'split')
    game.get_write_state().__dict__.update(source.__dict__)
    game.request_swap()
    frame = game.get_render_state()
    try:
        interpolate_camera(frame, 10.0 + 1.5 * TICK, TICK)
        assert frame.player_pos.x == pytest.approx(4.0)
        assert frame.player2_pos.x == pytest.approx(-4.0)
        assert glm.vec3(glm.inverse(frame.player2_view_matrix)[3]).x == pytest.approx(-4.0)
        assert game.published('player_pos').x == 8
        assert game.published('player2_pos').x == -8
    finally:
        game.release_render_state(frame)
    assert game._read_leases == 0


def test_a_stalled_renderer_never_predicts_beyond_the_newest_pose():
    history = CameraHistory()
    history.capture(pose(0), 0, 10.0, 'play')
    state = pose(8)
    history.capture(state, 1, 10.0 + TICK, 'play')
    interpolate_camera(state, 20.0, TICK)
    assert state.player_pos.x == 8
