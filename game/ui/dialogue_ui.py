"""
The dialogue box overlay — a framed, gilded panel across the lower third with
the speaker's line and numbered responses, and the character's **head** shown
just off the right edge of the window. Reads the live conversation from the
session's :class:`DialogueRunner`.

The head image is always the NPC's *assigned world head* (its ``head`` id,
resolved exactly like the overhead billboard via :func:`heads.any_head_path`),
so the face in the conversation is guaranteed to match the sprite the player
sees walking around the world.
"""

from __future__ import annotations

import os

from PyQt5.QtCore import QRect, QRectF, Qt
from PyQt5.QtGui import (QColor, QFont, QPixmap, QPainterPath, QLinearGradient,
                         QBrush, QPen, QFontMetrics)

from . import theme as T
from ..rpg import guilds, heads

_PIXMAP_CACHE = {}


def _pixmap(path):
    if not path:
        return None
    if path in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[path]
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    pm = QPixmap(os.path.join(root, path))
    _PIXMAP_CACHE[path] = pm if not pm.isNull() else None
    return _PIXMAP_CACHE[path]


def _head_pixmap(npc):
    """The pixmap for *npc*'s assigned world head, or ``None``.

    Resolved through :func:`heads.any_head_path` from the NPC's ``head`` id —
    the *same* resolution the runtime uses for the overhead billboard
    (see :meth:`game.runtime.GameRuntime._assign_npc_heads` and
    :func:`game.entities._apply_head_sprite`) — so the dialogue face and the
    world sprite are always the identical image.
    """
    if npc is None:
        return None
    hid = str(npc.properties.get("head", "") or "")
    if not hid:
        return None
    return _pixmap(heads.any_head_path(hid))


PAD = 18
#: Fixed default width used to size the floating conversation window; the same
#: value is fed back in as the draw width, so measurement and drawing agree.
DEFAULT_WIDTH = 760

#: Displayed head square (px). The head sits beside the window, sized to the box
#: height but never larger than this.
HEAD_MAX = 160
#: How far the left of the head image overlaps back over the window's right edge
#: (px). Kept as a single knob so the distance is easy to fine-tune.
HEAD_OVERLAP = 10

#: Body text (the speaker's line) font — kept in one place so the wrap
#: measurement in :func:`_layout` uses exactly the font the drawing uses.
_BODY_FONT = T.font(12, italic=True)

# Vertical offsets from the box top.
_TEXT_TOP = PAD + 34            # first line of the speaker's text
_GAP_AFTER_TEXT = 16            # space between the text block and the responses
_RESP_LINE_H = 24              # height of each numbered response row
_FOOTER_H = 22                 # room for the "[1-9] choose  [Esc] leave" hint
_MIN_BOX_H = 170


def _layout(session, w):
    """Measure the box for the current view at draw width *w*.

    Returns a dict of geometry (all vertical values are offsets from the box
    top). The speaker's line is measured with the real body font at the real
    text-column width so a long, multi-line greeting reserves the height it
    actually needs and the numbered responses always sit *below* it instead of
    being overdrawn (the previous fixed 58px slot let long lines overlap them).

    The head lives *outside* the window (off its right edge), so it never enters
    this measurement — the text spans the full box width.
    """
    view = session.current_view()
    responses = view["responses"] if view else []
    n_resp = max(1, len(responses))

    text_x = PAD
    text_w = max(80, int(w) - PAD - text_x)

    body = view["text"] if view else ""
    fm = QFontMetrics(_BODY_FONT)
    br = fm.boundingRect(QRect(0, 0, text_w, 100000), int(Qt.TextWordWrap), body)
    text_h = max(fm.height(), br.height())

    resp_top = _TEXT_TOP + text_h + _GAP_AFTER_TEXT
    box_h = resp_top + n_resp * _RESP_LINE_H + _FOOTER_H + PAD
    box_h = max(_MIN_BOX_H, int(box_h))

    return {
        "responses": responses,
        "text_x": text_x,
        "text_w": text_w,
        "text_h": text_h,
        "resp_top": resp_top,
        "box_h": box_h,
    }


