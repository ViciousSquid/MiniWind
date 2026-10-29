# Changes

## Storyteller as a first-class simulation subsystem

- Move the storyteller into the reactive simulation as `game/sim/storyteller.py`.
  It is now a `game.sim.SimSystem` (new `game/sim/system.py`). The faction
  spine is one too.
- The `Director` owns attached subsystems: `attach()`/`system()`, a tick after
  each pipeline pass at absolute world hours, and `persist()`/`restore()`/`reset()`
  that cover the event history first and then each subsystem in attachment order.
  The session no longer ticks, saves, loads or resets the storyteller and faction
  spine one by one, and no longer ticks pacing from the frame loop.
- Add `Director.cached_intents()`, a read-only view of decided intents. The
  storyteller no longer reads the director's private `_intents`/`_dirty`.
  Board hooks ask `Storyteller.player_town()` instead of reaching into its hooks.
- No snapshot schema changes: `storyteller.state` stays at schema 3 and
  `factions.state` at schema 1.
- New `game/tests/test_sim_systems.py` covers tick order and world time, unique
  names, lifecycle order, intent reads that never appraise, session wiring, and
  new-game reset.

Validation: full headless suite on clean `2dfaf1b`: 4,251 passed, 34 skipped,
1,974 deselected, and the five failures that were already failing (listed in
`docs/factions.md`). With this change: 4,260 passed, the same skips,
deselections and five failures. The extra 9 are the 6 new tests plus 3
suite-integrity checks that cover the new test file automatically.

## Cache faction projections per board update

- Restore `Director.intents()` caching with a mood provider. Board-update and
  knowledge revisions refresh dependent intentions without forcing every query
  to appraise again. Ordinary movement does not invalidate the shared mood sample.
- Parse each unchanged holder's facts once per board update, project market
  traffic once, and reuse one goodwill ledger per faction and one mood per
  resident. Dirty knowledge immediately invalidates dependent projections even
  after an actor consumes its dirty flag. Read-only queries leave knowledge,
  ordinary intent caches, dirty flags, snapshots and RNG unchanged.
- Rebind only living faction/home pairs from the current scene, preserving
  historical facts without counting stale homes toward current goodwill. Hourly
  communication skips unchanged member accounts and re-tells only changed facts.
- Keep all caches transient across bind/reset/restore. Document coarse leader
  attribution for abstract kills and contact-dependent raid resolution through
  the existing road encounters and destination rest/loiter period.

Validation:

- Clean baseline `32e76b2`: 4,237 passed, 34 skipped, 1,974 deselected, five
  pre-existing failures. Full headless: 4,251 passed with the same skips,
  deselections and five failures; no tests weakened or disabled.
- Focused cache/faction/simulation/storyteller/Studio/Karma run: 194 passed.
  Eleven new work-count and invalidation pins also add three automatic suite
  integrity checks. The selected baseline node set is retained in full.
- Same five failures: backport import boundary, repeated-assault aggression,
  container lock difficulty enum, Ember Tome site spacing, missing inventory
  icon archive manifest. Commands and full names are in `docs/factions.md`.
- Python compilation and `git diff --check` passed. Interactive play and OpenGL
  were not exercised.

## Faction spine and world-priced drama

- Preserve the existing actor-faction knowledge repair and extend the fact
  snapshots with target faction and existing Karma. Pin identified fight/flee
  appraisal through perception, gossip and restore.
- Add local faction actors with goodwill derived solely from deduplicated known
  crimes, heals/rescues, gifts and trades. Every contribution retains a holder
  and source fact. Karma remains the existing good/evil system and creates no
  hidden goodwill or testimony.
- Route justified faction orders through JourneyBoard from real homes using
  actual resident combatants, physical travel and return legs. Preserve social
  identity, possessions and wounds; returning survivors share actual combat
  facts. Expose causal receipts in the existing inspector and Studio.
- Sample prosperity, notoriety and legend from current world state. Prosperity
  prices existing legal bandit destinations; notoriety lowers the hunter
  threshold while bounty/news gates remain. The storyteller gains no authoring
  powers. Evaluate resident moods as pure touchpoint projections using existing
  appraisal and Karma functions, with no new off-screen needs simulation.
- Bump storyteller snapshots to schema 3 and add version-1 faction snapshots.
  Preserve effective pricing, active causes and discharged orders exactly.
  Extend pristine-day byte/RNG parity and read-only mechanism pins. Player hold
  as a board town remains deferred. See [docs/factions.md](docs/factions.md).

Validation (no tests weakened, disabled or newly skipped):

