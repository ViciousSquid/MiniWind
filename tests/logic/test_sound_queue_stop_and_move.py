"""The sound queue's 'stoppable' one-shots and 'move' (engine/view_audio.py):
a game can cut a one-shot short and keep a tracked sound on a moving source,
and the mix follows it -- nearer the listener louder, off to one side panned."""

from types import SimpleNamespace

import pytest

pygame = pytest.importorskip("pygame")
glm = pytest.importorskip("glm")

from engine.view_audio import ViewAudio  # noqa: E402


class _Channel:
    def __init__(self):
        self.stopped = False
        self.volume = None

    def stop(self):
        self.stopped = True

    def set_volume(self, *v):
        self.volume = v


class _Sound:
    def __init__(self):
        self.channels = []

    def play(self, loops=0):
        channel = _Channel()
        self.channels.append((loops, channel))
        return channel


class _AudioView:
    def __init__(self, camera, game_state):
        self.camera = camera
        self.game_state = game_state


def _audio(requests):
    pending = list(requests)
    camera = SimpleNamespace(pos=glm.vec3(0.0, 0.0, 0.0),
                             get_front_vector=lambda: glm.vec3(0.0, 0.0, -1.0))
    view = _AudioView(camera, SimpleNamespace(
        consume_sounds=lambda: [pending.pop(0) for _ in range(len(pending))]))
    audio = ViewAudio(view)
    sound = _Sound()
    audio._get_sound_instance = lambda _name: sound
    return audio, sound, pending


def test_a_stoppable_one_shot_is_tracked_and_can_be_cut_short():
    audio, sound, pending = _audio([{"file": "bow_draw.mp3", "position": [100.0, 0.0, 0.0],
                                     "radius": 900.0, "entity_id": "bow", "stoppable": True}])
    audio._process_sound_queue()
    loops, channel = sound.channels[0]
    assert loops == 0 and "bow" in audio._speaker_channels
    pending.append({"action": "stop", "entity_id": "bow"})
    audio._process_sound_queue()
    assert channel.stopped and "bow" not in audio._speaker_channels


def test_an_ordinary_one_shot_is_still_not_tracked():
    audio, sound, _pending = _audio([{"file": "ding.wav", "entity_id": "x"}])
    audio._process_sound_queue()
    assert "x" not in audio._speaker_channels


def test_move_carries_a_tracked_sound_with_its_source_and_the_mix_follows():
    audio, sound, pending = _audio([{"file": "bow_draw.mp3", "position": [600.0, 0.0, 0.0],
                                     "radius": 900.0, "entity_id": "bow", "stoppable": True}])
    audio._process_sound_queue()
    channel = sound.channels[0][1]
    far_left, far_right = channel.volume
    assert far_right > far_left                      # off to the right, panned right
    pending.append({"action": "move", "entity_id": "bow", "position": [-100.0, 0.0, 0.0]})
    audio._process_sound_queue()
    near_left, near_right = channel.volume
    assert near_left > near_right                    # now just to the left
    assert near_left + near_right > far_left + far_right   # and nearer: louder
    assert audio._speaker_mix["bow"]["position"] == [-100.0, 0.0, 0.0]


def test_move_for_an_unknown_sound_is_harmless():
    audio, _sound, pending = _audio([{"action": "move", "entity_id": "nobody",
                                      "position": [1.0, 2.0, 3.0]}])
    audio._process_sound_queue()
    assert audio._speaker_channels == {}
