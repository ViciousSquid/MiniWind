# NPC navigation worklog / agent handoff

Updated: 2026-10-27. Status: implemented and validated. Result branch:
[`codex/improve-npc-navigation`](https://github.com/ViciousSquid/MiniWind/tree/codex/improve-npc-navigation).
The branch HEAD identifies the final commit; the chat deliverable also records it.

## User requirements

- Improve NPC navigation and create a new branch.
- Route work must not run at render FPS. Existing Monster AI runs at 30 Hz.
- Add real-time pathfinding debugging, console toggle and controls/filters.
- Make the debugger reusable in future prompts for behaviour, decision and
  performance investigations, including structured exports and documentation.
- BigWorld is authoritative. Respect its existing residency and simulation
  layers; do not create another tier classifier or simulation scheduler.
- Keep this handoff current for other agents.

## Branch and environment

- Repository: ViciousSquid/MiniWind.
- Local branch: `codex/improve-npc-navigation`, in `/workspace/MiniWind`.
- GitHub branch with the same name was created from
  `7b52485c32b1ab7500a9a087fbd3f9fa708e31d3` (the linked source/main).
- The supplied local checkout started one merge behind that source. The exact
  source snapshot has now been imported using SHA-verified GitHub objects and
  the working branch is based on `7b52485c32b1ab7500a9a087fbd3f9fa708e31d3`.
  Upstream runtime/UI changes, including inventory cursor handling, are preserved.
- Shell `git fetch` fails because the configured proxy cannot be reached.
  The GitHub connector works and is used for publication. Local history is
  shallow at the source revision; use GitHub for history beyond that boundary.
- Python/dependencies: `/workspace/.venvs/miniwind/bin/python` (3.14).
  `pyflakes` is not installed. No repository AGENTS.md was found.
- No sub-agents have been started. Existing user changes were absent.
- Checked for an existing handoff file in the repository and workspace. The
  existing `docs/handoff/` directory contains engine patch bundles and helper
  scripts, but no status/handoff document to update. This is the shared record.

## Implemented so far

- `game/navigation.py`: failed searches retry after 0.5 seconds; cached queries
  invalidate on relevant cell/height changes; waypoint visibility checks run
  at 0.25-second intervals within the same cell; route expiration remains two
  seconds. Batch steering reads the clock/ages the shared cell cache once.
- Replaced sampled visibility with grid traversal, including both side cells
  at diagonal crossings. This prevents smoothing from undoing A* corner safety.
- Smoothing collapses collinear runs and checks turns in a forward pass.
- Route cursor avoids list-front removal. Blocked requested goals retain their
  safe snapped endpoint instead of immediately steering into the blocked goal.
- Optional per-actor counters: steering calls, searches/failures/reasons,
  expanded nodes, smoothing probes, search timing and last search outcome.
- Detached diagnostic records; drawing/reporting/exporting do not plan routes.
- `game/pathfinding_debug.py`: filter configuration, actor records, versioned
  report API and JSON export. `docs/PATHFINDING_DEBUG.md` describes future use.
- `paths` / `pathfinding` console command: fixed broken on/off parsing; toggle,
  panel, actor/state/distance/labels filters, report/reset/export.
- `game/ui/path_debug.py`: control panel, live labels, remaining waypoint
  rendering, safe endpoint vs requested goal, correct camera clipping adjacency.
- Mouse cursor eligibility added for `debug:pathfinding` window.
- BigWorld integration completed: `steer_actor` and batch entry
  points read `engine.spatial.tier_of`; DISTANT/DORMANT suppress A* and discard
  live route caches. Existing runtime tick/stride scheduling is preserved.
  `_move` now calls `steer_actor`. Debugger reads authoritative tier stamps,
  suppresses dormant rows and labels distant records as coarse movement.
  Console and panel include a BigWorld tier filter; display distance does not
  reclassify tiers. Tests cover demotion, promotion, the combat hook and coarse
  schedule walking.

## Validation completed

- Initial movement/tactics baseline: 30 passed.
- Navigation, debug API/panel, movement, tactics, console, scheduling, residency
  and BigWorld tier integration on the exact source base: **128 passed**.
- Unchanged-source gameplay + Monster AI baseline: **1222 passed, 11 failed**.
  Failures concern
  combat provocation, disposition, lock schema, location spacing, missing icon
  archive and dense-AI delta parity. These failures reproduce without the task's
  changes. An older-checkout run also failed a pause-menu test fixed upstream.
- Final gameplay + Monster AI + all BigWorld tests: **1411 passed, 11 failed**.
  The failure set exactly matches the unchanged-source baseline: **no new
  failures**. All BigWorld tests and the new navigation/debug tests pass.
- The first expanded run stalled while SDL initialized the editor audio mixer.
  Using `SDL_AUDIODRIVER=dummy` resolved it, including the editor hierarchy test.
  Use that setting in this headless environment; no production audio change
  was needed.
- Syntax compilation and `git diff HEAD --check` passed.
- Offscreen preview rendered and inspected: panel controls, world paths, route
  labels and authoritative tier labels are visible and legible. Sample preview
  and JSON are in `work/`.
- Benchmark against original navigation, 100 stationary NPCs, five simulated
  seconds, 30 Hz (same local machine):

| Scenario | Original | Improved |
| --- | ---: | ---: |
| Unreachable A* calls | 15,000 (30/NPC/s) | 1,000 (2/NPC/s) |
| Unreachable elapsed | 464.50 ms | 44.39 ms |
| Wall-detour visibility probes | 25,200 | 6,200 |
| Wall-detour elapsed | 433.97 ms | 312.15 ms |
| Corridor smoothing probes | 2,143 | 20 |
| Corridor smoothing waypoints | 19 | 19 |

These are microbenchmarks, not renderer FPS or a moving-world performance claim.
No native extension has been introduced; avoiding redundant work is the current
optimization. `tools/benchmark_navigation.py` reproduces the measurements.

## Reuse in future prompts

Read `docs/PATHFINDING_DEBUG.md` for the investigation workflow, commands,
structured schema and script API. Start in Play Mode with `paths on` or
`paths panel`; filter with `paths actor "Name"`, `paths tier near` and
`paths state failed` as needed. Run `paths reset`, observe the scenario, then
`paths report` and `paths export "cache/pathfinding-investigation.json"`.
Reports expose positions, goals, remaining waypoints, decisions, BigWorld
layers, route age, search reasons/outcomes, timings and per-actor search rates.
Neither the renderer nor the reporting API triggers a search.

## Verification commands and evidence

```bash
SDL_AUDIODRIVER=dummy /workspace/.venvs/miniwind/bin/python -m pytest \
  game/tests tests/monster_ai plugins/bigworld/tests \
  -m 'not gl and not benchmark' -q --tb=no
/workspace/.venvs/miniwind/bin/python tools/benchmark_navigation.py \
  --reference work/navigation_before.py --npcs 100 --seconds 5 --hz 30
git diff HEAD --check
```

Local evidence: `work/baseline.xml`, `work/final.xml`, `work/final.log`,
`work/benchmark-final.txt`, `work/pathfinding-debug-preview.png` and
`work/pathfinding-debug-sample.json`. `work/` contains originals and scratch
assets and must not be committed. The durable handoff and debugger guide are
committed in `docs/NAVIGATION_WORKLOG.md` and `docs/PATHFINDING_DEBUG.md`.

## Known limits and follow-up scope

- The 11 baseline failures are unrelated work, recorded above; they are not
  repaired by this navigation change.
- Obstacle-cell memory remains 20 seconds, so dynamic door state can be stale
  until cache expiry. The tool documents this when analysing a blocked route.
- Search rates average the observation window, including idle time. Reset
  before representative comparisons. Runtime actor IDs are session-local.
- No native backend is added. The measured gains come from avoiding searches,
  reducing smoothing probes and following BigWorld's existing simulation layers.

## Follow-up: repeated letters in the Play Mode console

User report: command text sometimes becomes `debbuug` instead of `debug`.
Investigation found no duplicate event-forwarding path. The exact text is
reproducible by sending printable OS/Qt autorepeat events to the real Play
Mode console inputs. The physical keyboard/platform cause has not been
confirmed; the user was asked which OS and whether quick taps also repeat.

`CommandInput` now accepts a `repeat_text` option. Both Play Mode inputs (the
viewport input and the older frame input) disable printable autorepeat and
key compression. Each physical press still inserts text, so intentionally
typed double letters work. Held Backspace/navigation, command history, input
methods and normal editor-console text repeat keep their existing handling.
There is no time-based deduplication that could discard fast typing.

Regression tests reproduced the reported `debbuug` string before the fix in
both Play Mode inputs. After the fix, they also verify `coffee`, held
Backspace and the editor console's normal autorepeat. Validation:

```bash
SDL_AUDIODRIVER=dummy /workspace/.venvs/miniwind/bin/python -m pytest \
  tests/editor/test_console_history.py tests/editor/test_console_key.py \
  tests/editor/test_held_keys.py tests/editor/test_debug_console.py \
  game/tests/test_console.py -q --tb=short
```

Result: **38 passed**. `git diff --check` also passed. This follow-up changes
console input only; BigWorld and navigation scheduling are untouched.
