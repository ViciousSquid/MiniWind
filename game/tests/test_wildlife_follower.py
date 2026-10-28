"""Raised creatures follow their caster instead of continuing to roam."""

import pytest

from game.entities import Creature
from game.rpg import equipment as eq
from game.rpg.character import Character
from game.runtime import MiniwindSession
from .test_cast_controls import _Logic


def _roamer():
    creature = Creature(pos=[0., 0., 100.], properties={
        "name": "Wolf", "npc_role": "wolf", "aggression": "passive",
        "roam": True, "_roam_dest": (1000., 100.),
    })
    session = MiniwindSession(_Logic([creature]), cfg={})
    session.game.character = Character.create("Caster", "imperial", "necromancer")
    session.needs_char_creation = False
    session.open_screen = None
    return session, creature


def test_a_raised_creature_abandons_its_old_roaming_destination():
    session, creature = _roamer()
    creature.properties.update(dead=True, health=0)
    assert eq.equip_spell(session.game.character, "resurrection", "main")
    assert session.do_cast(target=creature, hand="main")
    start = list(creature.pos)

    session.wildlife.update(1.)

    assert creature.pos == start
    assert "_roam_dest" not in creature.properties


@pytest.mark.parametrize("raised,following", [(False, False), (False, True), (True, False)])
def test_creatures_without_active_raised_loyalty_still_roam(raised, following):
    session, creature = _roamer()
    creature.properties.update(resurrection_used=raised, follow_player=following)

    session.wildlife.update(1.)

    assert creature.pos[0] > 0.
