"""Magic's visible effects as data (game/magic_fx.py), without a GL context."""

import numpy as np
import pytest

from .. import magic_fx as mf


class _Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def _fx(player=(0.0, 0.0, 0.0)):
    clock = _Clock()
    fx = mf.MagicFX(clock=clock, player_pos=lambda: player)
    return fx, clock


def _modes(sprites):
    return set(int(m) for m in sprites[:, 8])


def test_a_spell_looks_like_its_element_and_its_own_overrides():
    flare = mf.look_for("flare", (255, 140, 50), "fire")
    firebolt = mf.look_for("firebolt", (255, 140, 50), "fire")
    assert flare["trail"] == "embers" and flare["lens"] == 0.0
    assert firebolt["lens"] > 0.0 and firebolt["orb"] > flare["orb"]
    assert mf.look_for("lightning", None, "shock")["trail"] == "arcs"
    # An unknown element falls back to plain magic.
    assert mf.look_for("x", (1, 1, 1), "weird")["element"] == "magic"


def test_editor_visuals_override_the_look_and_bad_ones_are_dropped():
    look = mf.look_for("flare", None, "fire",
                       {"trail": "frost", "lens": 0.7, "sparks": "12", "rays": True,
                        "hit_tint": "nonsense", "orb": "huge", "unknown": 3})
    assert look["trail"] == "frost" and look["lens"] == 0.7
    assert look["sparks"] == 12 and look["rays"] is True
    assert look["hit_tint"] == "burn"          # the bad value kept the default
    assert look["orb"] == mf.ELEMENT_LOOKS["fire"]["orb"]


def test_a_cast_draws_a_rune_circle_under_the_feet():
    fx, _clock = _fx()
    fx.cast((0.0, 10.0, 0.0), mf.look_for("flare", None, "fire"))
    sprites, _lenses, _tints = fx.frame()
    runes = sprites[sprites[:, 8] == mf.RUNES]
    assert len(runes) == 1
    assert runes[0, 1] == pytest.approx(10.0 + mf.GROUND_LIFT)
    assert runes[0, 11] == 1.0                  # lying flat on the ground


def test_a_cast_can_be_set_to_show_no_circle():
    fx, _clock = _fx()
    fx.cast((0.0, 0.0, 0.0), mf.look_for("flare", None, "fire", {"cast": "none"}))
    assert not len(fx.frame()[0])


def test_heavy_impacts_bend_the_screen_light_ones_do_not():
    fx, clock = _fx()
    fx.impact((0.0, 48.0, 0.0), mf.look_for("flare", None, "fire"))
    assert fx.frame()[1] == []
    fx.impact((0.0, 48.0, 0.0), mf.look_for("lightning", None, "shock"))
    clock.t += 0.1
    sprites, lenses, _tints = fx.frame()
    assert len(lenses) == 1 and lenses[0][3] > 0.0
    assert {mf.FLASH, mf.RING, mf.MOTE, mf.RAYS} <= _modes(sprites)
    clock.t += 1.0
    assert fx.frame()[1] == []                   # the lens has passed


def test_resurrection_washes_the_screen_dark_red_for_three_seconds():
    fx, clock = _fx()
    fx.resurrection((50.0, 0.0, 0.0))
    for at, expect in ((0.1, 0.0), (1.0, 0.62), (2.0, 0.62), (2.8, 0.0)):
        clock.t = 100.0 + at
        tints = fx.frame()[2]
        assert tints and tints[0][2] == "blood"
        if expect:
            assert tints[0][1] == pytest.approx(expect)
        else:
            assert 0.0 < tints[0][1] < 0.62
    clock.t = 103.05
    assert fx.frame()[2] == []


