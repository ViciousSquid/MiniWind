
# <img src="https://github.com/user-attachments/assets/83dc0282-4d1f-4c2c-90f9-7fdd571cabc3f" width="200">


# A small living fantasy RPG, built on Fio

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

## Author causality, not stories

MiniWind is an **emergent storytelling** game. There is no scenario code: the
game ships small, composable systems, and the stories are what happens when
they interact. Every notable act runs through one general-purpose pipeline:

```
EVENT → PERCEPTION → INTERPRETATION → STATE CHANGE → BEHAVIOUR
```

Stab a townsperson and nothing is scripted, yet all of this can follow:

```
crime → witness → the witness walks to a guard → a charge is laid → a bounty →
arrest → the player resists → combat → death → the dead man's brother finds out →
he comes for you → the story of it spreads through the town by foot traffic
```

Every step is a general rule, which is why the *un*happy paths work too:

* murder the only witness before they reach a guard and there is no bounty
* do it at 2am, out of everyone's sight, and nobody ever knows
* sneak, and you shrink everyone's effective sight range against you
* lie low: hearsay decays daily, so a story can be outlived as well as outrun
* a rumour that reaches a guard three days later still lands the charge

The systems live in `game/sim/` and are all pure Python (no Qt, no engine):

| Module | What it is |
|--------|------------|
| `events.py` | the world event bus — every notable act, as data, with a bounded causal history |
| `perception.py` | who could have seen or heard it (distance, sight range, sleep, darkness, stealth) |
| `knowledge.py` | what each actor *believes*: facts with a certainty and a source (witnessed / heard / told), plus rumour propagation and daily decay |
| `ownership.py` | who owns a thing; what counts as theft; stolen goods stay branded |
| `crime.py` | crime severity and reporting — a bounty is what other people *do about it*, not a tax on the act |
| `appraisal.py` | how one actor interprets one fact — and a plain-English **reason** for it |
| `production.py` | objects that make other objects on a clock |
| `director.py` | the glue that runs the whole chain, and the explanation trail the editor inspects |

Nothing in there knows what a farmer, a bounty or a bucket of milk is. Add a row
to `EVENT_KINDS` or a new NPC and the entire chain applies to it for free.

### Systemic objects: the cow, not the milk quest

Millbrook ships with livestock. A cow is an ordinary Creature with two extra
data fields — `produces: milk`, `produce_every_hours: 8` — and an `owner`. That
is the whole authoring. From it:

* the cow yields a **bucket of milk**, an ordinary item, owned by the farmer
* taking it is a **theft**, which needs a witness, which produces a bounty when
  word reaches the watch, and a farmer who remembers you took it
* it can be carried, traded, given, dropped, sold and stolen back
* kill the cow and the milk stops

There is no milk quest, no milk code and no special case for milk anywhere in
the game.

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
| Perception & witnesses | per-entity `sight_range`, the top-down positions | `sim.perception`: sight vs hearing, sleep, darkness, stealth |
| Memory & knowledge | the persistent KV store, `disposition`'s per-NPC identity | `sim.knowledge`: beliefs with certainty + source, rumour spread, decay |
| Crime & bounty | `character.bounty`, the guard arrest/escort flow | `sim.crime`: a charge only exists once a witness reaches the law |
| Ownership & theft | ordinary item stacks and `properties` | `sim.ownership`: an `owner` field, and everything that follows from it |
| Production | the item DB + the `ItemPickup` entity | `sim.production`: a cow, a hen, a well — objects that make objects |
| Combat visuals | sprite billboards + projectile system | per-role attack sprite, arrows / magic bolts, red damage flash, speech bubbles |
| Save / load | Fio's UUID-matched serializer + `.fiosave` | nothing new — state lives in `properties`/KV |
| Editor UI | `register_property_tab`, typed property schemas, right-click placement | sectioned property panels, composable Inventory/Schedule/Dialogue/Loot/Quest components, creation **wizards**, "Add MiniWind Entity" submenu |
| Top-down view | overhead camera (default) + `render.overlay` | HUD, dialogue box, character/inventory screens |

## Running it

```bash
python main.py
```

After the splash, the **launcher** asks which half of MiniWind you came for:

```
                   ▓▓  MiniWind
        ────────────────────────────────────────
           Mode          Fullscreen ▾
           Resolution    1280 × 720 ▾      (Windowed only)
           The game takes over the whole screen.
           ☑ Vertical sync
           ☑ High DPI scaling
        ────────────────────────────────────────
         Reset to defaults      [ PLAY ]   [ EDIT ]
         version 2.2.0.…                       Quit
```

* **PLAY** drops straight into the game with the editor UI hidden, presented
  the way the display mode says — the existing kiosk mode.
* **EDIT** opens the editor exactly as it always did.

**Mode and resolution are the game's, not the editor's.** Play mode is presented
in the editor's own main window, so its size, position and frame are snapshotted
on the way in and restored exactly on the way out — and never written to the
editor's saved layout. Setting the game to 1280 × 720 does not resize the
editor, and quitting straight from play no longer reopens the editor at the
game's resolution. Vertical sync and high-DPI scaling are unavoidably
application-wide: Qt is told about both once, before it starts.

