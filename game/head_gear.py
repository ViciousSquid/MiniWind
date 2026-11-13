"""
A worn helmet drawn over the character's head.

The player's head is their whole visual identity (game/rpg/heads.py): the
paperdoll shows it, and in play it is their overhead sprite. A helmet in the
head slot is drawn over it in both places -- the item's own picture
(assets/sprites/items/<id>.png), covering the top of the head and, as a helmet
does, much of the face.

One rule places it (:func:`helmet_rect`), used both by the paperdoll, which
draws the helmet over its live head (eyes and all), and by
:func:`sprite_path`, which writes the head with its helmet to a cached image
for the overhead sprite renderer.
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The helmet's width as a share of the head's (the head's visible extent).
HELMET_WIDTH = 0.95
#: How far above the head's top edge the helmet starts, as a share of the
#: helmet's own height.
HELMET_LIFT = 0.03

_CACHE_DIR = os.path.join(tempfile.gettempdir(), "miniwind_heads")
_images = {}


def helmet_id(character) -> Optional[str]:
    """The item worn in *character*'s head slot, or None."""
    try:
        return (getattr(character, "equipment", None) or {}).get("head") or None
    except Exception:
        return None


def _image(path):
    """A cached ``QImage`` of *path* (ARGB32), or None."""
    if not path:
        return None
    img = _images.get(path)
    if img is None:
        from PyQt5.QtGui import QImage
        img = QImage(path)
        if img.isNull():
            img = False
        else:
            img = img.convertToFormat(QImage.Format_ARGB32)
        _images[path] = img
    return img or None


def _opaque_box(img) -> Tuple[int, int, int, int]:
    """(left, top, right, bottom) of *img*'s visible pixels (whole image if
    it has none)."""
    key = ("box", img.cacheKey())
    box = _images.get(key)
    if box is not None:
        return box
    w, h = img.width(), img.height()
    left, top, right, bottom = w, h, -1, -1
    step = max(1, min(w, h) // 128)          # coarse is plenty for placement
    for y in range(0, h, step):
        for x in range(0, w, step):
            if (img.pixel(x, y) >> 24) & 0xFF > 16:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
    box = (0, 0, w, h) if right < 0 else (left, top, right + 1, bottom + 1)
    _images[key] = box
    return box


def helmet_picture(item_id):
    """The helmet's picture cropped to its visible pixels (a ``QImage``), or
    None."""
    if not item_id:
        return None
    key = ("helmet", item_id)
    if key in _images:
        return _images[key]
    try:
        import game.item_icons as item_icons
        path = item_icons.icon_path(item_id)
    except Exception:
        path = os.path.join(_ROOT, "assets", "sprites", "items", f"{item_id}.png")
    img = _image(path)
    if img is not None:
        l, t, r, b = _opaque_box(img)
        img = img.copy(l, t, r - l, b - t)
    _images[key] = img
    return img


def helmet_rect(head_img, helmet_img, x, y, size):
    """Where the helmet goes over a head drawn as a *size*-pixel square at
    (*x*, *y*): ``(left, top, width, height)`` as floats."""
    hw, hh = head_img.width(), head_img.height()
    l, t, r, b = _opaque_box(head_img)
    scale = size / float(max(hw, hh))
    head_left, head_top = x + l * scale, y + t * scale
    head_width = (r - l) * scale
    width = head_width * HELMET_WIDTH
    height = helmet_img.height() * width / float(max(1, helmet_img.width()))
    left = head_left + (head_width - width) / 2.0
    top = head_top - height * HELMET_LIFT
    return left, top, width, height


def draw_helmet(painter, head_path, item_id, x, y, size) -> bool:
    """Draw the helmet *item_id* over the head at *head_path*, drawn as a
    *size*-pixel square at (*x*, *y*). False when there is nothing to draw."""
    head = _image(head_path)
    helmet = helmet_picture(item_id)
    if head is None or helmet is None:
        return False
    from PyQt5.QtCore import QRectF
    painter.save()
    painter.setRenderHint(painter.SmoothPixmapTransform, True)
    painter.drawImage(QRectF(*helmet_rect(head, helmet, x, y, size)), helmet)
    painter.restore()
    return True


def sprite_path(head_path, item_id) -> str:
    """The overhead sprite for a head wearing *item_id*: *head_path* itself
    with no helmet (or no picture for it), else a cached image of the head
    with its helmet drawn on (written once per head and helmet)."""
    if not item_id:
        return head_path
    head_abs = head_path if os.path.isabs(head_path) else os.path.join(_ROOT, head_path)
    head = _image(head_abs)
    helmet = helmet_picture(item_id)
    if head is None or helmet is None:
        return head_path
    stem = os.path.splitext(os.path.basename(head_abs))[0]
    out = os.path.join(_CACHE_DIR, f"{stem}__{item_id}.png")
    if os.path.isfile(out):
        return out
    try:
        from PyQt5.QtCore import QRectF
        from PyQt5.QtGui import QImage, QPainter
        os.makedirs(_CACHE_DIR, exist_ok=True)
        img = QImage(head)
        painter = QPainter(img)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        size = max(head.width(), head.height())
        painter.drawImage(QRectF(*helmet_rect(head, helmet, 0, 0, size)), helmet)
        painter.end()
        tmp = out + f".{os.getpid()}.tmp"
        if not img.save(tmp, "PNG"):
            return head_path
        os.replace(tmp, out)
        return out
    except Exception:
        return head_path
