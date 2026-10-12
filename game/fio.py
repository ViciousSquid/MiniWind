"""Where MiniWind finds things on Fio's logic thread.

Fio 3 split the logic thread into owned runtimes (``player_runtime``,
``camera``, ``session_runtime``, ``world_runtime``, ``combat_runtime``, ...).
Game code reaches them through these few functions rather than spelling the
runtime chain at every call site, so the next time Fio moves something only
this module changes. Every function takes the logic thread, or None (no game
running, a tool, a test without one) and then answers as if nothing were there.
"""

from __future__ import annotations

import contextlib


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


#: Fio's jump key (engine.logic_player.KEY_SPACE).
_KEY_SPACE = 0x20


def set_jump_enabled(logic, enabled) -> None:
    """Allow or forbid the player's jump.

    With it off the jump key is dropped before Fio's player update sees it --
    except in water, where the same key swims up and climbs out over a pool's
    rim, so a pool is never a trap.
    """
    runtime = getattr(logic, "player_runtime", None)
    if runtime is None:
        return
    wrapped = vars(runtime).get("update_primary")
    if enabled:
        if wrapped is not None and getattr(wrapped, "_no_jump", False):
            del runtime.update_primary
        return
    if wrapped is not None and getattr(wrapped, "_no_jump", False):
        return
    update = getattr(runtime, "update_primary", None)
    if update is None:
        return

    def update_primary(delta, keys, mouse_dx, mouse_dy):
        if _KEY_SPACE in keys:
            player = getattr(runtime, "player", None)
            if not getattr(player, "in_water", False):
                keys = set(keys)
                keys.discard(_KEY_SPACE)
        return update(delta, keys, mouse_dx, mouse_dy)

    update_primary._no_jump = True
    runtime.update_primary = update_primary


def monster_things(logic) -> list:
    """The session's actors (monsters, NPCs, creatures), as the AI sees them."""
    runtime = getattr(logic, "world_runtime", None)
    return getattr(runtime, "monster_things", None) or []


def monster_lock(logic):
    """The lock the monster AI holds while it moves actors, or None."""
    session = getattr(logic, "session_runtime", None)
    return getattr(session, "monster_lock", None)


def ground_height(logic, x, z, below=None):
    """The height of the ground at (*x*, *z*), or None where there is none.

    The terrain's surface, or the top of a solid brush (a floor, a step, a
    bridge) standing on it, whichever is higher. A brush counts only if its
    top is at or under *below*, so a roof over an actor is not its ground.
    """
    ground = None
    ter = terrain(logic)
    if ter is not None and getattr(ter, "enabled", False):
        try:
            ground = ter.get_height_at_safe(float(x), float(z))
        except Exception:
            ground = None
    session = getattr(logic, "session_runtime", None)
    grid = getattr(session, "spatial_grid", None)
    if grid is not None:
        try:
            top = grid.raycast_down(float(x), float(z),
                                    1e9 if below is None else float(below))
        except Exception:
            top = None
        if top is not None and (ground is None or top > ground):
            ground = top
    return ground


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


def projectile_tag(logic, row) -> int:
    """The tag Fio gave the projectile in *row* (0 for one without hooks)."""
    runtime = getattr(logic, "combat_runtime", None)
    store = getattr(runtime, "_monster_projectiles", None)
    lock = monster_lock(logic)
    if store is None or row is None:
        return 0
    with lock or contextlib.nullcontext():
        return int(store.tag[int(row)]) if int(row) < len(store) else 0


def projectile_count(logic) -> int:
    """How many projectiles are in flight."""
    runtime = getattr(logic, "combat_runtime", None)
    store = getattr(runtime, "_monster_projectiles", None)
    return len(store) if store is not None else 0


def set_projectile_split(logic, split) -> None:
    """Let the game draw some projectiles itself (None puts Fio's back).

    Fio draws every projectile as one shared billboard. ``split(store, count)``
    is called, under the monster lock, whenever Fio publishes the projectiles
    for a frame; it returns a boolean mask of the rows Fio should go on
    drawing (or None for all of them), and may read the rest for its own
    drawing.
    """
    runtime = getattr(logic, "combat_runtime", None)
    if runtime is None:
        return
    current = vars(runtime).get("_publish_projectile_render_snapshot")
    if current is not None and getattr(current, "_game_split", False):
        del runtime._publish_projectile_render_snapshot
    if split is None:
        return
    import numpy as np
    from engine.logic_combat import NO_PROJECTILES

    def publish():
        with monster_lock(logic) or contextlib.nullcontext():
            store = runtime._monster_projectiles
            count = len(store)
            keep = split(store, count) if count else None
            if not count:
                positions = NO_PROJECTILES
            elif keep is None:
                positions = store.pos[:count].astype(np.float32, copy=True)
            else:
                positions = store.pos[:count][keep].astype(np.float32, copy=True)
            runtime.projectile_positions = positions
            return positions

    publish._game_split = True
    runtime._publish_projectile_render_snapshot = publish


def bigworld(logic):
    """The running Big World session, or None."""
    plugins = getattr(logic, "plugins", None)
    services = getattr(plugins, "services", None)
    return services.get("bigworld") if services is not None else None


def set_bigworld_reach(logic, radius=None) -> None:
    """Let Big World's resident, simulated area reach *radius* (None: the
    map's own radius) -- a zoomed-out camera sees, and simulates, more."""
    session = bigworld(logic)
    setter = getattr(session, "set_reach", None)
    if callable(setter):
        setter(radius)


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
