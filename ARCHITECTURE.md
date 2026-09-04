# MiniWind branch — migration & architecture

This document is the migration record for turning MiniWind from a **Fio plugin**
into the **integrated game layer** of this branch, and the answer to the final
verification checklist (§26). It complements [`README.md`](README.md) (how to run
it) and [`PLAN.md`](PLAN.md) (the original code-grounded design).

## 1. Repository shape

```
game/          the integrated MiniWind game (built-in, not a plugin)
  __init__.py  GAME instance + install() bootstrap
  host.py      MiniwindGame — native game host (was the FioPlugin adapter)
  integration.py  editor wiring: native "MiniWind" menu
  entities.py  NPC, GameSettings, Marker
  runtime.py   MiniwindSession — clock + low-frequency AI + combat + dialogue
  factions.py schedule.py gametime.py inventory.py dialogue.py  (game-facing shims)
  rpg/         engine-agnostic RPG core (character, skills, magic, quests, combat, …)
  ui/          Qt overlays (HUD, dialogue, character/inventory/journal screens)
  data/        editable content: bestiary/factions/schedules/items/settlement JSON (+ mods/)
  tools/       make_settlement.py, make_world.py, make_sprites.py
  tests/       test_rpg.py, test_miniwind.py, test_settlement.py

engine/        generic Fio technology (renderer, terrain, monster AI, save/load, …) — unchanged
editor/        the Fio editor, presented as the MiniWind RPG Editor
plugins/       generic plugin system + BigWorld (optional plugin) — plugin system unchanged
maps/          village.json  (the living settlement, generated from game/data)
```

## 2. Files removed

**Stale root-level upload duplicates** (older copies of the packaged code; the
canonical versions lived in `plugins/miniwind/`):
`dialogue.py`, `entities.py`, `factions.py`, `gametime.py`, `inventory.py`,
`runtime.py`, `schedule.py`, `plugin.py`, `editor_ui.py`, `make_sprites.py`,
`make_village.py`, `test_miniwind.py`, `__init__.py`, `__init__ (11).py`,
`__init__ (12).py`, `plugins/temp`, root `Miniwind_village.json`, and ~20
duplicate role PNGs at the repo root.

**Original FPS-demo content** (no place in a fantasy RPG):
`assets/sprites/gun1.png`, `gun1HUD.png`, `gun1HUD_flash.png`, `gun2.png`,
`gun2HUD.png`, `gun2HUD_flash.png`, `cig.png`, `cigHUD.png`;
`assets/sounds/shoot.wav`, `shoot2.wav`, `shoot_flying.wav`;
`assets/sprites/topdown/player_shoot_g.png`.

**Broken/superseded tool:** `game/tools/make_village.py` (referenced a base map
that does not exist; replaced by the data-driven `make_settlement.py`).

## 3. Files moved / renamed

* `plugins/miniwind/` → `game/` (whole package; git records the moves).
* `plugins/miniwind/plugin.py` → `game/host.py`, and its class
  `MiniwindPlugin(FioPlugin)` → `MiniwindGame` (plain class, no plugin base).
* Absolute imports `plugins.miniwind.*` → `game.*` throughout; asset dir
  constants → `assets/sprites/miniwind/*` and `assets/portraits/miniwind/*`; test/tool root-path
  depth adjusted for the shallower location.

## 4. New MiniWind game architecture (how it boots without a plugin)

`MiniwindGame` (`game/host.py`) exposes the same lifecycle surface a plugin does
(`register` / `register_runtime` / `connect` / `on_play_start` / `on_tick` /
`on_play_stop`) but is **not** a `FioPlugin`: no discovery, no `enabled`
toggle, no `api_version`/`requires`, no Plugins-menu entry.

`PluginManager` gained a generic **built-in game** surface
(`register_builtin_game`): built-in games take part in entity/property/IO
registration, runtime attach, host bind and the play-lifecycle / per-tick
dispatch, but are excluded from plugin discovery, the enabled/disabled machinery
and the Plugins menu. This capability is generic and backportable to mainline
Fio.

Boot path:

