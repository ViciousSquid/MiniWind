# MiniWind on Fio 2.5.10: handoff

Read this first if you are picking this work up in a new session. It says what
has been done, how the tree is organised, how to run and check things, and what
is left. The decision record behind the migration is
[`docs/MIGRATION_FIO_2.5.md`](docs/MIGRATION_FIO_2.5.md).

- **Working branch:** `claude/jolly-goldberg-uybdqw` (MiniWind). Commit and push
  here. Never force-push (the remote refuses history rewrites); use merges.
- **Fio upstream:** `ViciousSquid/fio`.
  - `Canary` is the development line the user points at.
  - `2.5.10.3009_Latest` is the release line.

---

## 1. The goal

Move MiniWind off its old Fio 2.4.1 fork onto Fio 2.5.10. Keep MiniWind's
gameplay, content, editor tooling and look. Adopt the 2.5 architecture
properly:

- dense `EntityTable`/`RenderTable`, with no per-NPC Python GL draws;
- game policy lives in `game/`;
- Fio never imports `game`;
- Big World is authoritative and mandatory;
- don't weaken Fio's tests.

The user's standing instruction is: *"identical gameplay and features as
before, just on the new 2.5.10 engine"*.

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
| (this session) | **Pause menu, music, loading bar, fonts**, see §5a |

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
- `engine/`, `editor/`, `plugins/`: MiniWind's copy of Fio 2.5.10. Changes from
  the vendored Fio are documented in commit messages. The main ones:
  - **LogicThread hooks:** `game_session`, `player_fire_handler`,
    `_player_damage_filter`, `set_aim`/secondary shot in
    `threaded_game_state`.
  - **QtGameView:** the overhead head sprite and `_suppress_default_hud`.
  - **Overhead fit (§5):** `overhead_ground_footprint`, MonsterAI off-screen
    throttle, the Big World `fit_overhead_camera`/`terrain_stream` settings.
  - **Water/glass frustum cull** before the frame capture.
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

## 5. Overhead performance (MiniWind `c2b4dc9`; upstream Canary `fb18c9a`)

- **Footprint:** `LogicThread.overhead_ground_footprint()` gives the half
  extents of the ground the overhead camera shows.
- **Residency:** Big World (when fitted) keeps a circle just past the screen
  corners resident, refreshed every 256 units of movement. NEAR is the screen
  rectangle (`TierClassifier.set_near_rect`), re-tiered every 128 units. It
  publishes `logic.sim_tiers_fit_view`.
- **MonsterAI:**
  - parked (DORMANT) monsters are left out of the pass;
  - with a fitted view, off-screen monsters run once per 0.2 s with a per-row
    delta.
- **MiniWind-only:**
  - `game/host.py` sets the AI's batched enemy search to start at 16 actors
    (Fio's 64 assumed few queries a tick).
  - `MiniwindSession`: off-screen NPCs decide and move one tick in 4;
    proximity checks run at 10 Hz.
  - `settings.ini` uses `water_quality = cheap`.
- **Measured headless** (Xvfb and Mesa, which inflates the GL cost): about 13
  → 15 FPS in the village. The user saw 7–9 FPS on their own machine before
  this; **re-measure on real hardware.**

**To do: align MiniWind's copy with Canary `fb18c9a`.** The upstream version
fixed three things MiniWind's copy still has:

1. `stop()` must clear `logic.sim_tiers_fit_view`, and MonsterAI must require a
   live `_bigworld` before throttling.
2. A *scalar* delta of 0 must not skip rows; only a per-row array does.
3. In fit mode, the derived terrain stream radius must be pushed to
   `terrain.set_streaming`.

Also:
- New per-tick AI state goes in `__init__` and `forget_monsters()` (Fio's
  `test_final_audit` checks nothing outlives Stop).
- Upstream gates on *overhead camera* automatically, with no
  `fit_overhead_camera` setting. Either re-vendor those files from Canary or
  port the diffs. Keep MiniWind's `terrain_stream` setting, which upstream
  doesn't have.

---

## 5a. Pause menu, music, loading bar, fonts

- **Pause menu** (`game/ui/pause_menu.py`): Escape in play raises it, in the
  editor's play mode and in kiosk play alike (the old "Quit game and return to
  editor?" box is gone wherever the game is installed). One horizontal row:
  RESUME, GAME (a dropdown: NEW GAME / LOAD GAME / SAVE GAME; its arrow points
  down folded, up open), MUSIC: ON/OFF, EDITOR, QUIT. Mouse (the arrow cursor
  shows while it is up) and keyboard both work.
  - Fio side, generic: `QtGameView.play_menu` slot, `open_play_menu()`,
    `play_menu_closed()`; the view routes input to an open menu and paints it
    last; `MainWindow` hands Escape to a game modal that closes on it
    (`game_session.escape_closes_modal()`), else opens the menu, else the old
    exit. `game/integration.py _patch_play_menu` installs MiniWind's menu.
  - Actions (`game/ui/pause_actions.py`): slots are `saves/slotN.fiosave`
    (console `save`/`load`) plus a `"miniwind"` block holding MiniWind's
    key/value store (character, quests, clock). Load stops play, puts the
    store back, then the console load reloads the map and overlays the world.
    New Game stops play, wipes progress, reloads the map, starts play.
- **Music** (`game/music.py`): every `.mp3` in `assets/music` (moved from
  `assets/sounds/music`), shuffled, no repeats back to back, through
  `pygame.mixer.music`, during play only. `[GAME] music` in settings.ini
  remembers the pause-menu switch; `[GAME] music_volume` (default 0.5).
- **Loading bar** (`editor/loading_overlay.py`): the splash's progress bar over
  the window during map loads and play start, stepped at each stage
  (`_loading_step` in `main_window.py`); `main.py` opens the default map and
  kiosk play under one bar.
- **Fonts** (`game/ui/fonts.py`, files in `assets/fonts`): Enchanted Land for
  the pause menu's banner/options and the loading title; MedievalSharp (OFL,
  licence beside it) for conversations, the menu's small print and the bar.
  Arial/Georgia only if a file is missing. The rest of the HUD and screens
  still use `game/ui/theme.py`'s fonts.

