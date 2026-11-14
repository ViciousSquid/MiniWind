"""Castle exports preserve human scale, material paths and modular wall joins."""
import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip('OpenGL')
from engine.glb_loader import GLBLoader
from engine.obj_loader import OBJLoader

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / 'assets/models'
pytestmark = pytest.mark.qt


@pytest.mark.parametrize('name,record,budget', [
    ('castle_tower', 'tower', 3500), ('town_wall', 'wall', 600),
    ('castle_gatehouse', 'gatehouse', 3200)])
def test_real_loaders_agree_on_geometry_scale_and_materials(name, record, budget):
    obj, glb = OBJLoader(), GLBLoader()
    assert obj.load(str(FOLDER / f'{name}.obj'))
    assert glb.load(str(FOLDER / f'{name}.glb'))
    assert obj.up_axis == 'y'
    a, b = np.asarray(obj.vertices), np.asarray(glb.get_flattened_vertices())
    info = json.loads((FOLDER / 'castle_kit.json').read_text())[record]
    for vertices in (a, b):
        assert np.isfinite(vertices).all()
        np.testing.assert_allclose(vertices.min(0), info['bounds_min'], atol=1e-3)
        np.testing.assert_allclose(vertices.max(0), info['bounds_max'], atol=1e-3)
        assert vertices[:, 1].min() == 0
    # Rounded clouds catch transformed or missing parts, beyond bounds alone.
    a, b = (np.unique(np.round(v, 3), axis=0) for v in (a, b))
    np.testing.assert_allclose(a, b, atol=1e-3)
    assert len(obj.faces) == len(glb.get_flattened_triangles()) == info['triangle_count']
    assert len(obj.faces) < budget
    for model in (obj, glb):
        mat = model.materials['Castle_stone']
        assert mat['texture'] == 'castle_stone_albedo.png'
        assert (FOLDER / mat['texture']).is_file()
        np.testing.assert_allclose(mat['color'], [1, 1, 1])
    # No reference person, ground plane, duplicate wall or node transforms in exports.
    j = glb.json_data
    assert len(j['meshes']) == 1 and len(j['nodes']) == 1
    assert not j['nodes'][0].get('translation')
    assert not j['nodes'][0].get('rotation')
    assert not j['nodes'][0].get('scale')


def test_wall_end_profiles_and_texture_phase_repeat_every_512_units():
    obj = OBJLoader()
    assert obj.load(str(FOLDER / 'town_wall.obj'))
    vertices = np.asarray(obj.vertices)
    ends = []
    for x in (-256, 256):
        end = vertices[np.isclose(vertices[:, 0], x)]
        ends.append(np.unique(end[:, 1:], axis=0))
    np.testing.assert_allclose(ends[0], ends[1])
    # On each textured lengthwise surface, UV phase also meets across the join.
    for face in obj.faces:
        if face['material'] != 'Castle_stone':
            continue
        xyz = np.array([obj.vertices[v[0]] for v in face['vertices']])
        if np.ptp(xyz[:, 0]) == 0:  # end caps map onto YZ, not along the wall
            continue
        if not np.any(np.isclose(abs(xyz[:, 0]), 256)):
            continue
        for index in face['vertices']:
            p = np.asarray(obj.vertices[index[0]])
            if abs(p[0]) == 256:
                uv = obj.texcoords[index[1]]
                assert uv[0] % 1 == pytest.approx(0, abs=1e-5)


def test_door_is_clear_of_the_battered_plinth_and_sized_for_a_person():
    obj = OBJLoader()
    assert obj.load(str(FOLDER / 'castle_tower.obj'))
    door = np.asarray([obj.vertices[v[0]] for f in obj.faces if f['material'] == 'Oak'
                       for v in f['vertices']])
    door = door[door[:, 1] < 200]  # exclude the roof hatch
    assert np.ptp(door[:, 1]) == pytest.approx(120)
    assert np.ptp(door[:, 0]) > 60
    assert door[:, 2].min() >= 224  # base cylinder never hides the door


def test_gatehouse_has_an_open_passage_in_the_exported_mesh():
    model = OBJLoader()
    assert model.load(str(FOLDER / 'castle_gatehouse.obj'))
    vertices = np.asarray(model.vertices)
    tris = np.array([[vertices[v[0]] for v in f['vertices']] for f in model.faces])
    def ray_hits(x, y):
        direction = np.array([0., 0., 1.])
        e1, e2 = tris[:, 1]-tris[:, 0], tris[:, 2]-tris[:, 0]
        h = np.cross(direction, e2)
        det = np.einsum('ij,ij->i', e1, h)
        valid = abs(det) > 1e-7
        inv = np.divide(1, det, out=np.zeros_like(det), where=valid)
        s = np.array([x, y, -500.])-tris[:, 0]
        u = inv*np.einsum('ij,ij->i', s, h)
        q = np.cross(s, e1)
        v = inv*(q@direction)
        distance = inv*np.einsum('ij,ij->i', e2, q)
        return np.any(valid & (u >= 0) & (v >= 0) & (u+v <= 1) & (distance > 0))
    for x in (-96, 0, 96):
        for y in (8, 100, 170):
            assert not ray_hits(x, y), 'a 100-unit person must pass through the arch'
    assert ray_hits(160, 100)  # actual stone pier
    assert ray_hits(0, 340)   # actual arch above the opening


def test_all_three_models_snap_at_their_advertised_x_planes():
    # Assembly: tower (0), wall (480), gatehouse (1248), next wall (2016).
    intervals=[]
    for name, x in [('castle_tower', 0), ('town_wall', 480),
                    ('castle_gatehouse', 1248), ('town_wall', 2016)]:
        model=OBJLoader()
        assert model.load(str(FOLDER / f'{name}.obj'))
        vertices=np.asarray(model.vertices)
        intervals.append((vertices[:, 0].min()+x, vertices[:, 0].max()+x))
    for left, right in zip(intervals, intervals[1:]):
        assert left[1] == right[0]
    # The tower has actual connection geometry at wall height at its X bounds.
    model=OBJLoader()
    assert model.load(str(FOLDER / 'castle_tower.obj'))
    v=np.asarray(model.vertices)
    for x in (-224, 224):
        end=v[np.isclose(v[:, 0], x)]
        assert np.any(np.isclose(end[:, 1], 392))
