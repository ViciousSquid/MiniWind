"""Stage 0: every shipped map's brushes behave exactly as recorded.

``tests/helpers/brush_semantics`` states what a brush dict means today --
its encoding, the faces the renderer draws (world-space polygon and
resolved material), the bound the bound-readers use -- and what its two
readings disagree on. ``semantics_snapshot.json`` records that for every
map in ``maps/``: a digest of the drawn faces and bounds, and the exact
inventory of inconsistencies per brush.

The unified brush model (``docs/brush-model-proposal.md``) changes how
brushes are stored, not what they draw. A stage that changes the meaning of
a shipped map must say so: it regenerates the snapshot in the same commit
(``python tools/brush_semantics_snapshot.py --write``) and names the change.
Nothing here is GL: it runs in the headless tier.
"""

import copy
import json

import pytest

from tests.helpers import brush_semantics as bs
from tests.helpers.paths import REPO_ROOT, repo_path

with open(repo_path('tests', 'brush_model', 'semantics_snapshot.json')) as _handle:
    RECORDED = json.load(_handle)

MAPS = bs.shipped_maps(REPO_ROOT)

#: MiniWind ships its own maps, not Fio's: the fixture records those, and the
#: inventory below is ``miniwind_world``'s (the caves and the Big World test
#: map are boxes throughout and carry nothing).
WORLD = 'miniwind_world.json'
#: Convex brushes whose authored per-tag value Stage 1 draws.
WALL_SCALED = '0ce48c9d-d122-49ad-b3ff-2147acdbfbc7'
SLAB_SCALED = '213d70aa-31b4-4205-afab-22736d34007a'
WALL_TURNED = '2cb2ca41-8ad0-4d45-83fd-ead8209be8f0'
TABLE_TURNED = '4002ca0e-f7a1-49ec-b291-8cf3dbf9bd60'
#: The roof whose stored ``pos`` is 4928 units from its planes.
ROOF_STALE = 'e23ac095-195e-4d67-9770-ab3c33fb3e1b'

REGENERATE = ("if this change is deliberate, regenerate with "
              "`python tools/brush_semantics_snapshot.py --write` and name it "
              "in docs/brush-model-proposal.md")


def test_every_shipped_map_is_recorded():
    assert sorted(MAPS) == sorted(RECORDED), REGENERATE


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_a_shipped_map_draws_what_was_recorded(name):
    recorded = RECORDED[name]
    current = bs.map_snapshot(MAPS[name])
    assert current['encodings'] == recorded['encodings'], REGENERATE
    assert current['inconsistencies'] == recorded['inconsistencies'], REGENERATE
    assert current['digest'] == recorded['digest'], (
        "%s: the drawn faces, materials or bounds changed; %s" % (name, REGENERATE))


def test_the_recorded_inventory_is_the_known_one():
    """The inventory in words, so a reader need not decode the fixture.

    None. ``miniwind_world`` held all of it (a roof whose ``pos`` was 4928
    units off its planes, four brushes whose per-tag ``uv_scale``/``uv_angle``
    was not on their planes, three whose per-tag ``texture`` was discarded)
    until it was re-saved as a version-5 map: one material record a face,
    ``pos`` at the planes' centre. The caves are box brushes, which carry
    none of these. No MiniWind map was saved with a mover mid-motion.
    """
    kinds = {}
    for name, entry in RECORDED.items():
        for found in entry['inconsistencies'].values():
            for kind in found:
                kinds.setdefault(kind, set()).add(name)
    assert kinds == {}


def test_the_digest_sees_a_visible_change_and_not_float_noise():
    """The oracle's own resolution: 1e-3 of a unit is a change, 1e-9 is not."""
    brushes = copy.deepcopy(MAPS['cave01.json'])
    base = bs.digest(brushes)
    box = next(b for b in brushes if bs.encoding(b) == 'box')
    box['pos'] = [box['pos'][0] + 1e-9] + list(box['pos'][1:])
    assert bs.digest(brushes) == base
    box['pos'] = [box['pos'][0] + 1e-3] + list(box['pos'][1:])
    assert bs.digest(brushes) != base
    box['pos'] = [box['pos'][0] - 1e-3] + list(box['pos'][1:])
    textures = box.setdefault('textures', {})
    textures['top'] = 'Dev/elsewhere.jpg'
    assert bs.digest(brushes) != base
