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

    All of it is in ``miniwind_world``, on seven of its twelve convex brushes:

    * Bounds: one roof brush whose ``pos`` is not its planes' centre, by
      4928 units (six more are within 1e-6 and not pinned).
    * Material (Stage 1), drawn: four brushes whose authored per-tag
      ``uv_scale`` or ``uv_angle`` -- what the Surface Inspector showed -- is
      not on their planes. By the precedence rule it is their one record and
      is now drawn (``test_stage1_changes`` names the faces that change).
    * Material, discarded: three brushes whose per-tag ``texture`` differs
      from the texture on their planes, which is what was and is drawn.
    * Runtime keys: none; no MiniWind map was saved with a mover mid-motion.
    """
    kinds = {}
    for name, entry in RECORDED.items():
        for found in entry['inconsistencies'].values():
            for kind in found:
                kinds.setdefault(kind, set()).add(name)
    assert kinds == {
        'bound_drift': {WORLD},
        'resolved_from_tag': {WORLD},
        'discarded_tag_value': {WORLD},
    }
    world = RECORDED[WORLD]['inconsistencies']
    resolved = {bid: f['resolved_from_tag'] for bid, f in world.items()
                if 'resolved_from_tag' in f}
    every_scale = ['down.uv_scale', 'east.uv_scale', 'north.uv_scale',
                   'south.uv_scale', 'top.uv_scale', 'west.uv_scale']
    assert resolved == {
        WALL_SCALED: every_scale,
        SLAB_SCALED: ['top.uv_scale'],
        WALL_TURNED: ['east.uv_angle'],
        TABLE_TURNED: ['top.uv_angle'],
    }
    discarded = {bid for bid, f in world.items() if 'discarded_tag_value' in f}
    assert discarded == {'327f41c5-e697-43b0-90da-895d31f99deb', TABLE_TURNED,
                         'd3a40da8-565b-4e00-9fed-e390dcd4d98a'}
    drifts = {bid: f['bound_drift'] for bid, f in world.items() if 'bound_drift' in f}
    assert drifts == {ROOF_STALE: RECORDED[WORLD]['inconsistencies'][ROOF_STALE]['bound_drift']}
    assert drifts[ROOF_STALE] == pytest.approx(4928.0, abs=2.5)


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
