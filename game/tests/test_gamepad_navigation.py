"""Controller -> real session/UI/physics regressions, without physical hardware."""

import math
from types import SimpleNamespace as NS

import glm
import numpy as np
import pytest

pytest.importorskip("PyQt5")
from PyQt5.QtGui import QImage, QPainter

from engine.logic_camera import LogicCamera
from engine.logic_player import LogicPlayer
from engine.player import Player
from engine.threaded_game_state import ThreadedGameState
from .. import controls, keybinds
from ..gamepad import GamepadInput, QtSink
from ..rpg import equipment as eq, inventory as inv
from ..ui import drag, hits, worldmap, hud_frame
from ..ui.pack_window import PackWindow
from .test_gamepad import _Source, _Clock
from .test_inventory_strip import _session, _give, _Thing

pytestmark = pytest.mark.qt


@pytest.fixture(autouse=True)
def clean_input():
    keybinds.apply(None)
    hits.clear()
    drag.reset()
    controls.use(controls.GAMEPAD)
    yield
    keybinds.apply(None)
    hits.clear()
    drag.reset()
    controls.use(controls.KEYBOARD)


def _sink(session):
    state = ThreadedGameState()
    view = NS(game_state=state, logic_thread=NS(_miniwind=session))
    sink = QtSink(view)
    sink.enabled = lambda: True
    sink.keyboard_menu = lambda: False
    sink.menu_open = lambda: session.open_screen is not None or session.dialogue is not None
    return sink


def _controller(session):
    session.needs_char_creation = False  # these scenarios start after character creation
    source, clock, sink = _Source(), _Clock(), _sink(session)
    pad = GamepadInput(source, sink, clock)
    def press(*buttons, **axes):
        source.set(*buttons, **axes)
        clock.t += 1 / 60
        pad.poll()
        hits.run_clicks(session)
    return pad, sink, press


