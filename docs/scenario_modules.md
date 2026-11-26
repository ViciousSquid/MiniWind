# Reusable world-scenario modules

Dynamic mode stages world encounters through the reusable implementations in
`game/living/scenario_modules/`. The Scenario Director owns
global pacing and chooses which encounter to stage; it does not own the
implementation of each encounter.

## Layout

- `waylaid.py`: a real traveller is waylaid by a real gang.
- `avenger.py`: a resident pursues the actual culprit behind a remembered grievance.
- `reckoning.py`: evidence-based vendetta, confrontation and restitution.
- `gratitude.py`: a resident returns to thank the player for a remembered deed.
- `patrol.py`: a watch patrol meets brigands.
- `ambush.py`: brigands lie in wait after dark.
- `procession.py`: cultists travel along a road at night.
- `cult_rite.py`: cultists hold a real resident captive during a rite.

Each module owns its scene-specific staging, dialogue, thoughts and ambient
lines. Cult Rite also owns its expiry consequence; Avenger owns its grievance
and culprit resolution and the behaviour of an avenger who proceeds alone.
Reckoning and Gratitude share the evidenced-meeting mechanism but own their
distinct outcomes.

## Contract and context

Each module has a stable `kind` and a
`stage(context, game_hours)` entry point. `ScenarioContext`
in `base.py` exposes only the shared world operations needed to stage
an encounter: road selection, party borrowing and creation, resident extraction,
journey staging, location descriptions and scene recording. Modules do not
receive the Scenario Director itself.

The Director still owns Dynamic enablement, tension/intensity, build/sustain/
fade/relax pacing, weighted selection, concurrent-scene limits, Storyteller
scaling, learning, decision logging, persistence and restoration.

## Invoking a module outside Dynamic pacing

A scripted quest, faction event or another game mode can request an encounter
directly without reimplementing it:

```python
scene = world.scenarios.invoke("waylaid", game_hours)
```

This direct invocation does not turn Dynamic mode on and does not run its
pacing system. The caller is responsible for choosing the appropriate time
and world conditions. The module still uses the same real residents, journey
board, combat, news and save-state semantics as a Dynamic-staged encounter.

Existing `_stage_*` Director entry points remain small routing methods
for current callers. New systems should use `invoke(kind, game_hours)`
rather than copying encounter logic.

## Adding a scenario

1. Add a module class in `game/living/scenario_modules/` with a unique `kind` and
   a `stage(context, game_hours)` implementation.
2. Put that scenario's thought, ambient and conversation content in the same module.
3. Register the class in `scenario_modules/__init__.py`.
4. Add its Dynamic scheduling weight, display name and any time-of-day selection
   rule to the Director only when Dynamic mode should schedule it.
5. Add focused module tests and a Director integration test.

Eligibility and time-of-day policy remain global scheduling concerns. A module
can reject staging through `context._no(reason)` when the required
real-world conditions are absent.
