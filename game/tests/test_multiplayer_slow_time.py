"""Slow Time in co-op (game/slow_time.py): one record for the world, however
many sessions share it. The world slows once (never below half speed); every
caster -- the host's player, another player, an NPC -- keeps their own speed
for their own spell and wears their own bubble and light; the world stays
slow until the last spell ends; everyone, a network client included, sees
every bubble, and the greyscale covers everything outside all of them."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest

from game import fio
from game.multiplayer.model import InputFrame
from game.tests.test_multiplayer_integration import coop_game  # noqa: F401 - shared runtime fixture


@pytest.fixture
def later(monkeypatch):
    """Real time, with a jump forward the test can add (the running game
    keeps its own clocks)."""
    real = time.monotonic
    offset = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: real() + offset[0])
    return offset


def _party(coop_game):
    coop = coop_game.logic.game_session.coop
    p1, p2 = list(coop.players.values())[:2]
    assert p1.session is coop.root and p2.session is not coop.root
    return coop, p1, p2


def _rate(coop, body):
    return fio.actor_time_rate(coop.logic, body)


def _bubbles_round(session, *bodies):
    """Whether *session*'s bubbles include one round each of *bodies*."""
    centres = [(lens[0], lens[2]) for lens in session.slow_time_lenses()]
    return all(any(abs(x - b.pos[0]) < 1.0 and abs(z - b.pos[2]) < 1.0
                   for x, z in centres) for b in bodies)


def _settle(later, seconds=0.5):
    later[0] += seconds                          # past the bubbles' fade-in


def test_another_players_cast_slows_the_real_world_and_only_they_are_exempt(
        coop_game, later):
    """Regression: player 2's session runs over an adapter of the world; its
    cast set the speed and the clock rate on the adapter, so the world was
    never slowed and nobody saw the bubble."""
    coop, p1, p2 = _party(coop_game)
    world = coop.logic
    assert p2.session.slow_time(1) == pytest.approx(5.0)
    assert world.time_scale == pytest.approx(0.5)
    assert "time_scale" not in vars(p2.session.logic)
    assert "actor_time_rates" not in vars(p2.session.logic)
    assert _rate(coop, p2.physics) == pytest.approx(2.0)
    assert _rate(coop, p1.physics) == 1.0
    assert p1.session.slow_time_casters() == [p2.physics]
    _settle(later)
    for player in (p1, p2):
        assert _bubbles_round(player.session, p2.physics)
        assert player.session.slow_time_tint() == pytest.approx(1.0)
    assert len(p2.session.slow_time_lights()) == 1
    assert p2.session.slow_time_lights()[0] in fio.things(world)
    coop.root.end_slow_time()


def test_the_caster_moves_twice_as_far_a_slowed_tick(coop_game, later):
    coop = coop_game.logic.game_session.coop
    p2, p3 = list(coop.players.values())[1:3]    # neither on the keyboard
    p2.session.slow_time(10)
    starts = [list(p.physics.pos) for p in (p3, p2)]
    for p in (p3, p2):
        coop.local_input(p.player_id, InputFrame(1, 0))
    coop_game.step(10)
    moved = [abs(p.physics.pos.x - s[0]) for p, s in zip((p3, p2), starts)]
    assert moved[0] > 1.0
    assert moved[1] > 1.6 * moved[0]
    coop.root.end_slow_time()


def test_two_players_both_exempt_the_world_slowed_once_each_ends_alone(
        coop_game, later):
    coop, p1, p2 = _party(coop_game)
    world = coop.logic
    world.time_scale = 1.0
    coop.root.slow_time(1)                       # player 1 (the host): 5 s
    later[0] += 1.0
    p2.session.slow_time(10)                     # player 2: 10 s
    assert world.time_scale == pytest.approx(0.5)        # never a quarter
    coop_game.step(3)                            # the root's tick holds it
    assert world.time_scale == pytest.approx(0.5)
    assert _rate(coop, p1.physics) == pytest.approx(2.0)
    assert _rate(coop, p2.physics) == pytest.approx(2.0)
    _settle(later)
    for player in (p1, p2):
        assert _bubbles_round(player.session, p1.physics, p2.physics)
    assert len(coop.root.slow_time_lights()) == 2
    later[0] += 4.0                              # player 1's spell is over
    coop_game.step(1)
    assert _rate(coop, p1.physics) == 1.0
    assert _rate(coop, p2.physics) == pytest.approx(2.0)
    assert world.time_scale == pytest.approx(0.5)
    assert coop.root.slow_time_casters() == [p2.physics]
    assert len(coop.root.slow_time_lights()) == 1
    later[0] += 6.0                              # and player 2's
    coop_game.step(1)
    assert world.time_scale == pytest.approx(1.0)
    assert _rate(coop, p2.physics) == 1.0
    assert coop.root.slow_time_casters() == [] and coop.root.slow_time_lights() == []


def test_a_players_spell_ends_when_they_fall(coop_game, later):
    coop, p1, p2 = _party(coop_game)
    coop.root.slow_time(1)
    p2.session.slow_time(1)
    p2.session.game.character.health = 0
    assert p2.session.game.character.is_dead
    coop.root._update_slow_time()
    assert coop.root.slow_time_casters() == [p1.physics]
    assert _rate(coop, p2.physics) == 1.0
    coop.root.end_slow_time()


