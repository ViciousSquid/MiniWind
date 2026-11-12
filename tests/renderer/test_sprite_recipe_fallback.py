"""A sprite recipe resolves to the first candidate whose image exists.

``load_texture`` answers a missing file with the white default texture, so
taking the first answer drew an actor whose variant or shoot frame is missing
as a white square instead of falling back to the image it does have.
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


def _resolve(monkeypatch, existing, props):
    resolver = _Resolver(existing)
    monkeypatch.setattr('engine.asset_archives.asset_exists',
                        lambda path: os.path.normpath(path) in
                        {os.path.normpath(p) for p in resolver._existing})
    return resolver, resolver._resolve_sprite_recipe(_monster_sprite_candidates(props))


def test_a_custom_image_is_drawn(monkeypatch):
    props = {'monster_type': 'human', 'custom_idle': 'assets/sprites/heads/mara.png'}
    _resolver, tex = _resolve(monkeypatch, {'sprites/heads/mara.png': 77,
                                            'sprites/monsters/human/idle.png': 5}, props)
    assert tex == 77


def test_a_missing_variant_shoot_frame_falls_back_to_idle(monkeypatch):
    props = {'monster_type': 'human', 'variant': 'variant1', 'is_shooting': True}
    _resolver, tex = _resolve(monkeypatch, {'sprites/monsters/human/idle.png': 5}, props)
    assert tex == 5


def test_nothing_found_still_draws_the_default_texture(monkeypatch):
    props = {'monster_type': 'nobody', 'custom_idle': 'assets/sprites/heads/gone.png'}
    _resolver, tex = _resolve(monkeypatch, {}, props)
    assert tex == _Resolver.DEFAULT
