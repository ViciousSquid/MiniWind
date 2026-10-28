"""Casting circles identify magic schools and never accompany mundane blows."""

from types import SimpleNamespace

import numpy as np
import pytest

from game import fio, magic_fx, warrior_fist
from game.rpg import equipment as eq, magic, skills
from game.rpg.character import Character
from .test_cast_controls import _Thing
from .test_spell_hands import _session


def _circles(session):
    sprites = session.magic_fx.frame()[0]
    return sprites[np.isin(sprites[:, 8], (magic_fx.RUNES, magic_fx.RING))]


@pytest.mark.parametrize("spell", list(magic.SPELLS.values()), ids=lambda spell: spell.id)
def test_registered_spell_runes_always_use_their_school_colour(spell):
    session = _session()
    look = session.spell_look(spell)
    session.magic_fx.cast((0., 0., 0.), look)
    circles = _circles(session)
    if spell.visuals.get("cast") == "none":
        assert not len(circles)
        return
    expected = (magic_fx.OCCULT_CAST_COLOUR if spell.school == skills.OFFENSIVE
                else magic_fx.DEFENSIVE_CAST_COLOUR)
    assert len(circles) == 1
    assert circles[0, 4:7] == pytest.approx(expected)
    assert look["colour"] == pytest.approx(np.asarray(spell.color) / 255.)


def test_authored_occult_spells_have_red_circles_even_with_a_yellow_projectile():
    look = magic_fx.look_for("new_spell", (255, 230, 20), "shock", school="occult")
    assert look["cast_colour"] == magic_fx.OCCULT_CAST_COLOUR
    assert look["colour"] == pytest.approx((1., 230 / 255., 20 / 255.))


@pytest.mark.parametrize("spell_id", ["heal_minor", "summon_wolf", "wisp"])
def test_self_spell_effect_rings_match_the_casting_school(spell_id):
    session = _session()
    spell = magic.get(spell_id)
    assert spell is not None
    session._magic_cast_fx(spell)
    circles = _circles(session)
    assert len(circles)
    assert np.allclose(circles[:, 4:7], magic_fx.cast_colour(spell.school))


def test_knock_draws_its_blue_casting_circle_on_success():
    session = _session()
    target = _Thing("Chest", (0., 0., 40.), type="container", locked=True)
    session.logic.things.append(target)
    session.game.character.known_spells.append("knock")
    assert eq.equip_spell(session.game.character, "knock", "main")
    session.game.cast_active_spell = lambda: SimpleNamespace(cast=True)
    assert session.do_cast(hand="main")
    assert not target.properties["locked"]
    circles = _circles(session)
    assert len(circles)
    assert np.allclose(circles[:, 4:7], magic_fx.DEFENSIVE_CAST_COLOUR)


def test_failed_casts_never_draw_a_casting_circle():
    session = _session()
    assert eq.equip_spell(session.game.character, "flare", "main")
    session.game.cast_active_spell = lambda: SimpleNamespace(cast=False, reason="not enough magicka")
    assert not session.do_cast(hand="main")
    assert not len(_circles(session))


@pytest.mark.parametrize("attack", ["melee", "bow", "shield", "fist"])
def test_physical_attacks_emit_no_spell_circle_or_yellow_fist_explosion(attack):
    session = _session()
    session._acquire_target = lambda *args, **kwargs: None
    if attack == "fist":
        session.game.character = Character.create("Brawler", "imperial", "warrior")
        assert warrior_fist.strike(session, 1.)
    else:
        item = {"melee": "iron_shortsword", "bow": "short_bow", "shield": "iron_shield"}[attack]
        assert eq.equip(session.game.character, item)
        if attack == "bow":
            session.game.fire_arrow = lambda **kwargs: True
            session._spawn_player_arrow_projectile = lambda **kwargs: None
        session.fire_player_weapon(session.logic, "secondary" if attack == "shield" else "primary")
    assert not len(_circles(session))
    assert all(t.properties.get("name") != "FistBlow" for t in fio.things(session.logic))
