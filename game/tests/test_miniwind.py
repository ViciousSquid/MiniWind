"""
Unit tests for the Miniwind RPG plugin's pure-logic core.

These exercise the systems that must be robust and deterministic — factions,
game time, schedules, inventory, dialogue and the runtime session's schedule/
combat/dialogue behaviour — without any Qt / OpenGL / editor dependency, so
they run in a headless CI the same way ``plugins/bigworld/tests`` do.

Run:  python -m pytest game/tests -q
or:   python -m game.tests.test_miniwind   (self-runner below)
"""

from __future__ import annotations

import os
import sys

# Allow running as a plain script from the repo root.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game import factions, schedule, inventory, gametime
from game.dialogue import DialogueRunner, DictStore


# --- factions --------------------------------------------------------------
def test_faction_relationships():
    assert factions.relationship("guards", "guards") == factions.FRIENDLY
    assert factions.relationship("player", "villagers") == factions.FRIENDLY
    assert factions.relationship("guards", "bandits") == factions.HOSTILE
    assert factions.relationship("bandits", "guards") == factions.HOSTILE  # symmetric
    assert factions.relationship("villagers", "wildlife") == factions.NEUTRAL
    assert factions.relationship("", "guards") == factions.NEUTRAL
    assert factions.is_hostile("player", "monsters")
    # overrides win over the built-in table
    ov = {("villagers", "guards"): factions.HOSTILE}
    assert factions.relationship("guards", "villagers", ov) == factions.HOSTILE


# --- per-role art wiring ---------------------------------------------------
def test_role_art_paths_and_files_exist():
    import os
    from game import entities
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    for role in ("villager", "guard", "bandit", "merchant", "wolf", "monster"):
        sp = entities.sprite_for(role)
        pr = entities.portrait_for(role)
        assert sp.endswith(f"/{role}.png") and pr.endswith(f"/{role}.png")
        # the generator must have produced the actual image files
        assert os.path.isfile(os.path.join(root, sp)), f"missing sprite {sp}"
        assert os.path.isfile(os.path.join(root, pr)), f"missing portrait {pr}"
    # unknown role falls back to villager art (never a broken path)
    assert entities.sprite_for("nonesuch").endswith("/villager.png")


def test_npc_gets_role_sprite_and_portrait():
    from game.entities import NPC, sprite_for, portrait_for
    guard = NPC(properties={"npc_role": "guard"})
    assert guard.properties["custom_idle"] == sprite_for("guard")
    assert guard.properties["portrait"] == portrait_for("guard")
    assert guard.properties["sprite_width"] == guard.properties["sprite_height"]
    # an authored sprite size is respected, not overwritten
    sized = NPC(properties={"npc_role": "bandit", "sprite_width": 200, "sprite_height": 200})
    assert sized.properties["sprite_width"] == 200


# --- game time -------------------------------------------------------------
def test_game_clock_advance_and_wrap():
    clk = gametime.GameClock(hour=23.0, day=1, hours_per_second=1.0)
    clk.advance(2.0)  # 23:00 + 2h -> 01:00 next day
    assert clk.day == 2
    assert abs(clk.hour - 1.0) < 1e-6
    clk.paused = True
    clk.advance(5.0)
    assert abs(clk.hour - 1.0) < 1e-6  # paused: no change


def test_game_clock_roundtrip():
    clk = gametime.GameClock(hour=14.5, day=3)
    clk2 = gametime.GameClock.from_dict(clk.to_dict())
    assert clk2.day == 3 and abs(clk2.hour - 14.5) < 1e-6


# --- schedules -------------------------------------------------------------
def test_schedule_evaluation():
    sch = schedule.schedule_for("blacksmith")
    assert sch, "role should have a default schedule"
    # 10:00 -> working; 23:00 -> sleeping; 03:00 -> overnight wraps to sleeping
    assert schedule.evaluate(sch, 10.0)["state"] == schedule.WORKING
    assert schedule.evaluate(sch, 23.0)["state"] == schedule.SLEEPING
    assert schedule.evaluate(sch, 3.0)["state"] == schedule.SLEEPING
    assert schedule.evaluate([], 12.0) is None


# --- inventory -------------------------------------------------------------
def test_inventory_add_remove_transfer():
    a, b = [], []
    inventory.add_item(a, inventory.make_item("gold", item_type="gold", value=1), qty=25)
    inventory.add_item(a, inventory.make_item("iron_sword", item_type="weapon", value=25, weight=8))
    assert inventory.quantity(a, "gold") == 25
    assert inventory.has_item(a, "iron_sword")
    # stacking
    inventory.add_item(a, inventory.make_item("gold"), qty=5)
    assert inventory.quantity(a, "gold") == 30
    # transfer
    moved = inventory.transfer(a, b, "gold", 10)
    assert moved == 10
    assert inventory.quantity(a, "gold") == 20
    assert inventory.quantity(b, "gold") == 10
    # remove more than present clamps
    assert inventory.remove_item(a, "iron_sword", 5) == 1
    assert not inventory.has_item(a, "iron_sword")
    assert inventory.total_weight(b) == 0.0


# --- dialogue --------------------------------------------------------------
def _quest_tree():
    return {
        "start": "greeting",
        "nodes": {
            "greeting": {
                "text": "Welcome.",
                "responses": [
                    {"text": "Work?", "goto": "quest",
                     "condition": {"key": "village_quest", "not_equals": "started"}},
                    {"text": "Bye", "goto": "END"},
                ],
            },
            "quest": {
                "text": "Clear the mill.",
                "on_enter": [{"op": "set", "key": "village_quest", "value": "started"}],
                "responses": [
                    {"text": "Take this blade.", "goto": "END",
                     "actions": [{"op": "give_item",
                                  "item": {"id": "iron_sword", "name": "Iron Sword",
                                           "type": "weapon", "value": 25}}]},
                ],
            },
        },
    }


