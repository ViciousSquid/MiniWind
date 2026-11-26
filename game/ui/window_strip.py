"""The header strip of the game's desktop debug windows.

A row along the top of a window (the storyteller window and Storyteller
Studio): an arrow that collapses the window to just this strip and expands it
again (▼ open, ▶ collapsed -- as on the in-game windows), whatever the window
puts in the middle, and a drawing pin that keeps the window above every other
window (pressed in: always on top).
"""

from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QToolButton, QWidget

_STYLE = """
QFrame#strip { background: #232a35; border: 1px solid #2f3846; }
QToolButton { background: transparent; border: none; color: #e4e6ec; padding: 2px; }
QToolButton:hover { background: #34404f; }
QToolButton:checked { background: #415f7d; }
"""


def pin_icon(pressed: bool, size: int = 32) -> QIcon:
    """A drawing pin: upright and red when pressed in, leaning and grey when not."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.translate(size / 2, size / 2)
    if not pressed:
        p.rotate(40)
    s = size / 32.0
    head = QColor(225, 70, 70) if pressed else QColor(160, 165, 175)
    rim = QColor(120, 25, 25) if pressed else QColor(85, 90, 100)
    # The needle.
    p.setPen(QPen(QColor(205, 210, 220), 2.0 * s, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(0, 3 * s), QPointF(0, 14 * s))
    # The body: a collar, a waist and a domed head.
    body = QPainterPath()
    body.addRoundedRect(QRectF(-7 * s, 0 * s, 14 * s, 4 * s), 1.5 * s, 1.5 * s)
    body.addRect(QRectF(-3.5 * s, -7 * s, 7 * s, 8 * s))
    body.addEllipse(QRectF(-6 * s, -14 * s, 12 * s, 9 * s))
    p.setPen(QPen(rim, 1.2 * s))
    p.setBrush(head)
    p.drawPath(body.simplified())
    # A highlight on the head.
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 110))
    p.drawEllipse(QRectF(-3.5 * s, -12.5 * s, 4 * s, 3 * s))
    p.end()
    return QIcon(pix)


class WindowStrip(QFrame):
    """The strip: collapse arrow, the window's own widgets, the pin."""

    def __init__(self, window: QWidget, body: QWidget):
        super().__init__(window)
        self.window_ = window
        self.body = body
        self.setObjectName("strip")
        self.setStyleSheet(_STYLE)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(4, 2, 4, 2)
        self._row.setSpacing(8)
        self.arrow = QToolButton()
        self.arrow.setText("▼")
        self.arrow.setToolTip("Collapse to this strip")
        self.arrow.clicked.connect(self.toggle)
        self._row.addWidget(self.arrow)
        self._middle = QHBoxLayout()
        self._middle.setSpacing(8)
        self._row.addLayout(self._middle, 1)
        self.pin = QToolButton()
        self.pin.setCheckable(True)
        self.pin.setIconSize(QSize(20, 20))
        self.pin.setIcon(pin_icon(False))
        self.pin.setToolTip("Always on top")
        self.pin.toggled.connect(self.set_on_top)
        self._row.addWidget(self.pin)
        self.expanded = True
        self._open_size = None
        self._open_minimum = None

    def add(self, widget, stretch=0):
        """Put one of the window's own widgets in the strip."""
        self._middle.addWidget(widget, stretch)

    # -- collapse / expand ---------------------------------------------------
    def toggle(self):
        self.set_expanded(not self.expanded)

    def set_expanded(self, expanded: bool):
        if expanded == self.expanded:
            return
        win = self.window_
        self.expanded = expanded
        if not expanded:
            self._open_size = win.size()
            self._open_minimum = win.minimumSize()
            self.body.hide()
            win.setMinimumHeight(0)
            win.resize(win.width(), win.minimumSizeHint().height())
            win.setFixedHeight(win.sizeHint().height())
            self.arrow.setText("▶")
            self.arrow.setToolTip("Expand")
        else:
            win.setMinimumHeight(0)
            win.setMaximumHeight(16777215)
            self.body.show()
            if self._open_minimum is not None:
                win.setMinimumSize(self._open_minimum)
            if self._open_size is not None:
                win.resize(self._open_size)
            self.arrow.setText("▼")
            self.arrow.setToolTip("Collapse to this strip")

    # -- always on top -------------------------------------------------------
    def set_on_top(self, on: bool):
        win = self.window_
        visible = win.isVisible()
        geometry = win.geometry()
        win.setWindowFlag(Qt.WindowStaysOnTopHint, bool(on))
        self.pin.setIcon(pin_icon(bool(on)))
        self.pin.setToolTip("Always on top: on" if on else "Always on top")
        if visible:                      # changing a window flag hides it
            win.setGeometry(geometry)
            win.show()
