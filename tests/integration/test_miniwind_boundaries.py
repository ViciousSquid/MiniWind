"""Ownership guards for MiniWind on Fio 2.4.1.

MiniWind adds game meaning to Fio primitives; it does not reimplement Fio's
infrastructure. These tests pin the dependency direction and the ownership
decisions taken when MiniWind moved onto Fio 2.4.1:

* Fio's packages (``engine``, ``editor``, ``plugins``, ``player``) never import
  the ``game`` package. The game is installed by the application bootstrap.
* World streaming, residency and simulation tiers belong to Fio's Big World
  plugin; there is no MiniWind streaming layer or ``BigWorldSettings`` entity.
* Typed state is ``LogicState``; the pre-2.4 key/value store is gone entirely.
* Shooting is the engine's: fire buttons reach the game through
  ``LogicThread.player_fire_handler``.
* Fio 2.4.1 functionality survives the merge.
"""

import ast
import pathlib

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
    assert "_miniwind.install()" in _read("main.py")
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
    for path in _sources(*FIO_PACKAGES, "game"):
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

def test_procedural_map_generator_is_removed():
    for rel in ("editor/procedural_generator.py", "editor/procedural_map_gen.py",
                "tools/procedural_map_gen.py"):
        assert not (ROOT / rel).exists(), rel
    for rel in ("editor/main_window.py", "editor/ui.py"):
        src = _read(rel)
        assert "procedural_generator" not in src, rel
        assert "procedural_action" not in src, rel


# ---------------------------------------------------------------------------
# Fio 2.4.1 functionality preserved
# ---------------------------------------------------------------------------

def test_angled_brush_geometry_helpers_survive():
    src = _read("engine/brush_geometry.py")
    for fn in ("def face_key(", "def iter_surface_faces(", "def find_surface_face(",
               "def face_plane_index(", "def ray_convex_face(", "def _ray_triangle("):
        assert fn in src, f"Fio geometry helper missing: {fn}"


def test_angled_faces_are_pickable_in_the_3d_view():
    src = _read("engine/qt_game_view.py")
    assert "brush_geometry.ray_convex_face(convex, ray_o_t, ray_d_t)" in src


def test_cut_face_highlight_and_texturing_survive():
    core = _read("engine/renderer_core.py")
    for name in ("_geo_face_highlight_verts", "_draw_face_highlight_verts", "_geo_run_plane"):
        assert name in core
    face_tex = _read("editor/face_texture.py")
    assert "def face_plane(" in face_tex
    assert "def is_cut_face(" in face_tex
    assert "face_texture" in _read("editor/surface_inspector.py")
    assert "brush_geometry.face_plane_index(brush, face_name)" in _read("editor/main_window.py")


def test_component_editing_and_scene_search_survive():
    assert "def set_component_mode(" in _read("editor/main_window.py")
    assert "self.search_box = QLineEdit()" in _read("editor/scene_hierarchy.py")
    assert (ROOT / "editor" / "project_overview.py").exists()


def test_io_widget_rewrite_survives():
    src = _read("editor/io_editor_widget.py")
    assert "self._row_height = self.table.fontMetrics().height() + 12" in src
    assert "setSectionResizeMode(QHeaderView.Fixed)" in src


def test_renderer_light_capacities_come_from_the_shaders():
    src = _read("engine/renderer_core.py")
    assert "MAX_LIGHTS = shaders.MAX_LIGHTS" in src
    assert "MAX_SHADOW_LIGHTS = shaders.MAX_SHADOW_LIGHTS" in src
    from engine import shaders as shader_module
    for name in ("lit.frag", "textured.frag"):
        source = shader_module.DEFAULT_SHADERS[name]
        assert "lights[%d]" % shader_module.MAX_LIGHTS in source, name


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

def test_window_title_is_miniwind():
    assert 'self.setWindowTitle("MiniWind")' in _read("editor/main_window.py")


def test_overhead_is_the_default_camera():
    assert 'MainWindow.camera_mode_combobox.setCurrentText("Overhead")' in _read("editor/ui.py")
