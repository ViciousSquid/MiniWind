"""Controller polling must never pump a second native window event loop."""

import os
from pathlib import Path
import subprocess
import sys

import pytest

pytestmark = pytest.mark.qt


@pytest.mark.parametrize("video_driver", ["cocoa", "windows", "dummy"])
def test_controller_startup_uses_dummy_video_even_before_a_view_exists(video_driver):
    # A fresh process catches driver selection errors that an SDL instance
    # initialized by another editor test would hide.
    env = dict(os.environ, SDL_VIDEODRIVER=video_driver, SDL_AUDIODRIVER="dummy")
    result = subprocess.run(
        [sys.executable, "-c", """
import pygame
from engine.sdl_runtime import init_input
from game.gamepad import SdlPad

pad = SdlPad()
assert pad._ok, 'controller initialization failed'
init_input()  # the view starts later: initialization is idempotent
assert pygame.display.get_driver() == 'dummy'
assert pygame.display.get_surface() is None
assert pygame.joystick.get_init()
assert not pygame.mixer.get_init(), 'input setup must leave audio to the view'
for _ in range(100):
    pygame.event.pump()
    assert pad.read() is None
pygame.event.post(pygame.event.Event(pygame.JOYDEVICEADDED, device_index=0))
assert pygame.event.get(pygame.JOYDEVICEADDED), 'hotplug events must still arrive'
pygame.quit()
"""],
        cwd=Path(__file__).resolve().parents[2], env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_editor_and_game_controller_polling_share_the_dummy_backend(main_window):
    import pygame
    from game.gamepad import SdlPad

    assert pygame.display.get_driver() == "dummy"
    pad = SdlPad()
    assert pad._ok
    for _ in range(100):
        main_window.view_3d._poll_gamepad()
        pad.read()
    assert pygame.display.get_driver() == "dummy"
    assert pygame.display.get_surface() is None
