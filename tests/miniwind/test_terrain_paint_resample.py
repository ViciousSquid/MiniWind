"""Paint saved at another resolution is resampled exactly as a whole-chunk
bilinear pass would, though tiles no painted texel reaches are skipped
(``Terrain._resample_paint``)."""

import numpy as np
import pytest

from engine.terrain import Terrain


def _whole_chunk(paint, res):
    """The resampler as it was before tiles were skipped: every texel."""
    n = paint.shape[0]
    if n == res:
        return paint
    at = (np.arange(res, dtype=np.float32) + 0.5) * (n / float(res)) - 0.5
    i0 = np.clip(np.floor(at).astype(np.int64), 0, n - 1)
    i1 = np.clip(i0 + 1, 0, n - 1)
    f = np.clip(at - np.floor(at), 0.0, 1.0).astype(np.float32)
    src = paint.astype(np.float32)
    src[..., :3] *= src[..., 3:4] / 255.0
    rows = src[i0] * (1.0 - f)[:, None, None] + src[i1] * f[:, None, None]
    out = rows[:, i0] * (1.0 - f)[None, :, None] + rows[:, i1] * f[None, :, None]
    alpha = out[..., 3:4]
    np.divide(out[..., :3] * 255.0, alpha, out=out[..., :3], where=alpha > 1e-3)
    out = np.clip(out + 0.5, 0, 255).astype(np.uint8)
    out[out[..., 3] == 0, :3] = 0
    return out


@pytest.mark.parametrize("n,res", [(128, 256), (64, 256), (128, 64), (32, 49), (16, 16)])
@pytest.mark.parametrize("unpainted", [0.0, 0.5, 0.95, 1.0])
def test_tiled_resample_matches_the_whole_chunk_pass(n, res, unpainted):
    rng = np.random.default_rng(n * 1000 + res + int(unpainted * 100))
    paint = rng.integers(0, 256, (n, n, 4), dtype=np.uint8)
    paint[rng.random((n, n)) < unpainted, 3] = 0
    assert np.array_equal(Terrain._resample_paint(paint, res), _whole_chunk(paint, res))


def test_a_painted_stroke_across_tile_borders_matches():
    paint = np.zeros((128, 128, 4), dtype=np.uint8)
    for i in range(128):                        # a diagonal road, as shipped
        paint[i, max(0, i - 2):i + 3] = (140, 110, 70, 255)
    paint[60:68, :, 3] = 90                     # a soft band across every tile
    assert np.array_equal(Terrain._resample_paint(paint, 256), _whole_chunk(paint, 256))


def test_an_unpainted_chunk_resamples_to_zeros():
    out = Terrain._resample_paint(np.zeros((128, 128, 4), dtype=np.uint8), 256)
    assert out.shape == (256, 256, 4) and not out.any()
