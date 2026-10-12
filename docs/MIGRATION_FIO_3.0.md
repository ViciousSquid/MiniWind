# MiniWind → Fio 3.0 migration record

MiniWind's engine moved from the Fio 2.5.10.3009 snapshot (vendored at MiniWind
`fb3fe1d`, the `core_2.5.10.0110_stable` line) to **Fio 3.0.0.1010**
(`ViciousSquid/fio` branch `3.0.0.1010_Latest`, commit `9d57cab6`), then
took Fio's later work on that branch up to commit `f445fac1` (see
[Update to `f445fac1`](#update-to-f445fac1-2026-10-12)).

Fio is the authoritative version: its files were vendored verbatim, and only
MiniWind's own seams were re-applied on top, each in the Fio 3 file that now
owns the concern. The previous migration (2.4 → 2.5) is recorded in
[`MIGRATION_FIO_2.5.md`](MIGRATION_FIO_2.5.md).

## Decisions

| Question | Decision |
|---|---|
| Pause menu | **MiniWind's.** Fio 3's Esc path (`open_pause_menu`) raises the game's `QtGameView.play_menu` when one is installed. |
| Cutscenes | **Fio's.** Tools → Cutscenes (Fio's wizard) and Fio's LogicCamera runtime. MiniWind's parallel `miniwindcutscene` system is removed; no map used it. |
| Music volume | **One setting**: Fio 3's `[Audio] music_volume` (0–100), shared by MiniWind's options page and Settings > Play Modes > Audio. `[GAME] music` stays the pause menu's on/off switch. |
| Player movement | **Fio's** Quake 2 movement (walk 200, diagonals 283, acceleration/friction, Shift sprints, lower jump). |

## What Fio 3 changed that MiniWind had to follow

- The 4,700-line `LogicThread` is split into owned runtimes
  (`player_runtime`, `camera`, `session_runtime`, `world_runtime`,
  `combat_runtime`, `cutscene_runtime`, ...). Fio 3 has no forwarding: a 2.5
  attribute read such as `getattr(logic, "player", None)` quietly returns None.
- The renderer is the `engine.renderer` package behind a plugin protocol
  (plugin API 1.6/1.7).
- Monster projectiles live in a structure-of-arrays `ProjectileStore`, not a
  list of dicts.
- Fio 3 ships its own pause menu, cutscene wizard and runtime, kiosk window
  modes, audio volumes, a loading throbber, item definitions and Big World's
  overhead-camera fit.
- Python 3.14 (GIL build) is required; the Benchmark plugin and
  `plugins/integration.py` are gone.

## Where each MiniWind seam lives now

