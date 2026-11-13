"""The engine's whole-number health never calls a living character dead.

The character's health is a float; the engine keeps a whole number and calls
the player dead at 0. Rounding 0.4 down froze the world on a death MiniWind
did not know about (its death screen asks the character), so there was no
death screen, no way back to an autosave, and nothing to do but quit.
"""

from __future__ import annotations

from ..rpg.character import whole_health
from .test_quest_files import _session


def test_whole_health_rounds_but_never_shows_a_living_character_as_zero():
    assert whole_health(0.0) == 0
    assert whole_health(-3.0) == 0
    assert whole_health(0.01) == 1
    assert whole_health(0.4) == 1
    assert whole_health(0.6) == 1
    assert whole_health(1.4) == 1
    assert whole_health(57.5) == 58
    assert whole_health("nonsense") == 0


def test_a_sliver_of_health_keeps_the_engine_player_alive():
    session = _session([])
    session.begin_new_character("Tamsin", "imperial", "warrior", "warrior")
    c = session.game.character
    runtime = session.logic.player_runtime
    c.health = 0.4
    session._sync_engine_health()
    assert not c.is_dead
    assert runtime.player_health == 1, "the engine would call this player dead"
    c.health = 0.0
    session._sync_engine_health()
    assert c.is_dead and runtime.player_health == 0


def test_the_same_toast_is_not_stacked_while_it_is_still_showing():
    session = _session([])
    for _ in range(4):
        session.notify("No healing potions")
    session.notify("Sneaking")
    texts = [n["text"] for n in session.notifications]
    assert texts == ["No healing potions", "Sneaking"]
    for n in session.notifications:
        n["t"] = 0.0
    session.notifications[:] = [n for n in session.notifications if n["t"] > 0]
    session.notify("No healing potions")
    assert [n["text"] for n in session.notifications] == ["No healing potions"]


def test_a_closed_shop_says_when_it_opens():
    from .. import entities
    elowen = entities.NPC(pos=[0, 0, 0], properties={
        "name": "Elowen", "display_name": "Elowen the Trader", "npc_role": "merchant",
        "merchant": True, "flour_target": 8})
    session = _session([elowen])
    session.clock.hour = 8.1
    elowen.properties["opening_day"] = session.clock.day
    elowen.properties["opening_hour"] = 9.5
    assert session._shop_closed_text(elowen) == \
        "The shop is closed. Elowen the Trader opens at 09:30."
    session.clock.hour = 22.0
    assert session._shop_closed_text(elowen).endswith("opens at 09:30 tomorrow.")
