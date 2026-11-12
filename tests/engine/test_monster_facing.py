"""One heading per actor: ``properties['angle']``, written only by
:mod:`engine.monster_facing`, journalled with the cheap FACING flag."""

import math
from types import SimpleNamespace

import pytest

from engine import change_journal, monster_facing
from engine.monster_facing import face_direction, heading, set_heading, turn_toward


def actor(angle=None):
    props = {} if angle is None else {'angle': angle}
    return SimpleNamespace(properties=props, pos=[0.0, 0.0, 0.0])


@pytest.fixture
def records(monkeypatch):
    seen = []
    monkeypatch.setattr(change_journal, 'touch',
                        lambda obj, flags=change_journal.STATE: seen.append(flags))
    return seen


def test_playerstart_convention_degrees_zero_along_plus_z(records):
    a = actor()
    turn_toward(a, 1.0, 0.0)
    assert a.properties['angle'] == pytest.approx(90.0)
    assert heading(a) == pytest.approx(math.pi / 2)
    turn_toward(a, 0.0, -1.0)
    assert a.properties['angle'] == pytest.approx(180.0)
    turn_toward(a, -1.0, 0.0)
    assert a.properties['angle'] == pytest.approx(270.0)
    assert records == [change_journal.FACING] * 3


def test_a_turn_is_journalled_once_and_a_non_turn_never(records):
    a = actor(90.0)
    set_heading(a, math.pi / 2)
    face_direction(a, (1.0, 5.0, 1e-9))       # round-off, not a turn
    turn_toward(a, 0.0, 0.0)                   # at rest: keep looking
    face_direction(a, (0.0, 1.0, 0.0))         # vertical: keep looking
    assert records == [] and a.properties['angle'] == 90.0
    set_heading(a, 0.0)
    assert records == [change_journal.FACING]


def test_without_a_turn_rate_the_turn_is_made_outright(records, monkeypatch):
    monkeypatch.setattr(monster_facing, 'TURN_RATE', None)
    a = actor(0.0)
    turn_toward(a, -0.2, -1.0, delta=0.016)
    assert heading(a) == pytest.approx(math.atan2(-0.2, -1.0) % (2 * math.pi))


def test_a_turn_rate_eases_the_short_way_round(records, monkeypatch):
    monkeypatch.setattr(monster_facing, 'TURN_RATE', 8.0)
    a = actor(0.0)
    turn_toward(a, -0.2, -1.0, delta=0.016)
    step = monster_facing.wrap(heading(a))
    assert 0.0 < abs(step) <= 8.0 * 0.016 + 1e-9
    # From just short of +180 degrees to just past it: a small turn, upward.
    b = actor(math.degrees(math.pi - 0.05))
    turn_toward(b, -0.05, -1.0, delta=0.016)
    assert abs(monster_facing.wrap(heading(b) - (math.pi - 0.05))) < 0.2
    # Within one step it arrives exactly.
    c = actor(0.0)
    turn_toward(c, 0.001, 1.0, delta=1.0)
    assert heading(c) == pytest.approx(math.atan2(0.001, 1.0))


def test_heading_reads_bad_or_missing_values_as_zero():
    assert heading(actor()) == 0.0
    assert heading(actor('north')) == 0.0
    assert heading(actor(None)) == 0.0


@pytest.mark.qt
def test_a_turn_refreshes_only_the_spin_in_both_render_buffers():
    from editor.things import Monster
    from engine.entity_table import EntityTable

    monster = Monster([0, 96, 0], {'angle': 90,
                                   'custom_idle': 'assets/sprites/heads/head_mara.png'})
    tables = [EntityTable(), EntityTable()]
    for table in tables:
        table.begin_frame([monster], epoch=1)
        assert tuple(table.sprite_spin[0]) == pytest.approx((math.pi / 2, 1.0))
    key = tables[0].sprite_key_id[0]
    face_direction(monster, (0, 0, -1))
    for table in tables:
        reads = table.rows_read
        table.begin_frame([monster], epoch=1)
        assert tuple(table.sprite_spin[0]) == pytest.approx((math.pi, 1.0))
        assert table.sprite_key_id[0] == key
        assert table.rows_read - reads <= 1
