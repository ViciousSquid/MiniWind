# Miniwind — implementation plan (grounded in the Fio codebase)

This is the concrete plan requested in §19: for each feature, which existing Fio
class/system it extends, which plugin hook it uses, whether it needs core
changes, how it saves/loads, how often its logic runs, how it behaves when a
world cell is unloaded, and how it's exposed in the editor. It is based on the
actual code (paths cited), not assumptions. Phase 1 (the vertical slice) is
**implemented** in this package; later phases are specified for continuation.

---

## 0. What the codebase already gives us (findings)

- **Entities** — every placeable is a `editor.things.Thing` with a free-form
  `properties` dict and a stable `properties['id']` UUID
  (`editor/things.py:80-96`). `Monster` (`things.py:357`) already has `health`,
  `damage`, `team`, `awake`/`triggered`/`wake_on_sight`, patrol, variant sprites
  and death handling.
- **Monster AI** — `engine.monster_ai.MonsterAI` runs on its own thread at
  ~30 Hz (`MonsterAIThread`, `monster_ai.py:1198`) and is **team-aware**: same
  team never targets or crossfires; an awake monster prefers an enemy-team
  monster over the player (`monster_ai.py:135-146, 261-278, 463-499`). Crucially,
  **any awake monster targets the player by default** (`monster_ai.py:276-278`).
- **Teams** — a plain `properties['team']` string; the AI reads it directly.
  There is no faction layer yet.
- **Global state** — `editor.things.LogicKeyValueStore` (`things.py:1438`) is a
  named, string-valued store with a process-wide `_persistent_registry` that
  survives level transitions and **serializes itself** into saves via a custom
  `to_dict`/`from_dict` embedding `runtime_data` (`things.py:1586-1607`).
- **Plugin GlobalStore** — `plugins.api.GlobalStore` binds to that *same*
  registry (`plugins/API.md` "GlobalStore"), so a plugin and map logic share KV
  state.
- **Save/load** — engine-native (`engine/savegame.py`), JSON `.fiosave`. It
  serializes the level (every thing's public `properties`, underscore-prefixed
  keys stripped by `_public_state`, `savegame.py:139`) plus a `runtime` block,
  and **restores by overlaying onto the live scene matched by UUID**
  (`API.md` "Play-session save / load"). So *any non-underscore property
  persists and round-trips for free.*
- **Plugin API** — `FioPlugin` lifecycle (`register`, `register_runtime`,
  `connect`, `on_play_start/tick/stop`), `EditorAPI.register_entity` /
  `register_properties` / `register_property_tab` (API 1.3.0), `RuntimeAPI`
  (I/O handlers, `entities_of_type`, `things_near`, `raycast_from_crosshair`,
  `spawn`/`despawn`), `PluginHost` (event bus, `render.overlay`, services). The
  `render.overlay` event hands a live `QPainter` (`qt_game_view.py:1174`).
- **Top-down** — an overhead camera mode exists (`cam topdown`,
  `console_commands.py:1401`; `qt_game_view._is_overhead`) with billboard
  sprites — exactly the target presentation.
- **Big World** — `plugins/bigworld` is the reference for a complete plugin with
  cell streaming and per-cell persistent deltas keyed by UUID; the RPG is
  designed to layer on top of it unchanged.

**Conclusion:** essentially nothing needs core-engine changes. The RPG is glue
over existing systems. The one non-obvious point is the combat reconciliation
below.

---

## 1. NPCs / creatures — one entity foundation (§1)

- **Extends:** `editor.things.Monster` (so `NPC` inherits billboards, health,
  `team`, death, and is picked up automatically by `MonsterAI`, which scans
  `isinstance(t, MonsterThing)`). → `entities.py: class NPC(Monster)`.
- **Hook:** `EditorAPI.register_entity(NPC)` + `register_properties("npc", …)`
  in `plugin.register`. Player-safe via the `editor.things` → `plugins.entitybase`
  fallback (same pattern as `plugins/tidy/entities.py`).
