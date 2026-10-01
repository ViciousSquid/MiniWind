# MiniWind → Fio 2.5.10 migration — Phase 1 archaeology & migration matrix

Status: **Phase 1 (archaeology) complete; no engine code changed yet.**
This document is the decision record the later phases execute against.

Categories used throughout (from the migration brief):

| # | Meaning | Action |
|---|---------|--------|
| **1 OBSOLETE** | Fio 2.5 now provides it | delete MiniWind version, use upstream |
| **2 REIMPLEMENT** | MiniWind needs the behaviour; old code is 2.4-shaped | rebuild against the 2.5 seam |
| **3 GENERIC** | genuinely generic Fio capability MiniWind added | port the smallest clean seam into 2.5 |
| **4 GAME** | MiniWind policy living in Fio | move under `game/` |

---

## 1. Versions

| | Commit | Notes |
|---|---|---|
| **Embedded baseline** | Fio `24a2757e` (2026‑09‑16, "Updated with 'Match case' button") | one commit past tag `v2.4.1.1609` (`1747926b`); the only difference is `editor/scene_hierarchy.py`, so its "Match whole word" button is **upstream, not a MiniWind delta** |
| **Audit branch substrate** | Fio `4be5cefc` (2.5.5.2409) | used by `claude/fio-2.5.5-migration-audit` |
| **Target** | Fio `f612655e` (branch `2.5.10.3009_Latest`, 2026‑09‑30) | 2 053 commits after the baseline, **1 376 after the audit substrate** |

Consequence: the audit branch is evidence, not a base. Between its substrate and
the target, `renderer_core.py` changed by ~4 100 lines, `entity_table.py` ~1 270,
`logic_thread.py` ~1 900, `shaders.py` ~1 400, and — decisively — **the per-monster
render snapshot the audit hooked into no longer exists.** EntityTable is now fed
by the change journal (`TrackedAttribute` writes), not by a per-frame snapshot.

---

## 2. Findings from the audit branch (`claude/fio-2.5.5-migration-audit`)

Three commits: vendor Fio verbatim → re-attach game through seams → route actors
through EntityTable. That *shape* is right and is the plan below. Revalidated
against current Fio:

| Audit idea | Verdict against 2.5.10 |
|---|---|
| Vendor Fio verbatim, re-apply MiniWind as seams | **Keep** (the method) |
| NPC/Creature remain Fio `Monster`s through EntityTable → instanced sprites | **Keep** |
| `game/actor_look.py`: death identity published as *derived* `custom_dead` | **Keep** — `entity_table.py:208` still resolves the dead sprite from `custom_dead`. Must be kept out of saved maps (derived, not authored). |
| Heading/tint/opacity added as keys to the per-frame render snapshot | **Obsolete mechanism** — snapshots are gone. Current Fio already has journalled `render_alpha` and `sprite_fixed_yaw` columns (driven by `TrackedAttribute`s `_respawn_fade_alpha` / `_carry_sprite_yaw` on Prop) that already reach the instanced sprite data (`renderer_core.py:3038‑3039`). MiniWind opacity + heading ride those; only **tint** is missing. |
| Sprite shader gains uniforms; instanced program derived by rewrite | Re-check against current shader; current instanced sprite already carries fixed-yaw + alpha as instance attributes (`shaders.py:461‑467`). Add tint the same way. |
| `register_builtin_game` in PluginManager | **Obsolete** — upstream now (`plugins/manager.py:448`) |
| API 1.5.0: property sections, KV suggestions, inspector providers | Needed, but the audit added them to the manager **without wiring the editor** (editor stayed verbatim): `kv_key_suggestions` and `inspector_snapshot` had no consumer. |
| LogicThread seams (pause, fire handler, damage filter, aim yaw, projectile callbacks) | **Keep the contracts**, re-apply to current LogicThread |
| `set_aim` / `queue_secondary_shot` in ThreadedGameState | Producer side had **no caller** — the view side (`qt_game_view`) was never migrated, so mouse aiming and right-click were dead on the audit branch |
| MiniWind `monster_ai.py` deltas | **Silently dropped** by the audit — factions (`_faction_hostile`), "only hostiles hunt the player", dice damage, attack styles, spell projectiles were all lost there |
| MiniWind `editor/main_window.py`, `qt_game_view.py` deltas | **Silently dropped** — pause menu, standalone play, mouse control, inspector, sound falloff, stuck arrows, overhead NPC weapons |

