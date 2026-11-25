"""Collectible-style cards: the game's way of showing a list of things.

A screen builds a :class:`Card` per entry (spell, item, ware ...), asks
:func:`layout` where a page of them goes, paints each with :func:`draw_card`,
and moves its selection with :func:`navigate`. The cards are drawn in the
game theme (:mod:`game.ui.theme`): a dark gradient body, a band tinted by the
card's *accent* (a spell's school, an item's category), a frame tinted by its
*frame* colour (rarity), the picture in an icon well, the title, a subtitle,
a description and a few small badges.

Two styles, chosen by :data:`LAYOUT`:

* ``"list"`` (the default): one wide card per row, top to bottom
  (:func:`layout_list`, painted by :func:`draw_row_card`): the accent as a
  strip down the left edge, a big square icon, then the title and two or
  three lines of description, the badges at the right edge. Rows are
  :data:`ROW_H` tall, or :data:`COMPACT_ROW_H` on dense screens (loot, trade).
* ``"grid"``: portrait cards in rows and columns (:func:`layout_grid`,
  :func:`draw_portrait_card`), :data:`SIZE` (150 x 210) or :data:`COMPACT`
  (110 x 150).

:func:`draw_card` paints whichever fits its rect: a row card in a rect wider
than tall, a portrait card otherwise. Everything inside a card scales with
its rect, so any size between works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from PyQt5.QtCore import QRect, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QFontMetrics, QLinearGradient, QPainterPath, QPen

from . import fonts
from . import theme as T

#: How the card screens lay out their cards: "list" (one row card per line)
#: or "grid" (portrait cards in rows and columns).
LAYOUT = "list"

#: The standard portrait card, and the compact one (logical px).
SIZE = (150, 210)
COMPACT = (110, 150)
#: The gap between cards in a grid.
GAP = 12
COMPACT_GAP = 8
#: A row card's height, standard and compact (logical px), and the gap
#: between rows.
ROW_H = 104
COMPACT_ROW_H = 80
ROW_GAP = 10
COMPACT_ROW_GAP = 8
#: How far *fit_all* may shrink rows to get every one on a page (compact
#: rows hardly at all: a dense screen pages instead).
ROW_MIN_SCALE = 0.68
COMPACT_ROW_MIN_SCALE = 0.9
#: How far rows may give to fit one more on a page that pages anyway.
ROW_FILL_SCALE = 0.86

#: Greyed-out text and frame (worn metal armour, an unaffordable ware ...).
GREY = QColor(118, 118, 126)
#: The glow of an *active* card (the readied spell, an equipped item).
ACTIVE_GLOW = QColor(110, 160, 255)

_BODY_TOP = QColor(42, 38, 56, 250)
_BODY_BOT = QColor(20, 18, 28, 250)
_WELL = QColor(12, 11, 18, 230)
_BADGE = QColor(14, 13, 20, 225)
_GREY_VEIL = QColor(18, 18, 22, 90)
#: On a parchment scroll (theme.parchment): a pale vellum card in ink.
T.ink_colours(globals(), GREY=QColor(112, 94, 76), ACTIVE_GLOW=QColor(40, 74, 160),
              _BODY_TOP=QColor(250, 240, 214, 235), _BODY_BOT=QColor(232, 214, 174, 235),
              _WELL=QColor(206, 182, 136, 200), _BADGE=QColor(248, 236, 208, 230),
              _GREY_VEIL=QColor(236, 222, 190, 120),
              _TIP_BG=QColor(246, 234, 204, 248), _TIP_EDGE=QColor(120, 84, 42))


def _tint(colour, lighten=100):
    """*colour* as text or a mark on a card: lifted *lighten* % on the dark
    card; on parchment, deepened to an ink of the same hue instead."""
    c = QColor(colour)
    if not T.inked():
        return c.lighter(lighten) if lighten != 100 else c
    return T.legible(c)


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
    *desc* is the longer description a row card wraps beside its picture
    (two or three lines; the *summary* stands in when it is empty); the
    portrait card has no room for it.
    """
    title: str
    icon: object = None                     # QPixmap or None
    subtitle: str = ""
    summary: str = ""
    desc: str = ""
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
    #: An illuminated manuscript entry (the journal): a PIGMENT_CYCLE name -- no
    #: picture; the title opens with a decorated initial on parchment.
    illuminate: str = ""
    #: One of a list in which another card is chosen: drawn faded so the
    #: chosen one stands out (see :func:`dimmed`).
    dimmed: bool = False


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


