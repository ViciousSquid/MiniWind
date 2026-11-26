"""Dynamic game mode: the scene director on the roads (game/living/scenarios.py).

Normal mode must be exactly as before -- nothing staged, nothing saved -- and
Dynamic mode casts its scenes from the world's own people, parties and
grievances, out of sight and ahead of the player."""

import json
import math
import random
from types import SimpleNamespace

from ..living import journeys as jn
from ..living import roads
from ..living import scenarios as sc


class _Store(dict):
    def get(self, key, default=None):
        return super().get(key, default)

    def set(self, key, value):
        self[key] = value


class _Clock:
    def __init__(self, hour):
        self.day, self.hour, self.hours_per_second = 0, float(hour), 1.0 / 60.0


class _Thing:
    def __init__(self, x, z, **props):
        self.pos = [float(x), 0.0, float(z)]
        self.properties = dict(props)


class _Hooks(jn.WorldHooks):
    def __init__(self):
        self.homes = []
        self.director = None

    def resident_can_leave(self, rid):
        return True

    def resident_home(self, rid, journey, alive):
        self.homes.append((rid, alive))

    def stage_expired(self, journey, t):
        return self.director.stage_expired(journey, t)


# Four places strung along an east-west road, the player in the middle.
PLACES = {"ashby": {"name": "Ashby", "x": 0.0, "z": 0.0, "kind": "town"},
          "camp": {"name": "Old Camp", "x": 4000.0, "z": 0.0, "kind": "camp"},
          "kettle": {"name": "Kettlewick", "x": 8000.0, "z": 0.0, "kind": "town"},
          "farm": {"name": "Low Farm", "x": -4000.0, "z": 0.0, "kind": "farm"}}


def _world(mode="dynamic", hour=12.0, player=(2000.0, 0.0), facing=(1.0, 0.0)):
    nodes = [(f"r{i}", float(x), 0.0, (f"r{i + 1}",) if i < 12 else ())
             for i, x in enumerate(range(-4000, 8001, 1000))]
    network = roads.RoadNetwork.build(nodes, [(k, v["x"], v["z"]) for k, v in PLACES.items()])
    hooks = _Hooks()
    board = jn.JourneyBoard(network, dict(PLACES), 1.0 / 60.0, rng=random.Random(4),
                            hooks=hooks, population=0)
    store = _Store()
    notes, barks, said, gold = [], [], [], []
    config = {"mode": mode}
    character = SimpleNamespace(health=100, max_health=100)
    session = SimpleNamespace(
        rng=random.Random(7), clock=_Clock(hour), store=store,
        game=SimpleNamespace(character=character),
        _player_pos=lambda: [player[0], 0.0, player[1]],
        _player_forward=lambda: (facing[0], 0.0, facing[1]),
        notify=lambda text, seconds=3.0: notes.append(text),
        bark=lambda thing, text, *a: barks.append(text),
        dynamic_mode_enabled=lambda: config["mode"] == "dynamic",
        _credit_found_gold=lambda amount, verb="Found": gold.append(amount) or amount,
        storyteller=SimpleNamespace(state="CALM", narrate=lambda kind, text, now=None: said.append(text)),
        director=None, npcs=lambda: [])
    world = SimpleNamespace(session=session, board=board, live={}, _residents={},
                            flour_roads=None, reach=lambda: 2200.0,
                            resident_thing=lambda rid: world._residents.get(rid),
                            _register=lambda quest: None)

    def abstract_pos(j, t):
        if j.stage is not None and j.state == "rest" and not j.stage.get("walking"):
            return j.stage["x"], j.stage["z"]
        return j.position_at(t)

    world._abstract_pos = abstract_pos
    director = sc.ScenarioDirector(world)
    hooks.director = director
    return SimpleNamespace(world=world, board=board, director=director, store=store,
                           notes=notes, barks=barks, said=said, gold=gold, config=config,
                           character=character, session=session, hooks=hooks)


def _culprit_gang(board, t=12.0, name="black_rook", display="Black Rook"):
    """Black Rook's band on the roads: the culprit as the gang's chief."""
    gang = board.plan("bandits", t, origin="camp", dest="kettle")
    gang.members[0]["name"], gang.members[0]["display"] = name, display
    return gang


def _trader(board, t=12.0):
    j = board.plan("trader", t, origin="farm", dest="kettle")
    assert j is not None
    return j


def _build(w):
    """Skip the opening rest straight to build-up."""
    w.director._enter("build", 0.0)


# -- Normal mode is untouched -------------------------------------------------
def test_normal_mode_stages_nothing_and_saves_nothing():
    w = _world(mode="normal")
    _trader(w.board)
    before = w.board.to_json()
    _build(w)
    for _ in range(300):
        w.director.tick(12.0, 1.0)
        w.director.watch()
    w.director.persist()
    assert w.board.to_json() == before
    assert not w.director.scenes and sc.STORE_KEY not in w.store
    assert sc.LEARNED_KEY not in w.store            # nothing learned, nothing saved