- Clean baseline at current main `1bc5085`: 4,204 passed, 34 skipped, 1,974
  deselected; five pre-existing failures. The initial `1490d1d` baseline also
  had those five failures (4,189 passed). Upstream controller/camera changes
  are retained by rebasing onto current main.
- Full headless suite: 4,237 passed, 34 skipped, 1,974 deselected; the same five
  failures. Both runs use `FIO_HEADLESS_TIER=1` and exclude `qt`, `gl`, `benchmark`.
- Focused faction/simulation/storyteller/Studio/Karma run: 183 passed.
- Unchanged failures: backport import boundary (`tools/benchmark_navigation.py`),
  repeated-assault aggression restoration, container lock difficulty enum,
  Ember Tome site spacing (3982.84), and absent inventory icon archive manifest.
  Exact test names and commands are in `docs/factions.md`.
- Python compilation and `git diff --check` passed. Interactive play and OpenGL
  rendering were not exercised.

## Gamepad Statistics shortcut

- Y opens Statistics directly on the Character sheet. LB/RB change tabs;
  B or Y closes the window. Reopening starts on Character again.

## Gamepad navigation and camera orbit

- D-pad left/right highlights quickbar items; A equips, consumes or uses the
  selection. Nearby talk/open/loot prompts still work with A.
- Conversations support D-pad up/down, A to select, and B to leave. Inventory
  supports D-pad focus, A pick/place, LB/RB tabs, and B to close.
- Analog walking faces the direction of travel independently of camera orbit.
  LT/RT use the corresponding physical hand; a shield trigger holds block.
- Right-stick camera pitch is limited to ±5° from the configured view, with
  physical elevation limits respected. Vertical stick input still scrolls menus.
- The minimap, markers and player arrow follow camera heading. The upright
  north indicator trails turns with gentle liquid-compass damping.
  Camera orbit survives save/load. Hold `[` / `]` to rotate left / right.
  Set `[GAME] camera_rotation = False` in `settings.ini` to disable both
  bracket-key and right-stick rotation during play; rotation defaults to on.


## Faction-aware threat appraisal

- Preserve the event's `actor_faction` snapshot when creating a knowledge fact.
  Storage and gossip now carry it into appraisal, enabling the existing enemy
  threat branch to choose fighting or fleeing from perceived violence. Crime
  reporting and arrest retain their precedence, and reasons come from appraisal.
- Faction threats require an identified offender; sound-only accounts cannot
  start a targeted fight. A clearer eyewitness account can upgrade the belief.
  Legacy facts without a faction remain unknown rather than being backfilled
  from an actor's current faction. No additional randomness is consumed.
- Validation: 134 focused simulation/storyteller tests passed; the full headless
  suite reports 4,189 passed, 34 skipped and the same five pre-existing failures
  listed below.

## Quieter storyteller receipts

- Record journey outcomes for storyteller-biased destination choices and actual
  materialisations. Routine authored planning no longer replaces the inspector's
  latest outcome or fills the bounded receipt history. Neutral memory weights
  produce no planning receipt. All actual arrivals remain visible.
- Match inherited arrival causes to the journey leg, including resting arrivals,
  so suppressing ordinary planning cannot misattribute an earlier leg's crime.
  Pins cover busy planning, RNG parity, save/load and causal leg matching.
- Validation: 111 focused tests passed; the full headless suite reports 4,179
  passed, 34 skipped and the same five pre-existing failures listed below.

## Storyteller pacing and Studio

- Eligible clean, undischarged kin vendettas can draw an ordinary resident
  market trip toward the healthy player's town, within the configured distance.
  Trips keep routes, travel time and return legs; actors retain their intents.
- Respite suppresses incoming hostile journeys only within the player's live
  region. Distant hostile departures, raids and encounters keep authored rules.
  Successful streamer materialisations feed a regional arrivals-per-game-hour
  sensor; an empty pressure window caps population growth without forcing an
  arrival. Continuously sampled old unpaid writs can lower the hunter threshold.
- Move tuning to moddable `game/data/storyteller.json`, retaining code fallbacks.
  The content kill switch disables every override and bias and leaves sensors
  idle. Cache holders per sample and lever snapshots per board update; remove
  the unused knowledge-source gate.
- Turn the console window into a resizable Storyteller Studio with live sensors,
  draggable numeric cells for every state's lever table, session-persisted edits,
  reset controls, and a world view of threads, vendettas and journey outcomes.
  The World Simulation history panel shows those explanations beside causal
  history and links them to their remembered source events. Inspection creates
  no events, facts or intentions and consumes no randomness.
