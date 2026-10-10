# MiniWind → Fio 3.0 migration record

MiniWind's engine moved from the Fio 2.5.10.3009 snapshot (vendored at MiniWind
`fb3fe1d`, the `core_2.5.10.0110_stable` line) to **Fio 3.0.0.1010**
(`ViciousSquid/fio` branch `3.0.0.1010_Latest`, commit `9d57cab6`).

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
| Escape to a game modal, HOME, editor camera hand-over, `focus_on_bounds(views=)` | `editor/main_window.py` |
| Allow Fio maps | Settings > Editor > Maps (`[Editor] allow_fio_maps`) |
| `Monster.get_render_snapshot` | `editor/things.py` |
| `terrain_stream` | Big World config/entity/plugin/runtime |

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
Fio's GL tests are written against the default camera.

Note: upstream Fio 3's own suite segfaults when everything runs in one
process here (Qt teardown in its `main_window` fixture); run it by tier, as
Fio 3's CI does.
