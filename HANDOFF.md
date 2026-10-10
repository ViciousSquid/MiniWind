# MiniWind on Fio 3.0: handoff

Read this first if you are picking this work up in a new session. It says what
has been done, how the tree is organised, how to run and check things, and what
is left. The decision record for the current engine is
[`docs/MIGRATION_FIO_3.0.md`](docs/MIGRATION_FIO_3.0.md); the earlier 2.4 → 2.5
move is in [`docs/MIGRATION_FIO_2.5.md`](docs/MIGRATION_FIO_2.5.md).

- **Working branch:** `claude/confident-darwin-5e4jxd` (MiniWind). Never
  force-push (the remote refuses history rewrites); use merges.
- **Fio upstream:** `ViciousSquid/fio`, branch `3.0.0.1010_Latest`
  (`9d57cab6` is what MiniWind vendors). Fio is the authoritative version:
  take its files verbatim and re-apply MiniWind's seams (see §3).

---

## 1. The goal

MiniWind runs on Fio 3.0 (before: Fio 2.5.10, and before that a 2.4.1
fork). Keep MiniWind's gameplay, content, editor tooling and look. Adopt Fio's
architecture properly:

- dense `EntityTable`/`RenderTable`, with no per-NPC Python GL draws;
- game policy lives in `game/`;
- Fio never imports `game`;
- Big World is authoritative and mandatory;
- don't weaken Fio's tests.

The user's standing instruction is: *keep all existing functionality, with
Fio as the authoritative version*. For Fio 3 they chose MiniWind's pause menu,
Fio's cutscenes, Fio's music volume setting and Fio's Quake 2 movement
(docs/MIGRATION_FIO_3.0.md).

### Rules the user has set (still in force)

- **MiniWind's own copy of Fio may be changed.** That's `engine/`, `editor/`
  and `plugins/` in this repo. Keep changes small and generic. MiniWind policy
  goes in `game/`.
- **The Fio repo is changed only when the user explicitly asks** (as they did
  for API 1.5.0, world pause and pick, and the overhead backport).
- **No red branding.** No First Person/Overhead dropdown in MiniWind; play is
  always overhead, and the editor keeps its own camera.
- **One map.** Only `maps/village_walled_source.json` ships, and it loads by
  default. Plain Fio maps are refused unless *Settings > Editor > Allow Fio
  maps* is ticked.
- **No Tidy plugin. Big World is mandatory**
  (`[Plugins] mandatory = bigworld` in `settings.ini`).
- **No pull requests** unless the user asks.

---

## 2. What has been done (MiniWind branch, oldest first)

