"""Falling off the world kills -- through god and buddha mode -- and a fall
never blows the body apart; an explosion's overkill still does."""
from types import SimpleNamespace

import pytest

from .test_corpse_loot import _Logic
from .test_sim import _FakeGlobals


class _Player:
    def __init__(self, y=2000.0):
        self.pos = [0.0, y, 0.0]
        self.velocity = [0.0, -800.0, 0.0]
        self.on_ground = False
        self.in_water = False
        self.physics_enabled = True
        self.void_handler = None


def _session(y=2000.0):
    from ..runtime import MiniwindSession
    logic = _Logic([])
    logic.player = _Player(y)
    s = MiniwindSession(logic, cfg={}, globals_store=_FakeGlobals())
    s.needs_char_creation = False
    s.game.dice = None
    return s, logic.player


def _fall(s, player, distance, step=12.0):
    """Drop *player* *distance* units in steps of a 60 Hz tick at terminal speed."""
    s._watch_fall(1 / 60)
    fallen = 0.0
    while fallen < distance and not s.game.character.is_dead:
        player.pos[1] -= step
        fallen += step
        s._watch_fall(1 / 60)


def test_a_fall_of_more_than_2000_units_kills():
    from ..runtime import FATAL_FALL
    s, player = _session()
    _fall(s, player, FATAL_FALL - 50.0)
    assert not s.game.character.is_dead
    _fall(s, player, 100.0)
    assert s.game.character.is_dead
    assert s.death_message() == "Fell to their death"


def test_standing_swimming_and_teleports_start_a_fall_afresh():
    s, player = _session()
    _fall(s, player, 1500.0)
    player.on_ground = True                 # landed on a ledge
    s._watch_fall(1 / 60)
    player.on_ground = False
    _fall(s, player, 1500.0)
    assert not s.game.character.is_dead
    player.in_water = True                  # a deep lake
    _fall(s, player, 2500.0)
    assert not s.game.character.is_dead
    player.in_water = False
    s._watch_fall(1 / 60)
    player.pos[1] -= 5000.0                 # fast travel down a mountain
    s._watch_fall(1 / 60)
    assert not s.game.character.is_dead


def test_falling_out_of_the_world_is_a_death_not_a_trip_to_the_start():
    s, player = _session()
    s._watch_fall(1 / 60)
    assert player.void_handler == s._fell_out_of_world
    assert player.void_handler(player) is True       # the engine does not respawn
    assert s.game.character.is_dead


@pytest.mark.parametrize("mode", ["god_mode", "buddha_mode"])
def test_god_and_buddha_mode_do_not_survive_a_fatal_fall(mode):
    from ..runtime import FATAL_FALL
    s, player = _session()
    setattr(s.logic.player_runtime, mode, True)
    _fall(s, player, FATAL_FALL + 100.0)
    assert s.game.character.is_dead


def test_a_fall_never_gibs():
    s, player = _session()
    _fall(s, player, 3000.0)
    assert s.game.character.is_dead
    assert not s.player_body_gone()


def test_the_edge_trigger_kills_a_falling_player_without_gibbing():
    s, player = _session()
    s.logic.player_runtime.last_damage = ({"death_message": "Fell off the edge of the world"},
                                          "trigger", "physical")
    s._mitigate_incoming(1000.0)
    assert s.game.character.is_dead
    assert not s.player_body_gone()
    assert s.death_message() == "Fell off the edge of the world"


def test_an_explosions_overkill_still_gibs_the_player():
    s, player = _session()
    player.on_ground = True
    s.logic.player_runtime.last_damage = (None, "explosion", "physical")
    c = s.game.character
    s.store.set("fortune.escape_day", str(s.clock.day))   # today's lucky escape is spent
    s.game.dice = None
    s._dice_rng = SimpleNamespace(random=lambda: 0.0, randint=lambda a, b: b,
                                 uniform=lambda a, b: a, choice=lambda seq: seq[0])
    s._mitigate_incoming(c.max_health * 50.0)      # far past any armour
    assert c.is_dead
    assert s.player_body_gone()


@pytest.mark.parametrize("how", ["edge trigger", "fall"])
def test_the_lucky_escape_does_not_save_anyone_from_the_edge(monkeypatch, how):
    """The once-a-day lucky escape from a killing blow never stops a death by
    falling off the edge, even when it is certain."""
    import game.rpg.fortune as fortune
    from ..runtime import FATAL_FALL
    monkeypatch.setattr(fortune, "lucky_escape_chance", lambda c: 1.0)
    s, player = _session()
    if how == "edge trigger":
        s.logic.player_runtime.last_damage = ({"death_message": "x"}, "trigger", "physical")
        s._mitigate_incoming(1000.0)
    else:
        _fall(s, player, FATAL_FALL + 100.0)
    assert s.game.character.is_dead
    assert s.store.get("fortune.escape_day", "") in ("", "false")    # not spent


# -- a shield against an explosion -------------------------------------------
def _shield_bearer(angle=0.0):
    from ..rpg import items
    s, player = _session()
    player.angle = angle            # facing +z
    player.pos = [0.0, 0.0, 0.0]
    c = s.game.character
    from ..rpg import equipment as eq
    c.inventory = [items.make("iron_shield", 1), items.make("iron_longsword", 1)]
    assert eq.equip(c, "iron_longsword") and eq.equip(c, "iron_shield")
    s._blocking = True
    return s, player


def test_a_shield_raised_towards_a_blast_softens_it():
    from ..runtime import BLAST_BLOCK_DAMAGE, BLAST_BLOCK_PUSH
    from ..rpg import equipment as eq
    s, player = _shield_bearer()
    assert eq.shield(s.game.character) is not None
    assert s.blast_guard((0.0, 0.0, 300.0)) == (BLAST_BLOCK_DAMAGE, BLAST_BLOCK_PUSH)
    assert (BLAST_BLOCK_DAMAGE, BLAST_BLOCK_PUSH) == (0.95, 0.80)


@pytest.mark.parametrize("why", ["behind", "beside", "not blocking", "no stamina", "no shield"])
def test_a_shield_softens_only_a_blast_it_faces(why):
    s, player = _shield_bearer()
    centre = (0.0, 0.0, 300.0)
    if why == "behind":
        centre = (0.0, 0.0, -300.0)
    elif why == "beside":
        centre = (300.0, 0.0, 0.0)
    elif why == "not blocking":
        s._blocking = False
    elif why == "no stamina":
        s.game.character.stamina = 0
    else:
        from ..rpg import items
        s.game.character.equipment.pop(items.SLOT_SHIELD, None)
    assert s.blast_guard(centre) == (1.0, 1.0)


def test_an_explosion_is_not_a_blow_the_block_save_reduces(monkeypatch):
    import game.rpg.combat as combat
    s, player = _shield_bearer()
    seen = []
    real = combat.resolve_incoming
    monkeypatch.setattr(combat, "resolve_incoming",
                        lambda *a, **k: seen.append(k["blocking"]) or real(*a, **k))
    s.logic.player_runtime.last_damage = (None, "explosion", "physical")
    s._mitigate_incoming(10.0)
    s.logic.player_runtime.last_damage = (None, "attack", "physical")
    s._mitigate_incoming(10.0)
    assert seen == [False, True]
