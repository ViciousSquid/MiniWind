# Miniwind — a first-party fantasy RPG for Fio

**Miniwind** is a complete, top-down, open-world fantasy role-playing game built
on Fio, set in its own world, the **Vale of Miniwind**. It draws on the broad
well of fantasy RPGs — the learn-by-doing progression of the Elder Scrolls, the
grounded factions and reputation of *Gothic*, the coloured loot rarity of
*Diablo*-style ARPGs, and the attributes-and-skills backbone of tabletop D&D —
recast as its own setting rather than a copy of any one of them.

It began as a small plugin "taste" of what Fio could host; this is the full game:
character creation, a deep skill/attribute system that improves through use,
melee & archery & magic combat, quests, guilds, an economy, schedules and a
living day/night world.

Fio is treated here as the **engine powering a total conversion** — a first-party
title, not an optional plugin. It ships enabled and is the canonical
demonstration that Fio can drive an entire RPG.

> **No guns.** Miniwind is a sword-and-sorcery world. The engine's combat was
> extended so creatures and NPCs fight with **melee** or **bows & arrows** — never
> firearms. See *Engine changes* below.

## Play it

```bash
python -m game.tools.make_world   # -> maps/Miniwind.json
python main.py                                # open maps/Miniwind.json, press Play
```

You spawn into character creation, then into the village of Miniwind. Talk to
the townsfolk for work, buy gear from Borin the smith and Elowen the trader,
then head out to clear the bandits from the Old Mill, cull the wolves troubling
Bryn's flock, or brave the skeleton barrow to earn your place in the Fighters
Guild.

### Controls (top-down)

| Key | Action | Key | Action |
|-----|--------|-----|--------|
| **WASD** | Move | **E** (use) | Talk / interact |
| **F** / Space | Attack (melee swing / loose an arrow) | **R** | Cast active spell |
| **X** | Cycle active spell | **B** (hold) | Block |
| **V** | Toggle sneak | **H** | Quick-drink a healing potion |
| **I** | Inventory & equipment | **C** | Character sheet |
| **J** | Quest journal | **P** | Spellbook |
| **L** | Level up (when available) | **1–9 / Esc** | Dialogue choices / close |

## What's in the game

| System | Summary |
|--------|---------|
| **Character creation** | 10 races (each with attribute/skill bonuses, resistances and a daily power), 13 classes, 10 birthsigns, or your own custom class. |
| **8 attributes** | Strength, Endurance, Agility, Speed, Intelligence, Willpower, Personality, Luck — driving every derived stat and roll. |
| **20 skills, leveled by use** | Blade, Blunt, Marksman, Block, Heavy/Light Armor, Destruction, Restoration, Alteration, Conjuration, Illusion, Mysticism, Alchemy, Sneak, Security, Mercantile, Speechcraft, Acrobatics, Athletics, Light Fingers. Doing raises them; raising *major* skills levels you up. |
| **Derived pools** | Health, Magicka and Stamina, recomputed from attributes; passive magicka/stamina regen. |
| **Combat** | Melee (Strength + weapon skill), archery (draw + ammo), spells; hit chance, criticals, sneak attacks (×6 with a dagger), blocking, armour mitigation and elemental resistance. |
| **Magic** | 30+ spells across six schools, magicka cost that falls with skill, self/touch/target/projectile delivery, summons and bound weapons. |
| **Items & equipment** | Weapons, armour (heavy/light by slot & material), ammunition, potions, ingredients, books, keys and gold; encumbrance from Strength. |
| **Loot rarity** | Dropped gear can roll **Fine / Rare / Fabled** tiers (ARPG-style) — worth more, tinted in the UI, and hitting/protecting harder. |
| **Quests & journal** | Multi-stage quests with objectives, a journal, and quest state stored in the persistent KV store (visible to map logic). |
| **Guilds & reputation** | Joinable guilds with rank ladders, reputation-driven promotion, NPC disposition, persuasion, and a crime bounty. |
| **Economy** | Merchants with stock and gold; buy/sell prices set by Mercantile + Personality. |
| **World** | A game clock with day/night, Radiant-AI-lite NPC schedules (home → work → sleep), factions and combat that resolve from the world state. |
| **Save / load** | The whole character (stats, skills, inventory, equipment, spells, guild standing) plus quests and the clock round-trip through Fio's stock save system — no new format. |

## Authoring in the editor (no code, no hand-edited JSON)

Select an entity in Fio and use its **Property Manager** tabs:

* **Creature / NPC → Inventory** — add/remove item stacks, edit quantities & values.
* **Creature / NPC → Dialogue** — build a branching conversation as nodes. Each
  response is one line:

  ```
  I'm looking for work. -> quest | if quest.mill.state != active | do start_quest mill
  I'll take the blade.  -> END   | do give iron_longsword,1 ; complete_quest mill
  Goodbye.              -> END
  ```

  `-> NODE` picks the next node (`END` closes). `| if …` gates the option
  (`key == value`, `key != value`, `has item_id`, `lacks item_id`). `| do …`
  runs actions (`start_quest`, `complete_quest`, `advance_quest`, `give item,qty`,
  `take item,qty`, `set key=value`, `open_trade`, `persuade`, `join_guild id`).
  A node can also run actions **on enter**.

