"""Rendering for MiniWind cutscene dialogue and message lines."""

from __future__ import annotations

from PyQt5.QtCore import QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPixmap

from . import fonts, theme as T


PAD = 18
DEFAULT_WIDTH = 760
HEAD_MAX = 132


def _head_pixmap(actor):
    try:
        from . import dialogue_ui
        return dialogue_ui._head_pixmap(actor)
    except Exception:
        return None


def _wrap_lines(painter, text, width):
    metrics = painter.fontMetrics()
    words = str(text).split()
    lines, line = [], ""
    for word in words:
        candidate = word if not line else line + " " + word
        if metrics.horizontalAdvance(candidate) <= width:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines or [""]


def window_body_size(cutscene):
    text = str((cutscene.dialogue or {}).get("text", "") or "")
    lines = max(1, min(7, (len(text) // 68) + 1))
    return DEFAULT_WIDTH, max(150, 88 + lines * 23)


def draw_in_rect(painter, cutscene, x, y, w, h):
    """Draw a non-modal cutscene conversation inside a CallbackWindow."""
    dialogue = cutscene.dialogue or {}
    text = str(dialogue.get("text", "") or "")
    speaker = str(dialogue.get("speaker", "") or "Narrator")
    actor = None
    try:
        actor = cutscene._find_actor(dialogue.get("speaker_id", ""))
    except Exception:
        pass

    painter.save()
    painter.setRenderHint(painter.TextAntialiasing, True)
    painter.setPen(T.INK)
    painter.setFont(T.font(15, bold=True))
    painter.drawText(QRectF(x + PAD, y + PAD, w - PAD * 2, 25),
                     Qt.AlignLeft | Qt.AlignVCenter, speaker)

    text_right = x + w - PAD
    pm = _head_pixmap(actor) if actor is not None else None
    if pm is not None and not pm.isNull():
        size = min(HEAD_MAX, h - PAD * 2)
        target = QRect(int(x + w - size - PAD), int(y + PAD), size, size)
        painter.drawPixmap(target, pm)
        text_right = target.left() - 10

    body_width = max(120, int(text_right - (x + PAD)))
    painter.setFont(fonts.dialogue_font(13))
    painter.setPen(T.text())
    lines = _wrap_lines(painter, text, body_width)
    line_h = painter.fontMetrics().height() + 3
    for i, line in enumerate(lines[:9]):
        painter.drawText(
            QRectF(x + PAD, y + PAD + 34 + i * line_h,
                   body_width, line_h),
            Qt.AlignLeft | Qt.AlignVCenter, line)

    painter.restore()


def draw(painter, cutscene, width, height):
    """Fallback full-screen conversation draw when no WindowManager exists."""
    if not cutscene.active or not cutscene.dialogue:
        return
    w, h = window_body_size(cutscene)
    w = min(w, width - 40)
    x = (width - w) // 2
    y = height - h - 54
    painter.save()
    painter.fillRect(QRect(x, y, w, h), QColor(24, 22, 20, 232))
    painter.setPen(QColor(202, 167, 82, 230))
    painter.drawRect(QRect(x, y, w, h))
    draw_in_rect(painter, cutscene, x + 1, y + 1, w - 2, h - 2)
    painter.restore()


def draw_message_lines(painter, cutscene, width, height):
    lines = cutscene.message_lines
    if not any(lines.values()):
        return
    painter.save()
    painter.setRenderHint(painter.TextAntialiasing, True)
    painter.setFont(T.font(16, bold=True))
    metrics = painter.fontMetrics()
    margin = max(20, int(width * 0.05))
    y = max(18, int(height * 0.07))
    for key in ("message", "message2", "message3"):
        text = str(lines.get(key, "") or "")
        if not text:
            continue
        tw = min(int(width * 0.78), metrics.horizontalAdvance(text) + 32)
        x = (width - tw) // 2
        rh = metrics.height() + 14
        painter.fillRect(QRect(x, y, tw, rh), QColor(10, 10, 10, 180))
        painter.setPen(QColor(226, 190, 92, 235))
        painter.drawRect(QRect(x, y, tw, rh))
        painter.setPen(T.text())
        painter.drawText(QRect(x + 16, y + 7, tw - 32, rh - 10),
                         Qt.AlignCenter, text)
        y += rh + 5
    painter.restore()
