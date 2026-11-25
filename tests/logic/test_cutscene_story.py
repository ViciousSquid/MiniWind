"""Story cutscenes: actors SAY and THINK on a keyframe, MOVE on their tracks,
and fight simulated team battles (ATTACK), through the production LogicThread
and CutsceneRuntime."""

import pytest

pytest.importorskip("PyQt5", reason="LogicThread owns editor-backed entities")

from editor.editor_state import EditorState
from editor.things import LogicCamera, Monster
from engine.cutscene_runtime import FIGHT_RETARGET_SECONDS
from engine.logic_thread import LogicThread
from engine.threaded_game_state import ThreadedGameState
from tests.helpers.worlds import make_thing

pytestmark = pytest.mark.qt


@pytest.fixture
def logic(request):
    runtime = LogicThread(ThreadedGameState(), EditorState())
    request.addfinalizer(runtime.stop)
    return runtime


def _actor(name, x, z=0.0, **props):
    return make_thing(Monster, name, (x, 0.0, z), id=name, health=100, **props)


def _play(logic, actors, events=(), tracks=None):
    logic.editor_state.things[:] = list(actors)
    logic.world_runtime.build_entity_caches()
    camera = make_thing(LogicCamera, "cam", (0.0, 200.0, 0.0))
    emitted = []
    logic._plugin_emit = lambda name, **data: emitted.append((name, data))
    data = {
        "camera": [{"time": 0.0, "pos": [0, 200, 0]}, {"time": 30.0, "pos": [0, 200, 0]}],
        "actors": [{"id": a.properties["id"], "name": a.properties["name"]} for a in actors],
        "actor_tracks": tracks or {},
        "events": list(events),
    }
    assert logic.cutscene_runtime._start_json_cutscene(camera, "story.json", data)
    return logic.cutscene_runtime, emitted


def _step(runtime, seconds, dt=0.05):
    for _ in range(int(round(seconds / dt))):
        if runtime.state is None:
            return
        runtime._update_json_cutscene(dt)


def test_say_and_think_lines_go_to_the_game_at_their_time(logic):
    hero = _actor("hero", 0.0)
    runtime, emitted = _play(logic, [hero], events=[
        {"time": 0.5, "type": "say", "actor": "hero", "text": "For the Vale!", "duration": 2.0},
        {"time": 1.0, "type": "think", "actor": "hero", "text": "I hope they hold."},
    ])
    _step(runtime, 0.4)
    assert not [e for e in emitted if e[0] == "cutscene.line"]
    _step(runtime, 0.8)
    lines = [data for name, data in emitted if name == "cutscene.line"]
    assert [(l["kind"], l["text"], l["actor"]) for l in lines] == [
        ("say", "For the Vale!", hero), ("think", "I hope they hold.", hero)]
    assert lines[0]["seconds"] == 2.0 and lines[1]["seconds"] == 3.0


def test_a_battle_sets_each_fighter_on_its_nearest_living_foe_both_ways(logic):
    a1, a2 = _actor("a1", 0.0), _actor("a2", 0.0, 400.0)
    d1, d2 = _actor("d1", 100.0), _actor("d2", 100.0, 420.0)
    runtime, emitted = _play(logic, [a1, a2, d1, d2], events=[
        {"time": 0.0, "type": "fight", "duration": 5.0,
         "attackers": ["a1", "a2"], "defenders": ["d1", "d2"]}])
    _step(runtime, 0.1)
    aim = {a.properties["id"]: a.properties.get("_aggro_target") for a in (a1, a2, d1, d2)}
    assert aim == {"a1": id(d1), "a2": id(d2), "d1": id(a1), "d2": id(a2)}
    assert all(not a.properties.get("disabled") and a.properties["awake"]
               for a in (a1, a2, d1, d2))
    assert runtime.simulating()
    assert ("cutscene.fight", True) in [(n, d.get("started")) for n, d in emitted]


