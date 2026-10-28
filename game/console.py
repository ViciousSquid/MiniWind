"""
MiniWind's debug-console commands.

Registered through Fio's console-command surface
(``EditorAPI.register_console_command``, plugin API 1.4.0) from
:meth:`game.host.MiniwindGame.register`, so the generic console carries no
knowledge of dice, quests or the reactive simulation. Fio calls a command as
``callback(args, main_window, logic, play_mode)``; :func:`_adapt` hands each
handler here a :class:`ConsoleContext` (the live logic thread, whether a play
session is running, and the editor window) plus the raw argument string.

    diceroll | dice   roll a dice expression, optionally animated
    quest | quests    list / start / advance / complete / reset quests
    sim               inspect and drive the reactive simulation
    inspect | mind    pause and click an actor for its live mental state
    torch_shadows [on|off]   torches near you cast shadows (toggles)
    weather [auto|clear|cloudy|rain|storm|snow] [0..1]   local outdoor weather
"""

import time
import shlex
from dataclasses import dataclass
from typing import Any

try:
    from editor.debug_console import debug_log
except Exception:  # pragma: no cover - console unavailable (headless)
    def debug_log(category, message):
        print(f"[{category}] {message}")

from .diceroll import DiceRoller

_CONSOLE_DICE = None


@dataclass
class ConsoleContext:
    """What a MiniWind console handler is handed.

    ``logic_thread`` is the live play session's logic thread (None in the
    editor), ``play_mode`` whether a play session is running, and
    ``main_window`` the editor window hosting the console (None headless).
    """
    logic_thread: Any = None
    play_mode: bool = False
    main_window: Any = None


def _console_dice():
    """The editor-side roller used when no play session owns the dice."""
    global _CONSOLE_DICE
    if _CONSOLE_DICE is None:
        _CONSOLE_DICE = DiceRoller()
    return _CONSOLE_DICE


def cmd_diceroll(ctx, args):
    """Roll a dice expression and optionally show the native HUD animation."""
    tokens = str(args or "").split()
    animate = any(token.lower() in ("--animate", "animate") for token in tokens)
    notation_tokens = [token for token in tokens
                       if token.lower() not in ("--animate", "animate")]
    notation = "".join(notation_tokens) or "1d20"

    try:
        visualise = animate
        if not visualise:
            try:
                visualise = ctx.main_window.config.getboolean(
                    "GAME", "visualise_dice_rolls", fallback=False)
            except (AttributeError, TypeError, ValueError):
                visualise = False
        view_3d = getattr(ctx.main_window, "view_3d", None)
        session = getattr(ctx.logic_thread, "_miniwind", None)
        if session is not None:
            if not animate:
                session.dice_animation = None
                result = session.game.request_roll(notation, source="console")
            else:
                result = session.roll_dice(notation)
            source_label = "play session"
        else:
            view_3d = getattr(ctx.main_window, "view_3d", None)
            if view_3d is not None and not visualise:
                view_3d._editor_dice_animation = None
            result = _console_dice().request_roll(notation, source="console")
            source_label = "editor"
            if visualise:
                view_3d = getattr(ctx.main_window, "view_3d", None)
                if view_3d is not None:
                    view_3d._editor_dice_animation = {
                        "result": result,
                        "started_at": time.monotonic(),
                    }
                    view_3d.update()
                if not animate:
                    debug_log("Info", "Dice roll completed; showing editor preview from GAME settings.")
                else:
                    debug_log("Info", "Dice roll completed; showing editor preview.")

        details = ", ".join(str(value) for value in result.get("roll_details", []))
        debug_log("Roll", f"{result['dice_notation']} => total {result['roll_result']} "
                           f"(rolls: [{details}], source: {source_label}"
                           f"{', animated' if visualise else ''})")
    except (ValueError, TypeError) as exc:
        debug_log("Error", f"Dice roll failed: {exc}")


