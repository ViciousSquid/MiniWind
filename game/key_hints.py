"""
Key hints after character creation: the I key over "Inventory", then the P
key over "Spellbook".

The moment a new character starts to play, the inventory key is shown in the
middle of the screen -- the key's picture (128 x 128) with its word under it --
fading in, held, then fading out. A character who starts with spells (some
builds are given them; ``known_spells``) is then shown the spellbook key the
same way, and a Mage always is -- never a Warrior or a Barbarian, who never have magic
(``classes.can_use_magic``). Only one hint is ever up at a time:

* the inventory hint starts as soon as play is first in view (no menu up --
  the experimental tutorial's pages, if ticked, come first);
* the spellbook hint starts at ``max(start + SPELLBOOK_DELAY, the moment the
  inventory hint ended)``, the inventory hint's own start being ``start``;
* pressing a hint's key (its bound action, so a rebinding counts) while the
  hint is up hides it at once, without a fade; pressed before its hint has
  shown, the hint is skipped. Opening the inventory or the spellbook any
  other way (a click) counts as pressing its key.

Time is real (monotonic) time, never game time: Slow Time does not stretch a
hint. A hint that has started keeps its clock while a menu, a conversation or
the pause menu is up, and is simply not drawn meanwhile; a hint that has not
started yet waits for play to be in view again.

Not for a loaded save or CONTINUE: only :meth:`MiniwindSession.begin_new_character`
arms the hints. Drawn by :func:`game.ui.hud.draw_key_hints`.
"""

from __future__ import annotations

import threading
import time

#: A hint's life (seconds): fading in, held, fading out.
FADE_IN, HOLD, FADE_OUT = 0.5, 2.0, 0.5
DURATION = FADE_IN + HOLD + FADE_OUT
#: The spellbook hint comes no sooner than this long after the inventory
#: hint began (and never while it is up).
SPELLBOOK_DELAY = 3.0

#: (bindable action, the word under its key), in the order they show.
INVENTORY = ("inventory", "Inventory")
SPELLBOOK = ("spells", "Spellbook")


def alpha_at(age: float) -> float:
    """A hint's opacity *age* seconds after it began (0 outside its life)."""
    if age < 0.0 or age >= DURATION:
        return 0.0
    if age < FADE_IN:
        return age / FADE_IN
    if age < FADE_IN + HOLD:
        return 1.0
    return max(0.0, (DURATION - age) / FADE_OUT)


def key_letter(action: str) -> str:
    """The key *action* is bound to now, as the hint names it (``"I"``)."""
    import game.keybinds as keybinds
    key = keybinds.key_binding(action)
    return keybinds.label(key) if key else "?"


