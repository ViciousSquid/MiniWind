"""AI target selection tolerates party actors still attaching to a new map."""

from argparse import Namespace

import pytest

pytest.importorskip("PyQt5")

from editor.things import Monster
from game.tests.test_multiplayer_integration import coop_game  # noqa: F401
from game.tools import soak
from tests.helpers.worlds import make_thing

pytestmark = [pytest.mark.qt, pytest.mark.integration]


def _hunter(game):
    hunter = make_thing(Monster, "hunter", (0, 64, 0), team="bandits",
                        aggression="hostile", combatant=True)
    assert game.logic.monster_ai._hunts_player(hunter)
    return hunter


@pytest.mark.parametrize("pending", [1, 4])
def test_ai_skips_party_members_whose_actors_are_not_attached(coop_game, pending):
    coop = coop_game.logic.game_session.coop
    players = list(coop.players.values())
    actors = [p.actor for p in players]
    hunter = _hunter(coop_game)
    try:
        for player in players[:pending]:
            player.actor = None
        coop.prepare_ai([hunter])
        target = hunter.properties.get("_aggro_target")
        if pending == len(players):
            assert target is None
        else:
            assert target in {id(actor) for actor in actors[pending:]}
    finally:
        for player, actor in zip(players, actors):
            player.actor = actor


def test_ai_keeps_actor_references_stable_during_target_selection(coop_game, monkeypatch):
    coop = coop_game.logic.game_session.coop
    players = list(coop.players.values())
    actors = [p.actor for p in players]
    hunter = _hunter(coop_game)
    nearest = min(actors, key=lambda a: (a.pos[0] - hunter.pos[0]) ** 2
                  + (a.pos[2] - hunter.pos[2]) ** 2)
    hunts = coop_game.logic.monster_ai._hunts_player

    def detached_after_snapshot(thing):
        for player in players:
            player.actor = None
        return hunts(thing)

    monkeypatch.setattr(coop_game.logic.monster_ai, "_hunts_player", detached_after_snapshot)
    try:
        coop.prepare_ai([hunter])
        assert hunter.properties["_aggro_target"] == id(nearest)
    finally:
        for player, actor in zip(players, actors):
            player.actor = actor


def test_ai_keeps_a_retaliating_monsters_specific_offender(coop_game):
    coop = coop_game.logic.game_session.coop
    hunter = _hunter(coop_game)
    offender = list(coop.players.values())[-1].actor
    hunter.properties["_aggro_target"] = id(offender)
    coop.prepare_ai([hunter])
    assert hunter.properties["_aggro_target"] == id(offender)


@pytest.mark.parametrize("category,message", [
    ("Error", "missing output"),
    ("MonsterAI", "Unhandled exception in update:\nTraceback (most recent call last):\n"
                  "AttributeError: actor is missing"),
])
def test_soak_fails_when_a_background_subsystem_reports_an_error(coop_game, monkeypatch,
                                                               category, message):
    monkeypatch.setattr(soak, "capture_debug_log", lambda sink: None)
    run = soak.Soak(Namespace(seed=1, mode="bots", threaded=True))
    run.logic, run.session = coop_game.logic, coop_game
    coop_game.publish()
    assert run.check(0)
    run.debug.append((0.0, category, message))
    assert not run.check(1), "a background AI exception must fail the soak"
    assert run.report["faults"][-1]["kind"] == "debug_error"