def test_a_bolt_flies_with_an_orb_and_bursts_where_it_ends():
    fx, clock = _fx(player=(1000.0, 0.0, 0.0))
    look = mf.look_for("firebolt", None, "fire")
    fx.bolt(7, look)
    fx.track_bolts({7: ((0.0, 48.0, 0.0), (900.0, 0.0, 0.0))})
    sprites = fx.frame()[0]
    assert mf.ORB in _modes(sprites)
    clock.t += 0.1
    ended = fx.track_bolts({})
    assert ended and ended[0][0] == (0.0, 48.0, 0.0)
    sprites, lenses, tints = fx.frame()
    assert mf.ORB not in _modes(sprites) and mf.RING in _modes(sprites)
    assert lenses and not tints                  # the player was not hit


def test_a_hostile_bolt_ending_on_the_player_washes_the_screen():
    fx, _clock = _fx(player=(0.0, 0.0, 0.0))
    fx.bolt(3, mf.look_for("frostbite", None, "frost"), hostile=True)
    fx.track_bolts({3: ((30.0, 48.0, 0.0), (-900.0, 0.0, 0.0))})
    fx.track_bolts({})
    tints = fx.frame()[2]
    assert tints and tints[0][2] == "frost"


def test_effects_far_from_the_player_are_never_spawned():
    fx, _clock = _fx(player=(0.0, 0.0, 0.0))
    fx.impact((mf.FX_RADIUS + 10.0, 48.0, 0.0), mf.look_for("firebolt", None, "fire"))
    fx.heal((mf.FX_RADIUS + 10.0, 0.0, 0.0))
    sprites, lenses, _tints = fx.frame()
    assert not len(sprites) and not lenses


def test_live_particles_are_capped():
    fx, _clock = _fx()
    for _ in range(200):
        fx.impact((0.0, 48.0, 0.0), mf.look_for("disintegrate", None, "magic"))
    assert len(fx._p) <= mf.MAX_PARTICLES


def test_wards_are_drawn_as_bubbles_round_the_wearer():
    fx, _clock = _fx()
    fx.wards = lambda: [((5.0, 0.0, 5.0), (110, 190, 255), "shield")]
    sprites = fx.frame()[0]
    bubble = sprites[sprites[:, 8] == mf.BUBBLE]
    assert len(bubble) == 1 and bubble[0, 1] == pytest.approx(mf.BODY_LIFT)
    assert bubble[0, 3] == pytest.approx(mf.WARD_SIZE, rel=mf.WARD_PULSE + 1e-6)


def test_sparks_fly_and_fall():
    fx, clock = _fx()
    fx._burst((0.0, 100.0, 0.0), 30, (1, 1, 1), 400.0, 2.0, 10.0)
    start = fx.frame()[0][:, :3].copy()
    clock.t += 0.5
    later = fx.frame()[0][:, :3]
    assert np.abs(later - start).max() > 10.0


def test_a_ward_is_a_fisheye_lens_too():
    fx, _clock = _fx()
    fx.wards = lambda: [((5.0, 0.0, 5.0), (110, 190, 255), "shield")]
    lenses = fx.frame()[1]
    assert len(lenses) == 1
    x, y, z, strength, radius, rim, _colour, shimmer = lenses[0]
    assert (x, z) == (5.0, 5.0) and y == pytest.approx(mf.BODY_LIFT)
    assert strength > 0.3 and shimmer > 0.0
    assert radius == pytest.approx(mf.WARD_SIZE / 2, rel=mf.WARD_PULSE + 1e-6)
    assert rim == mf.WARD_RIM


def test_a_ward_gently_breathes():
    fx, clock = _fx()
    fx.wards = lambda: [((0.0, 0.0, 0.0), (110, 190, 255), "shield")]
    sizes = []
    for k in range(20):
        clock.t = 100.0 + k * 0.1
        sprites = fx.frame()[0]
        sizes.append(float(sprites[sprites[:, 8] == mf.BUBBLE][0, 3]))
    assert max(sizes) - min(sizes) > mf.WARD_SIZE * mf.WARD_PULSE
    assert max(sizes) <= mf.WARD_SIZE * (1 + mf.WARD_PULSE) + 1e-3
