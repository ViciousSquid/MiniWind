"""The live Props and render projection follow each mill's production flag."""

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

from ..windmills import (HUB, PRODUCING, ROTOR_FOR, RUN_SPEED, SPIN_DOWN_SECONDS,
                         SPIN_UP_SECONDS, Windmills, set_producing)

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
        'name': name, 'render_mode': 'model', 'model_path': 'assets/models/windmill_body.glb',
        PRODUCING: producing, 'rotation': list(rotation), 'scale': [scale] * 3})
    rotor = Prop(properties={
        'name': name + '_sails', 'render_mode': 'model',
        'model_path': 'assets/models/windmill_rotor.glb', ROTOR_FOR: body.properties['id'],
        'rotation': list(rotation)})
    logic.editor_state.things.extend([body, rotor])
    return body, rotor


def test_mills_operate_independently_and_the_towers_never_turn(logic):
    body, rotor = _pair(logic)
    other, other_rotor = _pair(logic, 'other', producing=False)
    mills = Windmills(logic)
    mills.install()
    mills.update(SPIN_UP_SECONDS)
    assert rotor.properties['rotation'][2] == pytest.approx(RUN_SPEED * SPIN_UP_SECONDS / 2)
    assert other_rotor.properties['rotation'] == [0, 0, 0]
    assert body.properties['rotation'] == other.properties['rotation'] == [0, 0, 0]
    set_producing(body, False)
    set_producing(other, True)
    mills.update(SPIN_DOWN_SECONDS)
    stopped_angle = rotor.properties['rotation'][2]
    mills.update(5.0)
    assert rotor.properties['rotation'][2] == stopped_angle
    assert other_rotor.properties['rotation'][2] != 0
    assert len(logic.editor_state.things) == 4


def test_the_rotor_follows_a_translated_rotated_scaled_tower(logic):
    body, rotor = _pair(logic, pos=(100, 30, -200), rotation=(0, 90, 0), scale=2)
    mills = Windmills(logic)
    mills.install()
    np.testing.assert_allclose(rotor.pos, [100 + 2 * HUB[2], 30 + 2 * HUB[1], -200], atol=1e-4)
    mills.update(SPIN_UP_SECONDS)
    assert rotor.properties['rotation'] == pytest.approx([0, 90, RUN_SPEED * SPIN_UP_SECONDS / 2])
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
    angle = rotor.properties['rotation'][2]
    mills.update(2.0)
    assert rotor.properties['rotation'][2] == angle


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


def test_the_shipped_world_has_an_operating_mill_with_a_linked_rotor(logic):
    world = json.loads((ROOT / 'maps/miniwind_world.json').read_text())
    body = next(t for t in world['things'] if t['properties'].get('name') == 'windmill')
    rotor = next(t for t in world['things'] if t['properties'].get(ROTOR_FOR) == body['properties']['id'])
    for record in (body, rotor):
        assert (ROOT / record['properties']['model_path']).is_file()
        logic.editor_state.things.append(Prop(pos=record['pos'], properties=record['properties']))
    mills = Windmills(logic)
    mills.install()
    assert len(mills.mills) == 1 and body['properties'][PRODUCING] is True
    np.testing.assert_allclose(mills.mills[0].rotor.pos, rotor['pos'])
    mills.update(0.5)
    assert mills.mills[0].rotor.properties['rotation'][2] > 0


def test_the_game_session_installs_ticks_and_clears_its_windmills(logic):
    from ..runtime import MiniwindSession

    _body, rotor = _pair(logic)
    session = MiniwindSession(logic, cfg={})
    session.install()
    try:
        session.tick(0.1)
        assert rotor.properties['rotation'][2] > 0
    finally:
        session.uninstall()
    assert not session.windmills.mills


@pytest.mark.parametrize('parameter,expected', [('true', True), ('false', False), ('1', True), ('0', False)])
def test_the_production_input_can_start_and_stop_the_live_mill(logic, parameter, expected):
    from plugins.api import RuntimeAPI
    from plugins.manager import get_manager
    from ..host import MiniwindGame

    body, _rotor = _pair(logic)
    logic.world_runtime.build_entity_caches()
    host = MiniwindGame()
    host.register_runtime(RuntimeAPI(get_manager(), logic, host))
    logic.io_manager._execute_input(body.properties['name'], 'SetMillProducing', parameter,
                                    'test', target_id=body.properties['id'])
    assert body.properties[PRODUCING] is expected
