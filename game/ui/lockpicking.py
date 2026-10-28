"""Scalable lock artwork and platform-neutral mouse/keyboard controls.

Qt events already use logical pixels on Windows and macOS. Do not multiply
their positions by devicePixelRatio or use OS raw-motion/acceleration APIs.
Only the pick meets resistance; the system cursor is never captured/warped.
"""

from __future__ import annotations

import math
from pathlib import Path

from PyQt5.QtCore import QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QLinearGradient, QPainterPath, QPen, QPixmap

from engine.floating_windows import CallbackWindow
from . import hits, theme as T
from ..rpg import inventory as inv
from ..rpg.lockpicking import shear_chance
from ..sim import ownership


WIDTH, HEIGHT = 820, 560
GOLD = QColor("#d8b87a")
PALE = QColor("#efe3c9")
MUTED = QColor("#aaa69d")
TEAL = QColor("#85cbbb")
RED = QColor("#f3a08c")
_PLATE = None


def geometry(x, y, w, h):
    scale = max(0.1, min(w / WIDTH, h / HEIGHT))
    return x + (w - WIDTH * scale) / 2, y + (h - HEIGHT * scale) / 2, scale


def _text(p, rect, text, size=11, color=PALE, bold=False, align=Qt.AlignLeft | Qt.AlignVCenter):
    p.setFont(T.font(size, bold=bold))
    p.setPen(color)
    p.drawText(QRectF(*rect), int(align | Qt.TextWordWrap), text)