def cmd_sim(ctx, args):
    """sim [events | why <name> | knows <name> | tell <name> <id> | emit <kind> [actor] [target] [item] | crimes | forget <name>]

    Inspect and drive MiniWind's reactive simulation from the console — the
    same director the World Simulation window shows, so anything here is
    also visible there.

      sim events            the world history, newest first, with the
                            consequence each event caused
      sim crimes            crimes nobody has reported to the watch yet
      sim actors            every actor's current intent and the reason
      sim why <name>        why that actor is doing what it is doing
      sim knows <name>      what that actor believes, and how sure it is
      sim tell <name> <id>  hand an actor a belief about event <id>
      sim forget <name>     wipe an actor's knowledge
      sim emit <kind> [actor] [target] [item]
                            inject an event through the real pipeline
    """
    if not ctx.play_mode:
        debug_log("Error", "sim: enter Play Mode first.")
        return
    session = getattr(ctx.logic_thread, "_miniwind", None)
    director = getattr(session, "director", None) if session is not None else None
    if director is None:
        debug_log("Error", "sim: no active MiniWind session.")
        return
    from .sim import crime as _crime, knowledge as _know
    from .sim.director import actor_key as _key

    parts = args.split()
    sub = (parts[0].lower() if parts else "events")
    rest = parts[1:]

    def _find(name):
        want = str(name or "").strip().lower()
        for a in session._sim_actors():
            p = getattr(a, "properties", {}) or {}
            if want in (str(p.get("display_name", "")).lower(),
                        str(p.get("name", "")).lower(), _key(a)):
                return a
        return None

    if sub in ("events", "history", ""):
        lines = director.report_lines(limit=25)
        for line in lines or ["(nothing has happened yet)"]:
            debug_log("Info", line)
        return

    if sub == "crimes":
        open_crimes = _crime.unsolved(director.store, director.bus)
        for ev in open_crimes or []:
            debug_log("Info", f"#{ev.id} [{ev.timestamp()}] {ev.describe()} "
                              f"— unreported")
        if not open_crimes:
            debug_log("Info", "No unreported crimes: the watch knows about "
                              "everything that has happened.")
        return

    if sub == "actors":
        for a in session._sim_actors():
            p = getattr(a, "properties", {}) or {}
            intents = director.intents(a)
            top = intents[0] if intents else None
            debug_log("Info", f"{p.get('display_name', '?')}  "
                              f"[{p.get('sched_state', '')}]  "
                              f"{top.label if top else '—'}"
                              f"{' — ' + top.reason if top else ''}")
        return

    if sub in ("why", "knows", "forget", "tell") and not rest:
        debug_log("Error", f"sim {sub}: name an actor.")
        return

    thing = _find(rest[0]) if rest else None
    if sub in ("why", "knows", "forget", "tell") and thing is None:
        debug_log("Error", f"sim {sub}: no actor called '{rest[0]}'.")
        return

    if sub == "why":
        debug_log("Info", director.why(thing))
        for it in director.intents(thing):
            debug_log("Info", f"   {it.priority:>3}  {it.label} — {it.reason}")
        return

    if sub == "knows":
        lines = director.knowledge_lines(thing, limit=20)
        for line in lines or ["(knows nothing of note)"]:
            debug_log("Info", line)
        return

    if sub == "forget":
        _know.forget_all(director.store, _key(thing))
        director.invalidate(thing)
        debug_log("Info", f"{rest[0]} remembers nothing.")
        return

    if sub == "tell":
        if len(rest) < 2 or not rest[1].lstrip('#').isdigit():
            debug_log("Error", "sim tell <name> <event id>  (see 'sim events')")
            return
        event = director.bus.get(int(rest[1].lstrip('#')))
        if event is None:
            debug_log("Error", f"sim tell: no event #{rest[1]}.")
            return
        fact = _know.fact_from_event(event, 0.8, _know.SOURCE_TOLD)
        if event.kind == "theft":
            fact["value"] = int(event.data.get("value", 0) or 0)
        _know.learn(director.store, _key(thing), fact)
        director.invalidate(thing)
        debug_log("Info", f"{rest[0]} now believes: {event.describe()}")
        debug_log("Info", f"   -> {director.why(thing)}")
        return

    if sub == "emit":
        if not rest:
            debug_log("Error", "sim emit <kind> [actor] [target] [item]")
            return
        kind = rest[0]
        actor = _find(rest[1]) if len(rest) > 1 else None
        target = _find(rest[2]) if len(rest) > 2 else None
        data = {}
        if len(rest) > 3:
            data["item"] = rest[3]
            data["item_name"] = rest[3].replace("_", " ").title()
        event = session.emit_event(kind, actor=actor, target=target, **data)
        director.resolve_reports(session._sim_actors())
        debug_log("Info", f"#{event.id} {event.describe()}")
        for c in event.consequences:
            debug_log("Info", f"   -> {c}")
        return

    debug_log("Error", f"sim: unknown subcommand '{sub}'. Try 'sim events'.")


