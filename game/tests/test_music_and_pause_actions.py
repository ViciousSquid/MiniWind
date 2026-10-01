"""
MiniWind's soundtrack (:mod:`game.music`) and what the pause menu's options do
(:mod:`game.ui.pause_actions`).

The music must play every ``.mp3`` in its folder, shuffled and never the same
track twice in a row, only while a play session runs, and the pause menu's
switch must silence it at once and be remembered in settings.ini. A pause-menu
save must carry MiniWind's store (the character, quests and clock) as well as
the world, and loading it must put that store back before play restarts.

Run:  python -m pytest game/tests/test_music_and_pause_actions.py -q
"""

from __future__ import annotations

import configparser
import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

pytest.importorskip("PyQt5.QtCore")

from ..music import MusicPlayer, SETTING      # noqa: E402
from ..ui import pause_actions                # noqa: E402
from ..ui.pause_actions import PauseActions   # noqa: E402


class _Mixer:
    """pygame.mixer.music, recorded."""

    def __init__(self):
        self.loaded = []
        self.busy = False
        self.stopped = 0
        self.volume = None

    def load(self, path):
        self.loaded.append(os.path.basename(path))

    def play(self):
        self.busy = True

    def stop(self):
        self.busy = False
        self.stopped += 1

    def set_volume(self, v):
        self.volume = v

    def get_busy(self):
        return self.busy


@pytest.fixture
def music_dir(tmp_path):
    for name in ("a.mp3", "b.mp3", "c.MP3", "notes.txt"):
        (tmp_path / name).write_bytes(b"")
    return str(tmp_path)


def _player(music_dir, mixer=None):
    return MusicPlayer(music_dir, backend=mixer or _Mixer(), rng=random.Random(3))


# ------------------------------------------------------------------- music

def test_every_mp3_in_the_folder_is_a_track(music_dir):
    names = [os.path.basename(t) for t in _player(music_dir).tracks()]
    assert names == ["a.mp3", "b.mp3", "c.MP3"]


def test_music_plays_only_while_a_session_runs(music_dir):
    mixer = _Mixer()
    player = _player(music_dir, mixer)
    assert mixer.loaded == []
    player.start()
    assert len(mixer.loaded) == 1 and mixer.busy
    player.stop()
    assert not mixer.busy and player.current is None


def test_a_finished_track_is_followed_by_the_next_without_repeats(music_dir):
    mixer = _Mixer()
    player = _player(music_dir, mixer)
    player.start()
    for n in range(8):
        mixer.busy = False            # the track ended
        player.poll(now=1000.0 + n * 10)
    assert len(mixer.loaded) == 9
    assert all(a != b for a, b in zip(mixer.loaded, mixer.loaded[1:]))
    # Each full pass plays every track once.
    assert sorted(mixer.loaded[:3]) == ["a.mp3", "b.mp3", "c.MP3"]


def test_switching_music_off_silences_it_and_is_remembered(music_dir):
    mixer = _Mixer()
    config = configparser.ConfigParser()
    saved = []
    player = _player(music_dir, mixer)
    player.configure(config, lambda: saved.append(True))
    player.start()
    assert player.toggle() is False
    assert not mixer.busy and player.current is None
    assert config.getboolean(*SETTING) is False and saved
    mixer.busy = False
    player.poll(now=1e6)
    assert len(mixer.loaded) == 1     # off means off: no next track either
    player.toggle()
    assert mixer.busy and len(mixer.loaded) == 2


def test_music_off_in_settings_starts_silent(music_dir):
    config = configparser.ConfigParser()
    config.read_dict({"GAME": {"music": "False"}})
    mixer = _Mixer()
    player = _player(music_dir, mixer)
    player.configure(config)
    player.start()
    assert mixer.loaded == [] and not player.enabled


def test_no_mixer_means_no_music_and_no_error(music_dir):
    player = MusicPlayer(music_dir)          # no backend, no pygame mixer
    player.start()
    player.poll(now=1e6)
    player.toggle()
    player.stop()


def test_an_empty_folder_is_silence(tmp_path):
    mixer = _Mixer()
    player = _player(str(tmp_path / "missing"), mixer)
    player.start()
    assert mixer.loaded == []


# ----------------------------------------------------------- pause actions

class _Store:
    _name = "miniwind"


class _Session:
    def __init__(self):
        self.store = _Store()
        self.persisted = 0

    def persist(self, force=False):
        self.persisted += 1


class _Logic:
    def __init__(self):
        self._miniwind = _Session()


class _Console:
    def __init__(self, root, window):
        self.root = root
        self.window = window
        self.loaded = []

    def _resolve_save_path(self, name):
        return os.path.join(self.root, name + ".fiosave")

    def cmd_save(self, name):
        with open(self._resolve_save_path(name), "w") as fh:
            json.dump({"fio_savegame": True, "map": "village.json",
                       "saved_at": "2026-10-01T10:00:00"}, fh)

    def cmd_load(self, name):
        self.loaded.append((name, dict(pause_actions._global_store().all(
            store="miniwind")), self.window.view.play_mode))


