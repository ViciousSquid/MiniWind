# MiniWind → Fio 3.5 migration record (3.5.0.1211)

MiniWind's engine moved from Fio 3.0.0.1010 (taken up to upstream commit
`f445fac1`, plus later per-file backports) to **Fio 3.5.0.1111**, then to
**Fio 3.5.0.1211** (Milestone 7). The game
layer (`game/`) needed four source changes: `multiplayer/replication.py` and
`multiplayer/world.py` (a door's live position and state rows, below),
`ui/launcher.py` (engine and game versions shown apart) and `tools/soak.py`
(one BLAS thread, as `main.py`), plus three tests that followed. Everything
else MiniWind adds to Fio was re-applied in the Fio 3.5 file that now owns
the concern.

## Pinned sources

| | Ref | Commit |
|---|---|---|
| MiniWind (start) | `main` | `41eeb2c742b998ec3244356ac005a2faab450d0e` |
| Fio (first target) | `3.5.0.1111_Latest` | `9b2dca952b88e7c1abd1f5f5979764c3783490b4` |
| Fio (then) | `3.5.0.1111_CANARY` | `a278e956` (26 commits past `9b2dca95`) |
| Fio (now) | `3.5.0.1211_Latest` | `77387caaeba284b5467a180b1ba39e147aace86d` (40 commits past `a278e956`) |
| Common upstream ancestor | Fio `3.0.0.1010_Latest` | `f445fac1be58a1011da276a77de00ef9487add0a` |

`backup_3.0.0.3010` is an ancestor of `41eeb2c` (22 commits behind it), so
this migration carries everything on that branch plus the 22 newer feature
commits: four-player co-op, launcher lobbies and AI companions, navigation
and shadow invalidation, the freeze watchdog and error reporting, GC control,
co-op lock ordering, release hardening, and the windmill farmers. Every
engine/editor/plugin line those commits added was checked against the merged
tree and is present, in its Fio 3.5 home where the file was split.

Milestone 1 then brought in Fio's `3.5.0.1111_CANARY` up to `a278e956`: the
26 commits after the release under the same version string (monster hit
volumes measured from the feet and monsters seeing, shooting and taking
crossfire at their real heights, the `hitboxes` command and floating Monster
Debug window, end-user `.fiopak` packs, editor colour settings, Fio UI in
the HUD and pause menu). MiniWind keeps its sounds in `sounds.fiopak` (its
six loose sounds were packed in) rather than Fio's loose folder, and its
missiles are loosed at Fio's projectile body height
(`game.fio.projectile_body_lift()`), not a game constant.

Milestone 7 brought in Fio 3.5.0.1211 (`77387caa`): `a278e956` plus 40
commits, merged three-way against it, every line either side added since
that base checked present in the merged tree. It adds placed image, wet
(screen-space reflection) and stain decals, edited like terrain stamps
(`editor/decal_tool.py`, `engine/decal_textures.py`, the decal pass,
`decalfade`); the Asset Browser's single tiled view with thumbnails read and
cached off the UI thread (`editor/asset_thumbnails.py`, which supersedes
MiniWind's own thumbnail cache; MiniWind keeps only its dormant-launch
deferral); Edit > Colours tabs; and its Decal button icon, added to
MiniWind's branded `editor.fiopak`. Not taken: the Android player's decals
and workflow, `CHANGELOG.md`, the `Wet_Decal_Test` demo map.

Engine provenance is `editor/version.txt` (`version 3.5.0.1211`). MiniWind's
own version is `game.rpg.GAME_VERSION`; the launcher shows both
("Miniwind 1.0.0 · Fio 3.5.0.1211") and the log header names the engine build.

## Method

A three-way merge of `41eeb2c` and Fio 3.5 against `f445fac1`. MiniWind took
some upstream files later than `f445fac1`, so each file both sides changed was
re-merged against its closest upstream ancestor (the Fio commit whose blob
differs least from MiniWind's). Every re-merged file was then checked both
ways: MiniWind's additions present (or moved), and Fio 3.5's lines present
(a too-new base silently reverts upstream additions MiniWind never took).

## What MiniWind does not ship from Fio 3.5

The Android player (`player/`), the Deathmatch and Tidy plugins, Fio's demo
maps and showcase cutscene, `CHANGELOG.md`/`STAGE2_HANDOFF.md`, and the
Android, macOS-DMG and stand-alone build workflows. Fio tests that only
exercise those products were removed. Tests written against Fio's example
maps either build their level in code (`tests/helpers/scenes.py`), use a
MiniWind map, or load one of four Fio example maps kept as test fixtures in
`tests/fixtures/maps/` (`_SHOWCASE`, `Simple_Map_Test_Extended`,
`Office_Corridor`, `Angled_Brush_Test`); nothing in the game loads those.

## Where MiniWind's seams live now

| MiniWind seam | Fio 3.5 home |
|---|---|
| `game_session`, `player_fire_handler`, `_player_damage_filter`; primary/secondary fire; a handled or failing game fire never reaches a stock weapon | `LogicThread`, `LogicCombat._handle_shooting` (unchanged contract) |
| Game projectiles: own range, tags, `on_hit`/`on_impact`, deflection, damage kind | `LogicCombat.spawn_projectile`, `_strike_player`/`_strike_monster`, run through the new `_projectile_strike` so Fio 3.5's damage-owner and damage-direction bookkeeping applies to them |
| Damage source/cause for the game (`last_damage`) | `LogicTriggers._apply_player_damage(source=, cause=)`; Fio's damage-indicator position is kept apart from the game's *source* |
| Faction hostility, shot/steer/attack-style/damage hooks, pursuit range | `engine/hostility.py`, `MonsterAI` hooks; the AI turns actors through `engine/monster_facing.py`, the one heading writer |
| Crossfire queries | Fio 3.5's kernel (`CROSSFIRE_NUMPY_MIN`); MiniWind's tests follow its threshold |
| Mover/door position revision for the game's navigation cache | `mover_table._Group.position_revision`, bumped at every Fio 3.5 position write |
| A door's or mover's live position in game code | `engine.brush_placement.placement(brush).centre` (a brush's `pos` is its authored placement in Fio 3.5): co-op collision copies of parked doors, door-state replication, tests |
| `.fiopak` packages mounted Quake-3 style (any `*.fiopak`, later names override) | `engine/asset_archives.py`, second half; the category-archive loaders fall back to mounted packages; sounds use Fio's end-user pack loader (`engine/view_audio.py`) |
| Game pause menu, death menu, game pointer, floating windows, HUD suppression, HOME camera, camera-focus hint | `QtGameView` and its delegates (`view_pause.py`, `view_hud.py`, `view_picking.py`) |
| Pointer ownership | `QtGameView._mouse_look_captured` also yields while a game menu or pointer claim holds, so Fio 3.5's per-frame cursor re-centring never takes the pointer from a game screen |
| Terrain biomes, wheat, tundra, seasons, grass pushers | CPU generation in `engine/terrain.py` (no OpenGL); biome map, version and pushers published on `TerrainFrame`; textures, uniforms and buffers owned by `TerrainGL` |
| GC policy | one owner, `engine/gc_policy.py` (Fio's settle/release plus MiniWind's load policy and play-time freeze); `engine/gc_control.py` is its older name |
| Error reporting, freeze watchdog, data_copy, file_version, game input, game package, render camera | MiniWind-only modules, kept |
| Hidden procedural-generation action, MiniWind branding, editor UI parity work | kept (`game/integration.py`, `assets/editor.fiopak` repacked with MiniWind's icon, logo and splash) |

## Defects found and fixed during the migration

* **Every actor drew as a white square, then as Fio's stock soldier.** Fio
  3.5's eight-direction sprites list a per-angle file first; `load_texture`
  answers a missing file with the white default texture, so the first
  candidate always "loaded". A sprite recipe now resolves to the first
  candidate that exists (`engine/renderer/core/tables.py`); the
  eight-direction sprites themselves were later removed (Milestone 2).
* Torch lights were moved by editing `light.pos` in place, which the change
  journal never sees; they are assigned now.
* Every frame was counted twice (Fio's timer and MiniWind's paint), and
  SysMon's frame times recorded twice; counted once now, where painted.
* A forward-compatible core context refuses line widths above 1.0;
  `glLineWidth(2.0)` left `GL_INVALID_VALUE` queued (error checking off)
  for a later call to be blamed for. The width is clamped to 1 there.
* Missiles were loosed 48 above an actor's pos; Fio 3.5 CANARY centres the
  hit sphere on the body, so they flew over. Launch heights now come from
  the engine (`game.fio.projectile_body_lift()`).
* Co-op door-state replication sent `None` for every door (Fio 3.5's state
  rows are a `Mapping`, not a `dict`).
* A built-in game layer was treated as overriding plugin hooks it does not
  define (an error logged on every map load).
* Six loose sounds absent from `sounds.fiopak` would not have loaded.
* The renderer's `[Renderer] grass`/`low_grass` settings now decide what the
  terrain grows, not only what is drawn.

## The editor while the game is fullscreen

Fullscreen play (F12, or the launcher's Play) leaves the editor dormant. Its
docks are hidden and do no per-frame work: in fullscreen the main thread
spends ~90% of its time in the 3D paint. Panels that would rebuild for nobody
wait until shown (the scene hierarchy, the asset browser), and the map
autosave waits too: nothing can be edited, and it wrote the world as play had
changed it.

Started from the launcher's Play, the editor is built dormant
(`MainWindow(dormant=True)`, `begin_dormant_launch()`): its chrome is hidden
before the window is first shown, so the first paint is the 3D view, and the
asset browser does not decode its 139 thumbnails. Launcher Play to the game:
6.3–6.6 s → 4.4–4.7 s, 125 MB less peak memory. F12 or Escape back to the
editor restores the saved layout and fills each panel as it is shown; a launch
whose map fails to open wakes the editor. The rest of the editor (docks,
toolbars, property editor, 2D views; about 0.15 s) is still constructed:
game hooks patch its menus and the player can return to it at any time.

## Fio 3.5's architecture, adopted (Milestones 2-6)

Fio 3.5 is "tables all the way to GL": the renderer draws from published
dense tables and re-reads only what the change journal says changed. These
milestones removed the MiniWind code that still worked the pre-3.5 way.

**One heading per actor.** MiniWind kept its own `_facing` (radians) beside
Fio's `angle` (degrees), and its writers turned actors without telling the
tables, so a head's spin went stale. Now `properties['angle']` is the only
heading and `engine/monster_facing.py` the only writer (`set_heading`,
`turn_toward`, `face_direction`); every turn is journalled with the cheap
`FACING` record, which refreshes only the sprite's spin. `game/facing.py` is
a thin wrapper that sets the engine's turn rate (8 rad/s), so the combat AI's
turns ease as the game's do. A ratchet test fails on any other heading writer
or a second heading store. Fio's eight-direction monster sprites (view
selection, two table columns, directional recipes, 64 images) are removed:
MiniWind draws every actor as a top-down head. So are the Deathmatch bot
debugger, deathmatch-node linking and an unused pre-API-1.9 render snapshot.

**Change-driven game data.** Per frame, the game used to re-derive what had
not changed: the minimap's witness markers parsed every NPC's beliefs from
JSON, the floor objects re-read every container and pickup, and the held
weapons walked every actor. Witness markers are now re-derived only when a
belief, a death or a reported flag changes; floor objects are kept by a
change-journal subscriber, as Fio's tables are; held weapons use the set
the logic tick already found in range; art paths and item classes are looked
up once. Per tick, the actor index gathers column by column, jurisdiction
areas and container radii are read once per set, and co-op replicas no
longer re-resolve every row each frame.

**Instanced overhead sprites.** Held weapons, torches, floor objects, blood,
arrows and their trails were drawn a quad at a time (a glm matrix and ~15 GL
calls each). They are batched: one upload to a texture buffer, the model
matrix built in the vertex shader, one instanced draw per run sharing a
texture and depth state, in the same order (frames match the per-quad path
to 1/255 on a handful of pixels).

**Nothing decoded before it is used.** Building a 3D view decoded all 46
sounds (1.5 s on the UI thread) and every editor window decoded every asset
browser tab's thumbnails. Sounds now decode on first use (median 4 ms); the
16 large ones decode once per process on a background thread (pygame
releases the GIL). A browser tab fills when shown or first used, and an
image is kept at thumbnail size.

**Debug Tables as the oracle.** Each milestone was checked with Fio's three
independent oracles while MiniWind played (the engine's
`FIO_RENDER_ORACLE=record`, Debug Tables' published tables against tables
rebuilt from scratch, the frame repainted with every cache dropped), plus
from-scratch comparisons of the game's new caches. They found the stale head
spins (fixed by the single heading) and deaths that the living world, the
burning fallback and a journey's return never journalled (fixed).

## The view, split as Fio 3.5 split it

Fio 3.5 broke `QtGameView` up into the classes it delegates to
(`85140e25`, `618a5523`): the view keeps construction, the frame, input
events, play and renderer switching, and thin delegates; each concern is a
small class holding the view (`view.audio`, `view.hud`, `view.messages`,
`view.pause`, `view.terrain_edit`, `view.components`, `view.picking`,
`view.debug_draw`). MiniWind's own additions live in the class that owns
their concern, not in `qt_game_view.py`:

| MiniWind addition | Home |
|---|---|
| A game's play menu (raised instead of Fio's pause menu) | `view_pause.py` |
| Who owns the mouse in Play: a game's pointer claim, windows that need the cursor, a party's pad player's clicks | `view_pointer.py` (`view.pointer`) |
| The overhead actors a game draws: the player's head image, held weapons, actors' and a party's held items, batched | `view_overhead.py` (`view.overhead`); Fio's `_draw_overhead_sprite` calls it once |
| Error notices over the view | `view_messages.py` |
| A level change with no Complete box | `view_hud.py` |
| Lazy sounds, archive members decoded in the background | `view_audio.py` |

What MiniWind still adds to `qt_game_view.py` itself (2,626 lines against
Fio's 2,369) is the frame (camera interpolation between ticks, frame pacing,
the `render.pre_sprites` hook), input-handler branches and view state, which
the split keeps on the view.

## MiniWind's tests: a fifth tier

Fio's suite has four tiers (the headless core, `qt`, `gl`, `benchmark`).
MiniWind's own tests are a fifth, `miniwind`, applied by path: the game
layer's (`game/tests/`) and those of its seams in Fio (`tests/miniwind/`).
`-m "not miniwind"` runs Fio's suite as Fio ships it, the check that the
engine still meets upstream's contract; `-m miniwind` runs the game's. CI
runs it as its own job (`tests/README.md`).

## Map and save compatibility

* **Maps.** Fio 3.5 writes map version 5 (convex planes in the brush's own
  frame). MiniWind's shipped maps are version 3 and are converted on load;
  they are not rewritten on disk. All 12 angled brushes of the overworld keep
  their world bounds exactly (worst error 1.5e-11). Exported `.fiopak`
  packages still carry version 4.
* **Saves.** MiniWind's schema is kept: co-op campaign saves version 4, solo
  saves version 3, full/delta/both modes and Big World cell deltas. Five saves
  made by the pre-migration code (solo overworld, solo cave full/delta/both,
  four-player co-op) load into the migrated engine with the same state the
  pre-migration engine restores from them, and the world ticks on afterwards.

## Performance

Same host, settings, world, seeds and routes; baseline is `41eeb2c` (Fio
3.0). Software GL (llvmpipe under Xvfb), 960x540, logic and AI threads
free-running, 2D views hidden, the player standing at noon; one 20-second run
per cell at the Milestone 7 tip. GPU-side numbers are host-specific; nothing
here was measured on M5 or Adreno hardware.

| Scene | fps (3.0 → now) | paint CPU p50 | Python calls per painted frame | draw calls |
|---|---|---|---|---|
| Overworld, running | 12.5 → 13.9 | 35.5 → 28.5 ms | 7,147 → 2,275 | 110 → 53 |
| Overworld, paused | 13.9 → 15.5 | 34.0 → 25.5 ms | 7,699 → 2,126 | 110 → 53 |
| Cave, running | 29.0 → 34.9 | 8.5 → 7.0 ms | 3,004 → 1,365 | 14 → 14 |
| Cave, paused | 32.5 → 42.2 | 7.5 → 6.6 ms | 3,037 → 1,371 | 14 → 14 |

`prepare_render_state` per tick: 0.80 → 0.27 ms (overworld). The logic tick
p50 in the running overworld is 1.67 → 2.20 ms: the held-weapon overlay is now
built once per tick for the viewport (60 a second) rather than walked in every
painted frame; the UI thread is what got cheaper.

Where the per-frame Python went (paused overworld, main thread): PyOpenGL's
argument conversion for brush-instance pointers, matrices and element draws
(now native entry points, `engine/glraw.py`); the minimap's witness markers
and the floor objects (re-derived only on change); the overhead sprites (one
instanced draw per depth state, every image a layer of one texture array);
function-level imports in the game (absolute, CPython's fast path); per-frame
terrain appearance and culling (memoised, vectorised).

Earlier measurements, kept for the record: threaded four-player co-op (1
human, 3 bots), two minutes: CPU 45.4 s → 31.8 s; launcher Play to the game,
dormant editor: 6.3-6.6 s → 4.4-4.7 s, 125 MB less peak memory; building a 3D
view no longer decodes 46 sounds (1.5 s → 2 ms).

Measurement notes, so later comparisons are like for like:
`game/tools/soak.py` limits OpenBLAS to one thread as `main.py` does
(otherwise its workers spin between the dense tables' NumPy calls). Fio 3.5
repaints visible 2D views at 10 Hz in play. Fix the view size: the two
builds' test sessions size the 3D view differently. Run with
`PYOPENGL_ERROR_CHECKING=0`, as `main.py` ships.

## Known limitations

* The remaining +0.25 s per overworld load is Fio 3.5 converting MiniWind's
  128-texel terrain paint to 256 texels. Removing it needs a decision: re-save
  the world with 256-texel paint (a content change), or keep converted chunks
  per process (~26 MB more memory).
* Hardware parity on M5/Adreno is unverified; macOS behaviour is unverified.
