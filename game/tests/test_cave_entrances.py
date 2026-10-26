"""Cave transitions are outside rock, on the ground and reachable on foot."""

import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from game.tools.make_caves import CAVES, DRAGON_CAVE, CaveMouths, build_cave_map


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
    assert len(changers) == 20
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


@pytest.mark.parametrize('slug', [f'cave{k:02}' for k in range(1, 21)])
def test_shipped_cave_exit_is_clear(slug):
    cave = json.loads((MAPS / f'{slug}.json').read_text())
    changer = next(t for t in cave['things'] if t['type'] == 'levelchanger')
    _assert_player_clear(changer['pos'], cave['brushes'], slug)


def test_all_20_caves_have_unique_entrances_and_round_trip_destinations(overworld):
    expected = {f'cave{k:02}' for k in range(1, 21)}
    assert {c[0] for c in CAVES} == expected
    assert {p.stem for p in MAPS.glob('cave*.json')} == expected
    assert set(overworld['_miniwind_world']['caves']) == expected
    entrances = [t for t in overworld['things']
                 if t['type'] == 'levelchanger' and t['properties'].get('_cave')]
    assert Counter(t['properties']['_cave'] for t in entrances) == dict.fromkeys(expected, 1)
    for entrance in entrances:
        p = entrance['properties']
        slug = p['_cave']
        assert p['target_map'] == f'maps/{slug}.json'
        cave = json.loads((MAPS / f'{slug}.json').read_text())
        assert sum(t['type'] == 'playerstart' and t['properties']['name'] == p['destination_spawn']
                   for t in cave['things']) == 1
        exits = [t for t in cave['things'] if t['type'] == 'levelchanger']
        assert len(exits) == 1
        destination = exits[0]['properties']
        assert destination['target_map'] == 'maps/village_walled_source.json'
        assert destination['destination_spawn'] == f'{slug}_exit'
        assert sum(t['type'] == 'playerstart'
                   and t['properties']['name'] == destination['destination_spawn']
                   for t in overworld['things']) == 1
    primary = [t for t in overworld['things']
               if t['type'] == 'playerstart' and t['properties'].get('primary')]
    assert len(primary) == 1
    assert not primary[0]['properties'].get('_cave')


def test_caves_span_the_world_and_remain_separated(overworld):
    positions = np.asarray([t['pos'][::2] for t in overworld['things']
                            if t['type'] == 'levelchanger' and t['properties'].get('_cave')])
    mouths = CaveMouths(overworld)
    assert np.all(np.ptp(positions, axis=0) > (mouths.hi - mouths.lo) * 0.7)
    quadrants = Counter((x >= 0, z >= 0) for x, z in positions)
    assert len(quadrants) == 4
    assert min(quadrants.values()) >= 3
    distances = np.linalg.norm(positions[:, None] - positions[None, :], axis=2)
    np.fill_diagonal(distances, np.inf)
    # The mouths are spaced by at least 5000; their use icons extend 220
    # units towards the approach, which can bring a pair a little closer.
    assert distances.min() >= 4500


def _dragons(things):
    return [t for t in things if t['type'] == 'creature'
            and (t['properties'].get('npc_role') == 'dragon'
                 or t['properties'].get('head') == 'dragon'
                 or t['properties'].get('breathes_fire'))]


def test_exactly_one_dragon_in_one_shipped_cave():
    from game.rpg.heads import HEAD_SIZE, size_for

    locations = []
    for path in MAPS.glob('*.json'):
        world = json.loads(path.read_text())
        for dragon in _dragons(world.get('things', [])):
            locations.append(path.stem)
            assert dragon['properties']['respawn'] is False
            assert dragon['properties']['persistent'] is True
            assert size_for(dragon['properties']) == HEAD_SIZE * 8
    assert locations == [DRAGON_CAVE]


def test_regenerating_all_caves_still_creates_only_one_dragon(overworld):
    from game.rpg.heads import HEAD_SIZE, size_for

    settings = next(t for t in overworld['things'] if t['type'] == 'miniwindsettings')
    protos = {t['properties'].get('display_name'): t for t in overworld['things']
              if t['type'] == 'creature'}
    locations = []
    for k, (slug, name, monsters, count, loot) in enumerate(CAVES):
        cave = build_cave_map(slug, name, monsters, count, loot, settings, None,
                              protos, seed=101 + k * 17)
        for dragon in _dragons(cave['things']):
            locations.append(slug)
            assert size_for(dragon['properties']) == HEAD_SIZE * 8
    assert locations == [DRAGON_CAVE]


@pytest.mark.parametrize('definition', CAVES[12:], ids=lambda c: c[0])
def test_new_caves_have_their_monsters_and_treasure(definition):
    slug, _, monsters, count, loot = definition
    cave = json.loads((MAPS / f'{slug}.json').read_text())
    creatures = [t for t in cave['things'] if t['type'] == 'creature']
    assert len(creatures) == count
    assert {t['properties']['display_name'] for t in creatures} == set(monsters)
    chest = next(t for t in cave['things'] if t['type'] == 'container')
    assert [(s['id'], s['qty']) for s in chest['properties']['inventory']] == list(loot)