def test_a_fighter_whose_foe_falls_turns_to_the_next(logic):
    a1 = _actor("a1", 0.0)
    d1, d2 = _actor("d1", 100.0), _actor("d2", 300.0)
    runtime, _ = _play(logic, [a1, d1, d2], events=[
        {"time": 0.0, "type": "fight", "duration": 5.0,
         "attackers": ["a1"], "defenders": ["d1", "d2"]}])
    _step(runtime, 0.1)
    assert a1.properties["_aggro_target"] == id(d1)
    d1.properties.update(dead=True, health=0)
    _step(runtime, FIGHT_RETARGET_SECONDS + 0.1)
    assert a1.properties["_aggro_target"] == id(d2)


def test_without_mutual_the_defenders_do_not_fight_back(logic):
    a1, d1 = _actor("a1", 0.0), _actor("d1", 100.0)
    runtime, _ = _play(logic, [a1, d1], events=[
        {"time": 0.0, "type": "fight", "duration": 5.0, "mutual": False,
         "attackers": ["a1"], "defenders": ["d1"]}])
    _step(runtime, 0.1)
    assert a1.properties["_aggro_target"] == id(d1)
    assert "_aggro_target" not in d1.properties and d1.properties.get("disabled")


def test_after_a_battle_its_survivors_walk_on_from_where_it_left_them(logic):
    a1, d1 = _actor("a1", 0.0), _actor("d1", 100.0)
    tracks = {"a1": [{"time": 0.0, "pos": [0, 0, 0], "yaw": 0.0},
                     {"time": 4.0, "pos": [1000, 0, 0], "yaw": 0.0}]}
    runtime, _ = _play(logic, [a1, d1], tracks=tracks, events=[
        {"time": 1.0, "type": "fight", "duration": 1.0,
         "attackers": ["a1"], "defenders": ["d1"]}])
    _step(runtime, 1.2)
    a1.pos = [500.0, 0.0, 777.0]           # where the fight took it
    _step(runtime, 0.2)
    assert list(a1.pos) == [500.0, 0.0, 777.0]      # the battle has it, not the track
    _step(runtime, 0.65)                   # the fight is over (t > 2.0)
    assert a1.properties.get("disabled")   # back in the cutscene's hands
    x, _y, z = a1.pos
    assert 500.0 < x < 1000.0 and 0.0 < z < 777.0   # on from there, not a jump back


def test_the_dead_stay_dead_where_they_fell_and_the_living_go_back(logic):
    a1, d1 = _actor("a1", 0.0), _actor("d1", 100.0)
    runtime, _ = _play(logic, [a1, d1], events=[
        {"time": 0.0, "type": "fight", "duration": 0.5,
         "attackers": ["a1"], "defenders": ["d1"]}])
    _step(runtime, 0.1)
    d1.pos = [150.0, 0.0, 30.0]
    d1.properties.update(dead=True, health=0)
    a1.pos = [120.0, 0.0, 0.0]
    runtime._finish_json_cutscene(runtime.state)
    assert list(d1.pos) == [150.0, 0.0, 30.0] and d1.properties["dead"]
    assert list(a1.pos) == [0.0, 0.0, 0.0]


def test_the_dead_say_nothing(logic):
    hero = _actor("hero", 0.0, dead=True)
    runtime, emitted = _play(logic, [hero], events=[
        {"time": 0.0, "type": "say", "actor": "hero", "text": "..."}])
    _step(runtime, 0.1)
    assert not [e for e in emitted if e[0] == "cutscene.line"]


def test_the_cutscene_tick_runs_combat_only_while_a_battle_simulates(logic, monkeypatch):
    import glm
    from engine.player import Player
    logic.player_runtime.player = Player(0.0, 0.0)
    a1, d1 = _actor("a1", 0.0), _actor("d1", 100.0)
    runtime, emitted = _play(logic, [a1, d1], events=[
        {"time": 1.0, "type": "fight", "duration": 1.0,
         "attackers": ["a1"], "defenders": ["d1"]}])
    flown = []
    monkeypatch.setattr(logic.combat_runtime, "_update_monster_projectiles",
                        lambda dt: flown.append(dt))
    logic._tick_play_mode(0.5)
    assert not flown and not [e for e in emitted if e[0] == "cutscene.tick"]
    logic._tick_play_mode(0.6)             # t = 1.1: the battle is on
    assert flown and [e for e in emitted if e[0] == "cutscene.tick"]


