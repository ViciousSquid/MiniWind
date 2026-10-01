"""
The trade screen's motion: a bought or sold item flies across.

When an item changes hands, a copy of its row lifts out of the column it was
in and glides, in a shallow arc, to the row it becomes on the other side (or,
when the other side has no row for it, to the foot of that column, where it
fades into the stock). A row that only appears because of the trade stays
hidden until the card lands on it, so the item is seen to *move*, not to be
in two places at once. The price floats up from the gold total.

The trade itself happens on the game tick (:func:`launch` is called there);
everything else runs while the screen paints. :func:`begin_frame` /
:func:`record_row` / :func:`record_column` note where this frame's rows are, so
a flight knows where it starts and where it lands.
"""

from __future__ import annotations

import math
import threading
import time

#: How long an item takes to cross, and how long the price floats.
FLIGHT_SECONDS = 0.55
GOLD_SECONDS = 1.2
#: Height of the arc at mid-flight (px) and how much the card swells.
ARC = 46
SWELL = 0.08

_lock = threading.Lock()
_flights = []           # dicts, see launch()
_floaters = []          # (start, text, gain)
_rows = {}              # (side, item id) -> QRect of the row drawn this frame
_columns = {}           # side -> QRect of the next free row slot in that column
_gold_anchor = None     # QPoint where the gold total ends


def begin_frame():
    """A new paint of the trade screen: rows are re-recorded as they draw."""
    _rows.clear()
    _columns.clear()


def record_row(side, item_id, rect):
    _rows[(side, item_id)] = rect


def record_column(side, next_slot):
    """*next_slot*: the rect a new row would occupy at the foot of *side*."""
    _columns[side] = next_slot


def record_gold(point):
    global _gold_anchor
    _gold_anchor = point


def reset():
    with _lock:
        _flights.clear()
        _floaters.clear()
    begin_frame()


def launch(item_id, label, price_text, from_side, to_side, lands_on_new_row,
           gold_text=None, gold_gain=False, now=None):
    """Start an item's flight (called from the game tick after a trade).

    Needs the row the item was drawn in last frame; with none (the screen was
    never painted) the trade simply happens without motion.
    """
    start = time.monotonic() if now is None else now
    source = _rows.get((from_side, item_id))
    with _lock:
        if source is not None:
            _flights.append({
                "start": start, "item": item_id, "label": label,
                "price": price_text, "to": to_side, "from_rect": source,
                "hide_landing": bool(lands_on_new_row)})
        if gold_text:
            _floaters.append((start, gold_text, bool(gold_gain)))


def active(now=None) -> bool:
    now = time.monotonic() if now is None else now
    with _lock:
        return (any(now - f["start"] < FLIGHT_SECONDS for f in _flights)
                or any(now - s < GOLD_SECONDS for s, _t, _g in _floaters))


def landing_hidden(side, item_id, now=None) -> bool:
    """Is a row still waiting for its item to arrive? (Draw it empty if so.)"""
    now = time.monotonic() if now is None else now
    with _lock:
        return any(f["to"] == side and f["item"] == item_id and f["hide_landing"]
                   and now - f["start"] < FLIGHT_SECONDS for f in _flights)


def _ease(t):
    """Ease in and out: a slow lift, a quick crossing, a soft landing."""
    return t * t * (3.0 - 2.0 * t)


def draw(painter, now=None):
    """Paint every flight and gold floater in progress, dropping finished ones."""
    from PyQt5.QtCore import QRectF, Qt
    from PyQt5.QtGui import QColor, QPen
    from . import fonts
    from . import theme as T

    now = time.monotonic() if now is None else now
    with _lock:
        _flights[:] = [f for f in _flights if now - f["start"] < FLIGHT_SECONDS]
        _floaters[:] = [x for x in _floaters if now - x[0] < GOLD_SECONDS]
        flights = list(_flights)
        floaters = list(_floaters)

    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    for f in flights:
        t = max(0.0, min(1.0, (now - f["start"]) / FLIGHT_SECONDS))
        k = _ease(t)
        src = f["from_rect"]
        dst = _rows.get((f["to"], f["item"]))
        into_stock = dst is None
        if into_stock:
            dst = _columns.get(f["to"], src)
        x = src.x() + (dst.x() - src.x()) * k
        y = src.y() + (dst.y() - src.y()) * k - ARC * math.sin(math.pi * t)
        swell = 1.0 + SWELL * math.sin(math.pi * t)
        w = src.width() * swell
        h = src.height() * swell
        x -= (w - src.width()) / 2.0
        y -= (h - src.height()) / 2.0
        # A card going into the merchant's stock (no row to land on) fades as
        # it arrives; one landing on a row simply becomes it.
        alpha = 1.0 - max(0.0, (t - 0.7) / 0.3) if into_stock else 1.0
        card = QRectF(x, y, w, h)

        painter.setOpacity(0.35 * alpha)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0))
        painter.drawRoundedRect(card.translated(3, 6 + 10 * math.sin(math.pi * t)), 4, 4)

        painter.setOpacity(alpha)
        painter.setBrush(T.SELECT)
        painter.setPen(QPen(T.GOLD_BRIGHT, 1.5))
        painter.drawRoundedRect(card, 4, 4)
        painter.setFont(fonts.dialogue_font(10))
        painter.setPen(T.GOLD_BRIGHT)
        painter.drawText(card.adjusted(8, 0, -8, 0),
                         int(Qt.AlignVCenter | Qt.AlignLeft), f["label"])
        painter.setPen(T.GOLD)
        painter.drawText(card.adjusted(8, 0, -8, 0),
                         int(Qt.AlignVCenter | Qt.AlignRight), f["price"])

    anchor = _gold_anchor
    if anchor is not None:
        for start, text, gain in floaters:
            t = max(0.0, min(1.0, (now - start) / GOLD_SECONDS))
            painter.setOpacity(1.0 - t * t)
            painter.setFont(fonts.dialogue_font(12))
            painter.setPen(QColor(150, 220, 120) if gain else QColor(230, 120, 100))
            painter.drawText(int(anchor.x()), int(anchor.y() - 30 * _ease(t)), text)
    painter.restore()