def test_dialogue_conditions_and_actions():
    store = DictStore()
    given = []
    runner = DialogueRunner(_quest_tree(), store=store, give_item=given.append)
    view = runner.start()
    # Both responses visible before the quest starts.
    assert len(view["responses"]) == 2
    # Choose "Work?" -> enters quest node, on_enter sets the flag.
    view = runner.choose(0)
    assert store.get("village_quest") == "started"
    assert view["text"] == "Clear the mill."
    # Accept the blade -> give_item fires, conversation ends.
    end = runner.choose(0)
    assert end is None
    assert given and given[0]["id"] == "iron_sword"
    # Re-open: the now-satisfied condition hides the "Work?" option.
    runner2 = DialogueRunner(_quest_tree(), store=store)
    view = runner2.start()
    assert len(view["responses"]) == 1


# --- runtime session (schedule move + combat override + dialogue) ----------
class _FakeThing:
    def __init__(self, pos, properties):
        self.pos = list(pos)
        self.properties = dict(properties)


class _FakePlayer:
    def __init__(self, pos):
        self.pos = list(pos)
        self.properties = {}


class _FakeLogic:
    def __init__(self, things, player):
        self.things = things
        self.player = player


def _make_session(things, player):
    from game.runtime import MiniwindSession
    logic = _FakeLogic(things, player)
    session = MiniwindSession(logic, cfg={"start_hour": 9.0, "minutes_per_day": 20.0})
    return logic, session


def test_session_moves_npc_toward_work():
    # A parked villager at home should walk toward its market destination.
    npc = _FakeThing([0, 0, 0], {
        "type": "npc", "npc_role": "villager", "faction": "villagers",
        "team": "villagers", "aggression": "passive", "triggered": True,
        "home": [0, 0, 0], "work_location": [1000, 0, 0],
        "schedule": [{"hour": 9, "state": "WORKING", "location": "work"}],
        "dialogue": {}, "inventory": [],
    })
    player = _FakePlayer([5000, 0, 5000])
    logic, session = _make_session([npc], player)
    start_x = npc.pos[0]
    for _ in range(30):
        session.tick(0.1)
    assert npc.pos[0] > start_x, "villager should move toward work"
    assert npc.properties["sched_state"] == "WORKING"


def test_session_combat_override_for_guard():
    guard = _FakeThing([0, 0, 0], {
        "type": "npc", "npc_role": "guard", "faction": "guards", "team": "guards",
        "aggression": "defensive", "triggered": True, "home": [0, 0, 0],
        "work_location": [0, 0, 0], "schedule": [{"hour": 6, "state": "WORKING", "location": "work"}],
        "dialogue": {}, "inventory": [],
    })
    bandit = _FakeThing([100, 0, 0], {
        "type": "npc", "npc_role": "bandit", "faction": "bandits", "team": "bandits",
        "aggression": "hostile", "triggered": False, "awake": True,
    })
    player = _FakePlayer([9999, 0, 9999])
    logic, session = _make_session([guard, bandit], player)
    session.tick(0.5)
    # Guard should have been un-parked (handed to core AI) to fight the bandit.
    assert guard.properties["triggered"] is False
    assert guard.properties["awake"] is True
    assert guard.properties["sched_state"] == "COMBAT"


def test_session_dialogue_gives_item_to_player_inventory():
    npc = _FakeThing([0, 0, 0], {
        "type": "npc", "npc_role": "villager", "faction": "villagers",
        "team": "villagers", "aggression": "passive", "triggered": True,
        "home": [0, 0, 0], "schedule": [], "inventory": [],
        "dialogue": _quest_tree(),
    })
    player = _FakePlayer([10, 0, 0])
    logic, session = _make_session([npc], player)
    assert session.start_dialogue(npc, player)
    session.choose(0)  # Work? -> quest
    session.choose(0)  # take blade -> END, gives item
    pinv = session.game.character.inventory
    assert inventory.has_item(pinv, "iron_sword")
    assert session.dialogue is None  # conversation closed


def test_session_persist_restore_roundtrip():
    npc = _FakeThing([0, 0, 0], {"type": "npc", "schedule": [], "dialogue": {}, "inventory": []})
    player = _FakePlayer([0, 0, 0])
    logic, session = _make_session([npc], player)
    # Use a real GlobalStore-like DictStore-backed store via the plugin store.
    from game.dialogue import DictStore

    class _G:
        def __init__(self):
            self.d = {}

        def get(self, k, default=None, store="plugins"):
            return self.d.get((store, k), default)

        def set(self, k, v, store="plugins"):
            self.d[(store, k)] = str(v)

        def all(self, store="plugins"):
            return {k[1]: v for k, v in self.d.items() if k[0] == store}

    from game.runtime import MiniwindSession, StateStore
    g = _G()
    session.store = StateStore(g, "miniwind")
    session.game.store = session.store
    session.clock.set_time(15.0, 4)
    session.game.character.gold = 42
    inventory.add_item(session.game.character.inventory,
                       inventory.make_item("iron_sword", value=25, qty=1))
    session.persist()

    # New session over the same store restores clock + character.
    logic2 = _FakeLogic([npc], player)
    s2 = MiniwindSession(logic2, cfg={})
    s2.store = StateStore(g, "miniwind")
    s2.game.store = s2.store
    s2.restore()
    assert s2.clock.day == 4 and abs(s2.clock.hour - 15.0) < 1e-6
    assert s2.game.character.gold == 42
    assert inventory.has_item(s2.game.character.inventory, "iron_sword")


# --- self-runner -----------------------------------------------------------
if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception as e:  # noqa
            failed += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