class _Window:
    def __init__(self, root, view):
        self.view = view
        self.console_handler = _Console(root, self)
        self.toasts = []
        self.exits = 0

    def show_toast(self, message, is_error=False):
        self.toasts.append((message, is_error))

    def _exit_play_mode(self):
        self.exits += 1
        self.view.play_mode = False


class _View:
    def __init__(self, root):
        self.play_mode = True
        self.logic_thread = _Logic()
        self.editor = _Window(root, self)


@pytest.fixture
def actions(tmp_path):
    store = pause_actions._global_store()
    before = store.all(store="miniwind")
    for key in store.keys(store="miniwind"):
        store.delete(key, store="miniwind")
    yield PauseActions(_View(str(tmp_path)), music=MusicPlayer(str(tmp_path)))
    for key in store.keys(store="miniwind"):
        store.delete(key, store="miniwind")
    for key, value in before.items():
        store.set(key, value, store="miniwind")


def test_a_save_carries_the_character_store(actions):
    store = pause_actions._global_store()
    store.set("_character", json.dumps({"name": "Aldric", "level": 4}), store="miniwind")
    store.set("_clock_day", "3", store="miniwind")
    assert actions.pause_menu_save_slot(2)
    assert actions.view.logic_thread._miniwind.persisted == 1   # flushed first
    with open(actions.slot_path(2)) as fh:
        block = json.load(fh)["miniwind"]
    assert block["store"] == "miniwind"
    assert block["values"]["_clock_day"] == "3"
    info = actions.pause_menu_slot_info()
    assert info[0] is None and info[2] is None
    assert info[1]["summary"] == "Aldric, level 4"


def test_loading_puts_the_store_back_before_play_restarts(actions):
    store = pause_actions._global_store()
    store.set("_character", json.dumps({"name": "Aldric", "level": 4}), store="miniwind")
    actions.pause_menu_save_slot(1)
    store.set("_character", json.dumps({"name": "Somebody else"}), store="miniwind")
    store.set("stray_key", "1", store="miniwind")

    assert actions.pause_menu_load_slot(1)
    window = actions.window
    assert window.exits == 1
    name, values, playing = window.console_handler.loaded[-1]
    assert name == "slot1"
    assert not playing                       # stopped before the store swap
    assert json.loads(values["_character"])["name"] == "Aldric"
    assert "stray_key" not in values


def test_an_empty_slot_is_not_loaded(actions):
    assert not actions.pause_menu_load_slot(3)
    assert actions.window.console_handler.loaded == []
    assert actions.window.toasts[-1][1] is True


def test_the_volume_reaches_the_player_and_zero_is_off(actions):
    assert actions.pause_menu_music_volume() == pytest.approx(0.5)
    actions.pause_menu_set_music_volume(0.8)
    assert actions.pause_menu_music_volume() == pytest.approx(0.8)
    actions.pause_menu_set_music_volume(0.0)
    assert actions.pause_menu_music_volume() == 0.0
    assert not actions.music.enabled


def test_setting_the_volume_is_live_and_remembered(music_dir):
    mixer = _Mixer()
    config = configparser.ConfigParser()
    player = _player(music_dir, mixer)
    player.configure(config)
    player.start()
    player.set_volume(0.3)
    assert mixer.volume == pytest.approx(0.3) and mixer.busy
    assert config.get("GAME", "music_volume") == "0.30"
    player.set_volume(0.0)
    assert not mixer.busy and config.getboolean("GAME", "music") is False
    player.set_volume(0.6)                          # back on: a track starts
    assert mixer.busy and player.effective_volume == pytest.approx(0.6)


# ------------------------------------------------------------------- fonts

def test_the_menu_face_falls_back_until_its_font_is_installed(qt_app, tmp_path,
                                                              monkeypatch):
    from ..ui import fonts
    monkeypatch.setattr(fonts, "_families", None)
    monkeypatch.setattr(fonts, "FONT_DIR", str(tmp_path))
    assert fonts.menu_family() == fonts.FALLBACK_FAMILY        # empty folder

    shipped = os.path.join(os.path.dirname(__file__), "..", "..", "assets",
                           "fonts", "Rushfordclean-rgz89.otf")
    if not os.path.exists(shipped):
        pytest.skip("no bundled font to stand in for Enchanted Land")
    import shutil
    shutil.copy(shipped, tmp_path / "stand-in.otf")
    monkeypatch.setattr(fonts, "_families", None)
    monkeypatch.setattr(fonts, "MENU_FAMILY", "Rushford Clean")
    assert fonts.menu_family() == "Rushford Clean"              # found by family