def test_an_ordinary_journey_saves_exactly_as_before():
    w = _world(mode="normal")
    j = _trader(w.board)
    assert "stage" not in j.to_dict()
    assert jn.Journey.from_dict(j.to_dict()).stage is None


def test_the_ordinary_board_never_picks_a_dynamic_only_kind():
    w = _world(mode="normal")
    for hour in range(24):
        for _ in range(50):
            assert w.board._pick_kind(float(hour)) not in jn.DYNAMIC_KINDS
    assert not set(jn.DYNAMIC_KINDS) & set(jn.KINDS)


# -- Dynamic mode -------------------------------------------------------------
def test_the_session_opens_with_a_rest_before_anything_is_staged():
    w = _world()
    _trader(w.board)
    for _ in range(int(sc.FIRST_RELAX) - 2):
        w.director.tick(12.0, 1.0)
    assert not [s for s in w.director.scenes.values() if s["kind"] != "gratitude"]


def test_a_real_traveller_is_waylaid_ahead_of_the_player_and_out_of_sight():
    w = _world()
    trader = _trader(w.board)
    _build(w)
    scene = w.director._stage_waylaid(12.0)
    assert scene is not None and scene["kind"] == "waylaid"
    victim = w.board.journeys[scene["journeys"]["victim"]]
    gang = w.board.journeys[scene["journeys"]["attacker"]]
    assert victim is trader                          # borrowed, not invented
    assert gang.kind == "bandits" and gang.hostile
    px = 2000.0
    for j in (victim, gang):
        assert j.stage["scene"] == scene["id"] and j.state == "rest"
        x, z = w.world._abstract_pos(j, 12.0)
        assert math.hypot(x - px, z) >= sc.STAGE_MIN * 0.85
        assert x > px                                # ahead: the player faces east
    assert gang.id in victim.fought and victim.id in gang.fought
    assert w.said                                    # on the storyteller's record


def test_an_existing_gang_is_borrowed_before_a_new_one_is_made():
    w = _world()
    _trader(w.board)
    gang = w.board.plan("bandits", 20.0, origin="camp", dest="farm")
    scene = w.director._stage_waylaid(20.0)
    assert scene["journeys"]["attacker"] == gang.id
    assert gang.stage["borrowed"]


def test_an_unmet_scene_lets_the_world_move_on():
    w = _world()
    trader = _trader(w.board)
    gang = w.board.plan("bandits", 12.0, origin="camp", dest="farm")
    w.director._stage_waylaid(12.0)
    w.board.update(12.0)
    w.board.update(12.0 + sc.HOLD_HOURS + 0.1)
    assert trader.stage is None and trader.state in ("travel", "rest")
    assert trader.dest == "kettle"                   # on to where they were going
    assert gang.stage is None and gang.state != "done"


def test_a_cult_rite_holds_a_real_townsperson_and_unrescued_they_are_lost():
    w = _world(hour=23.0)
    farmer = _Thing(-4000, 0, name="mabel", display_name="Mabel", npc_role="farmer",
                    faction="villagers", type="npc")
    w.world._residents["mabel"] = farmer
    w.board.resident_pool = [{"id": "mabel", "home": "farm", "role": "farmer",
                              "name": "mabel", "display": "Mabel"}]
    scene = w.director._stage_cult_rite(23.0)
    assert scene is not None
    captive = w.board.journeys[scene["journeys"]["victim"]]
    cult = w.board.journeys[scene["journeys"]["attacker"]]
    assert captive.resident == "mabel" and captive.members[0]["display"] == "Mabel"
    assert w.board.residents_on_trips["mabel"] == captive.id
    assert cult.kind == "cultists" and {m["role"] for m in cult.members} >= {"cult_leader"}
    w.board.update(23.0)
    w.board.update(23.0 + sc.RITE_HOURS + 0.1)
    w.board.update(23.0 + sc.RITE_HOURS + 0.2)
    assert ("mabel", False) in w.hooks.homes
    assert any("taken by cultists" in n["text"] for n in w.board.news.values())


def test_cult_scenes_wait_for_the_night():
    w = _world(hour=12.0)
    _build(w)
    kinds = set()
    for _ in range(40):
        w.director.gap_left = 0.0
        w.director.scenes.clear()
        scene = w.director._cast(12.0, False)
        if scene:
            kinds.add(scene["kind"])
    assert not kinds & {"cult_rite", "procession", "ambush"}


