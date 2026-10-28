# Changes

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