def box_height(session):
    """Pixel height the dialogue box needs for the current view."""
    if session.current_view() is None:
        return _MIN_BOX_H
    return _layout(session, DEFAULT_WIDTH)["box_h"]


def window_body_size(session, width_hint=DEFAULT_WIDTH):
    """Suggested floating-window body size for the conversation."""
    return (width_hint, box_height(session))


def draw(painter, session, width, height):
    """Legacy full-screen placement: a box across the lower third."""
    if session.current_view() is None:
        return
    box_h = box_height(session)
    margin = max(24, int(width * 0.06))
    x = margin
    y = height - box_h - int(margin * 0.6)
    w = width - margin * 2
    _draw_content(painter, session, x, y, w, box_h, framed=True)


def draw_in_rect(painter, session, x, y, w, h):
    """Draw the conversation inside a supplied rect (e.g. a floating window),
    with no outer gilded frame — the window provides the chrome."""
    if session.current_view() is None:
        return
    _draw_content(painter, session, x, y, w, h, framed=False)


def _draw_content(painter, session, x, y, w, box_h, framed=True):
    view = session.current_view()
    if view is None:
        return
    lay = _layout(session, w)
    npc = session.dialogue_npc
    speaker = ""
    head = None
    subtitle = ""
    if npc is not None:
        speaker = npc.properties.get("display_name") or npc.properties.get("name", "")
        head = _head_pixmap(npc)
        disp = guilds.disposition(session.game.character, npc.properties)
        mood = ("friendly" if disp >= 60 else "wary" if disp >= 35 else "hostile")
        subtitle = f"Disposition {disp} ({mood})"

    pad = PAD
    if framed:
        inner = T.panel(painter, x, y, w, box_h, radius=14)
    else:
        inner = QRect(int(x), int(y), int(w), int(box_h))

    tx = x + lay["text_x"]

    if head is not None:
        _draw_head(painter, head, x, y, w, box_h)

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
    painter.setFont(_BODY_FONT)
    painter.drawText(QRect(tx, y + _TEXT_TOP, lay["text_w"], lay["text_h"]),
                     int(Qt.TextWordWrap), view["text"])

    ry = y + lay["resp_top"] + 11   # baseline of the first response row
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
        ry += _RESP_LINE_H

    painter.setPen(T.DIM)
    painter.setFont(T.font(8, family="Segoe UI"))
    painter.drawText(x + w - pad - 150, y + box_h - 10, "[1-9] choose   [Esc] leave")


def _draw_head(painter, head, x, y, w, box_h):
    """Draw the character's head just off the *right* edge of the window.

    The left of the head image overlaps :data:`HEAD_OVERLAP` px back over the
    window's right edge (``x + w``); the head is a square sized to the box
    height (capped at :data:`HEAD_MAX`) and vertically centred against it. The
    head sits in a small gilded frame so a transparent billboard PNG reads as a
    portrait beside the conversation.
    """
    hs = min(HEAD_MAX, int(box_h))
    hx = int(x + w - HEAD_OVERLAP)
    hy = int(y + (int(box_h) - hs) / 2)

    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    frame = QRect(hx, hy, hs, hs)
    painter.setBrush(QColor(20, 20, 25, 235))
    painter.setPen(QPen(T.GILD, 2))
    painter.drawRoundedRect(frame, 8, 8)
    inset = frame.adjusted(4, 4, -4, -4)
    scaled = head.scaled(inset.width(), inset.height(),
                         Qt.KeepAspectRatio, Qt.SmoothTransformation)
    # Centre the (aspect-preserved) head within the framed square.
    dx = inset.x() + (inset.width() - scaled.width()) // 2
    dy = inset.y() + (inset.height() - scaled.height()) // 2
    painter.drawPixmap(dx, dy, scaled)
    painter.restore()
