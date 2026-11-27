"""Wheat inventory drives the live mill and its render projection."""

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("PyQt5")

from editor.editor_state import EditorState
from engine.entity_table import EntityTable
from engine.logic_thread import LogicThread
from engine.prop_entity import Prop
from engine.threaded_game_state import ThreadedGameState

from ..rpg import inventory, items
from ..windmills import (HUB, MILL, ROTOR_AXIS, ROTOR_ANCHOR, ROTOR_FOR, RUN_SPEED,
                         SPIN_DOWN_SECONDS, SPIN_UP_SECONDS, Windmills,
                         is_producing, wheat_stock)

pytestmark = pytest.mark.qt
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def logic():
    owner = LogicThread(ThreadedGameState(), EditorState())
    try:
        yield owner
    finally:
        owner.stop()


def _pair(logic, name='mill', *, producing=True, pos=(0, 0, 0), rotation=(0, 0, 0), scale=1):
    body = Prop(pos=list(pos), properties={
        'name': name, 'render_mode': 'model', 'model_path': 'assets/models/windmill_body.obj',
        MILL: True, 'inventory': [items.make('wheat')] if producing else [],
        'display_name': 'Windmill', 'use_radius': 280.0,
        'rotation': list(rotation), 'scale': [scale] * 3})
    rotor = Prop(properties={
        'name': name + '_sails', 'render_mode': 'model',
        'model_path': 'assets/models/windmill_rotor.obj', ROTOR_FOR: body.properties['id'],
        'rotation': list(rotation)})
    logic.editor_state.things.extend([body, rotor])
    return body, rotor


def test_operational_mills_turn_independently_of_wheat_and_towers_never_turn(logic):
    body, rotor = _pair(logic)
    other, other_rotor = _pair(logic, 'other', producing=False)
    mills = Windmills(logic)
    mills.install()
    mills.update(SPIN_UP_SECONDS)
    assert rotor.properties['rotation'][1] == pytest.approx(RUN_SPEED * SPIN_UP_SECONDS / 2)
    assert other_rotor.properties['rotation'][1] == pytest.approx(
        RUN_SPEED * SPIN_UP_SECONDS / 2)
    assert is_producing(body) and not is_producing(other)
    assert body.properties['rotation'] == other.properties['rotation'] == [0, 0, 0]

    # Disabling a mill, not emptying its stock, coasts its rotor to rest.
    body.properties['disabled'] = True
    mills.update(SPIN_DOWN_SECONDS)
    stopped_angle = rotor.properties['rotation'][1]
    other_angle = other_rotor.properties['rotation'][1]
    mills.update(5.0)
    assert rotor.properties['rotation'][1] == stopped_angle
    assert other_rotor.properties['rotation'][1] > other_angle
    assert len(logic.editor_state.things) == 4


def test_a_side_mounted_rotor_uses_its_authored_anchor_and_forward_axis(logic):
    body = Prop(pos=[10, 20, 30], properties={
        'name': 'Chesterton Windmill', MILL: True,
        'model_path': 'assets/models/chesterton_windmill_body.obj',
        ROTOR_ANCHOR: [0, 700, 130],
        'rotation': [0, 0, 0], 'scale': [1, 1, 1],
    })
    rotor = Prop(pos=[0, 0, 0], properties={
        'name': 'Chesterton Windmill sails',
        'model_path': 'assets/models/chesterton_windmill_rotor.obj',
        ROTOR_FOR: body.properties['id'], ROTOR_AXIS: 'z',
        'rotation': [0, 0, 0],
    })
    logic.editor_state.things.extend([body, rotor])
    mills = Windmills(logic)
    mills.install()
    np.testing.assert_allclose(rotor.pos, [10, 720, 160], atol=1e-4)

    mills.update(SPIN_UP_SECONDS)
    assert rotor.properties['rotation'][2] == pytest.approx(RUN_SPEED * SPIN_UP_SECONDS / 2)
    assert rotor.properties['rotation'][1] == pytest.approx(0.0)
    assert body.properties['rotation'] == [0, 0, 0]


def test_the_rotor_follows_a_translated_rotated_scaled_tower(logic):
    body, rotor = _pair(logic, pos=(100, 30, -200), rotation=(0, 90, 0), scale=2)
    mills = Windmills(logic)
    mills.install()
    np.testing.assert_allclose(rotor.pos, [100 + 2 * HUB[2], 30 + 2 * HUB[1], -200], atol=1e-4)
    mills.update(SPIN_UP_SECONDS)
    assert rotor.properties['rotation'] == pytest.approx([0, 90 + RUN_SPEED * SPIN_UP_SECONDS / 2, 0])
    assert rotor.properties['scale'] == [2, 2, 2]
    body.pos = [200, 40, -100]
    mills.update(0.0)
    np.testing.assert_allclose(rotor.pos, [200 + 2 * HUB[2], 40 + 2 * HUB[1], -100], atol=1e-4)