def cmd_quest(ctx, args):
    """quest [list | start <id> | advance <id> | complete <id> | reset <id>]

    Test MiniWind quests in Play Mode. With no argument (or 'list') it prints
    every authored quest and its live state. 'start' makes a quest active on
    the player so its stage conditions begin tracking; 'advance' bumps it to
    the next stage; 'complete' finishes it and pays the rewards; 'reset'
    clears its state so you can run it again.
    """
    if not ctx.play_mode:
        debug_log("Error", "quest: enter Play Mode first.")
        return
    session = getattr(ctx.logic_thread, "_miniwind", None)
    if session is None:
        debug_log("Error", "quest: no active MiniWind session.")
        return
    try:
        from .rpg import quests as _q
    except Exception as exc:
        debug_log("Error", f"quest: {exc}")
        return

    parts = args.split()
    sub = parts[0].lower() if parts else "list"
    qid = parts[1] if len(parts) > 1 else ""
    log = session.game.quests

    if sub in ("list", "ls", ""):
        if not _q.QUESTS:
            debug_log("Info", "No quests are defined on this map "
                              "(author them on Game Settings ▸ Quests).")
            return
        for q in _q.QUESTS.values():
            state = log.state_of(q.id) or "inactive"
            obj = log.current_objective(q.id)
            line = f"{q.id}  [{state}]"
            if state == "active" and obj:
                line += f"  — {obj}"
            debug_log("Info", line)
        return

    if not qid:
        debug_log("Error", f"quest {sub}: needs a quest id (see 'quest list').")
        return
    if _q.get(qid) is None:
        debug_log("Error", f"quest: unknown quest '{qid}' (see 'quest list').")
        return

    if sub == "start":
        if session.game.start_quest(qid):
            session.notify(f"Quest started: {_q.get(qid).name}")
            debug_log("Info", f"Started quest '{qid}'.")
        else:
            debug_log("Info", f"Quest '{qid}' is already active or complete "
                              f"(use 'quest reset {qid}' first).")
    elif sub == "advance":
        log.advance(qid)
        debug_log("Info", f"Advanced '{qid}' to stage {log.stage_of(qid)}.")
    elif sub == "complete":
        session.game.complete_quest(qid)
        debug_log("Info", f"Completed quest '{qid}' (rewards paid).")
    elif sub == "reset":
        session.store.set(f"quest.{qid}.state", "")
        session.store.set(f"quest.{qid}.stage", "-1")
        debug_log("Info", f"Reset quest '{qid}'.")
    else:
        debug_log("Error", "quest: use list | start | advance | complete | reset.")


