"""Tundra heath, wheat through the seasons, and the biome map's fifth channel."""

import numpy as np

from engine import terrain_biomes as tb


def test_a_five_channel_map_round_trips_and_samples_tundra():
    m = np.zeros((8, 8, 5), np.uint8)
    m[..., tb.TUNDRA] = 255
    back = tb.decode(tb.encode(m))
    assert back.shape == (8, 8, 5)
    w = tb.sample(back, ((0, 100), (0, 100)), [50], [50])
    assert w.shape == (1, 5) and w[0, tb.TUNDRA] == 1.0
    # Four-channel maps are unchanged: four columns, no tundra.
    assert tb.sample(np.zeros((8, 8, 4), np.uint8), ((0, 100), (0, 100)), [50], [50]).shape == (1, 4)


def test_meadow_thins_under_tundra_and_the_ground_turns_russet():
    w = np.zeros((2, 5), np.float32)
    w[1, tb.TUNDRA] = 1.0
    keep = tb.grass_keep(w)
    assert keep[0] == 1.0 and keep[1] == 0.0
    ground = tb.blend_colors(np.full((2, 3), 0.4, np.float32), w)
    assert np.allclose(ground[0], 0.4) and not np.allclose(ground[1], 0.4)


def test_tundra_glows_in_drifts_of_flame_among_green():
    rng = np.random.default_rng(1)
    calm = tb.tundra_colours(rng, 4000, np.zeros(4000))
    drift = tb.tundra_colours(rng, 4000, np.ones(4000))
    flame = lambda c: np.mean(c[:, 0] > c[:, 1] + 0.15)
    assert flame(calm) < 0.2 < 0.5 < flame(drift)


def test_wheat_sprouts_grows_very_tall_ripens_is_cut_and_lies_bare():
    spring, summer, autumn = tb.wheat_stage(0.05), tb.wheat_stage(0.45), tb.wheat_stage(0.6)
    harvest, winter = tb.wheat_stage(0.72), tb.wheat_stage(0.9)
    assert spring[0] < summer[0] < autumn[0] == 1.0
    assert spring[1] == 0.0 < summer[1] <= autumn[1] == 1.0
    assert harvest[0] < 0.2 and winter[2] < autumn[2]
    assert tb.season_of(0.1) == "spring" and tb.season_of(0.8) == "winter"
    assert np.allclose(tb.wheat_stage(1.45), tb.wheat_stage(0.45))   # years repeat
    # Ripe wheat stands about shoulder high on a 100-unit player.
    assert tb.WHEAT_SIZE[1] * 5.0 >= 80.0


def test_no_grass_of_any_kind_on_sand_or_snow_even_at_their_edges():
    w = np.zeros((4, 5), np.float32)
    w[0, tb.DESERT] = 0.4
    w[1, tb.SNOW] = 0.34
    w[2, tb.SNOW] = 0.1
    keep = tb.bare_keep(w)
    assert keep[0] == 0.0 and keep[1] == 0.0 and 0.0 < keep[2] < 1.0 and keep[3] == 1.0
    assert (tb.grass_keep(w)[:2] == 0.0).all()
