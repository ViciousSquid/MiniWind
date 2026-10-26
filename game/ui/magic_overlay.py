"""
Whole-screen magic washes, drawn with the overlay painter over the world and
under the HUD (the tints of :meth:`game.magic_fx.MagicFX.frame`):

* ``blood`` -- the resurrection: the screen sinks into a dark red, deepest at
  the edges, with a slow heartbeat in it;
* ``vignette`` -- a hit by fire, arcane force or disintegration: the edges of
  sight flare in the spell's colour;
* ``frost`` -- frostbite: rime creeps in from the corners, white-blue and
  splintered;
* ``flash`` -- lightning: one bright blink.
"""

from __future__ import annotations

import math
import random

from PyQt5.QtCore import QPointF, QRect
from PyQt5.QtGui import QColor, QPen, QRadialGradient

#: Rime lines in the frost wash: generated once, in unit coordinates.
_RIME = None


def _rime():
    global _RIME
    if _RIME is None:
        rng = random.Random(7)
        lines = []
        for _ in range(140):
            # Seeds hug the edges; each grows a short jagged spike inward.
            edge = rng.random()
            side = rng.randrange(4)
            x, y = [(edge, 0.0), (edge, 1.0), (0.0, edge), (1.0, edge)][side]
            inward = [(0, 1), (0, -1), (1, 0), (-1, 0)][side]
            length = rng.uniform(0.03, 0.14)
            pts = [(x, y)]
            for _ in range(4):
                x += inward[0] * length / 4 + rng.uniform(-0.012, 0.012)
                y += inward[1] * length / 4 + rng.uniform(-0.012, 0.012)
                pts.append((x, y))
            lines.append(pts)
        _RIME = lines
    return _RIME


def draw(painter, tints, width, height, now=0.0) -> None:
    """Draw every live tint (``((r, g, b), alpha, style, progress)``)."""
    if not tints:
        return
    painter.save()
    rect = QRect(0, 0, width, height)
    centre = QPointF(width / 2.0, height / 2.0)
    reach = math.hypot(width, height) * 0.55
    for colour, alpha, style, _progress in tints:
        if alpha <= 0.003:
            continue
        r, g, b = (int(max(0, min(255, c * 255))) for c in colour)
        if style == "blood":
            beat = 0.92 + 0.08 * math.sin(now * 5.5)
            painter.fillRect(rect, QColor(r, g, b, int(255 * alpha * beat)))
            grad = QRadialGradient(centre, reach)
            grad.setColorAt(0.35, QColor(0, 0, 0, 0))
            grad.setColorAt(1.0, QColor(20, 0, 0, int(255 * min(1.0, alpha * 1.3))))
            painter.fillRect(rect, grad)
        elif style == "flash":
            painter.fillRect(rect, QColor(r, g, b, int(255 * alpha)))
        else:
            grad = QRadialGradient(centre, reach)
            grad.setColorAt(0.45, QColor(r, g, b, 0))
            grad.setColorAt(1.0, QColor(r, g, b, int(255 * alpha)))
            painter.fillRect(rect, grad)
            if style == "frost":
                pen = QPen(QColor(235, 245, 255, int(220 * alpha)))
                pen.setWidthF(1.4)
                painter.setPen(pen)
                for pts in _rime():
                    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                        painter.drawLine(QPointF(x0 * width, y0 * height),
                                         QPointF(x1 * width, y1 * height))
    painter.restore()