def cmd_inspect(ctx, args):
    """inspect | mind -- pause the world and click an actor to inspect it.

    Arms Fio's Play Mode actor pick (``MainWindow.begin_actor_pick``): the
    world freezes and the cursor is freed; the next click on an NPC, creature
    or monster opens a floating debug window on it (game/ui/inspector.py):
    its schedule, where it is heading and why, and its AI state, with a line
    in the world to its destination. Esc or a right-click cancels. Play Mode
    only."""
    if not ctx.play_mode:
        debug_log("Error", "inspect: Play Mode only.")
        return None
    window = ctx.main_window

    def _open(actor):
        # The window opens on the view the pick was made in.
        from .ui import inspector
        inspector.open_inspector(getattr(window, "view_3d", None), actor)

    begin = getattr(window, "begin_actor_pick", None)
    if begin is None or not begin(_open):
        debug_log("Error", "inspect: the actor picker is not available in this view.")
        return None
    toast = getattr(ctx.main_window, "show_toast", None)
    if toast is not None:
        toast("Inspect (paused): click an actor (Esc to cancel)")
    debug_log("Info", "Inspect armed - world paused; click an actor.")
    return None


#: The world-pause request the ``pause`` command holds (its own owner, so it
#: never clashes with the menus, an inspector or the actor pick).
CONSOLE_PAUSE = "console_pause"


def cmd_pause(ctx, args):
    """pause -- freeze the world (game time, NPCs, combat) or let it run again.

    A toggle, with no pause menu: the view stays as it is, so the frozen
    scene can be looked at and inspected. Play Mode only."""
    if not ctx.play_mode or ctx.logic_thread is None:
        debug_log("Error", "pause: Play Mode only.")
        return None
    runtime = getattr(ctx.logic_thread, "session_runtime", None)
    if runtime is None:
        return None
    owners = getattr(runtime, "world_pause_owners", None)
    owners = (owners() if callable(owners) else owners) or frozenset()
    want = CONSOLE_PAUSE not in owners
    runtime.set_world_paused(CONSOLE_PAUSE, want)
    msg = "World paused (type 'pause' again to resume)." if want else "World running."
    debug_log("Info", msg)
    toast = getattr(ctx.main_window, "show_toast", None)
    if toast is not None:
        toast(msg)
    return None


def cmd_dragonfire(ctx, args):
    """dragonfire 1..5 -- which FIRE setting the dragon's breath is made of.

    The breath is a stream of the engine's FIRE Effects (game/dragon_fire.py);
    this picks their fire (fire01..fire05). The choice is remembered."""
    from .dragon_fire import FIRE_SETTINGS
    session = getattr(ctx.logic_thread, "_miniwind", None)
    fire = getattr(session, "dragon_fire", None)
    text = str(args or "").strip()
    if fire is None:
        debug_log("Error", "dragonfire: Play Mode only.")
        return None
    if not text:
        current = session.store.get("dragonfire", None)
        debug_log("Info", f"dragonfire: setting {current or 1} "
                          f"({len(fire.flames)} flames in this map). Use dragonfire 1..{FIRE_SETTINGS}.")
        return None
    try:
        setting = int(text.split()[0])
    except ValueError:
        setting = 0
    if not fire.set_setting(setting):
        debug_log("Error", f"dragonfire: pick 1..{FIRE_SETTINGS}.")
        return None
    msg = f"Dragon fire set to {setting}."
    debug_log("Info", msg)
    toast = getattr(ctx.main_window, "show_toast", None)
    if toast is not None:
        toast(msg)
    return None


def cmd_debugtools(ctx, args):
    """debugtools -- a floating window of time controls for the simulation:
    rewind, play / pause, and speed (0.25×, 0.5×, 1×, 2×). Play Mode only."""
    if not ctx.play_mode:
        debug_log("Error", "debugtools: Play Mode only.")
        return None
    view = getattr(ctx.main_window, "view_3d", None)
    from .ui import debug_tools
    if debug_tools.open_debug_tools(view) is None:
        debug_log("Error", "debugtools: no game view to open it on.")
    return None


