"""The water's sky clouds (engine/sky_clouds.py): baked once, off the main
thread, a seamless texture."""

import time

import numpy as np

from engine import sky_clouds


def test_the_clouds_tile_and_carry_their_light_channels():
    a = sky_clouds.bake(size=128)
    assert a.shape == (128, 128, 4) and a.dtype == np.uint8
    # Seamless: the last column runs into the first as any two neighbours do.
    edge = np.abs(a[:, -1, 0].astype(int) - a[:, 0, 0].astype(int)).mean()
    inner = np.abs(np.diff(a[:, :, 0].astype(int), axis=1)).mean()
    assert edge < inner * 3 + 2
    assert a[..., 0].std() > 20                       # real cloud, not flat
    assert not np.array_equal(a[..., 0], a[..., 1])   # lit from one side


def test_it_bakes_on_its_own_thread_and_is_ready_after():
    sky_clouds._baked, sky_clouds._baking = None, None
    sky_clouds.prepare()
    assert sky_clouds._baking is not None
    deadline = time.monotonic() + 10
    while sky_clouds.ready() is None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert sky_clouds.ready() is not None and sky_clouds.ready().shape == (512, 512, 4)
