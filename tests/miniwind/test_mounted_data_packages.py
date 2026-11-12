"""Data packages are streamed read-only, without the removed player loader."""

import json
import zipfile

import pytest

from engine import asset_archives


@pytest.fixture
def package(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    archive = tmp_path / "demo.fiopak"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("metadata.json", json.dumps({"map_path": "maps/level.json"}))
        zf.writestr("maps/level.json", json.dumps({"version": 3, "brushes": [],
                                                 "things": []}))
        zf.writestr("assets/sprites/pickup.png", b"sprite")
    asset_archives.refresh()
    yield archive
    asset_archives.refresh()


def test_reading_a_package_preserves_the_archive(package):
    before = package.read_bytes()

    assert asset_archives.read("assets/sprites/pickup.png") == b"sprite"
    assert json.loads(asset_archives.read("maps/level.json"))["version"] == 3
    assert package.read_bytes() == before
    assert zipfile.is_zipfile(package)


def test_package_members_are_streamed_without_extraction(package, monkeypatch):
    def extraction_is_forbidden(*args, **kwargs):
        raise AssertionError("mounted packages must not extract files")

    monkeypatch.setattr(zipfile.ZipFile, "extract", extraction_is_forbidden)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", extraction_is_forbidden)

    assert asset_archives.read("assets/sprites/pickup.png") == b"sprite"
    assert not (package.parent / "assets").exists()
    assert not (package.parent / "maps").exists()


@pytest.mark.parametrize("name", ["../escape.json", "/escape.json",
                                  r"assets\escape.json", "assets/../escape.json"])
def test_unsafe_members_are_not_mounted(package, name):
    with zipfile.ZipFile(package, "a") as zf:
        zf.writestr(name, "escape")
    asset_archives.refresh()

    assert asset_archives.archive_of(name) is None
    assert asset_archives.read("assets/sprites/pickup.png") == b"sprite"
    assert not (package.parent / "escape.json").exists()
