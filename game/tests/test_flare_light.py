"""Flare's light rides its bolt, then lingers where the bolt landed and fades."""

from types import SimpleNamespace

from game import fio
from game.rpg import magic
from game.runtime import BOLT_LIGHT_INTENSITY, BOLT_LIGHT_RADIUS, BOLT_LINGER_FADE, MiniwindSession
from .test_cast_controls import _Logic, _Thing


def _session_with_bolt(spell, monkeypatch):
    s = MiniwindSession(_Logic([_Thing("Rock", (0, 0, 0), type="prop")]), cfg={})
    monkeypatch.setattr(fio, "projectile_tag", lambda logic, row: 7)
    monkeypatch.setattr(fio, "projectile_count", lambda logic: 1)
    s._attach_bolt_light(0, [0.0, 48.0, 0.0], spell)
    return s, s._bolt_lights[7]


def test_flare_lingers_twenty_seconds_and_grows_with_its_level():
    flare = magic.get("flare")
    assert flare.linger == 20.0
    top = flare.at_level(5)
    assert top.linger > flare.linger
    radius, bright = top.light_scale()
    assert 1.0 < radius < bright
    assert flare.light_scale() == (1.0, 1.0)
    assert magic.Spell.from_dict(top.to_dict()).linger == top.linger


def test_the_light_follows_the_bolt_then_stays_and_fades(monkeypatch):
    s, light = _session_with_bolt(magic.get("flare"), monkeypatch)
    # In flight: the light is moved onto the bolt (assigned, so drawn there).
    s._bolt_positions = {7: (300.0, 48.0, 50.0)}
    s._update_bolt_lights(0.016)
    assert light.pos == [300.0, 48.0, 50.0]
    # It lands: the light stays where the bolt was.
    s._bolt_positions = {}
    s._update_bolt_lights(0.016)
    assert light in fio.things(s.logic) and light.pos == [300.0, 48.0, 50.0]
    s._update_bolt_lights(19.9)
    assert light.properties["intensity"] == BOLT_LIGHT_INTENSITY
    s._update_bolt_lights(0.2)
    s._update_bolt_lights(BOLT_LINGER_FADE / 2)
    assert 0.0 < light.properties["intensity"] < BOLT_LIGHT_INTENSITY
    s._update_bolt_lights(BOLT_LINGER_FADE)
    assert light not in fio.things(s.logic) and not s._lingering_lights


def test_a_higher_level_flare_burns_wider_and_brighter(monkeypatch):
    _s, light = _session_with_bolt(magic.get("flare").at_level(4), monkeypatch)
    assert light.properties["radius"] > BOLT_LIGHT_RADIUS
    assert light.properties["intensity"] > BOLT_LIGHT_INTENSITY


def test_other_bolts_go_out_with_the_bolt(monkeypatch):
    s, light = _session_with_bolt(SimpleNamespace(color=[255, 0, 0]), monkeypatch)
    s._bolt_positions = {}
    s._update_bolt_lights(0.016)
    assert light not in fio.things(s.logic)