def _paint(window):
    image = QImage(1280, 800, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        window.draw_body(painter, 20, 20, 1120)
    finally:
        painter.end()
    return image


def test_dpad_browses_and_a_uses_quickbar_even_beside_an_npc():
    s = _session()
    _give(s, "iron_shortsword", "potion_heal_minor")
    s.strip_selected = 1
    s.interact_prompt = "Press A to talk"
    _pad, sink, press = _controller(s)
    press("dpad_right")
    assert s.strip_selected == 0
    assert eq.weapon(s.game.character) is None
    press()
    press("a")
    assert eq.weapon(s.game.character).id == "iron_shortsword"
    press()
    press("a")
    assert sink.view.game_state.consume_use_key(), "A should still talk when not browsing"
    s.interact_prompt = ""
    s.game.character.health = 1
    press()
    press("dpad_right")
    before = inv.quantity(s.game.character.inventory, "potion_heal_minor")
    press()
    press("a")
    assert inv.quantity(s.game.character.inventory, "potion_heal_minor") == before - 1


def test_dialogue_dpad_a_and_b_do_not_need_a_mouse_or_a_held_key():
    npc = _Thing("Talker", type="npc", dialogue={"start": "hello", "nodes": {
        "hello": {"text": "Choose", "responses": [
            {"text": "First", "goto": "first"}, {"text": "Second", "goto": "second"}]},
        "first": {"text": "Wrong branch", "responses": []},
        "second": {"text": "Chosen branch", "responses": [{"text": "Bye", "goto": "END"}]}}})
    s = _session(npc)
    assert s.start_dialogue(npc, s.logic.player)
    _pad, _sink_, press = _controller(s)
    press("dpad_up")                  # wraps to the last available response
    assert s.dialogue_selected == len(s.current_view()["responses"]) - 1
    press()
    press("dpad_down")
    selected = next(i for i, response in enumerate(s.current_view()["responses"])
                    if response["text"] == "Second")
    for _ in range(selected):
        press()
        press("dpad_down")
    assert s.dialogue_selected == selected
    press()
    press("a")
    assert s.current_view()["text"] == "Chosen branch"
    assert s.dialogue_selected == 0
    press()
    press("b")
    assert s.dialogue is None


def test_inventory_dpad_pick_place_tabs_and_close(qt_app):
    s = _session()
    _give(s, "iron_helmet", "bread")
    s.open_screen = "inventory"
    win = s._overlay_win = PackWindow(s)
    _paint(win)
    _pad, _sink_, press = _controller(s)
    press("a")
    assert drag.picked_source() == ("pack", None, "iron_helmet")
    press()
    press("dpad_right")
    assert win.selected == "bread"
    press()
    press("a")                       # place back in the pack, with no double-click use
    assert drag.picked_source() is None
    assert eq.equipped_id(s.game.character, "head") is None
    first = win._cells[0][0].center()
    win._pad_point = (first.x(), first.y())
    press()
    press("a")
    s.open_screen = "character"
    win.set_screen("character")
    _paint(win)
    helmet_slot = next(rect for rect, target in win._targets if target == ("equip", "head"))
    point = helmet_slot.center()
    win._pad_point = (point.x(), point.y())
    press()
    press("a")
    assert eq.equipped_id(s.game.character, "head") == "iron_helmet"
    assert drag.picked_source() is None
    press()
    press("rb")
    assert s.open_screen == "journal"
    win.set_screen("journal")
    press()
    press("lb")
    assert s.open_screen == "character"
    win.set_screen("character")
    press()
    press("b")
    assert s.open_screen is None and drag.picked_source() is None


@pytest.mark.parametrize("handed,trigger", [("right", "left"), ("left", "right")])
def test_shield_trigger_holds_block_and_releases_without_a_bash(handed, trigger):
    s = _session()
    _give(s, "iron_shield")
    s.game.character.handed = handed
    eq.equip(s.game.character, "iron_shield")
    sink = _sink(s)
    shots = []
    sink.mouse = lambda *args, **kwargs: shots.append((args, kwargs))
    sink.hand(trigger, True)
    hits.run_clicks(s)
    assert s._pad_blocking
    sink.hand(trigger, False)
    hits.run_clicks(s)
    assert not s._pad_blocking and not shots


def test_disconnect_clears_shield_block_and_analog_movement():
    s = _session()
    _give(s, "iron_shield")
    eq.equip(s.game.character, "iron_shield")
    pad, sink, press = _controller(s)
    press(lt=1, lx=1)
    assert s._pad_blocking
    pad.source.state = None
    pad.poll()
    hits.run_clicks(s)
    assert not s._pad_blocking
    assert sink.view.game_state.consume_gamepad_input() == (None, (0, 0))


def test_fast_inventory_button_and_b_close_survive_between_logic_ticks():
    s = _session()
    _pad, sink, press = _controller(s)
    press("y")
    assert s.open_screen == "inventory"
    assert not sink.view.game_state.get_keys()
    press()
    press("b")
    assert s.open_screen is None


def _movement():
    logic = NS(game_state=ThreadedGameState(), game_session=None,
               collision_runtime=NS(_collision_brushes_cache=[]),
               mover_runtime=NS(_mover_brush_list=[], _door_brush_list=[]),
               world_runtime=NS(terrain=None),
               session_runtime=NS(spatial_grid=None, physics_world=None))
    runtime = logic.player_runtime = LogicPlayer(logic)
    runtime.player = Player(0, 0, angle=0.7, physics_enabled=False)
    logic.camera = LogicCamera(logic)
    logic.camera.set_camera_mode("Overhead")
    return logic, runtime


@pytest.mark.parametrize("yaw", [0, math.pi / 2, -math.pi / 2, 0.38])
@pytest.mark.parametrize("stick", [(0, -1), (0, 1), (1, 0), (-1, 0), (.7, -.7)])
def test_stick_walks_camera_relative_and_faces_movement_without_spiralling(yaw, stick):
    logic, runtime = _movement()
    logic.camera.overhead_yaw = yaw
    logic.game_state.set_gamepad_move(stick)
    start = glm.vec3(runtime.player.pos)
    for _ in range(8):
        runtime.update_primary(.02, set(), 0, 0)
    delta = runtime.player.pos - start
    h = math.pi + yaw
    x, y = stick
    wish = glm.vec3(-x * math.cos(h) - y * math.sin(h), 0,
                    x * math.sin(h) - y * math.cos(h))
    assert glm.dot(glm.normalize(delta), glm.normalize(wish)) == pytest.approx(1, abs=1e-5)
    assert runtime.player.angle == pytest.approx(math.atan2(delta.x, delta.z), abs=1e-5)
    assert logic.camera.overhead_yaw == yaw


def test_right_stick_orbits_without_turning_idle_sprite_and_modal_stops_it():
    logic, runtime = _movement()
    logic.game_state.set_gamepad_move((0, 0))
    logic.game_state.add_gamepad_look(100, 0)
    runtime.update_primary(.02, set(), 0, 0)
    assert logic.camera.overhead_yaw != 0
    assert runtime.player.angle == .7
    yaw = logic.camera.overhead_yaw
    logic.game_session = NS(modal_input_active=lambda: True)
    logic.game_state.add_gamepad_look(100, 0)
    runtime.update_primary(.02, set(), 0, 0)
    assert logic.camera.overhead_yaw == yaw


def test_controller_keeps_a_player_oriented_camera_stable_while_walking_sideways():
    logic, runtime = _movement()
    logic.camera.overhead_orientation = "player"
    heading = logic.camera.overhead_heading(runtime.player.angle)
    logic.game_state.set_gamepad_move((1, 0))
    for _ in range(8):
        runtime.update_primary(.02, set(), 0, 0)
    difference = logic.camera.overhead_heading(runtime.player.angle) - heading
    assert math.atan2(math.sin(difference), math.cos(difference)) == pytest.approx(0)


@pytest.mark.parametrize("enabled", [False, True])
def test_settings_ini_can_disable_right_stick_rotation(enabled):
    import configparser
    s = _session()
    config = configparser.ConfigParser()
    config.read_dict({"GAME": {"camera_rotation": str(enabled)}})
    s._editor_config = lambda: config
    sink = _sink(s)
    sink.walk((0, 0))
    sink.look(100, 25)
    assert sink.view.game_state.consume_gamepad_input()[1] == ((100, 25) if enabled else (0, 0))


@pytest.mark.parametrize("key,stick", [(ord("["), -1), (ord("]"), 1)])
@pytest.mark.parametrize("enabled", [False, True])
def test_brackets_and_right_stick_share_rotation_and_the_renamed_setting(key, stick, enabled):
    import configparser
    from ..gamepad import LOOK_SPEED
    s = _session()
    config = configparser.ConfigParser()
    config.read_dict({"GAME": {"camera_rotation": str(enabled)}})
    s._editor_config = lambda: config
    s.needs_char_creation = False
    keyboard, keyboard_runtime = _movement()
    controller, controller_runtime = _movement()
    keyboard.game_session = controller.game_session = s
    dt = 1 / 60
    # Already queued stick input must also be suppressed if rotation is off.
    controller.game_state.set_gamepad_move((0, 0))
    controller.game_state.add_gamepad_look(stick * LOOK_SPEED * dt, 0)
    keyboard_runtime.update_primary(dt, {key}, 0, 0)
    controller_runtime.update_primary(dt, set(), 0, 0)
    assert keyboard.camera.overhead_yaw == pytest.approx(controller.camera.overhead_yaw)
    assert (keyboard.camera.overhead_yaw != 0) is enabled
    assert keyboard_runtime.player.angle == .7
    assert controller_runtime.player.angle == .7
    # Releasing the key stops rotation immediately.
    yaw = keyboard.camera.overhead_yaw
    keyboard_runtime.update_primary(dt, set(), 0, 0)
    assert keyboard.camera.overhead_yaw == yaw


def test_camera_rotation_defaults_on_and_brackets_cancel_each_other_or_yield_to_menus():
    s = _session()
    s._editor_config = lambda: None
    assert s.camera_rotation_enabled()
    logic, runtime = _movement()
    runtime.update_primary(.02, {ord("[")}, 0, 0)
    yaw = logic.camera.overhead_yaw
    assert yaw != 0
    runtime.update_primary(.02, {ord("["), ord("]")}, 0, 0)
    assert logic.camera.overhead_yaw == yaw
    logic.game_session = NS(modal_input_active=lambda: True)
    runtime.update_primary(.02, {ord("]")}, 0, 0)
    assert logic.camera.overhead_yaw == yaw


def test_minimap_art_markers_player_and_north_rotate_with_camera(qt_app):
    logic, runtime = _movement()
    runtime.player.angle = math.pi
    s = NS(logic=logic, _live_actors=lambda: [
        NS(pos=(1400, 0, 0), properties={"aggression": "hostile"})])
    world = worldmap.WorldMap()
    world.rgb = np.zeros((64, 64, 3), np.uint8)
    world.rgb[:32, :, :] = (30, 180, 30)  # north green, south blue
    world.rgb[32:, :, :] = (30, 30, 180)
    world.bounds, world.cell = ((-3200, 3200), (-3200, 3200)), 100
    x, y, size = worldmap.minimap_rect(1280, 800)
    cx, cy, r = x + size / 2, y + size / 2, size / 2
    def paint(yaw):
        logic.camera.overhead_yaw = yaw
        image = QImage(1280, 800, QImage.Format_ARGB32)
        image.fill(0)
        p = QPainter(image)
        worldmap.draw_minimap(p, s, None, 1280, 800, world)
        p.end()
        return image
    north, east = paint(0), paint(-math.pi / 2)
    assert north.pixelColor(round(cx), round(cy - r * .6)).green() > 150
    assert east.pixelColor(round(cx - r * .6), round(cy)).green() > 150
    offset = 1400 * size / worldmap.MINIMAP_SPAN
    assert north.pixelColor(round(cx + offset), round(cy)).red() > 200
    assert east.pixelColor(round(cx), round(cy - offset)).red() > 200
    # North's badge leaves the top and moves left, with upright text.
    image = QImage(1280, 800, QImage.Format_ARGB32)
    image.fill(0)
    p = QPainter(image)
    f = hud_frame.layout(1280, 800)
    hud_frame._paint_north(p, f, worldmap.minimap_rotation(s))
    p.end()
    reach = (f.R + f.r) / 2
    assert image.pixelColor(round(f.cx - reach), round(f.cy)).alpha() > 0
    assert image.pixelColor(round(f.cx), round(f.cy - reach)).alpha() == 0
