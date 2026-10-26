"""Every shipped cave mouth answers Use from the approach a player walks."""

import json
from pathlib import Path

import glm
import numpy as np
import pytest

pytest.importorskip("PyQt5", reason="LevelChanger entities require the Qt-backed editor things")

from editor.editor_state import EditorState
from editor.things import LevelChanger
from engine.logic_thread import LogicThread
from engine.player import Player
from engine.threaded_game_state import ThreadedGameState

from game.tools.make_caves import CaveMouths

MAPS = Path(__file__).resolve().parents[2] / 'maps'


@pytest.fixture
def logic(request):
    logic = LogicThread(ThreadedGameState(), EditorState())
    request.addfinalizer(logic.stop)
    return logic


def _prepare(logic, things, player_pos, angle):
    logic.editor_state.things = list(things)
    logic.editor_state.brushes = []
    logic.player_runtime.player = Player(player_pos[0], player_pos[2], float(angle))
    logic.player_runtime.player.pos = glm.vec3(*player_pos)
    logic.world_runtime.build_entity_caches()


def test_every_shipped_cave_entrance_activates_from_the_clear_approach(logic):
    path = MAPS / 'village_walled_source.json'
    world = json.loads(path.read_text())
    mouths = CaveMouths(world)
    for record in world['things']:
        if record['type'] != 'levelchanger':
            continue
        props = record['properties']
        changer = LevelChanger(pos=record['pos'], properties=props)
        start = next(t for t in world['things']
                     if t['properties'].get('name') == props['_cave'] + '_exit')
        outward = np.asarray(start['pos']) - record['pos']
        outward[1] = 0
        outward *= 40.0 / np.linalg.norm(outward)
        approach_offset = np.asarray((-outward[2], 0.0, outward[0]))
        player_pos = np.asarray(record['pos']) + approach_offset
        player_pos[1] = mouths.ground(player_pos[0], player_pos[2]) + 50.0
        _prepare(logic, [changer], player_pos=player_pos,
                 angle=np.arctan2(-approach_offset[0], -approach_offset[2]))

        logic.interaction_runtime.handle(True)

        assert logic.interaction_runtime.current_hud_message == props['prompt']
        ui = logic.interaction_runtime.level_complete_ui
        assert ui['target_map'] == props['target_map']
        assert ui['destination_spawn'] == 'entrance'
        assert ui['immediate'] is True
