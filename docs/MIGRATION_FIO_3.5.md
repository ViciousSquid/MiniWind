# MiniWind → Fio 3.5 migration record (3.5.2.2411)

MiniWind's engine moved from Fio 3.0.0.1010 (taken up to upstream commit
`f445fac1`, plus later per-file backports) to **Fio 3.5.0.1111**, then to
**Fio 3.5.0.1211** (Milestone 7), to **Fio 3.5.0.1511** (Milestone 8), to
**Fio 3.5.0.1611** (Milestone 10), and now to **Fio 3.5.2.2411**, Fio's
`Canary` branch (Milestone 11, at the end of this record).
The game
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
| Fio (then) | `3.5.0.1211_Latest` | `77387caaeba284b5467a180b1ba39e147aace86d` (40 commits past `a278e956`) |
| Fio (then) | `3.5.0.1211_Latest` | `bcf4d297d9d78e5269428353db36d30ab3aca19e` (23 commits past `77387caa`: Play's mouse grab) |
| Fio (then) | `3.5.0.1511_Latest` | `a11848bffd272d7d3deb180451856849cefed9f2` (73 commits past 1211) |
| Fio (then) | `Canary_1611` | `68d052b9` (52 commits past `a11848bf`; version 3.5.0.1611) |
| Fio (now) | `Canary` | `580e7aedaf3ff0001b51bf0b3d3d04282ea7bc29` (433 commits past `68d052b9`; version 3.5.2.2411) |
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

Engine provenance is `editor/version.txt` (`Fio 3.5.0.1511`). MiniWind's own
version remains `MiniWind 0.5.0`; the launcher shows both version lines and
the log header names the engine build.

Milestone 8 brings in Fio 3.5.0.1511 (`a11848bf`): 73 commits after the
1211 baseline. The source merge keeps MiniWind's game/editor additions while
taking the upstream fixes in the same owning modules:

* The change journal supports filtered subscriptions. Physics subscribes only
  to authored state/visibility changes, tracks hidden and disabled bodies
  sparsely, defers placement settling until reactivation, and preserves this
  state across dense repacks. Sleeping bodies do not need a per-tick property
  poll; the player cannot push a hidden/disabled body.
* Generic and Prop `Show` / `ToggleVisibility` wake physics only on a
  hidden-to-visible transition. Repeated `Show` does not wake a body already at
  rest, and a carried kinematic Prop remains owned by the carry runtime.
* Placed decal entries use weak references; stopping a session releases the
  projection's placed-decal references and rows so the previous map is not
  retained by the long-lived decal table.
* SysMon's FPS/frame-time samples now come from successful Qt-presented
  frames, not the update timer or direct test/FBO calls. MiniWind's paint path
  retains its camera interpolation and animated-texture clock. Numeric readouts
  are smoothed and refreshed at the upstream cadence.
* Play mouse capture now reacts to viewport focus changes and is restored
  after an outer map-loading overlay has unwound, not only during nested Play
  entry.

The migration carries the upstream I/O, physics, decal, SysMon, editor and
view tests that apply to MiniWind, plus the test-tool adaptation for the
current per-map brush-semantics API. The overworld (`miniwind_world.json`) is
saved as version 5 since 691ef32; the other shipped maps remain version 3. Fio's refreshed version-5 demo maps and `_SHOWCASE` assets are not copied over.
The existing loader migration and MiniWind map fixtures remain authoritative.

`editor/version.txt` now records `Fio 3.5.0.1511`; MiniWind remains at
`MiniWind 0.5.0`. Runtime package versions are unchanged from the previous
Fio baseline (MiniWind continues to pin Pillow 13.0.0).

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
| Error reporting (screen notices, `logs/miniwind.log`), freeze watchdog, data_copy, file_version, game input, render camera | MiniWind-only modules, kept. Since Milestone 11 the crash logs on disk are Fio's (`editor/crash_log.py`); `error_report` hands it every unhandled exception |
| The game's navigation cache knowing the walls changed | `engine.spatial_grid.SpatialGrid.navigation_revision` (the grid left the old `engine/physics.py` in Milestone 11) |
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
* **A left click in Play could press Stop instead of attacking** (fixed in
  Fio, `bcf4d297`, merged three-way against `77387caa`). Play hid the cursor
  and turned the camera from mouse movement but never grabbed the mouse, so
  a click went to whatever widget the real pointer was over -- on macOS the
  Play button just clicked. The view now grabs the mouse while Play's look
  holds it (released for the pause menu, the console, an actor pick, a game
  pointer, another window, and on leaving Play), and macOS waits for the
  cursor's re-centre to land before detaching it. One conflict: where Play
  stops, MiniWind's restore of the chosen camera and the fix's release of
  the grab both stay. Tests: Fio's offscreen `tests/editor/test_play_mouse_grab.py`;
  Fio's native-input `tests/native/test_play_click_native.py` (real clicks
  through XTest, CGEventPost, `mouse_event` or a Wayland virtual pointer, on
  Fio's showcase, a fixture here); and MiniWind's own
  `tests/miniwind/test_play_click_native.py`, the same three checks on
  MiniWind's world with a new character, where a click is an attack. Each
  has a control that switches the grab off and must see the bug return. All
  six pass on X11 (Xvfb, openbox, xdotool); `.github/workflows/play-click-native.yml`
  runs them on Windows, macOS, X11 and Wayland and requires all six.
  MiniWind's macOS mouse-look test now lets the re-centre land first. Not
  taken: Fio's `.github/FUNDING.yml`.

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
  frame). The overworld was re-saved from the editor as version 5 (691ef32);
  the brush-model pins (stage-1/2a intended changes, the drift inventory and
  the semantics snapshot) were re-recorded for it, since its stored bounds now
  match what is drawn. The other shipped maps are version 3 and are converted
  on load; they are not rewritten on disk. All 12 angled brushes of the overworld keep
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
is level with the baseline (p50 1.4-1.9 ms over twelve runs, against 1.67).