def test_rescuing_a_victim_is_thanked_rewarded_and_told():
    w = _world()
    trader = _trader(w.board)
    scene = w.director._stage_waylaid(12.0)
    gang = w.board.journeys[scene["journeys"]["attacker"]]
    for m in gang.members:
        m["alive"] = False
    lead = _Thing(2000.0, 100.0, display_name="Hal the Trader", _member=0,
                  inventory=[{"id": "gold", "qty": 50}])
    trader.live = True
    w.world.live[trader.id] = {"things": [lead]}
    w.director.watch()
    assert scene["resolved"] and w.barks
    paid = w.gold[0]
    assert 10 <= paid <= 50                                   # from what they hold
    assert lead.properties["inventory"] == ([{"id": "gold", "qty": 50 - paid}] if paid < 50 else [])
    assert any("came to the aid of" in n["text"] for n in w.board.news.values())
    assert trader.stage is None and trader.state == "travel"


def test_intensity_builds_peaks_fades_and_rests():
    w = _world()
    d = w.director
    _build(w)
    w.character.health = 100
    d.tick(12.0, 1.0)
    w.character.health = 60                        # badly hit
    d.tick(12.0, 1.0)
    assert d.intensity >= sc.PEAK and d.phase == "sustain"
    for _ in range(20):
        d.tick(12.0, 1.0)
    assert d.phase in ("fade", "relax")
    for _ in range(40):
        d.tick(12.0, 1.0)
    assert d.phase == "relax"


def test_a_hurt_player_gets_no_new_threat():
    w = _world()
    _trader(w.board)
    _build(w)
    w.character.health = 30
    w.director._last_health = 0.3
    for _ in range(120):
        w.director.tick(12.0, 1.0)
    assert not w.director.scenes


def test_back_to_normal_returns_staged_parties_to_ordinary_life():
    w = _world()
    trader = _trader(w.board)
    w.director._stage_waylaid(12.0)
    w.config["mode"] = "normal"
    w.director.tick(12.0, 1.0)
    assert not w.director.scenes
    assert all(j.stage is None for j in w.board.journeys.values())
    assert trader.state == "travel" and trader.dest == "kettle"


def test_scenes_and_staged_parties_survive_a_save():
    w = _world()
    _trader(w.board)
    scene = w.director._stage_waylaid(12.0)
    w.director.persist()
    raw = w.board.to_json()
    w2 = _world()
    assert w2.board.load_json(raw)
    w2.store.update(w.store)
    w2.director.restore()
    assert scene["id"] in w2.director.scenes
    victim = w2.board.journeys[scene["journeys"]["victim"]]
    assert victim.stage["scene"] == scene["id"]


def test_dynamic_only_parties_load_from_a_save():
    w = _world(hour=23.0)
    w.director._stage_procession(23.0)
    raw = json.loads(w.board.to_json())
    assert any(j["kind"] == "cultists" for j in raw["journeys"])
    w2 = _world()
    assert w2.board.load_json(json.dumps(raw))
    assert any(j.kind == "cultists" for j in w2.board.journeys.values())


def test_an_avenger_goes_out_over_a_grievance_they_really_hold():
    from ..sim import knowledge
    from ..sim.director import actor_key
    w = _world()
    w.session.clock.day = 2
    edda = _Thing(-4000, 0, name="edda", display_name="Edda", npc_role="farmer",
                  faction="villagers", type="npc", relationships={"Aldo": "brother"})
    w.world._residents["edda"] = edda
    knowledge.learn(w.store, actor_key(edda), {
        "e": 41, "kind": "death", "actor": "black_rook", "actor_name": "Black Rook",
        "actor_faction": "bandits", "target": "aldo", "target_name": "Aldo",
        "day": 2, "hour": 3.0, "certainty": 0.9, "identified": True})
    gang = _culprit_gang(w.board)
    scene = w.director._stage_avenger(12.0)
    assert scene is not None and scene["fact_e"] == 41
    assert scene["journeys"]["attacker"] == gang.id           # the culprit's own band
    avenger = w.board.journeys[scene["journeys"]["avenger"]]
    assert avenger.resident == "edda" and avenger.members[0]["armed"]
    assert "Black Rook killed my brother Aldo" in avenger.stage["greeting"]
    # Nobody comes: they walk on after their quarry alone (and may meet the
    # gang off screen at once, the board's dice settling it).
    w.board.update(12.0)
    w.board.update(12.0 + sc.HOLD_HOURS)
    assert any("gone after the gang alone" in d["text"] for d in w.director.decisions)
    assert avenger.state == "done" or avenger.stage.get("walking")


def test_no_grievance_means_no_avenger():
    w = _world()
    w.world._residents["edda"] = _Thing(-4000, 0, name="edda", faction="villagers", type="npc")
    assert w.director._stage_avenger(12.0) is None