def test_rotating_the_sails_reaches_both_render_buffers(logic):
    body, rotor = _pair(logic)
    mills = Windmills(logic)
    mills.install()
    tables = [EntityTable(), EntityTable()]
    for table in tables:
        table.begin_frame(logic.editor_state.things, epoch=1)
    before = tables[0].model_base_matrix[:2].copy()
    mills.update(0.5)
    for table in tables:
        table.begin_frame(logic.editor_state.things, epoch=1)
        np.testing.assert_array_equal(table.model_base_matrix[0], before[0])
        assert not np.allclose(table.model_base_matrix[1], before[1])


def test_a_disabled_mill_coasts_to_rest(logic):
    body, rotor = _pair(logic)
    mills = Windmills(logic)
    mills.install()
    mills.update(SPIN_UP_SECONDS)
    body.properties['disabled'] = True
    mills.update(0.25)
    assert 0 < mills.mills[0].motion.speed < RUN_SPEED
    mills.update(SPIN_DOWN_SECONDS)
    angle = rotor.properties['rotation'][1]
    mills.update(2.0)
    assert rotor.properties['rotation'][1] == angle


def test_uninstall_and_reinstall_restore_the_authored_rotor(logic):
    _body, rotor = _pair(logic)
    original = (list(rotor.pos), list(rotor.properties['rotation']), list(rotor.properties['scale']))
    mills = Windmills(logic)
    mills.install()
    mills.update(2.0)
    mills.clear()
    assert (list(rotor.pos), rotor.properties['rotation'], rotor.properties['scale']) == original
    mills.install()
    mills.update(SPIN_UP_SECONDS / 2)
    assert mills.mills[0].motion.speed == pytest.approx(RUN_SPEED / 2)


def test_missing_or_self_referencing_rotors_are_ignored(logic):
    _body, rotor = _pair(logic)
    rotor.properties[ROTOR_FOR] = 'missing'
    mills = Windmills(logic)
    mills.install()
    assert mills.mills == []
    rotor.properties[ROTOR_FOR] = rotor.properties['id']
    mills.install()
    assert mills.mills == []


def test_the_shipped_world_has_an_empty_mill_and_a_linked_rotor(logic):
    world = json.loads((ROOT / 'maps/miniwind_world.json').read_text())
    body = next(t for t in world['things'] if t['properties'].get('name') == 'windmill')
    rotor = next(t for t in world['things'] if t['properties'].get(ROTOR_FOR) == body['properties']['id'])
    for record in (body, rotor):
        assert (ROOT / record['properties']['model_path']).is_file()
        logic.editor_state.things.append(Prop(pos=record['pos'], properties=record['properties']))
    mills = Windmills(logic)
    mills.install()
    assert len(mills.mills) == 1 and body['properties'][MILL] is True
    assert body['properties']['no_collision'] is True
    marker = next(t for t in world['things']
                  if t['properties'].get('name') == 'loc_windmill')
    assert marker['pos'][0] == body['pos'][0]
    assert marker['pos'][2] == body['pos'][2]
    assert body['properties']['inventory'] == []
    from ..sim import ownership
    from ..windmills import is_producing
    assert ownership.is_theft(body['properties'], 'player', 'player')
    np.testing.assert_allclose(mills.mills[0].rotor.pos, rotor['pos'])
    assert not is_producing(mills.mills[0].body)
    mills.update(0.5)
    first_angle = mills.mills[0].rotor.properties['rotation'][1]
    assert first_angle > 0
    inventory.add_item(mills.mills[0].body.properties['inventory'], items.make('wheat'))
    assert is_producing(mills.mills[0].body)
    mills.update(0.5)
    assert mills.mills[0].rotor.properties['rotation'][1] > first_angle


def test_the_game_session_installs_ticks_and_clears_its_windmills(logic):
    from ..runtime import MiniwindSession

    _body, rotor = _pair(logic)
    session = MiniwindSession(logic, cfg={})
    session.install()
    try:
        session.tick(0.1)
        assert rotor.properties['rotation'][1] > 0
    finally:
        session.uninstall()
    assert not session.windmills.mills


