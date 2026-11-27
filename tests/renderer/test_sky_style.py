"""``[Renderer] skystyle``: the sky behind the world (forward/edge_sky.py).
No GL here: the setting, how near the edge space comes in, and its fade."""

import configparser

import pytest

pytestmark = pytest.mark.qt

from engine import shaders
from engine.renderer.forward.edge_sky import SKY_STYLES, EdgeSkyMixin

BOUNDS = (-40960.0, 40960.0, -40960.0, 40960.0)


def _settings(value=None):
    config = configparser.ConfigParser()
    config.add_section('Renderer')
    if value is not None:
        config.set('Renderer', 'skystyle', value)
    return config


@pytest.mark.parametrize("value, style", [
    (None, 0), ("0", 0), ("1", 1), ("2", 2), ("3", 3),
    ("4", 0), ("-1", 0), ("galaxy", 0)])
def test_the_setting_is_read_as_one_of_the_styles(value, style):
    assert EdgeSkyMixin.sky_style_from_config(_settings(value)) == style


def test_without_settings_the_sky_is_as_it_always_was():
    assert EdgeSkyMixin.sky_style_from_config(None) == 0
    assert SKY_STYLES == (0, 1, 2, 3)


def test_the_shipped_settings_choose_style_one():
    from tests.helpers.paths import repo_path
    config = configparser.ConfigParser()
    config.read(repo_path("settings.ini"))
    assert EdgeSkyMixin.sky_style_from_config(config) == 1


def test_space_comes_in_near_the_edge_only():
    target = EdgeSkyMixin.edge_sky_target
    assert target(0.0, 0.0, BOUNDS) == 0.0                              # the middle
    assert target(0.0, 40960.0 - EdgeSkyMixin.EDGE_SKY_FAR - 1.0, BOUNDS) == 0.0
    assert target(0.0, 40960.0 - EdgeSkyMixin.EDGE_SKY_NEAR, BOUNDS) == 1.0
    assert target(40000.0, -40000.0, BOUNDS) == 1.0                     # a corner
    halfway = 40960.0 - (EdgeSkyMixin.EDGE_SKY_NEAR + EdgeSkyMixin.EDGE_SKY_FAR) / 2.0
    assert 0.0 < target(halfway, 0.0, BOUNDS) < 1.0


class _Sky(EdgeSkyMixin):
    pass


def test_it_fades_in_gently_and_back_out():
    sky = _Sky()
    assert sky.advance_edge_sky(0.0, 10.0) == 0.0          # first frame: at once
    fade = EdgeSkyMixin.EDGE_SKY_FADE
    amount = sky.advance_edge_sky(1.0, 10.0 + fade / 3.0)  # a third of the way
    assert amount == pytest.approx(1.0 / 3.0)
    amount = sky.advance_edge_sky(1.0, 10.0 + fade)
    assert amount == pytest.approx(1.0)
    amount = sky.advance_edge_sky(0.0, 10.0 + fade * 1.5)  # walking away
    assert amount == pytest.approx(0.5)


def test_a_jump_in_time_takes_the_target_at_once():
    sky = _Sky()
    sky.advance_edge_sky(0.0, 10.0)
    assert sky.advance_edge_sky(1.0, 400.0) == 1.0         # a load, a long pause
    assert sky.advance_edge_sky(0.0, 2.0) == 0.0           # the clock went back


def test_the_sky_shader_is_the_waters_own_sky():
    frag = shaders.DEFAULT_SHADERS['edge_sky.frag']
    water = shaders.DEFAULT_SHADERS['water.frag']
    sky = water[water.index('uniform vec4 skyState;'):water.index('void main()')]
    assert sky in frag
    # Style 1 keeps the sky overhead; 2 and 3 turn all of it.
    assert 'u_mode == 1' in frag and 'smoothstep(0.05, 0.6, d.y)' in frag
