# MiniWind → Fio 2.5.10 migration record

Status: **Migration completed and merged into main.**

Merge commit: c56184506a — Merge pull request #17 from ViciousSquid/claude/jolly-goldberg-uybdqw

This document records what the 2.4 → 2.5 migration actually delivered. It replaces the earlier archaeology/migration plan, which is now obsolete.

---

## 1. Migration outcome

MiniWind is now a **native game layer on Fio 2.5**, rather than a 2.4-derived engine fork with a game attached to it.

The migration preserved MiniWind's authored world and game systems while moving the engine-facing parts onto Fio 2.5's current seams:

- Fio owns rendering, EntityTable, terrain, spatial partitioning, save/load, BigWorld residency, camera, collision, lighting and dense Monster AI.
- MiniWind owns game meaning: factions, actor presentation policy, combat loadouts, schedules, perception, knowledge, crime, appraisal, quests, production, director/event flow and game UI.
- Actor rendering crosses the engine boundary through journalled state and dense tables rather than MiniWind-specific per-actor OpenGL draw loops.
- The simulation layer in game/sim/ remains engine-independent and is organised around EVENT → PERCEPTION → INTERPRETATION → STATE CHANGE → BEHAVIOUR.

This is the intended Fio 2.5 architecture: **Fio provides the world machine; MiniWind supplies the world rules.**

---

## 2. Version provenance

| Stage | Fio version / ref | Result |
|---|---|---|
| Original MiniWind substrate | Fio 24a2757e, 2026-09-16 | 2.4-derived starting point |
| Migration work | Fio 2.5.x, ending at 2.5.10.3009_Latest | engine migration and seam work |
| Merged MiniWind | Fio 2.5.10.3009 | current MiniWind main |
| Merge | c56184506a | PR #17 merged into main |

The migration therefore represents a real architectural break from the old 2.4 substrate, not a compatibility layer around the old renderer.

The copy of Fio embedded in MiniWind is **not automatically the latest Fio after this merge**. Current upstream Fio has continued beyond the 2.5.10.3009 snapshot; updating MiniWind to later upstream 2.5.10 changes is a separate synchronisation task, not part of the historical migration itself.

---

## 3. What was migrated

### 3.1 LogicThread / game lifecycle

MiniWind-specific gameplay now attaches through explicit engine seams rather than forking the simulation loop.

Migrated capabilities include:

- game-session attachment and lifecycle
- gameplay pause state
- player damage filtering
- player fire / secondary-fire dispatch
- aim state publication
- projectile callbacks and published projectile state
- game start/tick/stop integration through Fio's builtin-game/plugin lifecycle

The important architectural change is that **Fio owns the tick loop**. MiniWind hooks into it; it does not replace it.

### 3.2 Monster AI

MiniWind's combat behaviour was re-attached to Fio's dense Monster AI rather than restoring the old 2.4 actor-draw / AI architecture.

The migration added an application-level combat policy hook:

- Fio remains responsible for dense enemy selection and MonsterTable processing.
- MiniWind supplies authored attack style/loadout policy.
- Combat loadouts determine melee/ranged/spell behaviour without moving the dense AI loop into game/.
- Game-specific damage policy can be supplied at the application seam while Fio retains the default fallback behaviour.

The attack-style hook is installed by the game host when play starts.

One lifecycle follow-up remains: the class-level engine hook should have a symmetric uninstall/clear operation when play stops, so repeated play sessions cannot retain stale game policy.

### 3.3 Actor simulation

The previous monolithic gameplay additions were split into domain systems under game/sim/.

Current responsibilities include:

- events.py — event production
- perception.py — sensory interpretation
- knowledge.py — certainty, sources, gossip decay and reporting
- crime.py — crime and consequence state
- appraisal.py — appraisal / interpretation
- production.py — production/economic behaviour
- director.py — generic orchestration and explanation trail

The resulting system is deliberately independent of Fio's renderer and Qt layer.

NPC simulation also has explicit distance tiers:

- **NEAR** — full decisions and movement
- **ACTIVE** — reduced/staggered decision cadence
- **DISTANT** — coarse schedule/clock behaviour
- **DORMANT** — parked state

BigWorld remains the authority for spatial relevance.

### 3.4 BigWorld and overhead play

MiniWind's overhead mode is now integrated with Fio BigWorld rather than using a separate world-size mechanism.

The migrated path includes:

- overhead camera fitting
- residency sized from the visible overhead footprint
- sim_tiers_fit_view publication by BigWorld
- reduced ACTIVE simulation cadence when actors are outside the fitted overhead view
- terrain streaming within the authored world
- parked monsters excluded from active AI processing
- large authored terrain/world expansion without reverting to the old hard-distance gameplay cutoff

This is the basis for MiniWind acting as a real large-world test of Fio's BigWorld architecture.

### 3.5 Rendering / EntityTable migration

The most important renderer change was replacing MiniWind's old per-NPC OpenGL presentation path.

The old model:

> iterate actors → issue Python-side draw work per actor

is no longer the intended path.

The migrated model is:

> authored/game state → journalled attributes → EntityTable / dense render state → instanced sprite rendering

The migration retained:

- actor heading
- render opacity / fade
- dead identity
- overhead presentation
- actor-held weapon presentation requirements
- ground/render layering requirements

Where Fio already had a journalled render attribute, MiniWind uses it rather than creating a parallel render-state system.

### 3.6 Overhead camera / player representation

