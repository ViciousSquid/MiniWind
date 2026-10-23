"""Mouse-controlled tumblers: sweep upward to lift, click on the top contact."""

import math

from PyQt5.QtCore import QPointF, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QLinearGradient, QPainterPath, QPen

from engine.floating_windows import CallbackWindow
from . import fonts, hits
from ..rpg.lockpicking import label


def layout(x, y, w, h, count):
    field = QRectF(x + w * 0.15, y + h * 0.20, w * 0.70, h * 0.44)
    xs = [field.left() + field.width() * (i + 0.5) / count for i in range(count)]
    gap = w * 0.025
    bw = (w - 2 * w * 0.07 - 2 * gap) / 3
    buttons = [QRect(int(x + w * 0.07 + i * (bw + gap)), int(y + h * 0.86),
                     int(bw), max(28, int(h * 0.075))) for i in range(3)]
    return field, xs, buttons


def _queued(attempt, action, index=None, height=None):
    def run(session):
        if session.lockpicking is attempt:
            session.lockpick_action(action, index, height)
    return run


def draw_lock(painter, session, x, y, w, h):
    attempt = session.lockpicking
    if attempt is None:
        return
    field, xs, buttons = layout(x, y, w, h, len(attempt.pins))
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    backdrop = QLinearGradient(x, y, x + w, y + h)
    backdrop.setColorAt(0, QColor(48, 36, 26))
    backdrop.setColorAt(1, QColor(18, 22, 25))
    painter.fillRect(QRectF(x, y, w, h), backdrop)
    painter.setPen(QPen(QColor(139, 111, 60), 1))
    painter.drawRoundedRect(QRectF(x + 12, y + 12, w - 24, h - 24), 8, 8)
    painter.setFont(fonts.dialogue_font(19))
    painter.setPen(QColor(242, 213, 154))
    name = str(session.lockpick_target.properties.get("display_name", "Locked chest"))
    name = QFontMetrics(painter.font()).elidedText(name, Qt.ElideRight, int(w - 70))
    painter.drawText(QRectF(x + 30, y + 16, w - 60, 30), int(Qt.AlignCenter), name)
    painter.setFont(fonts.dialogue_font(11))
    painter.setPen(QColor(187, 181, 160))
    painter.drawText(QRectF(x + 25, y + 51, w - 50, 22), int(Qt.AlignCenter),
                     f"{label(attempt.difficulty)} lock  ·  Security {attempt.security}"
                     f"  ·  {session.lockpick_count()} lockpicks")

    # A cutaway iron lock, with its brass shear line and individual springs.
    housing = field.adjusted(-18, -12, 18, 16)
    metal = QLinearGradient(0, housing.top(), 0, housing.bottom())
    metal.setColorAt(0, QColor(72, 76, 72))
    metal.setColorAt(0.45, QColor(34, 40, 40))
    metal.setColorAt(1, QColor(57, 59, 54))
    painter.setBrush(metal)
    painter.setPen(QPen(QColor(150, 125, 76), 2))
    painter.drawRoundedRect(housing, 10, 10)
    if attempt.broken:
        flash = max(0.0, 1.0 - attempt.break_elapsed / 0.4)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(237, 94, 65, int(230 * flash)), 3))
        painter.drawRoundedRect(housing, 10, 10)
    top = field.top() + field.height() * 0.10
    rest = field.top() + field.height() * 0.62
    travel = rest - top
    pin_w = min(30, field.width() / len(xs) * 0.30)
    pin_h = field.height() * 0.28
    painter.setPen(QPen(QColor(213, 171, 89, 150), 1, Qt.DashLine))
    painter.drawLine(QPointF(field.left(), top + pin_h), QPointF(field.right(), top + pin_h))
    for i, (px, pin) in enumerate(zip(xs, attempt.pins)):
        head = rest - pin.height * travel
        ready = pin.phase == "hold"
        selected = i == attempt.selected
        if ready or pin.latched:
            # The visible top-contact is exactly the model's setting window.
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(247, 204, 99, 55 if ready else 25))
            painter.drawRoundedRect(QRectF(px - pin_w, top - 6, pin_w * 2, pin_h + 15), 7, 7)
        if selected:
            painter.setBrush(QColor(218, 184, 120, 13))
            painter.setPen(QPen(QColor(207, 168, 92, 90), 1))
            painter.drawRoundedRect(QRectF(px - pin_w * 1.1, field.top(),
                                           pin_w * 2.2, field.height()), 5, 5)
        spring = QPainterPath(QPointF(px, field.top()))
        for coil in range(1, 9):
            spring.lineTo(px + (6 if coil % 2 else -6),
                          field.top() + (head - field.top()) * coil / 9)
        spring.lineTo(px, head)
        painter.setPen(QPen(QColor(175, 179, 169), 1.4))
        painter.drawPath(spring)
        brass = QLinearGradient(px - pin_w / 2, 0, px + pin_w / 2, 0)
        brass.setColorAt(0, QColor(124, 91, 40))
        brass.setColorAt(0.45, QColor(248, 218, 143) if ready else QColor(204, 171, 102))
        brass.setColorAt(1, QColor(115, 88, 44))
        painter.setBrush(brass)
        painter.setPen(QPen(QColor(245, 219, 157) if ready else QColor(96, 76, 43), 1.2))
        painter.drawRoundedRect(QRectF(px - pin_w / 2, head, pin_w, pin_h), 4, 4)
        if pin.latched:
            painter.setPen(QPen(QColor(193, 221, 142), 2))
            painter.drawLine(QPointF(px - 6, top + 9), QPointF(px - 1, top + 14))
            painter.drawLine(QPointF(px - 1, top + 14), QPointF(px + 7, top + 4))
    # Rivets around the cutaway housing.
    painter.setPen(QPen(QColor(16, 20, 19), 1))
    painter.setBrush(QColor(133, 133, 111))
    for rx in (housing.left() + 7, housing.right() - 7):
        for ry in (housing.top() + 7, housing.bottom() - 7):
            painter.drawEllipse(QPointF(rx, ry), 2.5, 2.5)

    # Mouse position steers the physical pick; the active spring pushes back.
    active = attempt.pins[attempt.selected]
    tip_x = xs[attempt.break_index if attempt.broken else attempt.selected]
    pick_height = attempt.break_height if attempt.broken else attempt.pick_height
    tip_y = min(field.bottom() - 5, rest + pin_h - pick_height * travel)
    contact_height = (attempt.break_pin_height if attempt.broken else
                      active.height if active.phase in ("rise", "hold") else None)
    if contact_height is not None:
        tip_y = rest - contact_height * travel + pin_h + 9
    start = QPointF(field.left() - 22, field.bottom() + 6)
    tip = QPointF(tip_x, tip_y - 1)

    def stroke(path):
        painter.setBrush(Qt.NoBrush)
        for colour, width in ((QColor(20, 20, 19), 6), (QColor(202, 211, 202), 3)):
            painter.setPen(QPen(colour, width, Qt.SolidLine, Qt.RoundCap))
            painter.drawPath(path)

    if attempt.broken:
        progress = attempt.break_elapsed / attempt.BREAK_DURATION
        motion = attempt.break_motion
        split = start * (1 - motion["split"]) + tip * motion["split"]
        recoil = math.sin(min(1.0, progress * 3) * math.pi) * motion["recoil"]
        handle = QPainterPath(start + QPointF(-recoil, recoil * 0.5))
        if attempt.break_style == "buckle":
            bend = min(1.0, progress * 5) * 18
            handle.lineTo(start * 0.45 + split * 0.55 + QPointF(0, -bend))
        handle.lineTo(split + QPointF(-5 - recoil, recoil * 0.5))
        stroke(handle)

        def fragment(origin, end, drift, fall, spin, hooked):
            painter.save()
            painter.translate(origin + QPointF(8 + progress * drift, 5 + progress ** 2 * fall))
            painter.rotate(progress * spin)
            piece = QPainterPath(QPointF(0, 0))
            piece.lineTo(end - origin)
            if hooked:
                piece.lineTo(end - origin + QPointF(0, -8))
            stroke(piece)
            painter.restore()

        # Four distinct fractures, with a fresh break point and flight each time.
        if attempt.break_style == "shatter":
            second = start * (1 - motion["second_split"]) + tip * motion["second_split"]
            fragment(split, second, motion["drift"], motion["fall"], motion["spin"], False)
            fragment(second, tip, -motion["drift"] * 0.65, motion["fall"] + 15,
                     -motion["spin"] * 0.85, True)
        else:
            fragment(split, tip, motion["drift"], motion["fall"], motion["spin"], True)
        spark = max(0.0, 1.0 - progress * 3)
        painter.setPen(QPen(QColor(255, 205, 105, int(255 * spark)), 2))
        for dx, dy in ((-9, -12), (3, -16), (13, -7)):
            painter.drawLine(split + QPointF(dx * 0.5, dy * 0.5), split + QPointF(dx, dy))
    else:
        pick = QPainterPath(start)
        pick.lineTo(tip)
        pick.lineTo(tip + QPointF(0, -8))
        stroke(pick)

    painter.setFont(fonts.dialogue_font(12))
    if attempt.broken:
        painter.fillRect(QRectF(x + 20, y + h * 0.68, w - 40, 30), QColor(99, 33, 24, 220))
    painter.setPen(QColor(255, 180, 137) if attempt.broken else
                   QColor(255, 220, 141) if attempt.can_set else QColor(224, 215, 190))
    painter.drawText(QRectF(x + 24, y + h * 0.69, w - 48, 24), int(Qt.AlignCenter), attempt.message)
    painter.setFont(fonts.dialogue_font(10))
    painter.setPen(QColor(188, 183, 166))
    painter.drawText(QRectF(x + 22, y + h * 0.75, w - 44, 20), int(Qt.AlignCenter),
                     "Move mouse sideways to choose a tumbler; sweep upward to lift.")
    painter.drawText(QRectF(x + 22, y + h * 0.79, w - 44, 20), int(Qt.AlignCenter),
                     "Feel the top contact, then click. A mistimed click can snap the pick.")
    from .screens import button
    usable = not attempt.breaking and session.lockpick_count() > 0
    button(painter, buttons[0], "New pick: lift" if attempt.broken else "Lift tumbler",
           _queued(attempt, "lift"), enabled=usable)
    button(painter, buttons[1], "Set tumbler", _queued(attempt, "set"),
           enabled=usable and not attempt.broken, primary=attempt.can_set)
    button(painter, buttons[2], "Leave [Esc]", lambda s: s.cancel_lockpicking()
           if s.lockpicking is attempt else None)
    painter.restore()


