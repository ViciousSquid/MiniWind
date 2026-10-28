"""Rain washes exposed ground blood gradually without altering other gore."""

import pytest

from game.gore_fx import GoreFX, POOL_SPREAD, RAIN_WASH_SECONDS, SPLAT_FADE, SPLAT_LIFE


def _blood():
    clock = [100.0]
    gore = GoreFX(clock=lambda: clock[0])
    gore._splat((0., 0., 0.), 30.)
    return gore, gore.splats[0], clock


def test_rain_fades_ground_blood_then_removes_it():
    gore, splat, _ = _blood()
    assert gore.wash(RAIN_WASH_SECONDS / 2., 1.) == 0
    assert gore.splat_alpha(splat) == pytest.approx(.5)
    assert gore.wash(RAIN_WASH_SECONDS / 2., 1.) == 1
    assert not gore.splats


def test_heavier_rain_washes_faster_and_dry_intervals_keep_progress():
    light, light_splat, _ = _blood()
    heavy, heavy_splat, _ = _blood()
    light.wash(20., .25)
    heavy.wash(20., 1.)
    assert heavy.splat_alpha(heavy_splat) < light.splat_alpha(light_splat)
    before = heavy.splat_alpha(heavy_splat)
    heavy.wash(200., 0.)
    assert heavy.splat_alpha(heavy_splat) == before
    heavy.wash(RAIN_WASH_SECONDS - 20., 1.)
    assert not heavy.splats


def test_sheltered_or_distant_ground_blood_does_not_wash():
    gore, sheltered, _ = _blood()
    gore._splat((100., 0., 0.), 30.)
    exposed = gore.splats[-1]
    gore.wash(RAIN_WASH_SECONDS, 1., exposed=lambda splat: splat["x"] > 0.)
    assert gore.splats == [sheltered]
    assert gore.splat_alpha(sheltered) == 1.
    assert gore.splat_alpha(exposed) == 0.


def test_rain_does_not_change_flying_droplets_or_screen_blood():
    gore, _, _ = _blood()
    gore._spray((0., 0., 0.), 5, 10., None, size=(2., 3.))
    gore.hurt(.5)
    particles, _, screen = gore.snapshot()
    gore.wash(RAIN_WASH_SECONDS, 1.)
    assert gore.particles == particles
    assert gore.screen == screen


def test_rain_preserves_pool_spreading_and_natural_drying():
    gore, _, clock = _blood()
    gore.kill((0., 0., 0.))
    pool = gore.splats[-1]
    early = gore.splat_size(pool)
    gore.wash(10., 1.)
    clock[0] += POOL_SPREAD
    assert gore.splat_size(pool) > early
    assert pool["t0"] == 100.
    clock[0] = 100. + SPLAT_LIFE - SPLAT_FADE / 2.
    assert gore.splat_alpha(pool) == pytest.approx(.5 * (1. - 10. / RAIN_WASH_SECONDS))


def test_stamping_receives_the_splats_accumulated_rain_exposure():
    gore, _, _ = _blood()
    stamped = []
    gore.stamp = lambda splat: stamped.append(splat) or True
    gore.wash(12., 1.)
    gore.update()
    assert stamped[0]["rain_wash"] == 12.
    assert not gore.splats


@pytest.mark.parametrize("delta,rain", [(0., 1.), (-1., 1.), (20., 0.),
                                        (float("nan"), 1.), (1., float("inf"))])
def test_inactive_or_invalid_rain_does_not_touch_ground_blood(delta, rain):
    gore, splat, _ = _blood()
    before = dict(splat)
    assert gore.wash(delta, rain) == 0
    assert splat == before