Lesson for this migration: every MiniWind delta gets an explicit row below, and
every seam gets both its producer and its consumer.

---

## 3. File-level diff vs baseline (non-asset)

Unchanged vs baseline (ignoring CRLF/whitespace): `engine/renderer_F.py`,
`player.py`, `physics.py`, `camera.py`, `constants.py`, `textures.py`,
`resource_manager.py`, `audio_manager.py`, `obj_loader.py`, `sysmon.py`,
`savegame.py`, `editor/package_dialog.py`, `tools/*`. → all **1 OBSOLETE**
(take current Fio).

MiniWind-only files outside `game/`:
`engine/{gore,facing,combat_loadout,pause_menu,sound_falloff}.py`,
`engine/tests/`, `editor/launcher.py`, `editor/tests/`,
`tests/integration/test_miniwind_boundaries.py`,
`tests/plugins/{test_console_commands,test_mandatory_plugins}.py`.

Largest modified files (changed lines vs baseline): `qt_game_view` 1342,
`main_window` 745, `overhead_sprite` 671, `monster_ai` 612, `logic_thread` 337,
`main.py` 269, `plugins/integration` 244, `plugins/manager` 238,
`editor/things` 238, `renderer_core` 124, `floating_windows` 95,
`property_editor` 94, `SettingsWindow` 78, `monster_constants` 77.

---

## 4. Migration matrix

### 4.1 Engine — LogicThread / game state

| MiniWind delta | Cat | 2.5 destination |
|---|---|---|
| `game_session` attribute | 3 | one generic attr on LogicThread, set/cleared by the game host at play start/stop; cleared in LogicThread teardown too (lifetime test) |
| `gameplay_paused` (world frozen, plugins still tick) | 3 | early-out in current `_update` before world simulation, still dispatching `plugins.tick` |
| `player_fire_handler(logic, mode)` + secondary fire | 3 | hook in current `_handle_shooting`; secondary-shot queue in ThreadedGameState **and** its producer (right mouse) in the view |
| `_player_damage_filter(damage, kind)` | 3 | hook at top of current `_apply_player_damage` |
| pointer aim yaw/direction | 3 | `ThreadedGameState.set_aim/get_aim_*`; producer = view mouse-control mode (see 4.3) |
| projectile `on_hit`, `on_impact`, `max_dist`, `owner_is_player`; publish `vel/color/kind` | 3 | current projectile update; audit the 2.5 projectile publication (dense or list) and add fields to whatever it publishes |
| blood-stain / gib sprite data | 2 | re-derive from current decal/bullet-mark path; gib *rule* is game (4) |
| game tick / lifecycle dispatch | 1 | upstream `PluginManager` builtin-game dispatch (`on_play_start/on_tick/on_play_stop`) |

### 4.2 Engine — Monster AI

