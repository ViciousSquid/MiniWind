"""The border glow: nothing far from a border, fading in near one, green on
the player's side and orange ahead, hugging the inked stroke; its setting;
and its GL pass."""

from types import SimpleNamespace

import numpy as np
import pytest

from .. import district_glow as dg
from .. import districts as dd


def two_districts():
    return dd.Districts({"bounds": [-4096, -4096, 4096, 4096], "warp": 0.0, "biome_bias": 0.0,
                         "border": {"cell": 32.0, "width": 30.0},
                         "districts": [{"id": "w", "seat": [-2000, 0]},
                                       {"id": "e", "seat": [2000, 0]}]})


def glow():
    return dg.Glow(two_districts(), lambda xs, zs: np.zeros(len(xs)))


def test_it_fades_in_from_its_range_and_is_full_close_by():
    assert dg.fade(dg.RANGE + 1) == 0.0 and dg.fade(dg.FULL) == 1.0
    assert 0.0 < dg.fade((dg.RANGE + dg.FULL) / 2) < 1.0


def test_far_from_a_border_nothing_is_built():
    g = glow()
    assert g.update(-1500.0, 0.0, 0.0) == 0.0
    assert g.fill is None and g.edge is None


def test_near_a_border_it_builds_green_here_and_orange_ahead():
    g = glow()
    assert g.update(-200.0, 0.0, 0.0) == pytest.approx(1.0)
    is_here = np.all(np.isclose(g.fill[:, 3:6], dg.HERE, atol=1e-3), axis=1)
    is_ahead = np.all(np.isclose(g.fill[:, 3:6], dg.AHEAD, atol=1e-3), axis=1)
    assert is_here.any() and is_ahead.any() and (is_here | is_ahead).all()
    def stroke_x(z):                                    # where the drawn line runs
        return centre_x(g, z)
    here = g.fill[np.all(np.isclose(g.fill[:, 3:6], dg.HERE, atol=1e-3), axis=1)]
    assert (here[:, 0] <= stroke_x(here[:, 2]) + 1.0).all()   # green on our (west) side
    version = g.version
    g.update(200.0, 0.0, 0.1)                           # crossed: the colours swap
    assert g.version > version
    here = g.fill[np.all(np.isclose(g.fill[:, 3:6], dg.HERE, atol=1e-3), axis=1)]
    assert (here[:, 0] >= stroke_x(here[:, 2]) - 1.0).all()
    g.update(-1500.0, 0.0, 5.0)
    assert g.fill is None                               # walked away: dropped


def centre_x(g, z):
    """x of the drawn stroke's centre at *z*, for the north-south border of
    :func:`two_districts`: the stroke runs at ``d = -tremor``, where +d is
    the left side of the border line's direction (as the bake has it)."""
    pts = g.lines[0]
    order = np.argsort(pts[:, 1])
    border_x = np.interp(z, pts[order, 1], pts[order, 0])
    tremor, _half, _p = dd.stroke_path(border_x, z, 30.0)
    d = pts[-1] - pts[0]
    left_x = -d[1] / np.hypot(*d)                       # the left normal's x
    return border_x + left_x * (-tremor)


def test_the_edge_hugs_the_inked_stroke():
    g = glow()
    g.update(-200.0, 0.0, 0.0)
    edge = g.edge[g.edge[:, 6] > 0.5]                   # the crisp band
    _t, half, _p = dd.stroke_path(np.zeros(len(edge)), edge[:, 2], 30.0)
    gap = np.abs(edge[:, 0] - centre_x(g, edge[:, 2])) - half
    assert (gap > -6.0).all() and (gap < 24.0).all()


def test_it_stays_off_the_water():
    found = two_districts()
    found.water = [(-1000.0, -4096.0, 1000.0, 4096.0, 50.0)]
    g = dg.Glow(found, lambda xs, zs: np.zeros(len(xs)))
    g.update(-200.0, 0.0, 0.0)
    assert g.fill[:, 6].max() == 0.0


def test_the_setting_and_the_console_turn_it_off(monkeypatch):
    from .. import console
    from ..runtime import MiniwindSession
    s = MiniwindSession.__new__(MiniwindSession)
    s._district_borders = True
    flags = {"border_glow": True}
    s._game_flag = lambda key, default=True: flags.get(key, default)
    assert s.border_glow_enabled()
    flags["border_glow"] = False
    assert not s.border_glow_enabled()
    flags["border_glow"] = True
    s._district_borders = False
    assert not s.border_glow_enabled()                   # never without the borders
    s._district_borders = True
    s.districts = two_districts()
    monkeypatch.setattr(console, "debug_log", lambda *a: None)
    ctx = console.ConsoleContext(logic_thread=SimpleNamespace(_miniwind=s), play_mode=True)
    console.cmd_districts(ctx, "glow off")
    assert not s.border_glow_enabled() and s.district_glow() is None
    import configparser
    import os
    ini = configparser.ConfigParser()
    ini.read(os.path.join(os.path.dirname(__file__), "..", "..", "settings.ini"))
    assert ini.getboolean("GAME", "border_glow")
    from ..integration import GAME_SETTINGS
    assert any(row[0] == "border_glow" and row[-1] is True for row in GAME_SETTINGS)


@pytest.mark.gl
def test_the_glow_draws_under_a_top_down_camera():
    import glm
    from OpenGL import GL as gl
    from tests.helpers.gl import GLTestContext
    from ..ui import district_glow_gl
    g = glow()
    g.update(-200.0, 0.0, 0.0)
    w, h = 160, 90
    with GLTestContext(w, h):
        gl.glViewport(0, 0, w, h)
        gl.glClearColor(0.3, 0.45, 0.2, 1.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        proj = glm.ortho(-800, 800, -450, 450, 1.0, 5000.0)
        view = glm.lookAt(glm.vec3(0, 2000, 0), glm.vec3(0, 0, 0), glm.vec3(0, 0, -1))
        drawn = district_glow_gl.draw(proj, view, g)
        raw = gl.glReadPixels(0, 0, w, h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
    image = np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(int)
    assert drawn > 0
    left, right = image[:, : w // 2 - 4], image[:, w // 2 + 4:]
    assert left[..., 1].max() > 130                     # a green wash on our side
    assert (right[..., 0] - right[..., 2]).max() > 60   # orange ahead
