# Fio divergence audit — 30 October 2026

This is the divergence audit that `AGENTS_LOOK_HERE.md` §7 step 2 asks for
before any migration PR. It records **where MiniWind's copied `engine/`,
`editor/` and `plugins/` trees stand against upstream Fio**, with a proposed
owner and action for every differing file. Use it as the Milestone 3 checklist
and as input to Milestones 1 and 2.

It only records what exists. No engine, editor or plugin code is changed.

## Snapshot

| | Revision |
| --- | --- |
| Fio | `3.0.0.3010_Latest` @ `c2d8ed5b3` ("3.0.0.3010"), 2111 commits |
| MiniWind | `main` @ `68c0ba8b2` |

The two repositories share **no Git history** (MiniWind began as an upload).
So a fork point is estimated **per file**. It is the Fio revision of that file
with the fewest changed lines against MiniWind's copy. To regenerate:

```bash
git clone https://github.com/ViciousSquid/Fio.git ../Fio   # full history, not --depth
python tools/fio_divergence_audit.py ../Fio --json fio-audit.json
```

## Summary

| Tree | Shared | Differ | Only in MiniWind | Only in Fio |
| --- | --- | --- | --- | --- |
| `engine/` | 89 | 51 | 5 | 1 |
| `editor/` | 46 | 18 | 0 | 3 |
| `plugins/` | 34 | 6 | 1 | 36 |

These match the baseline figures in the roadmap (51 engine, 18 editor).

The 75 differing files fall into three groups:

| Kind | Files | Meaning |
| --- | --- | --- |
| **stale** | 15 | MiniWind's copy is an exact old Fio revision. MiniWind made no change, and Fio has moved on. |
| **local** | 38 | Only MiniWind changed it since the fork point. See the caveat below. |
| **two-way** | 22 | Both sides changed it. Reconcile by hand. |

**Caveat on "local":** six local files are mostly *removals* relative to their
fork point: `editor/terrain_editor.py`, `editor/editor_state.py`,
`editor/view_2d.py`, `engine/logic_interaction.py`, `editor/asset_browser.py`
and `editor/main_window.py`. Fio history shows these files received later Fio
work, such as terrain stamps, `SelectionLookup`, editor-camera streaming
adoption and `levelchanger_eligible`. MiniWind took part of that work and not
the rest. Treat them as **two-way** until each removed block is explained.

Top-level files: `python_runtime.py`, `editor_styles.py`, `clean.py`,
`Dockerfile` and `docker-compose.yml` are identical. `main.py`, `conftest.py`,
`pytest.ini`, `requirements.txt` and `settings.ini` differ.

## Findings that change the Milestone 1 plan