- **Core changes:** none.
- **Save/load:** all RPG fields live in `properties` (`entity_type`, `faction`,
  `npc_role`, `display_name`, `inventory`, `dialogue`, `schedule`, `home`,
  `work_location`, `aggression`, `quest_flags`, `merchant`, `respawn`,
  `persistent`) → serialized and UUID-matched by the stock save system. Transient
  fields use a leading underscore (`_dest`) so `_public_state` drops them.
- **Frequency:** movement per tick; decisions low-frequency (see §3).
- **Cell unload:** state is in `properties`, saved in the cell's per-cell delta
  by Big World; on reload the schedule is re-resolved from the clock (§13).
- **Editor:** typed property widgets (role/faction/aggression enums) + custom
  Inventory & Dialogue tabs (§7/§10).

**The combat reconciliation (key decision).** Because an *awake* monster always
pursues the player, neutral NPCs must not be "awake" to the core AI. So `NPC`
defaults non-hostile roles to **parked** (`triggered=True`), which `MonsterAI`
treats as "waiting for an I/O trigger" and skips (`monster_ai.py:117-119`). The
plugin's schedule drives parked NPCs. Defenders un-park into the core AI for
combat and re-park afterwards; hostile roles start un-parked. This gives §15's
per-role behaviour from `team` + `aggression` + `npc_role` with zero core edits.

---

## 2. Factions & teams (§2)

- **Extends:** the `team` string the AI already uses.
- **Hook:** pure module `factions.relationship(a, b, overrides) →
  friendly|neutral|hostile`; consulted by `runtime._nearest_hostile` and the
  combat override. Same team ⇒ friendly; unlisted pairs ⇒ neutral.
