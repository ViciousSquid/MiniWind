# Pathfinding debug tool

Use this tool when investigating an NPC's movement, route choice, repeated
searches, blocked goals or navigation cost. It works with schedule walkers
and Monster AI chases. It is session-local and disabled by default.

## In Play Mode

| Console command | Effect |
| --- | --- |
| `paths` or `pathfinding` | Toggle live path lines and diagnostic collection |
| `paths on` / `paths off` | Explicit, repeatable enable / disable |
| `paths panel` | Open draggable controls; enables diagnostics and releases the mouse |
| `paths actor "Town Guard"` | Filter by case-insensitive name substring |
| `paths actor 123456` | Filter by the runtime actor ID printed by `paths report` |
| `paths actor all` | Clear the actor filter |
| `paths state all` | Show every route state |
| `paths state route` / `failed` / `direct` / `chase` | Show one route state |
| `paths tier all` / `near` / `active` / `distant` / `dormant` | Filter BigWorld's authoritative layer |
| `paths radius 3200` | Maximum world distance from the player |
| `paths labels on` / `paths labels off` | Show / hide actor name, state and A* frequency |
| `paths reset` | Start fresh counters without disturbing active routes |
| `paths report` | Print filtered actor decisions, search rates, costs and last search |
| `paths export` | Save `cache/pathfinding-debug.json` |
| `paths export "capture/guard-stuck.json"` | Save a structured capture at a chosen path |

The panel provides state, BigWorld tier and distance filters, labels, clearing the actor filter
and resetting counters. Closing the panel keeps lines enabled; use `paths off`
to stop collecting. Filters affect the overlay, console report and export, so
check them before comparing captures. There is no persistent settings change.

Cyan lines follow the remaining planned waypoints, yellow lines show direct
schedule walks, orange lines show direct chases, and red lines show a failed
search awaiting retry. Dots mark waypoints. A dashed red segment from a safe
endpoint to the requested goal identifies a goal the planner could not walk
into (for example, a goal inside a wall). The overlay is drawn over the world
and is visible through walls; it is a diagnostic, not a depth-tested path mesh.
Grey lines show DISTANT actors' coarse movement. DORMANT actors are absent from
the resident actor set and are never loaded or activated by this debugger.

## Workflow for future investigations

For a request such as “use the pathfinding debug tool to analyse this guard's
behaviour/performance/decision”:

1. Reproduce in Play Mode. Run `paths on`, `paths actor "Guard Name"` and
   `paths state all`. Include other actors by clearing the actor filter when
   examining a crowd. Move within the configured radius.
2. Run `paths reset` immediately before the behaviour. Observe at least ten
   seconds at normal simulation speed. Take a screenshot of the overlay if
   geometry or corner selection matters.
3. Run `paths report` and `paths export "cache/pathfinding-before.json"`.
   Compare the current position, requested goal, safe endpoint, next waypoint,
   decision, route age and last search reason/outcome. Distinguish a failed
   route from a successful route obstructed by the physical mover.
4. Inspect `searches`, `failed_searches`, `searches_per_second`, `expanded_nodes`,
   `smoothing_checks`, `search_ms` and `last_search`. Explain the observed work
   and route choice using the capture. Preserve the exported JSON as evidence.
5. After a change, reset counters and repeat the same scenario, observation
   duration, actor count and filters. Export an after capture and compare the
   counters and timings. Render FPS is not a navigation frequency measurement.

Monster AI updates at 30 Hz. Steering returns a waypoint on each call, but
visibility/waypoint checks reuse their result for 0.25 seconds in the same
grid cell; failed A* searches retry after 0.5 seconds. A route expires after
two seconds. Changing grid cell or height invalidates query/retry caches;
moving the route goal more than 160 units invalidates the route. A goal that
crosses a cell boundary invalidates cached direct visibility immediately.
These are maximum reuse intervals, not promises of exactly periodic work.

BigWorld remains the single source of truth for residency and simulation
layers. Navigation reads `engine.spatial.tier_of(actor)`, including its NEAR
default when no tier is stamped. NEAR and ACTIVE use the runtime's existing
tick/decision cadence and camera-fitted off-screen strides. DISTANT retains
coarse collision-checked movement without live A*; DORMANT receives no work.
Demotion discards live route caches, so promotion plans afresh. No timer wakes
actors, no actor distances are used to reclassify tiers, and the debug radius
only filters the display/capture. The tool reads the existing resident actor
set instead of enumerating the full world. Use the tier filter when comparing
costs at different simulation fidelities.

## Script / agent API and capture schema

No renderer or Qt dependency is needed for collection and reporting:

```python
from game import pathfinding_debug

# session is the active MiniwindSession (logic._miniwind in the editor).
pathfinding_debug.configure(session, enabled=True, actor="Guard", state="all")
session.nav.reset_search_stats()
# Let the real AI run the scenario; do not call steer from the debug tool.
capture = pathfinding_debug.report(session)
pathfinding_debug.export(session, "cache/pathfinding-investigation.json")
```

For standalone simulations, construct `Navigator(blocked, clock,
track_stats=True)`, run the existing steering calls and read
`navigator.search_stats()`. `set_debug(True)` additionally records positions,
goals and remaining waypoints for `debug_snapshot()`.

JSON schema version **1** has `captured_at` (UTC), `enabled`, `filters`,
`cadence`, `summary` and `actors`. Actor records include `key`, `name`, `pos`,
`goal`, `points` (remaining X/Z waypoints), `state`, `movement`, `decision`,
`route_age`, `tier`, `live_navigation`, and any collected counters. `waypoint` is the most recent steering
answer. A direct walker that has not needed the Navigator can have no counters.
The `last_search` object records the monotonic `at` time, `reason` (`missing`,
`expired`, `goal_moved`, `height`, `retry`), `outcome` (`found`, `unreachable`),
`expanded_nodes`, `smoothing_checks` and `elapsed_ms` when applicable.
`decision="bigworld_coarse"` identifies DISTANT movement, which is not an A*
failure. Counters can include work from before an actor's demotion; rates are
not a claim that its current tier performed that historical work.

Rates are averages since each actor's first observed steer call, including
idle time. Immediately after reset a short interval can report a large average;
use a representative observation window. Timings cover A* and smoothing,
including collision callbacks, and add diagnostic overhead. Actor IDs are
process-local and can change between sessions. Route snapshots older than
2.5 seconds are excluded; actors still in the world may retain their counters.
Obstacle cells are shared across NPCs and remembered for up to 20 seconds,
so a changed door can remain represented by a cached cell until expiry.

Neither drawing, reporting nor exporting requests a new route. Diagnostic
collection is optional, and disabling it discards debug-only counters.

## Reproducible microbenchmark

```bash
python tools/benchmark_navigation.py --npcs 100 --seconds 5 --hz 30
git show 7b52485:game/navigation.py > /tmp/navigation-before.py
python tools/benchmark_navigation.py --reference /tmp/navigation-before.py
```

This exercises open walks, a wall detour, unreachable goals and smoothing in a
winding corridor. It reports searches per NPC per second, visibility probes
and elapsed time. Stationary starts intentionally isolate redundant planning;
the benchmark does not represent a whole moving game scene or renderer FPS.
