# Director: the reactive simulation

`game/sim/director.py` is the coordinator for MiniWind's reactive simulation. It connects the event bus, perception, persistent NPC knowledge, appraisal, and the simulation's long-lived subsystems.

The Director is not a quest manager, dialogue author, movement controller, or encounter spawner. Its job is to turn things that have already happened into information, interpretations, and consequences. The session and the existing game AI remain responsible for making those consequences visible in the world.

For the higher-level pacing subsystem owned by the Director, see [Storyteller pacing](storyteller.md).

## Responsibilities and boundaries

The Director owns four related concerns:

1. **Event history.** It owns an `EventBus` and records serialisable `WorldEvent` objects.
2. **Reactive interpretation.** It takes an event through perception and knowledge, invalidates affected actors' cached intentions, and exposes ranked intentions to the runtime.
3. **World-time simulation.** It advances gossip, crime reporting, production and daily memory decay for actors supplied by the session.
4. **Subsystem lifecycle.** It attaches `SimSystem` instances and ticks, resets, persists and restores them alongside the event history. MiniWind attaches the Storyteller and FactionSpine here.

The `game.sim` package is designed to run without Qt, OpenGL or the Fio runtime. The Director works with actors through a small interface: an actor has a `properties` dictionary and a `pos`. Game-specific rules are injected as callables, rather than imported as hard-coded scenario dependencies.

The boundary is deliberate:

- The Director does not create scene entities. Production yields are queued and returned to the session to place.
- The Director does not move NPCs or run combat. It returns intentions; `game/runtime.py` translates the selected intention into existing movement, schedule and combat state.
- The Director does not decide what an actor ought to know from omniscient world history. Perception and stored beliefs determine that.
- A subsystem such as the Storyteller can inspect the simulation and publish policy values, but it does not become a second event or NPC-AI pipeline.

## The reactive pipeline

The central sequence is:

```text
world action
  -> WorldEvent / EventBus
  -> perception: who saw or heard it?
  -> knowledge: what fact did each observer retain?
  -> appraisal: what does each observer want to do?
  -> runtime: can that intention take control of this actor?
  -> existing movement, schedule, law or combat behaviour
```

An event is not automatically a fact for every actor, and a fact is not automatically an action. Each boundary is explicit.

### 1. Events and identity

A `WorldEvent` records an event kind, stable actor and target keys, display names, position, game day/hour, arbitrary event data, and a list of human-readable consequences. Event kinds declare semantic tags such as `violence`, `grave`, `crime`, `property`, `social`, and `notable`. Downstream systems reason from these tags and the event data.

The event bus assigns monotonically increasing IDs, retains a bounded in-memory history (400 events by default), and notifies synchronous subscribers. A failing subscriber is isolated so it cannot stop the simulation. The normal Director save stores the recent tail of the event history; the history is a diagnostic and causal log, not the sole source of truth.

The Director accepts an entity or a stable identity string for the actor and target. For entities, identity is aligned with MiniWind's NPC-memory identity through `game.rpg.disposition.mem_key`. The player uses the stable key `player` (or `player:<id>` for a player with an explicit ID). This keeps event history, NPC knowledge and player-facing disposition memory referring to the same identity.

`Director.emit()` fills in useful context where it is available: the event's position and time, its law region, actor/target faction snapshots, actor alignment, and faction-order provenance carried by the actor. It then publishes the event, invokes perception, and runs the witness callbacks. The event bus is also available to other systems through the session's injected subscribers.

Event vocabulary is data-driven. A new event kind can be registered through `game.sim.events.register_kind()` with tags, loudness, severity and a display phrase. An unknown kind still produces a valid, untagged event; it simply has no specialised downstream meaning until a consumer handles it.

### 2. Perception

`game/sim/perception.py` answers a narrow question: could this observer have perceived this event at this position and time?

- Sight requires a living, awake observer, visibility and sufficient sight range. Night reduces sight for an actor without a light source.
- Sound uses the event's loudness, so an event can be heard without being seen.
- A sleeper hears at reduced range and may wake if the sound is clear enough.
- Stealth, the Sneak skill and (for theft) sleight of hand reduce the effective sight range against the actor.
- Distance and perception mode affect certainty. Sight can produce full certainty; hearing is capped at the lower sound-certainty ceiling.

The actor who performed the event is not treated as a witness to their own action. A living victim is handled separately: the victim normally learns what happened even without being classified as an ordinary witness. A death is the exception; the dead victim does not receive a new memory.

This distinction is consequential. A scream may tell someone that violence happened without identifying the offender. A visible, sufficiently clear observation can identify the offender and support a stronger response.

### 3. Knowledge

Each observer gets an individual stored **Fact**, not a shared copy of the event log. Facts retain the information an NPC could plausibly remember: event ID and kind, identities and display names, position and time, the faction snapshot, whether it was a crime, whether the offender was identified, certainty, source and reporting state.

The source is one of:

- `witnessed` — perceived by sight;
- `heard` — perceived by sound;
- `told` — received from another actor through gossip.

