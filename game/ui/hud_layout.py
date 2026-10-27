"""
Where the HUD's panels sit, and which are folded away.

Every HUD panel but the status frame (the minimap and the bars on it, which
always stay top left) can be

* **collapsed** with the ▼ button on its top-right corner, leaving a small
  "▲ name" tab in its place that restores it, and
* **moved** in *rearrange mode* (pause menu › Options › Rearrange HUD), where
  every panel is outlined, the world is paused, and a panel is dragged by
  grabbing it anywhere.

A panel's draw function keeps drawing at its usual spot and returns the
rectangle it drew; :func:`panel` translates the painter by the panel's offset
around that call and remembers the rectangle, which is what the buttons, the
tabs and the outlines are placed by. Offsets are kept relative to the usual
spot, so a layout survives a change of resolution, and every panel is held
inside the view however it was left.

The layout is a player preference, not part of a saved game: it lives in
``settings.ini`` under ``[HUD] layout`` as JSON.
"""

from __future__ import annotations

import json

from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPen

from engine.floating_windows import FloatingWindow

from . import theme as T

#: The movable panels, in the order rearrange mode lists them: id -> name.
PANELS = {
    "active": "Weapon & spell",
    "clock": "Clock",
    "quest": "Quest",
    "compass": "Compass",
    "law": "Bounty",
    "target": "Target",
    "status": "Status",
    "dice": "Dice",
    "rolls": "Roll log",
    "toasts": "Messages",
    "strip": "Inventory",
}

#: The ▼ / ▲ button's size, and a collapsed tab's height (px).
BUTTON = 16
TAB_H = 20

#: The status flags' height above the bottom edge, clear of the inventory strip.
STATUS_BOTTOM = 124

#: id -> {"dx", "dy", "collapsed", "rect"}: the saved layout.
_state = {}
#: id -> the QRect each panel last drew at its usual spot (this run).
_rects = {}
#: id -> the frame each panel was last drawn in (:func:`begin_frame`).
_drawn = {}
_frame = 0
_config = None
_save_config = None

#: Rearrange mode is on.
arranging = False


# ---------------------------------------------------------------- settings
def configure(config, save=None) -> None:
    """Read the layout from the editor's settings (and how to write them)."""
    global _config, _save_config
    _config, _save_config = config, save
    _state.clear()
    try:
        raw = config.get("HUD", "layout", fallback="") if config is not None else ""
        data = json.loads(raw) if raw else {}
    except (ValueError, TypeError, AttributeError):
        data = {}
    for pid, entry in (data.items() if isinstance(data, dict) else ()):
        if pid in PANELS and isinstance(entry, dict):
            _state[pid] = {"dx": int(entry.get("dx", 0)), "dy": int(entry.get("dy", 0)),
                           "collapsed": bool(entry.get("collapsed", False)),
                           "rect": list(entry.get("rect") or [])[:4]}


def save() -> None:
    """Write the layout back to ``settings.ini``."""
    config = _config
    if config is None:
        return
    try:
        if not config.has_section("HUD"):
            config.add_section("HUD")
        config.set("HUD", "layout", json.dumps(_state, sort_keys=True))
        if _save_config is not None:
            _save_config()
    except Exception:
        pass


def reset() -> None:
    """Every panel back where it started, and unfolded."""
    _state.clear()
    save()


def _entry(pid):
    return _state.setdefault(pid, {"dx": 0, "dy": 0, "collapsed": False, "rect": []})


def collapsed(pid) -> bool:
    return bool(_state.get(pid, {}).get("collapsed"))


def toggle(pid) -> None:
    """Fold *pid* away, or bring it back."""
    e = _entry(pid)
    e["collapsed"] = not e["collapsed"]
    r = _rects.get(pid)
    if r is not None:
        e["rect"] = [r.x(), r.y(), r.width(), r.height()]
    save()


