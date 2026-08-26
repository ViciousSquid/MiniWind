"""
Integration tests for the MiniWind living settlement (§18).

These build the settlement from its data file (``game/data/settlement.json``),
check the data boundary holds (every NPC references markers that exist), and
then *simulate a day* headlessly through the real runtime session to prove the
living-world loop: townsfolk go to work by day and sleep at night, moving toward
their own authored markers — with no Qt, no OpenGL and no per-frame global AI.

Run:  python -m pytest game/tests/test_settlement.py -q
"""

from __future__ import annotations

import json
import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from game import data
from game.rpg import bestiary
from game.tools import make_settlement


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


class _FakeGlobals:
    """A real (dict-backed) stand-in for the plugin GlobalStore so persistence
    of settlement consequences can be exercised headlessly."""

    def __init__(self, data=None):
        self._d = dict(data or {})

    def get(self, key, default="false", store=None):
        return self._d.get((store, str(key)), default)

    def set(self, key, value, store=None):
        self._d[(store, str(key))] = str(value)

    def all(self, store=None):
        return {k[1]: v for k, v in self._d.items() if k[0] == store}


def _base_map():
    base = os.path.join(os.path.dirname(__file__), "..", "tools", "data", "base_terrain.json")
    with open(os.path.abspath(base)) as f:
        return json.load(f)


def _built():
    return make_settlement.build(data.load("settlement"), _base_map())


# --- data boundary ---------------------------------------------------------
def test_settlement_data_is_well_formed():
    s = data.load("settlement")
    assert s.get("markers") and s.get("npcs") and s.get("threats")
    marker_ids = set(s["markers"])
    for npc in s["npcs"]:
        for ref in ("home", "work", "bed"):
            if npc.get(ref):
                assert npc[ref] in marker_ids, f"{npc['name']} {ref} -> missing marker {npc[ref]}"
        assert bestiary.get(npc["role"]) is not None, f"unknown role {npc['role']}"
    # roles are varied — a settlement, not six clones
    assert len({n["role"] for n in s["npcs"]}) >= 5


def test_build_produces_loadable_map():
    world = _built()
    types = [t["type"] for t in world["things"]]
    assert types.count("playerstart") == 1
    assert types.count("miniwindsettings") == 1
    assert types.count("marker") == len(data.load("settlement")["markers"])
    # townsfolk are NPCs; threats are Creatures — distinct entities
    assert types.count("npc") == 6
    assert types.count("creature") == 3
    # every thing carries a stable UUID and a type (persistence contract)
    for t in world["things"]:
        assert t["properties"].get("id") and t["properties"].get("type")


def _load_session(hour, globals_store=None):
    """Materialise the built map's things into a live session at *hour*."""
    from game.runtime import MiniwindSession
    world = _built()
    things = [_FakeThing(t["pos"], t["properties"]) for t in world["things"]]
    player = _FakePlayer([300, 272, -100])  # near the square, away from the threat
    logic = _FakeLogic(things, player)
    session = MiniwindSession(logic, cfg={"start_hour": hour, "minutes_per_day": 999999.0},
                              globals_store=globals_store)
    session.clock.set_time(hour, 1)
    return session, things


def _find(things, name):
    for t in things:
        if t.properties.get("name") == name:
            return t
    return None


def test_townsfolk_work_by_day():
    session, things = _load_session(12.0)
    thalen = _find(things, "Thalen")
    forge = _find(things, "thalen_forge")
    d0 = math.dist(thalen.pos, forge.pos)
    for _ in range(60):
        session.tick(0.1)
    assert thalen.properties["sched_state"] == "WORKING"
    assert math.dist(thalen.pos, forge.pos) < d0, "Thalen should walk toward his forge marker"


