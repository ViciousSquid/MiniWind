"""
Autosaves: every few minutes of play, and when a new place is discovered.

Dying used to end the game. Now the death screen offers the last autosave
(:mod:`game.ui.death_screen`), so a death costs at most a few minutes.

Saves are *delta* saves (:mod:`engine.savegame`): MiniWind ships one world,
so a save need only hold what differs from it. On the overworld, Big World
already keeps those differences per cell; in a cave the save is diffed
against the cave's map. Who the player is (the character, quests, clock)
rides along in the same file, as for a pause-menu save
(:mod:`game.ui.pause_actions`).

Two halves, one per thread:

* :class:`Autosaver` lives on the session and runs on the game tick. It
  counts play time and hears of discoveries, and decides that a save is
  *due* -- holding a timed one back while the player is in danger (hurt in
  the last :data:`SAFE_AFTER_HURT` seconds), on a menu or in conversation.
* The host, on the UI thread, carries the save out
  (:meth:`game.ui.pause_actions.PauseActions.autosave`): the engine's save
  takes the logic thread's tick lock, so the tick cannot save itself.
"""

from __future__ import annotations

import time

#: The autosave's slot name (``saves/autosave.fiosave``).
AUTOSAVE_NAME = "autosave"
#: Seconds of play between timed autosaves.
INTERVAL = 300.0
#: A discovery this soon after the last autosave does not save again.
MIN_GAP = 30.0
#: A timed save waits until the player has gone this long unhurt (seconds).
SAFE_AFTER_HURT = 15.0


class Autosaver:
    """Decides when an autosave is due (see the module docstring)."""

    def __init__(self, session, clock=time.monotonic):
        self.session = session
        self._clock = clock
        #: Seconds of play since the last autosave (or since play began).
        self.elapsed = 0.0
        #: Why a save is due ("timer", "discovered <place>"), or None.
        self.pending = None
        self._last_saved = None
        self._last_health = None
        self._hurt_at = -1e9

    # -- the tick ---------------------------------------------------------
    def tick(self, delta: float) -> None:
        """One unpaused game tick of *delta* seconds."""
        c = getattr(self.session.game, "character", None)
        if c is None or getattr(self.session, "needs_char_creation", False):
            return
        health = float(getattr(c, "health", 0.0) or 0.0)
        if self._last_health is not None and health < self._last_health - 1e-6:
            self._hurt_at = self._clock()
        self._last_health = health
        if getattr(c, "is_dead", False):
            return
        self.elapsed += max(0.0, float(delta))
        if self.elapsed >= INTERVAL and self.pending is None:
            self.pending = "timer"

    def discovered(self, place: str) -> None:
        """A new place was discovered: save, unless one was made just now."""
        now = self._clock()
        if self._last_saved is not None and now - self._last_saved < MIN_GAP:
            return
        self.pending = f"discovered {place}"

    # -- whether to save now --------------------------------------------------
    def ready(self) -> bool:
        """Whether the due save can be made now: the player alive and free
        (no menu, no conversation, no character creation), and -- for a
        timed save -- not hurt lately. A discovery saves at once."""
        if self.pending is None:
            return False
        s = self.session
        c = getattr(s.game, "character", None)
        if c is None or getattr(c, "is_dead", False) or s.needs_char_creation:
            return False
        if s.open_screen is not None or s.dialogue is not None:
            return False
        if self.pending == "timer" and self._clock() - self._hurt_at < SAFE_AFTER_HURT:
            return False
        return True

    def take(self):
        """The due save's reason, handed to whoever makes it; the timer
        starts over."""
        reason, self.pending = self.pending, None
        self.elapsed = 0.0
        self._last_saved = self._clock()
        return reason