```
main.py → import editor.main_window
        → editor/__init__.py:
              load_plugins()               # discovers BigWorld only
              plugins.integration.apply()  # generic plugin editor hooks
              game.install()               # <-- MiniWind, native
                  get_manager().register_builtin_game(GAME)   # entities/props/IO
                  game.integration.apply()                    # "MiniWind" menu, title
        → engine.logic_thread drives GAME's play lifecycle + tick through the
          manager's existing generic dispatch (no engine edits were needed).
```

## 5. New RPG editor architecture

* The window is branded **"MiniWind RPG Editor — powered by Fio"**.
* MiniWind entities (`NPC`, `GameSettings`, `Marker`) register under a **MiniWind**
  category in the editor palette and a native top-level **MiniWind** menu
  (`game/integration.py`), not the Plugins menu.
* Typed property widgets, and the Inventory/Dialogue/Quests custom tabs, are
  served by the *generic* editor extension surface (property schemas +
  `register_property_tab`) that the built-in game registers into — the same
  surface plugins use, so no MiniWind-specific code lives in `plugins/`.

## 6. Fio technology retained (and why)

The branch remains recognisably Fio. Retained generic technology, used as-is:
renderer, terrain, brushes, spatial grid, collision, top-down/overhead camera,
billboard rendering, lighting/shadows, the team-aware `engine.monster_ai`
(MiniWind combat *is* this AI), UUID persistence and the `.fiosave` serializer,
the `LogicKeyValueStore`/`GlobalStore`, the plugin system itself, and the
PyQt-free `plugins.entitybase.Thing` used as the headless entity base. None of
this was replaced — MiniWind is glue over it.

The line held (§3): generic *technology* stays generic; MiniWind *game policy*
(races, classes, birthsigns, skills, factions, quests, dialogue, schedules,
fantasy combat rules, lore) lives in `game/`. The one new generic-shaped
capability — the manager's built-in-game surface — is kept clean enough to
backport.

## 7. BigWorld remains a separate, optional plugin

`plugins/bigworld/` is untouched: still discovered as a normal `FioPlugin`,
still disabled-by-default, still demonstrating the plugin API. MiniWind does not
depend on it — the settlement fits comfortably in Fio's ordinary world
representation and spatial grid, so no massive-world streaming was added.

## 8. Moddable content format

Game **content** is human-editable JSON under `game/data/` (see the file list in
§1). `game/data/__init__.py` is a ~40-line loader: it reads `<name>.json` and
merges any `mods/<modname>/<name>.json` over it (dicts update by id, lists
append). Game **rules** (combat maths, stat derivation, the schedule planner,
the autonomy state machine) stay in `game/rpg/`. `bestiary`, `factions`,
`schedule` and `items` now build their registries from this data with identical
public APIs. This is a clean boundary, deliberately **not** a scripting language
or full modding SDK.

## 9. The living settlement

`game/data/settlement.json` authors **Millbrook**: six townsfolk with distinct
roles (blacksmith, merchant, farmer, guard, beggar, villager), each with a
persistent identity, home, workplace, bed and role schedule anchored to named
**markers**; a guard post; and a bandit/archer/wolf threat east of town.
`python -m game.tools.make_settlement` materialises it into
`maps/village.json`. `game/tests/test_settlement.py` simulates a day
headlessly and asserts townsfolk work by day, sleep at night, and walk to their
authored markers, with the threat starting hostile and outside the settlement.

## 10. Tests

`python -m pytest game/tests engine/tests plugins/bigworld/tests -q` → **95 pass**
(43 MiniWind incl. the new settlement suite, 52 engine + BigWorld), all headless
(no Qt/OpenGL). PyQt-dependent editor/engine UI paths cannot run in a headless
CI and are exercised structurally only.

## 11. Living world, combat and the Aurora-style editor (later pass)

A second pass turned the vertical slice into a world that reads as alive and an
editor that authors an RPG, keeping MonsterAI as the low-level mechanism and
MiniWind as the RPG-semantics layer:

* **Two distinct actor entities.** `NPC` (social/quest) and `Creature` (monster)
  are separate MiniWind entities — different roles, schemas and defaults — though
  both still run on the engine `Monster` + `MonsterAI`. Both bake per-role
  `custom_idle`/`custom_dead`/`custom_shoot` + size from the bestiary, so the 2D
  icon and 3D billboard match and an attacker never flips to the stock human
  sprite. Also added: `ItemPickup`, `MiniwindTrigger`, `CreatureSpawn`.
