"""Nothing the desktop runs may import the ``player`` package (Fio's Android
player, which a desktop build leaves out and MiniWind does not ship at all).

The package reader and the export's asset collector are shared with the
player and live in the engine (``engine.fiopak``, ``engine.package_assets``);
the player reaches them through aliases. ``main.py`` may name the player only
inside its guarded FIO_PLAYER / Android branch.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _player_imports(path):
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names = [node.module or ""]
        found += [(node.lineno, name) for name in names
                  if name == "player" or name.startswith("player.")]
    return found


def test_editor_engine_and_plugins_never_import_the_player():
    offenders = []
    for top in ("editor", "engine", "plugins"):
        for path in sorted((ROOT / top).rglob("*.py")):
            if "tests" in path.parts:
                continue
            offenders += ["%s:%d imports %s" % (path.relative_to(ROOT), line, name)
                          for line, name in _player_imports(path)]
    assert not offenders, "\n".join(offenders)


def test_main_never_imports_the_player():
    """Fio's ``main.py`` names the player in one guarded Android branch.
    MiniWind ships no player package, so its ``main.py`` names it nowhere."""
    assert _player_imports(ROOT / "main.py") == []


def test_no_player_package_is_shipped():
    """Fio's release builds pass ``--nofollow-import-to=player``; MiniWind's
    have nothing to leave out."""
    assert not (ROOT / "player").exists()
    for workflow in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        assert "player/" not in workflow.read_text(encoding="utf-8"), workflow.name
