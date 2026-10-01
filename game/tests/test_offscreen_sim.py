"""Off-screen NPCs under Big World's camera-fitted tiers.

When ``logic.sim_tiers_fit_view`` is set, TIER_ACTIVE means off screen: such an
NPC moves on one tick in OFFSCREEN_STRIDE, carrying the ticks it skipped, while
on-screen (NEAR) NPCs still move every tick. Without the flag ACTIVE may be on
screen and moves every tick.
"""

from __future__ import annotations

from engine.spatial import SIM_TIER_KEY, TIER_ACTIVE, TIER_NEAR

from .. import runtime
from .test_ember_tome import _FakePlayer, _FakeThing, _session


def _npc(name, tier):
    return _FakeThing([0, 272, 0], {"type": "npc", "name": name, "npc_role": "villager",
                                    "faction": "villagers", SIM_TIER_KEY: tier})


def _moves(fit, ticks=8, dt=1 / 60):
    near, off = _npc("Near", TIER_NEAR), _npc("Off", TIER_ACTIVE)
    s = _session([near, off], _FakePlayer([0, 272, 0]))
    s.logic.sim_tiers_fit_view = fit
    seen = {"Near": [], "Off": []}
    s._move = lambda npc, delta: seen[npc.properties["name"]].append(delta)
    for _ in range(ticks):
        s.tick(dt)
    return seen


def test_off_screen_npcs_move_in_strides_without_losing_time():
    seen = _moves(fit=True)
    stride = runtime.OFFSCREEN_STRIDE
    assert len(seen["Near"]) == 8
    assert len(seen["Off"]) == 8 // stride
    assert sum(seen["Off"]) == sum(seen["Near"])


def test_without_a_fitted_view_active_npcs_move_every_tick():
    seen = _moves(fit=False)
    assert len(seen["Off"]) == len(seen["Near"]) == 8