# -- the real session ---------------------------------------------------------
def test_a_staged_scene_becomes_real_actors_and_plays_out_in_a_session():
    import pytest
    pytest.importorskip("PyQt5")
    from engine.player import Player
    from engine.logic_thread import LogicThread
    from editor.editor_state import EditorState
    from engine.threaded_game_state import ThreadedGameState
    from ..entities import Marker, NPC, Creature
    from ..living.world import LivingWorld
    from ..runtime import MiniwindSession

    logic = LogicThread(ThreadedGameState(), EditorState())
    try:
        things = logic.editor_state.things
        for name, x in (("Ashby", 0.0), ("Low Farm", -5000.0), ("Old Camp", 5000.0)):
            things.append(Marker(pos=[x, 0, 0], properties={
                "name": "loc_" + name, "marker_kind": "location", "place_name": name,
                "discover_radius": 900}))
        for i in range(4):
            things.append(NPC(pos=[100.0 * i, 0, 300], properties={
                "name": f"folk{i}", "npc_role": "villager", "faction": "villagers"}))
        for i in range(2):
            things.append(Creature(pos=[5000.0 + 100 * i, 0, 200], properties={
                "name": f"beast{i}", "npc_role": "wolf", "aggression": "hostile"}))
        logic.player_runtime.player = Player(1500, 0, angle=math.pi / 2)
        logic.world_runtime.build_entity_caches()
        session = MiniwindSession(logic, cfg={"start_hour": 12.0})
        session.clock.set_time(12.0, 1)
        session.rng.seed(3)
        session.dynamic_mode_enabled = lambda: True
        world = LivingWorld(session, population=0)
        assert world.build()
        world.board.journeys.clear()
        t = sc._now_hours(session.clock)
        trader = world.board.plan("trader", t, origin="low_farm", dest="ashby")
        scene = world.scenarios._stage_waylaid(t)
        assert scene is not None
        world._stream()
        gang = world.board.journeys[scene["journeys"]["attacker"]]
        assert trader.live and gang.live
        actors = world.live[gang.id]["things"]
        assert all(a.properties.get("faction") == "bandits" for a in actors)
        for jid in list(world.live):
            world._drive(jid)                         # held, not walking off
        # The gang falls; the trader, reached, thanks the player and pays.
        for a in actors:
            a.properties["dead"] = True
        lead = world.live[trader.id]["things"][0]
        lead.pos[0], lead.pos[2] = 1600.0, 0.0
        before = session.game.character.gold
        world.scenarios.watch()
        assert scene["resolved"]
        assert session.game.character.gold > before
        assert trader.stage is None and trader.state == "travel"
        for _ in range(5):
            world.tick(1.0)                           # the live loop runs it all
        world.shutdown()
    finally:
        logic.stop()


# -- the decisions, for the debug window -------------------------------------
def test_each_decision_is_plain_words_with_its_raw_data():
    w = _world(hour=23.0)
    _trader(w.board)
    _build(w)
    w.director.tick(23.0, 1.0)
    staged = [d for d in w.director.decisions if d["kind"] == "stage"]
    assert staged, w.director.decisions
    entry = staged[-1]
    assert entry["text"].startswith("The storyteller decided that")
    assert entry["result"] and "night" in entry["why"]
    data = entry["data"]
    assert data["scene_kind"] and data["options"] and "intensity" in data and "phase" in data


def test_a_failed_casting_says_why_each_scene_was_passed_over():
    w = _world(mode="dynamic")          # no travellers, no townsfolk on the board
    w.board.network.place_node.clear()  # and no roads at all
    _build(w)
    w.director.tick(12.0, 1.0)
    skip = [d for d in w.director.decisions if d["kind"] == "skip"]
    assert skip and "no road" in skip[-1]["text"]
    assert skip[-1]["data"]["rejected"]


def test_waits_are_merged_into_one_line():
    w = _world()
    _trader(w.board)
    _build(w)
    for _ in range(30):
        w.director.tick(12.0, 1.0)
    waits = [d for d in w.director.decisions if d["kind"] == "wait"]
    assert len(waits) <= 2


def test_the_report_shows_the_director_only_in_dynamic_mode():
    from .. import storyteller_report as report
    w = _world(mode="normal")
    session = SimpleNamespace(living=w.world)
    w.world.scenarios = w.director
    assert report.dynamic_rows(session) == []
    assert not any(h and "director" in h.lower() for h, _k, _v in report.raw_rows(None, session))
    w.config["mode"] = "dynamic"
    _trader(w.board)
    w.director._stage_waylaid(12.0)
    rows = report.dynamic_rows(session)
    assert rows[0][0] == "Director" and any(label == "Scene" for label, _ in rows)
    raw = report.raw_rows(None, session)
    assert any(h and "director" in h.lower() for h, _k, _v in raw)
    assert any(k and k.startswith("scenes.") for _h, k, _v in raw)


