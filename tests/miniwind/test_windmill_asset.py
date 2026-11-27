"""The live windmill is packaged as split Wavefront OBJ assets."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from engine.obj_loader import OBJLoader

ROOT = Path(__file__).resolve().parents[2]
FOLDER = ROOT / "assets/models"
pytestmark = pytest.mark.qt


def load_obj(name):
    model = OBJLoader()
    assert model.load(str(FOLDER / name)), name
    return model


def vertices_for_material(model, material):
    return np.asarray([
        model.vertices[corner[0]]
        for face in model.faces if face["material"] == material
        for corner in face["vertices"]
    ], dtype=np.float32)


def test_live_body_and_rotor_load_as_obj_with_top_down_bounds():
    body = load_obj("windmill_body.obj")
    rotor = load_obj("windmill_rotor.obj")

    assert body.up_axis == rotor.up_axis == "y"
    body_vertices = np.asarray(body.vertices, dtype=np.float32)
    rotor_vertices = np.asarray(rotor.vertices, dtype=np.float32)

    assert body_vertices[:, 1].min() == pytest.approx(0)
    assert 700 < body_vertices[:, 1].max() < 720
    assert 560 < np.ptp(body_vertices[:, 0]) < 610
    assert 350 < np.ptp(body_vertices[:, 2]) < 500

    # The OBJ rotor is authored around the original [0, 550, 170] prop anchor.
    # Its sails lie in X/Z and its axle is only a short distance above the pivot.
    assert np.ptp(rotor_vertices[:, 1]) < 25
    assert np.ptp(rotor_vertices[:, 0]) > 550
    assert np.ptp(rotor_vertices[:, 2]) > 550

    hub = np.asarray([0, 550, 170], dtype=np.float32)
    combined = np.concatenate([body_vertices, rotor_vertices + hub])
    assert combined[:, 1].min() == pytest.approx(0)
    assert combined[:, 1].max() < 730


def test_live_rotor_obj_has_valid_indices_and_four_complete_sails():
    rotor = load_obj("windmill_rotor.obj")
    quadrant_faces = [0, 0, 0, 0]

    for face in rotor.faces:
        corners = face["vertices"]
        assert corners
        assert all(0 <= corner[0] < len(rotor.vertices) for corner in corners), (
            "windmill_rotor.obj contains a face with an invalid position index"
        )
        points = np.asarray([rotor.vertices[corner[0]] for corner in corners],
                            dtype=np.float32)
        centre = points.mean(axis=0)
        if np.hypot(centre[0], centre[2]) < 80:
            continue
        angle = (np.degrees(np.arctan2(centre[2], centre[0])) + 360.0) % 360.0
        quadrant = int(((angle + 45.0) % 360.0) // 90.0)
        quadrant_faces[quadrant] += 1

    assert min(quadrant_faces) >= 30, quadrant_faces
    assert min(rotor.materials["Sail_red"]["diffuse"]) >= 0.65


def test_body_and_rotor_obj_material_libraries_resolve():
    body = load_obj("windmill_body.obj")
    rotor = load_obj("windmill_rotor.obj")

    assert {"Brick", "Roof_tile", "Roof_light", "Door", "Stone"} <= set(body.materials)
    assert {"Sail_red", "Iron"} <= set(rotor.materials)
    texture = body.materials["Brick"]["texture"]
    assert texture == "windmill_brick_albedo.png"
    assert (FOLDER / texture).is_file()


def test_live_body_obj_has_no_ground_facing_bottom_face():
    body = load_obj("windmill_body.obj")
    floor_y = min(vertex[1] for vertex in body.vertices)
    for face in body.faces:
        face_vertices = [body.vertices[corner[0]] for corner in face["vertices"]]
        assert not all(abs(vertex[1] - floor_y) < 1e-5 for vertex in face_vertices), (
            "windmill_body.obj must not contain a bottom face"
        )


def test_full_static_preview_obj_remains_y_up_and_grounded():
    model = load_obj("windmill.obj")
    vertices = np.asarray(model.vertices, dtype=np.float32)
    assert vertices[:, 1].min() == pytest.approx(0)
    assert 800 < vertices[:, 1].max() < 900


def test_the_door_fits_the_100_unit_player():
    model = load_obj("windmill.obj")
    door = vertices_for_material(model, "Door")
    door = door[door[:, 1] < 120]  # Exclude the same timber used by upper windows.
    assert np.ptp(door[:, 1]) == pytest.approx(106)


@pytest.mark.parametrize("name", ["windmill_topdown.png", "windmill_overhead.png"])
def test_rendered_sprites_have_real_alpha_and_a_clear_gutter(name):
    with Image.open(ROOT / "assets/sprites/scenery" / name) as image:
        assert image.mode == "RGBA" and image.size == (1024, 1024)
        alpha = image.getchannel("A")
        assert alpha.getextrema() == (0, 255)
        left, top, right, bottom = alpha.getbbox()
        assert min(left, top) >= 8 and max(right, bottom) <= 1016
        assert alpha.getpixel((512, 512)) > 240