The held-items list (who near the player holds what, their attack and block
poses, the weapons' sway) is rebuilt every 5 ticks; each holder's position and
heading are read live every frame, so a weapon never trails its actor. The
interval, measured in the running overworld (two runs each):

| Rebuilt every | fps | tick p50 | list cost per tick |
|---|---|---|---|
| 1 tick | 15.0 / 14.7 | 1.69 / 1.90 ms | 0.16-0.31 ms |
| 2 ticks | 15.9 / 14.7 | 1.44 / 1.82 ms | 0.07 ms |
| 5 ticks | 14.9 / 15.0 | 1.59 / 1.65 ms | 0.04 ms |
| 10 ticks | 14.2 / 14.3 | 1.88 / 2.32 ms | 0.035 ms |
| 20 ticks | 15.1 / 14.8 | 1.55 / 1.73 ms | 0.02 ms |
| 60 ticks | 14.9 / 14.6 | 1.65 / 2.04 ms | 0.013 ms |

Frame rate and tick time do not move beyond run-to-run noise at any
interval; the list's own cost stops falling at about 5 ticks, where a new
swing or a raised shield still shows within 83 ms (`HeldWeapons.REBUILD_TICKS`).

The HUD is drawn with QPainter over the GL view. The parts that do not
change from frame to frame are now painted once into an image and redrawn as
that one image until what they show changes (`game/ui/paint_cache.py`): the
inventory strip, the bronze frame under and over the minimap (its fins, bars
and identity text), and the minimap's disc. Each is keyed on what is visible
-- a bar's fill in whole pixels, the minimap's offset in whole pixels and its
turn in quarter degrees -- and painted from those same values, so a cached
picture is pixel-identical to a fresh one (checked over a 900-tick soak). HUD
CPU per frame: ~5.4 → ~2.2 ms.

The minimap repaints only when it changes, so it is still while the player
stands, and on the move it repaints at most 30 times a second
(`worldmap.MINIMAP_HZ`); turning always repaints at once, as the north
marker beside it is drawn live. A repaint costs ~0.85 ms. Measured walking a circle
(15 s each, two runs):

| Minimap cap | repaints/s | minimap CPU per frame | fps |
|---|---|---|---|
| none (every change) | 15.2 / 15.4 | 0.85 / 0.91 ms | 15.2 / 15.4 |
| 30 Hz | 15.8 / 14.5 | 0.81 / 0.87 ms | 15.8 / 14.5 |
| 10 Hz | 7.8 / 7.9 | 0.55 / 0.52 ms | 15.7 / 15.8 |

At llvmpipe's 15 fps a 30 Hz cap never applies, and 10 Hz saves ~0.35 ms a
frame. At 60 fps, 30 Hz saves ~0.4 ms a frame and 10 Hz ~0.7 ms, but 10 Hz
makes the map visibly step. 30 is the default.

Grass quality is a setting (the launcher; the pause menu's Options ▸
Advanced ▸ Graphics, a slider that applies while it is dragged):
`[Renderer] grass_quality` = high, medium, low or off. It grows that share of
the grass (all, half, a quarter, none), keeping the first tufts placed, so a
lower setting thins the same meadow. Wheat is a crop and always grows in
full, so Off still has its fields (the farms and the seasons depend on them).
An older file's `low_grass = True` reads as Medium.

MiniWind's grass is its meadow and the tundra heath. The meadow
(`game/meadow.py`, grown when Play starts) is occasional tufts all over the
land: ten blades each, 3.5 times the map's blade height and a green of their
own. At the map's size and ground colour a tuft is a dark speck from the
overhead camera, which sits past the grass's detail distance, where only a
blade's shaded root shows.

Grass is drawn only where the camera can see it, and as cheaply as what is
on screen allows (`engine/renderer/core/terrain_gl.py`):

* Each chunk's blades are uploaded sorted into cells about 128 units square
  (Morton order); only cells inside the view are drawn. MiniWind's chunks are
  2048 units, so drawing a chunk whole drew 70% of its blades off screen.
* Detail is chosen per cell: a cell wholly beyond the detail distance draws
  one triangle a blade, the shape the shader already gives it there. Chosen
  per chunk, every blade in the player's chunk was sent at full detail.
* A run of cells no actor reaches draws without the shader's per-actor
  parting loop (up to 20 actors, every vertex): the costliest part of a
  distant blade.
* Runs under 128 blades join their neighbour, drawn the costlier way.

At the village start (meadow everywhere; 10 s each, llvmpipe):

| Grass | before | culled | + detail per cell | + parting only where needed | fps (before → now) |
|---|---|---|---|---|---|
| High | 167 ms | 80 ms | 43 ms | 31-36 ms | 4.6 → 13.1 |
| Medium | 93 ms | 44 ms | | 16-20 ms | 6.9 → 16.7-17.5 |
| Low | 53 ms | 23 ms | | 9-11 ms | 9.8 → 20.7-21.2 |
| Off (wheat) | 12.7 ms | 1.0 ms | | 0.8 ms | 16.3 → 23.8-24.1 |

High sends 28,000 of the 78,000 blades held, in 50-75 draws (one a chunk
before, 4-16). MiniWind then shortens the grass detail distance to 150-300
units from the player (Fio's 350-700 suits a camera at head height;
`game/meadow.py`): only the grass near the player keeps its curved blades,
and High falls to 20-27 ms (fps 15-16). Over the tundra (before the
culling) High drew 336,000 heath blades at 3.8 fps and Off 40 fps.

Where the per-frame Python went (paused overworld, main thread): PyOpenGL's
argument conversion for brush-instance pointers, matrices and element draws
(now native entry points; since Milestone 11 Fio's own,
`engine/renderer/core/raw_calls.py` and `gl_state.py`); the minimap's witness markers
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


## Milestone 9 — Fio Canary sky-map integration (2026-11-15)

MiniWind's map-owned panorama workflow is aligned with Fio Canary through
`84f2dca16946dc77e6640e7972f4d8959a909cb2`:

* The Primary PlayerStart property editor uses Fio's ordered built-ins:
  `None`, `Cloudy sky`, `Space` (the shipped q80 Space image), plus a custom
  project asset selected through Browse. Custom JPG/JPEG images and other
  common formats remain supported.
* `QtGameView` publishes the Primary PlayerStart's `sky_image` to the active
  renderer every frame. The renderer contract owns the background in both
  editor and Play; the MiniWind weather hook no longer competes with it.
* Older maps with MiniWind's `miniwindsettings.void_background` value migrate
  that image to the Primary PlayerStart when the map is normalised. The damaged
  `void-panorama.webp` preset path is redirected to
  `void-panorama-q80.webp`. New maps have one sky setting only.
* Game-package asset discovery follows `sky_image`; the obsolete second
  `void_background` property is no longer exposed or loaded into the runtime.
* The independent deferred-renderer example implements the same panorama
  contract. Native Windows x64 and ARM64 no-GPU/Qt test tiers have also been
  added as report-only CI coverage.

The built-in panorama assets are byte-identical to Fio Canary. The legacy
`assets/backgrounds/void-panorama.webp` file is removed; existing maps that
refer to it are migrated to the q80 preset on load.


## Milestone 10 — Fio 3.5.0.1611 (`Canary_1611`), and a performance audit (2026-11-16)

MiniWind's engine is now Fio `Canary_1611` at `68d052b9`: the 52 commits after
the 3.5.0.1511 baseline (`a11848bf`), version 3.5.0.1611. Milestone 9 had
already taken the first of them (the map-owned sky, to `84f2dca1`); this takes
the rest. Merged three-way as before, each file against its closest upstream
ancestor, then checked both ways (five test files sat closest to a mid-way
commit and silently lost upstream additions; they were re-merged against
`a11848bf`).

What it brings:

* **Decal text.** A Decal entity paints words over its image, or alone, in
  Fio's fonts, black or white, sized and offset inside a plate, changeable by
  IO (`SetText`, `ClearText`, `SetFont`, `SetTextColor`); `engine/decal_text.py`.
  Decal images are read the right way round and may be JPEGs; three sign
  textures are added. A package carries the font its signs use.
* **Reflection probes.** A `ReflectionProbe` entity (Environment): water whose
  centre is inside its radius reflects a snapshot taken from the probe instead
  of the sky. Taken when the map loads, when Play starts and when the probe
  moves; nothing is redrawn per frame.
* **Sky.** The panorama is drawn from a cube map built once
  (`[Renderer] sky_cubemap_size`, 384), behind the opaque world rather than
  under it, so a covered pixel never shades it.
* **Water.** It reflects the map's sky panorama when the map has one; box
  water does not shade the walls its own top surface covers; caustics and foam
  are computed on the top surface only; the reflection march steps in clip
  space. Wet decals reflect glossily rather than as a mirror.
* **Sprites.** The sprite texture array is filled up front (changed for
  MiniWind; see the audit below).
* **Editor.** A map's sky is resolved read-only and repaired only at an edit,
  inside that edit's undo step (a UI refresh no longer edits the map);
  superseded property pages are destroyed; the stylesheet's SVG controls have
  PNG fallbacks where Qt has no QtSvg (`assets/ui/controls/raster/`); the
  loading overlay's backdrop is stretched at paint time; Big World's debug
  overlay is off by default.
* **Tests.** An opt-in soak tier (`tests/soak`, `--run-soak`): Play/Stop
  sessions, editor history, map round trips, physics activation, decals and
  sky switches, each checked for flat memory, resource counts and per-cycle
  time.

Where MiniWind differs from Fio in what was merged:

| Fio 3.5.0.1611 | MiniWind |
|---|---|
| Water reflects the panorama or Fio's procedural sky | MiniWind's game sky (night, cloud cover, dusk, the moon and stars) stays; a map with a panorama reflects that instead, and the moon and stars are not added to it (`water.frag`: `skyColor`, `skyLights`) |
| A water brush's "High quality" checkbox places a reflection probe | MiniWind has no per-brush quality (one graphics setting): the checkbox and its handler are not taken. A probe is placed by hand; `make_water_probe` / `water_probe_of` are present, unused |
| A monster's fight frames are interned for each of eight facings | One facing: shooting and dead only. They are filed under the monster that shows them (`EntityTable.fight_frame_ids`) |
| The sky is stored on a PlayerStart | Also read from an older MiniWind map's Game Settings (`void_background`) without editing it; moved to the Primary PlayerStart at the first edit. The damaged `void-panorama.webp` still resolves to the q80 file |
| The panorama is on texture unit 15 | So is MiniWind's terrain biome map, in the terrain program only, which binds it at every terrain draw |
| Windows Qt tiers run the whole suite in six shards | `tools/run_qt_suite_shard.py` and its test are in; MiniWind's `tests-windows.yml` is unchanged |

Not taken: the Android player's decal changes, the Deathmatch plugin's test,
Fio's refreshed demo maps (`_SHOWCASE` and the `Terrain_Test` maps, version 5),
the wiki pages. Tests that read those maps build the level in code, use the
fixture copy, or keep MiniWind's own expectations (the brush-model drift
counts). Pillow stays at 13.0.0.

