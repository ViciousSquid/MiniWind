"""
MiniWind — the integrated fantasy RPG game layer of this Fio branch.

MiniWind is **not** a plugin. It is built into the branch and always active. Its
rules and content live in :mod:`game.rpg` (engine-agnostic, unit-tested) and its
Fio wiring in :mod:`game.host` (the native game host). :func:`install` registers
that host with Fio's editor and engine and applies the MiniWind RPG editor
integration.

The plugin *system* (:mod:`plugins`) remains generic Fio technology used by
optional plugins such as BigWorld; MiniWind no longer travels through it.
"""

from __future__ import annotations

from .host import MiniwindGame

#: The process-wide built-in game instance.
GAME = MiniwindGame()

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
    if _installed:
        return
    _installed = True
    try:
        from plugins.manager import get_manager
        get_manager().register_builtin_game(GAME)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[MiniWind] game host registration skipped: {exc}")
        return
    try:
        from . import integration as _integration
        _integration.apply()
    except Exception as exc:  # pragma: no cover - editor/PyQt may be absent
        print(f"[MiniWind] editor integration skipped: {exc}")
