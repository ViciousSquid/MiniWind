"""Garbage-collector policy around level loads.

Loading the shipped overworld builds well over a million Python objects. With
the cyclic collector running, it triggered repeated full (generation 2)
collections in the middle of the load, each walking every one of them: about
0.8 s of every return from a cave. :func:`level_load` pauses the collector for
the load and afterwards decides what to do with the new heap:

* after a *small* level (a cave) it collects once. The level just left -- the
  overworld -- has been freed by reference counting; the collection only has
  to find its cyclic leftovers among a small live heap, so it is cheap;
* after a large level it does not collect (that would walk the whole new
  world again); any small cyclic leftovers of the level left behind are
  picked up by the next small-level load.

With *freeze* (the game turns it on, see :func:`set_freeze`), everything alive
after the load is moved to the collector's permanent generation
(:func:`gc.freeze`), so collections during play never re-traverse the static
world either, and no full collection lands in the first minutes of play. The
next load unfreezes first. The editor and the test suite leave it off: frozen
objects are never collected, which defeats leak checks.
"""

from __future__ import annotations

import contextlib
import gc
import time

#: A level with fewer brushes and entities than this counts as small.
SMALL_LEVEL_OBJECTS = 8000

_settings = {"freeze": False, "depth": 0}


def set_freeze(enabled: bool) -> None:
    """Whether loads freeze the loaded world out of later collections."""
    if _settings["freeze"] and not enabled:
        gc.unfreeze()
    _settings["freeze"] = bool(enabled)


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
                if freeze:
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
