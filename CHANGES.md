# Changes

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