def _dial(p, a):
    """Engraved escutcheon with a live cutaway, springs and two-piece pins."""
    global _PLATE
    p.save()
    p.translate(7, 8)
    p.scale(.95, .95)
    if _PLATE is None:
        _PLATE = QPixmap(str(Path(__file__).resolve().parents[2] /
                            "assets/ui/lockpicking/escutcheon.png"))
    p.setRenderHint(p.SmoothPixmapTransform, True)
    p.drawPixmap(QRectF(-12, 130, 480, 320), _PLATE, QRectF(_PLATE.rect()))
    xs = [173, 200, 228, 255, 282]
    shear = 312
    p.setPen(QPen(QColor(133, 203, 187, 95), 1, Qt.DashLine))
    p.drawLine(155, shear, 298, shear)
    active_x, foot = xs[min(a.pins_set, 4)], 338
    for i, cx in enumerate(xs):
        if i >= a.lock.pins:
            continue
        set_ = i < a.pins_set
        active = i == a.pins_set
        # At the sweet spot the gap meets the shear line. Individual pins
        # latch instead of falling on every later mistake.
        lift = (a.angle + 80) / 160 * 32 if active else 0
        target = a.target if active else a.targets[i]
        required = (target + 80) / 160 * 32
        gap = shear if set_ else shear + required - lift
        color = TEAL if set_ else GOLD if active else QColor("#857454")
        brass = QLinearGradient(cx - 6, 0, cx + 6, 0)
        brass.setColorAt(0, QColor("#65441e"))
        brass.setColorAt(.35, QColor("#f3cf79"))
        brass.setColorAt(.7, QColor("#bd8a36"))
        brass.setColorAt(1, QColor("#735022"))
        p.setBrush(brass)
        p.setPen(QPen(color, 1))
        p.drawRoundedRect(QRectF(cx - 5, gap - 27, 10, 26), 2, 2)
        p.drawRoundedRect(QRectF(cx - 5, gap + 2, 10, 23), 2, 2)
        spring = QPainterPath(QPointF(cx, 241))
        for j in range(11):
            spring.lineTo(cx + (4 if j % 2 else -4), 243 + j * max(1, (gap - 274) / 11))
        p.setPen(QPen(QColor("#d3c9ac"), 1.3))
        p.drawPath(spring)
        p.setPen(QPen(color, 1.5))
        p.setBrush(color if set_ else QColor("#1a1c18"))
        p.drawEllipse(QPointF(cx, 229), 3, 3)
        if active:
            active_x, foot = cx, gap + 25
            if a.aligned or a.assisted:
                target_y = shear + 25
                p.setPen(QPen(TEAL, 2))
                p.drawLine(QPointF(cx + 9, target_y), QPointF(cx + 17, target_y))
            p.setPen(QPen(TEAL if a.aligned else GOLD, 2))
            p.drawLine(cx - 8, 357, cx + 8, 357)
    tremor = math.sin(a.elapsed * 48) * a.resistance * (1.0 + a.strain * 2.5)
    recoil = math.sin(a.feedback_time * 35) * a.feedback_time * 9
    curve = QPainterPath(QPointF(14, 333))
    curve.lineTo(65, 333)
    if a.last_event == "pick_broke" and a.feedback_time > 0:
        curve.lineTo(86, 334 + recoil)
        curve.moveTo(99, 333 - recoil)
    curve.quadTo(110, 333 + a.resistance * 9, active_x - 10, foot + 7)
    curve.quadTo(active_x, foot + 9, active_x, foot + tremor + recoil)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QColor(0, 0, 0, 160), 6, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(curve)
    p.setPen(QPen(RED if a.strain >= .65 else QColor("#d3d9d5"), 3, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(curve)
    p.setPen(QPen(QColor("#765139"), 7, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(14, 333, 62, 333)
    _text(p, (65, 435, 335, 25), "DRAG ↑ / ↓ TO LIFT THE ACTIVE PIN", 9, MUTED,
          align=Qt.AlignCenter)
    p.restore()


def _pins(p, a):
    for i in range(a.lock.pins):
        x = 468 + i * (280 / a.lock.pins)
        set_ = i < a.pins_set
        active = i == a.pins_set
        color = TEAL if set_ else GOLD if active else QColor("#5c5c55")
        p.setPen(QPen(QColor("#444942"), 1))
        p.setBrush(QColor("#101719"))
        p.drawRoundedRect(QRectF(x, 153, 38, 69), 5, 5)
        spring = QPainterPath(QPointF(x + 19, 157))
        for j in range(9):
            spring.lineTo(x + (13 if j % 2 else 25), 160 + j * 2)
        p.setPen(QPen(color, 1.1))
        p.drawPath(spring)
        y = 177 if set_ else 190 - (a.turn * 13 if active else 0)
        p.setBrush(color)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(QRectF(x + 12, y, 14, 23), 2, 2)
        _text(p, (x, 226, 38, 20), "SET" if set_ else str(i + 1), 9, color,
              align=Qt.AlignCenter)


def draw(p, session, x, y, w, h):
    a = session.lockpick_attempt
    if a is None:
        return
    ox, oy, scale = geometry(x, y, w, h)
    p.save()
    p.translate(ox, oy)
    p.scale(scale, scale)
    p.setRenderHint(p.Antialiasing, True)
    bg = QLinearGradient(0, 0, WIDTH, HEIGHT)
    bg.setColorAt(0, QColor("#20272a"))
    bg.setColorAt(1, QColor("#101719"))
    p.setBrush(bg)
    p.setPen(QPen(QColor("#756345"), 1))
    p.drawRoundedRect(QRectF(1, 1, WIDTH - 2, HEIGHT - 2), 10, 10)
    p.setPen(QPen(QColor("#3e443c"), 1))
    p.drawLine(30, 115, 790, 115)
    owned = ownership.is_theft(session.lockpick_thing.properties, "player", "player")
    _text(p, (32, 20, 750, 20), "LOCKPICKING · OWNED — STAY UNSEEN" if owned
          else "LOCKPICKING · KEEP WATCH", 10, GOLD, True)
    name = session.lockpick_thing.properties.get("display_name") or "Locked container"
    _text(p, (32, 43, 750, 37), str(name), 23, PALE)
    count = inv.quantity(session.game.character.inventory, "lockpick")
    _text(p, (32, 84, 750, 23),
          f"{a.difficulty.upper()}    /    SECURITY {int(a.security)}    /    {count} PICKS    /    WORLD IS LIVE", 10, MUTED)
    _dial(p, a)
    _pins(p, a)
    _text(p, (462, 124, 315, 23), f"TUMBLERS   {a.pins_set} / {a.lock.pins} LATCHED", 10, GOLD, True)
    _text(p, (462, 257, 315, 50), a.cue, 14, RED if a.strain >= .65 else TEAL if a.aligned else PALE)
    _text(p, (462, 310, 315, 30), f"PICK STRAIN   {int(a.strain * 100)}%", 10, RED if a.strain >= .65 else MUTED)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#303735"))
    p.drawRoundedRect(QRectF(462, 345, 312, 10), 4, 4)
    p.setBrush(RED if a.strain >= .65 else GOLD)
    p.drawRoundedRect(QRectF(462, 345, 312 * a.strain, 10), 4, 4)
    p.setPen(QPen(RED, 1))
    p.drawLine(QPointF(462 + 312 * .65, 341), QPointF(462 + 312 * .65, 359))
    _text(p, (462, 365, 315, 33), a.message, 10, MUTED)
    risk = shear_chance(a.security)
    if risk:
        _text(p, (462, 404, 315, 54),
              f"INEXPERIENCED · {risk:.0%} shear risk on snap\nSheared tip: only Knock can open this lock.", 10, RED)
    else:
        _text(p, (462, 404, 315, 54), "Release tension to relieve strain.\nA snapped pick costs one pick; set pins stay set.", 10, MUTED)
    p.restore()

    # Publish buttons in window coordinates; never put scaled rectangles into
    # the global hit registry. Mutations remain on the logic thread.
    from .screens import button
    def b(rect, label, action, value=0, enabled=True, primary=False):
        rx, ry, rw, rh = rect
        actual = QRect(round(ox + rx * scale), round(oy + ry * scale), round(rw * scale), round(rh * scale))
        def invoke(s):
            if s.lockpick_attempt is a:
                s.lockpick_action(action, value)
        button(p, actual, label, invoke, enabled, primary)
    b((32, 476, 54, 34), "←", "move", -2)
    b((94, 476, 54, 34), "→", "move", 2)
    b((166, 476, 238, 34), "Release tension" if a.tension else "Apply tension", "tension",
      enabled=count > 0 or a.tension, primary=True)
    b((462, 476, 170, 34), "Guide: ON" if a.assisted else "Guide: OFF", "assist")
    b((650, 476, 124, 34), "Leave", "cancel")
    p.save()
    p.translate(ox, oy)
    p.scale(scale, scale)
    from .. import controls
    _text(p, (32, 522, 750, 23),
          "L-stick lift (lean lightly for fine aim)   ·   RT hold tension   ·   Y guide   ·   B leave"
          if controls.gamepad() else
          "Drag ↑↓ / arrow keys lift   ·   Shift fine aim   ·   RMB hold / Space tension   ·   H guide   ·   Esc leave",
          9, MUTED)
    p.restore()


def handle_key(session, key):
    if key in ("escape", "esc", "e", "tab"):
        session.lockpick_action("cancel")
    elif key in ("space", "return", "enter"):
        session.lockpick_action("tension")
    elif key in ("left", "a", "right", "d", "up", "w", "down", "s"):
        session.lockpick_action("move", -2 if key in ("left", "a", "down", "s") else 2)
    elif key == "h":
        session.lockpick_action("assist")
    return True


def handle_input(session, just, ctx):
    # Cancellation wins over every other action in this tick.
    if just & {"escape", "e", "tab"}:
        session.lockpick_action("cancel")
        return
    if just & {"space", "return", "enter"}:
        session.lockpick_action("tension")
    if "h" in just:
        session.lockpick_action("assist")
    left = any(ctx.key_down(k) for k in ("left", "a", "down", "s"))
    right = any(ctx.key_down(k) for k in ("right", "d", "up", "w"))
    if left != right:
        step = (9 if ctx.key_down("shift") else 36) * min(.1, max(0, ctx.delta))
        session.lockpick_action("move", -step if left else step)


class LockpickWindow(CallbackWindow):
    """Relative mouse drag with spring resistance on Windows and macOS.

    Secondary-button tension is optional: Space works with trackpads and
    one-button mice. Capture lasts through button release outside the window.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = None
        self._last_y = None
        self._right_down = False

    @property
    def mouse_captured(self):
        return self._last_y is not None or self._right_down

    def _queue(self, action, value=0):
        attempt = getattr(self.session, "lockpick_attempt", None)
        def run(s):
            if s is self.session and s.lockpick_attempt is attempt:
                s.lockpick_action(action, value)
        hits.queue(run)

    def _geometry(self):
        rect = self._full_rect()
        return geometry(rect.x(), rect.y() + self.HEADER_H, self.width, self.content_height())

    def handle_mouse_press(self, event):
        if not self.active or not self.expanded:
            return super().handle_mouse_press(event)
        ox, oy, scale = self._geometry()
        dial = QRectF(ox + 62 * scale, oy + 124 * scale, 340 * scale, 340 * scale)
        if dial.contains(event.localPos()):
            if event.button() == Qt.LeftButton:
                self._last_y = event.localPos().y()
                return True
            if event.button() == Qt.RightButton:
                self._right_down = True
                self._queue("tension_on")
                return True
        return super().handle_mouse_press(event)

    def handle_mouse_move(self, event, view_w, view_h):
        hits.pointer = (event.localPos().x(), event.localPos().y())
        if self._last_y is not None:
            _, _, scale = self._geometry()
            dy = self._last_y - event.localPos().y()
            self._last_y = event.localPos().y()
            # Logical pixels, normalized by the displayed mechanism height.
            fine = .25 if event.modifiers() & Qt.ShiftModifier else 1.0
            self._queue("mouse", dy / (120 * scale) * 160 * fine)
            return True
        return super().handle_mouse_move(event, view_w, view_h)

    def handle_mouse_release(self, event):
        if event.button() == Qt.RightButton and self._right_down:
            self._right_down = False
            self._queue("tension_off")
            return True
        if event.button() == Qt.LeftButton and self._last_y is not None:
            self._last_y = None
            return True
        return super().handle_mouse_release(event)

    def on_close(self):
        self._last_y = None
        self._right_down = False
        super().on_close()
