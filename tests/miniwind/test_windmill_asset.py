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
    assert 800 < a[:, 1].max() < 900             # legacy static rotor reaches above the tower
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


def test_the_live_body_and_overhead_rotor_have_the_expected_top_down_bounds():
    models = {}
    for name in ('windmill_body', 'windmill_rotor'):
        model = GLBLoader()
        assert model.load(str(FOLDER / f'{name}.glb'))
        models[name] = np.asarray(model.get_flattened_vertices())
    body, rotor = models['windmill_body'], models['windmill_rotor']
    # The body includes the attached gabled house and remains grounded.
    assert body[:, 1].min() == pytest.approx(0)
    assert 700 < body[:, 1].max() < 720
    assert 700 < np.ptp(body[:, 0]) < 750
    assert 350 < np.ptp(body[:, 2]) < 550
    # The rotor is centred on the unchanged [0, 550, 170] prop anchor.
    # Its horizontal sail disk spans X/Z, with only a short vertical axle.
    assert np.ptp(rotor[:, 1]) < 180
    assert np.ptp(rotor[:, 0]) > 550
    assert np.ptp(rotor[:, 2]) > 550
    hub = np.asarray([0, 550, 170])
    combined = np.concatenate([body, rotor + hub])
    assert combined[:, 1].min() == pytest.approx(0)
    assert 700 < combined[:, 1].max() < 730
    assert 700 < np.ptp(combined[:, 0]) < 750
    assert {'Brick', 'Roof_tile', 'Sail_red'} <= set(model.materials)


@pytest.mark.parametrize('name', ['windmill_topdown.png', 'windmill_overhead.png'])
def test_rendered_sprites_have_real_alpha_and_a_clear_gutter(name):
    with Image.open(ROOT / 'assets/sprites/scenery' / name) as image:
        assert image.mode == 'RGBA' and image.size == (1024, 1024)
        alpha = image.getchannel('A')
        assert alpha.getextrema() == (0, 255)
        left, top, right, bottom = alpha.getbbox()
        assert min(left, top) >= 8 and max(right, bottom) <= 1016
        assert alpha.getpixel((512, 512)) > 240    # footprint stays at canvas center
