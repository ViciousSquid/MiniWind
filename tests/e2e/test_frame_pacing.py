"""Publication and Qt presentation remain independent of the display refresh."""

import glm
import pytest

pytest.importorskip('PyQt5')

from PyQt5.QtGui import QSurfaceFormat

from tests.helpers.worlds import level_data, make_thing, room
from editor.things import PlayerStart

pytestmark = [pytest.mark.qt, pytest.mark.integration]


def playing(fio_session):
    return fio_session(level_data(brushes=room(size=2048, height=512), things=[
        make_thing(PlayerStart, 'spawn', (0, 40, 0)),
    ])).start_play()


def test_camera_samples_use_tick_boundaries_and_survive_an_empty_iteration(fio_session):
    session = playing(fio_session)
    logic = session.logic
    tick = logic.TICK_DURATION
    logic._step_frame(tick, frame_time=10.0)
    logic._publish_frame()
    logic._step_frame(tick * 1.25, frame_time=10.0 + tick * 1.25)
    logic._publish_frame()
    with session.render_state() as state:
        previous, current = state.camera_frames
        assert previous.timestamp == pytest.approx(10.0)
        assert current.timestamp == pytest.approx(10.0 + tick)
    logic._step_frame(tick * 0.5, frame_time=10.0 + tick * 1.5)
    logic._publish_frame()
    with session.render_state() as state:
        assert state.camera_frames[1] is current
        assert state.camera_frames[0] is previous
    logic.session_runtime.set_world_paused('test', True)
    logic._step_frame(tick, frame_time=10.0 + tick * 2)
    logic._publish_frame()
    with session.render_state() as state:
        assert state.camera_frames is None
        assert state.player_pos == logic.player_runtime.player.pos


def test_a_completed_swap_schedules_play_even_without_a_new_tick(fio_session, monkeypatch):
    session = playing(fio_session)
    view = session.view
    calls = []
    surface = QSurfaceFormat()
    surface.setSwapInterval(1)
    monkeypatch.setattr(view, 'format', lambda: surface)
    monkeypatch.setattr(view, 'update', lambda: calls.append(True))
    view.frameSwapped.emit()
    assert calls == [True]
    calls.clear()
    surface.setSwapInterval(0)
    view.frameSwapped.emit()
    assert calls == []


def test_interpolating_a_borrow_does_not_pin_future_publications(fio_session):
    from engine.render_camera import interpolate_camera
    session = playing(fio_session)
    logic = session.logic
    tick = logic.TICK_DURATION
    for i in range(2):
        logic.player_runtime.player.pos.x = i * 8.0
        logic._step_frame(tick, frame_time=10.0 + i * tick)
        logic._publish_frame()
    with session.render_state() as frame:
        actual = glm.vec3(frame.player_pos)
        interpolate_camera(frame, 10.0 + tick * 1.5, tick)
        assert frame.player_pos.x == pytest.approx(4.0)
        assert session.game_state.published('player_pos') == actual
        logic._step_frame(tick, frame_time=10.0 + tick * 2)
        assert not logic._publish_frame()
    assert session.game_state.published_frames >= 3
    assert session.game_state._read_leases == 0
