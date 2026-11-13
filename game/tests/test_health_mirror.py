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


def test_a_jump_covers_the_view_until_the_ground_is_built(monkeypatch):
    """A loaded save or a cave mouth puts the player where the terrain has not
    streamed in; the camera saw the clear colour (a blue void) until it did."""
    import game.fio as fio
    session = _session([])
    session.begin_new_character("Tamsin", "imperial", "warrior", "warrior")
    where = {"pos": [0.0, 0.0, 0.0]}
    ready = {"now": False}
    monkeypatch.setattr(session, "_player_pos", lambda: list(where["pos"]))
    terrain = type("T", (), {"view_ready": lambda self, x, z, r: ready["now"]})()
    monkeypatch.setattr(fio, "terrain", lambda logic: terrain)
    for _ in range(6):
        session._update_arrival()
    assert session.fade_alpha() == 255.0, "play starts covered until the ground is there"
    ready["now"] = True
    for _ in range(6):
        session._update_arrival()
    assert session.fade_alpha() < 255.0
    session._arrival["ready_at"] -= 10.0
    assert session.fade_alpha() == 0.0
    ready["now"] = False
    where["pos"] = [9000.0, 0.0, -5000.0]          # a jump
    session._update_arrival()
    assert session.fade_alpha() == 255.0
    where["pos"] = [9010.0, 0.0, -5000.0]          # walking on is not a jump
    ready["now"] = True
    for _ in range(6):
        session._update_arrival()
    session._arrival["ready_at"] -= 10.0
    assert session.fade_alpha() == 0.0


def test_the_quick_heal_key_eats_bread_when_the_potions_are_gone():
    from ..rpg import inventory as inv, items as rpg_items
    session = _session([])
    session.begin_new_character("Tamsin", "imperial", "warrior", "warrior")
    c = session.game.character
    c.inventory[:] = [s for s in c.inventory if "heal" not in str(s.get("id"))]
    c.health = 20.0
    assert not session.use_health_potion()
    inv.add_item(c.inventory, rpg_items.make("flour", 1))
    inv.add_item(c.inventory, rpg_items.make("bread", 2))
    assert session.use_health_potion()
    assert c.health == 28.0
    assert inv.quantity(c.inventory, "bread") == 1, "the cheaper food is eaten first"
    assert inv.quantity(c.inventory, "flour") == 1
    c.health = c.max_health
    assert not session.use_health_potion(), "not hurt: nothing eaten"
    assert inv.quantity(c.inventory, "bread") == 1
