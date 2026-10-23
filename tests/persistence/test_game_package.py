"""The editor can play exports without importing the removed player package."""

import json
import shutil
import stat
import zipfile

import pytest

from editor.package_exporter import PackageExporter
from engine import game_package


def _package(tmp_path, extra=(), metadata=None):
    path = tmp_path / "demo.fiopak"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("metadata.json", json.dumps(
            {"map_path": "maps/start.json"} if metadata is None else metadata))
        archive.writestr("maps/start.json", '{"version":3,"brushes":[],"things":[]}')
        for name, data in extra:
            archive.writestr(name, data)
    return path


def test_exported_package_opens_at_its_manifest_map(tmp_path):
    maps = tmp_path / "maps"
    maps.mkdir()
    level = {"version": 3, "brushes": [], "things": []}
    source = maps / "start.json"
    source.write_text(json.dumps(level))
    path = tmp_path / "demo.fiopak"
    assert PackageExporter(None, str(tmp_path)).export(
        str(path), {"title": "Demo"}, str(source))[0]
    before = path.read_bytes()
    directory, start = game_package.extract_package(path)
    try:
        with open(start) as stream:
            assert json.load(stream) == level
        assert path.read_bytes() == before
    finally:
        shutil.rmtree(directory)


@pytest.mark.parametrize("name", [
    "../escape", "/escape", "assets/../escape", "assets//escape",
    r"assets\escape", "assets/C:/escape", "assets/a.py",
    "plugins/demo/__init__.py", "maps/start.json", "MAPS/START.JSON",
])
def test_unsafe_members_are_refused_before_extraction(tmp_path, monkeypatch, name):
    path = _package(tmp_path, [(name, "unsafe")])
    monkeypatch.setattr(game_package.tempfile, "mkdtemp",
                        lambda **kw: pytest.fail("extraction began before validation"))
    with pytest.raises(ValueError):
        game_package.extract_package(path)


@pytest.mark.parametrize("metadata", [[], {}, {"map_path": "../start.json"},
                                     {"map_path": "maps/missing.json"},
                                     {"map_path": ["maps/start.json"]}])
def test_invalid_start_maps_are_refused(tmp_path, metadata):
    with pytest.raises(ValueError):
        game_package.extract_package(_package(tmp_path, metadata=metadata))


def test_symlinks_are_refused(tmp_path):
    link = zipfile.ZipInfo("assets/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ValueError, match="links"):
        game_package.extract_package(_package(tmp_path, [(link, "../../escape")]))


@pytest.mark.parametrize("limit,value", [("MAX_PACKAGE_ENTRIES", 1),
                                        ("MAX_ASSET_ENTRY_BYTES", 10),
                                        ("MAX_TOTAL_ASSET_BYTES", 10),
                                        ("MAX_METADATA_BYTES", 1)])
def test_extraction_budgets_are_enforced(tmp_path, monkeypatch, limit, value):
    monkeypatch.setattr(game_package, limit, value)
    with pytest.raises(ValueError, match="too many|too large|size limit"):
        game_package.extract_package(_package(tmp_path))


def test_partial_extraction_is_removed(tmp_path, monkeypatch):
    path = _package(tmp_path)
    destination = tmp_path / "extracted"
    destination.mkdir()
    monkeypatch.setattr(game_package.tempfile, "mkdtemp", lambda **kw: str(destination))

    def interrupted(archive, target):
        (destination / "partial").write_text("incomplete")
        raise OSError("disk full")

    monkeypatch.setattr(zipfile.ZipFile, "extractall", interrupted)
    with pytest.raises(OSError, match="disk full"):
        game_package.extract_package(path)
    assert not destination.exists()


@pytest.mark.qt
def test_editor_plays_an_export_without_the_standalone_player(
        main_window, tmp_path, monkeypatch):
    path = _package(tmp_path)
    before = path.read_bytes()
    launched = []
    monkeypatch.setattr(main_window, "check_unsaved_changes", lambda: True)
    monkeypatch.setattr(main_window, "enter_kiosk_mode", lambda: launched.append(True))
    main_window.play_package_from_path(str(path))
    assert launched == [True]
    assert main_window.file_path is None
    assert main_window._package_level_dir == main_window._package_temp_dir
    assert path.read_bytes() == before


@pytest.mark.qt
def test_invalid_package_map_preserves_the_open_map(main_window, tmp_path, monkeypatch):
    path = tmp_path / "invalid.fiopak"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("metadata.json", '{"map_path":"maps/start.json"}')
        archive.writestr("maps/start.json", '{"brushes":[{"pos":"bad"}]}')
    original = str(tmp_path / "original.json")
    main_window.file_path = original
    before = main_window.state.get_level_data()
    monkeypatch.setattr(main_window, "check_unsaved_changes", lambda: True)
    main_window.play_package_from_path(str(path))
    assert main_window.file_path == original
    assert main_window.state.get_level_data() == before
    assert main_window._package_level_dir is None