MiniWind's overhead gameplay was brought onto the 2.5 camera path rather than keeping its earlier specialised draw architecture.

The migrated game-side behaviour includes:

- top-down NPC presentation
- player overhead presentation
- mouse-control / pointer aiming
- projectile orientation from published velocity
- game-specific player/weapon presentation
- cross-cursor interaction
- overhead-compatible AI scheduling

Fio's normal first-person camera remains intact.

### 3.7 Editor and plugin integration

MiniWind-specific editor behaviour was moved behind Fio 2.5 plugin/API seams.

The migration retained game-specific needs such as:

- entity presentation rules
- property/editor metadata
- inspector providers
- game console commands
- mandatory BigWorld configuration
- game launcher/UI integration
- game-owned settings

Fio's generic editor/plugin APIs remain the implementation boundary instead of MiniWind carrying a permanent editor fork.

### 3.8 Save/load and authored world

The authored MiniWind world remains game content, not engine code.

The migrated world includes:

- the expanded terrain/world
- NPCs, creatures, markers, lights, containers and pickups
- schedules/quests/game data
- BigWorld settings
- LogicState/global game state

Unknown entity types continue to round-trip through Fio's unresolved-entity path, rather than requiring MiniWind to own another save/load fork.

Derived presentation state such as dead-sprite identity must remain derived and must not become authored map data.

---

## 4. What was deliberately removed or superseded

The migration explicitly discarded the 2.4-era approaches that no longer fit Fio 2.5:

- old renderer/draw paths
- MiniWind's per-NPC OpenGL draw loop
- renderer-side MiniWind snapshot plumbing
- duplicate sprite shader mechanisms where EntityTable already provides the state
- old LogicKeyValueStore architecture
- engine-owned game policy that belongs in game/
- unnecessary duplication of Fio systems which already exist upstream

The rule throughout the migration was:

> **Do not preserve a 2.4 mechanism merely because it existed in MiniWind.**

Where Fio 2.5 already supplied the capability, MiniWind moved to the upstream implementation.

---

## 5. Game systems now owned by MiniWind

The following remain intentionally outside generic Fio:

- faction relationships and social semantics
- actor appearance policy
- combat loadouts and attack-style policy
- schedules and daily routines
- perception / knowledge / gossip
- crime and consequences
- appraisal and behavioural interpretation
- production/economic behaviour
- quests and world-specific progression
- game UI and game launcher behaviour

These are not engine features that need to be upstreamed merely because MiniWind uses them.

---

## 6. Architectural decisions recorded by the migration

### Dense data remains the engine boundary

Fio's high-frequency systems continue to operate on dense numeric data. MiniWind does not reintroduce Python object traversal into the render/AI hot path merely to make the game layer convenient.

### Domain logic remains ordinary game code

The game/sim/ layer is allowed to be expressive and object-oriented where that makes the game model clear. It is not part of the renderer's dense numerical core.

### BigWorld owns relevance

World scale and actor residency are not solved by another MiniWind-specific global distance cutoff. Spatial relevance belongs to Fio BigWorld and its residency tiers.

### MiniWind is not a second engine

MiniWind deliberately depends on Fio for the world machine. It adds game semantics and content; it does not recreate Fio's renderer, terrain, spatial system, or simulation infrastructure.

---

## 7. Known post-migration follow-ups

These are **follow-ups after the migration**, not reasons to consider the migration incomplete.

### Faction-aware dense Monster AI

MiniWind installs logic._faction_hostile, but the dense MonsterAI targeting path currently still derives hostility from MonsterTable team differences. The intended next step is a dense team-relation representation (for example a boolean relation matrix plus a player-hunting mask) rather than a per-pair Python callback.

### Combat-hook lifecycle

game/combat_loadout.py installs the MonsterAI attack-style hook at play start. A matching uninstall/clear path should be added at play stop.

### BigWorld-aware reactive simulation population

The current MiniWind director population can still include live actors broadly. As world scale increases, reactive simulation should be made explicitly tier-aware: interactive NEAR/ACTIVE actors, coarse DISTANT state progression, and persisted DORMANT state.

### Actor identity

Death bookkeeping still has some name-based state. Stable UUIDs should be used for runtime identity and persistence wherever possible.

### WorldIndex duplication

WorldIndex and Fio's MonsterTable both maintain dense actor/query information. This is not automatically a bug. Consolidation should only happen if profiling shows that the duplication is material.

### Upstream Fio synchronisation

MiniWind's embedded Fio snapshot should be reviewed against subsequent Fio 2.5.10 changes. In particular, newer upstream overhead/relevance plumbing has moved beyond MiniWind's sim_tiers_fit_view snapshot.

This should be handled as a normal upstream sync, with MiniWind-specific seams preserved—not by reopening the 2.4 migration.

---

## 8. Documentation state after migration

This file is the **historical migration record**.

It is no longer a work plan and should not contain instructions such as:

- "replace the engine"
- "Phase 1 archaeology"
- "no engine code changed yet"
- "future migration phases"

Future work should be recorded as normal maintenance/synchronisation/audit work against the completed Fio 2.5 architecture.

---

## 9. Final state

The 2.4 → 2.5 MiniWind migration is **complete** as represented by the merged main branch at c56184506a.

The important result is not merely that the code runs on Fio 2.5.10. It is that MiniWind now exercises the architecture in the way Fio 2.5 was intended to work:

**Fio owns the world machinery; MiniWind owns the world.**