def cmd_resurrect(ctx, args):
    """resurrect -- click an NPC or monster to bring it back to life at full
    health (a living one is healed). The world pauses while you choose; Esc
    or a right-click cancels. Play Mode only."""
    if not ctx.play_mode:
        debug_log("Error", "resurrect: Play Mode only.")
        return None
    window = ctx.main_window

    def _raise(actor):
        from . import rewind
        from .ui import hits
        hits.queue(lambda session: rewind.resurrect(session, actor))

    begin = getattr(window, "begin_actor_pick", None)
    if begin is None or not begin(_raise):
        debug_log("Error", "resurrect: the actor picker is not available in this view.")
        return None
    toast = getattr(window, "show_toast", None)
    if toast is not None:
        toast("Resurrect: click an NPC or monster (Esc to cancel)")
    return None


def cmd_torch_shadows(ctx, args):
    """torch_shadows [on|off] -- whether carried torches near you (the NEAR
    simulation distance) cast shadows. With no argument it toggles.

    The same setting as Settings > Game > Torch shadows (GAME /
    torch_shadows in settings.ini): it applies at once and is saved."""
    from . import runtime
    config = getattr(ctx.main_window, "config", None) or runtime._editor_config
    if config is None:
        debug_log("Error", "torch_shadows: no settings to change (no editor).")
        return None
    try:
        current = config.getboolean("GAME", "torch_shadows", fallback=False)
    except (AttributeError, TypeError, ValueError):
        current = False
    word = str(args or "").strip().lower()
    if word in ("on", "1", "true", "yes", "enable"):
        want = True
    elif word in ("off", "0", "false", "no", "disable"):
        want = False
    elif not word or word == "toggle":
        want = not current
    else:
        debug_log("Error", "torch_shadows: use on, off, or nothing to toggle.")
        return None
    try:
        if not config.has_section("GAME"):
            config.add_section("GAME")
        config.set("GAME", "torch_shadows", str(want))
    except Exception as exc:
        debug_log("Error", f"torch_shadows: could not change the setting ({exc}).")
        return None
    if runtime._editor_config is None:
        runtime.set_editor_config(config)        # so a running game reads it
    save = getattr(ctx.main_window, "save_config", None)
    if save is not None:
        try:
            save()
        except Exception as exc:
            debug_log("Error", f"torch_shadows: could not save the setting ({exc}).")
    msg = f"Torch shadows {'on' if want else 'off'}."
    debug_log("Info", msg)
    toast = getattr(ctx.main_window, "show_toast", None)
    if toast is not None:
        toast(msg)
    return None


def cmd_weather(ctx, args):
    """weather [auto|clear|cloudy|rain|storm|snow] [intensity 0..1].

    With no arguments, show the current weather. A named weather overrides the
    natural cycle; ``weather auto`` returns to changing weather. Effects stay
    within the top-down camera view and are hidden in cave maps.
    """
    session = getattr(ctx.logic_thread, "_miniwind", None)
    if not ctx.play_mode or session is None:
        debug_log("Error", "weather: enter Play Mode first.")
        return None
    from .ui import hits
    import math
    tokens = str(args or "").lower().split()
    if not tokens:
        weather = session.weather
        mode = "automatic" if weather.automatic else "manual"
        debug_log("Info", f"Weather: {weather.mode} ({mode}).")
        return None
    kind = tokens[0]
    if kind not in ("auto", "clear", "cloudy", "rain", "storm", "snow") or len(tokens) > 2:
        debug_log("Error", "Usage: weather [auto|clear|cloudy|rain|storm|snow] [0..1]")
        return None
    try:
        intensity = float(tokens[1]) if len(tokens) == 2 else 1.0
        if not math.isfinite(intensity) or not 0.0 <= intensity <= 1.0 or (kind == "auto" and len(tokens) > 1):
            raise ValueError
    except ValueError:
        debug_log("Error", "weather: intensity must be between 0 and 1; auto takes no intensity.")
        return None

    def apply(active_session):
        if kind == "auto":
            active_session.weather.set_auto()
        else:
            active_session.weather.set_weather(kind, intensity)
        active_session.notify("Weather: " + ("automatic" if kind == "auto" else kind))

    hits.queue(apply)
    debug_log("Info", "Weather: " + ("automatic cycle" if kind == "auto" else kind))
    return None


