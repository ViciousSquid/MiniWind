"""Waterfalls off the world's edge and the underside beside them: the CPU
side (no GL). Where water reaches the terrain's edge it pours over it
(TerrainGL.edge_falls); beside the falls, the edge land hangs mirrored under
the strata wall (TerrainGL.under_slots, terrain_under.vert)."""

import math

import numpy as np
import pytest

from engine import shaders
from engine.constants import WATER_FLOW_DIRECTIONS, water_flow_velocity
from engine.renderer.core.terrain_gl import TerrainGL

BOUNDS = (-1000.0, 1000.0, -1000.0, 1000.0)
#: water_params rows: opacity, fresnel, wave height, waves on, distortion,
#: refraction, roughness.
PARAMS = [0.75, 0.5, 0.5, 1.0, 0.0, 1.33, 0.0]


def falls(centre, half, params=PARAMS):
    return TerrainGL.edge_falls(BOUNDS, [centre], [half], [[0.0, 0.32, 0.5]], [params])


def test_water_inside_the_world_pours_over_nothing():
    assert falls((0.0, 50.0, 0.0), (400.0, 16.0, 400.0)) == []


def test_water_reaching_one_side_pours_over_that_side_only():
    (fall,) = falls((800.0, 50.0, 0.0), (200.0, 16.0, 300.0))
    side, lo, hi, top, tint, opacity, reflectivity, slope = fall
    assert side == 1                                  # +x
    assert (lo, hi) == (-300.0, 300.0)                # along z
    assert top == 66.0                                # the water's surface
    assert tint == (0.0, 0.32, 0.5) and opacity == 0.75 and reflectivity == 0.5
    assert slope > 0.0


def test_water_round_a_corner_pours_over_both_sides_and_runs_on_round_it():
    got = falls((700.0, 50.0, -700.0), (300.0, 16.0, 300.0))
    assert sorted(f[0] for f in got) == [1, 2]        # +x and -z
    run = TerrainGL.FALLS_CORNER_RUN
    by_side = {f[0]: f for f in got}
    # The corner end of each stretch is carried past the corner, so neither
    # fades out there; the inland end stays where the water ends.
    assert by_side[1][1] == -1000.0 - run and by_side[1][2] == -400.0
    assert by_side[2][1] == 400.0 and by_side[2][2] == 1000.0 + run


def test_a_brush_just_short_of_the_edge_does_not_pour():
    assert falls((790.0, 50.0, 0.0), (200.0, 16.0, 300.0)) == []


def test_the_tongue_clears_the_waves_growing_off_the_pinned_edge():
    (fall,) = falls((800.0, 50.0, 0.0), (200.0, 16.0, 300.0))
    amp = TerrainGL.wave_amplitude(PARAMS, 32.0)
    cell = 400.0 / TerrainGL.WATER_SURFACE_CELLS      # the brush is 400 deep
    assert fall[7] >= amp / cell
    calm = falls((800.0, 50.0, 0.0), (200.0, 16.0, 300.0),
                 params=[0.75, 0.5, 0.5, 0.0, 0.0, 1.33, 0.0])
    assert calm[0][7] < fall[7]


def test_the_perimeter_runs_on_round_every_corner():
    w = BOUNDS[1] - BOUNDS[0]
    d = BOUNDS[3] - BOUNDS[2]
    # Each side's ends, as perimeter coordinates: the end of one is the
    # start of the next, and the last wraps to the first.
    ends = {side: TerrainGL.perimeter_span(BOUNDS, side, -1000.0, 1000.0)
            for side in range(4)}
    assert ends[2] == (0.0, w)                        # -z, from the -x/-z corner
    assert ends[1] == (w, w + d)                      # +x
    assert ends[3] == (w + d, 2 * w + d)              # +z, back towards -x
    assert ends[0] == (2 * w + d, 2 * w + 2 * d)      # -x, back to the start


def test_the_falls_reach_far_below_the_wall_into_the_haze():
    assert TerrainGL.falls_bottom(66.0, -700.0) <= -700.0 - TerrainGL.FALLS_DEPTH


def test_the_shaders_are_registered_and_the_fall_wraps_its_pattern():
    vert = shaders.DEFAULT_SHADERS['terrain_falls.vert']
    frag = shaders.DEFAULT_SHADERS['terrain_falls.frag']
    assert 'perimeter(' in vert and 'uTongueRows' in vert
    # Periodic noise along the perimeter: no seam where it closes.
    assert 'mod(i.x, n)' in frag and 'uPerimeter' in frag
    # Hidden behind the water, which writes no depth.
    assert 'uCamPos.y > uTop' in frag
    under = shaders.DEFAULT_SHADERS['terrain_under.vert']
    assert 'mirrorDepth' in under and 'nearShore' in under
    # The wall's foot fades its dark band where the underside hangs.
    assert 'mirrorDepth' in shaders.DEFAULT_SHADERS['terrain_skirt.vert']
    assert 'FootMirror' in shaders.DEFAULT_SHADERS['terrain_skirt.frag']


def test_the_underside_hangs_only_near_a_shore():
    size = 400.0
    # A ring of chunks round a 2000-wide world.
    world = [(x, z) for x in np.arange(-1000.0, 1000.0, size)
             for z in np.arange(-1000.0, 1000.0, size)]
    sizes = [size] * len(world)
    assert len(TerrainGL.under_slots(world, sizes, BOUNDS, ())) == 0
    picked = TerrainGL.under_slots(world, sizes, BOUNDS, [(1, 0.0)])
    xs = {world[i][0] for i in picked}
    # Only chunks by the +x edge (within the reach in from it).
    assert all(x + size > BOUNDS[1] - TerrainGL.UNDER_REACH for x in xs)
    assert max(xs) == 600.0


def test_water_flows_on_the_diagonals_too():
    for name in ('NE', 'NW', 'SE', 'SW'):
        x, z = WATER_FLOW_DIRECTIONS[name]
        assert math.isclose(math.hypot(x, z), 1.0)
    vx, vz = water_flow_velocity({'water_flow': 'se', 'water_flow_speed': 4.0})
    assert vx == pytest.approx(4.0 / math.sqrt(2.0))
    assert vz == pytest.approx(-4.0 / math.sqrt(2.0))


def _flow_clock():
    from engine.renderer.forward import passes
    owner = next(cls for cls in vars(passes).values()
                 if isinstance(cls, type) and hasattr(cls, 'water_flow_clock'))

    class Holder:
        water_flow_clock = owner.water_flow_clock
    return Holder()


def test_the_flow_clock_is_the_frame_time_at_a_steady_pace():
    holder = _flow_clock()
    for t in (0.0, 1.5, 3.0, 2.0, 10.0):
        assert holder.water_flow_clock(t) == pytest.approx(t)


def test_a_storm_quickens_the_flow_without_a_jump():
    holder = _flow_clock()
    assert holder.water_flow_clock(10.0) == pytest.approx(10.0)
    holder.water_flow_boost = 4.0
    # Picks up from where it was, then runs four times as fast.
    assert holder.water_flow_clock(11.0) == pytest.approx(14.0)
    holder.water_flow_boost = 1.0
    assert holder.water_flow_clock(12.0) == pytest.approx(15.0)