def test_a_staged_avenger_names_the_grievance_and_says_what_was_done():
    from ..sim import knowledge
    from ..sim.director import actor_key
    w = _world()
    w.session.clock.day = 2
    edda = _Thing(-4000, 0, name="edda", display_name="Edda", npc_role="farmer",
                  faction="villagers", type="npc", relationships={"Aldo": "brother"})
    w.world._residents["edda"] = edda
    knowledge.learn(w.store, actor_key(edda), {
        "e": 41, "kind": "death", "actor": "black_rook", "actor_name": "Black Rook",
        "actor_faction": "bandits", "target": "aldo", "target_name": "Aldo", "pos": [-3900, 0, 0],
        "day": 2, "hour": 3.0, "certainty": 0.9, "identified": True, "source": "witnessed"})
    _culprit_gang(w.board)
    scene = w.director._stage_avenger(12.0)
    assert scene["decision"] == ("The storyteller decided that Edda wants revenge on Black Rook "
                                 "because Black Rook killed their brother Aldo near Low Farm on day 2, "
                                 "which they saw for themselves.")
    assert scene["result"].startswith("Spawned Edda (taken from Low Farm while nobody could see), armed")
    assert "offers the player a quest" in scene["result"]


def test_switching_modes_during_play_is_on_the_record():
    w = _world(mode="normal")
    w.director.tick(12.0, 1.0)
    w.config["mode"] = "dynamic"
    w.director.tick(12.0, 1.0)
    assert w.director.phase == "relax"                 # a fresh rest first
    w.config["mode"] = "normal"
    w.director.tick(12.0, 1.0)
    texts = [d["text"] for d in w.director.decisions]
    assert any(t.startswith("Game mode switched to Dynamic") for t in texts)
    assert any(t.startswith("Game mode switched to Normal") for t in texts)
    assert any("switched to Dynamic" in t for t in w.said)   # the storyteller's feed too


# -- learning -------------------------------------------------------------------
def _peak(w, low):
    """Play one peak through to its fade with the player's health at *low*."""
    d = w.director
    d._enter("build", 0.0)
    w.character.health = 100
    d._last_health = 1.0
    d._cycle_low = 1.0
    d._enter("sustain", 5.0)
    d._cycle_low = low
    d._enter("fade", 0.0)


def test_a_peak_that_was_too_hard_slows_the_pace_and_says_why():
    w = _world()
    _peak(w, 0.2)
    L = w.director.learned
    assert L["gap"] == 1.1 and L["hostile"] == 0.9 and L["peaks"] == 1
    entry = [d for d in w.director.decisions if d["kind"] == "learn"][-1]
    assert entry["text"] == ("The storyteller learned that the last peak was too hard: the player "
                             "fell to 20% health (below 30%).")
    assert "further apart" in entry["result"] and "was ×1" in entry["result"]
    assert any(t.startswith("Learned: the last peak was too hard") for t in w.said)


def test_a_peak_that_was_too_easy_quickens_it_and_one_about_right_changes_nothing():
    w = _world()
    _peak(w, 0.9)
    assert w.director.learned["gap"] == 0.9 and w.director.learned["hostile"] == 1.1
    _peak(w, 0.5)
    entry = [d for d in w.director.decisions if d["kind"] == "learn"][-1]
    assert "about right" in entry["text"] and entry["result"] == "No change to the pace."
    assert w.director.learned["gap"] == 0.9


def test_nudges_are_small_and_never_leave_their_bounds():
    w = _world()
    for _ in range(30):
        _peak(w, 0.1)
    L = w.director.learned
    assert L["gap"] == sc.LEARNING["gap_max"] and L["hostile"] == sc.LEARNING["hostile_min"]
    last = [d for d in w.director.decisions if d["kind"] == "learn"][-1]
    assert last["result"].startswith("No change: the pace is already at the limit")


def test_stepping_into_a_scene_or_passing_it_by_moves_only_that_scene():
    w = _world()
    trader = _trader(w.board)
    scene = w.director._stage_waylaid(12.0)
    gang = w.board.journeys[scene["journeys"]["attacker"]]
    for m in gang.members:
        m["alive"] = False
    trader.live = True
    w.world.live[trader.id] = {"things": [_Thing(2000.0, 100.0, display_name="Hal the Trader")]}
    w.director.watch()
    assert w.director.learned["scenes"] == {"waylaid": 1.05}
    # Seen and passed by: less often.
    w2 = _world(hour=23.0)
    scene2 = w2.director._stage_ambush(23.0)
    scene2["hinted"] = True
    w2.board.update(23.0)
    w2.board.update(23.0 + sc.HOLD_HOURS + 0.1)
    assert w2.director.learned["scenes"] == {"ambush": 0.9}
    entry = [d for d in w2.director.decisions if d["kind"] == "learn"][-1]
    assert "passes an ambush by" in entry["text"]


