"""
The contract for a simulation subsystem the :class:`~game.sim.director.Director` owns.

A subsystem is a long-lived part of the reactive simulation with state of its
own — the storyteller's pacing, the faction actors — rather than a step of the
event pipeline. Attaching one to the director gives it the same lifecycle as
the world's event history:

* ``reset()``   -- a new world: authored starting state, nothing remembered;
* ``tick(now)`` -- after each simulation tick, at absolute world time in game
  hours (``day * 24 + hour``). A subsystem paces itself from ``now``; the
  director calls it whatever the frame rate;
* ``persist()`` / ``restore()`` -- after the history, in attachment order, so a
  restored subsystem may read a past that is already loaded.

Every hook defaults to doing nothing, so a subsystem driven from elsewhere
(the faction spine answers the living board) still shares the lifecycle.
"""

from __future__ import annotations


class SimSystem:
    #: Unique registry name; the director looks a subsystem up by it.
    name = ""

    def reset(self) -> None:
        pass

    def tick(self, now: float) -> None:
        pass

    def persist(self) -> None:
        pass

    def restore(self):
        pass
