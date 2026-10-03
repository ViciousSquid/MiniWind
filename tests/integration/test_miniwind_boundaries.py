"""Ownership guards for MiniWind on Fio 2.5.10.

MiniWind adds game meaning to Fio primitives; it does not reimplement Fio's
infrastructure. These tests pin the dependency direction and the ownership
decisions MiniWind keeps on Fio 2.5.10 (Fio's own guards, in
test_backport_boundaries.py, cover Fio's features surviving):

* Fio's packages (``engine``, ``editor``, ``plugins``, ``player``) never import
  the ``game`` package. The application bootstrap loads it by name from
  settings.ini ``[Startup] game_module``.
* World streaming, residency and simulation tiers belong to Fio's Big World
  plugin; there is no MiniWind streaming layer or ``BigWorldSettings`` entity.
* Typed state is ``LogicState``; the pre-2.4 key/value store is gone entirely.
* Shooting is the engine's: fire buttons reach the game through
  ``LogicThread.player_fire_handler``.
* MiniWind's product choices (title, overhead play, no procedural map
  generator) are applied by the game's editor integration, not by editing
  Fio's editor.
"""

import ast
import importlib
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

FIO_PACKAGES = ("engine", "editor", "plugins", "player")


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8", errors="replace")


def _sources(*roots):
    for root in roots:
        for path in (ROOT / root).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def _imported_modules(path):
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


# ---------------------------------------------------------------------------
# Dependency direction: Fio -> MiniWind, never back
# ---------------------------------------------------------------------------

def test_fio_packages_never_import_the_game():
    offenders = []
    for path in _sources(*FIO_PACKAGES):
        if "tests" in path.relative_to(ROOT).parts:
            continue
        for module in _imported_modules(path):
            if module == "game" or module.startswith("game."):
                offenders.append((str(path.relative_to(ROOT)), module))
    assert not offenders, f"Fio code imports the game layer: {offenders}"


def test_the_game_is_installed_by_the_application_bootstrap():
    import configparser
    main = _read("main.py")
    assert "config.get('Startup', 'game_module'" in main
    assert "game_module = importlib.import_module(game_name)" in main
    assert "game_module.install()" in main
    config = configparser.ConfigParser()
    config.read(ROOT / "settings.ini")
    assert config.get("Startup", "game_module") == "game"
    assert "import game" not in _read("editor/main_window.py")


def test_engine_reads_the_session_by_its_generic_name():
    for rel in ("engine/qt_game_view.py", "engine/monster_ai.py",
                "engine/logic_thread.py", "editor/main_window.py"):
        assert "_miniwind" not in _read(rel), rel


# ---------------------------------------------------------------------------
# Big World owns streaming, residency and simulation relevance
# ---------------------------------------------------------------------------

def test_no_parallel_streaming_layer():
    for rel in ("engine/world_cells.py", "engine/world_streaming.py",
                "engine/world_streaming_disk.py", "engine/world_persistence.py",
                "engine/streaming_debug.py", "engine/cells.py",
                "engine/world_index.py"):
        assert not (ROOT / rel).exists(), f"{rel} duplicates Big World"
    assert (ROOT / "plugins" / "bigworld" / "tiers.py").exists()


def test_big_world_settings_is_the_plugins_entity_only():
    for rel in ("editor/things.py", "editor/main_window.py", "engine/logic_thread.py"):
        assert "class BigWorldSettings" not in _read(rel), rel
    assert "class BigWorldSettings" in _read("plugins/bigworld/entities.py")


def test_logic_thread_does_not_drive_streaming_itself():
    src = _read("engine/logic_thread.py")
    for banned in ("_start_world_streaming", "_rebuild_world_index",
                   "_camera_relevance_box", "_shadow_casters", "WorldIndex"):
        assert banned not in src, f"{banned} reimplements Fio infrastructure"


def test_the_actor_index_is_the_games():
    assert (ROOT / "game" / "world_index.py").exists()
    assert "self.world_index = WorldIndex()" in _read("game/runtime.py")


# ---------------------------------------------------------------------------
# Typed state
# ---------------------------------------------------------------------------

def test_the_pre_2_4_key_value_store_is_removed_from_code():
    offenders = []
    # MiniWind's own code. Fio's tests/logic/test_logic_state.py guards the
    # engine side (upstream still lists an inert "logickeyvaluestore" token in
    # Big World's persistent types, which is Fio's to remove).
    for path in _sources("game"):
        rel = path.relative_to(ROOT)
        if "tests" in rel.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in ("LogicKeyValueStore", "logic_keyvalue", "logickeyvalue"):
            if token in text:
                offenders.append((str(rel), token))
    assert not offenders, f"removed key/value store still referenced: {offenders}"


# ---------------------------------------------------------------------------
# Shooting
# ---------------------------------------------------------------------------

def test_fire_buttons_go_through_the_engine_shot_path():
    lt = _read("engine/logic_thread.py")
    assert "self.player_fire_handler = None" in lt
    assert "def _handle_shooting(self, secondary=False):" in lt
    assert "consume_secondary_shot" in lt
    gs = _read("engine/threaded_game_state.py")
    assert "def queue_secondary_shot(" in gs
    for banned in ("queue_rpg_attack", "consume_rpg_attack", "queue_rpg_cast"):
        assert banned not in gs
    assert "logic.player_fire_handler = self.fire_player_weapon" in _read("game/runtime.py")


# ---------------------------------------------------------------------------
# Removed from MiniWind
# ---------------------------------------------------------------------------

def test_the_procedural_map_generator_is_not_offered():
    """Fio's guard keeps the generator's files; MiniWind hides its one action."""
    src = _read("game/integration.py")
    assert 'getattr(MainWindow, "procedural_action", None)' in src
    assert "action.setVisible(False)" in src and "action.setEnabled(False)" in src


def test_dice_are_the_games_not_fios_io():
    assert "def fire_output(" in _read("plugins/api.py")
    for rel in ("editor/io_system.py", "plugins/api.py"):
        src = _read(rel)
        for banned in ("RollDice", "OnDiceRolled", "request_dice_roll", "set_dice_roller"):
            assert banned not in src, f"{banned} in {rel}"
    assert '"rolldice", _roll_dice' in _read("game/host.py")


def test_thing_counters_keep_fios_semantics():
    src = _read("editor/things.py")
    assert "cls._counters[class_name] = max_indices[class_name]" in src


# ---------------------------------------------------------------------------
# MiniWind identity
# ---------------------------------------------------------------------------

@pytest.mark.qt
def test_window_title_is_miniwind():
    integration = importlib.import_module("game.integration")
    assert integration._product_title("Fio") == "MiniWind"
    assert integration._product_title("Fio - village.json *") == "MiniWind village.json *"
    assert integration._product_title("Unsaved Changes") == "Unsaved Changes"


@pytest.mark.qt
def test_play_is_always_overhead_and_the_camera_choice_is_hidden():
    host = importlib.import_module("game.host")
    assert host.PLAY_CAMERA == "Overhead"
    assert "set_camera(PLAY_CAMERA)" in _read("game/host.py")
    assert "_hide_camera_dropdown(MainWindow)" in _read("game/integration.py")