def test_townsfolk_sleep_at_night():
    session, things = _load_session(23.0)
    for _ in range(20):
        session.tick(0.1)
    # Every scheduled townsperson should be heading to bed / asleep, not working.
    for name in ("Thalen", "Elowen", "Bram", "Mara"):
        npc = _find(things, name)
        assert npc.properties["sched_state"] in ("SLEEPING", "GOING_HOME"), \
            f"{name} should be sleeping/going home at 23:00, got {npc.properties['sched_state']}"


def test_threat_starts_hostile_and_is_far_from_town():
    session, things = _load_session(12.0)
    bandit = _find(things, "Bandit")
    assert bandit.properties["aggression"] == "hostile"
    # The threat sits outside the settlement, so it does not interrupt daily life
    # on the very first decision tick.
    guard = _find(things, "Kestrel")
    assert math.dist(bandit.pos, guard.pos) > 700


# --- guard patrol (a visibly moving watch) ---------------------------------
def test_guard_patrols_its_circuit_by_day():
    from game.rpg import schedule as sched
    session, things = _load_session(12.0)
    kestrel = _find(things, "Kestrel")
    start = list(kestrel.pos)
    seen_wp = set()
    moved = 0.0
    for _ in range(300):
        session.tick(0.1)
        seen_wp.add(kestrel.properties.get("_patrol_i"))
        moved = max(moved, math.dist(kestrel.pos, start))
    # on duty at noon the guard is patrolling, not standing at one spot
    assert kestrel.properties["sched_state"] == sched.PATROL
    assert moved > 100.0, "the guard should walk a real distance on patrol"
    # and it cycles through more than one waypoint of its authored circuit
    assert len(seen_wp) >= 2, f"guard should advance along its circuit, saw {seen_wp}"


def test_guard_resumes_patrol_after_a_threat_passes():
    from game.rpg import schedule as sched
    session, things = _load_session(12.0)
    kestrel = _find(things, "Kestrel")
    # The engine's entity constructor fills faction/team on load; the headless
    # fixture skips it, so set the guard's side explicitly (as the combat tests do).
    kestrel.properties.update({"faction": "guards", "team": "guards", "combatant": True})
    # A bandit appears right next to the guard: it un-parks for the core combat AI.
    bandit = _FakeThing([kestrel.pos[0] + 120, kestrel.pos[1], kestrel.pos[2]],
                        {"type": "creature", "npc_role": "bandit", "faction": "bandits",
                         "team": "bandits", "aggression": "hostile", "triggered": False})
    things.append(bandit)
    session.tick(0.5)
    assert kestrel.properties["triggered"] is False   # handed to the combat AI
    assert kestrel.properties["sched_state"] == sched.COMBAT
    # The threat is dealt with and removed; the guard recovers and patrols again.
    bandit.properties["dead"] = True
    for _ in range(30):
        session.tick(0.1)
    assert kestrel.properties["triggered"] is True    # re-parked to schedule
    assert kestrel.properties["sched_state"] == sched.PATROL


# --- settlement consequences persist ---------------------------------------
def test_npc_death_is_recorded_and_persists_through_save_load():
    g = _FakeGlobals()
    session, things = _load_session(12.0, globals_store=g)
    session.install()
    elowen = _find(things, "Elowen")
    elowen.properties["dead"] = True
    elowen.properties["health"] = 0
    session.tick(0.1)                       # reaping turns the death into state
    assert session.store.get("dead.Elowen", "false") == "1"
    assert session.store.get("town.mourning", "false") == "1"
    assert int(session.store.get("town.deaths", "0")) == 1
    session.persist(force=True)

    # A brand-new session sharing the same persistent store still knows Elowen is
    # gone — the consequence survived the "save/load".
    session2, _ = _load_session(12.0, globals_store=g)
    assert session2.store.get("dead.Elowen", "false") == "1"
    assert session2.store.get("town.mourning", "false") == "1"