- **Core changes:** none. (The core AI's same-team rule already covers "allies
  don't fight"; the plugin adds cross-faction hostility on top.)
- **Save/load:** faction is `properties['faction']` (mirrored to `team`);
  quest-driven changes go through the KV store as an `overrides` source later.
- **Frequency:** evaluated only on the decision tick / on combat checks.
- **Cell unload:** stateless lookup; nothing to store.
- **Editor:** `faction` enum property.
- **Growth room:** `overrides` param + KV-backed standings → reputation, crimes,
  guards reacting, quest faction shifts — without touching call sites.

---

## 3. Low-frequency AI (§3)

- **Extends:** the plugin tick (`on_tick`, `logic_thread.py:1569`) and the
  existing movement/position + spatial grid.
- **Hook:** `MiniwindSession.tick(delta)` (`runtime.py`): advance the clock and
  move NPCs **every tick** (cheap float math); run the **decision** loop only
  every `DECISION_INTERVAL` (0.4 s) or when the game hour changes. Decisions:
  evaluate schedule, pick destination, apply combat override.
- **Core changes:** none. Combat itself is delegated to `MonsterAI`.
- **Save/load:** `sched_state` persists in `properties`; `_dest` is transient.
- **Frequency:** high-frequency = movement/animation/collision (reused core);
  low-frequency = decide/destination/schedule/target (plugin).
- **Cell unload:** decisions simply don't run for unloaded cells; on reload the
  first decision tick re-derives state from the clock.
- **Editor:** none (behavioural).

---

## 4. Radiant-AI-lite schedules (§4)

- **Extends:** nothing — new data, driven by the decision tick.
- **Hook:** `schedule.evaluate(schedule, game_hour)` returns the active
  `{state, location}`; `ROLE_SCHEDULES` gives per-role defaults (blacksmith,
  merchant, guard, farmer, beggar, villager). States: SLEEPING / GOING_TO_WORK /
  WORKING / GOING_HOME / IDLE / COMBAT (COMBAT applied as an override only).
- **Core changes:** none.
- **Save/load:** `schedule` + `sched_state` in `properties`.
- **Frequency:** table lookup on the decision tick.
- **Cell unload:** re-evaluated from the clock on reload (the whole point of a
  *time-based* schedule) — the NPC is restored where it should be, not simulated
  there (§13).
- **Editor:** a Schedule tab is the natural next custom editor (§11); Phase 1
  authors schedules as a property / via `make_village.py`.

---

## 5. World time (§5)

- **Extends:** nothing (engine has no game clock; it ticks real seconds).
- **Hook:** `gametime.GameClock` advanced from `ctx.delta` in `session.tick`;
  drawn top-right via `render.overlay`.
- **Core changes:** none.
- **Save/load:** the clock is mirrored into the KV store (`_clock_hour`,
  `_clock_day`) which persists via a map `LogicKeyValueStore` — no new format.
- **Frequency:** a couple of float adds per tick.
- **Cell unload:** the clock is global, unaffected.
- **Editor:** `MiniwindSettings` entity (`start_hour`, `minutes_per_day`, …).

---

## 6. Inventory (§6)

- **Extends:** the `properties` dict as storage.
- **Hook:** `inventory.py` free functions (add/remove/transfer/has/quantity/
  weight/value) over `properties['inventory']` (a list of item-stack dicts).
  Works for player, NPCs and monsters identically.
- **Core changes:** none.
- **Save/load:** NPC/monster inventories persist as ordinary properties; the
  **player** inventory lives on `logic._mw_player_inventory` and is mirrored to
  the KV store as JSON so it round-trips (the player object has no stable
  gameplay-property dict).
- **Frequency:** event-driven (pickup, trade, dialogue) — never per frame.
- **Cell unload:** inventories travel with their entity's per-cell delta.
- **Editor:** the **Inventory tab** (`editor_ui.make_inventory_tab`) — a table
  with Add/Remove and editable qty/value (§7).
- **Growth room:** the stack schema (`id/name/qty/type/value/weight/description`)
  leaves room for equipment slots, containers, loot tables, encumbrance and
  per-instance ids with no storage-shape change.

---

## 7. Inventory editor (§7)

- **Extends:** the Property Manager via `EditorAPI.register_property_tab`
  (API 1.3.0, consumed at `plugins/integration.py:480`).
- **Hook:** `plugin.register` registers `make_inventory_tab` for `entity_type="npc"`.
- **Core changes:** none (the extension point already exists).
- **Save/load:** the tab writes straight back into `properties['inventory']`.
- **Frequency:** editor-time only.
- **Cell unload:** N/A (editor).
- **Editor:** *is* the editor feature.

---

## 8. Dialogue trees (§8)

- **Extends:** nothing; new data + a small runner.
- **Hook:** `dialogue.DialogueRunner(tree, store, give_item, …)`: start node,
  branching responses, `condition` gating (visibility) and `actions`/`on_enter`
  (set flag, start quest, give/take item, plus an `on_action` sink for teleport /
  fire-I/O / change-faction). Opened from `on_tick` (proximity + USE) or the
  `StartDialogue` I/O input; rendered via `render.overlay`.
- **Core changes:** none.
- **Save/load:** the tree is `properties['dialogue']`; conversational *outcomes*
  (flags, items) persist through the KV store / inventory, so a save mid- or
  post-conversation restores correctly.
- **Frequency:** only while a conversation is open (input handling), else idle.
- **Cell unload:** trees travel with the NPC; state is in the KV store.
- **Editor:** the **Dialogue tab** (§10).

---

## 9. Reuse the logic system for state (§9)

- **Extends:** `LogicKeyValueStore` / `GlobalStore` — *the* persistent global
  RPG state, not a second system.
- **Hook:** `runtime.StateStore` adapts `host.globals` to the dialogue store;
  dialogue conditions read it and actions write it. A map `LogicKeyValueStore`
  named after `state_store` makes those values durable and shareable with map
  logic (its I/O `SetValue`/`TestValue` see the same keys).
- **Core changes:** none.
- **Save/load:** the KV store persists itself (`things.py:1586`).
- **Frequency:** event-driven (dialogue) + a cheap periodic mirror of clock/inv.
- **Cell unload:** global; unaffected.
- **Editor:** existing KV-store editor + `MiniwindSettings.state_store`.

---

## 10. Dialogue editor (§10)

- **Extends:** Property Manager via `register_property_tab` (as §7).
- **Hook:** `editor_ui.make_dialogue_tab` — node list + NPC-text + `text ->
  node` response outline + Add/Remove node + start-node field, writing back to
  `properties['dialogue']`. A structured list editor now; the data format (nodes
  keyed by id, responses with `goto`/`condition`/`actions`) is exactly what a
  future graphical node editor would consume.
- **Core/​save/​frequency/​cell/​editor:** as §7.

---

## 11. Property Manager architecture (§11)

- **Extends:** the existing tab registry — *not* a bespoke UI framework. The
  general mechanism already exists: `register_property_tab(label, factory,
  entity_type)` and `register_extra_fields(entity_type, specs)`
  (`plugins/manager.py:489-520`, `integration.py:464-495`).
- **Plan:** this plugin uses it for Inventory & Dialogue now; Schedule, Loot
  Table, Quest and Faction editors are further factories on the same seam — the
  "property_type → custom editor" registry §11 asks for, already Fio-native.
- **Core changes:** none.

---

## 12. Persistence (§12)

- **Extends:** the native save system (`engine/savegame.py`) — no new format.
- **How each thing persists:**
  - NPC position / inventory / schedule state / faction / quest_flags → ordinary
    `properties`, saved and UUID-matched by the stock serializer.
  - Global quest flags → KV store registry (self-serializing).
  - Clock + player inventory → mirrored into the KV store.
  - Dead entities, looted containers, changed factions → all are `properties`
    mutations the overlay restores by UUID.
- **Core changes:** none. (If a future need arises to persist plugin state on a
  map with *no* KV entity, the clean hook is a `save.snapshot`/`save.restore`
  event on the bus — additive, still no format change.)
- **Frequency / cell:** save is user-driven; delta saves already store only
  changed entities by UUID and cooperate with Big World's per-cell registry.

---

## 13. Large-world compatibility (§13)

- **Extends:** `plugins/bigworld` — designed to layer under this plugin
  unchanged. Big World hides/streams entities by cell and keeps per-cell
  persistent deltas keyed by UUID (`bigworld/persistence.py`).
- **Plan:** off-screen NPCs are **not simulated**. When a cell unloads its NPCs'
  state is in `properties` (captured by the cell delta); when it reloads, the
  first decision tick re-resolves the schedule from the current game hour, so an
  NPC "snaps" to where it logically should be (home at 23:00, market at 12:00)
  rather than walking across unloaded terrain.
- **Core changes:** none.
- **Editor:** placing both a `BigWorldSettings` and RPG entities just works
  (both plugins auto-enable off their own entities).

---

## 14–15. Top-down presentation & combat (§14/§15)

- **Presentation:** the overhead camera + billboard sprites already exist; the
  plugin leans into them and draws the clock/dialogue via `render.overlay`. No
  directional sprites required.
- **Combat:** entirely the core `MonsterAI` — chase, LoS, melee, projectiles,
  death-fall — selected by `team`/`faction` + `aggression` + the park/un-park
  override. A guard fights a bandit; a villager flees the fight by staying
  parked; a merchant never attacks. No "is this a monster or an NPC?" branch
  anywhere.

---

## 16–17. Architecture & phases

Phase 1 (**implemented here**): plugin foundation, `NPC` extension, faction
interpretation, game time, one scheduled NPC, inventory, one dialogue tree,
save/load — proven by `tests/test_miniwind.py` and `tools/make_village.py`.

Phase 2 — multiple schedules, home/work, guards, merchants, faction relations,
combat overrides (foundations all present; add trade + more roles).

Phase 3 — player inventory UI (HUD panel via `render.overlay`), NPC inventories/
loot on death, item pickups, dialogue conditions/actions (already supported),
global quest flags (already KV-backed).

Phase 4 — Property-Manager Schedule/Loot/Quest editors on the existing tab seam.

Phase 5 — Big World integration: per-cell NPC unload/reload, simplified
off-screen schedule resolution (design already cell-safe).

---

## The smallest viable vertical slice (§19)

`maps/Miniwind_village.json` (built by `tools/make_village.py`): the player
spawns overhead into a village; **Fargoth** follows wake → work → home → sleep;
the player presses USE to open his **dialogue tree**, accepts a quest and
receives an **Iron Sword** into the **player inventory**; a **Gate Guard**
demonstrates the combat override against an eastern **Bandit**; the **game clock**
shows top-right; and `save`/`load` restores clock, quest flag and inventory. That
single loop exercises every Phase-1 system and demonstrates Fio hosting a
complete game as a plugin.