def layout_list(area: QRect, count: int, row_h: int = ROW_H, gap: int = ROW_GAP,
                fit_all: bool = False, min_scale: float = ROW_MIN_SCALE,
                fill: bool = True) -> Grid:
    """A list of row cards inside *area*: one per line, each the full width
    of *area*, *row_h* tall, as many as fit (a :class:`Grid` with one
    column, so paging and hit-testing work as for a grid). With *fit_all*,
    rows that would need more than one page shrink (down to *min_scale* of
    *row_h*) so all *count* fit on one, where they can; otherwise the list
    pages, its rows giving a little (to :data:`ROW_FILL_SCALE`) where that
    fits one more on a page (unless not *fill*: rows exactly *row_h*). A
    row never overflows *area*."""
    aw, ah = max(1, area.width()), max(1, area.height())
    rh = max(1, int(row_h))
    rows = max(0, (ah + gap) // (rh + gap))
    if fit_all and count > rows:
        fit = (ah - (count - 1) * gap) // max(1, count)
        if fit >= rh * min_scale:
            rh, rows = int(fit), count
    if fill and count > rows >= 1:
        # A page with room for most of one more row: the rows give a little
        # so it fits, rather than leave the space empty.
        tight = (ah + gap) // (int(rh * ROW_FILL_SCALE) + gap)
        if tight > rows:
            rows = min(tight, count)
            rh = min(rh, (ah - (rows - 1) * gap) // rows)
    if rows < 1:
        rh, rows = min(rh, ah), 1
    slots = [QRect(area.x(), area.y() + i * (rh + gap), aw, rh) for i in range(rows)]
    return Grid(slots, 1, rows, (aw, rh), gap)


def layout(area: QRect, count: int, *, compact: bool = False, size=None,
           gap: Optional[int] = None, grid_min_scale: float = 0.75,
           fit_all: bool = False, center: bool = True,
           row_min_scale: Optional[float] = None) -> Grid:
    """Where a page of *count* cards goes in *area*, in the :data:`LAYOUT`
    style: a list of row cards (:data:`ROW_H`, or :data:`COMPACT_ROW_H`
    when *compact*) or a grid of portrait cards (:data:`SIZE` or
    :data:`COMPACT`, shrinking to *grid_min_scale*). *size* reuses another
    layout's ``card_size`` (two columns of cards at one size): in a list
    its height is the row height. *fit_all* tries to get every card on one
    page (see :func:`layout_list` / :func:`layout_grid`), rows shrinking
    no further than *row_min_scale* (by default :data:`ROW_MIN_SCALE`, or
    :data:`COMPACT_ROW_MIN_SCALE` when *compact*)."""
    if LAYOUT == "list":
        row_h = int(size[1]) if size else (COMPACT_ROW_H if compact else ROW_H)
        g = (COMPACT_ROW_GAP if compact else ROW_GAP) if gap is None else gap
        return layout_list(area, count, row_h, g, fit_all=fit_all and not size, fill=not size,
                           min_scale=row_min_scale if row_min_scale is not None else
                           COMPACT_ROW_MIN_SCALE if compact else ROW_MIN_SCALE)
    card_size = tuple(size) if size else (COMPACT if compact else SIZE)
    g = (COMPACT_GAP if compact else GAP) if gap is None else gap
    return layout_grid(area, count, card_size, g, min_scale=1.0 if size else grid_min_scale,
                       center=center, fit_all=fit_all and not size)


def smaller(*sizes):
    """The smallest of some layouts' ``card_size`` (by area): two columns
    of cards drawn at one size."""
    return min(sizes, key=lambda wh: (wh[0] * wh[1], wh[1]))


def icon_px(painter, rect: QRect) -> int:
    """Device pixels for the picture in a card drawn in *rect* (either
    style), so the pixmap is not scaled up."""
    from . import theme
    if rect.width() > rect.height() * _ROW_ASPECT:
        side = rect.height()
    else:
        side = min(rect.width(), rect.height()) * 0.7
    return max(32, int(side * theme.device_ratio(painter)))


def navigate(index: int, direction: str, count: int, cols: int,
             page_size: Optional[int] = None) -> int:
    """The selection after a move in a grid of *count* cards, *cols* wide
    (a list is a grid one column wide).

    left / right step one card (wrapping round the whole list); up / down a
    row (onto the next or previous page past the page's edge, wrapping to
    the far end of the same column; in a list, the previous / next card);
    pageup / pagedown a whole page. A screen with two lists side by side
    (loot, trade) moves between them on left / right itself."""
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


#: A rect this much wider than tall holds a row card.
_ROW_ASPECT = 1.25


#: A card in a list that has another card chosen is drawn this opaque, so
#: the chosen one stands out; under the pointer it lifts to the second;
#: a card already greyed is only faded to the third (it stays greyed, not
#: lost).
DIM_OPACITY = 0.5
DIM_HOVER_OPACITY = 0.8
DIM_GREYED_OPACITY = 0.75


def dimmed(card: Card, others_dimmed: bool = True) -> Card:
    """*card*, marked to be drawn faded when it is one of a list in which
    another card is chosen (*others_dimmed*); the chosen one is not."""
    card.dimmed = bool(others_dimmed) and not card.selected
    return card


def draw_card(painter, rect: QRect, card: Card) -> None:
    """Paint *card* filling *rect*: as a row card (:func:`draw_row_card`)
    when *rect* is wider than tall, as a portrait card otherwise. A
    :func:`dimmed` card is drawn faded (:data:`DIM_OPACITY`)."""
    fade = 1.0
    if card.dimmed and not card.selected:
        fade = (DIM_HOVER_OPACITY if card.hovered else
                DIM_GREYED_OPACITY if (card.greyed or card.locked) else DIM_OPACITY)
    if fade < 1.0:
        painter.save()
        painter.setOpacity(painter.opacity() * fade)
    try:
        if rect.width() > rect.height() * _ROW_ASPECT:
            draw_row_card(painter, rect, card)
        else:
            draw_portrait_card(painter, rect, card)
    finally:
        if fade < 1.0:
            painter.restore()


def draw_portrait_card(painter, rect: QRect, card: Card) -> None:
    """Paint *card* as a portrait card filling *rect* (any size; laid out
    for 150 x 210)."""
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
        painter.setPen(GREY.lighter(130) if grey else _tint(accent, 140))
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
    sub_ink = GREY if grey else _tint(accent, 135)
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
        painter.fillPath(body, _GREY_VEIL)
    painter.restore()


# ------------------------------------------------------------------ row cards
def _bold(px):
    f = _font(px)
    f.setBold(True)
    return f


def _wrap_lines(text: str, fm: QFontMetrics, width: int, max_lines: int) -> List[str]:
    """*text* word-wrapped to *width*, at most *max_lines* lines; the last
    one ends in an ellipsis when there was more."""
    out: List[str] = []
    words = str(text).split()
    line = ""
    i = 0
    while i < len(words) and len(out) < max_lines:
        trial = (line + " " + words[i]).strip()
        if fm.horizontalAdvance(trial) <= width or not line:
            line = trial
            i += 1
            continue
        out.append(line)
        line = ""
    if line and len(out) < max_lines:
        out.append(line)
        line = ""
    if out and (i < len(words) or line):
        rest = " ".join([out[-1]] + ([line] if line else []) + words[i:])
        out[-1] = fm.elidedText(rest, Qt.ElideRight, width)
    return [fm.elidedText(l, Qt.ElideRight, width) for l in out]


def _row_badges(card: Card):
    """(top line, bottom line) of a row card's right-edge badges, as
    (text, colour) lists from the right edge inwards."""
    top, bottom = [], []
    colors = list(card.badge_colors)
    badges = list(card.badges)[:2]

    def col(k, default):
        return colors[k] if k < len(colors) and colors[k] is not None else default

    if card.price:
        top.append((card.price, T.GOLD_BRIGHT))
    if len(badges) > 1 and badges[1]:
        top.append((badges[1], col(1, T.DIM.lighter(120))))
    if badges and badges[0] and not card.pips:
        bottom.append((badges[0], col(0, T.GOLD)))
    return top, bottom


#: The illuminated rows' parchment, ink and the initials' pigments (main,
#: ornament) -- lapis blue with madder red, and red with blue.
_VELLUM_TOP = QColor(236, 224, 196)
_VELLUM_BOT = QColor(219, 202, 166)
_INK = QColor(52, 36, 24)
_RUBRIC = QColor(160, 52, 36)
_PIGMENTS = {"blue": (QColor(38, 68, 150), QColor(196, 96, 84)),
             "red": (QColor(172, 60, 44), QColor(52, 80, 160)),
             # Fio's own colours: its green and its orange.
             "green": (QColor(34, 177, 76), QColor(196, 70, 44)),
             "orange": (QColor(240, 128, 0), QColor(38, 68, 150)),
             # Every entry but the active quest's: warm grey inks.
             "grey": (QColor(112, 104, 96), QColor(176, 166, 154))}
#: The initials' pigments down the page, entry by entry.
PIGMENT_CYCLE = ("blue", "red", "green", "orange")
#: A rubric in grey ink (an entry that is not the active quest).
_RUBRIC_GREY = QColor(120, 110, 100)
#: The faint warm-grey band behind an entry's title.
_TITLE_BAND = QColor(120, 110, 98, 46)


def _illuminated_initial(painter, box: QRectF, letter: str, colour: str, faded: bool) -> None:
    """A decorated capital filling *box* (game/ui/initials.py, in its
    current style), the capital in the pigment *colour* -- or all in grey
    ("grey", an entry that is not the active quest); *faded* (a finished
    entry) draws it lighter."""
    from . import initials
    grey = colour == "grey"
    initials.draw(painter, box, letter, "red" if grey else colour, grey=grey,
                  opacity=0.6 if faded else 1.0)


def _draw_illuminated_row(painter, rect: QRect, card: Card) -> None:
    """A journal entry as a line of a manuscript: parchment, a decorated
    initial opening the title (the rest of it in ink, the subtitle as a red
    rubric), the objective written under it. Completed entries are faded;
    the tracked one glows; the selected one has a gold edge."""
    h = float(rect.height())
    s = max(0.4, min(1.4, h / float(ROW_H)))
    faded = card.greyed or card.locked
    r = QRectF(rect)
    rad = 6 * min(1.0, s)
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    if card.active and not faded:
        for k in range(4, 0, -1):
            painter.setPen(QPen(QColor(ACTIVE_GLOW.red(), ACTIVE_GLOW.green(),
                                       ACTIVE_GLOW.blue(), 34), k * 2.2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(r.adjusted(-1, -1, 1, 1), rad, rad)
    if card.selected:
        for k in range(3, 0, -1):
            painter.setPen(QPen(QColor(255, 214, 130, 40), k * 2.6))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(r.adjusted(-2, -2, 2, 2), rad + 2, rad + 2)
    body = QPainterPath()
    body.addRoundedRect(r, rad, rad)
    grad = QLinearGradient(0, r.top(), 0, r.bottom())
    top, bot = QColor(_VELLUM_TOP), QColor(_VELLUM_BOT)
    if card.hovered and not card.selected:
        top, bot = top.lighter(104), bot.lighter(104)
    grad.setColorAt(0.0, top)
    grad.setColorAt(1.0, bot)
    painter.fillPath(body, QBrush(grad))
    # Faint ruling, as a scribe ruled the page.
    painter.save()
    painter.setClipPath(body)
    painter.setPen(QPen(QColor(150, 120, 90, 46), 1))
    pad = max(5.0, 10 * s)
    rule = max(12.0, 22 * s)
    y = r.top() + pad + rule
    while y < r.bottom() - 2:
        painter.drawLine(int(r.left() + 6), int(y), int(r.right() - 6), int(y))
        y += rule
    painter.restore()
    # The initial: a box the row's height less the padding.
    side = max(10.0, h - 2 * pad)
    box = QRectF(r.left() + pad + side * 0.22, r.top() + pad, side * 0.86, side)
    title = card.title or ""
    # Only the active quest's entry is in colour; the rest in grey ink.
    lit = card.active and not faded
    # The rest of the title, in the manuscript's hand, then a red rubric.
    tx = box.right() + 6 * s
    right = r.right() - max(10.0, 16 * s)
    tw = max(20.0, right - tx)
    ink = QColor(_INK)
    if faded:
        ink.setAlpha(140)
    family = fonts.dialogue_family()
    from PyQt5.QtGui import QFont
    tf = QFont(family)
    tf.setPixelSize(int(max(16, 24 * s)))
    # After a one-letter word ("A Culling of Wolves") the rest is tucked up
    # to the initial rather than set a space away from it.
    rest = title[1:].lstrip()
    while tf.pixelSize() > 11 and QFontMetrics(tf).horizontalAdvance(rest) > tw:
        tf.setPixelSize(tf.pixelSize() - 1)
    tfm = QFontMetrics(tf)
    base = int(box.top() + tfm.ascent() + 2 * s)
    used = tfm.horizontalAdvance(rest)
    sub, sf = card.subtitle, None
    if sub:
        sf = QFont(family)
        sf.setPixelSize(int(max(11, 15 * s)))
        if QFontMetrics(sf).horizontalAdvance(sub) > tw - used - 14 * s:
            sub = ""
    # A faint grey band behind the title line: from the middle of the
    # initial (never out to the row's edge) to just past the title and its
    # rubric, its ends feathered. The initial and the words sit on it.
    end = tx + used + (14 * s + QFontMetrics(sf).horizontalAdvance(sub) if sub else 0)
    band = QRectF(box.center().x(), base - tfm.ascent() - 3 * s,
                  min(right, end + 14 * s) - box.center().x(),
                  tfm.ascent() + tfm.descent() + 6 * s)
    if title and band.width() > 0:
        g = QLinearGradient(band.left(), 0, band.right(), 0)
        tone = QColor(_TITLE_BAND)
        clear = QColor(tone)
        clear.setAlpha(0)
        feather = min(0.2, 18.0 / max(1.0, band.width()))
        g.setColorAt(0.0, clear)
        g.setColorAt(feather, tone)
        g.setColorAt(1.0 - feather, tone)
        g.setColorAt(1.0, clear)
        bp = QPainterPath()
        bp.addRoundedRect(band, band.height() / 2.0, band.height() / 2.0)
        painter.fillPath(bp, QBrush(g))
    if title:
        _illuminated_initial(painter, box, title[0], card.illuminate if lit else "grey",
                             faded)
    painter.setFont(tf)
    painter.setPen(ink)
    painter.drawText(int(tx), base, rest)
    if sub:
        rub = QColor(_RUBRIC if lit else _RUBRIC_GREY)
        if faded:
            rub.setAlpha(140)
        painter.setFont(sf)
        painter.setPen(rub)
        painter.drawText(int(tx + used + 14 * s), base, sub)
    text = card.desc or card.summary
    if text:
        df = QFont(family)
        df.setPixelSize(int(max(13, 17 * s)))
        dfm = QFontMetrics(df)
        line_h = dfm.lineSpacing()
        top_y = base + tfm.descent() + 4 * s
        max_lines = max(0, min(3, int((r.bottom() - pad - top_y) // line_h)))
        lines = _wrap_lines(text, dfm, int(tw), max_lines) if max_lines else []
        painter.setFont(df)
        painter.setPen(ink)
        y = top_y
        for line in lines:
            painter.drawText(QRect(int(tx), int(y), int(tw), line_h),
                             int(Qt.AlignLeft | Qt.AlignVCenter), line)
            y += line_h
    if card.active and card.mark and not faded:
        painter.setFont(_font(max(12.0, 18 * s)))
        painter.setPen(QColor(ACTIVE_GLOW).darker(130))
        painter.drawText(QRectF(r.right() - 30 * s, r.top() + 4 * s, 24 * s, 24 * s),
                         int(Qt.AlignCenter), card.mark)
    # The edge: gold when selected, a brown hairline otherwise.
    painter.setBrush(Qt.NoBrush)
    if card.selected:
        painter.setPen(QPen(T.GOLD_BRIGHT, 2.6))
    elif card.hovered:
        painter.setPen(QPen(QColor(150, 110, 60), 1.8))
    else:
        painter.setPen(QPen(QColor(120, 90, 60, 200), 1.2))
    painter.drawRoundedRect(r.adjusted(0.8, 0.8, -0.8, -0.8), rad, rad)
    painter.restore()


def draw_row_card(painter, rect: QRect, card: Card) -> None:
    """Paint *card* as one wide row filling *rect* (laid out for
    :data:`ROW_H` tall; any height from about 40 to 140 works): the accent
    as a strip down the left edge, a square icon well, the title (shrunk to
    fit, never cut short) with the subtitle after it, the description
    wrapped under them, and the badges, price and level pips at the right
    edge. Selected, hovered, active, locked and greyed look as on the
    portrait card. An *illuminate* card is a manuscript entry instead
    (:func:`_draw_illuminated_row`)."""
    if card.illuminate:
        _draw_illuminated_row(painter, rect, card)
        return
    h = float(rect.height())
    s = max(0.4, min(1.4, h / float(ROW_H)))
    grey = card.locked or card.greyed
    accent = QColor(card.accent) if card.accent is not None else QColor(T.GILD)
    frame = QColor(card.frame) if card.frame is not None else QColor(T.GILD)
    if grey:
        accent, frame = QColor(GREY).darker(115), QColor(GREY)
    r = QRectF(rect)
    rad = 8 * min(1.0, s)
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setRenderHint(painter.SmoothPixmapTransform, True)

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

    # The accent: a strip down the left edge and a wash fading from it.
    strip = max(4.0, 7 * s)
    painter.save()
    painter.setClipPath(body)
    wash = QLinearGradient(r.left(), 0, r.left() + r.width() * 0.45, 0)
    wash.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 64))
    wash.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
    painter.fillRect(r, QBrush(wash))
    band = QLinearGradient(0, r.top(), 0, r.bottom())
    band.setColorAt(0.0, QColor(accent.red(), accent.green(), accent.blue(), 230))
    band.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 150))
    painter.fillRect(QRectF(r.left(), r.top(), strip, r.height()), QBrush(band))
    painter.restore()

    # The icon well: a square the row's height less the padding.
    pad = max(4.0, 9 * s)
    side = max(8.0, h - 2 * pad)
    well = QRectF(r.left() + strip + pad, r.top() + (h - side) / 2, side, side)
    painter.setBrush(_WELL)
    painter.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 170), 1.4))
    painter.drawRoundedRect(well, 6 * s, 6 * s)
    pm = card.icon
    if pm is not None and not pm.isNull():
        if grey:
            from . import spell_lock
            pm = spell_lock.grey(pm, True)
        inset = well.adjusted(3 * s, 3 * s, -3 * s, -3 * s)
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(inset, 4 * s, 4 * s)
        painter.setClipPath(clip)
        painter.drawPixmap(inset.toRect(), pm)
        painter.restore()
    elif card.glyph:
        painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 50))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(well.center(), side * 0.38, side * 0.38)
        f, ok = fitted_font(card.glyph, int(side * 0.84), side * 0.5, side * 0.2)
        painter.setFont(f)
        painter.setPen(GREY.lighter(130) if grey else _tint(accent, 140))
        painter.drawText(well.adjusted(3, 3, -3, -3),
                         int(Qt.AlignCenter | (0 if ok else Qt.TextWordWrap)), card.glyph)
    else:
        painter.setBrush(QColor(accent.red(), accent.green(), accent.blue(), 120))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(well.center(), side * 0.22, side * 0.22)
    if card.active:
        d = max(14.0, 26 * s)
        disc = QRectF(well.left() - d * 0.25, well.top() - d * 0.25, d, d)
        glow = GREY if grey else ACTIVE_GLOW
        painter.setBrush(QColor(16, 20, 40, 240))
        painter.setPen(QPen(glow, 1.6))
        painter.drawEllipse(disc)
        painter.setFont(_font(d * 0.66))
        painter.setPen(GREY.lighter(140) if grey else QColor(225, 235, 255))
        painter.drawText(disc, int(Qt.AlignCenter), card.mark)
    bs = max(1.0, min(1.3, s * 1.15))      # badge scale: legible at any height
    if card.quantity and int(card.quantity) > 1:
        q = f"×{int(card.quantity)}"
        br = _badge_rect(painter, q, bs, int(well.right() - 2 * s), 0, True)
        br.moveBottom(int(well.bottom() - 2 * s))
        _badge(painter, br, q, GREY.lighter(130) if grey else T.INK, bs)

    # The right edge: badges (price, cost) level with the title, a note or
    # level pips under them.
    right = int(r.right() - max(8.0, 14 * s))
    top_badges, bottom_badges = _row_badges(card)
    bh = max(13, int(17 * bs))
    line1_y = int(r.top() + pad + 2 * s)
    line2_y = int(r.bottom() - pad - bh - 1 * s)
    one_line = line2_y < line1_y + bh + 3           # a short row
    if one_line:
        line1_y = line2_y = int(r.center().y() - bh / 2)
    ink_of = (lambda c: GREY.lighter(120)) if grey else (lambda c: _tint(c, 100))
    used = [0, 0]
    for line, (badges, y) in enumerate(((top_badges, line1_y), (bottom_badges, line2_y))):
        x = right - (used[0] + 6 if line and one_line and used[0] else 0)
        for text, color in badges:
            br = _badge_rect(painter, text, bs, x, y, True)
            br.setHeight(bh)
            _badge(painter, br, text, ink_of(color), bs)
            x = br.left() - int(5 * bs)
        used[line] = right - x if badges else 0
    if card.pips and card.pips[1] > 0:
        filled, total = int(card.pips[0]), int(card.pips[1])
        d = max(4.0, 8 * bs)
        gapx = 3.5 * bs
        x = right - (used[0] + 6 if one_line and used[0] else used[1])
        x0 = x - total * (d + gapx) + gapx
        cy = line2_y + bh / 2.0
        col = GREY.lighter(120) if grey else T.GOLD_BRIGHT
        for k in range(total):
            on = k < filled
            cx = x0 + k * (d + gapx) + d / 2
            painter.setPen(QPen(col if on else QColor(col.red(), col.green(), col.blue(), 120), 1))
            painter.setBrush(col if on else Qt.NoBrush)
            painter.drawEllipse(QRectF(cx - d / 2, cy - d / 2, d, d))
        used[1] = int(right - x0 + gapx)
    def reserve(w):
        return w + (int(12 * s) if w else 0)

    # The words: the title (and subtitle) on the first line, beside the top
    # badges; the description wrapped under it, beside the bottom ones.
    tx = int(well.right() + 14 * s)
    tw = max(20, int(right - reserve(max(used) if one_line else used[0]) - tx))
    dw = max(20, int(right - reserve(max(used) if one_line else used[1]) - tx))
    ink = GREY.lighter(125) if grey else (T.GOLD_BRIGHT if card.selected else T.INK)
    tf, ok = fitted_font(card.title, tw, max(16.0, 20 * s), max(10.0, 13 * s))
    tf.setBold(True)
    px = tf.pixelSize()
    while px > 8 and QFontMetrics(tf).horizontalAdvance(card.title) > tw:
        px -= 1
        tf = _bold(px)
    tfm = QFontMetrics(tf)
    title_w = tfm.horizontalAdvance(card.title)
    title_h = tfm.height()
    text = card.desc or card.summary
    df = _font(max(12.0, min(16.0, 15 * s)))
    dfm = QFontMetrics(df)
    line_h = dfm.lineSpacing()
    avail = h - 2 * pad - title_h - 3 * s
    max_lines = max(0, min(3, int(avail // line_h)))
    lines = _wrap_lines(text, dfm, dw, max_lines) if text and max_lines else []
    block = title_h + (3 * s + len(lines) * line_h if lines else 0)
    ty = r.top() + max(pad, (h - block) / 2.0)
    painter.setFont(tf)
    painter.setPen(ink)
    painter.drawText(QRect(tx, int(ty), tw + 4, title_h),
                     int(Qt.AlignLeft | Qt.AlignVCenter), card.title)
    if card.subtitle:
        sf = _font(max(11.0, min(14.0, 13 * s)))
        gap = int(12 * s)
        room = tw - title_w - gap
        sub = card.subtitle
        if QFontMetrics(sf).horizontalAdvance(sub) <= room:       # whole, or not at all
            painter.setFont(sf)
            painter.setPen(GREY if grey else _tint(accent, 135))
            base = int(ty) + (title_h + tfm.ascent() - tfm.descent()) // 2
            painter.drawText(tx + title_w + gap, base, sub)       # on the title's baseline
    if lines:
        painter.setFont(df)
        painter.setPen(GREY.lighter(115) if grey else T.PARCH)
        y = ty + title_h + 3 * s
        for line in lines:
            painter.drawText(QRect(tx, int(y), dw, line_h),
                             int(Qt.AlignLeft | Qt.AlignVCenter), line)
            y += line_h

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
        painter.drawRoundedRect(r.adjusted(3, 3, -3, -3), max(1.0, rad - 2), max(1.0, rad - 2))
    if grey:
        painter.fillPath(body, _GREY_VEIL)
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
