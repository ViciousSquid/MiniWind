"""Optional "Restore the world when leaving Play" (Settings -> Play Modes).

Off by default: the editor keeps showing what happened in play (dead monsters,
killed or hidden objects), as it always has. On, Stop puts every brush and
entity back as it was when Play started, and the undo history and the unsaved
flag with them, so the session leaves no trace.
"""


import configparser

import pytest

pytest.importorskip("PyQt5", reason="the play toggle lives on the editor window")

from editor.main_window import MainWindow          # noqa: E402
from editor.things import Monster                  # noqa: E402
from tests.helpers.worlds import box_brush, make_thing  # noqa: E402

pytestmark = pytest.mark.qt


def _play_a_session(window):
    from editor.things import PlayerStart
    wall = window.state.brushes[0]
    grunt = window.state.things[0]
    # Play refuses to start without somewhere to put the player.
    if not any(isinstance(t, PlayerStart) for t in window.state.things):
        window.state.things.append(PlayerStart(pos=[0.0, 64.0, -200.0]))
    window.enter_play_mode()
    assert window.view_3d.play_mode, "Play did not start"
    wall["hidden"] = wall["disabled"] = True          # I/O Kill
    grunt.properties["dead"] = True
    grunt.pos = [500.0, 64.0, 0.0]
    window.state.save_state()                           # e.g. setprop in play
    window.unsaved_changes = True
    window._exit_play_mode()


def test_stop_restores_the_pre_play_world_when_enabled(main_window):
    window = main_window
    window.config.add_section("Settings")
    window.config.set("Settings", "restore_world_on_stop", "true")
    window.state.brushes[:] = [box_brush("wall", (0, 64, 0))]
    window.state.things[:] = [
        make_thing(Monster, "grunt", (100, 64, 0), health=50)
    ]
    window.state.save_state()
    window.unsaved_changes = False

    history = len(window.state.undo_stack)
    _play_a_session(window)

    wall, grunt = window.state.brushes[0], window.state.things[0]
    assert not wall.get("hidden") and not wall.get("disabled")
    assert not grunt.properties.get("dead")
    assert list(grunt.pos) == [100.0, 64.0, 0.0]
    assert len(window.state.undo_stack) == history
    assert window.unsaved_changes is False


def test_stop_keeps_the_play_changes_when_restore_is_disabled(main_window):
    window = main_window
    window.config.add_section("Settings")
    window.config.set("Settings", "restore_world_on_stop", "false")
    window.state.brushes[:] = [box_brush("wall", (0, 64, 0))]
    window.state.things[:] = [
        make_thing(Monster, "grunt", (100, 64, 0), health=50)
    ]
    window.state.save_state()

    wall, grunt = window.state.brushes[0], window.state.things[0]
    _play_a_session(window)

    assert wall.get("hidden") and wall.get("disabled")
    assert grunt.properties.get("dead")
    assert list(grunt.pos) == [500.0, 64.0, 0.0]



def test_stop_keeps_what_happened_in_play_by_default(main_window):
    window = main_window
    window.config.add_section("Settings")
    window.config.set("Settings", "restore_world_on_stop", "false")
    window.state.brushes[:] = [box_brush("wall", (0, 64, 0))]
    window.state.things[:] = [
        make_thing(Monster, "grunt", (100, 64, 0), health=50)
    ]
    window.state.save_state()
    _play_a_session(window)
    assert window.state.brushes[0]["hidden"] is True
    assert window.state.things[0].properties["dead"] is True


def test_a_level_change_drops_the_previous_maps_world():
    """_load_level clears the capture before leaving play, so the new map is
    never replaced by the one the session started on."""
    import inspect
    source = inspect.getsource(MainWindow._load_level)
    assert source.index("self._pre_play_world = None") < source.index(
        "self._exit_play_mode()")


def test_the_setting_round_trips_through_the_settings_window(qt_app):
    from editor.SettingsWindow import SettingsWindow
    config = configparser.ConfigParser()
    config.optionxform = str
    dialog = SettingsWindow(config)
    try:
        assert dialog.restore_world_checkbox.isChecked() is False, "must default off"
        dialog.restore_world_checkbox.setChecked(True)
        dialog._save_settings()
        assert config.getboolean("Settings", "restore_world_on_stop") is True
        dialog.restore_world_checkbox.setChecked(False)
        dialog.load_settings()
        assert dialog.restore_world_checkbox.isChecked() is True
    finally:
        dialog.deleteLater()


def test_a_saved_map_is_restored_from_its_file_without_a_snapshot(main_window, tmp_path,
                                                                  monkeypatch):
    """With nothing unsaved the scene *is* its file: Play start keeps the path,
    not a whole-world snapshot, and Stop reads the file back."""
    from editor import main_window as main_window_module
    from tests.helpers import scenes
    window = main_window
    window.config.add_section("Settings")
    window.config.set("Settings", "restore_world_on_stop", "true")
    path = scenes.write(tmp_path, "arena.json", scenes.monster_arena())
    assert window.load_level_file(path)
    assert window.unsaved_changes is False

    def no_snapshot():
        raise AssertionError("a saved map must not be snapshotted at Play")

    monkeypatch.setattr(window.state, "snapshot", no_snapshot)
    window.enter_play_mode()
    assert window.view_3d.play_mode
    assert isinstance(window._pre_play_world[0], main_window_module._SavedLevelFile)
    monster = next(t for t in window.state.things if t.properties.get("name") == "Monster_1")
    monster.properties["dead"] = True
    monster.pos = [900.0, 64.0, 900.0]
    window._exit_play_mode()

    monster = next(t for t in window.state.things if t.properties.get("name") == "Monster_1")
    assert not monster.properties.get("dead")
    assert list(monster.pos) == [320.0, 64.0, 320.0]
    assert window.file_path == path and window.unsaved_changes is False


def test_unsaved_edits_are_still_snapshotted(main_window, tmp_path):
    from editor import main_window as main_window_module
    from tests.helpers import scenes
    window = main_window
    window.config.add_section("Settings")
    window.config.set("Settings", "restore_world_on_stop", "true")
    assert window.load_level_file(scenes.write(tmp_path, "arena.json", scenes.monster_arena()))
    window.unsaved_changes = True
    window.enter_play_mode()
    assert isinstance(window._pre_play_world[0], str), "unsaved work needs the snapshot"
    assert not isinstance(window._pre_play_world[0], main_window_module._SavedLevelFile)
    window._exit_play_mode()
