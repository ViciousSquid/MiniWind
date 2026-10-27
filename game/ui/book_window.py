"""
Reading a book: an open book over the game, two pages at a time.

The pages are parchment (made once per size: grain, stains, a darker rim,
the shadow of the spine), the text is MiniWind's medieval face
(MedievalSharp, game/ui/fonts.py), and the book's text is laid out to fit:
title and author at the head of the first page, then the paragraphs, a
paragraph running on over the turn of a page as it would in a real book, a
``[page]`` in the text starting a fresh one.

Click the left page to turn back and the right page to turn on (or ← / →,
A / D); Esc, E or the ✕ closes the book. The book is read from
``session.reading`` (see MiniwindSession.open_book).

A **note** (``"note": true`` on the item) is not a book: it is shown as one
loose sheet of paper, folded once and a little worn -- or a torn scrap of
brown paper -- with its lines kept as they were written: a list stays a
list, a poem keeps its lines. A page of the Millbrook Crier is newsprint.
Some books are illuminated: a painted vine in the margins and an initial at
the head of the text (game/ui/page_art.py). A note longer than its sheet goes on to
another; click the sheet (or ← / →) to turn it.
"""

from __future__ import annotations

import math
import random
import zlib

import numpy as np
from PyQt5.QtCore import QPoint, QRect, QRectF, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QImage, QPainter, QPen

from engine.floating_windows import FloatingWindow

from . import hits

INK = QColor(46, 32, 20)
INK_SOFT = QColor(92, 70, 48)
COVER = QColor(58, 34, 20)
#: The book's shape: width over height of the open spread.
ASPECT = 1.33
#: Page margins, as fractions of a page's width / the book's height.
MARGIN_X = 0.11
MARGIN_TOP = 0.075
MARGIN_BOTTOM = 0.1

_parchment_cache = {}


