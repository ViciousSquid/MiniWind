# Storyteller pacing

`game/storyteller.py` is a headless sampler over the reactive simulation. It
creates no events, knowledge, witnesses or NPC intentions. Every designer
setting is in the `TUNING` table at the top of that module.

The cycle is `CALM → RISING → PEAK → RESPITE → CALM`. Quiet time and recovery
gate escalation. Existing unreported memories, kin vendettas and regional writs
can start the rise; recent attacks against the player, visible hostiles and
injury measure tension. The crest is short. Respite lasts until the player has
recovered, even if recovery takes longer than an ordinary cycle.

Each state supplies journey kind weights and departure windows, road population,
the hunter bounty threshold, a multiplier for new lair refill delays, market
trip probability, and destination and vendetta sampling multipliers. Windows
such as `[18, 6]` cross midnight. Unspecified journey weights/windows retain
`game/living/journeys.py`'s authored defaults. Existing travellers and NPC
intentions continue under their ordinary rules. Saved lair deadlines keep their
timing; the delay multiplier applies when a death creates a new deadline.

`StorytellerHooks` is a read-only interface like `WorldHooks`.
`SessionStorytellerHooks` projects the session's health, town, living knowledge
holders, visible hostile counts and existing Writs rows. Hostiles use
`world_index.counts_by_tier(predicate=...)`, filtering for visibility, liveness
and relevant tiers. Writs are read without calling methods that create records.

Although `crime.unsolved()` lists unperceived crimes too, the sampler only uses
its event IDs to filter actual stored beliefs with a known perception source.
Remembered crimes remain loose threads after their events leave the bounded
history, until reported, settled or forgotten. Only living NPC holders contribute
loose threads. Destination weights follow
the town holding the memory, not the event's hidden location. They influence
departures, subsequent legs and local market trips; legal destinations remain
available.

Vendetta staging requires a cached, clean kin `FIGHT` intent against the player
and the corresponding identified death fact in the actor's own knowledge.
An actor who has already attacked the player for that fact is discharged from
staging. The discharge survives rolling event history and save/load. A bonus
only applies while the player is healthy inside a town and the journey's
natural position is nearby. The streamer uses that weight to prioritise its
existing live slots, preserving the journey's route and position. Resident
proxies retain the social identity that owns their knowledge while keeping
separate scene UUIDs for save overlays.

The session samples world time immediately before ticking the living board.
`WorldHooks` exposes the lever and sampling queries to board/streaming code.
Every decision updates a plain-English explanation shown in the existing
mental-state inspector's **Storyteller decisions** section beside ranked
intents. Explanations are bounded, with current pacing information retained.

In Play Mode, type `storyteller` in the console to open the live floating
inspector. It shows every effective journey weight and departure window,
including inherited defaults, all other current lever settings, and the last
10 sampled observations, newest first. Each observation retains its world time,
state, sensor readings and decision reason; repeated unchanged samples remain
separate observations. The history survives save/load. Scroll with the wheel
or the Up/Down buttons; running the command again brings the window forward.
Opening and reading the window does not pause or advance the simulation.

State, timing, discharge records, sampled threads, observations, reasons and the complete
lever overrides persist under `storyteller.state` in the normal KV store.
Restoration uses the saved overrides rather than recomputing them from today's
tuning table. The sampler consumes no random numbers; board choices use the
session's reseeded RNG as before.

Run the mechanism tests with:

```sh
python -m pytest game/tests/test_storyteller.py -q
```
