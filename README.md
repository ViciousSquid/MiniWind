
# <img src="https://github.com/user-attachments/assets/83dc0282-4d1f-4c2c-90f9-7fdd571cabc3f" width="200">


## A small living fantasy RPG, built on Fio
#### RPG-oriented evolution of the Fio creation environment, with a game included as reference implementation

> # Early alpha work-in-progress

MiniWind (working title) is a **dedicated evolutionary branch of Fio**: a miniature, top-down,
moddable fantasy RPG that demonstrates Fio's technology through a complete game
and a specialised RPG editor.

> **Fio technology → MiniWind branch → small living RPG → easily-moddable game data**

MiniWind is **not a Fio plugin** and **not a separate engine**. It is the native
game layer of this branch. It reuses Fio's renderer, terrain, entities, spatial
grid, save/load, UUID persistence, top-down camera, billboard rendering,
lighting, collision and the team-aware Monster AI — and adds the RPG on top as an
integrated `game/` layer, not a plugin.

The generic Fio **plugin system remains** for optional plugins (BigWorld, Tidy);
MiniWind simply no longer travels through it — it is built in and always on.

| RPG feature | Reuses (Fio technology) | Adds (MiniWind game layer) |
|-------------|-------------------------|----------------------------|
| NPCs & creatures | `editor.things.Monster`, `engine.monster_ai.MonsterAI`, billboards, `team` | distinct **NPC** (social) and **Creature** (monster) entities, plus Item / Trigger / Spawn Point / Marker |
| Combat & targeting | team-aware `MonsterAI` (chase, melee, projectiles, death) | a `logic._faction_hostile` predicate + per-entity `sight_range`; faction / combat-capability / flee kept as separate axes |
| Factions | monster `team` string | `factions.relationship()` matrix (data-driven) |
| World time | — (engine ticks in real seconds) | `GameClock` |
| Schedules & autonomy | movement uses the existing position/grid path | low-frequency decision tick, `schedule.evaluate()`, local wander, bounded civilian flee-to-refuge |
| World markers | named entities + UUID persistence | authorable `Marker` entity referenced by name |
| Inventory / items | serialized for free via `properties` | `inventory` model + data-driven item DB |
| Dialogue | `LogicKeyValueStore` registry for state | `DialogueRunner` + an Aurora-style **dialogue tree** editor |
| Combat visuals | sprite billboards + projectile system | per-role attack sprite, arrows / magic bolts, red damage flash, speech bubbles |
| Save / load | Fio's UUID-matched serializer + `.fiosave` | nothing new — state lives in `properties`/KV |
| Editor UI | `register_property_tab`, typed property schemas, right-click placement | sectioned property panels, composable Inventory/Schedule/Dialogue/Loot/Quest components, creation **wizards**, "Add MiniWind Entity" submenu |
| Top-down view | overhead camera (default) + `render.overlay` | HUD, dialogue box, character/inventory screens |

## Running it

MiniWind starts with the editor — there is no plugin to enable:

```bash
python main.py            # launches "MiniWind RPG Editor — powered by Fio"
```

The editor bootstrap (`editor/__init__.py`) installs the native game host
(`game.install()`); the engine drives its play lifecycle and per-tick hook
through the manager's generic built-in-game surface. Open a MiniWind map (below)
and press **Play**.

## The living settlement (vertical slice)

The starter settlement **Millbrook** is authored entirely as data
(`game/data/settlement.json`) and materialised into a loadable map:

```bash
python -m game.tools.make_settlement   # -> maps/village.json
```

It contains six townsfolk with distinct roles (blacksmith, merchant, farmer,
guard, beggar, villager), each with a persistent identity, a home, a job, a bed
and a daily schedule anchored to authored **markers**; a guard post; and a
bandit/wolf threat east of town. In play:

```
Morning → NPCs wake → walk to work → merchant & blacksmith open → farmer works →
guard patrols → player talks/trades → a hostile wanders near → guard fights →
combat ends → NPCs resume their lives → evening → they go home → night → they sleep
```

High-level decisions run at a low frequency (`DECISION_INTERVAL`) or on events
(hour change, combat start/end); only movement runs per tick. Off-screen NPCs
resolve their state from the game clock rather than being simulated — the design
stays faithful to Fio's low-power brief (Snapdragon 8CX class).

## Moddable game data

Game **rules** live in code (`game/rpg/`); game **content** lives as
human-editable JSON under `game/data/`:

```
game/data/
    bestiary.json     creature & NPC role templates
    factions.json     cross-faction relationships
    schedules.json    per-role daily schedules
    items.json        the item database
    settlement.json   the starter settlement (markers + NPCs)
```

Every file is readable, diffable and version-controllable. To extend the world,
edit a file — or ship a **mod**: drop files of the same names under
`game/data/mods/<modname>/` and their entries merge over the base (a dict updates
by id, a list is appended). No code change, no SDK.

## Architecture

```
game/                     the integrated MiniWind game layer (built-in, not a plugin)
    __init__.py           GAME instance + install() bootstrap
    host.py               MiniwindGame — the native game host (registration, tick, overlay)
    integration.py        editor-side wiring: the native "MiniWind" menu
    entities.py           NPC, GameSettings, Marker entities
    runtime.py            MiniwindSession: clock + low-frequency AI + combat + dialogue
    factions/schedule/... game-facing modules (load their content from game/data)
    rpg/                   engine-agnostic RPG core (character, skills, magic, quests, combat…)
    ui/                    HUD, dialogue box, character/inventory/journal screens
    data/                  editable game content (+ mods overlay)
    tools/                 make_settlement, make_world, make_sprites
    tests/                 headless tests (no Qt/OpenGL)

engine/                   generic Fio technology (renderer, terrain, monster AI, save/load…)
editor/                   the Fio editor, presented as the MiniWind RPG Editor
plugins/                  the generic plugin system + optional plugins (BigWorld) — unchanged
```


## Tests

```bash
python -m pytest game/tests -q            # MiniWind: 58 headless tests
python -m pytest game/tests engine/tests plugins/bigworld/tests -q   # full: 110
```

Covers factions, game time, schedules, inventory, dialogue, the session's
schedule movement / combat override / dialogue item-grant / persist-restore, the
living-settlement simulation (townsfolk work by day and sleep at night, walking
to their markers), faction-aware combat with separated combat-capability and
bounded civilian flee-to-refuge, speech-bubble cues, the editor authoring wiring
(grouped schemas + creation wizards), and the world placeables (item pickup,
quest trigger, creature spawn) — all headless, like the bigworld tests.