class LockpickWindow(CallbackWindow):
    def bind(self, session):
        self.session = session
        self.attempt = session.lockpicking
        self._last_point = None
        self._stroke = 0.0
        self._armed = True
        self._focused = True
        self._hover_index = None

    @property
    def mouse_captured(self):
        # Tumblers react to a hovering mouse, without requiring a drag button.
        return self.active and self.expanded and getattr(self, "_focused", False)

    def draw(self, painter, focused=False):
        self._focused = focused
        super().draw(painter, focused)

    def _geometry(self):
        rect = self._full_rect()
        return layout(rect.x(), rect.y() + self.HEADER_H, rect.width(),
                      self.content_height(), len(self.attempt.pins))

    def handle_mouse_move(self, event, view_w, view_h):
        if self.dragging:
            self._last_point = None
            return super().handle_mouse_move(event, view_w, view_h)
        field, xs, _buttons = self._geometry()
        point = QPointF(event.pos())
        if not field.adjusted(-18, -12, 18, 16).contains(point):
            self._last_point = None
            self._stroke = 0.0
            self._armed = True
            return False
        index = min(range(len(xs)), key=lambda i: abs(point.x() - xs[i]))
        height = max(0, min(1, (field.bottom() - point.y()) / field.height()))
        hits.queue(_queued(self.attempt, "select", index, height))
        if self._hover_index != index:
            self._stroke, self._armed = 0.0, True
        elif self._last_point is not None:
            dy = self._last_point.y() - point.y()
            if dy < 0:
                self._stroke = 0.0
                if dy < -3:
                    self._armed = True
            else:
                self._stroke += dy
            if self._armed and self._stroke >= max(8.0, field.height() * 0.05):
                hits.queue(_queued(self.attempt, "lift"))
                self._armed = False
                self._stroke = 0.0
        self._last_point, self._hover_index = point, index
        return True

    def handle_mouse_press(self, event):
        if self.expanded and event.button() == Qt.LeftButton:
            field, xs, _buttons = self._geometry()
            if field.adjusted(-18, -12, 18, 16).contains(QPointF(event.pos())):
                index = min(range(len(xs)), key=lambda i: abs(event.x() - xs[i]))
                hits.queue(_queued(self.attempt, "select", index))
                hits.queue(_queued(self.attempt, "set"))
                return True
        return super().handle_mouse_press(event)