def test_slain_guard_marks_the_town_unprotected():
    g = _FakeGlobals()
    session, things = _load_session(12.0, globals_store=g)
    kestrel = _find(things, "Kestrel")
    kestrel.properties["dead"] = True
    session.tick(0.1)
    assert session.store.get("town.unprotected", "false") == "1"
    # recorded exactly once, even across further ticks
    session.tick(0.1)
    session.tick(0.1)
    assert int(session.store.get("town.deaths", "0")) == 1


# --- authored, interconnected characters -----------------------------------
def test_key_npcs_have_authored_relationships():
    s = data.load("settlement")
    by_name = {n["name"]: n for n in s["npcs"]}
    # a small web, not six strangers: siblings, a friendship, a courtship
    assert by_name["Thalen"]["relationships"]["Elowen"] == "sister"
    assert by_name["Elowen"]["relationships"]["Thalen"] == "brother"
    assert by_name["Kestrel"]["relationships"]["Mara"] == "sweetheart"
    assert by_name["Mara"]["relationships"]["Bram"] == "brother"
    # every relationship names an NPC that actually exists in the settlement
    names = set(by_name)
    for n in s["npcs"]:
        for other in (n.get("relationships") or {}):
            assert other in names, f"{n['name']} references unknown NPC {other}"


def test_apply_settlement_content_upgrades_in_place():
    """The content-merge tool refreshes NPC dialogue/relationships/patrol on a
    hand-authored map without moving anything or touching geometry, and collapses
    exact-duplicate things."""
    from game.tools.apply_settlement_content import apply_content
    s = data.load("settlement")
    # A tiny stand-in "hand-edited" map: a wall brush, a bare Kestrel at a
    # bespoke position, and an accidental duplicate threat.
    world = {
        "brushes": [{"id": "wall-1", "pos": [0, 0, 0], "size": [10, 10, 10]}],
        "things": [
            {"type": "npc", "pos": [123, 272, -456],
             "properties": {"type": "npc", "name": "Kestrel", "npc_role": "guard"}},
            {"type": "creature", "pos": [9, 9, 9],
             "properties": {"type": "creature", "name": "Bandit"}},
            {"type": "creature", "pos": [9, 9, 9],
             "properties": {"type": "creature", "name": "Bandit"}},
        ],
    }
    out, n = apply_content(world, s)
    assert n == 1
    kestrel = next(t for t in out["things"] if t["properties"].get("name") == "Kestrel")
    # position preserved exactly; content upgraded from the data
    assert kestrel["pos"] == [123, 272, -456]
    assert kestrel["properties"]["relationships"]["Mara"] == "sweetheart"
    assert kestrel["properties"]["patrol_markers"][0] == "kestrel_post"
    assert "grieve_mara" in kestrel["properties"]["dialogue"]["nodes"]
    # geometry untouched; the duplicate threat collapsed to one
    assert out["brushes"][0]["id"] == "wall-1"
    assert sum(1 for t in out["things"] if t["properties"]["name"] == "Bandit") == 1


def test_dialogue_reflects_a_relatives_death():
    from game.rpg.dialogue import DialogueRunner, DictStore
    s = data.load("settlement")
    mara = next(n for n in s["npcs"] if n["name"] == "Mara")
    tree = mara["dialogue"]

    # Kestrel alive: Mara offers to talk about the folk she loves, no grief.
    runner = DialogueRunner(tree, store=DictStore())
    runner.start()
    texts = [r["text"] for r in runner.view()["responses"]]
    assert any("keeps you company" in t for t in texts)
    assert not any("Kestrel fell" in t for t in texts)

    # Kestrel dead (a persistent flag): the grief line opens, the small-talk closes.
    runner2 = DialogueRunner(tree, store=DictStore({"dead.Kestrel": "1"}))
    runner2.start()
    texts2 = [r["text"] for r in runner2.view()["responses"]]
    assert any("Kestrel fell" in t for t in texts2)
    assert not any("keeps you company" in t for t in texts2)
