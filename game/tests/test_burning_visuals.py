"""Flare's persistent flames share the dragon's standard FIRE visuals."""

from types import SimpleNamespace

from engine.effect_entity import EFFECT_DEFAULTS

from .. import burning
from ..dragon_fire import DEFAULT_SETTING, fire_texture


class _FlameFX:
    def __init__(self):
        self.calls = []

    def flames(self, *args):
        self.calls.append(args)


def _scene():
    things = []
    logic = SimpleNamespace(editor_state=SimpleNamespace(things=things))
    fx = _FlameFX()
    session = SimpleNamespace(
        logic=logic,
        magic_fx=fx,
        _player_pos=lambda: None,
        _things_of_type=lambda _kind: (),
    )
    return burning.Burning(session), things, fx


def _assert_dragon_fire_visuals(effect):
    assert effect is not None, "Flare must create an engine FIRE Effect"
    props = effect.properties
    assert props["effect_type"] == "FIRE"
    assert props["fire_texture"] == fire_texture(DEFAULT_SETTING)
    assert props["fire_texture"] == "assets/textures/effects/fire02.gif"
    for key in ("colour", "light_enabled", "light_radius", "light_colour", "light_intensity"):
        assert props[key] == EFFECT_DEFAULTS[key]


def test_flare_ground_fire_is_fire02_without_extra_magic_flames():
    fires, things, fx = _scene()
    fires.start_fire([10.0, 80.0, 20.0], dps=2.0, seconds=5.0)
    flame = fires.fires[0]["flame"]
    assert flame in things
    _assert_dragon_fire_visuals(flame)

    fires.update(0.1)
    assert fx.calls == [], "Do not layer procedural magic flames over the FIRE GIF"
    assert flame in things
    assert fires.fires[0]["left"] > 0

    fires.update(burning.GROUND_FIRE_SECONDS)
    assert flame not in things and not fires.fires


def test_flare_burning_actor_follows_with_fire02_and_no_extra_flames():
    fires, things, fx = _scene()
    actor = SimpleNamespace(
        pos=[0.0, 100.0, 0.0],
        properties={"sprite_height": 112.0, "dead": False},
    )
    fires.ignite(actor, dps=2.0, seconds=5.0)
    flame = fires.burns[id(actor)]["flame"]
    assert flame in things
    _assert_dragon_fire_visuals(flame)

    actor.pos = [25.0, 120.0, 35.0]
    fires.update(0.1)
    assert flame.pos == [25.0, 120.0 - 112.0 * burning.BODY_FLAME_LIFT, 35.0]
    assert fx.calls == [], "The moving burn must still use only the FIRE Effect"
    assert flame.properties["light_intensity"] == EFFECT_DEFAULTS["light_intensity"]

    fires.clear()
    assert flame not in things
