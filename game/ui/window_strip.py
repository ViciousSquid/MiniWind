"""The header strip of the game's desktop debug windows.

A row along the top of a window (the storyteller window and Storyteller
Studio): an arrow that collapses the window to just this strip and expands it
again (▼ open, ▶ collapsed -- as on the in-game windows), whatever the window
puts in the middle, and a drawing pin that keeps the window above every other
window: an outline leaning over when off, filled and upright when pinned.
"""

from __future__ import annotations

from PyQt5.QtCore import QPointF, QSize, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QToolButton, QWidget

_STYLE = """
QFrame#strip { background: #232a35; border: 1px solid #2f3846; }
QToolButton { background: transparent; border: none; color: #e4e6ec; padding: 2px; }
QToolButton:hover { background: #34404f; }
QToolButton:checked { background: transparent; }
"""


#: The pin's outline in a 1200-unit square: (start, [(control or None, point)]).
_PIN_OUTLINE = ((770, 155), [
    (None, (1045, 430)),            # the flat top of the head
    ((965, 505), (880, 470)),       # flaring in to the waist
    (None, (720, 630)),
    ((800, 800), (655, 905)),       # flaring out to the collar
    (None, (290, 537)),             # the flat underside of the collar
    ((400, 450), (540, 465)),       # back in to the waist
    (None, (715, 295)),
    ((700, 205), (770, 155)),       # and out to the head
])
_PIN_NEEDLE = ((450, 750), (140, 1060))


def pin_icon(pinned: bool, size: int = 32, colour=QColor(228, 230, 236)) -> QIcon:
    """A drawing pin, one colour: an outline leaning over when not pinned;
    filled and standing upright (pushed in) when pinned."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing, True)
    scale = size / 1200.0
    p.translate(size / 2, size / 2)
    if pinned:
        p.rotate(-45)                   # needle straight down
    p.scale(scale, scale)
    p.translate(-600, -600)
    (sx, sy), segments = _PIN_OUTLINE
    path = QPainterPath(QPointF(sx, sy))
    for control, (x, y) in segments:
        if control is None:
            path.lineTo(x, y)
        else:
            path.quadTo(QPointF(*control), QPointF(x, y))
    pen = QPen(colour, 75, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin)
    p.setPen(pen)
    p.setBrush(colour if pinned else Qt.NoBrush)
    p.drawPath(path)
    (ax, ay), (bx, by) = _PIN_NEEDLE
    p.drawLine(QPointF(ax, ay), QPointF(bx, by))
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
