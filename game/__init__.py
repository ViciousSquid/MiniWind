"""
MiniWind — the integrated fantasy RPG game layer of this Fio branch.

MiniWind is **not** a plugin. It is built into the branch and always active. Its
rules and content live in :mod:`game.rpg` (engine-agnostic, unit-tested) and its
Fio wiring in :mod:`game.host` (the native game host). :func:`install` registers
that host with Fio's editor and engine and applies the MiniWind RPG editor
integration.

The plugin *system* (:mod:`plugins`) remains generic Fio technology used by
optional gameplay plugins; MiniWind no longer travels through it.
"""

from __future__ import annotations

import threading

from . import combat_styles as _combat_styles

# The engine's combat loadout learns which items are weapons from MiniWind.
_combat_styles.register()

_host_lock = threading.RLock()


def _game_host():
    """Load desktop wiring only when the application asks for its host."""
    with _host_lock:
        if "GAME" not in globals():
            from .host import MiniwindGame
            globals()["MiniwindGame"] = MiniwindGame
            globals()["GAME"] = MiniwindGame()
        return globals()["GAME"]


def __getattr__(name):
    # Pure RPG, simulation and multiplayer modules must remain usable without
    # importing Qt, OpenGL or the entire desktop runtime through this package.
    if name in ("GAME", "MiniwindGame"):
        _game_host()
        return globals()[name]
    raise AttributeError("module %r has no attribute %r" % (__name__, name))

_installed = False


def install() -> None:
    """Wire the built-in MiniWind game into Fio's editor and engine.

    Registers :data:`GAME` on the process-wide plugin manager as a *built-in
    game* (native, always-on — not a discovered/toggleable plugin) so the engine
    drives its play lifecycle and per-tick hook, then applies the editor-side RPG
    integration (title, MiniWind menu). Idempotent and fully guarded: a failure
    here must never stop the editor from starting.
    """
    global _installed
    import game.facing as _facing
    _facing.install()            # MiniWind's actors swing round, never snap
    # Registration is the manager's (idempotent, and undone between tests by
    # the suite): made whenever it is missing. The editor integration below
    # patches classes, so it is applied once.
    try:
        from plugins.manager import get_manager
        get_manager().register_builtin_game(_game_host())
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[MiniWind] game host registration skipped: {exc}")
        return
    if _installed:
        return
    _installed = True
    try:
        import game.integration as _integration
        _integration.apply()
    except Exception as exc:  # pragma: no cover - editor/PyQt may be absent
        print(f"[MiniWind] editor integration skipped: {exc}")


def launched_party():
    """The multiplayer party the launcher started, or None.

    The application bootstrap (main.py) reaches the game only through the
    module it loaded by name, never by importing ``game``: it opens the
    party's map instead of the default one and closes the party on exit
    (:func:`close_party`).
    """
    from .multiplayer.lobby import active
    return active()


def close_party() -> None:
    """Close the launcher's multiplayer party (sockets, discovery)."""
    from .multiplayer.lobby import finish
    finish()


def show_launcher(root_directory, settings_path) -> str:
    """MiniWind's startup launcher: ``"play"``, ``"edit"`` or ``"quit"``.

    Called by the application bootstrap (main.py) before the main window is
    built, when ``[Startup] show_launcher`` is on.
    """
    from .ui.launcher import launch
    return launch(root_directory, settings_path)
