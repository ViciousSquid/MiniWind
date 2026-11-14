"""The water pass copies only the patch of screen its water covers
(engine/renderer/forward/passes.py water_screen_rect)."""

import glm
import numpy as np

from engine.renderer.forward.passes import WATER_COPY_PAD, water_screen_rect


def _camera():
    proj = glm.perspective(glm.radians(60.0), 1280 / 720, 1.0, 20000.0)
    view = glm.lookAt(glm.vec3(0, 1000, 1), glm.vec3(0, 0, 0), glm.vec3(0, 1, 0))
    return proj * view


def _pixel(vp, x, y, z):
    c = vp * glm.vec4(x, y, z, 1.0)
    return ((c.x / c.w + 1) * 0.5 * 1280, (c.y / c.w + 1) * 0.5 * 720)


def test_a_small_pond_copies_a_small_patch_round_itself():
    vp = _camera()
    pond = [[200.0, 0.0, 100.0, 60.0, 4.0, 40.0]]
    x, y, w, h = water_screen_rect(vp, pond, (1280, 720))
    px, py = _pixel(vp, 200.0, 0.0, 100.0)
    assert x <= px <= x + w and y <= py <= y + h          # it covers the pond
    assert w * h < 1280 * 720 * 0.1                       # and little else
    assert w <= 2 * WATER_COPY_PAD + 200 and h <= 2 * WATER_COPY_PAD + 200


def test_reflective_water_reaches_further_and_off_screen_corners_copy_all():
    vp = _camera()
    pond = [[200.0, 0.0, 100.0, 60.0, 4.0, 40.0]]
    plain = water_screen_rect(vp, pond, (1280, 720))
    shiny = water_screen_rect(vp, pond, (1280, 720), margin_fraction=0.2)
    assert shiny[2] > plain[2] and shiny[3] > plain[3]
    behind = [[0.0, 0.0, 0.0, 5000.0, 2000.0, 5000.0]]  # wraps the camera
    assert water_screen_rect(vp, behind, (1280, 720)) == (0, 0, 1280, 720)
    assert np.all(np.array(water_screen_rect(vp, [], (1280, 720))) == (0, 0, 1280, 720))