def test_a_parked_actor_fights_in_full_and_is_parked_again_after(logic):
    guard = _actor("guard", 0.0, triggered=True)        # a peaceful townsman
    bandit = _actor("bandit", 100.0)
    runtime, _ = _play(logic, [guard, bandit], events=[
        {"time": 0.0, "type": "fight", "duration": 0.5,
         "attackers": ["bandit"], "defenders": ["guard"]}])
    _step(runtime, 0.1)
    assert guard.properties["triggered"] is False and guard.properties["awake"]
    _step(runtime, 0.6)
    assert guard.properties["triggered"] is True
    assert "triggered" not in bandit.properties or bandit.properties["triggered"] is False


# -- triggers: what the cutscene editor's Trigger settings ask for -------------
def _story_camera(logic, tmp_path, monkeypatch, mode, **props):
    import json
    (tmp_path / "cutscenes").mkdir(exist_ok=True)
    (tmp_path / "cutscenes" / "scene.json").write_text(json.dumps({
        "camera": [{"time": 0.0, "pos": [0, 0, 0]}, {"time": 2.0, "pos": [0, 0, 0]}],
        "actors": [], "events": [], "settings": props.pop("settings", {})}))
    monkeypatch.setattr(logic, "root_dir", str(tmp_path), raising=False)
    cam = make_thing(LogicCamera, "story_cam", (1000.0, 300.0, 0.0), id="story-cam",
                     cutscene_file="cutscenes/scene.json",
                     cutscene_trigger_mode=mode, **props)
    logic.editor_state.things[:] = [cam]
    logic.world_runtime.build_entity_caches()
    from engine.player import Player
    logic.player_runtime.player = Player(0.0, 0.0)
    emitted = []
    logic._plugin_emit = lambda name, **data: emitted.append((name, data))
    return cam, emitted


def _walk_to(logic, x):
    import glm
    logic.player_runtime.player.pos = glm.vec3(x, 0.0, 0.0)
    logic.cutscene_runtime.check_triggers()


def test_a_play_start_cutscene_starts_once_play_begins(logic, tmp_path, monkeypatch):
    cam, emitted = _story_camera(logic, tmp_path, monkeypatch, "play_start", cutscene_once=True)
    runtime = logic.cutscene_runtime
    runtime.check_triggers()
    assert runtime.state is not None and runtime.state["entity"] is cam
    assert ("cutscene.played", "story-cam") in [(n, d.get("id")) for n, d in emitted]
    runtime._finish_json_cutscene(runtime.state)
    runtime.check_triggers()
    assert runtime.state is None                      # once


def test_a_proximity_cutscene_starts_when_the_player_walks_into_its_radius(logic, tmp_path, monkeypatch):
    _story_camera(logic, tmp_path, monkeypatch, "proximity",
                  cutscene_trigger_radius=200.0, cutscene_once=False)
    runtime = logic.cutscene_runtime
    _walk_to(logic, 500.0)
    assert runtime.state is None
    _walk_to(logic, 900.0)                            # 100 from it, across the ground
    assert runtime.state is not None
    runtime._finish_json_cutscene(runtime.state)
    _walk_to(logic, 950.0)
    assert runtime.state is None                      # still inside: not again
    _walk_to(logic, 0.0)
    _walk_to(logic, 950.0)                            # walked out and back in
    assert runtime.state is not None


def test_a_cutscene_the_save_remembers_as_played_does_not_play_again(logic, tmp_path, monkeypatch):
    _story_camera(logic, tmp_path, monkeypatch, "play_start", cutscene_once=True)
    runtime = logic.cutscene_runtime
    runtime.played.add("story-cam")                   # what the game's save put back
    runtime.check_triggers()
    assert runtime.state is None
    runtime.reset_triggers()                          # a new Play from the editor
    runtime.check_triggers()
    assert runtime.state is not None


