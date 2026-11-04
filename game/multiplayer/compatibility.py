"""Portable source identity for source checkouts and frozen desktop builds."""

import hashlib
import json
from pathlib import Path

MANIFEST = "game/data/multiplayer_build.json"


def text_bytes(path):
    # Git's Windows checkout may use CRLF; that does not change gameplay.
    return path.read_bytes().replace(b"\r\n", b"\n")


_MAP_HASHES = {}


def map_hash(path) -> str:
    """SHA-256 of *path*'s :func:`text_bytes`, cached per file version.

    Party travel, lobbies and joins compare map hashes; the overworld is
    87 MB, and hashing it again on the logic thread each time the party set
    off stalled the game for a quarter of a second.
    """
    path = Path(path)
    stat = path.stat()
    key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
    cached = _MAP_HASHES.get(key)
    if cached is None:
        cached = hashlib.sha256(text_bytes(path)).hexdigest()
        if len(_MAP_HASHES) > 64:
            _MAP_HASHES.clear()
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
