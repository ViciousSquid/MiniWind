import json
import math


def test_cutscene_files_save_and_load(tmp_path):
    from game.cutscene_files import load_cutscene, save_cutscene

    data = {
        "version": 2,
        "id": "battle_intro",
        "name": "Battle Intro",
        "camera": [{"time": 0, "pos": [1, 2, 3]}],
        "actor_tracks": {"a": [{"time": 0, "pos": [4, 5, 6], "yaw": 0.5}]},
        "events": [{"time": 2, "type": "blood", "position": [10, 0, 20]}],
    }
    path = save_cutscene(data, "battle_intro.json", root=str(tmp_path))
    assert path
    assert load_cutscene("battle_intro.json", root=str(tmp_path)) == data


def test_cutscene_normalises_timeline():
    from game.cutscene import normalise_cutscene

    data = normalise_cutscene(json.dumps({
        "version": 2,
        "actors": [{"id": "a", "name": "Guard"}],
        "camera": [
            {"time": 3, "pos": [4, 5, 6], "look_at": {"actor": "a"}},
            {"time": 0, "pos": [1, 2, 3]},
        ],
        "actor_tracks": {
            "a": [
                {"time": 2, "pos": [20, 0, 0]},
                {"time": 0, "pos": [0, 0, 0], "yaw": 1},
            ]
        },
        "events": [
            {"time": 4, "type": "fight", "attackers": ["a"], "defenders": ["b"], "duration": 5},
            {"time": 1, "type": "blood", "position": [2, 0, 3]},
            {"time": 2, "type": "message", "line": "message2", "text": "Battle!"},
        ],
    }))
    assert data["camera"][0]["time"] == 0.0
    assert data["actor_tracks"]["a"][0]["time"] == 0.0
    assert data["events"][0]["type"] == "blood"
    assert data["events"][1]["type"] == "message"
    assert data["events"][2]["duration"] == 5.0


def test_cutscene_camera_look_at_uses_engine_angle_convention():
    from game.cutscene import _angle_to

    yaw, pitch = _angle_to([0, 100, 0], [10, 110, 0])
    assert math.isclose(yaw, math.pi / 2, rel_tol=1e-6)
    assert pitch > 0


def test_cutscene_manager_loads_external_json_and_restores_actor(monkeypatch):
    from game.cutscene import CutsceneManager

    class P:
        def __init__(self, pos):
            self.pos = list(pos)
            self.angle = 0.25
            self.properties = {
                "id": "actor",
                "display_name": "Actor",
                "health": 100,
                "triggered": False,
            }

    class Logic:
        def __init__(self):
            self.things = [P([9, 9, 9])]
            self.player = P([0, 0, 0])
            self.cinematic_state = None
            self.io_manager = None

    class Session:
        def __init__(self):
            self.logic = Logic()

    session = Session()
    manager = CutsceneManager(session)
    scene = P([0, 0, 0])
    scene.properties = {
        "id": "scene",
        "cutscene_file": "scene.json",
        "once": True,
        "restore_actors": True,
    }
    session.logic.things.append(scene)

    monkeypatch.setattr(
        "game.cutscene.cutscene_files.load_cutscene",
        lambda filename: {
            "version": 2,
            "id": "scene",
            "name": "Scene",
            "actors": [{"id": "actor", "name": "Actor"}],
            "camera": [
                {"time": 0, "pos": [0, 10, 0], "yaw": 0, "pitch": 0, "fov": 90},
                {"time": 1, "pos": [10, 10, 0], "yaw": 0, "pitch": 0, "fov": 90},
            ],
            "actor_tracks": {
                "actor": [
                    {"time": 0, "pos": [100, 2, 300], "yaw": 1.5},
                    {"time": 1, "pos": [120, 2, 300], "yaw": 1.5},
                ]
            },
            "events": [],
            "settings": {"restore_actors": True},
        },
    )

    assert manager.start(scene)
    manager.tick(0.5)
    assert manager.active
    assert session.logic.things[0].pos[0] > 100.0

    manager.stop()
    assert list(session.logic.things[0].pos) == [9, 9, 9]
    assert session.logic.things[0].properties["health"] == 100


def test_cutscene_dialogue_and_message_events_are_time_based(monkeypatch):
    from game.cutscene import CutsceneManager

    class P:
        def __init__(self, pos):
            self.pos = list(pos)
            self.angle = 0.0
            self.properties = {"id": "actor", "display_name": "Actor"}

    class Logic:
        def __init__(self):
            self.things = [P([0, 0, 0])]
            self.player = P([0, 0, 0])
            self.cinematic_state = None
            self.io_manager = None

    class Session:
        def __init__(self):
            self.logic = Logic()

        def _things_of_type(self, t):
            return [x for x in self.logic.things if x.properties.get("type") == t]

        def _player_pos(self):
            return [0, 0, 0]

        def _dist2d(self, a, b):
            return math.hypot(a[0] - b[0], a[2] - b[2])

    session = Session()
    manager = CutsceneManager(session)
    scene = P([0, 0, 0])
    scene.properties = {
        "id": "scene",
        "cutscene_file": "scene.json",
        "once": False,
    }
    session.logic.things.append(scene)
    monkeypatch.setattr(
        "game.cutscene.cutscene_files.load_cutscene",
        lambda filename: {
            "version": 2,
            "name": "Dialogue",
            "actors": [{"id": "actor", "name": "Actor"}],
            "camera": [{"time": 0, "pos": [0, 10, 0]}],
            "actor_tracks": {},
            "events": [
                {
                    "time": 0.2,
                    "type": "dialogue",
                    "speaker_id": "actor",
                    "duration": 0.5,
                    "text": "Watch the hill.",
                },
                {
                    "time": 0.2,
                    "type": "message",
                    "line": "message2",
                    "text": "Battle!",
                },
            ],
            "settings": {},
        },
    )

    assert manager.start(scene)
    manager.tick(0.1)
    assert manager.dialogue is None
    manager.tick(0.15)
    assert manager.dialogue["text"] == "Watch the hill."
    assert manager.message_lines["message2"] == "Battle!"
    manager.tick(0.6)
    assert manager.dialogue is None