def test_an_npc_and_a_player_cast_both_exempt(coop_game, later):
    from game.tests.test_multiplayer_integration import _replicated_npc
    coop, p1, p2 = _party(coop_game)
    mage = _replicated_npc(coop)
    coop.root.slow_time(8, caster=mage)
    p2.session.slow_time(1)
    assert coop.logic.time_scale == pytest.approx(0.5)
    assert _rate(coop, mage) == pytest.approx(2.0)
    assert _rate(coop, p2.physics) == pytest.approx(2.0)
    assert _rate(coop, p1.physics) == 1.0
    coop.root.end_slow_time()
    assert _rate(coop, mage) == 1.0 and coop.logic.time_scale == pytest.approx(1.0)


def test_ending_it_from_any_session_ends_every_spell_on_the_world(coop_game, later):
    """Leaving the map (uninstall's end_slow_time) clears every caster's
    spell, clock and light, whichever session asks."""
    coop, p1, p2 = _party(coop_game)
    coop.root.slow_time(1)
    p2.session.slow_time(1)
    lights = coop.root.slow_time_lights()
    p2.session.end_slow_time()
    assert coop.logic.time_scale == pytest.approx(1.0)
    assert coop.root.slow_time_casters() == []
    assert fio.actor_time_rates(coop.logic) == {}
    assert not any(light in fio.things(coop.logic) for light in lights)


def test_a_client_sees_every_bubble_and_its_own_caster_keeps_its_speed(
        coop_game, later, monkeypatch):
    """The world frame carries the casts by identity: a client rebuilds them,
    draws both bubbles with grey outside them, leaves its own world's speed
    alone (the host's world is what it shows) and predicts its caster's steps
    at full speed, everyone else's at half."""
    import game.host as host
    from game.multiplayer.replication import apply, capture
    from game.tests.test_multiplayer_integration import _replicated_npc
    from game.ui import magic_gl

    coop, p1, p2 = _party(coop_game)
    mage = _replicated_npc(coop)
    p2.session.slow_time(10)
    coop.root.slow_time(10, caster=mage)
    _settle(later)
    frame = json.loads(json.dumps(capture(coop)))        # over the wire
    sent = frame["slow_time"]["casts"]
    assert [c["id"] for c in sent] == ["player:" + p2.player_id, mage.properties["id"]]
    assert all(9.0 < c["left"] <= 10.0 for c in sent)
    # The client's own world: unslowed, with no record of its own yet.
    coop.root.end_slow_time()
    assert coop.logic.time_scale == pytest.approx(1.0)
    coop.authority = False
    try:
        apply(coop, frame)
        record = coop.root.slow_time_record()
        assert record.remote and record.casters() == [p2.physics, mage]
        assert coop.logic.time_scale == pytest.approx(1.0)
        assert fio.actor_time_rates(coop.logic) == {}
        for player in (p1, p2):
            assert _bubbles_round(player.session, p2.physics, mage)
            assert player.session.slow_time_tint() == pytest.approx(1.0)
        assert coop.root.slow_time_left() == pytest.approx(sent[0]["left"], abs=0.05)
        # The GL pass: both bubbles, grey outside them.
        drawn, greys = [], []
        monkeypatch.setattr(magic_gl, "draw_lenses", lambda p, v, lenses, grey=0.0: (
            drawn.append(list(lenses)), greys.append(grey)))
        monkeypatch.setattr(magic_gl, "draw_sprites", lambda *a, **k: 0)
        game = host.MiniwindGame.__new__(host.MiniwindGame)
        game._host = SimpleNamespace(logic=SimpleNamespace(_miniwind=coop.root))
        game._on_post_scene({"play_mode": True, "projection": None, "view": None})
        assert len([lens for lens in drawn[0] if len(lens) > 8 and lens[8] > 0.0]) == 2
        assert greys == [pytest.approx(1.0)]
        # Prediction: the caster at full speed, player 1 at half.
        steps = {}
        monkeypatch.setattr(coop, "_move_player",
                            lambda context, frame, delta: steps.setdefault(
                                context.player_id, delta))
        for p in (p1, p2):
            p.last_input = time.monotonic()
        coop.move_all(1 / 60)
        assert steps[p2.player_id] == pytest.approx(1 / 60)
        assert steps[p1.player_id] == pytest.approx(0.5 / 60)
        # The host's spells over: the next frame says so.
        frame = dict(frame, sequence=frame["sequence"] + 1, slow_time={"casts": []})
        apply(coop, frame)
        assert record.casters() == [] and coop.root.slow_time_lenses() == []
    finally:
        coop.authority = True
        coop.root.end_slow_time()
    assert not coop.root.slow_time_record().remote


def test_the_casters_light_reaches_clients_in_its_colour(coop_game, later):
    from game.multiplayer.replication import capture
    from game.slow_time import SLOW_TIME_COLOUR
    coop, p1, p2 = _party(coop_game)
    p2.session.slow_time(1)
    light = p2.session.slow_time_light()
    frame = capture(coop)
    sent = next(e for e in frame["entities"] if e["id"] == light.properties["id"])
    assert tuple(sent["props"]["colour"]) == SLOW_TIME_COLOUR
    coop.root.end_slow_time()
