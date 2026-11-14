"""Birthsigns give exactly what they say, and the Apprentice's weakness to
magic is real.

Run:  python -m pytest game/tests/test_birthsigns.py -q
"""

from __future__ import annotations

import random
import re

import pytest

from ..rpg import attributes as attr, birthsigns, combat, magic
from ..rpg.character import Character


def _made(sign, klass="mage"):
    return Character.create("S", "valian", klass, sign)


@pytest.mark.parametrize("sign_id", birthsigns.BIRTHSIGN_IDS)
def test_every_description_names_exactly_what_the_sign_gives(sign_id):
    """Measured, not read off the table: a character born under the sign
    against one born under none."""
    sign, plain, born = birthsigns.get(sign_id), _made("none"), _made(sign_id)
    desc = sign.desc
    named = set()
    for a in attr.ATTRIBUTES:
        d = born.attrs[a] - plain.attrs[a]
        if d:
            assert f"{d:+d} {attr.label(a)}" in desc
            named.add(attr.label(a))
    # ... and no attribute is named that the sign does not raise.
    for label in re.findall(r"[+-]\d+ ([A-Z][a-z]+)", desc):
        assert label in named
    for pool, gain in (("health", born.max_health - plain.max_health),
                       ("magicka", born.max_magicka - plain.max_magicka)):
        bonus = sign.stat_bonuses.get(pool, 0)
        if pool == "magicka":
            gain -= 1.5 * (born.attrs[attr.INTELLIGENCE] - plain.attrs[attr.INTELLIGENCE])
        if pool == "health":
            gain -= 2.0 * (born.attrs[attr.ENDURANCE] - plain.attrs[attr.ENDURANCE])
        assert gain == pytest.approx(bonus)
        assert (f"{int(bonus):+d} {pool}" in desc) == bool(bonus)
    for sp in set(born.known_spells) - set(plain.known_spells):
        assert magic.get(sp).name in desc
    damage = re.search(r"damage from ([a-z, ]+)", desc)
    weak = set(re.split(r", | and ", damage.group(1))) if damage else set()
    assert weak == {k for k, v in sign.resistances.items() if v < 0}


def test_the_offered_signs_read_as_they_give():
    gifts = {b: birthsigns.get(b).gifts() for b in birthsigns.CREATION_BIRTHSIGN_IDS}
    magic_note = " Magicka and spells only for a class that works magic."
    assert gifts == {
        "warrior": "+10 Strength, +5 Endurance.",
        "mage": "+10 Intelligence, +50 magicka." + magic_note,
        "thief": "+10 Endurance, +5 Speed, +5 Luck.",
        "lord": "+25 health, the Minor Healing spell." + magic_note,
        "shadow": "+5 Endurance, the Invisibility spell." + magic_note,
    }
    assert birthsigns.get("apprentice").gifts() == (
        "+5 Intelligence, +100 magicka, but 50% more damage from magic, fire, "
        "frost and shock." + magic_note)


@pytest.mark.parametrize("kind", birthsigns.SPELL_DAMAGE_KINDS)
def test_the_apprentice_takes_half_as_much_again_from_spells(kind):
    plain, apprentice = _made("none"), _made("apprentice")
    # The same Endurance, so only the sign differs (it raises Intelligence).
    assert plain.attrs[attr.ENDURANCE] == apprentice.attrs[attr.ENDURANCE]
    hit = combat.resolve_incoming(plain, 40.0, damage_kind=kind, rng=random.Random(1))
    worse = combat.resolve_incoming(apprentice, 40.0, damage_kind=kind,
                                    rng=random.Random(1))
    base = 40.0 * (1.0 - (plain.attrs[attr.ENDURANCE] * 0.002 if kind == "magic" else 0.0))
    assert hit["final"] == pytest.approx(base, abs=0.1)
    weak = 40.0 * (1.0 - (0.5 * -1 + (apprentice.attrs[attr.ENDURANCE] * 0.002
                                       if kind == "magic" else 0.0)))
    assert worse["final"] == pytest.approx(weak, abs=0.1)
    assert worse["final"] > hit["final"]


def test_the_apprentice_is_no_weaker_to_steel():
    plain, apprentice = _made("none"), _made("apprentice")
    for c in (plain, apprentice):
        c.equipment = {}
    a = combat.resolve_incoming(plain, 40.0, rng=random.Random(3), attack_bonus=99)
    b = combat.resolve_incoming(apprentice, 40.0, rng=random.Random(3), attack_bonus=99)
    assert a["final"] == b["final"]
