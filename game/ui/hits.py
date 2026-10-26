"""
Clickable regions of MiniWind's on-screen menus.

The screens (:mod:`game.ui.screens`) and the conversation box
(:mod:`game.ui.dialogue_ui`) are painted with QPainter, not built from widgets,
so they say where their buttons are while they draw: each paint pass calls
:func:`begin`, every clickable thing calls :func:`add` with its rectangle and
what a click on it does, and :func:`end` publishes the set. The menus hosted
in floating windows are painted *after* the game's overlay hook has called
:func:`end` (the view draws its windows over the overlay), so :func:`end`
publishes the frame's list itself rather than a copy: whatever is added after
it, until the next :func:`begin`, still lands in the published set. Painting
and hit-testing both happen on the UI thread, so a click never sees a frame
half built. A screen that adds
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
_clicks = collections.deque(maxlen=32)

#: Where the pointer is, in view pixels (None when it has not moved yet).
pointer = None


def begin():
    """Start a paint pass with a fresh list (the last published frame stays
    published until :func:`end`)."""
    global _building
    with _lock:
        _building = []


def add(rect, action, label=None):
    """Make *rect* clickable this frame; *action(session)* runs on a click.

    *label* names the target (a button's text, say) for tests and debugging.
    A target added after :func:`end` (a menu in a floating window, painted
    after the overlay) joins the published frame.
    """
    with _lock:
        _building.append((rect, action, label))


def end():
    """Publish this frame's targets for hit-testing."""
    global _published
    with _lock:
        _published = _building


def clear():
    """No menu on screen: nothing is clickable."""
    global _published, _building
    with _lock:
        _building = []
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


def queue(action) -> None:
    """Queue *action(session)* for the game tick, like a click on a button
    (for UI that resolves its own hits, such as a drag and drop)."""
    _clicks.append(action)


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
        if session.game.character.is_dead:
            # The death screen's menu (restore, load, new game); there is no
            # live player to look around, so its buttons keep the pointer.
            from . import death_screen
            return death_screen.has_button()
        if getattr(session, "spell_aiming", False):
            return True        # aiming a spell: the cursor says where it goes
        # The character sheet, spellbook and merchant trade screen release
        # the captured mouse so their choices can be clicked. The quickbar,
        # dialogue and other game screens keep normal mouse-look captured.
        open_screen = getattr(session, "open_screen", None)
        interactive_screen = open_screen in ("character", "spells", "trade")
        # Initial character creation happens before normal play controls exist.
        needs_creation = bool(getattr(session, "needs_char_creation", False))
        return bool((interactive_screen or needs_creation) and has_targets())

    def _actor_at(self, x, y):
        pick = getattr(self.view, "actor_at", None)
        try:
            actor = pick(x, y) if pick is not None else None
        except Exception:
            actor = None
        props = getattr(actor, "properties", None)
        return actor if isinstance(props, dict) and not props.get("dead") else None

    def ground_point(self, x, y):
        """The world point under pixel (*x*, *y*) at bolt height above the
        player's feet: where a level bolt cast there would pass. None when
        the cursor looks above the horizon."""
        import glm
        view = self.view
        session = self._session()
        feet = session._player_pos() if session is not None else None
        w, h = max(1, view.width()), max(1, view.height())
        if feet is None:
            return None
        inverse = glm.inverse(view.projection_matrix * view.view_matrix)
        nx, ny = 2.0 * x / w - 1.0, 1.0 - 2.0 * y / h
        near = inverse * glm.vec4(nx, ny, -1.0, 1.0)
        far = inverse * glm.vec4(nx, ny, 1.0, 1.0)
        near, far = glm.vec3(near) / near.w, glm.vec3(far) / far.w
        ray = far - near
        plane_y = float(feet[1]) + 48.0
        if abs(ray.y) < 1e-6:
            return None
        t = (plane_y - near.y) / ray.y
        if t <= 0:
            return None
        hit = near + ray * t
        return [float(hit.x), plane_y, float(hit.z)]

    def pointer_move(self, event):
        global pointer
        pointer = (event.x(), event.y())
        self.view.update()

    def pointer_press(self, event):
        from PyQt5.QtCore import Qt
        session = self._session()
        if session is not None and getattr(session, "spell_aiming", False):
            # Left: cast there (at the creature under the cursor, else the
            # ground); right: put the spell away.
            if event.button() == Qt.LeftButton:
                actor = self._actor_at(event.x(), event.y())
                point = None if actor is not None else self.ground_point(event.x(), event.y())
                queue(lambda s, p=point, a=actor: s.cast_at(p, a))
            else:
                queue(lambda s: s.cancel_spell_aim())
            self.view.update()
            return True
        if event.button() != Qt.LeftButton:
            return True
        if session is not None and session.game.character.is_dead:
            # The tick is not running: the death screen acts here.
            from . import death_screen
            death_screen.press(self.view, event.x(), event.y())
            self.view.update()
            return True
        click(event.x(), event.y())
        self.view.update()
        return True