def cmd_roads(ctx, args):
    """roads -- who is travelling the roads right now, and where.

    Lists every party on the living world's board (game/living): kind, leader,
    whether they are walking or resting, origin and destination, where the
    clock puts them, and which are near enough to be actors ([LIVE])."""
    session = getattr(ctx.logic_thread, "_miniwind", None)
    living = getattr(session, "living", None)
    if living is None:
        debug_log("Error", "roads: the living world is not running (Play Mode on a map "
                  "with places).")
        return None
    for line in living.summary():
        debug_log("Info", line)
    return None


def cmd_paths(ctx, args):
    """paths [on|off|panel|report|reset|export [file]|state <kind>|tier <layer>|actor <name>|radius <units>|labels on|off].

    Toggle real-time pathfinding diagnostics; filter by actor, route state or
    distance. ``paths panel`` opens controls. ``paths export`` saves the same
    structured report available through game.pathfinding_debug.report(session).
    """
    session = getattr(ctx.logic_thread, "_miniwind", None)
    if session is None or not ctx.play_mode:
        debug_log("Error", "paths: enter Play Mode first.")
        return None
    from . import pathfinding_debug as debug
    try:
        tokens = shlex.split(str(args or ""))
        command = tokens[0].lower() if tokens else "toggle"
        rest = tokens[1:]
        if command in ("on", "off", "toggle", "1", "0", "true", "false") and not rest:
            enabled = (not getattr(session, "show_paths", False) if command == "toggle"
                       else command in ("on", "1", "true"))
            debug.configure(session, enabled=enabled)
        elif command == "panel" and not rest:
            from .ui.path_debug import open_panel
            if open_panel(getattr(ctx.main_window, "view_3d", None)) is None:
                debug_log("Error", "paths panel: no game view available.")
                return None
            debug.configure(session, enabled=True)
        elif command == "state" and len(rest) == 1:
            debug.configure(session, state=rest[0].lower())
        elif command == "tier" and len(rest) == 1:
            debug.configure(session, tier=rest[0].lower())
        elif command == "actor" and rest:
            debug.configure(session, actor="" if rest == ["all"] else " ".join(rest))
        elif command == "radius" and len(rest) == 1:
            debug.configure(session, radius=float(rest[0]))
        elif command == "labels" and rest in (["on"], ["off"]):
            debug.configure(session, labels=rest == ["on"])
        elif command == "reset" and not rest:
            session.nav.reset_search_stats()
            debug_log("Info", "Pathfinding observation counters reset; active routes retained.")
            return None
        elif command in ("report", "stats") and not rest:
            snapshot = debug.report(session)
            debug_log("Info", f"Pathfinding {'on' if snapshot['enabled'] else 'off'}: {snapshot['summary']}")
            for actor in snapshot["actors"]:
                debug_log("Info", f"{actor['name']} [{actor['key']}] {actor['tier']} {actor['state']}: "
                          f"{actor.get('searches', 0)} searches, "
                          f"{actor.get('searches_per_second', 0):.2f}/s, "
                          f"{actor.get('failed_searches', 0)} failed; "
                          f"{actor['decision']}; last={actor.get('last_search')}")
            return None
        elif command == "export" and len(rest) <= 1:
            path = debug.export(session, *rest)
            debug_log("Info", f"Pathfinding report saved to {path} (schema version 1).")
            return None
        else:
            raise ValueError("use on|off|panel|report|reset|export [file]|state all|route|failed|direct|chase|"
                             "tier all|near|active|distant|dormant|actor <name or id>|actor all|"
                             "radius <units>|labels on|off")
    except (ValueError, OSError) as exc:
        debug_log("Error", f"paths: {exc}")
        return None
    config = debug.settings(session)
    debug_log("Info", f"Pathfinding {'on' if getattr(session, 'show_paths', False) else 'off'}; "
              f"state={config.state}, tier={config.tier}, actor={config.actor or 'all'}, "
              f"radius={config.radius:g}. "
              "Cyan=route, yellow=direct, orange=chase, red=failed. "
              "Use 'paths panel', 'paths report' or 'paths export'.")
    return None


