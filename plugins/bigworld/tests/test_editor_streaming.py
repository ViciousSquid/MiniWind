"""Camera residency must never turn unloading into an authored deletion."""

import pytest

pytest.importorskip('PyQt5')
from editor.editor_state import EditorState
from editor.things import Light

pytestmark = pytest.mark.qt


def level():
    return {
        'version': 3,
        'brushes': [
            {'id': 'near-brush', 'name': 'Near wall', 'pos': [0, 0, 0], 'size': [64, 64, 64]},
            {'id': 'far-brush', 'name': 'Far wall', 'pos': [8192, 0, 0], 'size': [64, 64, 64]},
            {'id': 'spanning', 'name': 'Long road', 'pos': [4096, -64, 0], 'size': [8448, 32, 64]},
        ],
        'things': [
            {'type': 'bigworldsettings', 'pos': [0, 0, 0], 'properties': {
                'id': 'settings', 'type': 'bigworldsettings', 'activation_radius': 512,
                'deactivation_radius': 768}},
            {'type': 'playerstart', 'pos': [0, 40, 0], 'properties': {'id': 'start'}},
            {'type': 'light', 'pos': [0, 100, 0], 'properties': {'id': 'near-light', 'radius': 128}},
            {'type': 'light', 'pos': [8192, 100, 0], 'properties': {'id': 'far-light', 'radius': 128}},
        ],
    }


def load():
    state = EditorState()
    state.load_from_data(level(), stream_editor=True)
    return state


def ids(state):
    return {b['id'] for b in state.brushes} | {t.properties['id'] for t in state.things}


def test_only_camera_local_objects_are_instantiated_and_stationary_ticks_do_no_work(monkeypatch):
    state = load()
    assert 'near-brush' in ids(state)
    assert 'far-brush' not in ids(state)
    assert 'far-light' not in ids(state)
    monkeypatch.setattr(state.editor_stream, 'merge', lambda *args: pytest.fail('stationary scan'))
    assert not state.stream_editor_camera([1, 40, 1])


def test_crossing_cells_releases_old_objects_and_loads_new_ones_without_duplicate_spanning_brushes():
    state = load()
    assert state.stream_editor_camera([8192, 40, 0])
    assert 'far-brush' in ids(state)
    assert 'near-brush' not in ids(state)
    assert sum(b['id'] == 'spanning' for b in state.brushes) == 1
    assert 'start' in ids(state)


def test_edits_additions_and_deletions_survive_unload_save_and_reload():
    state = load()
    state.save_state()
    state.find_entity_by_id('near-brush')['name'] = 'Edited wall'
    state.things = [t for t in state.things if t.properties['id'] != 'near-light']
    added = Light(pos=[0, 100, 0])
    state.things.append(added)
    state.stream_editor_camera([8192, 40, 0])
    saved = state.get_level_data()
    assert len(saved['brushes']) == 3
    assert next(b for b in saved['brushes'] if b['id'] == 'near-brush')['name'] == 'Edited wall'
    assert 'near-light' not in {r['properties']['id'] for r in saved['things']}
    assert added.properties['id'] in {r['properties']['id'] for r in saved['things']}
    assert next(b for b in saved['brushes'] if b['id'] == 'far-brush') == level()['brushes'][1]
    state.load_from_data(saved, stream_editor=True)
    assert state.find_entity_by_id('near-brush')['name'] == 'Edited wall'
    assert added.properties['id'] in ids(state)


def test_selection_stays_live_across_camera_moves_and_history_restores_the_whole_map():
    state = load()
    wall = state.find_entity_by_id('near-brush')
    state.selected_objects = [wall]
    state.save_state()
    wall['name'] = 'Edited'
    state.stream_editor_camera([8192, 40, 0])
    assert state.find_entity_by_id('near-brush') is wall
    assert state.undo()
    assert state.selected_objects[0]['name'] == 'Near wall'
    assert len(state.get_level_data()['brushes']) == 3
    assert state.redo()
    assert state.selected_objects[0]['name'] == 'Edited'
    assert len(state.get_level_data()['brushes']) == 3


def test_play_handoff_retains_the_full_world_and_editor_can_resume_locally():
    state = load()
    checkpoint = state.snapshot()
    state.materialize_editor_world()
    assert {'near-brush', 'far-brush', 'near-light', 'far-light'} <= ids(state)
    assert state.editor_stream.suspended
    state.restore_state(checkpoint)
    assert not state.editor_stream.suspended
    assert 'far-brush' not in ids(state)
    assert len(state.get_level_data()['brushes']) == 3


def test_plain_maps_and_disabled_editor_streaming_keep_the_normal_load_path():
    data = level()
    data['things'][0]['properties']['editor_streaming'] = False
    state = EditorState()
    state.load_from_data(data, stream_editor=True)
    assert state.editor_stream is None
    assert 'far-brush' in ids(state)
