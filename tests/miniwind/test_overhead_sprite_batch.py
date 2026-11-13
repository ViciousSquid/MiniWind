"""The overhead sprites (heads, held weapons, floor objects, blood, arrows)
drawn as one instanced batch look the same as drawn one at a time, in the
same order, with one draw per run sharing a texture, depth bias and depth
write."""

import math

import numpy as np
import pytest

pytest.importorskip("PyQt5")
pytest.importorskip("OpenGL")

from tests.helpers.gl import GLTestContext  # noqa: E402

pytestmark = pytest.mark.gl


def _scene(renderer):
    """Overlapping sprites in several textures, layers, tints and fades."""
    keys = sorted(renderer._textures)
    tex = [renderer._textures[k] for k in keys if renderer._textures[k]]
    out = []
    for i in range(24):
        a = i * 0.7
        # Each at its own height: coplanar overlaps at one depth bias would
        # z-fight, deciding pixels by rounding rather than by the renderer.
        out.append(dict(pos=(math.cos(a) * 60.0, 3.0 * i, math.sin(a) * 60.0), facing=a,
                        texture=tex[i % len(tex)] if i % 5 else tex[0],
                        size=40.0 + 3 * i, y_offset=float(i % 3) * 4.0,
                        tint=(1.0, 0.2, 0.1, 0.4) if i % 4 == 0 else (0, 0, 0, 0),
                        depth_write=bool(i % 2), opacity=1.0 - 0.03 * i,
                        squash=0.5 if i % 7 == 0 else 1.0))
    return out


def _paint(ctx, renderer, scene, batched):
    import OpenGL.GL as gl
    import glm
    ctx.bind()
    gl.glViewport(0, 0, ctx.width, ctx.height)
    gl.glClearColor(0.2, 0.3, 0.4, 1.0)
    gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
    gl.glEnable(gl.GL_DEPTH_TEST)
    projection = glm.perspective(glm.radians(60.0), 1.0, 1.0, 2000.0)
    view = glm.lookAt(glm.vec3(0, 300, 1), glm.vec3(0, 0, 0), glm.vec3(0, 1, 0))
    if batched:
        assert renderer.begin(projection, view)
    for s in scene:
        renderer._draw_texture(projection, view, s["pos"], s["facing"], s["texture"],
                               s["size"], s["y_offset"], tint=s["tint"],
                               depth_write=s["depth_write"], opacity=s["opacity"],
                               squash=s["squash"])
    if batched:
        assert renderer.end() == len(scene)
    gl.glFinish()
    return np.asarray(ctx.read_pixels()).astype(int)


def test_a_batch_draws_what_single_sprites_draw(monkeypatch):
    from engine.overhead_sprite import OverheadSpriteRenderer
    with GLTestContext(160, 160) as ctx:
        renderer = OverheadSpriteRenderer(size=64.0)
        assert renderer._ready() and renderer._batch_prog is not None
        scene = _scene(renderer)
        one_by_one = _paint(ctx, renderer, scene, batched=False)

        import OpenGL.GL as gl
        draws = []
        real = gl.glDrawArraysInstanced
        monkeypatch.setattr(gl, "glDrawArraysInstanced",
                            lambda *a: (draws.append(a[3]), real(*a))[1])
        batched = _paint(ctx, renderer, scene, batched=True)

        background = one_by_one[0, 0]
        assert (np.abs(one_by_one - background).max(axis=-1) > 8).mean() > 0.05  # it drew
        # Every image is a layer of one texture array, resampled to the
        # layer's square size: the same picture, give or take resampling at
        # the sprites' edges.
        delta = np.abs(one_by_one - batched).max(axis=-1)
        assert delta.max() <= 32 and (delta > 8).mean() < 0.005
        # Images and owners no longer split a draw: only the depth state does.
        runs = 1 + sum(1 for a, b in zip(scene, scene[1:])
                       if (a["y_offset"], a["depth_write"])
                       != (b["y_offset"], b["depth_write"]))
        assert len(draws) == runs and sum(draws) == len(scene)


def test_the_same_layer_serves_every_owner_of_an_image():
    """A player's and an NPC's sword are one image and one layer."""
    from engine.overhead_sprite import OverheadSpriteRenderer
    import glm
    with GLTestContext(64, 64):
        renderer = OverheadSpriteRenderer(size=64.0)
        assert renderer.begin(glm.mat4(1.0), glm.mat4(1.0))
        tex = next(t for t in renderer._textures.values() if t)
        for x in (0.0, 10.0, 20.0):
            renderer._draw_texture(glm.mat4(1.0), glm.mat4(1.0), (x, 0, 0), 0.0, tex,
                                   10.0, 0.0)
        renderer.end()
        layers = renderer._layers.layers_for([tex, tex])
        assert layers is not None and layers[0] == layers[1]
        assert renderer._layers.count == 1


def test_nothing_collected_draws_nothing():
    from engine.overhead_sprite import OverheadSpriteRenderer
    import glm
    with GLTestContext(32, 32):
        renderer = OverheadSpriteRenderer()
        assert renderer.begin(glm.mat4(1.0), glm.mat4(1.0))
        assert renderer.end() == 0
        assert renderer._batch is None