def offset(pid):
    e = _state.get(pid)
    return (int(e["dx"]), int(e["dy"])) if e else (0, 0)


def _clamped(rect, dx, dy, width, height):
    """(dx, dy), pulled in so *rect* moved by them stays inside the view."""
    if rect is None or width <= 0 or height <= 0:
        return dx, dy
    dx = max(-rect.x(), min(dx, width - rect.x() - rect.width()))
    dy = max(-rect.y(), min(dy, height - rect.y() - rect.height()))
    return int(dx), int(dy)


def move_to(pid, dx, dy, width, height) -> None:
    """Set *pid*'s offset from its usual spot (kept on screen)."""
    e = _entry(pid)
    e["dx"], e["dy"] = _clamped(natural_rect(pid, width, height), int(dx), int(dy),
                                width, height)


# ----------------------------------------------------------------- drawing
def begin_frame() -> None:
    """A new HUD frame: panels drawn from here on are on screen now."""
    global _frame
    _frame += 1


def panel(painter, pid, draw, width, height):
    """Draw panel *pid* with ``draw()`` (which returns the QRect it drew at its
    usual spot, or None when it drew nothing) moved to where the player put
    it. Nothing is drawn while the panel is collapsed."""
    if collapsed(pid):
        return None
    dx, dy = _clamped(_rects.get(pid), *offset(pid), width, height)
    painter.save()
    try:
        painter.translate(dx, dy)
        rect = draw()
    finally:
        painter.restore()
    note(pid, rect)
    return rect


def note(pid, rect) -> None:
    """Record that *pid* drew *rect* (its usual spot) this frame -- for a panel
    that applies its own offset, such as the inventory strip."""
    if rect is not None and not rect.isEmpty():
        _rects[pid] = QRect(rect)
        _drawn[pid] = _frame


def visible(pid) -> bool:
    """Whether *pid* is on screen this frame."""
    return _drawn.get(pid) == _frame and not collapsed(pid)


def natural_rect(pid, width, height):
    """Where *pid* sits before it is moved: as last drawn, else as saved,
    else a fair guess (for rearrange mode, before a transient panel has ever
    shown)."""
    r = _rects.get(pid)
    if r is not None:
        return QRect(r)
    saved = _state.get(pid, {}).get("rect")
    if saved and len(saved) == 4:
        return QRect(*[int(v) for v in saved])
    return _default_rect(pid, width, height)