def cmd_searchradius(ctx, args):
    """searchradius 1|0 -- show or hide the search circle and its orbiting label."""
    session = getattr(ctx.logic_thread, "_miniwind", None)
    if session is None or not ctx.play_mode:
        debug_log("Error", "searchradius: enter Play Mode first.")
        return None
    text = str(args or "").strip()
    if text not in ("0", "1"):
        debug_log("Error", "Usage: searchradius 1 (show) or searchradius 0 (hide).")
        return None
    session.store.set("law.searchradius", text)
    view = getattr(ctx.main_window, "view_3d", None)
    menu = getattr(view, "play_menu", None)
    page = getattr(menu, "map", None)
    if page is not None:
        page.refresh()
    if view is not None:
        view.update()
    debug_log("Info", "Search radius " + ("shown." if text == "1" else "hidden."))
    return None


#: (names, handler, help) for every command this module provides.
COMMANDS = (
    (("diceroll", "dice"), cmd_diceroll,
     "[NdM[+/-modifier]…] [--animate] — Roll dice in Editor or Play mode"),
    (("quest", "quests"), cmd_quest,
     "[list | start|advance|complete|reset <id>] — Test quests (Play Mode)"),
    (("sim",), cmd_sim,
     "[events | crimes | actors | why|knows|forget <name> | tell <name> <id> | emit …]"
     " — Reactive simulation (Play Mode)"),
    (("inspect", "mind"), cmd_inspect,
     "— Pause and click an actor: schedule, destination, AI state (Play Mode)"),
    (("paths", "pathfinding"), cmd_paths,
     "[on|off|panel|report|reset|export [file]|state <kind>|tier <layer>|actor <name>|radius <units>|labels on|off]"
     " — Live pathfinding diagnostics (Play Mode)"),
    (("searchradius",), cmd_searchradius,
     "1|0 — Show or hide the search circle and orbiting Searching label (saved)"),
    (("roads", "travellers"), cmd_roads,
     "— List the parties on the roads: who, where from/to, where now (Play Mode)"),
    (("weather",), cmd_weather,
     "[auto|clear|cloudy|rain|storm|snow] [0..1] — Outdoor weather in the camera view (saved)"),
    (("debugtools", "debug"), cmd_debugtools,
     "— Time controls (rewind, play/pause, speed) and teleport to any cave (Play Mode)"),
    (("resurrect",), cmd_resurrect,
     "— Click an NPC or monster to restore it to life and full health (Play Mode)"),
    (("dragonfire",), cmd_dragonfire,
     "1..5 — Which FIRE setting the dragon breathes (remembered)"),
    (("torch_shadows",), cmd_torch_shadows,
     "[on|off] — Torches near you cast shadows; no argument toggles (saved)"),
    (("pause", "freeze"), cmd_pause,
     "— Toggle freezing the world (time, NPCs, combat); no pause menu (Play Mode)"),
)


def _adapt(handler):
    """Fio's ``callback(args, main_window, logic, play_mode)`` -> ``handler(ctx, args)``."""
    def callback(args, main_window=None, logic=None, play_mode=False):
        ctx = ConsoleContext(logic_thread=logic, play_mode=bool(play_mode),
                             main_window=main_window)
        return handler(ctx, args or "")
    callback.__doc__ = handler.__doc__
    return callback


def register(api) -> None:
    """Register every MiniWind console command on *api* (an EditorAPI)."""
    for names, handler, help_text in COMMANDS:
        for name in names:
            api.register_console_command(name, _adapt(handler), help_text)