def test_a_scene_the_player_never_came_near_teaches_nothing():
    w = _world(hour=23.0)
    w.director._stage_ambush(23.0)
    w.board.update(23.0)
    w.board.update(23.0 + sc.HOLD_HOURS + 0.1)
    assert w.director.learned == w.director.fresh_learning()


def test_what_it_learned_shapes_the_pace_and_the_choice_of_scene():
    w = _world()
    d = w.director
    d.learned.update(gap=1.5, hostile=0.5, scenes={"waylaid": 2.0})
    assert d.gap_scale() == 1.5 and d.hostile_scale() == 0.5 and d.scene_scale("waylaid") == 2.0
    _trader(w.board)
    _build(w)
    d.tick(12.0, 1.0)
    staged = [e for e in d.decisions if e["kind"] == "stage"][-1]
    assert staged["data"]["options"]["waylaid"] == round(3.0 * 2.0 * 0.5, 2)
    assert d.gap_left >= sc.BUILD_GAP[0] * 1.5 - 1e-6


def test_it_is_saved_in_the_save_as_minified_json_and_comes_back_within_bounds():
    w = _world()
    _peak(w, 0.2)
    w.director.persist()
    raw = w.store[sc.LEARNED_KEY]
    assert " " not in raw and json.loads(raw)["gap"] == 1.1      # minified
    w2 = _world()
    w2.store.update(w.store)
    w2.director.restore()
    assert w2.director.learned["gap"] == 1.1
    w2.store[sc.LEARNED_KEY] = json.dumps({"gap": 99, "hostile": -4, "scenes": {"ambush": 50}})
    w2.director.restore()
    L = w2.director.learned
    assert (L["gap"], L["hostile"], L["scenes"]["ambush"]) == (
        sc.LEARNING["gap_max"], sc.LEARNING["hostile_min"], sc.LEARNING["scene_max"])


def test_learning_switched_off_neither_learns_nor_applies(monkeypatch):
    w = _world()
    w.director.learned.update(gap=1.5)
    monkeypatch.setitem(sc.LEARNING, "enabled", False)
    assert w.director.gap_scale() == 1.0
    _peak(w, 0.1)
    assert w.director.learned["gap"] == 1.5 and w.director.learned["peaks"] == 0


def test_unlearn_forgets_and_says_so():
    w = _world()
    _peak(w, 0.1)
    w.director.forget_learning()
    assert w.director.learned == w.director.fresh_learning()
    assert "forgot" in w.director.decisions[-1]["text"]
    assert json.loads(w.store[sc.LEARNED_KEY])["gap"] == 1.0


# -- what they say ----------------------------------------------------------------
def test_a_score_settler_opens_with_an_introduction_an_insult_or_a_scream():
    from ..living.scenario_modules.reckoning import OPENINGS, opening_line

    rng = random.Random(3)
    styles = set()
    for _ in range(200):
        style, line = opening_line(rng, "vendetta", "aldo")
        styles.add(style)
        assert line and "{" not in line
        assert line in [o.format(victim="aldo", Victim="Aldo")
                        for o in OPENINGS[style]["vendetta"]]
    assert styles == {"introduction", "insult", "scream"}
    for _ in range(50):                              # nobody to name: no {victim} lines
        assert "{" not in opening_line(rng, "reckoning")[1]

def _world_with_bark():
    from ..living.world import LivingWorld
    said = []
    session = SimpleNamespace(rng=random.Random(5), bark=lambda thing, line, *a: said.append(line),
                              _nearest_hostile=lambda x, r: None,
                              _player_pos=lambda: [0.0, 64.0, 0.0], player_actor=object(),
                              faction_spine=None)
    living = LivingWorld(session)
    living.board = jn.JourneyBoard(roads.RoadNetwork(), {}, 1.0 / 60.0, hooks=jn.WorldHooks())
    return living, said


def test_the_opening_is_said_once_then_the_fight_starts():
    living, said = _world_with_bark()
    j = jn.Journey("j1", "avenger", [{"display": "Edda", "grudge": True, "alive": True}],
                   "", "", [(0, 0), (1, 1)], 0.0, 1.0, 1, "")
    living.board.journeys["j1"] = j
    x = _Thing(300.0, 0.0, combatant=True, triggered=True, aggression="hostile",
               _journey="j1", _member=0,
               _grudge_opening={"kind": "vendetta", "victim": "Aldo"})
    assert living._react(j, x, [0.0, 64.0, 0.0])
    assert len(said) == 1 and x.properties["sched_state"] == "COMBAT"
    x.properties["triggered"] = True                 # seen again later: no second opening
    living._react(j, x, [0.0, 64.0, 0.0])
    assert len(said) == 1 and j.members[0]["grudge_opened"]


