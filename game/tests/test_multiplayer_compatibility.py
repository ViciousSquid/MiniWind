"""The same revision can play together from source or packaged desktop builds."""

import runpy
from pathlib import Path

import hashlib
import os
from contextlib import contextmanager

import pytest

from game.multiplayer.compatibility import gameplay_signature


def test_manifest_matches_source_and_normalises_windows_newlines(tmp_path):
    source = tmp_path / "source"
    frozen = tmp_path / "frozen"
    files = {
        "game/multiplayer/model.py": "def value():\n    return 1\n",
        "engine/player.py": "speed = 100\n",
        "quests/test.quest": '{"id":"q"}\n',
        "game/data/test.json": "{}\n",
    }
    for name, text in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())
    # The build tool deliberately has no import of the desktop game package.
    helper = source / "game/multiplayer/compatibility.py"
    helper.write_bytes(
        (
            Path(__file__).resolve().parents[1] / "multiplayer/compatibility.py"
        ).read_bytes()
    )
    api = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "tools/multiplayer_build_manifest.py")
    )
    expected = gameplay_signature(source, 1)
    manifest = api["write_manifest"](source)
    for name in (
        "game/data/test.json",
        "quests/test.quest",
        "game/data/multiplayer_build.json",
    ):
        path = frozen / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((source / name).read_bytes().replace(b"\n", b"\r\n"))
    assert gameplay_signature(frozen, 1) == expected
    assert manifest.is_file()
    for path in source.rglob("*.py"):
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert gameplay_signature(source, 1) == expected
    assert gameplay_signature(source, 2) != expected
    (source / "engine/player.py").write_text("speed = 200\n")
    assert gameplay_signature(source, 1) != expected


@pytest.mark.parametrize("content", [b"", b"a\r\nb\nc\r", b"a" * (1024 * 1024 - 1) + b"\r\nb\r\r\n"])
def test_map_hash_matches_normalised_content_across_read_boundaries(tmp_path, content):
    from game.multiplayer.compatibility import map_hash
    path = tmp_path / "map.json"
    path.write_bytes(content)
    assert map_hash(path) == hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def test_map_hash_reuses_unchanged_files_and_detects_preserved_mtime(tmp_path, monkeypatch):
    from game.multiplayer import compatibility
    path = tmp_path / "map.json"
    path.write_bytes(b'{"map": 1}')
    original = compatibility.map_hash(path)
    real_open = Path.open
    reads = []

    def opened(self, *args, **kwargs):
        if self == path:
            reads.append(self)
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", opened)
    assert compatibility.map_hash(path) == original
    assert reads == [], "cached map hashes must not read the map again"

    stat = path.stat()
    replacement = tmp_path / "replacement.json"
    replacement.write_bytes(b'{"map": 2}')
    os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    replacement.replace(path)
    reads.clear()
    assert compatibility.map_hash(path) != original, "a replaced map reused its old hash"
    assert reads, "the new file version must be hashed"


def test_a_map_changed_during_hashing_is_not_cached(tmp_path, monkeypatch):
    from game.multiplayer import compatibility
    path = tmp_path / "map.json"
    path.write_bytes(b"original")
    real_hash = compatibility._hash_map_file

    def changed_while_reading(path):
        digest = real_hash(path)
        path.write_bytes(b"changed")
        return digest

    monkeypatch.setattr(compatibility, "_hash_map_file", changed_while_reading)
    assert compatibility.map_hash(path) == hashlib.sha256(b"original").hexdigest()
    monkeypatch.setattr(compatibility, "_hash_map_file", real_hash)
    assert compatibility.map_hash(path) == hashlib.sha256(b"changed").hexdigest()


def test_map_hash_never_reads_the_whole_file_at_once(tmp_path, monkeypatch):
    from game.multiplayer import compatibility
    path = tmp_path / "map.json"
    path.write_bytes(b"a\r\nb\r\r\nc\r")
    real_open = Path.open

    @contextmanager
    def bounded_open(self, *args, **kwargs):
        with real_open(self, *args, **kwargs) as handle:
            class Reader:
                def read(self, size=-1):
                    assert 0 < size <= 1024 * 1024, "map hashing made an unbounded read"
                    return handle.read(size)
            yield Reader()

    monkeypatch.setattr(Path, "open", bounded_open)
    monkeypatch.setattr(compatibility, "_MAP_HASH_CHUNK_BYTES", 1)
    assert compatibility.map_hash(path) == hashlib.sha256(b"a\nb\r\nc\r").hexdigest()
