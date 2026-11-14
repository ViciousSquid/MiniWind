"""Actors reflected in water (engine/renderer/forward/passes.py): which
sprites reflect where, how a reflection is laid out, and the ripple shader."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest


def _passes():
    from engine.renderer.forward.passes import PassesMixin
    return PassesMixin.__new__(PassesMixin)


def _top_down_view():
    import glm
    # Looking straight down with the screen's "up" towards -z (north).
    return glm.lookAt(glm.vec3(0, 2000, 0), glm.vec3(0, 0, 0), glm.vec3(0, 0, -1))


def test_a_reflection_is_mirrored_flipped_fainter_and_laid_below_the_actor():
    p = _passes()
    data = np.zeros((1, 13), dtype=np.float32)
    data[0, 0:3] = (100.0, 96.0, -300.0)       # centre: 64 above the water at 32 (feet at 32)
    data[0, 3:5] = (128.0, 128.0)
    data[0, 6] = 1.0 + 2.0 * 5                  # opacity 1, a wound packed on top
    data[0, 10:13] = 1.0
    down = (0.0, 1.0)                           # the screen's down is +z here
    p._mirror_sprite_instances(data, None, None, np.array([32.0]), down, 0.4, (0.5, 0.6, 0.7))
    x, y, z, w, h = data[0, 0:5]
    assert y == pytest.approx(32.5)                       # on the surface
    assert h < 0                                          # upside down
    assert abs(h) == pytest.approx(128 * p.WATER_REFLECTION_SQUASH)
    assert x == pytest.approx(100.0) and z > -300.0       # moved towards the screen's bottom
    wound = np.floor(data[0, 6] * 0.5) * 2.0
    assert wound == 10.0                                  # the wound survives
    assert data[0, 6] - wound == pytest.approx(0.4, abs=1e-6)   # fainter
    assert tuple(np.round(data[0, 10:13], 3)) == (0.5, 0.6, 0.7)


def test_further_above_the_water_a_fainter_reflection():
    p = _passes()
    data = np.zeros((2, 13), dtype=np.float32)
    data[:, 3:5] = 128.0
    data[:, 6] = 1.0
    data[0, 1] = 64.0 + 32.0                    # feet on the water
    data[1, 1] = 64.0 + 32.0 + 150.0            # feet well above it
    p._mirror_sprite_instances(data, None, None, np.array([32.0, 32.0]), (0.0, 1.0), 0.4, (1, 1, 1))
    assert data[1, 6] < data[0, 6]


@pytest.fixture
def no_stencil(monkeypatch):
    import engine.renderer.forward.passes as passes
    monkeypatch.setattr(passes.gl, "glIsEnabled", lambda what: False)


def _scene(actors):
    """A 1000 x 600 pond (top at 32) centred on the origin, and *actors*
    ``(x, y, z, is_actor)``."""
    from engine.entity_table import ENT_MONSTER
    table = SimpleNamespace(bounds=np.array([[0.0, 16.0, 0.0, 500.0, 16.0, 300.0]]))
    pos = np.array([a[:3] for a in actors], dtype=np.float64)
    etable = SimpleNamespace(pos=pos, sprite_size=np.full((len(actors), 2), 128.0),
                             class_bits=np.array([ENT_MONSTER if a[3] else 0 for a in actors]))
    return table, etable


def test_only_actors_on_the_far_shore_reflect(no_stencil):
    p = _passes()
    table, etable = _scene([
        (0.0, 96.0, -330.0, True),     # north shore: reflection falls into the water
        (0.0, 96.0, 330.0, True),      # south shore: it would fall on land
        (0.0, 96.0, -1000.0, True),    # far from the water
        (0.0, 900.0, -330.0, True),    # high above it (on a cliff)
        (60.0, 96.0, -330.0, False),   # a marker, not an actor
    ])
    p._reflect_source = (etable, np.arange(5))
    plan = p._water_reflection_plan(table, np.array([0]), _top_down_view(), {})
    _etable, slots, planes, down, loose = plan
    assert list(slots) == [0]
    assert planes.tolist() == [32.0]
    assert down[1] == pytest.approx(1.0) and loose == []


def test_the_overhead_player_is_reflected_too(no_stencil):
    p = _passes()
    table, _etable = _scene([(0.0, 96.0, 0.0, True)])
    p._reflect_source = None
    head = ("assets/sprites/heads/head01.png", (0.0, 96.0, -330.0), (128.0, 128.0), 0.5)
    plan = p._water_reflection_plan(table, np.array([0]), _top_down_view(),
                                    {"reflected_heads": (head,)})
    assert plan[1] is None and plan[4] == [(head, 32.0)]


def test_reflections_off_or_inside_a_portal_draw_nothing(monkeypatch):
    import engine.renderer.forward.passes as passes
    p = _passes()
    table, etable = _scene([(0.0, 96.0, -330.0, True)])
    p._reflect_source = (etable, np.arange(1))
    monkeypatch.setattr(passes.gl, "glIsEnabled", lambda what: True)     # a portal owns the stencil
    assert p._water_reflection_plan(table, np.array([0]), _top_down_view(), {}) is None
    monkeypatch.setattr(passes.gl, "glIsEnabled", lambda what: False)
    p.water_reflects_actors = False
    assert p._water_reflection_plan(table, np.array([0]), _top_down_view(), {}) is None


def test_the_ripple_is_off_unless_asked_for():
    from engine.renderer.forward.shaders import ShadersMixin
    from engine.shaders import DEFAULT_SHADERS
    vert, frag = ShadersMixin._with_sprite_ripple(DEFAULT_SHADERS["sprite.vert"],
                                                 DEFAULT_SHADERS["sprite.frag"])
    assert "out vec2 TexCoordsIn;" in vert and "TexCoordsIn = aPos + 0.5;" in vert
    assert "uniform float spriteRipple;" in frag and "if (spriteRipple > 0.0)" in frag
    assert "texture(sprite_texture, TexCoords)" in frag      # the layered rewrite still applies
    # A shader that does not look as expected is left alone.
    assert ShadersMixin._with_sprite_ripple("x", "y") == ("x", "y")
