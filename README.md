
# <img src="https://github.com/user-attachments/assets/83dc0282-4d1f-4c2c-90f9-7fdd571cabc3f" width="200">

# Miniwind — a first-party fantasy RPG for Fio

**Miniwind** is a complete, top-down, open-world fantasy role-playing game built
on Fio, set in its own world, the **Vale of Miniwind**: learn-by-doing
progression, grounded factions and reputation, coloured loot rarity, and an
attributes-and-skills backbone with every roll on the table, in the spirit of
tabletop roleplaying.

Fio is treated here as the **engine powering a total conversion** — a first-party
title, not an optional plugin. It ships enabled and is the canonical
demonstration that Fio can drive an entire RPG.

> **No guns.** Miniwind is a sword-and-sorcery world. The engine's combat was
> extended so creatures and NPCs fight with **melee**, **bows & arrows** or
> **magic** — never firearms.

## Play it

```bash
python main.py
```

The launcher offers **Play** or **Edit**. Play drops you into character creation
and then into the Vale; the map it opens is set by `[Startup] default_map` in
`settings.ini`. The starter world can be regenerated with:

```bash
python -m game.tools.make_world       # -> maps/Miniwind.json (starter slice)
```

Talk to the townsfolk for work, buy gear from the smith and the trader, then
clear the bandits from the Old Mill, cull the wolves troubling the flocks, or
brave the barrows and caves of the Vale. What the town knows about you is a
consequence of what it saw — see *The reactive simulation* below.

The world has 20 caves spread across the Vale. Only Whisperdeep contains a
dragon: Vharzul the Ember Wyrm, whose head is eight times the player's size.

### Controls (top-down)

| Key | Action | Key | Action |
|-----|--------|-----|--------|
| **WASD** | Move | **E** | Talk / interact (nearest NPC or object) |
| **F** | Attack | **K** | Cast the active spell |
| **X** | Cycle active spell | **B** (hold) | Block |
| **V** | Toggle sneak | **H** | Quick-drink a healing potion |
| **I** | Inventory & equipment | **C** | Character sheet |
| **J** | Quest journal | **P** | Spellbook (click a spell to ready it) |
| **M** | Map | **Q** | Current quest (objective + how to complete) |
| **L** | Level up (when available) | **1–9** | Weapon quick slots (taken in hand at once) |
| **Esc** | Close / back | | |

Gameplay rolls (attacks, casts, loot) animate on their own; there is no manual
die-roll key.

In the gameplay console, `overheadangle` shows the current camera elevation.
Try `overheadangle 60` or `overheadangle 45` for an angled view;
`overheadangle 90` restores straight down (the default). Values from 1 to 90
degrees are accepted, and saves preserve the angle.

Locked containers open a real-time [lockpicking minigame](docs/lockpicking.md).
Lift the active pin by dragging, then hold the right button or toggle Space
to apply tension. Patrols can catch you. Snapped picks can jam a lock at very
low Security; only the **Knock** spell can open a jammed container.

