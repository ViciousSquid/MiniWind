"""
The window an open chest or a searched body is shown in.

The container screen itself is painted by :mod:`game.ui.screens` (two
columns: what is in it, and what you carry). This window adds drag and drop to
it: drag a row out of the contents onto the strip, the pack or a slot of the
character window (C) to take it there; drag something from your side, the
strip or the character window onto the contents to store it. A press that does
not move is an ordinary click (take / store, the buttons).
"""

from __future__ import annotations

from PyQt5.QtCore import QPoint, Qt

from engine.floating_windows import CallbackWindow

from . import drag, hits, screens

DRAG_START = 5


class ContainerWindow(CallbackWindow):
    """A :class:`CallbackWindow` for the container screen, with drag and drop."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._press = None              # (QPoint, source) of a press on a row
        self._dragging = False

    def draw(self, painter, focused=False):
        super().draw(painter, focused)
        zones = list(screens.CONTAINER_DRAG["zones"]) if self.expanded else []
        drag.set_zones(self, zones)
        if self._dragging:
            drag.draw_ghost(painter, self, hits.pointer, 48)

    def _cell_at(self, p):
        for rect, source in reversed(screens.CONTAINER_DRAG["cells"]):
            if rect.contains(p) and source[2]:
                return source
        return None

    def handle_mouse_press(self, event):
        if not self.active:
            return False
        rect = self._full_rect()
        if not rect.contains(event.pos()):
            return False
        in_body = event.y() >= rect.y() + self.HEADER_H
        picked = drag.picked_source()
        if in_body and self.expanded and picked is not None:
            # Something picked up with a click: a click on the contents
            # stores it; any other puts it back down.
            drag.unpick()
            zone = next((t for r, t in screens.CONTAINER_DRAG["zones"]
                         if r.contains(event.pos())), None)
            if event.button() == Qt.LeftButton and zone == ("container", None) \
                    and picked[0] != "container":
                hits.queue(lambda session: session.item_drop(picked, zone))
            return True
        if in_body and self.expanded and event.button() == Qt.LeftButton:
            source = self._cell_at(event.pos())
            if source is not None:
                self._press = (QPoint(event.pos()), source)
                return True
        return super().handle_mouse_press(event)

    @property
    def mouse_captured(self):
        return self._press is not None

    def handle_mouse_move(self, event, view_w, view_h):
        if self.dragging:
            return super().handle_mouse_move(event, view_w, view_h)
        hits.pointer = (event.x(), event.y())
        if self._press is None:
            return False
        start, source = self._press
        if not self._dragging and (event.pos() - start).manhattanLength() >= DRAG_START:
            self._dragging = True
            drag.start(self, source)
        return True

    def handle_mouse_release(self, event):
        if self.dragging:
            return super().handle_mouse_release(event)
        if self._press is None:
            return False
        start, source = self._press
        self._press = None
        if not self._dragging:
            # It never moved: a click on the row (take it / store it).
            hits.click(start.x(), start.y())
            return True
        self._dragging = False
        drag.stop(self)
        target = drag.target_at(event.x(), event.y())
        if target is None:
            return True
        # Within the screen, a row let go over its own side does nothing.
        if (source[0] == "container") == (target[0] == "container") and \
                target[0] in ("container", "pack"):
            return True
        hits.queue(lambda session: session.item_drop(source, target))
        return True

    def on_close(self):
        drag.forget(self)
        super().on_close()
