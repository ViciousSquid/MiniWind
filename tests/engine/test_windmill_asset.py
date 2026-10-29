"""The bundled windmill imports at the same human scale in both Fio loaders."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

pytest.importorskip('OpenGL')
from engine.obj_loader import OBJLoader
from engine.glb_loader import GLBLoader

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / 'assets/models'
pytestmark = pytest.mark.qt


def _load_obj():
    obj = OBJLoader()
    assert obj.load(str(FOLDER / 'windmill.obj'))
    return obj


def test_obj_and_glb_have_the_same_upright_ground_origin_and_dimensions():
    obj = _load_obj()
    glb = GLBLoader()
    assert glb.load(str(FOLDER / 'windmill.glb'))
    a, b = np.asarray(obj.vertices), np.asarray(glb.get_flattened_vertices())
    assert obj.up_axis == 'y'
    np.testing.assert_allclose(a.min(0), b.min(0), atol=1e-3)
    np.testing.assert_allclose(a.max(0), b.max(0), atol=1e-3)
    assert a[:, 1].min() == pytest.approx(0)
    assert 800 < a[:, 1].max() < 900             # about eight 100-unit players
    assert 570 < np.ptp(a[:, 0]) < 600
    assert len(obj.faces) < 10000 and len(glb.get_flattened_triangles()) < 10000
    info = json.loads((FOLDER / 'windmill.json').read_text())
    np.testing.assert_allclose(a.max(0), info['bounds_max'], atol=1e-3)


def test_the_door_fits_the_100_unit_player_and_sails_clear_their_head():
    obj = _load_obj()
    def material_vertices(name):
        return np.asarray([obj.vertices[index[0]] for face in obj.faces
                           if face['material'] == name for index in face['vertices']])
    door = material_vertices('Door')
    door = door[door[:, 1] < 120]               # the same timber also frames upper windows
    assert np.ptp(door[:, 1]) == pytest.approx(106)
    assert material_vertices('Sail_red')[:, 1].min() > 200


def test_both_model_texture_paths_resolve_in_the_packaged_layout():
    obj = _load_obj()
    brick = obj.materials['Brick']
    assert brick['texture'] == 'windmill_brick_albedo.png'
    assert (FOLDER / brick['texture']).is_file()
    assert tuple(brick['color']) == (1, 1, 1)
    glb = GLBLoader()
    assert glb.load(str(FOLDER / 'windmill.glb'))
    assert glb.materials['Brick']['texture'] == 'windmill_brick_albedo.png'
    assert (FOLDER / glb.materials['Brick']['texture']).is_file()


def test_the_separate_body_and_hub_centered_rotor_reconstruct_the_static_model():
    models = {}
    for name in ('windmill', 'windmill_body', 'windmill_rotor'):
        model = GLBLoader()
        assert model.load(str(FOLDER / f'{name}.glb'))
        models[name] = np.asarray(model.get_flattened_vertices())
    hub = np.asarray([0, 550, 170])
    combined = np.concatenate([models['windmill_body'], models['windmill_rotor'] + hub])
    full = models['windmill']
    # Compare the actual vertex cloud, including the brick tower and sail
    # lattice, rather than accepting two models with merely similar bounds.
    assert combined.shape == full.shape
    for points, reference in ((combined, full), (full, combined)):
        points, reference = np.unique(points, axis=0), np.unique(reference, axis=0)
        for start in range(0, len(points), 128):
            distances = np.sum((points[start:start + 128, None] - reference) ** 2, axis=-1)
            assert np.max(np.min(distances, axis=1)) < 1e-6
    assert np.ptp(models['windmill_rotor'][:, 2]) < 20
    assert models['windmill_body'][:, 1].max() < 720


@pytest.mark.parametrize('name', ['windmill_topdown.png', 'windmill_overhead.png'])
def test_rendered_sprites_have_real_alpha_and_a_clear_gutter(name):
    with Image.open(ROOT / 'assets/sprites/scenery' / name) as image:
        assert image.mode == 'RGBA' and image.size == (1024, 1024)
        alpha = image.getchannel('A')
        assert alpha.getextrema() == (0, 255)
        left, top, right, bottom = alpha.getbbox()
        assert min(left, top) >= 8 and max(right, bottom) <= 1016
        assert alpha.getpixel((512, 512)) > 240    # footprint stays at canvas center