| MiniWind seam | Fio 3 home |
|---|---|
| `game_session`, `player_fire_handler`, `_player_damage_filter` | `LogicThread` host attributes, read by the runtimes |
| Fire handler, primary/secondary dispatch | `LogicCombat._handle_shooting(secondary)`; `LogicThread` drains/dispatches secondary shots |
| Game projectiles (own range, `on_hit`, `on_impact`) | `LogicCombat.spawn_projectile`; `ProjectileStore` `max_dist`/`tag` columns and callback table |
| Damage filter with damage kind | `LogicTriggers._apply_player_damage(damage, damage_kind)` |
| Pointer aim yaw | `LogicPlayer.update_primary`; `ThreadedGameState.set_aim` |
| Camera focus, HOME | `LogicCamera.set_camera_focus` / `focused_camera_centre`; `LogicRender`; reset per session in `LogicSession` |
| Faction hostility, who hunts the player | `MonsterAI.set_hostility` (`engine/hostility.py`) in the dense pass, the per-monster path and both nearest-enemy kernels |
| Attack-style hook | `MonsterAI.install_attack_style_hook` |
| Game pause menu, game pointer, floating windows in play | `QtGameView.play_menu`, `game_pointer`, `floating_windows` (also `window_manager`) |
| Player head sprite, pose, hurt flash, held weapon | `QtGameView._draw_overhead_sprite`; `engine/overhead_sprite.py` (unchanged in Fio 3, so MiniWind's version is carried as-is) |
| Game HUD replaces Fio's | `QtGameView._suppress_default_hud` |
| View follows the game's camera mode in play; chosen mode restored after | `QtGameView._paint_frame`, `toggle_play_mode` |
| Water/glass refraction only when in view | `engine/renderer/core/visibility.py`, `engine/renderer/forward/renderer.py` |
| Game boot, launcher, default map, mandatory plugins | `main.py` |
| Staged loading bar | `editor/loading_overlay.py`; Fio 3's throbber stands down while it is up |
| Escape to a game modal, HOME, `focus_on_bounds(views=)` | `editor/main_window.py` |
| Allow Fio maps | Settings > Editor > Maps (`[Editor] allow_fio_maps`) |
| `Monster.get_render_snapshot` | `editor/things.py` |
| `terrain_stream` | Big World config/entity/plugin/runtime |
| Wheel zoom widens the simulated area (`BigWorldSession.set_reach`) | `plugins/bigworld/runtime.py`; driven through `game/fio.py` |

The game reaches Fio 3's runtimes only through **`game/fio.py`**;
`tests/integration/test_miniwind_boundaries.py` fails if game code reads one
of the 2.5 `LogicThread` attributes again.

## What went away

- MiniWind's copies of features Fio 3 now has: the overhead-fit residency
  code and `sim_tiers_fit_view` (Big World's `tiers.near_rect`), MonsterAI's
  off-screen throttle, `apply_kiosk_display_mode` (Fio's
  `_apply_kiosk_window_mode`), the batched-enemy threshold tweak (Fio 3
  always batches), `fit_overhead_camera` (automatic for an overhead camera;
  the key in the map is ignored).
- MiniWind's cutscene system: `game/cutscene.py`, `cutscene_files.py`,
  `ui/cutscene_ui.py`, the `miniwindcutscene` entity and its I/O, the forked
  wizard, `test_cutscene.py` and the cutscene workflow.
- 2.4-era leftovers no test run included: `engine/tests/`, `editor/tests/`,
  `engine/sound_falloff.py`.
- The projectile render records (`_projectile_records`): nothing read them.
- The Benchmark plugin (removed upstream).

## Verification

Run on CPython 3.14.6 (GIL) with the pinned requirements, in Fio 3's CI tiers.

| | Result |
|---|---|
| Before (MiniWind on 2.5.10, one process) | 4,466 passed, 158 skipped |
| After: core tier (`not qt and not gl`) | 3,270 passed, 8 skipped, 0 failed |
| After: Qt tier (offscreen) | 2,404 passed, 36 skipped, 1 failed (upstream, below) |
| After: GL tier (xvfb + llvmpipe) | 195 passed, 4 skipped, 0 failed |
| Real boot (dev harness): village map, play, exit | renders as before (HUD, minimap, heads, overhead camera); editor camera restored on exit |

The one failure, `tests/editor/test_toolbar_buttons.py::
test_the_greyed_strip_is_used_by_the_toggles_and_nothing_else`, fails the same
way on pristine Fio 3: Fio added the Visgroups toolbar button after writing the
test. It is left as Fio ships it. Skips are Fio tests needing content MiniWind
does not ship (Fio's example maps, the Tidy plugin, the showcase cutscene).

Also kept from the 2.5 behaviour, outside Fio's files: MiniWind's map opens
with the editor camera at its Player Start (`game/integration.py`). Fio 3 sets
that on the view alone, which the logic thread's editor camera undoes, and
Fio's GL tests are written against the default camera. (Fio fixed this
upstream; the update to `f445fac1` below drops MiniWind's version.)

Note: upstream Fio 3's own suite segfaults when everything runs in one
process here (Qt teardown in its `main_window` fixture); run it by tier, as
Fio 3's CI does.

## Update to `f445fac1` (2026-10-12)

Fio's `3.0.0.1010_Latest` branch moved on from `9d57cab6` to `f445fac1`
(the version string is still `3.0.0.1010`). Fio stays authoritative: every
file MiniWind had not changed was taken as Fio has it, and the files both
sides changed were merged three ways against `9d57cab6`.

### What came in

- Gameplay: a hitscan shot's pellets trace one snapshot of the world, then
  apply their hits in order; linked portals share one active state
  (`editor/portal_links.py`; portal outputs are now `OnEnabled`,
  `OnDisabled`, `OnToggled`); the crouch view eases over 0.5 s; the Prop
  registry is built once at Play start.
- Editor: `QtGameView.set_editor_camera` moves the view's and the logic
  thread's editor camera together, so a map opens at its Player Start (now
  facing the way the player spawns); the Camera dropdown follows play and
  resets to First Person per map (`sync_camera_mode_combo`,
  `reset_camera_mode`); F12 before kiosk mode no longer crashes; the
  cutscene wizard's Load button; the Visgroups window's look.
- Performance: per-row brush uniforms uploaded through raw entry points
  (`engine/renderer/core/uniform_rows.py`); Effect columns published only
  when the store changes; small mover groups walked row by row; terrain GL
  objects deleted in the 3D view's own context (`QtGameView.gl_context`).
- Build: the Windows ARM64 job in `build.yml` and the ARM64 markers in
  `requirements.txt` (`PyQt5-WinARM64` on Windows ARM64).
- Tests: Fio's new and updated tests, including the toolbar test that
  failed above. Fio's new dev tools under `tools/`.

### Decisions

| Question | Decision |
|---|---|
| Editor camera at the Player Start | **Fio's.** `set_editor_camera` replaces MiniWind's `_sync_editor_camera` and the `_camera_to_player_start` wrapper in `game/integration.py`. |
| `requirements.txt` | **Fio's, verbatim** (Pillow 11.3.0, the ARM64 PyQt5 markers). |
| Windows ARM64 build | **Ported** into MiniWind's own `build.yml` with MiniWind's Nuitka inputs (`game`, `quests`); the release gains `Fio-Windows-ARM64.zip`. |
| Fio content in tests | **Not shipped.** No Fio example maps, no showcase cutscene, no Tidy plugin; the tests that used them were changed instead (below). |

### Fio's tests without Fio's content

Every Fio test now runs in MiniWind; none is skipped for missing content, and
`tests/conftest.py` (which skipped them) is gone. Where a Fio test loaded one
of Fio's maps, it builds the level it needs in code with
`tests/helpers/scenes.py` (`showcase`, `monster_arena`, `portal_pair`,
`spawner_room`, `simple_room`, `terrain_map`), or uses a map MiniWind ships.
Where it used the Tidy plugin, it uses a fixture plugin in
`tests/plugins/fixtures` (`prop_extender`: own entity types plus an I/O
extension of `prop`; `menu_owner`: a Plugins-menu action, an Add-entity
entry and a tick), Big World, or a model MiniWind ships
(`assets/models/prop_book.obj`). Only one test went:
`test_tidy_reset_refiles_the_prop_it_moves`, which tested Tidy's own runtime.
Tidy's own test package (`plugins/tidy/tests`) is not vendored.

MiniWind still differs from Fio's test files in three places:
`pytest.ini` also collects `game/tests`;
`tests/integration/test_backport_boundaries.py` exempts the game layer
(`game/`) and the two names MiniWind's `editor/things.py` seam uses
(`hit_flash`, `npc`), since Fio's version forbids a game package outright;
and the tests above.

### Verification

CPython 3.14.6 (GIL), Fio's pinned requirements, Fio 3's CI tiers.

| | Result |
|---|---|
| Core tier (`not qt and not gl and not benchmark and not slow`) | 3,226 passed, 34 skipped, 0 failed |
| Qt tier (offscreen, `qt and not gl and not benchmark`) | 2,513 passed, 25 skipped, 0 failed |
| GL tier (xvfb + llvmpipe, `gl`) | 203 passed, 3 skipped, 0 failed |
| Real boot (dev harness): village map in the editor, play, exit | editor opens textured at the Player Start, facing the way the player spawns; Play renders the overhead camera, HUD, compass, clock, minimap and heads; leaving Play restores First Person |

None of the remaining skips is for missing content: they need
`glslangValidator` or `pyflakes`, which this environment lacks, or the
benchmark tier (`--run-benchmarks`).

One earlier run of the whole Qt tier in one process crashed (a segfault in
`tests/tools/test_debug_tables.py`, with logic threads of earlier tests
still running); that file passes alone, three times over, and the full tier
passed when run again. It is the single-process Qt teardown noted above.