### Performance audit

Same host, software GL (llvmpipe under Xvfb), `main` (`a2c389d`) against this
branch. Three tools, all in the tree:

* `tools/perf_gate.py`: every probe in a fresh process pinned to one core,
  base and head interleaved, five rounds, a one-sided Mann-Whitney test on the
  round medians. Its probes read Fio's example maps from `maps/`, where
  MiniWind does not keep them, so five of the eight failed here and the
  gameplay probe hung; they now find the fixture copies, skip a map a tree
  does not have, and measure `miniwind_world` and `cave01` too
  (`tools/perf_probes.py`; `tools/bench_water.py` likewise).
* `game/tools/audit_launch.py`: `main.py` as shipped, the launcher answered,
  a new character, 30 s walked through Millbrook at 960x540; three runs a
  tree, alternating.
* `tools/bench_water.py` (new in 1611): the water pass alone, fixed cameras.

**The upgrade as merged had one regression, in MiniWind only.** Fio now
imports, when a map's sprite recipes change, every image the sprite pass may
draw for every row of the map and every monster's fight frames, so that no
sprite is imported -- and the array regrown, re-uploading every layer -- as it
first comes into view. Fio's maps are small. MiniWind's world has 890 sprite
rows and about 500 monster recipes, and the opening draws 19 images:

