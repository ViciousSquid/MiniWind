"""The ``worldmap`` console command's window (game/ui/worldmap_window.py):
the editor camera in the editor, the player in Play."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from game.ui import worldmap_window as wmw  # noqa: E402


def test_in_play_it_marks_the_player_facing_as_the_pause_map_does(monkeypatch):
    player = SimpleNamespace(pos=[1200.0, 80.0, -340.0], angle=math.pi / 2)
    monkeypatch.setattr("game.fio.player", lambda logic: player)
    x, z, fx, fz, label = wmw._player_marker(object())
    assert (x, z, label) == (1200.0, -340.0, "Player")
    assert fx == pytest.approx(1.0) and fz == pytest.approx(0.0, abs=1e-9)


def test_without_a_player_there_is_no_marker(monkeypatch):
    monkeypatch.setattr("game.fio.player", lambda logic: None)
    assert wmw._player_marker(object()) is None


def test_in_the_editor_it_marks_the_editor_camera():
    cam = SimpleNamespace(pos=SimpleNamespace(x=10.0, y=900.0, z=20.0), yaw=0.0)
    assert wmw._camera_marker(cam) == (10.0, 20.0, 1.0, 0.0, "Editor camera")
    assert wmw._camera_marker(None) is None


def test_a_click_in_play_teleports_the_player_onto_the_ground(monkeypatch):
    queued = []
    monkeypatch.setattr("game.ui.hits.queue", queued.append)
    terrain = SimpleNamespace(get_height_at_safe=lambda x, z: 150.0)
    player = SimpleNamespace(pos=[0.0, 0.0, 0.0])
    monkeypatch.setattr("game.fio.terrain", lambda logic: terrain)
    monkeypatch.setattr("game.fio.player", lambda logic: player)
    wmw.teleport_player(500.0, -700.0)
    assert len(queued) == 1, "the move waits for the game tick, which owns the session"
    went = []
    queued[0](SimpleNamespace(logic=object(), teleport_player=went.append))
    assert went == [(500.0, 154.0, -700.0)]


def test_the_command_opens_the_window_in_play_too(monkeypatch):
    from game import console
    opened = []
    monkeypatch.setattr(wmw, "toggle", opened.append)
    window = object()
    console.cmd_worldmap(SimpleNamespace(play_mode=True, main_window=window), "")
    console.cmd_worldmap(SimpleNamespace(play_mode=False, main_window=window), "")
    assert opened == [window, window]
