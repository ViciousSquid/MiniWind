"""Stage 2a changes exactly the shipped bounds it names, and nothing drawn.

Stage 2a (derived bounds, ``docs/brush-model-stage2.md``) makes every
bound-reader -- culling, collision rows, the physics grid, Big World,
picking -- take a convex brush's bound from its planes instead of the
``pos``/``size`` copy the map stores. On MiniWind's shipped maps that copy
is right everywhere except one brush: ``miniwind_world``'s roof ``e23ac095``
stores the right size at a stale ``pos``, 2032 units along X and 4928 along
Z from where its planes are (and were always drawn). Its bound -- what
culling, collision rows, the physics grid and Big World's cells read -- is
now where the solid is. Nothing any shipped brush *draws* changes: the faces
(rings and materials) are identical, and so is every other bound beyond the
solver's last bits (``DRIFT_NOISE``). (Fio's own test names brushes of maps
MiniWind does not ship.)

The pre-Stage-2a reading of a bound is frozen below (``pos``/``size``);
the current reading is the helper. The pixel-level check of "nothing drawn
changes" is ``tools/compare_map_pixels.py``.
"""

import numpy as np
import pytest

from tests.helpers import brush_semantics as bs
from tests.helpers.paths import REPO_ROOT

MAPS = bs.shipped_maps(REPO_ROOT)

STALE_ROOF = 'e23ac095'

#: ``(map, brush id prefix) -> (stored centre, derived centre)``; the size
#: is the same in both.
INTENDED = {
    ('miniwind_world.json', STALE_ROOF): ((3632.0, 192.0, -8784.0),
                                          (1600.0, 192.0, -3856.0)),
}
SIZE = (944.0, 96.0, 928.0)


def _changed_bounds():
    out = {}
    for name, brushes in MAPS.items():
        for raw in brushes:
            brush = bs.migrated(raw)
            stored = tuple(map(np.asarray, bs.stored_bound(brush)))
            derived = tuple(map(np.asarray, bs.bound(brush)))
            drift = max(float(np.abs(stored[0] - derived[0]).max()),
                        float(np.abs(stored[1] - derived[1]).max()))
            if drift > bs.DRIFT_NOISE:
                out[(name, str(raw.get('id'))[:8])] = (stored, derived)
    return out


def test_only_the_named_bounds_change():
    changed = _changed_bounds()
    assert set(changed) == set(INTENDED)
    for key, (stored, derived) in changed.items():
        was, now = INTENDED[key]
        # The copy had the solid's size, somewhere else: only the centre moves.
        assert np.allclose(stored[0], was) and np.allclose(derived[0], now, atol=1e-9)
        assert np.allclose(stored[1], SIZE) and np.allclose(derived[1], SIZE, atol=1e-9)


@pytest.mark.parametrize("name", sorted(MAPS))
def test_no_shipped_brush_draws_differently(name):
    """The faces each brush draws -- world rings, posed, and materials --
    are the planes' (or the box's), whatever the stored copy says."""
    for raw in MAPS[name]:
        brush = bs.migrated(raw)
        for tag, ring, _material in bs.render_faces(brush):
            assert np.array_equal(bs.posed(brush, ring), np.asarray(ring)), (
                name, raw.get('id'), tag)
