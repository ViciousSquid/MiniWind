# Factions: the world prices drama

MiniWind keeps its causal web. Factions add stakes to that web; the storyteller
still samples existing legal choices. It cannot create crimes, witnesses,
grievances, residents, raids, or combat outcomes. This carries over the pressure
model of a colony simulation without adding its game content or an incident
queue. The player hold is not a board town.

## Beliefs before politics

`fact_from_event()` retains the event's `actor_faction` snapshot through storage,
gossip and restore. Main already contained that repair at the start of this
branch; the mechanism pins remain and are extended here. `target_faction` and
the actor's existing Karma (`alignment`) snapshot now travel with the fact too.
Missing legacy fields remain unknown: nobody reconstructs an old offender's
faction or morality from their present state.

Appraisal's existing fifth branch responds to identified enemy violence with
FIGHT or FLEE, after personal reactions and ordinary crime reporting/arrest.
Sound-only accounts cannot identify an enemy. The new collective grievance rule
applies only to faction actors and their dispatched representatives. A known
crime against their own people can produce FIGHT when their fact-derived
goodwill toward the offender's faction is at or below -20. Ordinary residents
and the watch retain their existing reaction precedence.

## Entities and goodwill receipts

`game/sim/factions.py` discovers a local faction entity for each faction/home
pair represented by actual scene actors inside a named place's radius. Wildlife
keeps its authored ecology. There is no invented headquarters or recruitment
pool. Members communicate their existing facts at home. Away and dead members
cannot supply remote updates; returning survivors can tell what they learned.
The faction's knowledge uses the same bounded, inspectable knowledge store as
any resident, including its source and retelling chain.

The pure `ledger()` projection counts the strongest identified account of each
event once, at the existing reporting certainty threshold. Each contribution
contains its holder and the full source fact. Accounts are directed toward the
actor's recorded faction, for deeds against the receiver's recorded faction:

| Existing fact | Goodwill before certainty scaling |
| --- | ---: |
| Criminal death | -40 |
| Criminal attack | -12 |
| Theft / lockpick / trespass | -8 / -5 / -3 |
| Heal (the existing rescue mechanism) | +12 |
| Gift | +5 |
| Trade | +2 |

Lawful deaths do not become crimes. Repeated gossip does not multiply a debit
or credit. Karma does not add hidden goodwill. Live goodwill is recomputed from
current facts; persisted ledgers are explanation snapshots, not an independent
reputation currency. No diplomatic events or scheduled grudges are generated.
Knowledge and goodwill receipts are shown in the existing mental-state inspector.

## Orders walk the roads

At an off-screen actor decision touchpoint (at most once per game hour), the
faction appraises its knowledge and may hold a FIGHT intent against the player
or another faction's identified offender. This decision belongs to the faction,
not to a storyteller query. An actionable order needs a remembered cause, a
home, an available off-screen force of actual combatants, and a reachable
place associated with the remembered scene. There is no oracle for the player's
current position. A remembered offence at home does not create a departure to
an invented destination. A later identified known deed can supply a trail to
another place; both that trail and the original grievance remain in the receipt.

`JourneyBoard._faction_departures()` admits the order as a `faction_raid` journey
from that home, with ordinary route geometry, speed, arrival time, rest and
homeward leg. That kind has zero authored population weight and no generated
members. Home actors stay hidden while their representatives travel; social
identity, possessions, wounds and knowledge belong to those same people. One
active force per local faction and the persisted discharged-cause tokens prevent
duplicating an order. Forgetting its cause cancels a pending order.

The existing streamer materialises a force only when its computed position
enters the live region. Live intentions require actual sight of their target.
Departure receipts contain the faction, home, offender, known event, holder,
reason and fact. They appear in Storyteller Studio's existing journey receipts
and in the actor's inspector; road dialogue explains the purpose and home.
Authored ecological parties retain their existing home, purpose and carried news.

Existing board combat also feeds actual attack/death outcomes through the
ordinary director and perception pipeline when a faction force is involved.
This observes resolved combat: it does not roll more dice, cause damage or
schedule another encounter. Battle testimony does not invent criminal charges.
Only living survivors remember, and only those who reach home inform the home
faction. Live combat uses the session's existing event pipeline. The resulting
knowledge can support later appraisal; there is no private revenge counter.

## Footprint and the drama price

`game/footprint.py` is an on-demand projection of current world state:

- Prosperity is capped at 1: carried wealth / 2000 plus market route traffic / 20.
  Town prosperity for moods is market route traffic / 4, also capped at 1.
- Notoriety is capped at 1: remembered unreported threads / 8, clean kin vendettas
  / 4, and outstanding writ value / 1000.
- Legend counts distinct identified, sufficiently certain known player deeds:
  heals and gifts contribute positively, crimes negatively. Its receipts identify
  holders and events. The existing Karma value and tier remain the moral axis;
  an unseen deed does not manufacture legend or testimony.