class KeyHints:
    """The queue of hints for one new character. Thread-safe: key presses
    arrive from the logic tick, frames from the paint pass."""

    def __init__(self, magic: bool):
        self.queue = [INVENTORY] + ([SPELLBOOK] if magic else [])
        self._lock = threading.Lock()
        #: When play first came into view (the inventory hint's start).
        self.t0 = None
        #: Index into :attr:`queue` of the hint now running or next due.
        self.index = 0
        #: When the hint at :attr:`index` started (None: not yet).
        self.started = None
        #: When the previous hint ended (faded out, hidden or skipped).
        self.ended = None
        #: Actions whose key was pressed (or screen opened) since arming.
        self.used = set()
        #: Since when play has been in view without a break (None: not now).
        self._free_since = None

    # -- state ------------------------------------------------------------
    @property
    def done(self) -> bool:
        return self.index >= len(self.queue)

    def _earliest(self):
        """When the hint at :attr:`index` may start."""
        if self.index == 0:
            return self.t0
        return max(self.t0 + SPELLBOOK_DELAY, self.ended if self.ended is not None else self.t0)

    def _finish(self, at: float) -> None:
        self.ended = at
        self.index += 1
        self.started = None

    def _advance(self, now: float) -> None:
        """Bring the queue up to *now*: end hints whose time is up, start or
        skip the next one when it is due and play is in view."""
        if self.t0 is None:
            return
        while not self.done:
            action = self.queue[self.index][0]
            if self.started is not None:
                if now - self.started >= DURATION:
                    self._finish(self.started + DURATION)
                    continue
                return
            earliest = self._earliest()
            if action in self.used:
                self._finish(earliest)          # its key came first: skipped
                continue
            if self._free_since is None:
                return
            start = max(earliest, self._free_since)
            if now < start:
                return
            self.started = start
            return

    # -- input --------------------------------------------------------------
    def begin(self, now: float) -> None:
        """Play is in view for the first time: the inventory hint starts."""
        with self._lock:
            if self.t0 is None:
                self.t0 = now
                self._free_since = now
            self._advance(now)

    def press(self, action: str, now: float = None) -> None:
        """The key for *action* was pressed: its hint goes at once (no fade),
        or never shows if it has not yet."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._advance(now)
            self.used.add(action)
            if (not self.done and self.started is not None
                    and self.queue[self.index][0] == action):
                self._finish(now)
            self._advance(now)

    def frame(self, now: float = None, free: bool = True):
        """One frame at *now*, with play in view (*free*) or covered by a
        menu. Returns ``(action, caption, alpha)`` for the hint to draw, or
        None (nothing up, or play not in view)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            if free:
                if self.t0 is None:
                    self.t0 = now
                if self._free_since is None:
                    self._free_since = now
            else:
                self._free_since = None
            self._advance(now)
            if not free or self.done or self.started is None:
                return None
            alpha = alpha_at(now - self.started)
            if alpha <= 0.0:
                return None
            action, caption = self.queue[self.index]
            return action, caption, alpha

    def showing(self, now: float = None):
        """The action whose hint is running at *now* (drawn or not), or None."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._advance(now)
            if self.done or self.started is None:
                return None
            return self.queue[self.index][0]


def arm(session) -> None:
    """A new character begins: queue its hints on *session*."""
    try:
        character = session.game.character
        # A Mage always; anyone else with spells to show it for -- but never
        # a Warrior (or Barbarian): they never have magic, whatever they carry.
        magic = bool(character.can_use_magic()) and (
            str(getattr(character, "class_id", "") or "").lower() == "mage"
            or bool(character.known_spells))
    except Exception:
        magic = False
    session.key_hints = KeyHints(magic)


#: Screens that count as their hint's key having been pressed.
SCREEN_ACTIONS = {"inventory": "inventory", "spells": "spells"}


def note_keys(session, just, keys, now: float = None) -> None:
    """Key names newly pressed this tick (*just*); *keys* maps each hinted
    action to the key it is bound to now."""
    hints = getattr(session, "key_hints", None)
    if hints is None or hints.done or getattr(session, "needs_char_creation", False):
        return
    for action, key in keys.items():
        if key and key in just:
            hints.press(action, now)


def is_free(session) -> bool:
    """Whether play is in view: no menu, conversation, death or pause."""
    if getattr(session, "needs_char_creation", False):
        return False
    if session.open_screen is not None or session.dialogue is not None:
        return False
    try:
        if session.game.character.is_dead:
            return False
    except Exception:
        pass
    try:
        from . import fio
        if fio.world_paused(session.logic):
            return False
    except Exception:
        pass
    return True


def current(session, now: float = None):
    """The hint to draw this frame for *session*, ``(letter, caption, alpha)``,
    or None. Opening the inventory or spellbook counts as its key."""
    hints = getattr(session, "key_hints", None)
    if hints is None:
        return None
    now = time.monotonic() if now is None else now
    screen = getattr(session, "open_screen", None)
    if screen in SCREEN_ACTIONS and SCREEN_ACTIONS[screen] not in hints.used:
        hints.press(SCREEN_ACTIONS[screen], now)
    shown = hints.frame(now, is_free(session))
    if hints.done:
        session.key_hints = None
    if shown is None:
        return None
    action, caption, alpha = shown
    return key_letter(action), caption, alpha