def test_cultists_shout_their_own_lines_and_brigands_keep_theirs():
    from ..living.world import GREETINGS
    living, said = _world_with_bark()
    for kind in ("cultists", "bandits"):
        j = jn.Journey("c", kind, [{"display": "x", "alive": True}], "", "", [(0, 0), (1, 1)],
                       0.0, 1.0, 1, "")
        x = _Thing(300.0, 0.0, combatant=True, triggered=True)
        living._react(j, x, [0.0, 64.0, 0.0])
        assert said[-1] in GREETINGS[kind]


# -- review fixes -------------------------------------------------------------------
def _edda(w, actor_faction="bandits", actor="black_rook", actor_name="Black Rook", gold=7):
    from ..sim import knowledge
    from ..sim.director import actor_key
    w.session.clock.day = 2
    edda = _Thing(-4000, 0, name="edda", display_name="Edda", npc_role="farmer",
                  faction="villagers", type="npc", relationships={"Aldo": "brother"},
                  inventory=[{"id": "gold", "qty": gold}, {"id": "bread", "qty": 2}])
    w.world._residents["edda"] = edda
    knowledge.learn(w.store, actor_key(edda), {
        "e": 41, "kind": "death", "actor": actor, "actor_name": actor_name,
        "actor_faction": actor_faction, "target": "aldo", "target_name": "Aldo",
        "pos": [-3900, 0, 0], "day": 2, "hour": 3.0, "certainty": 0.9, "identified": True})
    return edda


def test_an_avenger_is_never_sent_after_a_stand_in_gang():
    w = _world()
    _edda(w)
    w.board.plan("bandits", 12.0, origin="camp", dest="farm")    # some other gang
    assert w.director._stage_avenger(12.0) is None
    assert "Black Rook, who is neither on the roads nor anywhere to be found" in w.director._why
    assert "no stand-in was sent" in w.director._why
    assert not any(j.stage for j in w.board.journeys.values())


def test_a_monster_grievance_never_becomes_a_bandit_one():
    w = _world()
    _edda(w, actor_faction="monsters", actor="grak", actor_name="Grak the Greenskin")
    _culprit_gang(w.board)                                       # brigands about: not them
    assert w.director._stage_avenger(12.0) is None
    raiders = w.board.plan("bandits", 12.0, origin="camp", dest="kettle")
    raiders.kind = "greenskins"
    raiders.members[0]["name"], raiders.members[0]["display"] = "grak", "Grak the Greenskin"
    scene = w.director._stage_avenger(12.0)
    assert scene["journeys"]["attacker"] == raiders.id
    assert scene["culprit"] == {"actor": "grak", "name": "Grak the Greenskin", "faction": "monsters"}


def test_a_culprit_off_the_roads_is_where_the_avenger_goes():
    w = _world()
    _edda(w)
    rook = _Thing(4000.0, 0.0, name="black_rook", display_name="Black Rook")
    w.session._sim_actor_by_key = lambda key: rook if key == "black_rook" else None
    scene = w.director._stage_avenger(12.0)
    assert set(scene["journeys"]) == {"avenger"}                 # no gang staged
    avenger = w.board.journeys[scene["journeys"]["avenger"]]
    assert avenger.stage["onward_dest"] == "camp"                # where Black Rook is
    assert "is not on the roads but is at Old Camp" in scene["result"]
    assert "Black Rook" in avenger.stage["greeting"] and "Old Camp" in avenger.stage["greeting"]
    rook.properties["dead"] = True                               # the culprit falls
    lead = _Thing(-100.0, 0.0, display_name="Edda", _member=0, inventory=[])
    avenger.live = True
    w.world.live[avenger.id] = {"things": [lead]}
    w.session._player_pos = lambda: [-100.0, 0.0, 0.0]
    w.director.watch()
    assert scene["resolved"]


def test_the_avenger_carries_their_own_purse_and_offers_only_what_they_have():
    w = _world()
    _edda(w, gold=7)
    registered = []
    w.world._register = registered.append
    _culprit_gang(w.board)
    scene = w.director._stage_avenger(12.0)
    member = w.board.journeys[scene["journeys"]["avenger"]].members[0]
    assert member["gold"] == 0 and member["own_purse"]
    assert member["inventory"] == [{"id": "gold", "qty": 7}, {"id": "bread", "qty": 2}]
    quest = registered[-1]
    assert quest["rewards"] == {"gold": 7} and "7 gold" in quest["offer"]
    assert quest["stages"][0]["condition"]["target"] == "black_rook"     # the culprit, by name


