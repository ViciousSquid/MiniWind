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

    #: It draws what it picked up (a split stack) itself, over its own body.
    draws_picked = True

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
        picked = drag.picked_source()
        if picked is not None and drag.picked.get("owner") is self and hits.pointer:
            # Half a stack split off here rides beside the pointer.
            drag.draw_ghost(painter, self, (hits.pointer[0] + 22, hits.pointer[1] + 22),
                            40, source=picked)

    def _cell_at(self, p):
        for rect, source in reversed(screens.CONTAINER_DRAG["cells"]):
            if rect.contains(p) and source[2]:
                return source
        return None

    @staticmethod
    def _zone_at(p):
        """The drop target under *p*: a contents card, else a column."""
        for rect, target in reversed(screens.CONTAINER_DRAG["zones"]):
            if rect.contains(p):
                return target
        return None

    def _split_at(self, p):
        """``(source, half)`` for a right click on a stack of two or more."""
        for rect, source, qty in reversed(screens.CONTAINER_DRAG.get("stacks", [])):
            if rect.contains(p) and source[2]:
                half = drag.split_half(qty)
                return (tuple(source[:3]) + (half,), half) if half else None
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
            # stores it (or, half a stack split off the contents, moves it
            # there); one on your side takes what came from the contents;
            # any other puts it back down.
            drag.unpick()
            zone = self._zone_at(event.pos())
            if event.button() == Qt.LeftButton and zone is not None:
                split = len(picked) > 3 and bool(picked[3])
                from_here = picked[0] == "container"
                if zone[0] == "container" and (not from_here or split):
                    hits.queue(lambda session: session.item_drop(picked, zone))
                elif zone[0] == "pack" and from_here:
                    hits.queue(lambda session: session.item_drop(picked, ("pack", None)))
            return True
        if in_body and self.expanded and event.button() == Qt.RightButton:
            # A right click on a stack splits it: half of it is picked up.
            hit = self._split_at(event.pos())
            if hit is not None:
                drag.pick(self, hit[0])
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