| Each tree's first run (cold caches) | `main` | 1611 as merged |
|---|---|---|
| Play started | 5.9 s | 9.3 s |
| Sprite array | 19 layers of 128 x 128, 2.7 MB | 252 layers of 512 x 512, 341 MB |
| Resident memory after 30 s | 1,476 MB | 2,013 MB |

Two things made it so large. The warm-up took the whole map's rows, and every
`msprite_` recipe in the table (485 of 500). And every layer is as large as
the largest image: among MiniWind's 128 x 128 heads, the one 341 x 512 image
was Fio's stock corpse (`sprites/monsters/human/dead.png`), the dead frame of
every actor with no death sprite of its own. So:

* the warm-up takes the rows within the camera's view distance (a map the
  view distance covers is still warmed whole, as Fio's are, and so is any map
  while it is edited); what is further off is imported when first drawn, as
  before, into the room `sprite_layers.reserve_all` leaves;
* fight frames are found per monster, and MiniWind does not warm them
  (`PassesMixin.WARM_FIGHT_FRAMES`): an actor's attack frame is its own head.

With that the array is 75 layers of 128 x 128, 21 MB, and over three
alternating runs each (medians; warm caches, so lower than the table above):

| | `main` | 1611 |
|---|---|---|
| Play started | 5.18 s | 5.31 s |
| First gameplay frame | 6.02 s | 6.09 s |
| Frame interval p50 / p95 / p99 | 88.8 / 104.3 / 113.1 ms | 88.1 / 100.2 / 106.1 ms |
| Paint p50 | 77.9 ms | 77.4 ms |
| Logic tick p50 / p99 | 1.6 / 8.1 ms | 1.6 / 7.6 ms |
| Hitches in 30 s (a frame over the median by 16.7 ms) | 15 | 5 |
| Their excess | 350 ms | 126 ms |
| Resident memory | 1,295 MB | 1,298 MB |

