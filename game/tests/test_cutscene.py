import json
import math


def test_cutscene_sequence_normalises_invalid_and_valid_data():
    from game.cutscene import normalise_sequence

    assert normalise_sequence("not json")["shots"] == []
    data = normalise_sequence(json.dumps({
        "actors": [{"id": "a", "pos": [1, 2, 3], "yaw": 0.5}],
        "shots": [{
            "duration": 4,
            "camera": {"pos": [4, 5, 6], "yaw": 1, "pitch": -0.25, "fov": 80},
            "look_at": "a",
            "dialogue": {"speaker_id": "a", "text": "Hello", "duration": 3},
            "messages": {"message": "One", "message2": "Two", "message3": "Three"},
        }],
    }))
    assert data["actors"][0]["pos"] == [1.0, 2.0, 3.0]
    assert data["shots"][0]["camera"]["fov"] == 80.0
    assert data["shots"][0]["dialogue"]["text"] == "Hello"
    assert data["shots"][0]["messages"]["message3"] == "Three"


def test_cutscene_camera_look_at_uses_engine_angle_convention():
    from game.cutscene import _angle_to

    yaw, pitch = _angle_to([0, 100, 0], [10, 110, 0])
    assert math.isclose(yaw, math.pi / 2, rel_tol=1e-6)
    assert pitch > 0


def test_cutscene_manager_stages_and_restores_actor():
    from game.cutscene import CutsceneManager

    class P:
        def __init__(self, pos):
            self.pos = list(pos)
            self.angle = 0.25
            self.properties = {"id": "actor", "display_name": "Actor"}

    class Logic:
        def __init__(self):
            self.things = [P([9, 9, 9])]
            self.player = P([0, 0, 0])
            self.cinematic_state = None
            self.io_manager = None

    class Session:
        def __init__(self):
            self.logic = Logic()
        def _find(self):
            return self.logic.things[0]

    session = Session()
    manager = CutsceneManager(session)
    scene = P([0, 0, 0])
    scene.properties = {
        "id": "scene",
        "once": True,
        "sequence": json.dumps({
            "actors": [{"id": "actor", "name": "Actor", "pos": [100, 2, 300], "yaw": 1.5}],
            "shots": [{"duration": 1, "camera": {"pos": [0, 10, 0], "yaw": 0, "pitch": 0, "fov": 90}}],
        }),
    }
    session.logic.things.append(scene)

    assert manager.start(scene)
    assert manager.active
    assert list(session.logic.things[0].pos) == [100.0, 2.0, 300.0]

    manager.stop()
    assert list(session.logic.things[0].pos) == [9, 9, 9]


def test_cutscene_manager_advances_to_finished_state():
    from game.cutscene import CutsceneManager

    class P:
        def __init__(self, pos):
            self.pos = list(pos)
            self.angle = 0.0
            self.properties = {"id": "x"}

    class Logic:
        def __init__(self):
            self.things = []
            self.player = P([0, 0, 0])
            self.cinematic_state = None
            self.io_manager = None
            self.game_state = None

    class Session:
        def __init__(self):
            self.logic = Logic()
        def _things_of_type(self, t):
            return [x for x in self.logic.things if x.properties.get("type") == t]
        def _find_actor(self, actor_id):
            for x in self.logic.things:
                if x.properties.get("id") == actor_id:
                    return x
        def _player_pos(self):
            return [0,0,0]
        def _dist2d(self, a,b):
            return math.hypot(a[0]-b[0],a[2]-b[2])

    session = Session()
    manager = CutsceneManager(session)
    scene = P([0,0,0])
    scene.properties = {
        "id": "scene", "once": True,
        "sequence": json.dumps({
            "actors": [],
            "shots": [
                {"duration": 0.1, "camera": {"pos": [1,2,3], "yaw": 0, "pitch": 0, "fov": 90}},
                {"duration": 0.1, "camera": {"pos": [4,5,6], "yaw": 1, "pitch": 0, "fov": 90}},
            ],
        }),
    }
    session.logic.things.append(scene)
    assert manager.start(scene)
    manager.tick(0.11)
    assert manager.active
    manager.tick(0.11)
    assert not manager.active