| Commit | What |
|---|---|
| `2b9a586`, `842e9a1` | Phase 1 archaeology and the migration matrix (`docs/MIGRATION_FIO_2.5.md`) |
| `0bf7a07` | Vendored Fio 2.5.10 (`f612655e`) verbatim |
| `9bdb9d2`, `0d53062` | Plugin API 1.5.0 (property sections, KV suggestions, entity inspector) vendored and consumed by `game/host.py` |
| `fae7175` | MiniWind policy moved out of `engine/`/`editor/` into `game/` (gore, facing, combat loadout, pause menu, launcher, console `inspect`) |
| `fb3fe1d` | Vendored Fio `c1b06a1`: world pause (`LogicThread.set_world_paused`) and Play Mode actor pick (`engine/actor_pick.py`) |
| `c29276e` | Boot: `main.py` loads `[Startup] game_module`, mandatory Big World, launcher and kiosk, `game/` uses world pause |
| `24e2f3e` | Village map pins `terrain_data.mesh_scale = 1.0` (this was the "buried village" bug) |
| `26f086d` | Play starts in Overhead (`game/host.py PLAY_CAMERA`); the editor keeps its camera |
| `ce332f1` | Player drawn as a head (`engine/overhead_sprite.py`, `QtGameView._draw_overhead_sprite`); window title; dropdown hidden |
| `7e9a3af` | LogicThread game hooks: fire handler (primary and secondary), damage filter, pointer aim, projectile `on_hit`/`on_impact`/`max_dist` (`tests/engine/test_game_hooks.py`) |
| `5a4f3fe` | Allow Fio maps setting and gate; Fio maps and Tidy removed; spellbook is a **Prop** (Tidy's book model, cover textures in `assets/textures/spellbook/`); game-side render writes `touch()` the change journal; `tests/conftest.py` skips Fio tests needing content MiniWind doesn't ship |
| `5ed6586` | **World expansion**, see §4 |
| `987d637` | Lakes and ponds are one water brush over a sculpted bowl; ground raised under the old slab-borne decals |
| `c40280e` | Restored `_suppress_default_hud` in `QtGameView._draw_hud` (doubled "Press E" prompt, Fio's big health number) |
| `c2b4dc9` | **Overhead performance**, see §5 |
| `fc20eaf` | **Pause menu, music, loading bar, fonts**, see §5a |
| `9d3f948` | **Fio 3.0.0.1010** vendored verbatim (`docs/MIGRATION_FIO_3.0.md`) |
| `bb60665` | MiniWind's engine seams re-applied onto Fio 3's runtimes |
| `e4fee54` | Editor, boot and Big World `terrain_stream` seams on Fio 3 |
| `9bb0f07` | Game layer on Fio 3: `game/fio.py`, Fio cutscenes, Fio music volume |
| (then) | View follows the game's camera in play, tests, CI, docs |

### Fio repo (upstream)

- **`Canary` `fb18c9a`:** "Big World: fit residency and tiers to the overhead
  camera". This is the clean Fio-side version of §5. It's gated on *Big World
  running AND the camera overhead*; Big World off, or first person, is
  unchanged. It has no map setting.
- **`Canary` `28b688b`, `2d8b603`, `08f97c1`:** plugin API 1.5.0, world pause
  and Play Mode actor pick, and their API.md docs. These are the same commits
  MiniWind vendors. Fio's full suite passes on `08f97c1`: 4,067 passed, 5
  skipped. [`docs/handoff/fio-patches/`](docs/handoff/fio-patches/) keeps the
  original patches for reference only.

---

## 3. Layout you need to know

- `game/`: all MiniWind policy.
  - `host.py`: the plugin, I/O, property sections, play start/stop, input,
    overlay.
  - `runtime.py`: `MiniwindSession`, the per-tick game simulation.
  - `entities.py`, `integration.py`: editor patches (title, map gate, menu).
  - `console.py`.
  - `ui/`: HUD, screens, pause menu, launcher.
  - `rpg/`: quests, items, magic, gore and more.
  - `sim/`: director, crime, perception.
  - `tools/`: content generators, including `expand_world.py`.
  - `data/`: items, bestiary, settlement JSON.
  - `tests/`: game tests.
  - `fio.py`: the only place game code learns where Fio 3 keeps things
    (`logic.player_runtime.player`, `logic.camera`, `logic.session_runtime`,
    ...). Use it; the boundary test fails on a 2.5-style `logic.player`.
- `engine/`, `editor/`, `plugins/`, `player/`, `tests/`: MiniWind's copy of
  Fio 3.0.0.1010. Every change from the vendored Fio is listed, with its
  file, in docs/MIGRATION_FIO_3.0.md ("Where each MiniWind seam lives now").
  In short:
  - **Game hooks on LogicThread:** `game_session`, `player_fire_handler`,
    `_player_damage_filter`, read by `LogicCombat`, `LogicTriggers`; aim and
    secondary fire in `threaded_game_state`/`LogicPlayer`.
  - **Projectiles:** `LogicCombat.spawn_projectile` (own range, `on_hit`,
    `on_impact`) over `ProjectileStore`'s `max_dist`/`tag` columns.
  - **Camera focus:** `LogicCamera.set_camera_focus`.
  - **MonsterAI:** `set_hostility` (`engine/hostility.py`), attack-style hook.
  - **QtGameView:** the game's `play_menu` replaces Fio's pause menu,
    `game_pointer`, floating windows in play, the overhead head sprite and
    held weapon, `_suppress_default_hud`, camera mode follows the logic
    thread in play.
  - **Water/glass frustum cull** (`engine/renderer/core/visibility.py`).
  - **Big World:** `terrain_stream`. The overhead-camera fit is Fio's own.
- Guard test: `tests/integration/test_backport_boundaries.py` (Fio's) plus
  `tests/integration/test_miniwind_boundaries.py`.
  - No `import game` outside `game/`. Indented `from game import` in tests
    also trips it; use `importlib` or relative imports.
  - No RPG vocabulary in generic modules.
  - `ui.py` must keep `camera_mode_combobox.setCurrentText("First Person")`.
  - and so on.

---

## 4. The world (`maps/village_walled_source.json`)

Generated by `python -m game.tools.expand_world`. It refuses to run twice. To
regenerate, start from the pre-expansion map:
`git show 5a4f3fe:maps/village_walled_source.json > /tmp/pre.json`, then
`python -m game.tools.expand_world /tmp/pre.json -o maps/village_walled_source.json`.

What the tool does:
- **Terrain:** 40×40 chunks of 2048 units (about 82,000 square); Millbrook
  untouched at the origin.
- **Spread:** outlying sites move rigidly with their ground, re-sculpted at the
  new place, to `R0 + 3*(r - R0)`.
- **Mountains:** a heightmap overlay laid over the terrain bounds (edge wall,
  Emberpeaks to the NE, SW uplands), kept clear of every site.
  - **Never enable Big World `terrain_fill` on this map.** It re-bounds the
    terrain and shifts the overlay. Use `terrain_stream`.
- **Emberpeak Shrine:** at (25600, ~790, −26400), up a cairn-lit pass beyond
  Frostcap Tor. The **Ember Tome** spellbook (`quest_item: ember_tome`) sits on
  the old Ashen Circle altar.
  - Thalen's quest `ember_tome` (`game/rpg/quests_content.py`) is a fetch.
  - The arrow points at the book. Reading it teaches firebolt and gives the
    item, which completes the quest.
- **New land:** 10 landmarks (tarns, ruined towers, stone rings, camps, a
  brigand hollow), wildlife spawners and about 900 trees.
- **Water:** each body is ONE water brush over a sculpted bowl, with a
  128-unit dry-bank margin and 12 units of freeboard. Water planes show
  through the terrain otherwise.
- **Floor slabs:** the 2.4 invisible floor slabs were removed (2.5 terrain is
  solid). The ground is raised under thin road and floor decals.
- **Big World settings in the map:** `fit_overhead_camera` and
  `terrain_stream` on, `show_cell_debug` off.

Tests: `game/tests/test_ember_tome.py` (quest, arrow, map invariants, water
rule).

---

## 5. Overhead performance (now Fio 3's own)

- **Footprint:** `logic.camera.overhead_ground_footprint()` gives the half
  extents of the ground the overhead camera shows.
- **Residency:** with an overhead camera Big World keeps a circle just past
  the screen corners resident, refreshed every 256 units of movement. NEAR is
  the screen rectangle (`session.tiers.near_rect`), re-tiered every 128 units.
  Fio 3 does this automatically for an overhead camera; the map's
  `fit_overhead_camera` key is ignored. MiniWind reads the fit through
  `game.fio.sim_tiers_fit_view(logic)`.
- **MonsterAI (Fio 3):** with a fitted view, parked (DORMANT) monsters are left
  out of the pass and off-screen monsters run once per 0.2 s carrying the
  time they owe.
- **MiniWind-only:**
  - `MiniwindSession`: off-screen NPCs decide and move one tick in 4;
    proximity checks run at 10 Hz.
  - `settings.ini` uses `water_quality = cheap`.
  - Big World `terrain_stream` streams the authored terrain inside its own
    bounds. **Never enable `terrain_fill` on the village map.**
- **Measured headless** (Xvfb and Mesa): the dev harness shows about 11 FPS in
  the village on Fio 3 where 2.5.10 showed 5 on the same machine;
  **re-measure on real hardware.**

---

## 5a. Pause menu, music, loading bar, fonts

- **Pause menu** (`game/ui/pause_menu.py`): Escape in play raises it, in the
  editor's play mode and in kiosk play alike (the old "Quit game and return to
  editor?" box is gone wherever the game is installed). One horizontal row:
  RESUME, GAME (a dropdown: NEW GAME / LOAD GAME / SAVE GAME; its arrow points
  down folded, up open), MUSIC: ON/OFF, EDITOR, QUIT. Mouse (the arrow cursor
  shows while it is up) and keyboard both work.
  - Fio side, generic: `QtGameView.play_menu` slot, `open_play_menu()`,
    `play_menu_closed()`; Fio 3's own Esc path (`open_pause_menu`) raises the
    game's menu instead of Fio's when one is installed; the view routes input
    to an open menu and paints it last; `MainWindow` hands Escape to a game
    modal that closes on it (`game_session.escape_closes_modal()`) first.
    `game/integration.py _patch_play_menu` installs MiniWind's menu.
  - Actions (`game/ui/pause_actions.py`): slots are `saves/slotN.fiosave`
    (console `save`/`load`) plus a `"miniwind"` block holding MiniWind's
    key/value store (character, quests, clock). Load stops play, puts the
    store back, then the console load reloads the map and overlays the world.
    New Game stops play, wipes progress, reloads the map, starts play.
- **Music** (`game/music.py`): every `.mp3` in `assets/music` (moved from
  `assets/sounds/music`), shuffled, no repeats back to back, through
  `pygame.mixer.music`, during play only. `[GAME] music` in settings.ini
  remembers the pause-menu switch; the volume is Fio 3's
  `[Audio] music_volume` (0-100, default 50), the same one Settings > Play
  Modes > Audio sets, and the player follows it live.
- **Loading bar** (`editor/loading_overlay.py`): the splash's progress bar over
  the window during map loads and play start, stepped at each stage
  (`_loading_step` in `main_window.py`); `main.py` opens the default map and
  kiosk play under one bar. Fio 3's separate-process loading throbber stands
  down while it is up.
- **Cutscenes** are Fio's (Tools > Cutscenes, `cutscenes/*.json`, played by a
  LogicCamera). While one plays Fio holds input and the plugin tick, and
  MiniWind hides its HUD and loadout window (`game.fio.cutscene_active`).
- **Fonts** (`game/ui/fonts.py`, files in `assets/fonts`): Enchanted Land for
  the pause menu's banner/options and the loading title; MedievalSharp (OFL,
  licence beside it) for conversations, the menu's small print and the bar.
  Arial/Georgia only if a file is missing. `theme.font()` turns any sans face
  the game UI asks for into MedievalSharp when it is installed.
- **Mouse in menus** (`game/ui/hits.py`): menus record click targets as they
  paint; Fio's generic `QtGameView.game_pointer` shows the arrow and hands
  the mouse to the game while it wants it; clicks run on the game tick.
  Character creation (Back/Next/Begin, head arrows, handedness, list rows),
  trading (rows, Buy/Sell, Leave) and conversation replies are clickable.
  Other screens (inventory, journal, spells, level-up, containers) are still
  keyboard-only: add targets with `screens.button` / `_row_target`.

## 6. What still needs doing

### Found during the Fio 3 migration (pre-existing, left as they were)

- `.github/workflows/build.yml` never packaged the `game` package or
  `quests/` (they are loaded by name at runtime), so a Nuitka build would
  start without the game. Add `--include-package=game` and
  `--include-data-dir=quests=quests`.
- `MiniwindSession._editor_config()` looks for `logic.editor_config`, which no
  Fio version has: `[GAME] visualise_dice_rolls` / `show_dialogue_heads` are
  never read in play (their defaults apply).
- `logic.blood_stain_sprites` is set by the session and read by nothing.
- Upstream Fio 3's suite segfaults if every tier runs in one process here
  (Qt teardown in its `main_window` fixture). Run by tier (§7).

### Also worth doing

- Re-measure performance on real hardware (§5).
- Fio 3 binds number keys 1–4 to its own weapon slots; MiniWind's slots are
  1–9 through the game. With no Fio weapon in hand Fio's are no-ops, but a
  Fio weapon pickup in a MiniWind map would compete for those keys.

### Older open items (from the 2.5 handoff, not re-checked)

- Actor visuals: NPC heads rotated by heading; hit-flash tint, dead heads,
  gib visuals (through EntityTable columns and `touch()`, never per-NPC
  Python draws).
- View/editor: sound falloff, stuck arrows and projectile visuals (the
  projectile store's `on_impact` reports where one landed), marker pins.

### Housekeeping

- Keep `docs/MIGRATION_FIO_3.0.md` current when MiniWind's copy of Fio
  changes.

---

## 7. Running and checking

Environment setup in a fresh cloud container. Fio 3 needs CPython 3.14
(GIL build); the container's system Python may be older, so use `uv`:

```bash
apt-get install -y libopengl0 libegl1 libglu1-mesa libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 \
  libxkbcommon-x11-0 libxcb-shape0 libxcb-randr0 libxcb-xfixes0 libxcb-cursor0 \
  libgl1-mesa-dri glslang-tools xvfb
uv python install 3.14 && uv venv -p 3.14 ~/venv314
VIRTUAL_ENV=~/venv314 uv pip install -r requirements.txt pytest pyflakes
```

Run the suite by tier, as Fio 3's CI does (`.github/workflows/tests.yml`). The
editor rewrites `settings.ini`, so back it up and restore it around any run:

```bash
cp settings.ini /tmp/settings.keep
PY=~/venv314/bin/python
$PY -m pytest -p no:cacheprovider -m "not qt and not gl and not benchmark" -q
QT_QPA_PLATFORM=offscreen $PY -m pytest -p no:cacheprovider -m "qt and not gl and not benchmark" -q
xvfb-run -a -s "-screen 0 1280x1024x24" $PY -m pytest -p no:cacheprovider -m gl -q
cp /tmp/settings.keep settings.ini
```

Results at the Fio 3 migration (docs/MIGRATION_FIO_3.0.md): core 3,270
passed; Qt 2,404 passed and 1 failed (`test_the_greyed_strip_is_used_by_the_
toggles_and_nothing_else`, which fails identically on pristine Fio 3); GL 195
passed. A tier takes about 1, 19 and 4 minutes here.

Game test modules must not set `QT_QPA_PLATFORM=offscreen` unconditionally:
under Xvfb that takes the GL context from every later test and the whole GL
tier silently skips.

Gotchas:
- Fio's root `conftest.pytest_ignore_collect` returns False, which disables
  `--ignore`. Run selected paths instead.
- The map file uses CRLF line endings. Edit it with Python (`json` plus
  `game.tools.expand_world.dump`), not `sed`.

Real-GL checks with the dev harnesses in [`docs/handoff/dev/`](docs/handoff/dev/)
(copy to a scratch dir; run from the repo root):

```bash
# screenshot in play; --exec/--post run Python with w, lt (logic), s (session)
xvfb-run -a -s "-screen 0 1600x1000x24" python3 shot.py out.png --skip-charcreate \
  --seconds 5 --size 1600x1000 --teleport=25600,-26600 \
  --exec 's.game.start_quest("ember_tome")' --post 'print(s.quest_arrow_targets())'
# per-thread profile of kiosk play (KIOSK=1, WARM=seconds of warm-up)
KIOSK=1 WARM=15 xvfb-run -a -s "-screen 0 1920x1080x24" python3 prof.py 10
```

`prof.py` sets `sys.setswitchinterval(0.001)` like `main.py`.
