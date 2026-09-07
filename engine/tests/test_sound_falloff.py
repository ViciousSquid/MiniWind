"""
Tests for speaker distance falloff (:mod:`engine.sound_falloff`).

A Speaker entity has always carried a ``radius``, but nothing used it: every
sound played at its authored volume wherever the player stood, so a fountain
across the village was as loud as one underfoot. Sound now fades linearly to
silence at the radius.

Linear, not inverse-square, on purpose: the radius drawn in the editor is then
exactly where the sound stops, which is what makes it authorable.

Run:  python -m pytest engine/tests/test_sound_falloff.py -q
"""

from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from engine import sound_falloff as sf


def test_full_volume_at_the_speaker_and_silence_at_its_edge():
    assert sf.distance_volume(1.0, 0.0, 512.0) == 1.0
    assert sf.distance_volume(1.0, 512.0, 512.0) == 0.0


def test_the_fade_is_a_straight_line():
    for fraction in (0.25, 0.5, 0.75):
        got = sf.distance_volume(1.0, 512.0 * fraction, 512.0)
        assert math.isclose(got, 1.0 - fraction)


def test_beyond_the_radius_is_silent_not_negative():
    assert sf.distance_volume(1.0, 5000.0, 512.0) == 0.0


def test_the_authored_volume_scales_the_whole_curve():
    assert math.isclose(sf.distance_volume(0.5, 256.0, 512.0), 0.25)
    assert sf.distance_volume(0.0, 0.0, 512.0) == 0.0


def test_a_global_speaker_ignores_distance():
    """Music beds and narration play everywhere."""
    assert sf.distance_volume(0.8, 99999.0, 512.0, is_global=True) == 0.8


def test_a_speaker_with_no_range_is_treated_as_unbounded():
    """An under-configured speaker should still be audible, not silent."""
    assert sf.distance_volume(1.0, 4000.0, 0.0) == 1.0
    assert sf.distance_volume(1.0, 4000.0, -1.0) == 1.0


def test_nonsense_values_do_not_break_the_mix():
    assert sf.distance_volume(None, 0.0, 512.0) == 1.0
    assert sf.distance_volume("loud", 0.0, 512.0) == 1.0
    assert sf.distance_volume(1.0, "far", 512.0) == 1.0
    assert sf.distance_volume(5.0, 0.0, 512.0) == 1.0        # clamped to 1
    assert sf.distance_volume(-2.0, 0.0, 512.0) == 0.0


def test_distance_is_measured_in_three_dimensions():
    assert math.isclose(sf.distance_between([0, 0, 0], [3, 4, 0]), 5.0)
    assert math.isclose(sf.distance_between([0, 0, 0], [0, 3, 4]), 5.0)
    assert sf.distance_between(None, [1, 2, 3]) == 0.0
    assert sf.distance_between([1, 2, 3], []) == 0.0


def test_volume_for_reads_a_live_speaker_record():
    speaker = {"pos": [0, 0, 256], "volume": 1.0, "radius": 512.0}
    assert math.isclose(sf.volume_for([0, 0, 0], speaker), 0.5)
    assert math.isclose(sf.volume_for([0, 0, 256], speaker), 1.0)
    assert sf.volume_for([0, 0, 1000], speaker) == 0.0


def test_walking_away_only_ever_gets_quieter():
    speaker = {"pos": [0, 0, 0], "volume": 1.0, "radius": 800.0}
    volumes = [sf.volume_for([0, 0, d], speaker) for d in range(0, 1000, 50)]
    assert volumes == sorted(volumes, reverse=True)
    assert volumes[0] == 1.0 and volumes[-1] == 0.0


def test_a_speaker_sends_its_position_and_range_with_the_sound():
    """The two halves of the feature have to agree.

    The falloff maths lives in the view, which mixes on the render thread; it
    can only do that if the play request carries where the speaker stands and
    how far it carries. This pins that contract at the point it is written.
    """
    import pytest

    io_module = pytest.importorskip("editor.io_handlers")
    io_system = pytest.importorskip("editor.io_system")

    queued = []

    class _GameState:
        def queue_sound(self, request):
            queued.append(request)

    class _Logic:
        active_speakers = set()

        def __init__(self, io_manager):
            self.io_manager = io_manager
            self.game_state = _GameState()

    class _Speaker:
        pos = [100.0, 20.0, -300.0]
        properties = {"name": "fountain", "sound_file": "water.wav",
                      "volume": 0.8, "looping": True, "radius": 640.0,
                      "global": False}

    # These handlers log to the editor console. Its Qt-backed singleton may
    # already have been torn down by another test's QApplication, and the
    # request payload is what is under test, not the logging — so swap the
    # logger itself, which every logging path goes through.
    console = pytest.importorskip("editor.debug_console")

    class _Silent:
        def log(self, *a, **kw):
            pass

    real_logger = console._debug_logger
    console._debug_logger = _Silent()
    try:
        manager = io_system.IOManager()
        io_module.register_all_input_handlers(manager)
        play = manager._input_handlers[("speaker", "playsound")]
        play(_Speaker(), None, _Logic(manager))
    finally:
        console._debug_logger = real_logger

    assert len(queued) == 1
    request = queued[0]
    assert request["pos"] == [100.0, 20.0, -300.0]
    assert request["radius"] == 640.0
    assert request["global"] is False
    # And the request is enough on its own to mix the sound.
    assert math.isclose(sf.volume_for([100.0, 20.0, 20.0], request), 0.4, abs_tol=1e-6)