The session supplies read-only wealth, market traffic and Karma hooks. The
storyteller samples the footprint on its ordinary world-time interval. Sampled
prosperity multiplies weights of **already legal bandit destinations** by
`1 + prosperity * prosperity_bandit_bias / (1 + distance / 6000)^2`, using distance
from that destination to the player's town. It does not add that town to the
bandits' legal destination set. Sampled notoriety multiplies the hunter threshold
by `1 - notoriety_hunter_scale * notoriety` (defaults 2 and 0.5 respectively).
The existing old-writ adjustment composes with it. Hunters still require a real
bounty and carried bounty news. Legend and Karma are observations, not new
storyteller authoring powers or automatic raid triggers.

## Moods without off-screen needs

`game/sim/moods.py` evaluates facts, town prosperity, faction goodwill and the
existing Karma functions (`heartens`, `affinity`, NPC moral baseline) as values.
Only identified remembered player deeds supply a moral snapshot for that
resident. No current secret deed supplies knowledge. Courage can yield defiance
or fear in the repaired appraisal pipeline; ordinary FIGHT, FLEE, MOURN and
other existing intentions still determine behavior. No new LEAVE kind is needed:
MiniWind's existing flight and market journey mechanisms handle departure.

`Director.evaluate()` is a read-only appraisal used at mention, materialisation
and journey sampling touchpoints. The normal decision path may cache intents.
Mood queries do not write facts, intent caches, actor properties, or need meters,
and consume no randomness. Mourning can hold a resident at home; a visible
threat can make a travelling resident fight or flee through existing controls.
Existing MiniWind needs and schedules remain in place.

## Pristine ecology and persistence

The storyteller content kill switch and Studio pristine switch also leave new
faction decisions, orders and mood sensors idle. Even an already cached pending
order cannot depart while disabled. Authored board traffic, combat and RNG draws
keep their ordinary path. Full-population same-seed day tests compare serialized
board bytes and RNG state at every quarter-hour, with faction causes available
and forbidden mood/footprint sensors. Existing faction journeys are never moved
or spawned past the board by a switch.

`storyteller.state` is schema **3**. It preserves sampled footprint readings,
effective thresholds, pricing coefficients, receipts and all existing pacing,
feedback and Studio state exactly across restore, including after retuning.
Other schema versions reset to CALM. `factions.state` starts at schema **1** and
stores entity homes, ledger snapshots, fact-backed intents, pending orders,
discharged causes, receipts and the actor decision timestamp. Other versions
reset that subsystem. Facts remain in normal knowledge keys; active journey
causes and real member identifiers ride in `living.board`. Ordinary journeys
omit the optional cause field, preserving their serialized representation.
Moods have no independent saved state. No restore needs a new random draw.

## Validation

The initial workspace was clean at `1490d1d`. Upstream main advanced during the
work, so the implementation was rebased onto `1bc5085` to preserve the newer
controller and camera changes. A separate clean detached worktree at that commit
provided the final baseline. Full runs used the repository's dependency-light
collection mode:

```sh
FIO_HEADLESS_TIER=1 python -m pytest -m 'not qt and not gl and not benchmark' -q
FIO_HEADLESS_TIER=1 python -m pytest game/tests/test_faction_spine.py \
  game/tests/test_sim.py game/tests/test_storyteller.py \
  game/tests/test_storyteller_window.py game/tests/test_alignment.py -q
```

Initial baseline (`1490d1d`): **4,189 passed, 34 skipped, 1,973 deselected, five failures**.
Current-main clean baseline (`1bc5085`): **4,204 passed, 34 skipped, 1,974 deselected, the same five failures**.
Final headless: **4,237 passed, 34 skipped, 1,974 deselected, the same five failures**.
Focused run: **183 passed**. Python compilation and `git diff --check` pass.
No tests were disabled or weakened; the old-writ pin now also asserts the exact
notoriety price and its removal after payment. The 34 skips and tier exclusions
are unchanged from baseline. OpenGL rendering and interactive play were not run.

The unchanged failures are:

- `tests/integration/test_backport_boundaries.py::test_no_module_imports_a_game_package`:
  `tools/benchmark_navigation.py` imports the game package.
- `game/tests/test_disposition.py::test_repeated_assaults_preserve_the_aggression_restored_by_the_watch`:
  restored aggression remains passive.
- `game/tests/test_editor_integration.py::test_container_locks_are_authored_alongside_existing_ownership`:
  `lock_difficulty` is an enum where the test expects an integer.
- `game/tests/test_ember_tome.py::test_the_sites_are_spread_out`:
  median spacing is 3982.84 instead of over 4000.
- `game/tests/test_inventory_artwork.py::test_original_icons_are_archived_exactly_and_all_live_versions_are_replaced`:
  the archive manifest is missing.