Knowledge is persisted in the normal KV store under an actor-specific key. The fact store is bounded: an actor keeps at most 24 facts, and facts below the 0.12 certainty floor are discarded. Gossip loses certainty as it is retold; heard and told facts fade faster per game day than witnessed facts.

Learning is deduplicated by event ID. Hearing the same rumour repeatedly does not create an endless chain of new information; a more certain or newly identified account can improve the existing fact.

The stored faction fields are snapshots from when the event occurred. The system does not reconstruct the offender's old faction from their current one when a rumour is later appraised.

### 4. Appraisal and intentions

`game/sim/appraisal.py` interprets an actor's own facts in the context of that actor's properties and injected game rules. Inputs include relationships, courage, health, combat capability, lawful status, faction hostility, disposition and faction goodwill.

An appraisal can return an `Intent` with a reaction, priority, target, reason and source fact. The available reactions are:

| Reaction | Default priority | Meaning |
|---|---:|---|
| `FIGHT` | 100 | Attack an identified offender or hostile threat |
| `ARREST` | 95 | A lawful actor acts on an identified, unresolved crime |
| `FLEE` | 90 | Escape a personal or nearby threat |
| `CONFRONT` | 80 | Approach someone over a personal property offence |
| `REPORT` | 75 | Carry an offence or disturbance to the watch |
| `INVESTIGATE` | 70 | Move towards a disturbance whose culprit is unknown |
| `MOURN` | 45 | React to the death of someone close |
| `WARM` | 15 | Remember a kindness towards the actor or someone close |
| `IGNORE` | 0 | Retain an explicit non-response |

These are appraisal priorities, not a promise that every reaction immediately controls the actor. The session has its own precedence rules for urgent combat, arrest and survival behaviour. The runtime then decides whether the current top intention can claim that decision tick.

Appraisal is per observer. The same witnessed death can make a sibling fight, a guard arrest, a frightened civilian flee, and a rival ignore it. The system does not need a scenario-specific branch for each of those characters.

Every intention includes a plain-English reason. The reason is generated alongside the decision and is exposed to the Live Simulation Inspector, so the explanation describes the actual appraisal rather than a separately maintained guess.

### 5. Runtime execution

The Director supplies the decision; the runtime supplies the physical behaviour.

In `game/runtime.py`, `_apply_sim_intent()` obtains the actor's current top intention and translates supported reactions into existing game state:

- `REPORT` uses the witness/reporting movement path.
- `INVESTIGATE` sends the actor towards the remembered event position.
- `FIGHT` and `ARREST` hand an eligible offender to the existing combat/guard path.
- `FLEE` parks combat behaviour and assigns a refuge destination.
- `CONFRONT` sends an eligible actor towards the offender, or towards reporting when the personal offence is still unresolved.
- `MOURN`, `WARM` and `IGNORE` remain meaningful social or inspector state but do not by themselves take over physical movement.

The main NPC decision order gives immediate combat, arrest and threat response precedence. When those urgent conditions do not claim the tick, a reactive simulation intention is considered before ordinary companionship and daily schedule behaviour. A traveller whose party is controlled by the living-world system is handled by that system instead of the ordinary NPC schedule path.

This is why the Director can remain engine-agnostic: it does not implement a second mover or combat engine.

## Secondary simulation work

The Director also advances systems that operate on world time rather than on every rendered frame.

### Gossip

Gossip is proximity-based. Actors who are awake and within 220 world units can exchange knowledge. A pass runs every 0.5 game-hours and is capped at six successful exchanges, preventing a crowded settlement from producing unbounded work in one pass.

The speaker and listener can each pass a fact to the other. A genuinely new fact dirties the receiving actor's intention cache and can update disposition. Gossip is therefore a physical information network: actors must meet, information loses certainty, and a rumour can stop when its carriers die or forget it.

### Crime reporting

Reporting has two routes:

1. An ordinary witness with an unreported crime can tell a nearby lawful actor within the 260-unit tell radius. The witness must physically reach that actor; a sleeping lawful actor can be woken by the messenger.
2. A lawful actor who already knows a sufficiently certain, identified crime can report it directly.

The crime module deduplicates reporting by event ID. Ten witnesses to one offence do not create ten charges. The session receives the bounty callback and owns the actual regional writ and player-bounty changes.

A crime event by itself does not automatically create a bounty. Somebody with an adequate account has to report it to the law. This is the mechanism behind delayed consequences and crimes that remain undiscovered.

### Production and memory decay

Producing actors are advanced by their own last-simulated timestamp. The Director queues the resulting yields; the session drains that queue and places ordinary world items, preserving their ownership.

At a day boundary, the Director advances knowledge decay using each actor's last-decayed day. A parked actor catches up on elapsed decay when it next re-enters a simulated tier.

## Time, residency and workload

The session's `_tick_sim()` converts the game clock into elapsed game-hours and calls `Director.tick()` when at least 0.01 game-hours have accumulated. It is not a per-rendered-frame story timer.

