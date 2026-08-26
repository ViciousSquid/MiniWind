"""
Shared drawing helpers and the Miniwind visual theme (Qt).

Only imported on the Qt side (editor/engine host). A dark, gilded fantasy-UI
palette with a few reusable primitives — framed panels, bars and text — so the
HUD and the full-screen menus look like one game rather than a debug overlay.
"""

from __future__ import annotations

from PyQt5.QtCore import QRect, QRectF, Qt
from PyQt5.QtGui import (QColor, QFont, QBrush, QPen, QLinearGradient,
                         QPainterPath)

# palette
GOLD = QColor(198, 162, 88)
GOLD_BRIGHT = QColor(255, 214, 130)
GILD = QColor(150, 122, 64)
PARCH = QColor(226, 224, 236)
INK = QColor(232, 228, 240)
DIM = QColor(150, 150, 168)
PANEL_TOP = QColor(30, 28, 40, 244)
PANEL_BOT = QColor(16, 15, 24, 246)
SHADOW = QColor(0, 0, 0, 140)
SELECT = QColor(70, 60, 96, 230)

HEALTH = QColor(196, 62, 54)
MAGICKA = QColor(64, 116, 200)
STAMINA = QColor(96, 168, 84)
XP = QColor(200, 170, 90)

ALIGN_CENTER = int(Qt.AlignCenter)
ALIGN_LEFT = int(Qt.AlignVCenter | Qt.AlignLeft)
ALIGN_RIGHT = int(Qt.AlignVCenter | Qt.AlignRight)
WORD_WRAP = int(Qt.TextWordWrap)


def font(size, bold=False, italic=False, family="Georgia"):
    return QFont(family, size, QFont.Bold if bold else QFont.Normal, italic)


#: Decorative "old RPG" family stack for titles — the same one the spell cards
#: use. Whatever the OS has first wins (Papyrus/Palatino/Book Antiqua/Georgia…).
FANCY_FAMILIES = ["Papyrus", "Luminari", "Palatino Linotype", "Book Antiqua",
                  "Georgia", "Cambria", "serif"]


def fancy_font(size, bold=False, italic=False):
    f = QFont()
    try:
        f.setFamilies(FANCY_FAMILIES)
    except Exception:
        f.setFamily("Georgia")
    f.setPointSize(int(size))
    f.setBold(bool(bold))
    f.setItalic(bool(italic))
    f.setStyleHint(QFont.Serif)
    return f


def panel(painter, x, y, w, h, radius=12, shadow=True):
    """Draw a framed, gilded, gradient panel and return its inner rect."""
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    if shadow:
        sp = QPainterPath()
        sp.addRoundedRect(QRectF(x + 4, y + 6, w, h), radius, radius)
        painter.fillPath(sp, SHADOW)
    body = QPainterPath()
    body.addRoundedRect(QRectF(x, y, w, h), radius, radius)
    grad = QLinearGradient(0, y, 0, y + h)
    grad.setColorAt(0.0, PANEL_TOP)
    grad.setColorAt(1.0, PANEL_BOT)
    painter.fillPath(body, QBrush(grad))
    painter.setPen(QPen(GILD, 2))
    painter.drawPath(body)
    inner = QPainterPath()
    inner.addRoundedRect(QRectF(x + 4, y + 4, w - 8, h - 8), radius - 3, radius - 3)
    painter.setPen(QPen(QColor(90, 74, 44), 1))
    painter.drawPath(inner)
    painter.restore()
    return QRect(int(x + 16), int(y + 16), int(w - 32), int(h - 32))


def bar(painter, x, y, w, h, frac, color, bg=QColor(20, 18, 26, 220), label=None,
        text_color=None):
    """A framed stat bar filled to *frac* (0..1)."""
    frac = max(0.0, min(1.0, frac))
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(bg)
    painter.drawRoundedRect(QRect(int(x), int(y), int(w), int(h)), 3, 3)
    fill = int(w * frac)
    if fill > 0:
        g = QLinearGradient(x, y, x, y + h)
        g.setColorAt(0.0, color.lighter(125))
        g.setColorAt(1.0, color.darker(115))
        painter.setBrush(QBrush(g))
        painter.drawRoundedRect(QRect(int(x), int(y), fill, int(h)), 3, 3)
    painter.setPen(QPen(GILD, 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(QRect(int(x), int(y), int(w), int(h)), 3, 3)
    if label:
        painter.setFont(font(max(7, int(h * 0.5)), bold=True, family="Segoe UI"))
        painter.setPen(text_color or QColor(240, 240, 245))
        painter.drawText(QRect(int(x), int(y), int(w), int(h)), ALIGN_CENTER, label)
    painter.restore()


def text(painter, x, y, s, size=11, color=INK, bold=False, italic=False,
         family="Georgia"):
    painter.save()
    painter.setFont(font(size, bold, italic, family))
    painter.setPen(color)
    painter.drawText(int(x), int(y), s)
    painter.restore()


def text_in(painter, rect, s, size=11, color=INK, align=ALIGN_LEFT, bold=False,
            italic=False, family="Georgia"):
    painter.save()
    painter.setFont(font(size, bold, italic, family))
    painter.setPen(color)
    painter.drawText(rect, align, s)
    painter.restore()


def dim_screen(painter, w, h, alpha=170):
    painter.fillRect(QRect(0, 0, int(w), int(h)), QColor(6, 6, 10, alpha))


def heading(painter, rect, title, subtitle=None):
    painter.save()
    painter.setFont(fancy_font(22, bold=True))   # titles use the RPG display face
    painter.setPen(GOLD_BRIGHT)
    painter.drawText(rect.x(), rect.y() + 22, title)
    painter.setPen(QPen(GILD, 1))
    painter.drawLine(rect.x(), rect.y() + 32, rect.right(), rect.y() + 32)
    if subtitle:
        painter.setFont(font(10, italic=True, family="Segoe UI"))
        painter.setPen(DIM)
        painter.drawText(rect.x(), rect.y() + 48, subtitle)
    painter.restore()
    return rect.y() + (56 if subtitle else 44)
