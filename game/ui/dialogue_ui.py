"""
The dialogue box overlay — a framed, gilded panel across the lower third with a
portrait, the speaker's line and numbered responses. Reads the live conversation
from the session's :class:`DialogueRunner`.
"""

from __future__ import annotations

import os

from PyQt5.QtCore import QRect, QRectF, Qt
from PyQt5.QtGui import (QColor, QFont, QPixmap, QPainterPath, QLinearGradient,
                         QBrush, QPen)

from . import theme as T
from ..rpg import guilds

_PORTRAIT_CACHE = {}


def _portrait(path):
    if not path:
        return None
    if path in _PORTRAIT_CACHE:
        return _PORTRAIT_CACHE[path]
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    pm = QPixmap(os.path.join(root, path))
    _PORTRAIT_CACHE[path] = pm if not pm.isNull() else None
    return _PORTRAIT_CACHE[path]


def draw(painter, session, width, height):
    view = session.current_view()
    if view is None:
        return
    npc = session.dialogue_npc
    speaker = ""
    portrait = None
    subtitle = ""
    if npc is not None:
        speaker = npc.properties.get("display_name") or npc.properties.get("name", "")
        portrait = _portrait(npc.properties.get("portrait", ""))
        disp = guilds.disposition(session.game.character, npc.properties)
        mood = ("friendly" if disp >= 60 else "wary" if disp >= 35 else "hostile")
        subtitle = f"Disposition {disp} ({mood})"

    margin = max(24, int(width * 0.06))
    pad = 18
    n_resp = max(1, len(view["responses"]))
    content_h = 40 + 58 + n_resp * 24 + 22
    box_h = max(170, pad * 2 + content_h)
    x = margin
    y = height - box_h - int(margin * 0.6)
    w = width - margin * 2

    inner = T.panel(painter, x, y, w, box_h, radius=14)
    tx = inner.x()

    if portrait is not None:
        ps = box_h - pad * 2 - 8
        px, py = x + pad, y + pad
        painter.fillRect(QRect(px - 2, py - 2, ps + 4, ps + 4), T.GILD)
        scaled = portrait.scaled(ps, ps, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        painter.drawPixmap(QRect(px, py, ps, ps), scaled, QRect(0, 0, scaled.width(), scaled.height()))
        tx = px + ps + pad

    painter.setPen(T.GOLD_BRIGHT)
    painter.setFont(T.font(16, bold=True))
    painter.drawText(tx, y + pad + 16, speaker)
    if subtitle:
        painter.setFont(T.font(8, italic=True, family="Segoe UI"))
        painter.setPen(T.DIM)
        painter.drawText(inner.right() - 170, y + pad + 14, subtitle)
    painter.setPen(QPen(T.GILD, 1))
    painter.drawLine(tx, y + pad + 26, x + w - pad, y + pad + 26)

    painter.setPen(T.PARCH)
    painter.setFont(T.font(12, italic=True))
    text_w = x + w - pad - tx
    painter.drawText(QRect(tx, y + pad + 34, text_w, 58), int(Qt.TextWordWrap), view["text"])

    painter.setFont(T.font(11, family="Segoe UI"))
    ry = y + pad + 104
    for i, resp in enumerate(view["responses"]):
        chip = QRect(tx, ry - 13, 18, 18)
        painter.setBrush(QColor(60, 52, 78))
        painter.setPen(QPen(T.GILD, 1))
        painter.drawRoundedRect(chip, 4, 4)
        painter.setPen(T.GOLD_BRIGHT)
        painter.setFont(T.font(9, bold=True, family="Segoe UI"))
        painter.drawText(chip, T.ALIGN_CENTER, str(i + 1))
        painter.setPen(QColor(180, 210, 255))
        painter.setFont(T.font(11, family="Segoe UI"))
        painter.drawText(tx + 26, ry, resp.get("text", ""))
        ry += 24

    painter.setPen(T.DIM)
    painter.setFont(T.font(8, family="Segoe UI"))
    painter.drawText(x + w - pad - 150, y + box_h - 10, "[1-9] choose   [Esc] leave")