* **Miniwind Game Settings → Quests** — create whole quests: id, name, giver,
  faction, XP, gold/item/reputation rewards, and a staged journal (each stage a
  line: `index | journal text | objective | finishes`). These load at play start
  and can add to — or replace — the built-in quests, all from the editor.

The dialogue/quest data is stored on the entities' `properties`, so it saves with
the map and round-trips through Fio's serializer like everything else.

## Architecture

```
game/
  __init__.py       GAME instance + install() — the native bootstrap (no PLUGIN)
  host.py           native game host: entity/IO registration, input, overlay wiring
  integration.py    editor-side wiring: the native "MiniWind" menu
  entities.py       the NPC/creature entity + GameSettings + Marker (reads the bestiary)
  runtime.py        the play session: NPC AI, player combat/cast/interact verbs
  editor_ui.py      Property-Manager Inventory / Dialogue / Quests tabs (Qt)
  rpg/              THE GAME (pure Python, engine-agnostic, fully unit-tested)
    attributes, skills, races, classes, birthsigns, character, (leveling in character)
    items, equipment, combat, magic, quests, quests_content, guilds, loot, bestiary
    authoring.py    the dialogue condition/action grammar (editor <-> runtime)
    inventory, dialogue, gametime, schedule, factions   (shared pure systems)
    game_state.py   the player-facing controller that ties it together
  ui/               Qt overlays: hud, screens (creation/inventory/sheet/journal/
                    spells/trade/levelup), dialogue_ui, theme
  data/             editable game content: bestiary/factions/schedules/items/settlement
                    JSON (+ mods/ overlay). Rules stay in code, content lives here.
  tools/            make_settlement.py (the living settlement), make_world.py, make_sprites.py
  tests/            test_rpg.py, test_miniwind.py, test_settlement.py
```

MiniWind is a **built-in game**, not a plugin: `host.py` defines `MiniwindGame`
(no `FioPlugin` base, no discovery, no enable/disable, no `api_version`), and
`__init__.install()` registers it on the manager's generic built-in-game surface.

The **rules live in `rpg/`** as pure data + functions; **state lives on the
`Character` and on entity `properties` dicts**, so Fio's UUID-matched serializer
persists the world for free. The Fio-facing files are a thin seam; the Qt UI is
isolated in `ui/`. Everything in `rpg/` runs headless — see the tests.

## A total conversion

This branch turns Fio from a general-purpose FPS/level editor into a dedicated
**fantasy RPG game and editor**. Fio is the technology underneath, but the
first-person, gun-based defaults are gone:

* **MiniWind is the built-in game** — it is installed natively at startup (not a
  plugin you switch on). The generic plugin system stays: **BigWorld remains an
  optional Fio plugin**, disabled by default, demonstrating the plugin API.
* **No guns anywhere** — the gun weapon tables are emptied, the player's hitscan
  shooting path is inert, the gun/cigarette HUD art is deleted, and legacy
  monster attack sounds point at the fantasy melee/bow sounds. All combat is
  melee, archery or magic.
* **No demo content** — Fio's ~20 example maps and the **random / procedural map
  generator** (menu item, widget and CLI tools) are removed. The shipped map is
  `maps/Miniwind.json`, regenerated by `make_world` from a **bundled** terrain
  base, so the game is self-contained.
* **The world pauses in menus** — opening character creation, the inventory,
  journal, etc. freezes the monsters, combat, sounds and clock until you close
  it (nothing fights behind the character-creation screen any more).

### Engine changes

1. **Fantasy combat** (`engine/monster_ai.py`, `monster_constants.py`) — monsters
   read an `attack_style` of `melee` (strike at close range) or `bow` (loose an
   **arrow** projectile). No hitscan bullets, no gunshot sounds.
2. **RPG damage mitigation** (`engine/logic_thread.py`) — an optional
   `_player_damage_filter` turns raw incoming damage into a post-armour/-resistance
   amount before health is reduced.
3. **World pause** (`engine/logic_thread.py`, `engine/monster_ai.py`) — a
   `gameplay_paused` flag freezes the world while a menu is open without stopping
   the plugin tick that drives the menu.
4. **HUD suppression** (`engine/qt_game_view.py`) — the game suppresses the stock
   health/weapon HUD (`_suppress_default_hud`) and draws its own via `render.overlay`.
5. New fantasy assets: `assets/sounds/{melee,bow}.wav`, `assets/sprites/monsters/arrow.png`.

## Tests

```bash
python -m game.tests.test_rpg        # RPG core + authoring (26 tests)
python -m game.tests.test_miniwind   # systems + session (12 tests)
# or:  python -m pytest game/tests -q
```

All headless — no Qt/OpenGL — like the `plugins/bigworld` tests.
