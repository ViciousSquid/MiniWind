"""
Character creation's window: the panel alone, with no window chrome.

Every other menu screen floats in a window that can be dragged, folded and
closed (engine/floating_windows.py). Making a character is not one of those:
it is the first thing a new player sees and the one screen that must be
finished, so it has no title bar. There is no [X], which used to finish
creation at once with every default (an "Adventurer"), no fold and no drag.
The world behind it is dimmed by the game's overlay
(game/host.py, ``_dim_behind_creation``).
"""

from __future__ import annotations

from engine.floating_windows import CallbackWindow


class CreationWindow(CallbackWindow):
    """A :class:`CallbackWindow` whose body is the whole window."""

    HEADER_H = 0

    def draw(self, painter, focused=False):
        rect = self._full_rect()
        self.window_rect.setHeight(rect.height())
        self.expanded = True
        self.draw_body(painter, rect.x(), rect.y(), rect.width())

    def handle_mouse_press(self, event):
        if not self.active:
            return False
        rect = self._full_rect()
        if not rect.contains(event.pos()):
            return False
        try:
            self.handle_body_click(event.x(), event.y())
        except Exception as exc:
            print(f"[CreationWindow] body click failed: {exc}")
        return True

    def handle_mouse_move(self, event, view_w, view_h):
        return False