1. **Fio's `.fiopak` handling extracts into the root; MiniWind's does not.**
   Fio's `engine/asset_archives.py` is "startup discovery … non-audio archives
   *materialise only missing files* at those paths". It writes files under
   `root_directory`. MiniWind's rewrite (+196/−110, local) mounts packages as
   one read-only file system and streams members ("nothing is ever extracted
   to disk"). It also adds archive-aware readers in `textures.py`,
   `terrain_style.py`, `renderer/core/resources.py`, `animated_texture.py`,
   `console_commands.py` and `main_window._read_level_json`. The roadmap
   forbids "extraction of archives into the vendor checkout". MiniWind's
   streaming design is therefore the **prerequisite upstream fix** for the
   Milestone 1 "Archive and asset paths" test, and it should land in Fio as
   part of Milestone 1 or immediately before it.
2. **Fio's `main.py` already has three things MiniWind's lacks:** the
   Android/`FIO_PLAYER` early exit, `editor.user_paths.settings_path()`
   (per-user writable fallback), and `apply_ui_scale`. MiniWind reads
   `settings.ini` relative to the cwd. MiniWind's `main.py` adds the
   `[Startup] game_module` hook (`importlib.import_module(name).install()`),
   `show_launcher`, and `[Plugins] mandatory` (`_missing_mandatory_plugins`).
   The Milestone 1 `launch()` should carry over all three MiniWind additions
   as generic features: game module, optional launcher callable and mandatory
   plugins.
3. **`editor/user_paths.py`, `editor/ui_scale.py` and `editor/selection.py`
   exist only in Fio.** MiniWind's `main_window.py` explicitly drops the
   `user_paths` and `ui_scale` imports. Milestone 1's settings-isolation design
   builds on `user_paths`, so MiniWind will gain it with the dependency
   switch. MiniWind does not need to backport it first.
4. **Both test suites write into the checkout's own `settings.ini`.** Running
   the Qt-offscreen tier added a `[Layout]` section to MiniWind's
   `settings.ini`. On Fio it replaced the file, leaving only `[Layout]` and
   dropping the shipped `[Display]`, `[Settings]`, `[Renderer]`, `[Kiosk]`
   and `[Editor]` defaults. `user_paths.settings_path()` falls back to a
   per-user file only when the root is *not writable*, so a writable
   `vendor/fio` checkout would be modified the same way. This makes the
   Milestone 1 "Settings isolation" and "Read-only project/engine" tests
   necessary rather than defensive. Editor tests that save settings should
   target a temporary project root. The bootstrap should take the settings
   path from the project context, not assume the engine root.

## Game policy that has leaked into the copied trees

Each item below either needs a generic hook in Fio, with the policy moved to
`game/`, or is presentation that belongs in `game/`.

| File | Leak | Proposed fix |
| --- | --- | --- |
| `plugins/bigworld/editor_streaming.py` | hardcodes `'miniwindsettings'` as a persistent type | Big World API to register extra always-resident entity types; MiniWind registers its settings entity |
| `engine/overhead_sprite.py` | rewritten as "MiniWind overhead sprite renderer" (weapons as ground quads, blood/gib/corpse layers); +595/−147 | split: generic ground-quad layering + actor sprite stays in Fio; weapon/blood/corpse presentation moves to `game/` via the renderer's `pre_sprites` hook (`renderer/api.py`, local) |
| `editor/SettingsWindow.py` | "Allow Fio maps" checkbox (`[Editor] allow_fio_maps`) | game-owned settings tab already exists (`game/integration.py::_add_game_settings_tab`); move it there |
| `editor/loading_overlay.py` | docstring examples name `miniwind_world` / save slots | cosmetic; take upstream text when reconciling |
| `engine/effect_entity.py`, `engine/entity_table.py` | default fire texture index `[0]` → `[1]` | game default; make it a project/entity default rather than an engine constant |
| `engine/monster_table.py` | `_pursuit_range` / `engagement_range` | likely generic (pursuit beyond sight); confirm, then upstream |

## Generic mechanisms MiniWind added (candidates to upstream for Milestone 2)

These are written generically in the MiniWind copy. The game reaches them by
name, and they are the "extension seams" Milestone 2 asks for. Each needs a
Fio PR with its tests.

| Seam | Where (MiniWind) | Used by |
| --- | --- | --- |
| Hostility model (`set_hostility`, `HostilityModel`) | `engine/hostility.py` (MiniWind-only), `engine/monster_ai.py` | `game/faction_ai.py`, `game/runtime.py` |
| Monster AI hooks: attack style, shot, damage filter (`install_damage_filter`, `clear_game_hooks`) | `engine/monster_ai.py` | `game/` combat |
| Player fire handler and damage filter (`player_fire_handler`, `_player_damage_filter`, `_apply_player_damage(kind, source, cause)`, `last_damage`) | `engine/logic_thread.py`, `engine/logic_combat.py`, `engine/logic_triggers.py`, `engine/logic_player.py` | `game/` combat |
| Projectile per-shot callbacks (`ProjectileStore.hooks`, `on_hit`/`on_impact`) | `engine/projectile_table.py`, `engine/logic_combat.py` | `game/fio.py::spawn_projectile` |
| Game input ownership (`modal_input_active`, `modal_escape_active`, `owns_number_keys`) | `engine/game_input.py` (MiniWind-only), `engine/qt_game_view.py`, `engine/logic_player.py` | `game/host.py` |
| Gamepad move/look, aim | `engine/threaded_game_state.py`, `engine/logic_player.py` | `game/` input |
| Camera: shake, focus, overhead yaw/pitch, presentation interpolation | `engine/logic_camera.py`, `engine/render_camera.py` (MiniWind-only), `engine/logic_render.py`, `engine/level_validation.py` | `game/` camera, wheel zoom |
| Player `move_speed_scale`, `movement_angle`; `LogicThread.time_scale` | `engine/player.py`, `engine/logic_thread.py` | `game/` encumbrance, slow-mo |
| Regional terrain biomes (5th heightmap channel, `uBiomeMap`) | `engine/terrain_biomes.py` (MiniWind-only), `engine/terrain.py`, `engine/shaders.py` | `game/ui/worldmap.py`, `game/farm_work.py`, tools |
| Per-light terrain shadow strength / shadow-only | `editor/things.py`, `renderer/forward/lighting.py` | maps |
| Sprite tint and spin instancing (`SPRITE_INSTANCE_FLOATS` 8→13) | `renderer/forward/{shaders,passes,instancing}.py`, `engine/entity_table.py` (`FACING`, head art) | top-down heads |
| Big World `set_reach(radius)` | `plugins/bigworld/runtime.py` (+test) | MiniWind wheel zoom |
| Floating-window wheel routing, `mouse_captured` | `engine/floating_windows.py` | game UI |
| Data-only package player (`Play Game Package`) | `engine/game_package.py` (MiniWind-only), `editor/main_window.py` | editor |
| Savegame snapshot builder | `engine/savegame.py` | `game/` saves |
| Ambient level setting helpers | `engine/view_distance.py` | settings |
| Debug console `repeat_text=False`, `overheadangle` command | `editor/debug_console.py`, `editor/console_commands.py` | game console |
| Frustum culling of brush slots | `renderer/core/visibility.py` | performance |

## Monkeypatches and private replacements in `game/`

Milestone 2 replaces each of these with a supported hook.

| Site | What it replaces | Hook needed in Fio |
| --- | --- | --- |
| `game/integration.py::_patch_editor_menu` | `Ui_MainWindow.create_menu_bar`, `create_status_bar` | editor menu/status contribution registry |
| `game/integration.py::_patch_map_loading` | `MainWindow.load_level_file` (gate plain-Fio maps) | "can open map?" project policy callback |
| `game/integration.py::_patch_window_title` | `MainWindow.setWindowTitle` | product title from project settings |
| `game/integration.py::_hide_camera_dropdown` | toolbar widget visibility | toolbar configuration hook |
| `game/integration.py::_add_tools_menu_entries` | appends to the Tools menu, sets `MainWindow.quest_editor_action` | Tools-menu contribution registry |
| `game/integration.py::_patch_settings_window` | `SettingsWindow.__init__`, `_save_settings` | settings-tab contribution hook |
| `game/integration.py::_patch_play_menu` | `QtGameView.__init__` (pause/death menu, pointer, wheel zoom, bow draw) | play-view overlay / input hook on `QtGameView` |
| `game/integration.py::_use_game_fonts_for_loading` | loading overlay fonts | project font/theme resource |
| `game/fio.py::set_jump_enabled` | wraps `player_runtime.update_primary` | a jump-allowed flag (or input filter) on `LogicPlayer` |
| `game/fio.py::set_projectile_split` | replaces `combat_runtime._publish_projectile_render_snapshot` (private) | projectile render-split callback on `LogicCombat` |

## Stale copies: take upstream (15)

MiniWind's file equals an old Fio revision byte for byte. Taking Fio's current
version should need no MiniWind code changes. Run the relevant tests and check
for API changes that `game/` relies on.

| File | Fork point | Upstream lines since |
| --- | --- | --- |
| `engine/physics.py` | `176a29b5e` 2026-10-09 | 498 |
| `engine/cutscene_runtime.py` | `3315199ce` 2026-10-07 | 94 |
| `engine/prop_entity.py` | `5bfc4dde4` 2026-10-07 | 76 |
| `editor/package_exporter.py` | `cbb21c123` 2026-10-09 | 74 |
| `engine/fileio.py` | `9ee2d79b5` 2026-10-07 | 60 |
| `plugins/bigworld/tests/test_bigworld_cell_membership.py` | `fa4e25978` 2026-10-07 | 55 |
| `engine/prop_runtime.py` | `186be56c3` 2026-10-12 | 40 |
| `engine/glb_loader.py` | `b29784fa3` 2026-10-09 | 19 |
| `engine/speaker_audio.py` | `69e1f4d87` 2026-10-09 | 18 |
| `engine/renderer/core/__init__.py` | `52c1f8e17` 2026-10-06 | 17 |
| `engine/renderer/core/tables.py` | `52c1f8e17` 2026-10-06 | 16 |
| `engine/obj_loader.py` | `0ebb03dae` 2026-10-09 | 10 |
| `editor/desktop_style.py` | `6337a7d3c` 2026-10-29 | 7 |
| `engine/renderer/core/base.py` | `6c53079ed` 2026-10-09 | 1 |
| `editor/version.txt` | `660de357c` 2026-10-14 | 1 |

## Checklist — local and two-way files

Fill the Status and PR columns as work lands.

Key: **UP** = upstream generic fix to Fio · **GAME** = move policy to `game/`
behind a Fio hook · **TAKE** = adopt Fio's version · **?** = investigate.

| File | Kind | MW +/− | Upstream since | Proposed | Notes | Status |
| --- | --- | --- | --- | --- | --- | --- |
| `engine/qt_game_view.py` | two-way | +742/−116 | 447 | UP + GAME | input ownership, play menu, pointer; largest reconcile | ☐ |
| `engine/terrain.py` | two-way | +545/−78 | 534 | UP + ? | biomes, grass limits vs Fio stamps/grass refinements | ☐ |
| `engine/overhead_sprite.py` | local | +595/−147 | 0 | GAME + UP | see leaks table | ☐ |
| `engine/asset_archives.py` | local | +196/−110 | 0 | UP (M1 prerequisite) | streaming mount, no extraction | ☐ |
| `engine/monster_ai.py` | local | +244/−25 | 0 | UP | hostility + AI hooks | ☐ |
| `editor/main_window.py` | two-way | +106/−195 | 101 | UP + GAME + ? | `.fiopak` map read, package player; drops `user_paths`/`ui_scale` | ☐ |
| `engine/shaders.py` | two-way | +152/−12 | 9 | UP | biome shader, `MAX_LIGHTS_TERRAIN` | ☐ |
| `engine/logic_camera.py` | local | +147/−6 | 0 | UP | shake, focus, overhead yaw/pitch | ☐ |
| `editor/property_editor.py` | two-way | +73/−24 | 163 | ? | mostly styling; Fio has since restyled | ☐ |
| `editor/terrain_editor.py` | local* | +25/−135 | 0 | ? / TAKE | lacks Fio terrain stamps | ☐ |
| `engine/entity_table.py` | two-way | +81/−6 | 123 | UP | head-art facing, `ENT_ALWAYS_SPRITE` for LevelChanger | ☐ |
| `engine/monster_table.py` | two-way | +81/−5 | 136 | UP | pursuit range | ☐ |
| `engine/logic_combat.py` | local | +87/−27 | 0 | UP | fire handler, projectile callbacks, secondary fire | ☐ |
| `engine/logic_player.py` | local | +73/−1 | 0 | UP | gamepad, keyboard look, modal input | ☐ |
| `engine/logic_thread.py` | two-way | +68/−9 | 4 | UP | game_session, fire handler, `time_scale` | ☐ |
| `engine/threaded_game_state.py` | local | +66/−1 | 0 | UP | gamepad and aim state | ☐ |
| `editor/console_commands.py` | local | +55/−5 | 0 | UP | archive-aware, `overheadangle` | ☐ |
| `editor/things.py` | local | +52/−0 | 0 | UP | light shadow props, render snapshot | ☐ |
| `engine/projectile_table.py` | local | +52/−2 | 0 | UP | per-shot hooks | ☐ |
| `editor/asset_browser.py` | two-way* | +2/−52 | 3 | TAKE + ? | MiniWind lacks Fio's audio-archive tab code | ☐ |
| `editor/editor_state.py` | local* | +19/−45 | 0 | TAKE + ? | `_adopt_stream_records` removed | ☐ |
| `editor/scene_hierarchy.py` | two-way | +39/−3 | 90 | ? | styling + stream state | ☐ |
| `engine/view_distance.py` | local | +39/−3 | 0 | UP | ambient setting helpers | ☐ |
| `editor/loading_overlay.py` | local | +35/−7 | 0 | UP / TAKE | font caching; game docstrings | ☐ |
| `editor/view_2d.py` | local* | +7/−29 | 0 | TAKE | lacks `SelectionLookup` | ☐ |
| `engine/audio_archives.py` | two-way | +20/−9 | 98 | ? | reconcile with asset_archives decision | ☐ |
| `engine/renderer/core/resources.py` | two-way | +33/−17 | 4 | UP | archive-aware texture read | ☐ |
| `engine/renderer/forward/renderer.py` | local | +27/−0 | 0 | UP | grass enable/quality settings | ☐ |
| `engine/logic_interaction.py` | local* | +19/−25 | 0 | ? | live LevelChanger check vs `levelchanger_eligible` | ☐ |
| `plugins/bigworld/runtime.py` | local | +24/−3 | 0 | UP | `set_reach` | ☐ |
| `plugins/bigworld/tests/test_bigworld_overhead_fit.py` | local | +20/−0 | 0 | UP | with `set_reach` | ☐ |
| `engine/renderer/core/visibility.py` | local | +19/−12 | 0 | UP | brush frustum cull | ☐ |
| `engine/floating_windows.py` | local | +18/−2 | 0 | UP | wheel routing | ☐ |
| `engine/savegame.py` | local | +17/−8 | 0 | UP | snapshot builder | ☐ |
| `engine/logic_triggers.py` | local | +16/−3 | 0 | UP | damage kind/source/filter | ☐ |
| `plugins/bigworld/persistence.py` | local | +15/−3 | 0 | UP | shallow normalize | ☐ |
| `engine/player.py` | local | +15/−7 | 0 | UP | speed scale, movement angle | ☐ |
| `editor/SettingsWindow.py` | two-way | +14/−0 | 21 | GAME | "Allow Fio maps" | ☐ |
| `engine/terrain_style.py` | two-way | +13/−0 | 31 | UP | archive-aware | ☐ |
| `engine/logic_render.py` | local | +13/−3 | 0 | UP | camera history | ☐ |
| `editor/debug_console.py` | local | +12/−1 | 0 | UP | `repeat_text` | ☐ |
| `engine/logic_world.py` | local | +12/−5 | 0 | UP | `levelchanger_usable` | ☐ |
| `engine/renderer/forward/lighting.py` | local | +11/−3 | 0 | UP | shadow props | ☐ |
| `engine/renderer/forward/passes.py` | two-way | +10/−0 | 48 | UP | grass flags, sprite tint/spin | ☐ |
| `engine/renderer/forward/shaders.py` | two-way | +10/−8 | 8 | UP | sprite tint | ☐ |
| `editor/ui.py` | two-way | +7/−8 | 43 | ? | `LAYOUT_VERSION` 4→7 | ☐ |
| `engine/textures.py` | local | +7/−1 | 0 | UP | archive-aware | ☐ |
| `plugins/bigworld/README.md` | two-way | +8/−3 | 8 | UP | light fade doc | ☐ |
| `engine/change_journal.py` | two-way | +6/−0 | 40 | UP | `FACING` bit | ☐ |
| `engine/renderer/core/overlays.py` | local | +6/−1 | 0 | UP | view-aligned billboards | ☐ |
| `engine/renderer/forward/instancing.py` | two-way | +4/−2 | 8 | UP | tint/spin attributes | ☐ |
| `engine/effect_entity.py` | local | +4/−3 | 0 | GAME | fire texture default | ☐ |
| `engine/logic_session.py` | local | +4/−0 | 0 | UP | reset focus / last damage | ☐ |
| `engine/renderer/api.py` | local | +4/−0 | 0 | UP | `pre_sprites` | ☐ |
| `engine/animated_texture.py` | local | +2/−1 | 0 | UP | file-like input | ☐ |
| `editor/io_editor_widget.py` | local | +2/−0 | 0 | UP | | ☐ |
| `engine/README.md` | two-way | +1/−0 | 2 | UP | lists `render_camera.py` | ☐ |
| `engine/level_validation.py` | local | +1/−1 | 0 | UP | overhead yaw/pitch keys | ☐ |
| `editor/shortcuts.py` | two-way | +1/−0 | 1 | UP | Backspace delete | ☐ |
| `plugins/bigworld/editor_streaming.py` | local | +1/−1 | 0 | GAME | `miniwindsettings` leak | ☐ |

\* mostly removals; see the caveat above.

## Files present on one side only

**Only in MiniWind:**

- `engine/game_input.py` → UP (input-ownership seam)
- `engine/hostility.py` → UP (hostility seam)
- `engine/render_camera.py` → UP (camera interpolation)
- `engine/terrain_biomes.py` → UP (generic regional biomes; MiniWind supplies the maps)
- `engine/game_package.py` → UP (data-only package player)
- `plugins/bigworld/tests/test_bigworld_runtime_spawns.py` → UP with Big World changes

**Only in Fio:**

- `engine/terrain_stamp.py` and `editor/selection.py` → MiniWind is behind
- `editor/user_paths.py` and `editor/ui_scale.py` → needed for Milestone 1
- `plugins/tidy/` (36 files) → a separate Fio sample plugin; MiniWind doesn't need it

## Baseline test results

These were run on Linux with Python 3.13 and the pinned `requirements.txt` in a
venv. The command was
`QT_QPA_PLATFORM=offscreen PYOPENGL_PLATFORM=glx python -m pytest -m "not gl and not benchmark"`.
CI uses Python 3.14, so treat these as indicative.

`PYOPENGL_PLATFORM=glx` is needed in this container: without it, PyOpenGL
picks EGL and test collection fails with
`'NoneType' object has no attribute 'eglGetCurrentContext'`. The same happens
on both repos.

| Repo | Result |
| --- | --- |
| MiniWind @ `68c0ba8b2` | 7652 passed, 17 failed, 2 errors, 34 skipped (15 min, `-n 4 --timeout 180`) |
| Fio @ `c2d8ed5b3` | 5973 passed, 34 skipped (12 min, `-n 4 --timeout 180`) |

A serial MiniWind run (no xdist) hung in
`tests/tools/test_debug_tables.py::test_the_terrain_table_is_shown` at 74%
and was killed after 25 minutes. The serial Fio run was killed at the same
limit. Under `pytest-xdist` with `pytest-timeout`, both runs completed and
nothing timed out. Use `-n 4 --timeout 180` until the hang is understood.

MiniWind failures on unchanged `main`, grouped by what they say about the
migration:

- **Boundary:** `tests/integration/test_backport_boundaries.py::test_no_module_imports_a_game_package`.
  `tests/test_additional_head_pool.py`, `tools/editor_ui_audit.py`,
  `tools/benchmark_navigation.py`, `tests/visual/test_windmill_asset.py` and
  `tests/engine/test_sdl_runtime.py` import `game`. These are Fio-shaped
  test/tool locations that already depend on the game.
- **Diverged engine default:** `tests/engine/test_effect_primitive.py`
  (2 tests). Fio's tests expect `fire01.gif`, and MiniWind's `effect_entity.py`
  defaults to `fire02.gif`. This is the leak listed above.
- **Suite integrity:** `tests/test_suite_integrity.py` (2 tests). They flag
  `object.__new__` in `tests/renderer/test_camera_interpolation.py:46` and
  `tests/threading/test_frame_pacing.py:17`.
- **Shipped world data:** `test_release_final_pass.py::test_every_shipped_connection_resolves[miniwind_world.json]`.
  PathNode targets are stored as comma lists (`'ROAD_0002,ROAD_0004,ROAD_0067'`),
  and Fio's validator reads each list as one name.
  `game/tests/test_cave_entrances.py` and `game/tests/test_windmills.py` also fail.
- **Editor layout (Qt offscreen):** `tests/editor/test_toolbar_button_size.py`
  (3 tests) and `tests/editor/test_macos_layout.py`.
- **Game logic, not investigated:** `game/tests/test_disposition.py`,
  `test_editor_integration.py`, `test_faction_spine.py`,
  `test_inventory_artwork.py` and `test_storyteller.py` (one test each). Some
  may depend on test order under xdist.
- **Errors at teardown:** `tests/engine/test_audio_backoff.py` and
  `tests/editor/test_pause_menu.py`. The container has no audio device, and
  creating a Qt OpenGL context fails.

GUI and GL tiers (`-m gl`, desktop smoke, player/Android) were **not** run.
