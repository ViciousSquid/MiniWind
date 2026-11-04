"""Portable source identity for source checkouts and frozen desktop builds."""

import hashlib
import json
from pathlib import Path
import threading

MANIFEST = "game/data/multiplayer_build.json"


def text_bytes(path):
    # Git's Windows checkout may use CRLF; that does not change gameplay.
    return path.read_bytes().replace(b"\r\n", b"\n")


_MAP_HASHES = {}
_MAP_HASH_LOCK = threading.Lock()
_MAP_HASH_CHUNK_BYTES = 1024 * 1024


def _hash_map_file(path):
    """Hash normalised newlines without holding a large map in memory."""
    digest = hashlib.sha256()
    pending_cr = False
    with path.open("rb") as handle:
        while block := handle.read(_MAP_HASH_CHUNK_BYTES):
            if pending_cr:
                block = b"\r" + block
            pending_cr = block.endswith(b"\r")
            if pending_cr:
                block = block[:-1]
            digest.update(block.replace(b"\r\n", b"\n"))
    if pending_cr:
        digest.update(b"\r")
    return digest.hexdigest()


def map_hash(path) -> str:
    """SHA-256 of *path*'s :func:`text_bytes`, cached per file version.

    Party travel, lobbies and joins compare map hashes; the overworld is
    87 MB, and hashing it again on the logic thread each time the party set
    off stalled the game for a quarter of a second.
    """
    from engine.file_version import file_version

    path = Path(path)
    key = file_version(path)
    with _MAP_HASH_LOCK:
        cached = _MAP_HASHES.get(key)
    if cached is None:
        cached = _hash_map_file(path)
        # A save racing this read must not publish a hash under an old version.
        try:
            unchanged = file_version(path) == key
        except OSError:
            unchanged = False
        if unchanged:
            with _MAP_HASH_LOCK:
                if len(_MAP_HASHES) >= 64:
                    _MAP_HASHES.pop(next(iter(_MAP_HASHES)))
                _MAP_HASHES[key] = cached
    return cached


def source_signature(root):
    root = Path(root)
    digest = hashlib.sha256()
    paths = (
        p
        for directory in ("engine", "game", "plugins")
        for p in (root / directory).rglob("*.py")
        if "tests" not in p.parts and "__pycache__" not in p.parts
    )
    for path in sorted(paths):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(text_bytes(path))
    return digest.hexdigest()


def gameplay_signature(root, protocol):
    root = Path(root)
    if (root / "game/multiplayer/model.py").is_file():
        code = source_signature(root)
    else:
        code = json.loads((root / MANIFEST).read_text())["source_sha256"]
    digest = hashlib.sha256(f"{protocol}:{code}".encode())
    for path in sorted(
        [
            p
            for p in (root / "game/data").rglob("*.json")
            if p.name != "multiplayer_build.json"
        ]
        + list((root / "quests").rglob("*.quest"))
    ):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(text_bytes(path))
    return digest.hexdigest()
