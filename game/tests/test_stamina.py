"""Walking and running, paid for in stamina: the player's sprint and everyone else's."""

import math

import pytest

from .. import npc_stamina as ns
from ..rpg.character import SPRINT_STAMINA_PER_SECOND


# ------------------------------------------------------------ NPCs

def test_an_actor_runs_while_its_stamina_lasts_then_walks_winded():
    props = {"creature_level": 1}
    top = ns.max_stamina(props)
    t, dt = 0.0, 0.1
    assert ns.pace(props, t, True) == ns.RUN_SCALE
    ran = 0.0
    while ns.pace(props, t, True) == ns.RUN_SCALE:
        t += dt
        ran += dt
        assert ran < 60, "never tired"
    # Out of breath after about top / net cost seconds.
    assert ran == pytest.approx(top / ns.RUN_COST, abs=0.3)
    assert props["_winded"] and props["_speed_scale"] == 1.0
    # Walking, it gets its wind back, and runs again only past RECOVER_AT.
    t += (top * ns.RECOVER_AT) / ns.REGEN - 1.0
    assert ns.pace(props, t, True) == 1.0
    t += 1.5
    assert ns.pace(props, t, True) == ns.RUN_SCALE


def test_a_pause_between_asks_counts_as_rest():
    props = {}
    ns.pace(props, 0.0, True)
    # It last ran; ten seconds pass without it being asked (standing in melee).
    stamina = ns.stamina(props, 10.0)
    assert stamina == pytest.approx(ns.max_stamina(props))


def test_walking_costs_nothing_and_clears_the_pace():
    props = {}
    assert ns.pace(props, 0.0, False) == 1.0
    assert ns.stamina(props, 30.0) == ns.max_stamina(props)
    ns.walk(props)
    assert "_speed_scale" not in props


def test_an_authored_pool_is_used():
    assert ns.max_stamina({"max_stamina": 300}) == 300.0


# ------------------------------------------------------------ the player

class _Logic:
    def __init__(self):
        from types import SimpleNamespace
        self.player_runtime = SimpleNamespace(player=SimpleNamespace())


def _session():
    from types import SimpleNamespace
    from ..rpg.character import Character
    c = Character()
    c.stamina = c.max_stamina = 100.0
    s = SimpleNamespace(game=SimpleNamespace(character=c), logic=_Logic(),
                        sprint_held=True)
    from ..runtime import MiniwindSession
    s.SPRINT_RECOVER_AT = MiniwindSession.SPRINT_RECOVER_AT
    s._sprint = MiniwindSession._sprint.__get__(s)
    return s, c


def test_the_player_sprint_spends_stamina_and_winds_them():
    s, c = _session()
    t = 0.0
    while s._sprint(0.1):
        c.regen(0.1, True)
        t += 0.1
        assert t < 60
    assert t == pytest.approx(100.0 / SPRINT_STAMINA_PER_SECOND, abs=0.2)
    assert s.logic.player_runtime.player.sprint_allowed is False
    # Shift still held: a walk until 30% is back.
    while not s._sprint(0.1):
        c.regen(0.1, False)
    assert c.stamina >= 30.0
    assert s.logic.player_runtime.player.sprint_allowed is True


def test_walking_the_player_gets_stamina_back():
    s, c = _session()
    s.sprint_held = False
    c.stamina = 10.0
    assert not s._sprint(0.1)
    c.regen(1.0, False)
    assert c.stamina > 10.0
