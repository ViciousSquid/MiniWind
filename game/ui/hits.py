"""
Clickable regions of MiniWind's on-screen menus.

The screens (:mod:`game.ui.screens`) and the conversation box
(:mod:`game.ui.dialogue_ui`) are painted with QPainter, not built from widgets,
so they say where their buttons are while they draw: each paint pass calls
:func:`begin`, every clickable thing calls :func:`add` with its rectangle and
what a click on it does, and :func:`end` publishes the set. A screen that adds
anything is a screen the mouse can use, so the view shows the cursor for it
(see :class:`GamePointer`).

Painting happens on the UI thread; the menus' state belongs to the game tick,
which already handles their keys. So a click is only *queued* here
(:func:`click`) and carried out by :func:`run_clicks` from the tick, in order
with the keys. Hover is cosmetic and stays on the UI thread.
"""

from __future__ import annotations

import collections
import threading

_lock = threading.Lock()
_building = []          # targets of the frame being painted
_published = []         # last finished frame: [(QRect, action, label)]
_clicks = collections.deque(maxlen=16)

#: Where the pointer is, in view pixels (None when it has not moved yet).
pointer = None


def begin():
    """Start a paint pass: forget the previous frame's targets being built."""
    del _building[:]


def add(rect, action, label=None):
    """Make *rect* clickable this frame; *action(session)* runs on a click.

    *label* names the target (a button's text, say) for tests and debugging.
    """
    _building.append((rect, action, label))


def end():
    """Publish this frame's targets for hit-testing."""
    global _published
    with _lock:
        _published = list(_building)


def clear():
    """No menu on screen: nothing is clickable."""
    global _published
    del _building[:]
    with _lock:
        _published = []
        _clicks.clear()


def has_targets() -> bool:
    return bool(_published)


def targets():
    """``[(QRect, label)]`` of the last published frame, in paint order."""
    with _lock:
        return [(rect, label) for rect, _action, label in _published]


def hovered(rect) -> bool:
    """True when the pointer is over *rect* (for highlighting while drawing)."""
    p = pointer
    if p is None:
        return False
    from PyQt5.QtCore import QPoint
    return rect.contains(QPoint(int(p[0]), int(p[1])))


def action_at(x, y):
    """The action of the topmost target under (x, y), or None."""
    from PyQt5.QtCore import QPoint
    point = QPoint(int(x), int(y))
    with _lock:
        published = list(_published)
    for rect, action, _label in reversed(published):
        if rect.contains(point):
            return action
    return None


def click(x, y):
    """Queue a click for the game tick. True when it landed on a target."""
    action = action_at(x, y)
    if action is None:
        return False
    _clicks.append(action)
    return True


def run_clicks(session) -> int:
    """Carry out the queued clicks against *session* (from the game tick)."""
    done = 0
    while _clicks:
        action = _clicks.popleft()
        try:
            action(session)
        except Exception:
            import traceback
            traceback.print_exc()
        done += 1
    return done


class GamePointer:
    """The view's ``game_pointer`` (see ``QtGameView.game_pointer``).

    Wants the pointer whenever the game has a menu on screen with something
    to click; then the view shows the arrow cursor and hands it the mouse.
    """

    def __init__(self, view):
        self.view = view

    def _session(self):
        return getattr(getattr(self.view, "logic_thread", None), "_miniwind", None)

    def wants_pointer(self) -> bool:
        session = self._session()
        if session is None:
            return False
        menu_up = (session.needs_char_creation or session.open_screen is not None
                   or session.dialogue is not None)
        return bool(menu_up and has_targets())

    def pointer_move(self, event):
        global pointer
        pointer = (event.x(), event.y())
        self.view.update()

    def pointer_press(self, event):
        from PyQt5.QtCore import Qt
        if event.button() != Qt.LeftButton:
            return True
        click(event.x(), event.y())
        self.view.update()
        return True