The Director receives two actor collections from the session:

| Simulation tier | Director treatment |
|---|---|
| Near / active | Full reactive pass on each Director tick; gossip on its 0.5-hour cadence, reporting and production |
| Distant | Coarse pass when its accumulated interval reaches 1.0 game-hour; gossip, reporting and production cover that interval |
| Dormant / parked | Not included in the pass; production and memory decay catch up from per-actor timestamps when visited again |

The Director filters dead actors from these passes. The session owns tier selection and supplies the actor lists; the Director does not query the renderer or independently scan the whole world.

For larger crowds, proximity candidate generation switches from a simple nested loop to block-wise NumPy distance tests at 48 actors. Candidate pairs are still confirmed with the scalar distance rule, and gossip has its independent six-exchange budget. These are workload controls; they do not change the knowledge rules.

## Intent caching and read-only queries

Appraisal can be a repeated operation, so the Director keeps ranked intentions by stable actor key.

- `intents(actor)` returns the actor's cached intentions, recomputing when the actor is dirty, has no cached entry, the mood context has changed, or the caller explicitly requests refresh.
- `top_intent(actor)` returns the first ranked intention.
- `why(actor)` returns the plain-English explanation of the ranked result.
- `evaluate(actor)` is a read-only appraisal. It does not write the actor's identity cache or populate the Director's intention cache.
- `cached_intents(key)` returns only a clean, already-computed result. It returns `None` when the result is absent or stale; it never appraises as a side effect.
- `invalidate(actor)` marks one actor for reconsideration. `invalidate()` clears all cached decisions.

The read-only methods matter to systems such as the Storyteller. Sampling or inspecting an actor must not silently create an intention, clear a dirty flag or change the next gameplay decision.

## Subsystems and lifecycle

A `SimSystem` is a long-lived simulation subsystem with a unique `name` and optional `reset()`, `tick(now)`, `persist()` and `restore()` methods. The Director owns attached systems in attachment order.

The Director's lifecycle is:

- **Attach:** `attach(system)` registers a unique subsystem name and returns the same instance.
- **Tick:** after gossip, reporting, production and day-boundary memory decay, each attached subsystem receives absolute game time: `day * 24 + hour`.
- **Reset:** clears the event bus and intention state, then resets every attached subsystem.
- **Persist:** saves the event history, then calls each subsystem's `persist()`.
- **Restore:** loads event history first, then restores each subsystem in attachment order. A subsystem can therefore consult restored history during its own restore.

In MiniWind's session, the Storyteller is attached first and the FactionSpine alongside it. The session also injects the faction hostility and disposition functions, faction mood context, and fact reader into the Director's appraisal context.

## Persistence

The event history is stored under `sim.history`. Individual facts, crime-report markers and disposition memories live in their own KV entries. The Director persists its attached subsystems through the same lifecycle, including the Storyteller's `storyteller.state` snapshot and the faction subsystem's state.

The event log is intentionally bounded. When an old event leaves the log, its consequences can remain in durable facts, disposition, reporting state and other subsystem records. The log is useful for causal inspection, not an unlimited archive or the canonical owner of every world fact.

## Developer-facing inspection

The Live Simulation Inspector reads an actor's knowledge, ranked intentions and reasons, alongside the causal event history. `Director.knowledge_lines()` provides a compact knowledge summary; `report_lines()` provides the event-history text representation. Event consequences are appended to the event itself by the systems that react to it.

The Storyteller Studio is a separate inspection surface for pacing state, sampled sensors, lever values and world-level journey explanations. Opening these views is intended to inspect existing state, not to advance the simulation.

## Tests

The headless mechanism tests cover the pipeline and its composition without requiring a running game window:

```sh
python -m pytest game/tests/test_sim.py -q
python -m pytest game/tests/test_sim_hot_paths.py game/tests/test_sim_residency.py game/tests/test_sim_tiers.py game/tests/test_sim_systems.py -q
```

The Storyteller's sampler, lever consumers and Studio have their own suite:

```sh
python -m pytest game/tests/test_storyteller.py game/tests/test_storyteller_window.py -q
```

Related implementation:

- [Director](../game/sim/director.py)
- [Event bus and event vocabulary](../game/sim/events.py)
- [Perception](../game/sim/perception.py)
- [Knowledge](../game/sim/knowledge.py)
- [Appraisal](../game/sim/appraisal.py)
- [Crime and reporting](../game/sim/crime.py)
- [Simulation subsystem contract](../game/sim/system.py)
- [Storyteller pacing](storyteller.md)
- [Faction simulation](factions.md)

## Reusable world scenarios

Dynamic encounter implementations are separate from the pacing controller.
`game/living/scenario_modules/` contains the eight reusable encounter
modules; the Director schedules them in Dynamic mode, while other systems can
invoke the same implementations directly. See [Reusable world-scenario modules](scenario_modules.md)
for the module contract, context boundary, invocation example and extension steps.
