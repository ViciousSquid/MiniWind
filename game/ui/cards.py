"""Collectible-style cards: the game's way of showing a list of things.

A screen builds a :class:`Card` per entry (spell, item, ware ...), asks
:func:`layout_grid` where a page of them goes, paints each with
:func:`draw_card`, and moves its selection with :func:`navigate`. The cards
are drawn in the game theme (:mod:`game.ui.theme`): a dark gradient body, a
header band tinted by the card's *accent* (a spell's school, an item's
category), a frame tinted by its *frame* colour (rarity), the picture in an
icon well, a subtitle, a one-line summary and up to two corner badges.

Two sizes: :data:`SIZE` (150 x 210, portrait) and :data:`COMPACT`
(110 x 150) for screens that show many things at once (containers, trade).
Everything inside a card scales with its rect, so any size between works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from PyQt5.QtCore import QRect, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QFontMetrics, QLinearGradient, QPainterPath, QPen

from . import fonts
from . import theme as T

#: The standard portrait card, and the compact one (logical px).
SIZE = (150, 210)
COMPACT = (110, 150)
#: The gap between cards in a grid.
GAP = 12
COMPACT_GAP = 8

#: Greyed-out text and frame (worn metal armour, an unaffordable ware ...).
GREY = QColor(118, 118, 126)
#: The glow of an *active* card (the readied spell, an equipped item).
ACTIVE_GLOW = QColor(110, 160, 255)

_BODY_TOP = QColor(42, 38, 56, 250)
_BODY_BOT = QColor(20, 18, 28, 250)
_WELL = QColor(12, 11, 18, 230)
_BADGE = QColor(14, 13, 20, 225)


@dataclass
class Card:
    """What one card shows. Only *title* is required.

    Keep cards clean: secondary details (weight, value, a spell's level and
    cost ...) belong in *tooltip* (multi-line text, shown on hover or
    gamepad focus by :func:`note_tooltip` / :func:`flush_tooltip`).

    *badges* are up to two short corner labels, bottom left then bottom
    right; use one at most where it matters (a spell's "12 mp").
    *badge_colors* optionally tints each. *pips* (filled, total) draws a row
    of dots bottom left instead of a first badge (a spell's level).
    *quantity* above 1 shows a small "x3" on the icon well (a stack count);
    *price* (text, e.g. "25 g") a gold badge on the well's lower edge --
    prefer the tooltip for it. *mark* is the glyph in the well's corner when
    the card is *active* ("✦"). *glyph* is drawn large in the icon well
    when there is no *icon* (a quest's mark, a save slot's number).
    """
    title: str
    icon: object = None                     # QPixmap or None
    subtitle: str = ""
    summary: str = ""
    accent: Optional[QColor] = None         # header band
    frame: Optional[QColor] = None          # border (rarity)
    badges: Sequence[str] = ()
    badge_colors: Sequence[Optional[QColor]] = ()
    quantity: int = 0
    price: Optional[str] = None
    mark: str = "✦"
    glyph: str = ""
    tooltip: str = ""
    pips: Optional[Tuple[int, int]] = None
    selected: bool = False
    hovered: bool = False
    active: bool = False
    locked: bool = False
    greyed: bool = False


@dataclass
class Grid:
    """Where a page of cards goes: *slots* (page_size rects, row by row)."""
    slots: List[QRect] = field(default_factory=list)
    cols: int = 1
    rows: int = 1
    card_size: Tuple[int, int] = SIZE
    gap: int = GAP

    @property
    def page_size(self) -> int:
        return self.cols * self.rows

    def bounds(self) -> QRect:
        if not self.slots:
            return QRect()
        r = QRect(self.slots[0])
        for s in self.slots[1:]:
            r = r.united(s)
        return r


def layout_grid(area: QRect, count: int, card_size=SIZE, gap: int = GAP,
                min_scale: float = 0.75, center: bool = True,
                fit_all: bool = False) -> Grid:
    """A grid of cards inside *area*: as many columns and rows as fit at
    *card_size*. When only one row would fit but more are needed, the cards
    shrink (down to *min_scale*) so two rows fit; when not even one row fits
    they shrink to fit one (never past *min_scale* wide, but always inside
    *area*'s height). With *fit_all*, cards that would need more than one
    page shrink further (still not past *min_scale*) until all *count* fit
    on one, where they can. The grid is centred horizontally when *center*."""
    if fit_all and count > 0:
        grid = layout_grid(area, count, card_size, gap, min_scale, center)
        scale = 1.0
        while grid.page_size < count and scale > min_scale + 1e-6:
            scale = max(min_scale, scale - 0.04)
            size = (max(1, int(card_size[0] * scale)), max(1, int(card_size[1] * scale)))
            grid = layout_grid(area, count, size, gap, 1.0, center)
        return grid
    cw, ch = int(card_size[0]), int(card_size[1])
    aw, ah = max(1, area.width()), max(1, area.height())

    def fit(w, h):
        return max(1, (aw + gap) // (w + gap)), max(0, (ah + gap) // (h + gap))

    cols, rows = fit(cw, ch)
    if rows < 2 and count > cols:
        s = (ah - gap) / (2.0 * ch)
        if s >= min_scale:
            cw, ch = int(cw * min(1.0, s)), int(ch * min(1.0, s))
            cols, rows = fit(cw, ch)
    if rows < 1:
        s = max(0.3, min(1.0, ah / float(ch)))
        cw, ch = max(1, int(cw * s)), max(1, min(ah, int(ch * s)))
        cols, rows = fit(cw, ch)
        rows = max(1, rows)
    if cw > aw:                                       # a very narrow area
        s = aw / float(cw)
        cw, ch = aw, max(1, int(ch * s))
    used_w = cols * cw + (cols - 1) * gap
    x0 = area.x() + ((aw - used_w) // 2 if center else 0)
    slots = [QRect(x0 + c * (cw + gap), area.y() + r * (ch + gap), cw, ch)
             for r in range(rows) for c in range(cols)]
    return Grid(slots, cols, rows, (cw, ch), gap)


def navigate(index: int, direction: str, count: int, cols: int,
             page_size: Optional[int] = None) -> int:
    """The selection after a move in a grid of *count* cards, *cols* wide.

    left / right step one card (wrapping round the whole list); up / down a
    row (onto the next or previous page past the page's edge, wrapping to
    the far end of the same column); pageup / pagedown a whole page."""
    if count <= 0:
        return 0
    cols = max(1, int(cols))
    i = max(0, min(int(index), count - 1))
    last = count - 1
    if direction == "left":
        return (i - 1) % count
    if direction == "right":
        return (i + 1) % count
    if direction == "up":
        if i - cols >= 0:
            return i - cols
        col = i % cols
        return col + cols * ((last - col) // cols) if col <= last else last
    if direction == "down":
        if i + cols <= last:
            return i + cols
        if i // cols < last // cols:
            return last                     # the short last row
        return i % cols
    size = max(1, int(page_size or cols))
    if direction == "pageup":
        return max(0, (i // size - 1) * size) if i >= size else 0
    if direction == "pagedown":
        return min(last, (i // size + 1) * size) if (i // size + 1) * size <= last else i
    return i


# ------------------------------------------------------------------ painting
def _font(px):
    return fonts.dialogue_font_px(max(6, int(round(px))))


def fitted_font(text: str, width: int, px_max: float, px_min: float):
    """The largest dialogue font from *px_max* down to *px_min* in which
    *text* fits *width* on one line, and whether it fits at all."""
    px = int(round(px_max))
    while px >= int(round(px_min)):
        f = _font(px)
        if QFontMetrics(f).horizontalAdvance(text) <= width:
            return f, True
        px -= 1
    return _font(px_min), False


def _badge(painter, rect, text, color, s):
    painter.setBrush(_BADGE)
    painter.setPen(QPen(QColor(color.red(), color.green(), color.blue(), 150), 1))
    painter.drawRoundedRect(QRectF(rect), 4 * s, 4 * s)
    painter.setFont(_font(max(9.0, 10 * s)))
    painter.setPen(color)
    painter.drawText(rect, int(Qt.AlignCenter), text)


def _badge_rect(painter, text, s, x, y, anchor_right=False):
    f = _font(max(9.0, 10 * s))
    w = QFontMetrics(f).horizontalAdvance(text) + max(6, int(10 * s))
    h = max(13, int(17 * s))
    return QRect(x - w if anchor_right else x, y, w, h)


def draw_card(painter, rect: QRect, card: Card) -> None:
    """Paint *card* filling *rect* (any size; laid out for 150 x 210)."""
    s = max(0.3, min(rect.width() / float(SIZE[0]), rect.height() / float(SIZE[1])))
    compact = s < 0.86
    grey = card.locked or card.greyed
    accent = QColor(card.accent) if card.accent is not None else QColor(T.GILD)
    frame = QColor(card.frame) if card.frame is not None else QColor(T.GILD)
    if grey:
        accent, frame = QColor(GREY).darker(115), QColor(GREY)
    r = QRectF(rect)
    rad = 8 * s
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setRenderHint(painter.SmoothPixmapTransform, True)

    # Glows behind: the active card in blue, the selected one in gold.
    if card.active and not grey:
        for k in range(4, 0, -1):
            painter.setPen(QPen(QColor(ACTIVE_GLOW.red(), ACTIVE_GLOW.green(),
                                       ACTIVE_GLOW.blue(), 34), k * 2.2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(r.adjusted(-1, -1, 1, 1), rad, rad)
    if card.selected:
        for k in range(3, 0, -1):
            painter.setPen(QPen(QColor(255, 214, 130, 30), k * 2.6))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(r.adjusted(-2, -2, 2, 2), rad + 2, rad + 2)

    body = QPainterPath()
    body.addRoundedRect(r, rad, rad)
    grad = QLinearGradient(0, r.top(), 0, r.bottom())
    top, bot = QColor(_BODY_TOP), QColor(_BODY_BOT)
    if card.hovered or card.selected:
        top, bot = top.lighter(125), bot.lighter(120)
    grad.setColorAt(0.0, top)
    grad.setColorAt(1.0, bot)
    painter.fillPath(body, QBrush(grad))

    # Header band, clipped to the card's rounded top.
    head_h = (28 if compact else 34) * s / (0.82 if compact else 1.0)
    head_h = min(head_h, r.height() * 0.22)
    painter.save()
    painter.setClipPath(body)
    band = QRectF(r.left(), r.top(), r.width(), head_h)
    bg = QLinearGradient(0, band.top(), 0, band.bottom())
    bg.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 150))
    bg.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 70))
    painter.fillRect(band, QBrush(bg))
    painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 200), 1))
    painter.drawLine(int(band.left()), int(band.bottom()), int(band.right()), int(band.bottom()))
    painter.restore()

    # The title: one line, shrunk to fit; failing that, two lines; the
    # name is never cut short.
    ink = GREY.lighter(125) if grey else (T.GOLD_BRIGHT if card.selected else T.INK)
    tw = int(r.width() - 10 * s)
    title_rect = QRect(int(r.left() + 5 * s), int(r.top()), tw, int(head_h))
    f, ok = fitted_font(card.title, tw, max(11.0, 15 * s), max(9.0, 10 * s))
    flags = int(Qt.AlignCenter)
    if not ok:
        f, ok2 = None, False
        px = int(round(max(10.0, 12 * s)))
        while px >= 7:
            f = _font(px)
            br = QFontMetrics(f).boundingRect(title_rect, int(Qt.AlignCenter | Qt.TextWordWrap),
                                              card.title)
            if br.height() <= title_rect.height() and br.width() <= tw:
                break
            px -= 1
        flags = int(Qt.AlignCenter | Qt.TextWordWrap)
    painter.setFont(f)
    painter.setPen(ink)
    painter.drawText(title_rect, flags, card.title)

    # The icon well.
    y = r.top() + head_h + 6 * s
    bottom_band = 24 * s
    text_h = (0 if compact or not card.summary else 24 * s) + (16 * s if card.subtitle else 0)
    side = min(r.width() - 2 * 14 * s, r.bottom() - bottom_band - text_h - y - 4 * s)
    side = max(8.0, side)
    well = QRectF(r.center().x() - side / 2, y, side, side)
    painter.setBrush(_WELL)
    painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 170), 1.4))
    painter.drawRoundedRect(well, 6 * s, 6 * s)
    pm = card.icon
    if pm is not None and not pm.isNull():
        if grey:
            from . import spell_lock
            pm = spell_lock.grey(pm, True)
        inset = well.adjusted(4 * s, 4 * s, -4 * s, -4 * s)
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(inset, 4 * s, 4 * s)
        painter.setClipPath(clip)
        painter.drawPixmap(inset.toRect(), pm)
        painter.restore()
    elif card.glyph:
        painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 50))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(well.center(), side * 0.36, side * 0.36)
        f, ok = fitted_font(card.glyph, int(side * 0.8), side * 0.5, side * 0.2)
        painter.setFont(f)
        painter.setPen(GREY.lighter(130) if grey else accent.lighter(140))
        painter.drawText(well.adjusted(3, 3, -3, -3),
                         int(Qt.AlignCenter | (0 if ok else Qt.TextWordWrap)), card.glyph)
    else:
        painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 120))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(well.center(), side * 0.22, side * 0.22)
    if card.active:
        # A medallion on the well's corner, so it reads over any picture.
        d = max(12.0, 22 * s)
        disc = QRectF(well.left() - d * 0.3, well.top() - d * 0.3, d, d)
        glow = GREY if grey else ACTIVE_GLOW
        painter.setBrush(QColor(16, 20, 40, 240))
        painter.setPen(QPen(glow, 1.6))
        painter.drawEllipse(disc)
        painter.setFont(_font(15 * s))
        painter.setPen(GREY.lighter(140) if grey else QColor(225, 235, 255))
        painter.drawText(disc, int(Qt.AlignCenter), card.mark)
    if card.quantity and int(card.quantity) > 1:
        q = f"×{int(card.quantity)}"
        br = _badge_rect(painter, q, s, int(well.right() - 3 * s), int(well.top() + 3 * s), True)
        _badge(painter, br, q, GREY.lighter(130) if grey else T.INK, s)
    if card.price:
        br = _badge_rect(painter, card.price, s, 0, 0)
        br.moveCenter(QRect(int(well.left()), int(well.bottom() - 2 * s),
                            int(well.width()), 0).center())
        _badge(painter, br, card.price, GREY.lighter(130) if grey else T.GOLD_BRIGHT, s)

    # Subtitle and summary.
    ty = well.bottom() + 5 * s
    sub_ink = GREY if grey else accent.lighter(135)
    if card.subtitle:
        f, _ok = fitted_font(card.subtitle, tw, max(9.0, 11 * s), max(8.0, 8 * s))
        painter.setFont(f)
        painter.setPen(sub_ink)
        sub = QFontMetrics(f).elidedText(card.subtitle, Qt.ElideRight, tw)
        painter.drawText(QRect(int(r.left() + 5 * s), int(ty), tw, int(15 * s)),
                         int(Qt.AlignCenter), sub)
        ty += 16 * s
    if card.summary and not compact:
        f, _ok = fitted_font(card.summary, tw, 12 * s, 9 * s)
        painter.setFont(f)
        painter.setPen(GREY.lighter(115) if grey else T.PARCH)
        box = QRect(int(r.left() + 5 * s), int(ty), tw, int(r.bottom() - bottom_band - ty - 2 * s))
        text = card.summary
        if not _ok:
            text = QFontMetrics(f).elidedText(text, Qt.ElideRight, tw * 2 - 8)
        painter.drawText(box, int(Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap), text)

    # Corner badges along the bottom (or level pips, bottom left).
    by = int(r.bottom() - bottom_band + 2 * s)
    if card.pips and card.pips[1] > 0:
        filled, total = int(card.pips[0]), int(card.pips[1])
        d = max(3.0, 7 * s)
        cy = by + max(12, int(17 * s)) / 2.0
        for k in range(total):
            cx = r.left() + 10 * s + k * (d + 3 * s) + d / 2
            on = k < filled
            col = GREY.lighter(120) if grey else T.GOLD_BRIGHT
            painter.setPen(QPen(col if on else QColor(col.red(), col.green(), col.blue(), 120), 1))
            painter.setBrush(col if on else Qt.NoBrush)
            painter.drawEllipse(QRectF(cx - d / 2, cy - d / 2, d, d))
    for k, text in enumerate(list(card.badges)[:2]):
        if not text or (k == 0 and card.pips):
            continue
        colors = list(card.badge_colors)
        col = colors[k] if k < len(colors) and colors[k] is not None else \
            (T.GOLD if k == 0 else T.DIM.lighter(120))
        if grey:
            col = GREY.lighter(120)
        br = (_badge_rect(painter, text, s, int(r.left() + 6 * s), by) if k == 0 else
              _badge_rect(painter, text, s, int(r.right() - 6 * s), by, True))
        _badge(painter, br, text, col, s)

    # The frame, last: rarity, or gold for the selected card.
    if card.selected:
        pen = QPen(T.GOLD_BRIGHT, 2.6)
    elif card.hovered:
        pen = QPen(frame.lighter(135), 2.0)
    else:
        pen = QPen(frame.darker(115), 1.8)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(pen)
    painter.drawRoundedRect(r.adjusted(0.8, 0.8, -0.8, -0.8), rad, rad)
    if not card.selected:
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        painter.drawRoundedRect(r.adjusted(3, 3, -3, -3), rad - 2, rad - 2)
    if grey:
        painter.fillPath(body, QColor(18, 18, 22, 90))
    painter.restore()


# ------------------------------------------------------------------ tooltips
_TIP_BG = QColor(18, 16, 24, 240)
_TIP_EDGE = QColor(150, 122, 64)
_pending_tip = None


def note_tooltip(rect: QRect, card: Card, focus: bool = False) -> bool:
    """Ask for *card*'s tooltip this paint: by the pointer when it is over
    *rect*, or by the card's corner when it has gamepad *focus*. The next
    :func:`flush_tooltip` draws it. Returns whether one was asked for."""
    global _pending_tip
    if not card.tooltip:
        return False
    from . import hits
    if focus:
        _pending_tip = (card.tooltip, (rect.right() - 10, rect.bottom() - 10))
        return True
    from . import drag
    if drag.current is not None or drag.picked is not None:
        return False            # an item rides on the pointer: no tooltip over it
    if hits.pointer is not None and hits.hovered(rect):
        _pending_tip = (card.tooltip, hits.pointer)
        return True
    return False


def flush_tooltip(painter) -> None:
    """Draw the tooltip :func:`note_tooltip` asked for this paint, if any."""
    global _pending_tip
    pending, _pending_tip = _pending_tip, None
    if pending and pending[1] is not None:
        draw_tooltip(painter, pending[0], pending[1])


def draw_tooltip(painter, text: str, pos) -> QRect:
    """A multi-line tooltip below and right of *pos*, kept in the window.
    The first line is the heading (gold)."""
    lines = str(text).split("\n")
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    head, body = _font(14), _font(12)
    fh, fb = QFontMetrics(head), QFontMetrics(body)
    w = max([fh.horizontalAdvance(lines[0])] +
            [fb.horizontalAdvance(l) for l in lines[1:]]) + 20
    h = fh.height() + fb.height() * (len(lines) - 1) + 12
    x, y = int(pos[0]) + 16, int(pos[1]) + 18
    try:
        bounds = painter.window()
        if x + w > bounds.right() - 4:
            x = int(pos[0]) - w - 8
        if y + h > bounds.bottom() - 4:
            y = int(pos[1]) - h - 8
        x, y = max(bounds.left() + 4, x), max(bounds.top() + 4, y)
    except Exception:
        pass
    box = QRect(x, y, w, h)
    painter.setBrush(_TIP_BG)
    painter.setPen(QPen(_TIP_EDGE, 1.5))
    painter.drawRoundedRect(QRectF(box), 4, 4)
    ty = y + 6
    for i, line in enumerate(lines):
        f, fm = (head, fh) if i == 0 else (body, fb)
        painter.setFont(f)
        painter.setPen(T.GOLD_BRIGHT if i == 0 else T.PARCH)
        painter.drawText(QRect(x + 10, ty, w - 20, fm.height()), int(Qt.AlignLeft | Qt.AlignVCenter), line)
        ty += fm.height()
    painter.restore()
    return box