@pytest.mark.parametrize("allowed", [True, False])
def test_escape_ends_a_cutscene_only_if_it_lets_itself_be_stopped(logic, tmp_path, monkeypatch, allowed):
    cam, emitted = _story_camera(logic, tmp_path, monkeypatch, "play_start",
                                 settings={"stop_on_escape": allowed})
    fired = []
    monkeypatch.setattr(logic.io_manager, "fire_output",
                        lambda entity, output, value=None: fired.append(output))
    runtime = logic.cutscene_runtime
    runtime.check_triggers()
    assert runtime.skip() is allowed
    assert (runtime.state is None) is allowed
    assert ("OnFinished" in fired) is allowed         # the story carries on


def test_spawned_actors_never_appear_on_top_of_each_other(logic):
    from engine.cutscene_runtime import CutsceneRuntime
    defs = [{"id": f"s{i}", "name": f"s{i}", "spawn": True,
             "definition": {"type": "monster", "pos": [10.0, 0.0, 10.0], "properties": {"health": 50}}}
            for i in range(6)]
    logic.editor_state.things[:] = []
    logic.world_runtime.build_entity_caches()
    camera = make_thing(LogicCamera, "cam", (0.0, 200.0, 0.0))
    logic._plugin_emit = lambda *a, **k: None
    assert logic.cutscene_runtime._start_json_cutscene(
        camera, "s.json", {"camera": [{"time": 0.0, "pos": [0, 0, 0]}], "actors": defs, "events": []})
    pts = [(float(a.pos[0]), float(a.pos[2])) for a in logic.cutscene_runtime.state["spawned_actors"]]
    gap = CutsceneRuntime.SPAWN_SPACING - 1e-6
    assert len(pts) == 6 and all((x1 - x2) ** 2 + (z1 - z2) ** 2 >= gap * gap
                                 for i, (x1, z1) in enumerate(pts) for (x2, z2) in pts[i + 1:])


def test_actors_turn_the_short_way_and_face_as_authored(logic):
    hero = _actor("hero", 0.0, angle=350.0)
    tracks = {"hero": [{"time": 0.0, "pos": [0, 0, 0], "yaw": 350.0},
                       {"time": 2.0, "pos": [0, 0, 0], "yaw": 10.0}]}
    runtime, _ = _play(logic, [hero], tracks=tracks)
    _step(runtime, 1.0)
    angle = hero.properties["angle"]
    assert angle > 355.0 or angle < 5.0                 # through 0, not round by 180
    _step(runtime, 1.1)
    assert hero.properties["angle"] == pytest.approx(10.0, abs=0.5)


def test_a_top_down_cutscene_follows_its_actor_from_above(logic):
    import glm
    from engine.player import Player
    hero = _actor("hero", 0.0)
    logic.cutscene_runtime.top_down = True
    logic.player_runtime.player = Player(0.0, 0.0)
    runtime, _ = _play(logic, [hero])
    runtime.state["camera_keys"] = [{"time": 0.0, "pos": [0.0, 900.0, 0.0], "yaw": 0.0,
                                     "pitch": 0.0, "look_at": {"actor": "hero"}}]
    hero.pos = [300.0, 0.0, -200.0]
    _step(runtime, 0.1)
    assert runtime.state["top_down"] and runtime.state["cam_pos"] == [300.0, 900.0, -200.0]
    # Drawn straight down, the top of the screen the way it is in play.
    import math
    logic.session_runtime.play_mode = True
    logic.render_runtime.prepare_render_state()
    view = logic.game_state.get_write_state().camera_view_matrix
    forward = glm.vec3(-view[0][2], -view[1][2], -view[2][2])    # the camera's -Z in world
    assert forward.y == pytest.approx(-1.0, abs=1e-4)
    heading = logic.camera.overhead_heading(0.0)
    up = glm.vec3(view[0][1], view[1][1], view[2][1])
    assert up.x == pytest.approx(math.sin(heading), abs=1e-4)
    assert up.z == pytest.approx(math.cos(heading), abs=1e-4)