* **Faction / capability / flee are three separate axes.** The engine consults a
  game-supplied `logic._faction_hostile(a,b)` predicate and each actor's
  `sight_range` (so a bandit camp stays dormant until approached, and wild
  animals stay neutral to villagers). Combat *capability* is an authorable
  `combatant` property distinct from faction: a guard fights, a merchant on the
  same side never does. Non-combatants **flee to a bounded refuge** (home / a
  guard / a guard post), not an endless sprint.
* **Combat visuals.** Casters hurl magic bolts, archers loose arrows, and a
  struck actor flashes red (a `sprite_tint` uniform on the sprite shader driven
  by a decaying `_hit_flash`). Speech bubbles ('!' quest / '…' talk) float over
  nearby interactable NPCs, projected with the live render matrices.
* **Aurora-style editor, composed not monolithic.** Property schemas render in
  sections via a `group` field on `PropertySpec`. Authoring is a set of
  *reusable components* — an inventory table, a schedule table, and a branching
  **dialogue tree** (`dialogue_tree_widget`) — each bound to a properties dict so
  it works in a property tab *or* inside a **creation wizard**. Wizards
  (`npc_wizard`, `creature_wizard`) compose those same components and are run
  from a right-click **"Add MiniWind Entity"** submenu and the MiniWind menu via
  a generic `register_entity_wizard` surface. All additive — Fio's own editor
  entities, menus and the Plugins submenu are untouched.

The default camera is now Overhead. All new game-layer behaviour has headless
tests (`test_combat_ai`, `test_world_entities`, `test_editor_integration`).

## 12. Compromises / technical debt

* **Editor & engine Qt/GL paths are untested here.** The native game-host
  registration and all new game-layer behaviour are covered by headless tests,
  but the editor widgets (property sections, dialogue tree, wizards, right-click
  submenu) and the engine visuals (the `sprite_tint` damage-flash shader edit,
  magic-bolt projectile, speech-bubble projection) run only under PyQt5 + OpenGL,
  which this environment lacks. They follow existing working patterns and parse
  cleanly, but were not executed — worth a visual pass in the real editor.
* **CreatureSpawn depends on the engine monster cache.** Spawned creatures are
  appended at play start and `logic._build_entity_caches()` is called to refresh
  `_monster_things`; if a future engine change stops exposing that rebuild, spawned
  creatures would need another way to enter the AI's precomputed list.
* **Dormant engine weapon plumbing remains.** The original first-person gun/
  hitscan code in `engine/qt_game_view.py` and `engine/logic_thread.py` is inert
  in top-down MiniWind (the RPG suppresses the stock HUD and routes all combat
  through `game/rpg/combat`). The gun/cig *assets* are deleted; the generic
  weapon/projectile *code* was left in place rather than risk destabilising
  untestable engine paths. It is a clean future removal.
* **`GameSettings` type/name mismatch** (`type: "miniwindsettings"` vs class
  `GameSettings`) is pre-existing; the runtime finds it by scanning live things,
  so it is unaffected, but `plugin_for_type("miniwindsettings")` returns `None`,
  so that one entity's panel renders generically rather than schema-typed.
* **Races/classes/birthsigns/loot remain in code.** They are the next content to
  externalise; the loader and boundary make it mechanical, but doing so now
  risked the character-creation tests, so it was deferred.

## 13. Quests as external `.quest` files

Quests are authored content, so they live as human-readable `.quest` files (one
per quest, pretty JSON) in the top-level `quests/` folder — not baked into the
map's `GameSettings` entity. `game/rpg/quest_files.py` is the Qt-free loader/saver
the editor and the headless player both use, so the files the Quest Editor writes
are exactly the ones the running game loads at play start
(`MiniwindSession.__init__`). A map still carrying the old in-entity `quests`
list is migrated into the folder the first time the Quest Editor opens it.

**Givers are wired automatically.** A quest simply names its `giver`; at play
start `MiniwindSession._wire_quest_givers` finds the matching NPC (by entity id
(UUID), name, display name or role — id being unambiguous when NPCs share a
name) and injects a dialogue offer branch via the shared
`quests.offer_dialogue_branch` helper — so the giver becomes talkable, shows the
`!` available-quest bubble, and the player can walk up and accept. No manual
dialogue authoring is required, and a hand-authored offer is left untouched.