- Version 2 storyteller snapshots preserve feedback, writ ages, Studio edits,
  evidence and bounded diagnostic receipts. Board arrival telemetry is separately
  versioned. Extend mechanism pins for pristine-day byte/RNG parity, feedback,
  route sampling, locality, editing, resizing, causal links and exact restore.

Validation for this work:

- Clean baseline at `4bddb3a`: 4,151 passed, 34 skipped, five existing failures.
- Full dependency-light headless suite (`FIO_HEADLESS_TIER=1`, excluding `qt`,
  `gl` and `benchmark`): 4,176 passed, 34 skipped, the same five failures.
- Focused storyteller, Studio, property-tab and console run: 108 passed.
- The existing failures remain enabled and unfixed: the backport import guard
  flags `tools/benchmark_navigation.py`; repeated assaults leave aggression
  passive; container `lock_difficulty` is an enum where its test expects an int;
  the Ember Tome map's median site spacing is 3982.84 rather than over 4000;
  the inventory artwork archive manifest is absent.
- The marker-only headless command stalled in an existing unmarked Qt console
  editor test. The complete headless runs above use the repository's explicit
  dependency-light collection mode. No tests were weakened or skipped to hide
  the five baseline failures. OpenGL rendering was not exercised.
- Python compilation and `git diff --check` passed. The Studio screenshot uses
  its real Qt painter with sample data.

## Three schools of magic, trainers and tutors

- Magic has three schools and no others: Offensive, Defensive and the new
  Occult (Charisma), which now holds Resurrection, Disintegrate, Summon Wolf,
  Command Creature and Detect Life. Old school names fold into their
  successors; a save from before the Occult starts it at the lower of its
  other two schools. Mage and Necromancer take Occult as a major skill.
- Trainers sell skill points: they cannot teach past their own rank, and
  nobody trains more than five times a character level. Spell tutors sell
  spells by rarity (a legendary one is 5,000 gold). The Arcane Circle's
  tutors ask standing for rarer spells, and you can now join the Circle and
  rise in it by studying. Twelve teachers across the Vale
  (`game/data/teachers.json`, `docs/TRAINING.md`).
- A fizzled cast floats "*fizzled*" over the caster's head, the player's and
  any NPC's. NPC casts can now fizzle, rolled against their school skill. A
  staff never fizzles.
- A little ambient light everywhere (0.15 by default), so unlit faces are dim,
  never black. `ambient X` sets the amount and settings.ini remembers it.
- Things stack at most five to a slot in the pack and on the strip (twelve
  potions take three slots). A weapon still takes a slot per copy, and arrows
  take one slot however many there are. Drinking a potion, from its strip
  slot's number key or anywhere else, plays `drink.mp3`.
- A player of Luck 60 or more finds 10% more gold in every purse, chest and
  body. Gold picked up from the ground now goes into the purse, as it already
  did from chests.

## Crossfire performance

- Use scalar ray tests for populations of up to 16 monsters to avoid NumPy
  dispatch overhead on small inputs.
- Keep larger populations on the vectorized NumPy path and preserve the
  tick-local live-target cache.
- Select the nearest hit without sorting every hit in the common case. Retain
  stable ordering when cached targets have died or become hidden.
- Remove a redundant position-array copy.
- Add scalar/dense equivalence tests, ray-boundary and stale-target checks,
  and an opt-in crossover benchmark.

Local microbenchmarks measured roughly an eightfold improvement for four-row
queries and improvements for large aligned target sets. These measurements
do not establish an end-to-end frame-rate improvement.

## Tests after standalone player removal

- Remove obsolete standalone player reader, renderer, and shader-translator
  checks without restoring the removed package.
- Inspect exported ZIP contents directly and test the current streamed archive
  mounts, including read-only access, unsafe paths, and non-execution of code.
- Recognize packaged assets when validating shipped map references.
- Update test discovery and documentation for the first-party game, move its
  pointer tests into the game suite, and correct missing Qt tier markers.
- Refresh gameplay test preconditions for magic-capable characters, armour
  agility caps, character creation, guard predicates, and enclosed NPC paths.

## Validation

- Final focused run: 1,453 passed; 34 reference-compiler checks skipped because
  `glslangValidator` was unavailable.
- Performance guards: 24 passed.
- OpenGL rendering and submission checks under Xvfb/Mesa: 27 passed.
- Clean headless run: 3,473 passed, 34 skipped, and six existing failures in
  assault/disposition/simulation handling. A duplicate `_provoke` definition in
  `game/runtime.py` calls itself with a properties dictionary. Those failing
  tests remain enabled; this change does not fix that application defect.
- `git diff --check` passed. The entire Qt suite was not rerun to completion.

Run test suites sequentially: their fixtures write the shared `settings.ini`.
