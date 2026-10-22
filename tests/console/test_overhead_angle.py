"""The console elevation uses the same camera geometry as rendering/culling."""
import math

import glm
import pytest

pytest.importorskip("PyQt5")
from editor.console_commands import ConsoleCommandHandler
from engine.logic_thread import LogicThread
from engine.threaded_game_state import ThreadedGameState
from editor.editor_state import EditorState

pytestmark = pytest.mark.qt


@pytest.fixture
def camera():
    logic = LogicThread(ThreadedGameState(), EditorState())
    yield logic.camera
    logic.stop()


@pytest.mark.parametrize("angle", [90, 60, 45, 30, 1])
def test_elevation_changes_the_actual_camera_direction_and_preserves_focus(camera, angle):
    camera.overhead_height = 800
    camera.set_overhead_angle(angle)
    focus = glm.vec3(10, 20, 30)
    position, direction, up = camera._overhead_camera(focus, 0)
    assert -direction.y == pytest.approx(math.sin(math.radians(angle)))
    assert abs(direction.z) == pytest.approx(math.cos(math.radians(angle)), abs=1e-6)
    assert position.y == pytest.approx(820)
    assert glm.length(glm.cross(direction, up)) > .001
    view = glm.lookAt(position, position + direction, up)
    projected = view * glm.vec4(focus, 1)
    # Measure screen displacement: glm uses single-precision matrices and a
    # shallow angle places the eye tens of thousands of world units away.
    assert abs(projected.x / projected.z) < 1e-4
    assert abs(projected.y / projected.z) < 1e-4
    assert camera.overhead_angle == angle


def test_initial_angle_is_straight_down(camera):
    assert camera.overhead_angle == 90
    _, direction, _ = camera._overhead_camera(glm.vec3(0), 0)
    assert tuple(direction) == (0, -1, 0)


@pytest.mark.parametrize("value", [0, -10, 91, float("nan"), float("inf"), "bad"])
def test_invalid_angles_leave_the_camera_unchanged(camera, value):
    camera.set_overhead_angle(60)
    with pytest.raises(ValueError):
        camera.set_overhead_angle(value)
    assert camera.overhead_angle == 60


def test_command_sets_queries_and_resets_via_the_live_camera(main_window, monkeypatch):
    messages, updates = [], []
    monkeypatch.setattr("editor.console_commands.debug_log", lambda level, msg: messages.append(msg))
    view = main_window.view_3d
    view.play_mode = True
    camera = view.logic_thread.camera
    monkeypatch.setattr(view, "update", lambda: updates.append(True))
    handler = ConsoleCommandHandler(main_window)
    assert "overheadangle" in handler.commands
    handler.handle_command("overheadangle 45")
    assert camera.overhead_angle == 45 and updates
    handler.handle_command("overheadangle")
    assert "45" in messages[-1]
    handler.handle_command("overheadangle nan")
    assert camera.overhead_angle == 45
    handler.handle_command("overheadangle 90")
    assert camera.overhead_angle == 90
    view.play_mode = False
    handler.handle_command("overheadangle 30")
    assert camera.overhead_angle == 90
