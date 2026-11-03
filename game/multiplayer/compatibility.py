"""Portable source identity for source checkouts and frozen desktop builds."""

import hashlib
import json
from pathlib import Path

MANIFEST = "game/data/multiplayer_build.json"


def text_bytes(path):
    # Git's Windows checkout may use CRLF; that does not change gameplay.
    return path.read_bytes().replace(b"\r\n", b"\n")


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