| MiniWind delta | Cat | 2.5 destination |
|---|---|---|
| faction hostility `logic._faction_hostile(a, b)` (per-pair Python predicate) | 2+3 | **dense team relation matrix**: game publishes `hostile[team_i, team_j]` (bool, indexed by MonsterTable's interned team ids); the vectorised nearest-enemy pass masks with it. Default (no matrix) = Fio's "different team is enemy". No per-pair callback. |
| "only hostile actors hunt the player" (`aggression`, faction vs `player`) | 2+3 | same matrix, one row/col for the player team, + a per-row `hunts_player` mask; default = Fio behaviour (all awake monsters hunt) |
| dice-rolled attack damage via `game_session.game.dice` | 3 | a `monster_damage_roll(attacker, max, style)` hook on the AI; default = Fio's flat damage |
| attack styles (melee/ranged/spell), `_primary_spell`, spell projectiles | 2/4 | style selection is game policy (4); the projectile spawn uses the 2.5 projectile path with the 4.1 fields |
| `_face_dir` / `engine/facing.py` | 4 | `game/`; result written to the actor's journalled heading attribute |
| `monster_constants` tweaks | 2 | re-evaluate per constant; game-specific tuning → game-owned overrides |

### 4.3 Engine — view / renderer

| MiniWind delta | Cat | 2.5 destination |
|---|---|---|
| `_draw_overhead_npcs` (per-NPC Python GL draw: heads, weapons, hover tint) | **DELETE** | replaced by EntityTable rows + instanced sprite pass |
| head heading | 2 | journalled yaw → existing `sprite_fixed_yaw` column; "lie flat on ground" overhead mode may need one orientation flag (verify against current shader first) |
| opacity / fade | 1/2 | existing `render_alpha` column; generalise its source attribute (today Prop-only `_respawn_fade_alpha`) to a generic journalled render-alpha attribute on Things |
| hit flash / hover tint | 3 | **new generic `render_tint` (rgba) column** + instance attribute; default 0 = bit-identical draw. Which colour and when = game policy |
| dead/gibbed identity | 2 | derived `custom_dead` (audit idea), game-owned in `game/actor_look.py` |
| actor-held weapon quads | 3 | smallest generic option: a secondary "attached sprite" row / layer in EntityTable (to be designed after reading current sprite pass); **not** a Python draw loop |
| player overhead head/weapon/flash (`overhead_sprite.py`, 671 lines) | 2 | start from current Fio `overhead_sprite.py` (302 lines); re-add only player presentation MiniWind needs via `game_session` duck-typing seam |
| ground layer constants (floor < blood < gib < actor < weapon) | 2 | express as per-row y-offset/layer in the dense path |
| stuck arrows, arrow projectile orientation, projectile lights | 2 | arrows oriented by published `vel`; stuck arrows as game-spawned entities or decals through the dense path |
| mouse-control mode (pointer → aim), cross cursor | 3 | generic view option; producer for `set_aim` |
| `sound_falloff.py` (speaker volume by distance) | 3 | generic engine audio seam |
| pause menu (`engine/pause_menu.py`) + save slots in `main_window` | 4 (+3 seam) | game UI under `game/ui/`, drawn via `render.overlay`; needs a generic "game modal wants keys/Escape" seam |
| inspector (`inspect`/`mind` command, `NpcDebugWindow`) | 3 + 4 | generic inspect-pick + floating window in Fio consuming `inspector_snapshot`; MiniWind snapshot provider stays in `game/` |
| renderer_core/shaders sprite `tint/rot/opacity` uniforms | **DELETE** | superseded by the columns above |

### 4.4 Editor

| MiniWind delta | Cat | 2.5 destination |
|---|---|---|
| `things.py` head sprites, dead-head composite, sprite caches | 4 / 1 | policy → `game/actor_look.py`; caches: current Fio's resolution path |
| `things.py` `max_health` default, custom_dead pop | 4 | NPC/Creature subclasses in `game/entities.py` |
| `property_editor` KV suggestions | 3 | `register_kv_suggestions` **with** the property-editor consumer |
| `property_editor` accent colour `#F08000 → #d61604` | 3 | visual identity: a small editor accent/theme setting rather than a fork |
| property sections / grouped specs (`plugins/integration`) | 3 | `register_property_section` + editor consumer, on top of API 1.4.0 |
| superseded palette entries (Monster/Pickup hidden in favour of Creature/ItemPickup) | 3 | generic "hide entity from palette" registration |
| `io_handlers` visibility notify, speaker fields | 1? | verify current Fio already calls `notify_authored_visibility_changed`; drop if so |
| `io_system` `logic_keyvalue` alias removal, `io_handlers` registering `_STATE_INPUTS` on `logic_state` only | 1 | upstream now matches: the store is `LogicState` only, no class alias, no I/O alias (see §4.8) |
| `console_commands` `inspect`, `main_window` passed to dispatch | 3 | upstream API 1.4.0 console commands take `(args, main_window, logic, play_mode)`; inspect per 4.3 |
| `main_window` title/About branding | 3 | product name from config, not a fork |
| `main_window` reset-prompt-on-play, `_reset_game_progress` | 4 | game menu action |
| `main_window` standalone/kiosk play, shortcut suspension during play, layout defaults | 3 | review each against current main_window; port only what is missing |
| `main_window` removal of procedural map generator | 4 | leave Fio's generator; hide via product config if needed |
| `scene_hierarchy` match-whole-word | 1 | upstream |
| `SettingsWindow` GAME tab (launcher, mouse control) | 3 | settings tab registration seam or generic "Game" settings |
| `floating_windows.NpcDebugWindow` | 3 | generic inspector window (4.3) |
| `editor/launcher.py`, `main.py` splash/launcher | 4 | game-owned launcher invoked by a generic startup hook |

### 4.5 Plugins

| MiniWind delta | Cat | 2.5 destination |
|---|---|---|
| builtin-game surface | 1 | upstream `register_builtin_game` |
| entity wizards, singletons, extra fields, console commands | 1 | upstream API 1.4.0 |
| `MANDATORY_PLUGINS = ("bigworld",)` | 3 | minimal generic mandatory-plugin config (product setting), not a BigWorld fork |
| BigWorld `enabled = True` | 3 | driven by mandatory config; plugin stays verbatim |
| BigWorld `logickeyvaluestore` in `DEFAULT_PERSISTENT_TYPES` removed | — | **not** carried: upstream 2.5.10 still lists the dead token, but it matches no class, so it is inert. BigWorld stays verbatim; raise the one-line cleanup upstream (see §4.8) |

### 4.6 game/ → Fio dependencies

`game/` imports: `editor.things.{Monster,Thing,Light,LogicState,ENTITY_TYPES}`,
`editor.property_editor.CollapsibleSection`, `editor.debug_console`, `editor.ui`,
`engine.monster_constants`, `engine.spatial.{CELL_SIZE,PARKED_*,TIER_*}`,
`engine.floating_windows.{FloatingWindow,CallbackWindow}`,
`plugins.{api,manager,entitybase}` — all still exist in 2.5.10.
Plus the misplaced MiniWind modules `engine.gore`, `engine.facing`,
`engine.combat_loadout` → **move to `game/`** (cat 4).

Reaching into internals to review during Phase 4/5: `logic._faction_hostile`,
`logic._player_damage_filter`, direct `properties` writes for render state
(`_hit_flash`, `_opacity`, `_facing`) — the last group must become journalled
attribute writes or they will never reach EntityTable.

### 4.7 Maps, save/load

| Item | Finding |
|---|---|
| `maps/village_walled_source.json` | format v3, 303 things: creature 131, marker 55, light 30, npc 28, container 19, itempickup 11, speaker 10, creaturespawn 10, path_node 4, spellbook 1, miniwindsettings 1, bigworldsettings 1, playerstart 1, logic_command 1; `terrain_data` in the old sculpt-offset form — must be verified against the new dense TerrainTable / GPU heightfield loader |
| expanded world (post-migration) | `game/tools/expand_world.py` grew the terrain to 40 x 40 chunks with `mesh_scale: 1.0`, moved the outlying sites rigidly with their ground (re-sculpted at the new place), added a heightmap-overlay mountain range and the Emberpeak Shrine, and removed the 2.4 invisible floor slabs (2.5 terrain is solid). BigWorld `terrain_fill` must stay off for this map: it re-bounds the terrain in play, and the heightmap overlay is laid over the authored bounds |
| overhead performance (post-migration) | BigWorldSettings `fit_overhead_camera` (MiniWind's plugin copy, off by default) sizes residency from `LogicThread.overhead_ground_footprint()` (screen corners + 256, refreshed every 256 units of movement) and makes NEAR the screen rectangle; BigWorld publishes `logic.sim_tiers_fit_view`, and only then do MonsterAI (one pass per 0.2 s, per-row delta) and MiniwindSession (one tick in 4) treat ACTIVE as off screen. `terrain_stream` streams terrain chunks inside the authored bounds (heightmap overlay stays aligned). Parked monsters are left out of the AI pass; the map has no BigWorld debug overlay; `water_quality = cheap`; water/glass skip the frame copy when none is in view |
| unknown entity preservation | **1** — current Fio keeps unknown types as `UnresolvedThing` and round-trips them verbatim |
| `.fiosave` | MiniWind never forked `savegame.py`; it persists via public properties + `LogicState`/`GlobalStore`. Fio 2.5 now writes delta saves against the base map and restores BigWorld cells — needs regression coverage, not code |
| derived `custom_dead`, transient look keys | must not leak into saved maps / saves |

### 4.8 Key/value store → `LogicState`

The pre-2.4 `LogicKeyValueStore` entity no longer exists in Fio; `LogicState`
(`editor/things.py`) is the only persistent named store, and Fio's own tests
enforce it (`tests/logic/test_logic_state.py`: no `LogicKeyValueStore`
attribute; a `logic_keyvalue` record no longer resolves to `LogicState`).

* Surviving "keyvalue" names in Fio are **method names on the LogicState path**,
  not the removed entity: `IOManager.query_keyvalue` / `set_keyvalue` read and
  write `LogicState` stores (entity first, then `LogicState._persistent_registry`),
  and `PropertyEditor._build_keyvalue_group` is the LogicState table editor.
  MiniWind's State Store quick-insert suggestions (§4.4) attach to that group.
* MiniWind content is already clean: no `keyvalue` reference in `game/`,
  `game/data/`, `quests/` or `maps/`; game state goes through `LogicState` and
  `plugins.api.GlobalStore` (which binds to the same registry).
* The one upstream remnant is the inert `"logickeyvaluestore"` string in
  `plugins/bigworld/manager.py` `DEFAULT_PERSISTENT_TYPES`.
* **Test conflict:** MiniWind's
  `tests/integration/test_miniwind_boundaries.py::test_the_pre_2_4_key_value_store_is_removed_from_code`
  scans the Fio packages *and* `game/` for the old tokens, so it would fail on
  verbatim upstream BigWorld. Rescope it to MiniWind-owned code (`game/`,
  MiniWind tests excluded as now) and rely on Fio's own
  `test_logic_state.py` for the engine side, rather than forking BigWorld to
  satisfy it. Also update `README.md:389`, which describes the old store.

---

## 5. Execution plan (Phases 2+)

1. **Substrate**: replace `engine/ editor/ plugins/ player/ tests/ conftest.py`
   with Fio `f612655e` verbatim; move `engine/{gore,facing,combat_loadout}` into
   `game/`; keep MiniWind content (`game/ maps/ quests/ assets/`). Run Fio's own
   suite green before touching MiniWind.
2. **Seams** (one commit each, producer + consumer + test): logic-thread hooks
   (4.1); AI team-relation matrix + damage roll (4.2); editor API 1.5 with editor
   consumers (4.4); mandatory-plugin config (4.5).
3. **Actor visuals**: journalled heading/alpha/tint attributes → EntityTable
   columns → instanced sprite; `game/actor_look.py` owns policy. Delete every
   per-actor draw path.
4. **Overhead**: player presentation, attached weapon sprites, ground layering,
   projectiles/arrows through the dense path.
5. **Game UI**: pause menu, inspector, launcher, mouse control, settings — as game
   code on generic seams.
6. **Tests & GL validation** per the brief's Phase 11/12 list, with Fio's own
   regression and shader suites as acceptance criteria.
