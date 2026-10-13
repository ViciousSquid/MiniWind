"""
Every assets/*.fiopak is mounted together: archives first, later names win,
loose files the fallback.

Run:  python -m pytest game/tests/test_asset_archives.py -q
"""

from __future__ import annotations

import os
import zipfile

import pytest

from engine import asset_archives as aa


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "assets" / "textures").mkdir(parents=True)
    aa.refresh()
    yield tmp_path
    aa.refresh()


def _archive(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
    aa.refresh()


def test_a_member_is_read_from_its_archive(project):
    _archive(project / "assets" / "textures_common.fiopak",
             {"assets/textures/stone.png": b"packed"})
    assert aa.read("assets/textures/stone.png") == b"packed"
    assert aa.in_archive("assets/textures/stone.png")


def test_loose_files_are_the_fallback(project):
    (project / "assets" / "textures" / "loose.png").write_bytes(b"loose")
    assert aa.read("assets/textures/loose.png") == b"loose"
    assert not aa.in_archive("assets/textures/loose.png")
    assert aa.exists("assets/textures/loose.png")


def test_an_archive_wins_over_a_loose_file(project):
    (project / "assets" / "textures" / "both.png").write_bytes(b"loose")
    _archive(project / "assets" / "textures.fiopak", {"assets/textures/both.png": b"packed"})
    assert aa.read("assets/textures/both.png") == b"packed"


def test_a_later_archive_overrides_an_earlier_one(project):
    _archive(project / "assets" / "sounds.fiopak", {"assets/sounds/a.mp3": b"one",
                                                    "assets/sounds/b.mp3": b"keep"})
    _archive(project / "assets" / "sounds2.fiopak", {"assets/sounds/a.mp3": b"two"})
    assert aa.read("assets/sounds/a.mp3") == b"two"
    assert aa.read("assets/sounds/b.mp3") == b"keep"
    assert aa.members("assets/sounds", (".mp3",)) == ["assets/sounds/a.mp3",
                                                      "assets/sounds/b.mp3"]


def test_a_member_cannot_escape_the_project(project):
    _archive(project / "assets" / "evil.fiopak", {"../outside.txt": b"x",
                                                  "assets/ok.txt": b"y"})
    assert aa.archive_of("../outside.txt") is None
    assert aa.read("assets/ok.txt") == b"y"


def test_pack_writes_project_relative_members(project):
    (project / "assets" / "textures" / "sand.png").write_bytes(b"sand")
    assert aa.pack("assets/textures", "assets/textures_desert.fiopak") == 1
    with zipfile.ZipFile(project / "assets" / "textures_desert.fiopak") as z:
        assert z.namelist() == ["assets/textures/sand.png"]
    assert aa.in_archive("assets/textures/sand.png")


def test_packages_mount_from_the_project_root_too_in_name_order(project):
    _archive(project / "pak0.fiopak", {"assets/textures/x.png": b"pak0"})
    _archive(project / "assets" / "pak1.fiopak", {"assets/textures/x.png": b"pak1"})
    _archive(project / "zz_mod.fiopak", {"assets/textures/x.png": b"mod"})
    assert [os.path.basename(a) for a in aa.archives()] == ["pak0.fiopak", "pak1.fiopak",
                                                            "zz_mod.fiopak"]
    assert aa.read("assets/textures/x.png") == b"mod"
