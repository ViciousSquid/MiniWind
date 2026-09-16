"""
MiniWind's debug-console commands.

Registered through Fio's console-command surface
(``EditorAPI.register_console_command``, plugin API 1.4.0) from
:meth:`game.host.MiniwindGame.register`, so the generic console carries no
knowledge of dice, quests or the reactive simulation. Each handler receives a
:class:`plugins.api.ConsoleContext` (the live logic thread, whether a play
session is running, and the editor window) plus the raw argument string.

    diceroll | dice   roll a dice expression, optionally animated
    quest | quests    list / start / advance / complete / reset quests
    sim               inspect and drive the reactive simulation
"""

import time

try:
    from editor.debug_console import debug_log
except Exception:  # pragma: no cover - console unavailable (headless)
    def debug_log(category, message):
        print(f"[{category}] {message}")

from .diceroll import DiceRoller

_CONSOLE_DICE = None


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


#: (names, handler, help) for every command this module provides.
COMMANDS = (
    (("diceroll", "dice"), cmd_diceroll,
     "[NdM[+/-modifier]…] [--animate] — Roll dice in Editor or Play mode"),
    (("quest", "quests"), cmd_quest,
     "[list | start|advance|complete|reset <id>] — Test quests (Play Mode)"),
    (("sim",), cmd_sim,
     "[events | crimes | actors | why|knows|forget <name> | tell <name> <id> | emit …]"
     " — Reactive simulation (Play Mode)"),
)


def register(api) -> None:
    """Register every MiniWind console command on *api* (an EditorAPI)."""
    for names, handler, help_text in COMMANDS:
        for name in names:
            api.register_console_command(name, handler, help_text)
