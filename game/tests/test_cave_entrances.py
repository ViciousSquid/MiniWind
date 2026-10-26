"""Cave transitions are outside rock, on the ground and reachable on foot."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from game.tools.make_caves import CaveMouths


MAPS = Path(__file__).resolve().parents[2] / 'maps'


def _assert_player_clear(pos, brushes, name):
    # The player's normal 50 x 100 x 50 hull also contains the 32-unit icon.
    centres = np.asarray([b['pos'] for b in brushes])
    half = np.asarray([b['size'] for b in brushes]) * 0.5
    overlaps = np.all(np.abs(centres - pos) < half + (25, 50, 25), axis=1)
    assert not overlaps.any(), f'{name} overlaps brushes {np.flatnonzero(overlaps)}'


@pytest.mark.parametrize('direction', range(8))
def test_generated_cave_mouth_is_clear_in_every_direction_on_sloping_ground(direction):
    world = {'brushes': [], 'things': []}
    mouths = CaveMouths.__new__(CaveMouths)
    mouths.world = world
    mouths.ground = lambda x, z: 100.0 + x * 0.1 + z * 0.05
    angle = direction * math.pi / 4
    mouths.build('cave01', 'Test Cave', (0, 0, 100, (math.cos(angle), math.sin(angle))), 1)
    changer = next(t for t in world['things'] if t['type'] == 'levelchanger')
    pos = changer['pos']

    _assert_player_clear(pos, world['brushes'], f'direction {direction}')
    assert pos[1] == pytest.approx(mouths.ground(pos[0], pos[2]) + 64, abs=0.1)
    assert changer['properties']['radius'] == 170.0
    assert 'sprite_size' not in changer['properties']


@pytest.fixture(scope='module')
def overworld():
    return json.loads((MAPS / 'village_walled_source.json').read_text())


def test_shipped_overworld_cave_changers_are_clear_and_reachable(overworld):
    mouths = CaveMouths(overworld)
    changers = [t for t in overworld['things'] if t['type'] == 'levelchanger']
    assert len(changers) == 12
    for changer in changers:
        props = changer['properties']
        pos = np.asarray(changer['pos'])
        _assert_player_clear(pos, overworld['brushes'], props['name'])
        assert pos[1] == pytest.approx(mouths.ground(pos[0], pos[2]) + 64, abs=0.1)
        start = next(t for t in overworld['things']
                     if t['properties'].get('name') == props['_cave'] + '_exit')
        # The return spawn remains nearby, within the unchanged use radius.
        assert np.linalg.norm(pos - start['pos']) < props['radius'] == 170.0
        outward = np.asarray(start['pos']) - pos
        outward[1] = 0
        outward *= 40.0 / np.linalg.norm(outward)
        # Walk up beside the icon; decorative boulders can flank the path.
        approach_offset = np.asarray((-outward[2], 0.0, outward[0]))
        for fraction in np.linspace(0, 1, 9):
            approach = pos + fraction * approach_offset
            approach[1] = mouths.ground(approach[0], approach[2]) + 64
            _assert_player_clear(approach, overworld['brushes'], props['name'])


@pytest.mark.parametrize('slug', [f'cave{k:02}' for k in range(1, 13)])
def test_shipped_cave_exit_is_clear(slug):
    cave = json.loads((MAPS / f'{slug}.json').read_text())
    changer = next(t for t in cave['things'] if t['type'] == 'levelchanger')
    _assert_player_clear(changer['pos'], cave['brushes'], slug)