Launch and frame time are level. Fewer frames run long; the part of that
which was measured is texture loading during play (44 ms to 6 ms: what is
near is imported before the first frame), the rest is not attributed.

**The gate:** 102 metrics, 98 unchanged, none slower in MiniWind's own maps.
`miniwind_world`: frame 32.2 to 32.3 ms, logic 0.86 ms both; `cave01`: 8.9 to
8.8 ms. Fio's Big World test map paints 16% faster (its debug overlay is off).
One metric is flagged, +3.0% (5.14 to 5.29 ms) of submission CPU for a still
frame of Fio's showcase: the per-brush work of the new covered-wall skip on
box water. It buys rasteriser time the metric does not count, and MiniWind's
water is all top-surface-only, which never takes that path.

**Water** (960x540, the pass with its rasteriser time, one llvmpipe thread):

| Scene | `main` | 1611 |
|---|---|---|
| Open water, no panorama | 72.0 ms | 70.9 ms |
| Open water, panorama | 71.8 ms (frame 85.7) | 66.6 ms (frame 77.0) |
| Showcase pool, no panorama | 81.5 ms | 80.0 ms |
| Showcase pool, panorama | 81.1 ms (frame 115.3) | 72.8 ms (frame 101.8) |

**Memory over time.** The new soak tier passes on MiniWind (its Play/Stop
test plays the fixture showcase, given a sky). Its map round-trip test at
first read the open world as a native leak: loading it over and over, resident
memory climbs about 15 MB a load, then levels off some 200 MB up after about
fifteen loads (forty were run), with the Python object count flat throughout
-- the allocator settling, and the same on `main`. The world is round-tripped
once for its fixed point and left out of that test's memory loop.