## 6. What still needs doing

### Known failing tests (4, in MiniWind only)

`game/tests/test_combat_loadout.py` expects `MonsterAI._attack_style_for` and
`Monster.get_render_snapshot`. These are fixed by Parity C. Everything else
passes: 4,333 passed and 166 skipped. The skips are Fio tests needing content
MiniWind doesn't ship.

### Parity C: monster AI (largest remaining gap)

The 2.4 fork had game-aware AI that 2.5's `engine/monster_ai.py` lacks. The
engine can't import `game`, so add generic hooks on LogicThread/MonsterAI and
install them from `game/host.py` or `game/runtime.py`, as `7e9a3af` did for
player hooks.

- Factions: `logic._faction_hostile` or a dense team-hostility matrix. Today
  any different team is an enemy, so villagers fight sheep.
- Only hostiles hunt the player; per-actor `sight_range`.
- Dice damage through `game_session`.
- Melee, bow and magic attack styles via a combat-loadout hook (fixes the 4
  tests). Spells.
- Facing hook; `_hit_flash` decay; `_sim_tier` LOD.
- Projectile colour, kind and stuck arrows.

Reference: `origin/main` (the 2.4 MiniWind) `engine/monster_ai.py`, and
`game/combat_loadout.py`, `game/combat_styles.py`, `game/facing.py`.

### Parity D: actor visuals (the rest)

- NPC heads rotated by heading.
- Hit-flash tint, dead heads, gib visuals.

All of it goes through EntityTable columns and the change journal (`touch()`),
never per-NPC Python draws. Player head and weapons are done.

### Parity E: view and editor features

- Mouse control and aim publication from `QtGameView` (the `set_aim` hook
  exists).
- Sound falloff.
- Stuck arrows and projectile visuals.
- Marker pins.
- Inspector simulation tab.
- `main_window`: kiosk standalone, shortcut suspension, reset prompt.
- Launcher integration testing.

Compare against `origin/main` to find each feature.

### Housekeeping

- Keep `docs/MIGRATION_FIO_2.5.md` current.
- If `origin/claude/fio-2.5.5-migration-audit` is ever needed: it's an old
  2.5.5 attempt, evidence only, not a base.

---

## 7. Running and checking

Environment setup in a fresh cloud container:

```bash
apt-get install -y libopengl0 libegl1 libglu1-mesa libxcb-icccm4 libxcb-image0 \
  libxcb-keysyms1 libxcb-render-util0 libxcb-xinerama0 libxcb-xkb1 \
  libxkbcommon-x11-0 libxcb-shape0 libxcb-randr0 libxcb-xfixes0 libxcb-cursor0 \
  glslang-tools xvfb
pip install -r requirements.txt pytest pyflakes yappi
```

Full suite (about 90 s). The editor rewrites `settings.ini`, so back it up and
restore it around any run:

```bash
cp settings.ini /tmp/settings.keep
PYTHONDONTWRITEBYTECODE=1 xvfb-run -a -s "-screen 0 1280x1024x24" \
  python3 -m pytest -q -p no:cacheprovider
cp /tmp/settings.keep settings.ini
```

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
