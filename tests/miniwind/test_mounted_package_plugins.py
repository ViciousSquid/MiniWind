"""Mounted data packages never import bundled Python code.

The standalone player and its rejecting archive reader were removed. The
current runtime mounts packages as read-only data through asset_archives.
"""

import json
import sys
import zipfile

import pytest

from engine import asset_archives


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    asset_archives.refresh()
    yield tmp_path
    asset_archives.refresh()


@pytest.mark.parametrize("name", [
    "plugins/packagedemo/__init__.py",
    r"plugins\packagedemo\plugin.py",
    "Plugins/packagedemo/__init__.py",
    "maps/../plugins/packagedemo/__init__.py",
    "./PLUGINS/x.py",
])
def test_mounting_a_package_does_not_execute_plugin_code(project, name):
    sentinel = project / "executed.txt"
    code = f"from pathlib import Path; Path({str(sentinel)!r}).write_text('ran')"
    with zipfile.ZipFile(project / "demo.fiopak", "w") as archive:
        archive.writestr(name, code)
        archive.writestr("assets/textures/example.png", b"texture")

    assert asset_archives.read("assets/textures/example.png") == b"texture"
    assert not sentinel.exists()
    assert "packagedemo" not in sys.modules


def test_plugin_dependency_metadata_remains_data(project):
    metadata = {"title": "Demo", "plugins": ["packagedemo"]}
    with zipfile.ZipFile(project / "demo.fiopak", "w") as archive:
        archive.writestr("metadata.json", json.dumps(metadata))
        archive.writestr("maps/plugins_showcase.json", '{"version":3,"things":[]}')

    assert json.loads(asset_archives.read("metadata.json")) == metadata
    assert asset_archives.members("maps", (".json",)) == ["maps/plugins_showcase.json"]
    assert "packagedemo" not in sys.modules