**Where the time goes now** (the 30 s walk; software GL, so the rasteriser
dominates and these are not a GPU's proportions): of the main thread's
samples, 65% are in the renderer's passes -- most in the grass draw and in the
water's frame copy, which is where llvmpipe finishes the frame so far -- 13%
in Qt (presenting the frame, events), 2% painting the HUD. Before Play:
texture loads 1.1 s (343 textures), `toggle_play_mode` 1.0 s, the
level-texture preload 0.5 s, `on_play_start` 0.5 s, the first music track
0.2-0.5 s. The logic tick is 1.6 ms at the median; sampled, about a seventh of
its Python is `WorldIndex.rebuild`, which snapshots every actor each tick.

**Found, not changed:**

* **One oversized sprite sets the size of every layer.** A dead actor with no
  `custom_dead` is drawn with Fio's 341 x 512 stock frame. When the sprite
  pass first draws one, the array is rebuilt at 512 x 512: sixteen times the
  memory of every head layer, and a re-upload of all of them, mid-play
  (reproduced with three head actors: 128 x 128 while they live, 512 x 512
  once one is dead; nothing died in the 30 s runs above). This was so before the upgrade; the bounded warm-up
  only keeps it from happening at Play's start. A head-sized death frame for
  MiniWind's actors removes it (`heads/dead.png`, 128 x 128, is in the tree
  and drawn by nothing); that is art and a game decision, not an engine one.
* **A map's first play paints its world-map picture during play**: 12-13
  hitches, 250-370 ms in all, in the first 30 s, once per map (`cache/`).
* **MiniWind's game sky costs the water about 10% a pixel** over Fio's
  procedural sky (70.9 ms against 64.5 ms on the open-water scene). It is the
  look; `[Renderer] water_quality = low` is the existing way out.
* `WorldIndex.rebuild` every tick, above: correct and already tuned, but a
  cost that grows with the cast rather than with what moved.
* Every GL number here is llvmpipe's. Hardware parity (M5, Adreno, a desktop
  GPU) is still unverified, as before.


## Milestone 11 — Fio 3.5.2.2411 (`Canary`) (2026-11-24)

MiniWind's engine is now Fio `Canary` at `580e7aed`: the 433 commits after
`68d052b9` (3.5.0.1611), version 3.5.2.2411. One rule governed the merge:
**Fio is definitive unless the code is RPG-specific.** Where MiniWind and Fio
had each solved the same engine problem, Fio's solution was taken and
MiniWind's removed; MiniWind keeps only what its game needs, re-applied onto
Fio's code with the least glue.