The physical key below **Esc** opens and closes the console in play and in the
editor, including **§** on ISO Mac keyboards and **` / ~** on US keyboards.

## What's in the game

| System | Summary |
|--------|---------|
| **Character creation** | 10 races (each with attribute/skill bonuses, resistances and a daily power), 13 classes, 10 birthsigns, or your own custom class. |
| **6 attributes** | Strength, Endurance, Speed, Intelligence, Charisma, Luck — driving every derived stat and roll. Strength, Endurance and Charisma are rolled at creation and belong to every living thing in the Vale. |
| **20 skills, leveled by use** | Blade, Blunt, Marksman, Block, Heavy/Light Armor, Destruction, Restoration, Alteration, Conjuration, Illusion, Mysticism, Alchemy, Sneak, Security, Mercantile, Speechcraft, Acrobatics, Athletics, Light Fingers. Doing raises them; raising *major* skills levels you up. |
| **Derived pools** | Health, Magicka and Stamina, recomputed from attributes; passive magicka/stamina regen. |
| **Combat** | Melee (charge weapons, dual wield, off-hand strikes), archery with a real draw for NPCs and player alike, spells; hit chance, criticals, sneak attacks, blocking, armour mitigation and elemental resistance — all through the engine-native dice service. |
| **Magic** | 30+ spells across six schools, magicka cost that falls with skill, self/touch/target/projectile delivery, summons and bound weapons. |
| **Items & equipment** | Weapons, armour (heavy/light by slot & material), ammunition, potions, ingredients, books (plain-text, fiopak-packable), keys and gold; encumbrance from Strength. |
| **Lockpicking** | Individual latched pins, mouse resistance, tension/strain, snapping and shearing; five lock difficulties, Security progression and the Knock spell. The world keeps running during an attempt. |
| **Loot rarity** | Dropped gear can roll **Fine / Rare / Fabled** tiers — worth more, tinted in the UI, and hitting/protecting harder. |
| **Quests & journal** | Multi-stage quests authored as human-readable `.quest` files in `quests/`, with a journal, and quest state stored in the persistent KV store (visible to map logic). |
| **Guilds & reputation** | Joinable guilds with rank ladders, reputation-driven promotion, NPC disposition, persuasion, and a crime bounty that exists only once somebody who knows tells the law. |
| **Economy** | Merchants with stock, gold and overnight restock; buy/sell prices set by Mercantile + Personality; stolen goods stay marked. |
| **World** | A game clock with day/night, Radiant-AI-lite NPC schedules (home → work → sleep), roads with real traffic that materialises near the player, wildlife that roams, and lairs that refill. |
| **Save / load** | The whole character (stats, skills, inventory, equipment, spells, guild standing) plus quests, the clock, each map's memory and the event history round-trip through Fio's stock save system — no new format. Autosaves run every few minutes of play and on discovery, as delta saves. |

## The reactive simulation — author causality, not stories

`game/sim/` provides the small, composable mechanisms whose *interactions*
produce the stories. The pipeline is deliberately one-directional and
scenario-free:

    session emits a WorldEvent
        → perception picks the witnesses (sight / sound / asleep / distance)
            → knowledge stores a Fact per witness (certainty, source)
                → appraisal turns each Fact into a ranked Intent + a reason
                    → the session's decision tick honours the top Intent

* **Ownership** — any object or stack may carry an `owner`. Taking something
  owned is a theft event; a cow's milk inherits the farmer as owner, so it is
  stealable with no code and no "milk quest".
* **Perception** — an act is not a fact. Sight needs an awake observer in range
  (dimmed at night, shrunk by a sneaking actor's stealth); sound needs only
  loudness. The victim always knows; nobody is a witness to their own deed.
* **Knowledge** — facts carry `certainty` and `source` (`witnessed` / `heard` /
  `told`). Gossip passes them on at decayed certainty, so news travels at
  walking pace, can be outrun, and fades with the days.
* **Appraisal** — the same fact means different things to different people:
  the victim's kin FIGHTs, a baker who saw it REPORTs, a guard ARRESTs, a
  coward flees, a rival shrugs. Every intent carries its reason in plain
  English, which is what the Live Simulation Inspector shows.
* **Crime** — a bounty is what *other people do about it*. No witness, no
  bounty — until the body is found or the rumour reaches a guard. Reporting is
  deduplicated per event: ten witnesses, one bounty.
* **Production** — objects that make other objects on a clock, whose yields
  inherit the producer's owner.

Everything here is pure Python — no Qt, no engine imports — and headlessly
tested. The **director** owns the bus and drives the chain; parked, distant
actors are simulated coarsely (gossip, reports, production in hour-long
catch-up passes), and truly dormant ones not at all.

### The settlement watch

[Player guide: Crime & the Settlement Watch](docs/CRIME_AND_THE_WATCH.md)

[Player and editor guide: Locks & Containers](docs/lockpicking.md)

An observed player crime immediately shows **“Someone witnessed your crime.”**
Hearing a disturbance alone does not identify its culprit. Witnesses walk to the
nearest living guard using the normal wall-aware pathfinder, choose another if
that guard dies, and must reach speaking distance to testify. If the watch is
absent they seek a guardpost and keep their account. Existing gossip can carry
the same accusation through other townsfolk; one crime still produces one charge.

Both the world map and minimap show witnesses carrying unreported accusations:
an **eye** means they identified you, **?** means an uncertain account, and a
**red marker with an arrow** means they are going to report. Markers follow the
living witness and clear after reporting or death.

The watch records a local **writ**. Guards act on accusations they have actually
heard, rather than sharing an all-knowing bounty flag. Refusing arrest raises the
**hue and cry**. Break sight, leave the circle around your last sighting, and stay
unseen for 15 game minutes (45 for a blood writ) to end the search. Your debt
survives escape, borders and saving. Darkness, sneaking, walls and invisibility
help you escape; seeing you again resets the search.

While guards search, both maps show a faint red circle with a gold rim and
**“Searching”** slowly orbiting outside it (one turn per minute). The console
commands **`searchradius 0`** and **`searchradius 1`** hide or show this visual;
the choice is saved and does not change guard behaviour.

Pay the full writ to a settlement guard through their conversation, or yield
and follow them to the nearest local gaol to serve time. Payment and gaol clear
only that jurisdiction's debt; personal grudges remain. There are no post offices.
Murder brings a **blood writ** and a named hue and cry that reaches only nearby
watchmen. Three reported killings within a game hour put the settlement under
six hours of curfew, during which merchants bar their shutters.

Maps without authored boundaries use their existing region name as one
jurisdiction. In the editor, a **Location Marker → Watch jurisdiction** and its
**Jurisdiction radius** define another watch's territory; guards may also have
an explicit **Watch jurisdiction**. Overlapping territories use the nearest
marker. Writs, curfews and searches use the ordinary persistent game store;
old saves' single bounty migrates into the current jurisdiction.

## The living world — computed, not simulated, until it matters

Big World keeps only the region round the player resident; everything beyond is
parked, and a parked actor does not move. So the off-screen world is *data*:

* **Journeys** (`game/living/journeys.py`) — travellers on the road network are
  records: who, why, which road, since when, how fast. Position is a function
  of the clock and costs nothing between queries. Encounters between distant
  hostile parties resolve with weighted dice.
* **Materialisation** (`game/living/world.py`) — when a journey's computed
  position enters the live region, its party becomes real actors with names,
  faces, gear, dialogue and wares; the engine's AI takes over from there. When
  it drifts back out, progress, wounds and purse are written back to the
  journey and the actors are removed.
* **Roads** (`game/living/roads.py`) — the graph is built per session from the
  map's own PathNodes and location markers, with auto-linking for orphans.
* **Wildlife** roams its home while idle (near tiers only), **navigation**
  routes walkers round walls with A* over the engine's collision grid (no
  navmesh), and **map memory** remembers each map's deaths, taken pickups and
  containers, and repopulates cleared lairs about a day later — never in sight
  of the player.

## Authoring in the editor (no code, no hand-edited JSON)

Select an entity and use its **Property Manager** tabs:

* **Creature / NPC → Inventory** — add/remove item stacks, edit quantities & values.
* **Creature / NPC → Dialogue** — build branching conversations as nodes:
  `-> NODE` picks the next node, `| if …` gates an option, `| do …` runs
  actions (`start_quest`, `give`, `take`, `set`, `open_trade`, `persuade`,
  `join_guild`).
* **Quests** — the **Quest Editor** is a first-class card-based popup over the
  `.quest` files in `quests/`; the Quest Wizard builds the quest *and* its
  supporting map logic (a location Marker, a dialogue branch on the giver).
  Legacy `properties['quests']` lists are migrated on first open.
* **Simulation** — the **Live Simulation Inspector** shows what an actor knows,
  what it intends and *why* (running on the same live director the game runs),
  plus a causal event history and a Simulate Event injector.
* **Ownership & production** — per-object tabs for owner fields and producer
  fields; there is no per-object code.

Content is moddable without touching Python: `game/data/*.json` (bestiary,
factions, items, schedules, settlement) is the base, and a folder under
`game/data/mods/<name>/` with files of the same names merges over it — add a
creature, retune an item, drop in a second village.

## Architecture

```
game/
  __init__.py       GAME instance + install() + show_launcher — the native bootstrap (no PLUGIN)
  host.py           native game host: entity/IO registration, input, render.overlay HUD wiring
  runtime.py        MiniwindSession: the play session — clock, NPC AI, player combat/cast/interact verbs
  integration.py    editor-side wiring: the native "MiniWind" menu
  entities.py       the NPC/creature entities + GameSettings + Marker (reads the bestiary)
  fio.py            the only module that spells out Fio's logic-thread runtime chain
  combat_loadout.py what an actor can fight with, and which it should use now
  combat_styles.py teaches the engine's loadout which items are weapons
  held_weapons.py   who holds what, which way they face; arms fighters with a second weapon
  dual_wield.py     off-hand strikes ride the AI's shot hook
  warrior_fist.py   innate charged weapon for the Warrior
  npc_archery.py    NPCs draw bows by the player's own draw rules
  dragon_fire.py    breath weapon built from the engine's FIRE Effect pool
  facing.py         one heading convention (_facing) shared by everything that turns an actor
  faction_ai.py     MiniWind's factions as an engine HostilityModel
  world_index.py    vectorised "who is near whom", reading Big World's tier stamps
  navigation.py     A* over the engine collision grid (no navmesh)
  wildlife.py       idle roaming for near-tier creatures
  map_memory.py     what each map remembers; how lairs refill
  mental_state.py   read-only actor snapshot for the debug inspector
  death_causes.py   "Stabbed to death by Kestrel the Guard"
  quest_editor.py   card-based Quest Editor + Quest Wizard (quests/ .quest files)
  sim_editor.py     the Live Simulation Inspector windows
  editor_ui.py      Property-Manager Inventory / Dialogue / Quests tabs (Qt)
  editor_wizards.py creation wizards composed from the same authoring components
  dungeon_map.py    a dungeon grid -> the playable map built from it
  diceroll.py       headless dice service (d4–d20, modifiers, history)
  autosave.py       timed + on-discovery delta autosaves
  rewind.py         debug time-travel over a short world history
  books.py          the library (plain-text books, fiopak-packable)
  music.py          shuffled soundtrack at Fio's music volume
  console.py        MiniWind's debug-console commands
  rpg/              engine-agnostic rules: attributes, skills, races, classes,
                    birthsigns, character, items, equipment, combat, magic,
                    quests, guilds, loot, bestiary, disposition, needs, daily
                    powers, bios, heads, gib/gore — and authoring.py, the
                    dialogue condition/action grammar
  sim/              the reactive simulation: events, perception, knowledge,
                    appraisal, ownership, crime, production, director
  living/           the off-screen world: journeys, roads, materialisation
  ui/               Qt overlays: hud, screens (creation/inventory/sheet/journal/
                    spells/trade/levelup/map), dialogue, launcher, theme, book window
  data/             editable content: bestiary/factions/schedules/items/settlement
                    JSON (+ mods/ overlay). Rules stay in code, content lives here.
  tools/            world builders (make_world, expand_world, enliven_world,
                    populate_world, make_settlement, make_caves, dungeon_designer)
                    and asset makers (sprites, icons, spellbooks, tree art)
  tests/            ~65 headless test modules (pytest)
```

MiniWind is a **built-in game**, not a plugin: `host.py` defines `MiniwindGame`
(no `FioPlugin` base, no discovery, no enable/disable, no `api_version`), and
`__init__.install()` registers it on the manager's generic built-in-game surface.

The **rules live in `rpg/`** as pure data + functions; **state lives on the
`Character` and on entity `properties` dicts**, so Fio's UUID-matched serializer
persists the world for free. The Fio-facing files are a thin seam (reached
through `fio.py`); the Qt UI is isolated in `ui/`. Everything in `rpg/` and
`sim/` runs headless — see the tests.

### The seams MiniWind hooks into Fio

| Seam | Used by |
|------|---------|
| `register_builtin_game` | `__init__.install()` |
| `player_fire_handler` | attack / cast on the fire buttons |
| `_player_damage_filter` | armour/resistance mitigation before health |
| MonsterAI `_shot_hook` | `npc_archery`, `dual_wield` |
| MonsterAI steer hook | `navigation` (and chase routing) |
| `HostilityModel` | `faction_ai` |
| combat-loadout item-style resolver | `combat_styles.register()` |
| `render.overlay` | HUD, dialogue box, screens (`host.py`) |
| `gameplay_paused` | world freezes while a menu is open |
| Big World `_sim_tier` stamps | `world_index`, director tick lists |
| console-command surface | `console.py` |
| property-tab / KV-suggestion / wizard surfaces | `editor_ui`, `quest_editor`, `sim_editor`, `editor_wizards` |
| stock savegame + UUID overlay | character, quests, clock, map memory, event history |

## A total conversion

This branch turns Fio from a general-purpose FPS/level editor into a dedicated
**fantasy RPG game and editor**:

* **MiniWind is the built-in game** — installed natively at startup, not a
  plugin you switch on. The generic plugin system stays for optional gameplay.
* **No guns anywhere** — all combat is melee, archery or magic; the fire
  buttons are handed to MiniWind, which swings, looses arrows or casts.
* **The world pauses in menus** — opening character creation, the inventory,
  the journal, etc. freezes the monsters, combat, sounds and clock until you
  close it.
* **World streaming, residency and simulation tiers** come from Fio's core
  Big World plugin; a map opts in with its `BigWorldSettings` entity.

## Tests

```bash
python -m pytest game/tests -q     # everything, headless
python -m pytest game/tests -q -m "not slow"
```

All headless — no Qt/OpenGL, no display — running under the same tier markers
as the engine's own suite. The reactive simulation, the arrest flow, journeys
and the living settlement all have dedicated end-to-end modules
(`test_sim.py`, `test_arrest.py`, `test_settlement.py`, …).
