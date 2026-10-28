"""The prison is marked in the world while the game runs, and only then."""

from __future__ import annotations

import pytest

from .test_combat_ai import _FakeLogic, _FakePlayer

pytestmark = pytest.mark.qt


def test_a_prison_sign_stands_over_the_marker_in_play_and_goes_when_play_stops(qt_app):
    from ..entities import Marker
    from ..runtime import MiniwindSession, PRISON_SIGN_RISE
    from engine.entity_table import ENT_MODE_BILLBOARD, ENT_HAS_SPRITE, _entity_class_bits
    prison = Marker([500.0, 10.0, -300.0], {"name": "gaol", "marker_kind": "prison"})
    home = Marker([0.0, 0.0, 0.0], {"name": "home1", "marker_kind": "home"})
    before = dict(prison.properties)
    logic = _FakeLogic([prison, home], _FakePlayer([0, 0, 0]))
    s = MiniwindSession(logic, cfg={})
    s._show_prison_signs()
    s._show_prison_signs()                       # never two
    signs = [t for t in logic.things if t.properties.get("_prison_sign")]
    assert len(signs) == 1
    sign, = signs
    assert list(sign.pos) == [500.0, 10.0 + PRISON_SIGN_RISE, -300.0]
    assert sign.properties["sprite_path"].endswith("marker_prison.png")
    bits = _entity_class_bits(sign)
    assert bits & ENT_MODE_BILLBOARD and bits & ENT_HAS_SPRITE   # drawn in play
    assert prison.properties == before           # the marker itself is untouched
    s._remove_prison_signs()
    assert not [t for t in logic.things if t.properties.get("_prison_sign")]