def _default_rect(pid, w, h):
    return {
        "active": QRect(w - 284, 132, 268, 60),
        "clock": QRect(w - 104, 14, 88, 107),
        "quest": QRect(w - 304, 32, 192, 56),
        "compass": QRect(w // 2 - 130, 14, 260, 22),
        "law": QRect(w // 2 - 170, 56, 340, 51),
        "target": QRect(w // 2 - 220, 44, 440, 50),
        "status": QRect(w // 2 - 90, h - STATUS_BOTTOM, 180, 20),
        "dice": QRect(w - 398, h - 100 - 236, 380, 236),
        "rolls": QRect(16, h - 128 - 90, 330, 90),
        "toasts": QRect(w // 2 - 200, 46, 400, 38),
        "strip": QRect(w // 2 - 300, h - 96, 600, 90),
    }.get(pid, QRect(w // 2 - 60, h // 2 - 20, 120, 40))


def screen_rect(pid, width, height):
    """Where *pid* is on screen now (its usual spot moved by its offset)."""
    r = natural_rect(pid, width, height)
    dx, dy = _clamped(r, *offset(pid), width, height)
    return r.translated(dx, dy)


def button_rect(pid, width, height):
    """The ▼ button: just right of the panel's top-right corner, so it covers
    none of it -- or inside the corner, against the right edge of the view."""
    r = screen_rect(pid, width, height)
    if r.right() + 2 + BUTTON <= width:
        return QRect(r.right() + 2, r.top(), BUTTON, BUTTON)
    return QRect(r.right() - BUTTON + 1, r.top(), BUTTON, BUTTON)


def tab_rect(pid, width, height):
    """A collapsed panel's "▲ name" tab, at the panel's top-left corner."""
    r = screen_rect(pid, width, height)
    w = QFontMetrics(T.font(8, bold=True, family="Segoe UI")).horizontalAdvance(
        "▲ " + PANELS[pid]) + 14
    x = max(0, min(r.left(), width - w))
    return QRect(x, max(0, min(r.top(), height - TAB_H)), w, TAB_H)


def banner_rect(width, height):
    """Rearrange mode's instructions, centred in the view."""
    return QRect(width // 2 - 230, height // 2 - 46, 460, 108)


def arrange_buttons(width, height):
    """Rearrange mode's [Reset] and [Done], centred in the view."""
    cx, cy = width // 2, height // 2
    return {"reset": QRect(cx - 130, cy + 22, 120, 30),
            "done": QRect(cx + 10, cy + 22, 120, 30)}


def hit(pos, width, height):
    """What a click at *pos* does: ``("toggle", id)``, ``("drag", id)`` (in
    rearrange mode), ``("done",)``, ``("reset",)`` -- or None."""
    if arranging:
        for name, rect in arrange_buttons(width, height).items():
            if rect.contains(pos):
                return (name,)
        if banner_rect(width, height).contains(pos):
            return None
    for pid in reversed(list(PANELS)):
        if collapsed(pid):
            if tab_rect(pid, width, height).contains(pos):
                return ("toggle", pid)
        elif (arranging or visible(pid)) and button_rect(pid, width, height).contains(pos):
            return ("toggle", pid)
    if arranging:
        for pid in reversed(list(PANELS)):
            if not collapsed(pid) and screen_rect(pid, width, height).contains(pos):
                return ("drag", pid)
    return None


def _hovered(rect, pointer):
    return pointer is not None and rect.contains(QPoint(int(pointer[0]), int(pointer[1])))


def draw_chrome(painter, width, height, pointer=None, dragging=None):
    """The buttons, tabs and (in rearrange mode) outlines, over everything."""
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    font = T.font(8, bold=True, family="Segoe UI")
    if arranging:
        painter.fillRect(QRect(0, 0, width, height), QColor(0, 0, 0, 70))
    for pid, name in PANELS.items():
        if collapsed(pid):
            tab = tab_rect(pid, width, height)
            hot = _hovered(tab, pointer)
            painter.setPen(QPen(QColor(168, 142, 84, 230 if hot else 170), 1))
            painter.setBrush(QColor(12, 11, 18, 230 if hot else 190))
            painter.drawRoundedRect(tab, 5, 5)
            T.text_in(painter, tab, "▲ " + name, size=8,
                      color=T.GOLD_BRIGHT if hot else T.PARCH,
                      align=T.ALIGN_CENTER, bold=True, family="Segoe UI")
            continue
        if arranging:
            r = screen_rect(pid, width, height)
            live = pid == dragging or _hovered(r, pointer)
            painter.setPen(QPen(QColor(255, 214, 130, 255 if live else 170), 1.5,
                                Qt.DashLine))
            painter.setBrush(QColor(255, 214, 130, 40 if live else 18))
            painter.drawRect(r)
            painter.setFont(font)
            painter.setPen(QColor(255, 214, 130))
            painter.drawText(r.adjusted(4, 2, -BUTTON - 2, 0),
                             int(Qt.AlignLeft | Qt.AlignTop), name)
        elif not visible(pid):
            continue
        b = button_rect(pid, width, height)
        hot = _hovered(b, pointer)
        painter.setPen(QPen(QColor(168, 142, 84, 230 if (hot or arranging) else 110), 1))
        painter.setBrush(QColor(12, 11, 18, 220 if (hot or arranging) else 120))
        painter.drawRoundedRect(b, 3, 3)
        T.text_in(painter, b, "▼", size=7,
                  color=QColor(255, 236, 190, 255 if (hot or arranging) else 150),
                  align=T.ALIGN_CENTER, family="Segoe UI")
    if arranging:
        cy = height // 2
        banner = banner_rect(width, height)
        painter.setPen(QPen(QColor(168, 142, 84), 1))
        painter.setBrush(QColor(12, 11, 18, 235))
        painter.drawRoundedRect(banner, 8, 8)
        T.text_in(painter, QRect(banner.x(), cy - 40, banner.width(), 22),
                  "REARRANGE HUD", size=12, color=T.GOLD_BRIGHT,
                  align=T.ALIGN_CENTER, bold=True, family="Segoe UI")
        T.text_in(painter, QRect(banner.x(), cy - 16, banner.width(), 18),
                  "Drag a panel to move it  ·  ▼ hides it, ▲ brings it back",
                  size=9, color=T.PARCH, align=T.ALIGN_CENTER, family="Segoe UI")
        T.text_in(painter, QRect(banner.x(), cy + 2, banner.width(), 16),
                  "The map and the bars beside it stay top left.",
                  size=8, color=T.DIM, align=T.ALIGN_CENTER, family="Segoe UI")
        for name, rect in arrange_buttons(width, height).items():
            hot = _hovered(rect, pointer)
            painter.setPen(QPen(QColor(168, 142, 84), 1))
            painter.setBrush(QColor(60, 48, 28) if hot else QColor(32, 28, 22))
            painter.drawRoundedRect(rect, 5, 5)
            T.text_in(painter, rect, name.upper(), size=10, color=T.GOLD_BRIGHT,
                      align=T.ALIGN_CENTER, bold=True, family="Segoe UI")
    painter.restore()


def start_arranging() -> None:
    global arranging
    arranging = True


def stop_arranging() -> None:
    global arranging
    arranging = False
    save()


# ------------------------------------------------------------------ input
class HudWindow(FloatingWindow):
    """The HUD's buttons and rearrange mode, as a window over the view: it
    draws :func:`draw_chrome` above every other window (the inventory strip
    included) and takes the clicks on it -- only on a button in play, every
    click while rearranging."""

    HEADER_H = 0

    def __init__(self):
        super().__init__("HUD", 0, 0, 200, body_height=0)
        self.key = "hud"
        self.view = (0, 0)
        self._drag = None          # (id, press QPoint, offset at press)
        self.window_rect = QRect(0, 0, 0, 0)

    def place(self, view_w, view_h):
        self.view = (int(view_w), int(view_h))
        self.window_rect = QRect(0, 0, int(view_w), int(view_h))

    def draw(self, painter, focused=False):
        from . import hits
        draw_chrome(painter, *self.view, pointer=hits.pointer,
                    dragging=self._drag[0] if self._drag else None)

    def hit(self, pos):
        return arranging or hit(pos, *self.view) is not None

    @property
    def mouse_captured(self):
        return self._drag is not None

    def handle_mouse_press(self, event):
        if not self.active:
            return False
        action = hit(event.pos(), *self.view)
        if action is None:
            return arranging            # rearranging: nothing reaches the game
        if action[0] == "toggle":
            toggle(action[1])
        elif action[0] == "drag":
            self._drag = (action[1], QPoint(event.pos()), offset(action[1]))
        elif action[0] == "reset":
            reset()
        elif action[0] == "done":
            stop_arranging()
        return True

    def handle_mouse_move(self, event, view_w, view_h):
        from . import hits
        hits.pointer = (event.x(), event.y())
        if self._drag is None:
            return False
        pid, start, (dx, dy) = self._drag
        delta = event.pos() - start
        move_to(pid, dx + delta.x(), dy + delta.y(), *self.view)
        return True

    def handle_mouse_release(self, event):
        if self._drag is None:
            return False
        self._drag = None
        save()
        return True
