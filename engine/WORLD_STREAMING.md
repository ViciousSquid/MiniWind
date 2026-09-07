# World streaming — cell streaming for very large maps

Cell streaming lets a single map hold **hundreds of thousands of brushes and
entities** while keeping only the area around the player active. The world is
divided into streamable **cells**; only the cells intersecting the player's
activation radius (default **2048 units**) take part in runtime rendering,
collision, entity processing and lighting. Distant cells stay stored in the map
but inactive — costing nothing per frame.

Crucially, this is a **runtime scalability layer, not a new world format**.
It builds on the systems the engine already has instead of replacing them: no
BVH, octree, BSP, ECS, or renderer rewrite. Objects keep their existing UUIDs
and positions; the streamer only decides, each frame, which of them are *live*.

It is a **core engine subsystem**, not a plugin — see
[`ARCHITECTURE.md`](../ARCHITECTURE.md) §7 for why it moved. `LogicThread` owns
the session, builds it at play start from the map's `BigWorldSettings` entity
and ticks it directly.

**Contents**

- [The idea](#the-idea)
- [Quick start](#quick-start)
- [Architecture](#architecture)
  - [Cells](#cells)
  - [Cell index](#cell-index)
  - [Session](#session)
  - [Terrain fill](#terrain-fill)
  - [Persistence](#persistence)
- [Editor vs. runtime](#editor-vs-runtime)
- [Configuration](#configuration-the-bigworldsettings-entity)
- [Measured performance](#measured-performance)
- [Simulation LOD](#simulation-lod)
- [Isolation & compatibility](#isolation--compatibility)
- [Generating and benchmarking worlds](#generating-and-benchmarking-worlds)
- [Files](#files)
- [Roadmap](#roadmap)

---

## The idea

```
                Fio World
                    │
          ┌─────────┴─────────┐
          │ Shared 512 Grid   │   (engine/cells.py — one definition, imported)
          └─────────┬─────────┘
                    │
            World cell index   
                    │
          ┌─────────┴─────────┐
          │   Cell Manager    │
          └─────────┬─────────┘
                    │
             2048-unit radius
                    │
          ┌─────────┴─────────┐
      ACTIVE CELLS       INACTIVE CELLS
          ▼                   ▼
   Render / Physics      Stored only
   Entities / Lights
```

The cell coordinates, the 512-unit cell size, and the multi-cell "spanning" rule
are all borrowed directly from Fio's existing `engine.physics.SpatialGrid`. Big
World adds one thing on top: a per-frame decision about which cells are active,
and a reversible way to apply that decision to the live engine.

Work each frame is proportional to **active cells + objects in active cells** —
*not* to the total size of the world. That is the entire point.

---

## Quick start

1. Open a map in the editor and place a **Big World Settings** entity. Its mere
   presence turns streaming on for that map; its properties set the radii. A map
   *without* one loads and plays exactly as before — see
   [Isolation & compatibility](#isolation--compatibility). (The entity keeps its
   original type name because that is what existing map files contain: a data
   format, not a code boundary.)
2. Enter play mode. Only cells within the activation radius of the player are
   active; walking moves the active set with you.
3. The debug overlay (top-left) shows live cell/brush/entity counts and a minimap
   of active cells.

`maps/bigworld_demo.json` is a small, hand-sized example: brushes across a 6×6
cell block, a spanning floor, NPCs, a light, a persistent world-manager and a
settings entity.

```bash
# run the headless test suite
python -m pytest engine/tests/test_world_streaming.py \
    engine/tests/test_world_streaming_saves.py \
    engine/tests/test_world_streaming_disk.py -q
```

Generating and benchmarking large synthetic worlds is covered
[below](#generating-and-benchmarking-worlds).

---

## Architecture

### Cells (`engine/cells.py`)

A cell is addressed by **integer** coordinates `(cell_x, cell_z)` — never floats
— and covers a fixed `512 × 512` column in X/Z, using `floor(coord / 512)`,
*identical* to `SpatialGrid`. Objects are **referenced** by a cell, never copied
into it, so a brush's data and UUID live in exactly one place regardless of how
many cells its footprint touches.

Each cell moves through a streaming lifecycle:

```
UNLOADED → LOADING → INACTIVE → ACTIVE → UNLOADING
```

For this milestone the whole map is resident in RAM, so a cell is only ever
`INACTIVE` or `ACTIVE`. The `LOADING`/`UNLOADING` states and the
`load_cell`/`unload_cell` API exist so true asynchronous disk streaming can be
layered on later **without reshaping the runtime above it** (see
[Roadmap](#roadmap)). `WorldCell` exposes `key()`, `is_active()`,
`is_loaded()`, `object_count()`, `bounds()` and `clear()`; `CELL_SIZE` and the
`CellState` enum are the shared constants.

### Manager (`engine/world_cells.py`)

`WorldCellIndex` owns the index and the active-set calculation.

- `index_world(brushes, things)` builds a UUID-addressed index and groups objects
  into cells: brushes into **every** cell their footprint overlaps (spanning
  handled exactly like `SpatialGrid.populate`), point entities into one cell,
  lights into every cell their influence *radius* reaches. `add_brush` /
  `add_thing` incrementally index a single object.
- `update(player_pos, force=False)` is the per-frame entry point. It **early-outs
  until the player crosses a cell boundary**, then:
  - obtains candidate cells from the **square** bounding the radius (cheap integer
    ranges over the grid), then keeps only those whose nearest edge is within the
    **circular** radius — never measuring distance to individual brushes;
  - applies **hysteresis** — a cell is added within `activation_radius` but not
    dropped until beyond `deactivation_radius` — so loitering on a boundary does
    not thrash cells on and off;
  - returns an `ActivationDelta`: the **net** cells entering and leaving,
    reference-counted so a brush shared by several cells is switched off only when
    its **last** active cell leaves.
- `activate_cell` / `deactivate_cell` return the `(brushes, things, lights)` that
  changed state; `active_brushes()`, `active_things()`, `active_lights()`,
  `is_brush_active()`, `is_thing_active()` and `stats()` expose the live set.

### Runtime (`engine/world_streaming.py`)

`WorldStreamingSession` applies the manager's active set to the live engine by
cooperating with existing machinery — every change is tracked and **fully
reversed on play-stop**:

| Concern | Integration (no subsystem replaced) |
|---------|-------------------------------------|
| Rendering | Inactive brushes get Fio's `hidden` flag; the per-frame cull already drops hidden brushes before the draw path, so only active geometry is submitted. |
| Physics | The player already collides via `SpatialGrid.get_potential_colliders`, which only returns brushes in the player's *local* cells — distant inactive geometry is never queried. Nothing to duplicate. |
| Entities | Inactive entities get `disabled` (and `hidden`), which the monster AI and pickup handlers already treat as "skip me". |
| Lights | Inactive lights are hidden, keeping the lights the renderer considers local to active cells — no global increase in light count. |

`start(player_pos)` snapshots what it is about to change and streams in the region
around the player; `tick(player_pos)` advances streaming (cheap — the manager
early-outs unless a boundary was crossed); `stop()` restores everything;
`player_cell()` and `stats()` feed the debug overlay.

### Terrain fill

Fio's procedural terrain is generated from noise as a pure function of world
position, so any point's height is the same however the mesh around it is built.
Big World uses that to fill a massive world with ground **without tessellating
the entire grid up-front**:

- With `terrain_fill` on, the session expands the terrain's chunk bounds to the
  bounding box of every indexed cell — so terrain covers the whole streamed world
  seamlessly — and switches the terrain into **streaming mode**.
- In streaming mode the terrain keeps resident only the chunks within
  `terrain_stream_radius` of the camera and frees chunks beyond it (with a
  hysteresis band, exactly like the cell manager). Because heights are
  position-deterministic, a chunk streamed back in is byte-for-byte identical: the
  world **stays the same shape**, it is simply built around the player as it moves
  rather than all at once.
- The terrain change is snapshotted on play-start and **restored verbatim on
  play-stop**, so the authored terrain (bounds, streaming flag, radius) is
  returned untouched — the editor is unaffected. The session never enables or
  disables the terrain itself, and never makes an OpenGL call off the render
  thread: a bounds change defers its chunk prune to the next render frame.

Terrain streaming is a plain `engine.terrain.Terrain` feature (off by default,
`set_streaming` / `set_world_extent`) that works with or without cell streaming;
the session just drives it from the same player position it already tracks.

### Persistence (`engine/world_persistence.py`)

Almost nothing new needs saving, by design:

- **UUIDs** are Fio's existing identity (`brush['id']` /
  `thing.properties['id']`). Big World only *reads* them — an object keeps the
  same UUID across load → activate → deactivate → save → reload → stream.
- **Cell assignment** is derived from position + the shared grid, so it is
  recomputed on load and can never be "lost".
- The only new datum — the map's streaming config — rides on the ordinary
  `BigWorldSettings` entity, so it round-trips through Fio's normal save/load with
  no core change. Transient runtime markers are stripped before a save.

#### Play-session saves are forced deltas

A **play-session save** of a Big World map (the native `save`/`quicksave`) is
always a **delta**, never a full world snapshot — chosen automatically:

```
Standard Fio map  → Full save
Big World map      → Forced delta save (world_mode = "bigworld")
```

The live `WorldStreamingSession` keeps a **persistent cell delta registry** —
`{"cx,cz": {"things": [...], "brushes": [...]}}` — that records each cell's
gameplay changes *relative to that cell's base state*, keyed by the same
`(cell_x, cell_z)` cell id the streaming manager uses, and by stable **UUID**
within a cell. It is independent of which cells are currently streamed in:

```
Cell loads → base instantiated → stored cell delta applied → gameplay mutates
→ commit_cell() merges the change into the registry → cell unloads
→ the change stays in the registry
```

Because the in-RAM streaming model never frees objects (parking only toggles
`hidden`/`disabled`/`bw_active`), a cell modified earlier and since unloaded is
still resident, so its changes are captured too. On save, `commit_all()` flushes
every cell in one authoritative pass (nothing pending is omitted); the registry
converges on *current − base*, dropping a change that has returned to base rather
than accumulating history. Streaming state is normalised away before diffing
(`normalize_streaming_state`) so a currently-parked-but-unmodified cell never
appears as a change. The save carries base-world identity (name + a UUID
fingerprint) to fail safe against the wrong world.

On load the save is auto-detected as a Big World delta, the base world is
validated, player/runtime state is restored, and every cell's UUID-keyed changes
are overlaid onto the freshly-loaded world (and the registry handed back to the
live session, so a cell streamed in later still carries its saved changes). This
reuses the delta machinery in [`engine/savegame.py`](savegame.py) — streaming
only adds the per-cell bucketing (`build_cell_delta_registry`) and streaming
normalisation, so there is no second persistence subsystem. Ordinary maps are
untouched and keep their full-snapshot saves.

#### Disk streaming — actually freeing unloaded cells (opt-in)

The default session keeps every object resident and only toggles flags, so an
unloaded cell's changes are trivially still in memory. The **disk-streaming**
milestone ([`engine/world_streaming_disk.py`](world_streaming_disk.py), enabled by the
`disk_streaming` setting) is the real thing: an unloaded cell's objects are
**removed from the live scene and freed**, and re-instantiated from a *cell
source* (its "disk") when the cell streams back in.

```
Cell streams in   → base instantiated from the source (a fresh copy)
                  → its base is CAPTURED here, the first time it is resident
                  → its saved delta is re-applied by UUID → cell active
gameplay mutates the cell
Cell streams out  → its delta is COMMITTED to the registry  ← before the free
                  → its objects are removed from the scene and freed
Cell streams in again → base re-instantiated + delta re-applied → change is back
```

Two things the in-RAM path got for free are earned here, and they are the point:

- **Each cell's base is captured the first time it streams in**, per UUID, from
  the pristine `CellSource` — because the whole world is never resident at once,
  a base can't be snapshotted up-front.
- **A cell's changes are committed before it is freed**, so the world-level
  registry (kept per UUID, bucketed by cell only when serialised) is the single
  source of truth for the save — most of the world isn't loaded to serialize.
  Freed UUIDs drop their retained base (re-captured on reload), so memory stays
  proportional to *loaded* cells, not world size.

`MemoryCellSource.from_logic(logic)` makes this usable over any ordinary map with
no new on-disk format (it deep-copies the map once as the pristine "disk image",
then the session empties the scene and streams cells in/out); `DirectoryCellSource`
reads `cell_<cx>_<cz>.json` files for a real on-disk world. Save/load reuse the
**same** Big World save format and the same `compute_delta_level` delta maths, so
a disk-streamed save is byte-compatible with an in-RAM one. `DiskStreamingSession`
exposes the same `commit_all` / `serialize_registry` / `base_identity` surface the
engine's save branch already calls, and loading routes through
`restore_saved` (the world can't be overlaid wholesale — cells apply their delta
as they stream). Spanning objects are reference-counted, so a brush straddling
two cells is freed only when its **last** loaded cell leaves. The base world is
fingerprinted to fail a load safely against the wrong world.

> Scope: the streaming/free/base-capture/registry/save-load logic is complete and
> covered by [`tests/test_bigworld_disk.py`](tests/test_world_streaming_disk.py). The
> remaining engine-side work is live integration — mutating the scene's
> `things`/`brushes` lists mid-frame and invalidating the renderer/physics caches
> for freed objects — so the setting ships **experimental** and off by default,
> falling back to the in-RAM session if anything goes wrong.

---

## Editor vs. runtime

Big World is primarily a **runtime** system. In the editor the full map stays
available — select, move, duplicate, delete, edit properties, read UUIDs — and
the session only parks geometry inside **play mode**, restoring everything exactly
on stop. Distant geometry is never made permanently inaccessible.

---

## Configuration (the `BigWorldSettings` entity)

One optional entity per map holds all config. Placing it is the opt-in; its
properties tune the behaviour:

| Property | Default | Meaning |
|----------|---------|---------|
| `enabled` | `true` | Master switch for streaming on this map. |
| `activation_radius` | `2048` | Cells within this distance of the player activate. |
| `deactivation_radius` | `2304` | Active cells drop only beyond this (hysteresis; clamped ≥ `activation_radius`). |
| `show_cell_debug` | `true` | Draw the stats panel + active-cell minimap in play mode. |
| `terrain_fill` | `false` | If the map has a procedural terrain, expand it to cover every cell of the world and **stream its chunks** around the player instead of building the whole grid up-front. Off by default — terrain is left exactly as authored. |
| `terrain_stream_radius` | `0` | World units of terrain kept resident around the player. `0` derives it from the activation radius. |

The schema is declared with typed
[`prop()`](../plugins/API.md#propertyspec-and-prop) specs (ranged floats, checkboxes,
tooltips), so the editor renders proper widgets for each field.

**Persistent (never-streamed) entities.** Mark any single entity persistent with
a truthy `bw_persistent` property; entity `type`s like `worldmanager` /
`globalscript` / `questcontroller` are persistent by default. Use this for world
managers, global game state, and quest/script controllers that must keep running
no matter where the player stands.

---

## Measured performance

`python -m tools.world.generate_world benchmark` on the reference
machine:

```
  brushes  startup  still/frame  per-cross   active/total brushes    save    load  idx-mem
   10,000     155m       3.44us     0.77ms       501/10,000        327m   153m    2.5M
   50,000    1030m       3.89us     1.01ms       501/49,729       1789m  1360m   14.4M
  100,000    1471m       3.67us     0.97ms       501/99,856       3268m  2709m   28.7M
  250,000    4127m       3.60us     1.09ms       501/250,000      9757m  8137m   65.8M
  500,000    7497m       3.68us     1.00ms       501/499,849     18941m 15768m  131.6M
```

The point of the table: **active brushes stay ~constant (≈500)** while the world
grows to 500k, and the **per-frame stationary cost (~3.7 µs)** and
**per-cell-crossing cost (~1 ms)** stay **flat regardless of world size**. Work is
proportional to `active cells + objects in active cells`, not to total world
objects.

Startup and save/load *do* scale with the total (a one-off whole-map pass —
acceptable while the map is resident in RAM). Removing even that is the future
milestone: async disk streaming, discussed in the [Roadmap](#roadmap).

---

## Simulation LOD

Streaming decides what is *loaded*. It does not, by itself, decide how much of
what is loaded gets simulated — that is
[`engine/world_index.py`](world_index.py), and the two are deliberately
separate systems that share one answer rather than one system doing both.

The link between them is the `disabled` flag this session already writes: an
actor the streamer has parked classifies as `TIER_DORMANT`, which means no
simulation *and* no classification — the world index is built only from the
unparked set, rebuilt when a cell streams in or out rather than rescanned each
tick. And a streaming map's activation radius becomes the engine's simulation-LOD
outer band on `start()`, so "how far out is the world still live" has exactly one
answer whichever system is asking.

The tiers inside the loaded region:

| Tier | Where | What runs |
|---|---|---|
| `TIER_NEAR` | player vicinity | everything |
| `TIER_ACTIVE` | near world | staggered decisions; still moves every tick |
| `TIER_DISTANT` | distant world | schedules and needs on the clock, one coarse step per pass, no perception |
| `TIER_DORMANT` | streamed out | nothing; state persists |

---

## How the engine drives it

`LogicThread` owns the session — there is no plugin between the engine and its
own world manager:

- **`_start_world_streaming`** (from `set_play_mode(True)`) finds the map's
  `BigWorldSettings` entity, builds a `WorldStreamingSession` (or a
  `DiskStreamingSession`), and publishes its radius to simulation LOD.
- **`_tick_play_mode`** calls `session.tick()` directly, first thing in the
  tick. A single cell-of-point compare early-outs until the player crosses a
  boundary.
- **`_stop_world_streaming`** (from `set_play_mode(False)`) restores the world
  exactly.
- **`notify_visibility_changed` / `notify_world_changed`** are the two calls the
  session makes back into the engine: the first says the cached non-hidden brush
  list and live-actor partition are stale, the second says objects entered or
  left the world and every index built from those lists must be re-derived.
  `StreamingHost` in [`engine/world_streaming.py`](world_streaming.py) writes
  that contract down; `LogicThread` implements a superset of it.
- The debug overlay lives in
  [`engine/streaming_debug.py`](streaming_debug.py) and is drawn by the viewport
  when the map's settings entity asks for it.

---

## Isolation & compatibility

- **Zero cost when unused.** A map without a `BigWorldSettings` entity never
  builds a session at all, keeps its whole world resident, and behaves exactly as
  before.
- **Fails safe.** The disk-streaming path falls back to the in-RAM session if
  anything about a map defeats it, and the debug overlay draws nothing rather
  than raising.
- **Reuses, never duplicates.** The cell grid is
  [`engine/cells.py`](cells.py) — the same one the collision grid, the actor
  index and the renderer's region cull use. Parking is expressed through the
  `hidden` / `disabled` flags the renderer, AI and pickup handlers already read.
  There is no second spatial structure and no second persistence subsystem.

---

## Generating and benchmarking worlds

The `generate_world` tool produces synthetic streaming maps and runs the scaling
benchmark headlessly:

```bash
# scaling report across 10k / 50k / 100k / 250k / 500k brushes
python -m tools.world.generate_world benchmark

# write a streaming-enabled map file
python -m tools.world.generate_world generate --brushes 100000 \
    --out maps/bigworld_100k.json
```

The generated maps include a `BigWorldSettings` entity, so they stream on load.

---

## Files

| File | Role |
|------|------|
| `engine/cells.py` | `WorldCell`, the `CellState` streaming states, shared 512-grid coordinate maths. |
| `engine/world_cells.py` | `WorldCellIndex` — UUID index, active-cell calc, hysteresis, streaming API, stats. |
| `engine/world_streaming.py` | `WorldStreamingSession` — applies the active set to the live engine (reversible); persistent cell delta registry. |
| `engine/world_streaming_disk.py` | `DiskStreamingSession` + `CellSource`/`MemoryCellSource`/`DirectoryCellSource` — disk streaming that frees unloaded cells, captures each cell's base on first stream-in. |
| `editor/things.py` | `BigWorldSettings` — the map-level opt-in / config entity. |
| `engine/world_persistence.py` | Config extraction, save hygiene, UUID-stability verification, cell delta registry + streaming normalisation. |
| `engine/logic_thread.py` | Owns the session: start, per-tick advance, stop, and the change notifications. |
| `engine/streaming_debug.py` | The stats panel + active-cell minimap. |
| `engine/world_index.py` | The actor index and simulation LOD that consume the loaded set. |
| `tools/world/generate_world.py` | Synthetic map generator + benchmark harness. |
| `engine/tests/test_world_streaming*.py` | Headless test suites. |

---

## Roadmap

The API is deliberately shaped so **asynchronous disk streaming** slots in behind
`load_cell` / `unload_cell` (reading/writing cell bytes) **without changing** the
`activate_cell` / `deactivate_cell` runtime above it. Profile first: the current
bottleneck is startup indexing + whole-map save — both one-off, both removed by
real disk streaming — not the per-frame path, which is already flat.