def test_a_rescue_never_pays_more_than_the_purse_and_nothing_from_an_empty_one():
    w = _world()
    trader = _trader(w.board)
    scene = w.director._stage_waylaid(12.0)
    for m in w.board.journeys[scene["journeys"]["attacker"]].members:
        m["alive"] = False
    lead = _Thing(2000.0, 100.0, display_name="Hal", _member=0, inventory=[{"id": "gold", "qty": 3}])
    trader.live = True
    w.world.live[trader.id] = {"things": [lead]}
    w.director.watch()
    assert w.gold == [3] and lead.properties["inventory"] == []          # all of it, no more
    w2 = _world()
    trader2 = _trader(w2.board)
    scene2 = w2.director._stage_waylaid(12.0)
    for m in w2.board.journeys[scene2["journeys"]["attacker"]].members:
        m["alive"] = False
    broke = _Thing(2000.0, 100.0, display_name="Hal", _member=0, inventory=[])
    trader2.live = True
    w2.world.live[trader2.id] = {"things": [broke]}
    w2.director.watch()
    assert w2.gold == [] and any("no gold to give" in t for t in w2.said)


def test_a_townsperson_comes_home_with_what_they_carried_and_the_lent_sword_goes_back():
    from ..living.world import LivingWorld, SessionHooks
    home = _Thing(0.0, 0.0, name="edda", inventory=[{"id": "gold", "qty": 7}], health=60)
    living = LivingWorld(SimpleNamespace())
    living._residents["edda"] = home
    living.set_hidden = lambda thing, hidden: None
    j = jn.Journey("j9", "avenger", [{"resident": "edda", "own_purse": True, "health": 41,
                                      "lent_weapon": "iron_shortsword",
                                      "inventory": [{"id": "gold", "qty": 2},
                                                    {"id": "iron_shortsword", "qty": 1}]}],
                   "", "", [(0, 0), (1, 1)], 0.0, 1.0, 1, "")
    SessionHooks(living).resident_home("edda", j, True)
    assert home.properties["inventory"] == [{"id": "gold", "qty": 2}]   # spent 5; no free sword
    assert home.properties["health"] == 41


def test_a_materialised_reckoning_character_is_hostile_and_fights_the_player():
    """Regression: 'armed' used to overwrite the grudge's hostility with
    'defensive', so someone sent to settle a score never attacked."""
    import pytest
    pytest.importorskip("PyQt5")
    from engine.player import Player
    from engine.logic_thread import LogicThread
    from editor.editor_state import EditorState
    from engine.threaded_game_state import ThreadedGameState
    from ..entities import Marker, NPC
    from ..living.world import LivingWorld
    from ..runtime import MiniwindSession

    logic = LogicThread(ThreadedGameState(), EditorState())
    try:
        things = logic.editor_state.things
        for name, x in (("Ashby", 0.0), ("Low Farm", -5000.0)):
            things.append(Marker(pos=[x, 0, 0], properties={
                "name": "loc_" + name, "marker_kind": "location", "place_name": name,
                "discover_radius": 900}))
        for i in range(4):
            things.append(NPC(pos=[100.0 * i, 0, 300], properties={
                "name": f"folk{i}", "npc_role": "villager", "faction": "villagers"}))
        mara = NPC(pos=[-5000.0, 0, 200], properties={
            "name": "mara", "display_name": "Mara", "npc_role": "farmer", "faction": "villagers",
            "inventory": [{"id": "gold", "qty": 12}]})
        things.append(mara)
        logic.player_runtime.player = Player(1500, 0, angle=math.pi / 2)
        logic.world_runtime.build_entity_caches()
        session = MiniwindSession(logic, cfg={"start_hour": 12.0})
        session.clock.set_time(12.0, 1)
        session.dynamic_mode_enabled = lambda: True
        world = LivingWorld(session, population=0)
        assert world.build()
        world.board.journeys.clear()
        t = sc._now_hours(session.clock)
        d = world.scenarios
        member = d._resident_member(mara, "mara")
        member.update(armed=True, grudge=True, grudge_kind="reckoning", grudge_victim="")
        route = [(2400.0, 0.0), (1500.0, 0.0), (0.0, 0.0)]
        j = d._new_journey("avenger", [member], route, "ashby", t)
        d._walking(j, route, "ashby", "dynX", "seeker", t)
        world._stream()
        assert j.live
        actor = world.live[j.id]["things"][0]
        p = actor.properties
        assert p["aggression"] == "hostile" and p["combatant"] is True       # not "defensive"
        assert p["_base_aggression"] == "hostile"
        said = []
        session.bark = lambda thing, line, *a: said.append(line)
        actor.pos[0], actor.pos[2] = 1900.0, 0.0                            # within sight
        assert world._react(j, actor, session._player_pos())
        assert p["sched_state"] == "COMBAT" and p["triggered"] is False
        assert len(said) == 1                                               # the opening, once
        world.shutdown()
    finally:
        logic.stop()
