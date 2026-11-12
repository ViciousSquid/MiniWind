"""A sprite recipe resolves to the first candidate whose image exists.

``load_texture`` answers a missing file with the white default texture. The
eight-view monster recipes list a directional file first (``head_3.png``) and
the image the monster really has after it, so taking the first answer drew
every monster with a single custom image -- all of MiniWind's cast -- as a
white square.
"""

import os

from engine.entity_table import _monster_sprite_candidates
from engine.renderer.core.tables import TablesMixin


class _Resolver(TablesMixin):
    DEFAULT = 4

    def __init__(self, existing):
        self.sprite_textures = {}
        self.loaded = []
        self._existing = {os.path.join('assets', *name.split('/')): tex
                          for name, tex in existing.items()}

    def load_texture(self, filename, subfolder):
        self.loaded.append((filename, subfolder))
        return self._existing.get(os.path.join('assets', subfolder, filename), self.DEFAULT)


def _resolve(monkeypatch, existing, props, rotation):
    resolver = _Resolver(existing)
    monkeypatch.setattr('engine.asset_archives.asset_exists',
                        lambda path: os.path.normpath(path) in
                        {os.path.normpath(p) for p in resolver._existing})
    return resolver, resolver._resolve_sprite_recipe(
        _monster_sprite_candidates(props, rotation))


def test_a_single_custom_image_serves_every_view(monkeypatch):
    props = {'monster_type': 'human', 'custom_idle': 'assets/sprites/heads/mara.png'}
    for rotation in range(1, 9):
        resolver, tex = _resolve(
            monkeypatch, {'sprites/heads/mara.png': 77}, props, rotation)
        assert tex == 77
        assert ('mara_%d.png' % rotation, 'sprites/heads') not in resolver.loaded


def test_a_directional_image_is_preferred_when_it_exists(monkeypatch):
    props = {'monster_type': 'human', 'custom_idle': 'assets/sprites/heads/mara.png'}
    _resolver, tex = _resolve(
        monkeypatch, {'sprites/heads/mara.png': 77, 'sprites/heads/mara_3.png': 78},
        props, 3)
    assert tex == 78


def test_nothing_found_still_draws_the_default_texture(monkeypatch):
    props = {'monster_type': 'nobody', 'custom_idle': 'assets/sprites/heads/gone.png'}
    _resolver, tex = _resolve(monkeypatch, {}, props, None)
    assert tex == _Resolver.DEFAULT


def test_a_custom_image_is_not_replaced_by_a_builtin_directional_view(monkeypatch):
    # The stock eight-view soldier exists; the actor's own single image must
    # still be what every view shows.
    props = {'monster_type': 'human', 'custom_idle': 'assets/sprites/heads/mara.png'}
    existing = {'sprites/heads/mara.png': 77}
    existing.update({'sprites/monsters/human/idle_%d.png' % n: 100 + n for n in range(1, 9)})
    for rotation in range(1, 9):
        _resolver, tex = _resolve(monkeypatch, existing, props, rotation)
        assert tex == 77


def test_a_view_of_a_custom_set_still_falls_back_to_the_builtin_direction(monkeypatch):
    # Upstream's rule for a custom eight-view set with a view missing.
    props = {'monster_type': 'human', 'custom_idle': 'assets/sprites/monsters/custom_1.png'}
    existing = {'sprites/monsters/custom_1.png': 77, 'sprites/monsters/human/idle_5.png': 105}
    _resolver, tex = _resolve(monkeypatch, existing, props, 5)
    assert tex == 105
