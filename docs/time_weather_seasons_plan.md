# Plan: day and night, weather the storyteller steers, and seasons

Status: **proposed** — nothing here is built yet. This plan builds on what the
game already does rather than replacing it. When a phase lands, move its rules
into [RULES.md](../RULES.md) (the game and that document must agree) and its
mechanism into the relevant doc ([storyteller.md](storyteller.md) for the
storyteller parts).

## Contents

- [What exists today](#what-exists-today)
- [Gaps](#gaps)
- [Phase 1 — one source of truth for time and season](#phase-1--one-source-of-truth-for-time-and-season)
- [Phase 2 — the full day/night cycle](#phase-2--the-full-daynight-cycle)
- [Phase 3 — seasons in the world](#phase-3--seasons-in-the-world)
- [Phase 4 — weather the storyteller can steer](#phase-4--weather-the-storyteller-can-steer)
- [Phase 5 — what the storyteller is doing (window and console)](#phase-5--what-the-storyteller-is-doing-window-and-console)
- [Order of work](#order-of-work)
- [Open questions](#open-questions)

## What exists today

| Piece | Where | What it does |
| --- | --- | --- |
| Game clock | `game/rpg/gametime.py` | Hours and days; one game day takes 24 real minutes (`DEFAULT_MINUTES_PER_DAY`, per-map `minutes_per_day`). Saved, and replicated to co-op clients. |
| NPC schedules | `game/rpg/schedule.py` | Fixed clock hours: up at 6, work 9–17, sleep at 22. |
| Night look | `game/ui/daylight.py` | Paints darkness over the scene from the key moments in `SKY`, with holes around lamps, hearths and carried torches. NPCs carry torches after dark (`runtime._update_torch_lights`). |
| Reflected sky | `game/sky.py`, `engine/shaders.py`, `engine/sky_clouds.py` | The water reflects a sky with dusk colour, stars, a moon and drifting clouds. `SUN_DIR` and `MOON_DIR` are shader constants. |
| Weather | `game/weather.py` | A Markov chain: clear → overcast → rain / storm → … with eased rain, gloom, storm and ground wetness. Storms bring gales (`game/wind.py`), lightning (`game/lightning.py`) and stop travel. Rain slows grass fire. Saved under the `weather` KV key. Drawn by `game/ui/rain.py`. Off with `[GAME] weather`. |
| `weather` command | `game/console.py` (`cmd_weather`) | Shows the weather, or forces a kind for a spell. |
| Farming year | `engine/terrain_biomes.py` | `YEAR_DAYS = 28`, `SEASONS`, `season_of`, `wheat_stage`; `runtime._update_season` with `YEAR_START = 0.42`. Only the wheat changes. |
| Storyteller | `game/sim/storyteller.py`, `game/data/storyteller.json` | CALM → RISING → PEAK → RESPITE. Changes pacing levers only, creates no events, uses no random numbers, and with pacing off the world matches an untouched one byte for byte. |
| `storyteller` command | `game/console.py` (`cmd_storyteller`) | Opens Storyteller Studio (`game/ui/storyteller_window.py`). |

## Gaps

1. **Three definitions of "day" disagree.** `GameClock.is_daytime` uses 6–20,
   `daylight.SKY` puts sunrise at 6.3 and sunset at 18.5, and
   `sky.dusk_amount` centres dusk on 18.8.
2. **The sun never moves.** `SUN_DIR` is a constant, so terrain shading and the
   sun's glint in water look the same at 08:00 and 17:00.
3. **Day length never changes.** Sunrise and sunset are the same all year.
4. **No `time` command** for testing night, dawn or a date.
5. **Weather ignores the season** and has no snow.
6. **Co-op clients roll their own weather.** Only the clock is sent
   (`game/multiplayer/replication.py`, the `"clock"` entry); each client's
   `Weather(random.Random())` runs independently, so players on one shared
   world can see different skies.
7. **The storyteller cannot influence weather**, and there is no quick way to
   read what it is doing without opening the Studio.

## Phase 1 — one source of truth for time and season

**Done** (with leap years and the Leap Festival, added on request). See
[RULES.md §19](../RULES.md#19-time-and-the-calendar) and `game/calendar.py`;
tests in `game/tests/test_calendar.py`. As built:

- Years are counted. Every fourth year (4, 8, 12 …) is a leap year with a 29th
  day, **Leap Day**, after winter: no weekday, no season, the clock reads
  "Leap Day". The Vale keeps it as the **Leap Festival**: announced the day
  before and on the day (message log and a long toast), and townsfolk small
  talk is all about it. New years and seasons are announced too.
- Day 1 is the last day of year 1's summer (`YEAR_START_DAYS = 12`, a whole
  number so dates turn over at the clock's midnight; the old `YEAR_START` was
  0.42 of a year, 11.76 days).
- Day length: 12.2 h at the equinoxes, 15.8 h midsummer, 8.6 h midwinter,
  centred on 12:24. Solar hours keep today's look exactly at the equinoxes.
- Torches keep their old rule in solar hours (lit from solar 20:00 to 06:00).
- The moon's cycle is 8 days.
- `coldness()` for snow lives here too (see Phase 3).

Original goal: everything that asks "is it day?", "how dark is it?" or "what
season is it?" gets the same answer.

### New module: `game/calendar.py`

Pure Python, no Qt or GL, tested headless. Takes a `GameClock` (or day and
hour) and answers:

- `year_fraction(clock)` — 0..1 through the year, using `YEAR_START` and
  `terrain_biomes.YEAR_DAYS` (both move here; `terrain_biomes` and `runtime`
  import them).
- `season(clock)` — `spring`, `summer`, `autumn`, `winter`.
- `season_blend(clock)` — weights for the current and next season, eased over
  the last couple of days of each season, so colours and weather odds change
  gradually rather than on a single midnight.
- `sunrise(day)`, `sunset(day)` — vary over the year on a cosine. Starting
  targets, to tune in play: summer roughly 05:00–21:00, the equinoxes
  06:00–18:30 (today's look), winter roughly 07:30–17:00.
- `day_fraction(clock)` — where in the day we are relative to that day's
  sunrise and sunset (0 at sunrise, 0.5 at sunset, 1 at the next sunrise).
- `sun(clock)` — elevation and direction, for the renderer.
- `moon(clock)` — direction and phase (a lunar month of, say, 7 or 14 game
  days so phases are visible within one season).
- `is_daytime(clock)`, `night_amount(clock)`, `dusk_amount(clock)`.

### Rewire existing callers

- `GameClock.is_daytime` delegates to `calendar.is_daytime`.
- `daylight.SKY` keeps its colours but keys them on `day_fraction` instead of
  fixed hours, so the same dusk stretches or shrinks with the day.
  `daylight.night_amount` and `map_night` follow.
- `sky.dusk_amount` uses `calendar.dusk_amount`.
- `runtime._update_season` and `terrain_biomes.wheat_stage` read
  `calendar.year_fraction`. The crop curve itself is unchanged.
- Torches light at real dusk, not at 20:00.
- NPC schedules **stay on clock hours** — people still rise at 6 — so nothing in
  the schedule data or the reactive simulation changes.

### Tests

- Sunrise is before sunset on every day of the year; day length is longest in
  mid-summer and shortest in mid-winter.
- `is_daytime`, `night_amount` and `dusk_amount` agree with each other at every
  hour of several sample days.
- At the equinox the old fixed-hour values are reproduced (within tolerance),
  so today's look is a special case.
- Wheat stages are unchanged for the same day.

## Phase 2 — the full day/night cycle

**Goal:** the world visibly turns: light moves across it, nights are dark, dawns
and dusks fit the season.

- **A moving sun.** Replace the `SUN_DIR` constant in `engine/shaders.py` with a
  `uSunDir` uniform. The game sets it each frame from `calendar.sun` the same
  way it already sets `sky_state` (`game/sky.py` → renderer `sky_state`). Terrain
  shading, the sun glint in water and `engine/sky_clouds.py`'s sun-side cloud
  channel all follow. Below the horizon, the sun term fades out.
- **A moving moon with phases.** `MOON_DIR` becomes `uMoonDir` plus a
  `uMoonPhase`. The reflected moon draws its phase; a full moon lifts the night
  darkness a little (`daylight` reads `calendar.moon` phase), a new moon deepens
  it.
- **Seasonal light.** `daylight.SKY` gets a per-season tint: warmer, longer
  summer evenings; a paler, cooler winter day. Overcast skies already darken it
  through `weather.gloom`.
- **Renderer default.** Without the game (the editor, other maps), the renderer
  keeps today's fixed direction as the uniform's default.

### `time` console command

Added to `game/console.py`'s `COMMANDS`, Play Mode only:

| Command | Effect |
| --- | --- |
| `time` | Date, weekday, season, sunrise, sunset, moon phase. |
| `time 21:30` | Set the hour today. |
| `time +6` | Advance six hours (weather and simulation catch up through their normal update). |
| `time day 15` | Jump to day 15 at the current hour. |
| `season winter` | Jump to the first day of that season. |

Hour and day are already saved and sent to co-op clients, so no new save data.
In co-op only the host may change time.

### Tests

- The uniform is set from `calendar.sun` and changes over a day.
- `time` parsing (bad input reports an error, does not change the clock).
- `season winter` lands on a winter day.

## Phase 3 — seasons in the world

**Goal:** each season looks and plays differently.

### Weather tables move to data

`game/data/weather.json` holds, per season: `next` (transition odds),
`spell_hours`, and the `rain`, `gloom` and `storm` levels per kind. Mods can
override it at `game/data/mods/<name>/weather.json`, loaded the same way as
`storyteller.json`. `weather.py` keeps its current constants as code fallbacks,
equal to today's behaviour (that table becomes "spring").

Starting character of each season:

| Season | Weather |
| --- | --- |
| Spring | Today's weather: showers, the odd storm. |
| Summer | Long clear spells, ground dries fast, rare but violent storms (more lightning in dry grass). |
| Autumn | Overcast and rain most often, longer rain spells, storms more likely. |
| Winter | Snow replaces most rain, short grey days, storms become blizzards. |

Odds blend between seasons using `calendar.season_blend`, so there is no sudden
switch.

### Snow

**Done** (brought forward on request). See RULES.md §9 *Weather › Snow*;
`game/weather.py` (`SNOW`, `NEXT_COLD`, blizzards, `snow` cover),
`calendar.coldness`, flakes in `game/ui/rain.py`, the terrain shader's
`uSnowCover` (renderer `snow_cover`, set by `game/host.py`). Tests:
`game/tests/test_snow.py`, `tests/renderer/test_snow_cover.py`. The rest of
Phase 3 (per-season weather tables in data, grass colour, trees) is still to
do. Original notes:

- New weather kind `SNOW` (alias `snowy`), allowed only when the season allows
  it.
- `game/ui/rain.py` draws drifting flakes instead of streaks for snow.
- `Weather` gains a `snow` cover value (0..1) that builds while it snows and
  thaws in warmer seasons and in rain, the same way `wet` soaks and dries.
- The terrain tints towards `terrain_biomes.SNOWFIELD` by `snow` cover
  (a new terrain uniform, similar to how the season is set today).
- Snow cover stops grass fire (folds into `Weather.dryness`). Snow cover is
  saved in the weather snapshot.
- Storms in winter keep their gale and stop travel; lightning is rarer.

### Grass and fields

- Meadow grass colour follows the season blend (fresh green in spring, yellowed
  late summer, browned autumn, dull and sparse winter), as the wheat already
  does.

### Stretch: seasonal trees

`docs/tree-kit.md` already has autumn and bare variants (oak, larch, apple and
others). Swapping them across 2.5 million parked objects is too costly to do at
once, so only swap trees as BigWorld streams them into view, and only on a
season change. Do this last, behind a setting, and measure it.

### Tests

- Each season's table loads and its odds sum correctly; a mod override replaces
  a season's table.
- Over many seeded spells, winter produces snow and summer never does.
- Snow cover builds and thaws; snow cover stops grass from catching.
- Old saves without `snow` load with no snow.

## Phase 4 — weather the storyteller can steer

**Goal:** the storyteller can make weather serve the story's pace, without
breaking its rules (it changes levers only, creates no events, uses no random
numbers, and with pacing off the world is byte-identical).

### How it steers: weights on the weather's own dice

The storyteller never picks the weather. It publishes weights; `Weather` applies
them when it rolls its next spell with its own random generator.

- New lever in each state's table in `game/data/storyteller.json`:

  ```json
  "weather": {
    "bias": {"clear": 1, "overcast": 1, "rain": 1, "storm": 1, "snow": 1},
    "spell_scale": 1.0
  }
  ```

  `bias` multiplies the season's transition odds; `spell_scale` multiplies spell
  length.
- Default tables:

  | State | Weather lever | Why |
  | --- | --- | --- |
  | CALM | neutral | Leave the season to itself. |
  | RISING | overcast ×1.5, rain ×1.5 | The sky darkens as trouble builds. |
  | PEAK | storm ×2.5, `spell_scale` 0.7 | Drama, and storms keep travellers off the roads. |
  | RESPITE | storm ×0, clear ×2 | Storms stop travel; relief should feel like relief. |

- `Weather` gets an optional `levers` hook (a callable, like
  `grass_fire.weather`) that returns the current weather lever. The session
  wires it to `storyteller.weather_levers()`, which returns `{}` when pacing is
  off, so pristine mode applies no weights.
- Season rules always apply: a bias cannot produce snow in summer.

### Nudges

When the storyteller changes state, it may ask the weather to **end the current
spell early** (`Weather.request_change(reason)`). The weather then rolls the next
spell with the storyteller's new weights, using its own random generator.

- A cooldown (`weather_nudge_hours` in the tuning, default 6) stops repeated
  nudges.
- Weather forced with the `weather` console command (`Weather.forced`) is never
  nudged.
- Turning the weather off in Settings (`[GAME] weather`) makes the lever and
  nudges inert.

### Receipts and the Studio

- Every weather decision the storyteller influences — a weighted roll, a nudge,
  a refused nudge (cooldown, forced, season) — gets a bounded receipt with a
  plain-English reason, e.g. "PEAK: asked the sky to change; storm weighted
  ×2.5, rolled RAIN."
- Studio's **Levers** tab gains a Weather group (bias per kind, spell scale),
  editable with the same drag controls and bounds checks. **Live** shows the
  current weather and the last weather receipt.

### Saves

- Storyteller save schema goes from version 3 to version 4. Today any other
  version resets to CALM; version 3 saves must instead be **migrated**, filling
  default weather levers and an empty nudge history.
- The weather snapshot adds the storyteller-nudge time (for the cooldown) and
  whether the current spell was nudged.

### Co-op: one sky for everyone

The host's `weather.snapshot()` is sent in the existing world update next to
`"clock"`, and clients restore it instead of rolling their own. Lightning
strikes and thunder already come from the host's simulation; check they reach
clients too.

### Tests

- With pacing off, the same seed gives byte-identical weather to a session
  without the storyteller.
- The storyteller still consumes no random numbers (its RNG state is unchanged
  across a day).
- PEAK produces measurably more storms than CALM over many seeded spells;
  RESPITE produces none.
- Nudge cooldown, forced weather and season rules are respected.
- A version 3 save loads into version 4 with its state kept.
- A co-op client shows the host's weather.

## Phase 5 — what the storyteller is doing (window and console)

**Done.** `storyteller` opens the **Storyteller — what it's doing** window;
`storyteller report [section]` prints the same report in the debug console
under the **Storyteller** category; `storyteller watch on|off` logs each
activity entry live; `storyteller studio` opens the Studio. See
[storyteller.md](storyteller.md#what-the-storyteller-is-doing). Code:
`game/storyteller_report.py`, `game/ui/storyteller_now.py`,
`Storyteller.summary()` / `activity` / `listeners`, tests in
`game/tests/test_storyteller_now.py`. Phase 4 adds weather decisions to the
activity feed and the Weather row.

## Order of work

1. **Phase 5** — small, low-risk, and makes the storyteller's behaviour visible
   before it gets new powers.
2. **Phase 1** — the shared calendar; everything else depends on it.
3. **Phase 2** — moving sun and moon, `time` command.
4. **Phase 4** — storyteller weather levers, nudges, receipts, co-op weather sync
   (the sync can ship earlier on its own; it is a bug today).
5. **Phase 3** — seasonal weather tables, snow, grass colour; seasonal trees last.

Each phase ships with headless tests and its matching updates to `RULES.md` and
the docs.

## Open questions

- **Year length.** 28 game days is about 11 real hours per year (2.8 hours per
  season). Keep it, or lengthen it so seasons last longer than a play session?
- **Night danger.** Should creatures (wolves especially) favour the night? The
  journey `kind_hours` windows already allow it; the storyteller could weight it
  per state.
- **Snow and travel.** Should deep snow slow walking or stop fast travel, as
  storms do?
- **Lunar month length** for visible moon phases.