Method: a three-way merge (`git merge-tree --merge-base=68d052b9`) of `main`
and `Canary`, 55 files resolved by hand, then every line MiniWind had added
since the base checked against the merged tree for presence *and* for still
sitting in the same function (an auto-merged hunk of `MonsterAI.__init__` had
landed inside Fio's new knockback method; nothing else had moved).

What it brings (Fio's own words are in its commit log; the large items):

* **Physics is a package and a contract**: `engine/physics/` (Soma, Fio's
  built-in physics, behind a registry and `PHYSICS_CONTRACT_VERSION`), the
  world's walls in engine core (`engine/spatial_grid.py`), plugin API 2.0.
  Model collision meshes the player walks on, steps up and stands on.
* **Two renderers**: Classic (the default, `[Renderer] renderer = Classic`)
  and HD_High (`engine/renderer/hd_high/`, physically based, Forward+), with
  material companion maps beside every surface texture (`*.mat.json`,
  `*_n.webp`, `*_m.webp`; `tools/make_material_maps.py`). Each display mode in
  its own folder; GL state through `core/gl_state.py`, pointer calls through
  `core/raw_calls.py`; prepared model plans.
* **Editor**: brush and entity groups (UUIDs I/O can target), a Move / Rotate /
  Scale gizmo, light volumes, model Rotate animation with a preview, Save As
  Minified, toasts as Debug Console cards, `condump`, a floating Terrain
  Editor, Fio Mono, kiosk mode on a native window (`[Kiosk] native_surface`,
  off), the editor dormant and painting on publish in kiosk mode, a crash log
  on disk (`fio_crash.log`, `fio_fault.log`).
* **World**: light cookies, lights along path nodes, emissive decals, brushes
  and water, water flow direction, lens water, explosive barrels, the Shake
  entity, GPU particle emitters on Effects, terrain paint and stamps kept
  beside the map in `<map>.paint`.
* **Hardening and speed**: untrusted map/package/model data refused, faults
  contained and logged once, the logic loop survives anything a frame raises,
  still frames examine no rows, the property panel and hierarchy reselect
  rather than rebuild, background autosave, export on a worker thread.
* **Tests**: each test gets its own `settings.ini`
  (`tests/helpers/settings_isolation.py`); golden frames of Classic
  (`tools/hd_golden.py`).

MiniWind's parallel implementations, removed in favour of Fio's:

| MiniWind had | Now Fio's |
|---|---|
| `<map>.stamp` (format 2) holding a map's terrain paint, `paint_file: "<name>.stamp"` | `<map>.paint` (`engine/terrain_stamp.py`, `paint_file: true`). `maps/miniwind_world.stamp` was converted once to `maps/miniwind_world.paint` and checked to join to the identical `terrain_data`. `paint_path` / `load_stamp_file` also look inside mounted data packages, where MiniWind's maps may ship. |
| `engine/glraw.py` (native GL entry points) | `engine/renderer/core/raw_calls.py` and `gl_state.py` (`has_base_instance` moved to `raw_calls`) |
| `logs/crash.log` (faulthandler in `engine/error_report.py`) | `editor/crash_log.py`; `error_report` keeps the on-screen notices and `logs/miniwind.log`, and passes every unhandled exception to Fio's crash log |
| A second `MainWindow.editor_dormant` that overrode Fio's | Fio's property, which now also counts MiniWind's dormant game launch; panels catch up through Fio's `_editor_ui_stale` |
| The scene hierarchy's dormant deferral (`_refresh_deferred`) | Fio's out-of-sight deferral (`_stale`) |
| Visible-views-only 2D repaints in Play | Fio's `update_views()`, which Fio now skips in kiosk mode |
| Play repainted at the display's refresh (`frameSwapped`, and every update-loop tick) for camera interpolation between ticks | Fio's paint on publish: one paint per published frame (60 Hz, also while paused). MiniWind's camera interpolation (`engine/render_camera.py`) still dates each painted pose |
| `engine/game_package.py` (extract a package to play it; unused) | `editor/package_session.py` (read in place) |
| Big World editor streaming's `data_copy` | Fio's `copy_record` |
| Sculpt-list cache, one-pass legacy sculpt load | Fio's compressed `sculpt_tiles` and dense-grid dab patching |
| Brush-run pointer loop, `UniformCache` overrides, framebuffer-depth cache, `render_cull.shadow_casters_in_reach` | Fio's per-run vertex arrays, `UniformCache`, `_read_framebuffer_has_depth`, `_casters_in_reach` (with MiniWind's rotated-corner bound and geometry epoch folded in) |

Kept, being the game's: single-facing monster sprites and fight frames
(`WARM_FIGHT_FRAMES = False`), the sprite warm-up bounded to the view
distance, head spin and tint, actor reflections in water, the game sky in the
water (night, clouds, the moon and stars), one global water quality, the
`pre_sprites` hook (bracketed by `gl_state.end_frame()` / `begin_frame()`, as
the game draws with plain GL), terrain-only light shadows (moved to free
light-buffer slots, `indices.y` and `indices.w`, as Fio's cookies took
`params.w`/`indices.z`), biomes, wheat, tundra, seasons and grass pushers
(a stamp's grass thinning regrows wheat and tundra rather than rolling per
blade), overhead sprites, co-op trigger filtering, gamepad movement, the
level changer's prompt and doorway behaviour, the Play menu and game pointer,
the dormant launch, the Big World `with_level` save, the navigation revision.

Where MiniWind differs from Fio in what was merged:

| Fio 3.5.2.2411 | MiniWind |
|---|---|
| The Android player, Deathmatch and Tidy plugins, demo maps, Android/DMG/stand-alone build workflows | Not shipped, as before. `Reel_To_Reel_Test.json` is a test fixture (`tests/fixtures/maps/`); its tests and `tools/make_reel_to_reel_test_map.py` point there. Tests that listed the absent plugins list Big World only. |
| Fio's stock `cobblestone`, `foxhex`, `mtlgrate`, `scifipnl01` companion maps | Not taken: MiniWind does not ship those textures. Tests that used `cobblestone.jpg` use `Stone_09-512x512.png`. |
| Companion maps for Fio's stock textures | Also baked for MiniWind's own 75 surface textures (`tools/make_material_maps.py`; 38 MB), so HD_High finds them and Fio's completeness check holds |
| HD_High's terrain samples 16 textures | MiniWind's biome map would be the 17th: HD_High's terrain program drops it (no biome tint in HD_High). HD_High also has no game sky in water, actor reflections, `pre_sprites`, head spin/tint, global water/grass settings or terrain-only shadows; Classic remains the default |
| The view reads `renderer.grass_enabled` / `grass_quality` | Outside Fio's renderer contract: the view now owns them (`QtGameView.grass_settings`, from `[Renderer] grass` / `grass_quality`; the pause menu sets them with `set_grass_settings`). The Play warm-up no longer counts the renderer's textures. |
| A level change keeps only start-up sounds (`ViewAudio.begin_level`) | Also keeps every `sounds.fiopak` sound: MiniWind decodes them on first use or in the background, not at start-up |
| Maps are written indented unless minified | The same; `miniwind_world.json` is minified, and stays so |
| `[Renderer] shadow_map_size = 1024`, `sky_cubemap_size = 512` | Taken |
| A failing `editor/main_window.py` load leaves the open map | The same, and a package's start map is validated before `file_path` is cleared, as before |

Game layer changes: `game/ui/pause_actions.py` (grass through the view),
`game/tools/rebake_roads.py` (the `.paint` API), `game/tools/expand_world.py`
and `populate_world.py` (read sculpting as `sculpt_tiles` or
`sculpt_offsets`: `sculpt_cells`), `game/tools/audit_launch.py` (buckets), and
the tests that followed.

Engine provenance is `editor/version.txt` (`Fio 3.5.2.2411`); MiniWind stays
at `MiniWind 0.5.0`. Pillow stays at 13.0.0.

### Verification

* No-GPU suite (`-m "not gl and not benchmark"`, Qt offscreen, 8 workers):
  14,447 passed, 78 skipped. Every failure found was fixed; the editor
  free-look and kiosk tests that timed out under eight workers pass run alone.
* GL tier (`-m gl`, Mesa llvmpipe under Xvfb): 604 passed, 10 skipped.
* Classic's golden frames and source lock re-recorded for MiniWind
  (`tools/hd_golden.py --update`, `--lock-sources`) on the two fixture maps it
  keeps; Fio's frames of maps MiniWind does not ship are removed.
* The game as shipped (`game/tools/audit_launch.py`: `main.py`, the launcher
  answered, a new character, 30 s walked through Millbrook at 960x540,
  software GL), two alternating runs a tree on one host:

| | `main` (3.5.0.1611) | 3.5.2.2411 |
|---|---|---|
| Play started | 11.4 s / 7.5 s | 9.9 s / 7.4 s |
| Frame interval p50 | 114.0 / 109.8 ms | 110.7 / 112.6 ms |
| Frame interval p95 | 144.2 / 131.8 ms | 150.9 / 146.4 ms |
| Logic tick p50 | 2.2 / 2.1 ms | 2.1 / 2.1 ms |
| Resident memory | 1,376 / 1,213 MB | 1,383 / 1,225 MB |

  Level within run-to-run noise; no error reached the screen or the log.
  Hardware GPUs (and HD_High on them) are, as before, unmeasured.
