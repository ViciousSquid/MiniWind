"""Garbage collection settled where a pause is expected, not in play.

CPython's cyclic collector runs a full (generation 2) collection whenever
the long-lived objects have grown by a quarter. A loaded world is a few
hundred thousand long-lived objects -- brush and entity dicts, their
geometry records, the tables -- and a full collection walks every one of
them: ~45 ms on BigWorld, a dropped frame or three, at a moment nobody
chose. MiniWind's shipped overworld is well over a million objects, and a
full collection of it is most of a second.

This module is the one owner of that policy. There are two entry points,
because there are two kinds of pause:

* :func:`level_load` wraps a level load. The collector is paused for the
  load (collecting in the middle of building the world walked it all,
  repeatedly). Afterwards a *small* level (a cave) is collected once: the
  level just left has been freed by reference counting, and the collection
  only has to find its cyclic leftovers among a small live heap. A large
  level is not collected -- that would walk the whole new world again; the
  leftovers wait for the next small-level load.

* :func:`settle` runs where the editor already shows a loading bar outside
  a load -- as play starts, as play stops. Inside :func:`level_load` it does
  nothing: the load's own policy above decides.

With *freeze* on (a game launch turns it on, see :func:`set_freeze`),
everything alive after a load or a settle is moved to the collector's
permanent generation (``gc.freeze``), so collections during play never
re-traverse the static world; a settle then collects only what was made
since the last freeze and freezes that too, which is cheap however large
the world is. The next load unfreezes first.

With freeze off (the editor), :func:`settle` collects everything once and
freezes the survivors, unfreezing first so a cycle among frozen objects is
found by the next settle; :func:`release` (a window closing) unfreezes, so
what it owned can be collected. A level load in the editor leaves nothing
frozen: frozen objects are never collected, which defeats leak checks.

:mod:`engine.gc_control` is the same module under MiniWind's older name.
"""

from __future__ import annotations

import contextlib
import gc
import time

#: A level with fewer brushes and entities than this counts as small.
SMALL_LEVEL_OBJECTS = 8000

#: Milliseconds the last settle took (diagnostics).
last_ms = 0.0

_settings = {"freeze": False, "depth": 0}


def set_freeze(enabled: bool) -> None:
    """Whether loads freeze the loaded world out of later collections."""
    if _settings["freeze"] and not enabled:
        gc.unfreeze()
    _settings["freeze"] = bool(enabled)


def settle() -> float:
    """Collect now and freeze the survivors; the milliseconds it took.

    Nothing inside :func:`level_load`. With freeze on, only what was made
    since the last freeze is walked; otherwise everything is.
    """
    global last_ms
    if _settings["depth"]:
        return 0.0
    started = time.perf_counter()
    if not _settings["freeze"]:
        gc.unfreeze()
    gc.collect()
    gc.freeze()
    last_ms = (time.perf_counter() - started) * 1000.0
    return last_ms


def release() -> None:
    """Unfreeze everything (the editor window is closing): what it held,
    cycles included, is collectable again."""
    gc.unfreeze()


class LoadPolicy:
    """Handed to the body of :func:`level_load`; it sets :attr:`objects`."""

    def __init__(self):
        #: Brushes + entities of the level that was loaded (None: unknown).
        self.objects = None
        self.collect_seconds = 0.0
        #: Unreachable objects the post-load collection found (None: none ran).
        self.collected = None


@contextlib.contextmanager
def level_load():
    """Pause the cyclic collector for a level load (nests safely)."""
    policy = LoadPolicy()
    outermost = _settings["depth"] == 0
    was_enabled = gc.isenabled()
    _settings["depth"] += 1
    if outermost:
        gc.disable()
    try:
        yield policy
    finally:
        _settings["depth"] -= 1
        if outermost:
            try:
                freeze = _settings["freeze"]
                # Whatever an earlier settle or load froze belongs to the
                # level left behind: it must be collectable again.
                gc.unfreeze()
                small = policy.objects is not None and policy.objects < SMALL_LEVEL_OBJECTS
                if small:
                    started = time.perf_counter()
                    policy.collected = gc.collect()
                    policy.collect_seconds = time.perf_counter() - started
                if freeze:
                    gc.freeze()
            finally:
                if was_enabled:
                    gc.enable()
