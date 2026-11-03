"""The same revision can play together from source or packaged desktop builds."""

import runpy
from pathlib import Path

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
