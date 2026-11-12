"""A machine with no working audio device must not stall on every sound.

A failed ``pygame.mixer.init`` probes the audio stack for about 100 ms on the
UI thread, and every sound request used to try again: each gunshot, door and
explosion cost a frame. The failure is now remembered and the device retried
only after a pause, so one connected later is still found.
"""

import pytest
from types import SimpleNamespace

pytest.importorskip("PyQt5", reason="the view is a Qt widget")
pygame = pytest.importorskip("pygame")

from engine import qt_game_view                               # noqa: E402

pytestmark = pytest.mark.qt


class _FailingMixer:
    def __init__(self):
        self.attempts = 0

    def get_init(self):
        return False

    def init(self, **_kwargs):
        self.attempts += 1
        raise pygame.error("no audio device")


def test_a_failed_mixer_is_not_reprobed_on_every_sound(main_window, qt_app, monkeypatch):
    mixer = _FailingMixer()
    monkeypatch.setattr(qt_game_view.pygame, "mixer", mixer)
    clock = [100.0]
    # Patching the shared time module also rewinds the real logic thread's
    # scheduler and can leave it sleeping past Stop. Only the view uses this clock.
    # The mixer probe lives in engine.view_audio (Fio 3.5 split it out of the
    # view): swap that module's clock, not the shared time module.
    from engine import view_audio
    monkeypatch.setattr(view_audio, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
    view = qt_game_view.QtGameView(main_window)
    try:
        ensure = view.audio._ensure_pygame_mixer

        # Construction performs the first real mixer probe. Repeated sound
        # requests must not probe again until the retry window expires.
        # __init__ probes once before _init_sound_system performs the
        # shared retry probe; the important contract is that no third probe
        # occurs until the retry window expires.
        assert mixer.attempts == 2

        for _ in range(20):
            assert ensure() is False
        assert mixer.attempts == 2

        clock[0] += view.audio.MIXER_RETRY_SECONDS
        assert ensure() is False
        assert mixer.attempts == 3, "a device connected later would never be found"
    finally:
        view.deleteLater()
        qt_app.processEvents()
