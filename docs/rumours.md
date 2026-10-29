# Rumours: the world, said aloud

The knowledge store already records who believes what, how surely, and who told
them. The rumour layer **broadcasts** it. Tavern talk, notice boards and
residents volunteering "Word is someone robbed Bram near the ford, yesterday"
make the emergent world readable as stories. A vendetta arrival stops reading
as a random ambush once someone in town has told you whose brother you killed.

It is narration, not authoring. `game/sim/rumours.py` turns existing facts,
board news and journeys into sentences. It creates no events, writes no beliefs,
changes no intentions and draws no simulation random numbers.

## What a resident can tell

`rumours.line(fact, place_of, today)` phrases one stored fact as its holder would
say it:

- **Opener by source and certainty.** "I saw it myself" (witnessed), "I heard it
  happen" (heard), "Word is" (told), or "They say, though I can't swear to it"
  when hearsay is held below 50% certainty.
- **Names as known.** An unidentified culprit stays "someone"; the listener is
  "you". Nobody learns a name they were never told.
- **Place and time.** The nearest named place to where the fact says it happened
  ("near the ford"), and how long ago ("yesterday", "a few days back").
- **Why a faction party was there.** Facts from a faction raid's fights carry the
  order's receipt. The rumour adds "Those were bandits out of Blacktooth Camp
  over how Mara was killed by you."

`rumours.pick()` chooses what is worth volunteering: notable kinds held at 30%
certainty or more, ranked by certainty × severity, newest first on ties.
The order is deterministic.

## Where the player hears it

- **"Heard any news?"** Any non-hostile resident offers it when they have
  something to say. The answer is up to two things they believe, one departure
  from their town, and the news travellers brought there (`LivingWorld.prepare_tree`).
  Before this change, residents who only knew things first-hand offered no news.
- **Volunteering and tavern talk.** On a decision pass, the idle resident nearest
  the player (within 220 units, in a chatting routine, not mid-bark) may
  volunteer the most interesting thing they have not yet told the player
  (`VOLUNTEER_CHANCE`, ×`TAVERN_FACTOR` at an inn). Each resident tells each
  fact once and then waits `VOLUNTEER_COOLDOWN` seconds before speaking again.
  The chance uses the HUD's chatter RNG, never the simulation's.
- **Notice boards.** Any thing of type `notice_board` can be read with the
  interact key, or through the `StartDialogue` input. It shows:
  - the writ on the player's head in its jurisdiction;
  - the watch's appeals over crimes that its town's residents know were
    reported and that are unsettled;
  - who set out from the town, and why;
  - news travellers brought.

## Departures

`LivingWorld.departures(place)` describes journeys actually on the road from a
town:

- **Faction orders** (`faction_raid`): "The Watch set out from here for
  Kettlewick, after you, over how Mara was killed by you."
- **Justified trips:** residents the storyteller routed toward the player (see
  [Justified journeys](storyteller.md#justified-journeys)), for example "Hester
  left for Ashby — swore to find whoever killed Bram."

A party that has arrived, or is heading home, is no longer described as setting
out. A justified trip is described only while the storyteller's sampled row
still names that destination. With pristine ecology it is never described.

## Tests

```sh
FIO_HEADLESS_TIER=1 python -m pytest game/tests/test_rumours.py -q
```