Everything the launcher changes is written straight back to `settings.ini` —
the same keys Settings ▸ Display and Settings ▸ Kiosk use — so the launcher and
the Settings window never disagree, and a choice made here is still there next
launch. **Reset to defaults** puts all four back. Every dimension in the
launcher is a multiple of the application font, so it scales with the OS display
scale and with the editor's own font-size setting rather than shrinking on a 4K
panel.

Turn the launcher off with `[Startup] show_launcher = False` (or the checkbox in
Settings ▸ Kiosk) to go straight to the editor as before.

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

It contains six **interconnected** townsfolk with distinct roles (blacksmith,
merchant, farmer, guard, beggar, villager), each with a persistent identity, a
home, a job, a bed, authored **relationships** (Thalen and Elowen are siblings;
Bram is Mara's brother; Kestrel courts Mara; Wick owes Thalen coin) and a daily
schedule anchored to authored **markers**; a guard who walks a real patrol
circuit; and a bandit/wolf threat east of town. In play:

```
Morning → NPCs wake → walk to work → merchant & blacksmith open → farmer works →
guard patrols the square → player talks/trades → a hostile threatens → guard fights →
combat ends → NPCs resume their lives → evening → they go home → night → they sleep
```

Actions leave a mark: an NPC's death — by the player's hand or a bandit's — is
recorded as a persistent flag in the quest store, so survivors mourn their kin
in dialogue and the town "remembers" the loss through save/load.

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

## The editor: construct the simulation, don't script it

Every system above is exposed for authoring **and observation**, live, during
Play — so a designer builds rules and watches what they produce rather than
writing what should happen.

* **NPC inspector** — the existing Properties tabs cover identity, role, faction,
  personality, courage, disposition and relationships (Appearance is a collapsed
  section inside Properties); the new **Simulation** tab adds what this actor
  *knows*, its ranked intents, and the plain-English reason behind the one it is
  acting on.
* **Object inspector** — an **Ownership & Production** tab on items, containers
  and creatures: who owns it, and what it makes.
* **Live Simulation Inspector** — click-to-inspect in play now shows a **Why**
  section and a **Knowledge** section. The explanation is produced by the
  decision itself, so it can never drift out of step with the behaviour.
* **World Event / History view** — *Tools ▸ World Simulation* (Ctrl+Shift+W):
  every significant event, expandable into the consequences it caused, with
  unreported crimes flagged.
* **Simulate Event** — inject an act (who, to whom, with what) and watch the
  world answer. It goes through the same pipeline the game uses, so what follows
  is the simulation reacting, not a preview of it.
* **Full inspection/editing during Play Mode** — every panel is live, and an
  NPC's knowledge can be edited while the game runs ("tell it about event #12",
  "wipe its memory") to see the behaviour change immediately.

From the debug console, the same surface is scriptable:

```
sim events            the world history, with the consequence each event caused
sim crimes            crimes nobody has reported to the watch yet
sim actors            every actor's current intent and the reason for it
sim why <name>        why that actor is doing what it is doing
sim knows <name>      what it believes, and how sure it is
sim tell <name> <id>  hand it a belief and watch what it decides
sim emit <kind> [actor] [target] [item]     inject an event
```

## Architecture

```
game/                     the integrated MiniWind game layer (built-in, not a plugin)
    __init__.py           GAME instance + install() bootstrap
    host.py               MiniwindGame — the native game host (registration, tick, overlay)
    integration.py        editor-side wiring: the native "MiniWind" menu
    sim/                  the reactive simulation: events, perception, knowledge,
                          ownership, crime, appraisal, production, director
    sim_editor.py         the editor's window onto it: per-entity Simulation and
                          Ownership & Production tabs, and the World Simulation
                          window (actors · history · Simulate Event)
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
python -m pytest game/tests -q            # MiniWind: 224 headless tests
python -m pytest editor/tests game/tests engine/tests plugins/bigworld/tests -q
# 339 with PyQt5 installed; 284 + 3 skipped without it (editor/tests needs Qt,
# and skips cleanly — everything else stays headless).
```

Covers the **reactive simulation** end to end (`game/tests/test_sim.py`) — that
a stabbing produces crime → witness → report → bounty without any of it being
scripted, that murdering the only witness buries the crime, that news travels by
foot traffic and lands the charge late, that a coward, a guard, a grieving
brother and the victim's rival each read the *same* murder differently, that
milking someone else's cow is a theft with no milk quest in sight, and that the
inspector's explanation matches the behaviour it caused — plus factions, game
time, schedules, inventory, dialogue, the session's
schedule movement / combat override / dialogue item-grant / persist-restore, the
living-settlement simulation (townsfolk work by day and sleep at night, walking
to their markers), the guard's authored **patrol circuit** and its recovery back
to patrol after a threat passes, faction-aware combat with separated
combat-capability and bounded civilian flee-to-refuge, **persistent settlement
consequences** (an NPC's death is recorded and survives save/load; a slain guard
leaves the town "unprotected"), **authored NPC relationships** and dialogue that
reflects a relative's death, speech-bubble cues, the editor authoring wiring
(grouped schemas + creation wizards), and the world placeables (item pickup,
quest trigger, creature spawn) — all headless, like the bigworld tests.