@pytest.mark.parametrize('stocks,expected', [
    ([], 0), ([items.make('bread', 4)], 0), ([items.make('wheat', 0)], 0),
    ([items.make('wheat', 2), items.make('wheat', 3)], 5),
    ([items.make('wheat', 0), items.make('wheat', 3)], 3),
    ([{'id': 'wheat', 'qty': 'bad'}, items.make('wheat', 2)], 2),
])
def test_only_positive_wheat_stock_powers_the_mill(logic, stocks, expected):
    body, _rotor = _pair(logic)
    body.properties['inventory'] = stocks
    assert wheat_stock(body) == expected
    assert is_producing(body) is (expected > 0)


def test_stock_controls_flour_production_but_not_sail_motion(logic):
    body, rotor = _pair(logic, producing=False)
    body.properties['mill_producing'] = True  # legacy flag cannot create flour
    mills = Windmills(logic)
    mills.install()
    assert not is_producing(body)
    mills.update(SPIN_UP_SECONDS)
    assert mills.mills[0].motion.speed == RUN_SPEED
    assert rotor.properties['rotation'][1] > 0

    inventory.add_item(body.properties['inventory'], items.make('wheat', 4))
    assert is_producing(body)
    body.properties['mill_producing'] = False
    mills.update(0.5)
    angle_with_wheat = rotor.properties['rotation'][1]
    assert mills.mills[0].motion.speed == RUN_SPEED

    body.properties['inventory'].clear()
    assert not is_producing(body)
    mills.update(0.5)
    assert mills.mills[0].motion.speed == RUN_SPEED
    assert rotor.properties['rotation'][1] > angle_with_wheat


def test_a_held_mill_is_idle_until_its_holder_dies(logic):
    """The Old Mill: idle while Hal Corbin lives -- no one delivers to it or
    buys from it, the sails stand still -- a working mill once he is dead,
    however he died."""
    from engine.prop_entity import Prop as _Prop
    from ..windmills import HELD_BY, HOLD_CHECK_SECONDS
    body, rotor = _pair(logic)
    body.properties[HELD_BY] = "Hal Corbin"
    hal = _Prop(properties={"name": "Hal Corbin", "health": 80})
    logic.editor_state.things.append(hal)
    mills = Windmills(logic)
    mills.install()
    assert mills.find(body.properties["id"]) is None
    assert mills.nearest(body.pos) is None
    assert not is_producing(body)                      # wheat in it, but held
    mills.update(SPIN_UP_SECONDS)
    assert rotor.properties["rotation"][1] == 0
    hal.properties["dead"] = True
    mills.update(HOLD_CHECK_SECONDS)                   # it notices within seconds
    assert mills.find(body.properties["id"]) is body
    assert is_producing(body)
    mills.update(SPIN_UP_SECONDS)
    assert rotor.properties["rotation"][1] > 0
    # A holder who is gone from the world altogether (a body cleared away)
    # holds nothing either.
    logic.editor_state.things.remove(hal)
    mills.check_holders()
    assert mills.find(body.properties["id"]) is body

def test_legacy_red_grove_windmill_gets_vertical_sails_at_authored_hub(logic):
    world = json.loads((ROOT / "maps/miniwind_world.json").read_text())
    body_record = next(
        record for record in world["things"]
        if record["properties"].get("id") == "933ae405-bd82-48e5-b8fc-16a035dc5392"
    )
    body = Prop(pos=body_record["pos"], properties=body_record["properties"])
    logic.editor_state.things.append(body)

    mills = Windmills(logic)
    mills.install()
    rotors = [thing for thing in logic.editor_state.things
              if thing.properties.get(ROTOR_FOR) == body.properties["id"]]
    assert len(rotors) == 1
    rotor = rotors[0]
    assert rotor.properties["model_path"] == "assets/models/chesterton_windmill_rotor.obj"
    assert rotor.properties[ROTOR_AXIS] == "z"
    assert (ROOT / rotor.properties["model_path"]).is_file()
    assert body.properties[ROTOR_ANCHOR] == pytest.approx([-35.342, 339.618, 17.848])
    np.testing.assert_allclose(rotor.pos, [-2028.658, 515.618, 7454.152], atol=1e-4)

    mills.update(SPIN_UP_SECONDS)
    assert rotor.properties["rotation"][1] == pytest.approx(180.0)
    assert rotor.properties["rotation"][2] > 0.0

    # Reinstalling the session must reuse the same linked rotor, not add one.
    mills.install()
    assert sum(thing.properties.get(ROTOR_FOR) == body.properties["id"]
               for thing in logic.editor_state.things) == 1

