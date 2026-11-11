<<<<<<< MiniWind
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
||||||| base
=======
"""Regression tests for the no-plugin-code .fiopak boundary."""

import io
import json
import zipfile

import pytest

from engine.fiopak import FioPackage, PackageError


def _bytes(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, raw in entries.items():
            zf.writestr(name, raw)
    return buf.getvalue()


def test_package_plugin_code_is_rejected():
    data = _bytes({
        "metadata.json": json.dumps({"title": "Demo"}).encode(),
        "maps/start.json": b'{"version":3,"things":[]}',
        "plugins/packagedemo/__init__.py": b"raise RuntimeError",
    })
    with pytest.raises(PackageError, match="Bundled plugins are not permitted"):
        FioPackage.from_bytes(data)


def test_package_plugin_dependency_metadata_is_not_code():
    data = _bytes({
        "metadata.json": json.dumps({
            "title": "Demo",
            "plugins": ["packagedemo"],
        }).encode(),
        "maps/start.json": b'{"version":3,"things":[]}',
    })
    with FioPackage.from_bytes(data) as package:
        assert package.required_plugins == ["packagedemo"]


def test_package_rejection_applies_to_backslash_entries_too():
    data = _bytes({
        "metadata.json": b'{"title":"Demo"}',
        "maps/start.json": b'{"version":3,"things":[]}',
        r"plugins\packagedemo\plugin.py": b"x",
    })
    with pytest.raises(PackageError, match="Bundled plugins are not permitted"):
        FioPackage.from_bytes(data)


@pytest.mark.parametrize("name", ["Plugins/packagedemo/__init__.py",
                                  "maps/../plugins/packagedemo/__init__.py",
                                  "./PLUGINS/x.py"])
def test_package_rejection_is_not_fooled_by_spelling(name):
    """Case and ``..`` do not change where an entry lands once extracted."""
    data = _bytes({
        "metadata.json": b'{"title":"Demo"}',
        "maps/start.json": b'{"version":3,"things":[]}',
        name: b"x",
    })
    with pytest.raises(PackageError, match="Bundled plugins are not permitted"):
        FioPackage.from_bytes(data)


def test_a_map_merely_named_after_plugins_is_fine():
    data = _bytes({
        "metadata.json": b'{"title":"Demo"}',
        "maps/plugins_showcase.json": b'{"version":3,"things":[]}',
    })
    with FioPackage.from_bytes(data) as package:
        assert package.list_maps() == ["maps/plugins_showcase.json"]
>>>>>>> Fio-3.5