def parchment(w, h):
    """The open book's paper: two pages of grained, stained parchment with
    a darkened rim and the spine's shadow down the middle (cached)."""
    key = (int(w), int(h))
    if key in _parchment_cache:
        return _parchment_cache[key]
    rng = np.random.default_rng(7)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)

    def noise(scale, seed):
        g = np.random.default_rng(seed).random((h // scale + 2, w // scale + 2)).astype(np.float32)
        fy, fx = ys / scale, xs / scale
        y0, x0 = fy.astype(int), fx.astype(int)
        ty, tx = fy - y0, fx - x0
        ty, tx = ty * ty * (3 - 2 * ty), tx * tx * (3 - 2 * tx)
        a = g[y0, x0] * (1 - tx) + g[y0, x0 + 1] * tx
        b = g[y0 + 1, x0] * (1 - tx) + g[y0 + 1, x0 + 1] * tx
        return a * (1 - ty) + b * ty
    tone = (noise(90, 1) - 0.5) * 22 + (noise(24, 2) - 0.5) * 10 + (rng.random((h, w)) - 0.5) * 7
    base = np.array([226, 205, 160], np.float32)
    img = base[None, None, :] + tone[..., None] * np.array([1.0, 0.95, 0.8])
    # A darker, browner rim round each page.
    half = w / 2.0
    px = np.where(xs < half, xs, w - 1 - xs)          # distance from the outer edge
    edge = np.minimum(np.minimum(px, ys), h - 1 - ys)
    rim = np.clip(1.0 - edge / (min(w, h) * 0.09), 0.0, 1.0) ** 1.6
    burnt = np.array([150, 104, 58], np.float32)
    img = img * (1 - rim[..., None] * 0.55) + burnt * rim[..., None] * 0.55
    # The spine: a shadow either side of the fold, and the fold itself.
    fold = np.abs(xs - half) / (w * 0.045)
    shade = np.clip(1.0 - fold, 0.0, 1.0) ** 2
    img *= (1.0 - 0.38 * shade)[..., None]
    # A few old stains.
    wobble = noise(40, 3) - 0.5
    for _ in range(5):
        cx, cy = rng.uniform(0.1, 0.9) * w, rng.uniform(0.1, 0.9) * h
        r = rng.uniform(0.05, 0.13) * h
        d = np.hypot(xs - cx, ys - cy) / r + wobble * 0.9
        blot = np.clip(1.0 - d, 0.0, 1.0) ** 1.5 * rng.uniform(0.04, 0.09)
        img *= (1.0 - blot)[..., None]
    arr = np.clip(img, 0, 255).astype(np.uint8)
    rgba = np.dstack([arr, np.full((h, w), 255, np.uint8)])
    qimg = QImage(np.ascontiguousarray(rgba).data, w, h, w * 4, QImage.Format_RGBA8888).copy()
    _parchment_cache[key] = qimg
    return qimg


_sheet_cache = {}


def note_paper(w, h, newsprint=False):
    """A loose sheet: grained paper, a soft worn rim, the crease of one fold
    across the middle (cached). Newsprint is greyer and smoother."""
    key = (int(w), int(h), bool(newsprint))
    if key in _sheet_cache:
        return _sheet_cache[key]
    rng = np.random.default_rng(11)
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    grain = (rng.random((h, w)).astype(np.float32) - 0.5) * (5 if newsprint else 8)
    # Soft blotches: a coarse field, smoothly enlarged (no blocks).
    from PIL import Image
    blotch = rng.random((h // 40 + 2, w // 40 + 2)).astype(np.float32)
    big = np.asarray(Image.fromarray((blotch * 255).astype(np.uint8)).resize(
        (w, h), Image.BICUBIC), np.float32) / 255.0 - 0.5
    base = np.array([214, 210, 196] if newsprint else [238, 226, 194], np.float32)
    img = base[None, None, :] + (grain + big * (6 if newsprint else 14))[..., None]
    edge = np.minimum(np.minimum(xs, w - 1 - xs), np.minimum(ys, h - 1 - ys))
    rim = np.clip(1.0 - edge / (min(w, h) * 0.06), 0.0, 1.0) ** 2
    img = img * (1 - rim[..., None] * 0.25) + np.array([170, 140, 95]) * rim[..., None] * 0.25
    # The fold: a light ridge and its shadow across the middle.
    d = (ys - h * 0.5) / max(1.0, h * 0.004)
    img *= (1.0 - 0.10 * np.exp(-(d - 1.5) ** 2) + 0.06 * np.exp(-(d + 1.5) ** 2))[..., None]
    arr = np.clip(img, 0, 255).astype(np.uint8)
    rgba = np.dstack([arr, np.full((h, w), 255, np.uint8)])
    qimg = QImage(np.ascontiguousarray(rgba).data, w, h, w * 4, QImage.Format_RGBA8888).copy()
    _sheet_cache[key] = qimg
    return qimg


def paginate_note(book, fonts, width, height):
    """A note laid out in sheets, as :func:`paginate` lays out pages, but
    line by line as it was written: each written line wraps on its own."""
    from .. import books as lib
    f_title, f_author, f_body = fonts
    mt, ma, mb = QFontMetrics(f_title), QFontMetrics(f_author), QFontMetrics(f_body)
    line_h = mb.lineSpacing()
    gap = int(line_h * 0.55)
    pages, page, y = [], [], 0

    def new_page():
        nonlocal page, y
        pages.append(page)
        page, y = [], 0
    for line in _wrap(book.title, mt, width):
        y += mt.lineSpacing()
        page.append(("title", line, y))
    if book.author:
        for line in _wrap(book.author, ma, width):
            y += ma.lineSpacing() + 2
            page.append(("author", line, y))
    y += gap * 2
    for para in book.lines:
        if para == [lib.PAGE_BREAK]:
            if page:
                new_page()
            continue
        for written in para:
            for line in _wrap(written, mb, width):
                if y + line_h > height and page:
                    new_page()
                y += line_h
                page.append(("body", line, y))
        y += gap
    if page:
        pages.append(page)
    return pages


def byline(author) -> str:
    """The line under a book's title: "By <author>", unless the author line
    already says how the book came to be ("As told by ...", "Collected in
    ...", "(no name ...)"), when it stands as written."""
    a = str(author or "").strip()
    first = a.split(" ", 1)[0].lower() if a else ""
    if a.startswith("(") or first in ("as", "by", "collected", "kept", "copied",
                                       "written", "anonymous,", "anonymous"):
        return a
    return f"By {a}"


def _wrap(text, metrics, width):
    words = text.split()
    lines, line = [], ""
    for word in words:
        trial = word if not line else line + " " + word
        if metrics.horizontalAdvance(trial) <= width or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _wrap_beside(text, metrics, width, narrow, lines):
    """Wrap *text*, its first *lines* lines *narrow* (beside an initial)."""
    out, line = [], ""
    for word in text.split():
        w = narrow if len(out) < lines else width
        trial = word if not line else line + " " + word
        if metrics.horizontalAdvance(trial) <= w or not line:
            line = trial
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    return out


def paginate(book, fonts, width, height, cap=0):
    """The book laid out in pages: each a list of ``(kind, text, y)`` where
    kind is "title", "author" or "body" and y is the baseline offset.

    With *cap* (pixels), the text opens with an illuminated initial that
    size: a ``("dropcap", letter, y)`` entry (y its top) and the first lines
    of the paragraph beside it as ``"indent"``."""
    from .. import books as lib
    f_title, f_author, f_body = fonts
    mt, ma, mb = QFontMetrics(f_title), QFontMetrics(f_author), QFontMetrics(f_body)
    line_h = mb.lineSpacing()
    gap = int(line_h * 0.65)
    pages, page, y = [], [], 0

    def new_page():
        nonlocal page, y
        pages.append(page)
        page, y = [], 0
    for line in _wrap(book.title, mt, width):
        y += mt.lineSpacing()
        page.append(("title", line, y))
    if book.author:
        for line in _wrap(byline(book.author), ma, width):
            y += ma.lineSpacing() + 2
            page.append(("author", line, y))
    y += gap * 2
    from .page_art import CAP_LINES
    initial = bool(cap)
    for para in book.paragraphs:
        if para == lib.PAGE_BREAK:
            if page:
                new_page()
            continue
        if initial and para[:1].isalpha():
            initial = False
            top = y
            page.append(("dropcap", para[0], top))
            lines = _wrap_beside(para[1:], mb, width, width - cap - 12, CAP_LINES)
            for i, line in enumerate(lines):
                if y + line_h > height and page:
                    new_page()
                y += line_h
                page.append(("indent" if i < CAP_LINES else "body", line, y))
            y = max(y, top + cap) + gap
            continue
        for line in _wrap(para, mb, width):
            if y + line_h > height and page:
                new_page()
            y += line_h
            page.append(("body", line, y))
        y += gap
    if page:
        pages.append(page)
    return pages


class BookWindow(FloatingWindow):
    """The open book (see the module docstring)."""

    wants_cursor = True

    def __init__(self, session):
        super().__init__("Book", 0, 0, width=900, body_height=680)
        self.session = session
        self.key = "screen:book"
        self.book_w, self.book_h = 900, 680
        self._layout = None          # (book id, w, h) -> pages
        self._pages = []
        self._page_rects = (QRect(), QRect())
        self._close_rect = QRect()
        from . import fonts
        self.fonts = (fonts.dialogue_font(26), fonts.dialogue_font(14),
                      fonts.dialogue_font(15))
        self.f_small = fonts.dialogue_font(11)
        self.note_fonts = (fonts.dialogue_font(21), fonts.dialogue_font(13),
                           fonts.dialogue_font(15))

    # -- size and place --------------------------------------------------
    def _is_note(self):
        return bool(self._reading().get("note"))

    def place(self, view_w, view_h):
        if self._is_note():
            # One sheet, a little taller than it is wide.
            h = int(min(view_h * 0.86, 760))
            w = int(min(view_w * 0.9, h * 0.74))
        else:
            w = int(min(1180, view_w * 0.9, (view_h * 0.9) * ASPECT))
            h = int(w / ASPECT)
        self.book_w, self.book_h = w, h
        self.width = w
        self._body_height = h
        self.window_rect = QRect((view_w - w) // 2, (view_h - h) // 2, w, h)

    def _full_rect(self):
        return QRect(self.window_rect.x(), self.window_rect.y(), self.book_w, self.book_h)

    def hit(self, pos):
        return self.active and self._full_rect().adjusted(-14, -14, 14, 14).contains(pos)

    def content_height(self):
        return self.book_h

    # -- the book ----------------------------------------------------------
    def _reading(self):
        return getattr(self.session, "reading", None) or {}

    def _book(self):
        from .. import books as lib
        return lib.get(self._reading().get("book", ""))

    def _style(self):
        from .page_art import style_of
        r = self._reading()
        return style_of(r.get("item", ""), note=bool(r.get("note")))

    def _cap(self):
        """The illuminated initial's size, for an illuminated book; else 0."""
        from .page_art import ILLUMINATED, cap_size
        if self._style() != ILLUMINATED:
            return 0
        return cap_size(QFontMetrics(self.fonts[2]).lineSpacing())

    def _layout_pages(self, book, page_w, page_h):
        cap = self._cap()
        key = (book.id, page_w, page_h, cap)
        if self._layout != key:
            self._layout = key
            self._pages = paginate(book, self.fonts, page_w, page_h, cap=cap)
            r = self._reading()
            if r is not None:
                r["spreads"] = max(1, (len(self._pages) + 1) // 2)
        return self._pages

    def _draw_note(self, painter, book, rect):
        """A note: one loose sheet, lines as written (module docstring)."""
        from . import page_art
        style = self._style()
        newsprint = style == page_art.NEWSPRINT
        if style == page_art.TORN:
            # A scrap torn from something bigger: ragged all round.
            seed = zlib.crc32(str(self._reading().get("item", "")).encode("utf-8"))
            painter.drawImage(rect.topLeft(), page_art.torn_paper(rect.width(), rect.height(), seed))
            mx = int(rect.width() * 0.14)
            top = int(rect.height() * 0.13)
            bottom = int(rect.height() * 0.12)
        else:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 110))
            painter.drawRect(rect.adjusted(6, 10, 10, 12))
            painter.drawImage(rect.topLeft(), note_paper(rect.width(), rect.height(), newsprint))
            mx = int(rect.width() * 0.1)
            top = int(rect.height() * 0.07)
            bottom = int(rect.height() * 0.08)
        page_w, page_h = rect.width() - 2 * mx, rect.height() - top - bottom
        key = ("note", book.id, page_w, page_h)
        if self._layout != key:
            self._layout = key
            self._pages = paginate_note(book, self.note_fonts, page_w, page_h)
        pages = self._pages
        r = self._reading()
        r["spreads"] = max(1, len(pages))
        sheet = max(0, min(int(r.get("spread", 0)), len(pages) - 1))
        r["spread"] = sheet
        self._page_rects = (QRect(rect.x(), rect.y(), rect.width() // 2, rect.height()),
                            QRect(rect.x() + rect.width() // 2, rect.y(),
                                  rect.width() - rect.width() // 2, rect.height()))
        ink = QColor(30, 28, 26) if newsprint else INK
        for kind, text, y in (pages[sheet] if pages else ()):
            font = {"title": self.note_fonts[0], "author": self.note_fonts[1]}.get(
                kind, self.note_fonts[2])
            painter.setFont(font)
            painter.setPen(INK_SOFT if kind == "author" else ink)
            painter.drawText(rect.x() + mx, rect.y() + top + y, text)
        if newsprint and pages:
            # The rule under a newspaper's masthead.
            painter.setPen(QPen(ink, 2))
            title_y = max((y for kind, _t, y in pages[0] if kind == "title"), default=0)
            if sheet == 0 and title_y:
                yy = rect.y() + top + title_y + 8
                painter.drawLine(rect.x() + mx, yy, rect.right() - mx, yy)
        if len(pages) > 1:
            painter.setFont(self.f_small)
            painter.setPen(INK_SOFT)
            painter.drawText(QRect(rect.x(), rect.bottom() - bottom + 8, rect.width(), 20),
                             Qt.AlignCenter, f"{sheet + 1} / {len(pages)}   (click to turn)")

    def draw(self, painter, focused=False):
        if not self.active:
            return
        book = self._book()
        rect = self._full_rect()
        if book is not None and self._is_note():
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.TextAntialiasing, True)
            self._draw_note(painter, book, rect)
            self._draw_close(painter, rect)
            painter.restore()
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        # The cover behind the pages, and the stacked page edges.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 120))
        painter.drawRoundedRect(rect.adjusted(-6, 8, 18, 22), 10, 10)
        painter.setBrush(COVER)
        painter.drawRoundedRect(rect.adjusted(-12, -10, 12, 12), 9, 9)
        for k in range(4, 0, -1):
            painter.setBrush(QColor(200 - k * 12, 180 - k * 12, 140 - k * 12))
            painter.drawRect(rect.adjusted(-k * 2, k, k * 2, k * 2))
        painter.drawImage(rect.topLeft(), parchment(rect.width(), rect.height()))
        half = rect.width() // 2
        left = QRect(rect.x(), rect.y(), half, rect.height())
        right = QRect(rect.x() + half, rect.y(), rect.width() - half, rect.height())
        self._page_rects = (left, right)
        mx = int(half * MARGIN_X)
        top = int(rect.height() * MARGIN_TOP)
        bottom = int(rect.height() * MARGIN_BOTTOM)
        page_w = half - 2 * mx
        page_h = rect.height() - top - bottom
        if book is None:
            painter.setFont(self.fonts[2])
            painter.setPen(INK)
            painter.drawText(left.adjusted(mx, top, -mx, -bottom), Qt.AlignTop | Qt.TextWordWrap,
                             "The pages are blank.")
            painter.restore()
            return
        pages = self._layout_pages(book, page_w, page_h)
        r = self._reading()
        spreads = max(1, (len(pages) + 1) // 2)
        spread = max(0, min(int(r.get("spread", 0)), spreads - 1))
        r["spread"] = spread
        cap = self._cap()
        from . import page_art
        for side, area in enumerate((left, right)):
            index = spread * 2 + side
            if index >= len(pages):
                continue
            if cap:
                # An illuminated book: a vine climbs each page's outer margin.
                page_art.draw_vine(
                    painter, page_art.border_points(QRectF(area), "left" if side == 0 else "right",
                                                    mx, zlib.crc32(f"{book.id}{index}".encode())),
                    zlib.crc32(f"{book.id}:{index}".encode()), scale=max(0.7, area.height() / 700.0))
            ox = area.x() + mx + (mx // 4 if side == 0 else -mx // 4)
            oy = area.y() + top
            for kind, text, y in pages[index]:
                if kind == "dropcap":
                    page_art.draw_initial(painter, text, QRect(ox, oy + y + 4, cap, cap),
                                          self._cap_font(cap), seed=zlib.crc32(book.id.encode()))
                    continue
                font = {"title": self.fonts[0], "author": self.fonts[1]}.get(kind, self.fonts[2])
                painter.setFont(font)
                painter.setPen(INK_SOFT if kind == "author" else INK)
                painter.drawText(ox + (cap + 12 if kind == "indent" else 0), oy + y, text)
            # The page number at the foot.
            painter.setFont(self.f_small)
            painter.setPen(INK_SOFT)
            painter.drawText(QRect(area.x(), area.bottom() - bottom + 12, area.width(), 20),
                             Qt.AlignCenter, f"{index + 1}")
        # Turn-the-page hints at the bottom corners, and the close mark.
        painter.setFont(self.fonts[1])
        if spread > 0:
            hot = hits.hovered(left)
            painter.setPen(INK if hot else INK_SOFT)
            painter.drawText(QRect(left.x() + mx // 2, left.bottom() - bottom + 10, 140, 24),
                             Qt.AlignLeft | Qt.AlignVCenter, "‹ turn back")
        if spread < spreads - 1:
            hot = hits.hovered(right)
            painter.setPen(INK if hot else INK_SOFT)
            painter.drawText(QRect(right.right() - mx // 2 - 140, right.bottom() - bottom + 10, 140, 24),
                             Qt.AlignRight | Qt.AlignVCenter, "turn on ›")
        self._draw_close(painter, rect)
        painter.restore()

    def _cap_font(self, cap):
        """The illuminated initial's face, sized to its box (cached)."""
        if getattr(self, "_cap_font_for", None) != cap:
            from . import fonts
            self._cap_font_for = cap
            self._cap_font_face = fonts.dialogue_font_px(int(cap * 0.78))
        return self._cap_font_face

    def _draw_close(self, painter, rect):
        self._close_rect = QRect(rect.right() - 8, rect.y() - 22, 30, 30)
        painter.setBrush(COVER.lighter(140) if hits.hovered(self._close_rect) else COVER)
        painter.setPen(QPen(QColor(200, 170, 110), 1.5))
        painter.drawEllipse(self._close_rect)
        painter.setFont(self.f_small)
        painter.setPen(QColor(235, 215, 170))
        painter.drawText(self._close_rect, Qt.AlignCenter, "✕")

    # -- mouse -------------------------------------------------------------
    def handle_mouse_press(self, event):
        if not self.active:
            return False
        p = event.pos()
        if self._close_rect.contains(p):
            self.on_close()
            return True
        left, right = self._page_rects
        if left.contains(p):
            self._queue_turn(-1)
            return True
        if right.contains(p):
            self._queue_turn(+1)
            return True
        return self.hit(p)

    def handle_mouse_move(self, event, view_w, view_h):
        return False

    def handle_mouse_release(self, event):
        return False

    def _queue_turn(self, step):
        hits.queue(lambda session: session.turn_book(step))

    def on_close(self):
        self.active = False
        hits.queue(lambda session: session.close_book())
