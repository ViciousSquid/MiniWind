"""Where MiniWind finds things on Fio's logic thread.

Fio 3 split the logic thread into owned runtimes (``player_runtime``,
``camera``, ``session_runtime``, ``world_runtime``, ``combat_runtime``, ...).
Game code reaches them through these few functions rather than spelling the
runtime chain at every call site, so the next time Fio moves something only
this module changes. Every function takes the logic thread, or None (no game
running, a tool, a test without one) and then answers as if nothing were there.
"""

from __future__ import annotations


def things(logic) -> list:
    """The live list of the world's entities (append to it to add one)."""
    state = getattr(logic, "editor_state", None)
    found = getattr(state, "things", None)
    return found if found is not None else []


def player(logic):
    """The player, or None outside Play."""
    runtime = getattr(logic, "player_runtime", None)
    return getattr(runtime, "player", None)


def player_runtime(logic):
    """The player's runtime (health, god mode), or None."""
    return getattr(logic, "player_runtime", None)


def camera(logic):
    """The camera runtime (mode, overhead orientation, focus), or None."""
    return getattr(logic, "camera", None)


def is_overhead(logic) -> bool:
    cam = camera(logic)
    return bool(cam is not None and cam.is_overhead())


def set_camera_mode(logic, mode) -> None:
    cam = camera(logic)
    if cam is not None:
        cam.set_camera_mode(mode)


def terrain(logic):
    runtime = getattr(logic, "world_runtime", None)
    return getattr(runtime, "terrain", None)


def set_world_paused(logic, owner, paused=True) -> None:
    """Hold (or release) the world pause *owner* asks for."""
    session = getattr(logic, "session_runtime", None)
    if session is not None:
        session.set_world_paused(owner, paused)


def world_paused(logic) -> bool:
    """Whether anybody holds the world paused."""
    session = getattr(logic, "session_runtime", None)
    return bool(session is not None and session.world_paused)


def rebuild_entity_caches(logic) -> None:
    """Re-index the world after entities were added or removed in play."""
    runtime = getattr(logic, "world_runtime", None)
    if runtime is not None:
        runtime.build_entity_caches()


def find_entity_by_name(logic, name):
    runtime = getattr(logic, "world_runtime", None)
    return runtime.find_entity_by_name(name) if runtime is not None else None


def find_entity_by_id(logic, entity_id):
    runtime = getattr(logic, "world_runtime", None)
    return runtime.find_entity_by_id(entity_id) if runtime is not None else None


def spawn_projectile(logic, pos, vel, **kwargs):
    """Launch a player projectile (``LogicCombat.spawn_projectile``)."""
    runtime = getattr(logic, "combat_runtime", None)
    if runtime is None:
        return None
    return runtime.spawn_projectile(pos, vel, **kwargs)


def bigworld(logic):
    """The running Big World session, or None."""
    plugins = getattr(logic, "plugins", None)
    services = getattr(plugins, "services", None)
    return services.get("bigworld") if services is not None else None


def sim_tiers_fit_view(logic) -> bool:
    """Whether Big World's tiers are fitted to the overhead camera's screen:
    NEAR is then exactly what is on screen, and anything else resident is
    off it."""
    session = bigworld(logic)
    tiers = getattr(session, "tiers", None)
    return bool(getattr(tiers, "near_rect", None))


def cutscene_active(logic) -> bool:
    """Whether one of Fio's cutscenes (a LogicCamera) owns the view now."""
    runtime = getattr(logic, "cutscene_runtime", None)
    return bool(getattr(runtime, "state", None))
