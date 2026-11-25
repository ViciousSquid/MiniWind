"""The 2D views' 60 px icons for MiniWind's actors: the same picture a fresh
smooth rescale gives, scaled once per source sprite however often the views
ask."""

import pytest

pytest.importorskip("PyQt5")

pytestmark = pytest.mark.qt


def _bytes(pixmap):
    image = pixmap.toImage()
    return image.size(), bytes(image.constBits().asarray(image.sizeInBytes()))


def test_an_actors_icon_is_its_sprite_rescaled_once(monkeypatch):
    from PyQt5.QtCore import Qt
    from game import entities
    from game.entities import NPC, Creature

    monkeypatch.setattr(entities, "_ICON_PIXMAP_CACHE", {})
    for cls in (NPC, Creature):
        actor = cls(pos=[0.0, 0.0, 0.0])
        sprite = entities._actor_2d_pixmap(actor, icon=False)
        if sprite is None:
            pytest.skip("actor art is not installed")
        fresh = sprite.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        first = actor.get_icon_pixmap()
        again = cls(pos=[5.0, 0.0, 5.0], properties=dict(actor.properties)).get_icon_pixmap()
        assert _bytes(first) == _bytes(fresh)          # the same picture
        assert again is first                          # the same sprite: no rescale
