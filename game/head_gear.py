"""
A worn helmet drawn over the character's head.

The player's head is their whole visual identity (game/rpg/heads.py): the
paperdoll shows it, and in play it is their overhead sprite. A helmet in the
head slot is drawn over it in both places -- the item's own picture
(assets/sprites/items/<id>.png), hiding the head and, as a helmet does, most
of the face.

Worn, the picture is turned to face out and its visor's openings are cut
through (:data:`VISORS`), so the face and eyes show through them.

Nothing of the head shows outside the helmet: it is clipped to the helmet's
shape, so only the face shows, through the visor. Every helmet is drawn the
same size, filling the head's square; the head moves (and, behind eye slits,
scales a little) so its eyes sit in the openings.
One picture (:func:`composite`) serves the paperdoll and, written to a
cached file (:func:`sprite_path`), the overhead sprite renderer.
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: The helmet's largest width, as a share of the head's square.
HELMET_WIDTH = 0.95
#: The item pictures show a helmet turned three-quarters away; worn, it is
#: turned back (degrees, anticlockwise) so the visor faces straight out.
HELMET_TURN = 35.0
#: Where a head's eyes sit (a share of its visible height) when they cannot be
#: found in the picture.
EYE_LINE = 0.58

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


def _array(img):
    """*img* (ARGB32) as an (h, w, 4) uint8 RGBA numpy array (a copy)."""
    import numpy as np
    w, h = img.width(), img.height()
    ptr = img.constBits()
    ptr.setsize(img.byteCount())
    bgra = np.frombuffer(ptr, np.uint8).reshape(h, img.bytesPerLine())[:, :w * 4]
    bgra = bgra.reshape(h, w, 4)
    return bgra[:, :, [2, 1, 0, 3]].copy()


def _from_array(arr):
    from PyQt5.QtGui import QImage
    import numpy as np
    h, w = arr.shape[:2]
    bgra = np.ascontiguousarray(arr[:, :, [2, 1, 0, 3]])
    return QImage(bgra.data, w, h, 4 * w, QImage.Format_ARGB32).copy()


def _opaque_box(img) -> Tuple[int, int, int, int]:
    """(left, top, right, bottom) of *img*'s visible pixels (whole image if
    it has none)."""
    key = ("box", img.cacheKey())
    box = _images.get(key)
    if box is not None:
        return box
    import numpy as np
    alpha = _array(img)[:, :, 3] > 16
    ys, xs = np.nonzero(alpha)
    if len(xs) == 0:
        box = (0, 0, img.width(), img.height())
    else:
        box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    _images[key] = box
    return box


#: Where each kind of helmet picture has its visor's openings, once turned to
#: face out: ``(left, top, right, bottom)`` as shares of the turned, cropped
#: picture. Inside them the visor's dark grey is cut through (the bars and
#: rims, lighter or outside, stay).
VISORS = {
    # Two eye slits either side of the nose bar.
    "slits": ((0.09, 0.465, 0.335, 0.62), (0.47, 0.465, 0.70, 0.62)),
    # One opening for the whole face.
    "open": ((0.16, 0.45, 0.71, 0.86),),
}
#: Which kind of visor each helmet picture has; an item can name its own
#: with ``"visor": "slits" | "open"``. Anything else is taken as open-faced.
VISOR_OF = {
    "iron_helmet": "slits", "steel_helmet": "slits",
    "plate_helm": "slits", "scale_helm": "slits",
    "leather_helmet": "open", "hide_cap": "open",
    "cloth_hood": "open", "chain_coif": "open",
}


def visor_kind(item_id) -> str:
    try:
        import game.rpg.items as items
        d = items.get(item_id)
        own = d.get("visor") if d is not None else None
    except Exception:
        own = None
    kind = own or VISOR_OF.get(str(item_id), "open")
    return kind if kind in VISORS else "open"


def _visor(arr, kind="open"):
    """The visor's openings in a worn helmet's RGBA array: within the
    *kind* of visor's regions (:data:`VISORS`), the flat dark grey the
    pictures paint them. Returns a boolean mask."""
    import numpy as np
    h, w = arr.shape[:2]
    rgb = arr[:, :, :3].astype(np.int16)
    grey = (rgb.max(axis=2) - rgb.min(axis=2)) < 18
    value = rgb.mean(axis=2)
    dark = grey & (value > 45) & (value < 98) & (arr[:, :, 3] > 200)
    region = np.zeros((h, w), dtype=bool)
    for l, t, r, b in VISORS.get(kind, VISORS["open"]):
        region[int(t * h):int(b * h), int(l * w):int(r * w)] = True
    return dark & region


def helmet_picture(item_id):
    """The helmet as worn: its picture turned to face out and cropped.
    ``(helmet, outline, (ox, oy), slits)``: the picture with the visor's
    openings cut through, the whole helmet's shape (openings included, for
    clipping the head to), the middle of the openings in the picture's
    pixels, and a slit visor's two openings' x centres (else None).
    None when the item has no picture."""
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
    out = None
    if img is not None:
        try:
            import numpy as np
            from PyQt5.QtCore import Qt
            from PyQt5.QtGui import QImage, QTransform
            l, t, r, b = _opaque_box(img)
            turned = img.copy(l, t, r - l, b - t).transformed(
                QTransform().rotate(-HELMET_TURN), Qt.SmoothTransformation)
            turned = turned.convertToFormat(QImage.Format_ARGB32)
            l, t, r, b = _opaque_box(turned)
            arr = _array(turned)[t:b, l:r]
            outline = _from_array(arr)
            visor = _visor(arr, visor_kind(item_id))
            arr[visor, 3] = 0
            # The openings' middle: the middle of the visor's regions.
            boxes = VISORS[visor_kind(item_id)]
            hh, ww = arr.shape[:2]
            centre = (ww * sum((l + r) / 2.0 for l, _t, r, _b in boxes) / len(boxes),
                      hh * sum((t + b) / 2.0 for _l, t, _r, b in boxes) / len(boxes))
            slits = (tuple(ww * (l + r) / 2.0 for l, _t, r, _b in boxes)
                     if len(boxes) == 2 else None)
            out = (_from_array(arr), outline, centre, slits)
        except Exception:
            out = None
    _images[key] = out
    return out


def _eyes(head_path, head_img):
    """The middle of the head's two eyes, in its picture's pixels."""
    key = ("eyes", head_path)
    if key in _images:
        return _images[key]
    centre = None
    try:
        import game.ui.eye_rig as eye_rig
        rig = eye_rig.rig_for(head_path, head_img.width())
        if rig is not None and rig.centres:
            centre = (sum(x for x, _ in rig.centres) / len(rig.centres),
                      sum(y for _, y in rig.centres) / len(rig.centres))
    except Exception:
        centre = None
    if centre is None:
        l, t, r, b = _opaque_box(head_img)
        centre = ((l + r) / 2.0, t + (b - t) * EYE_LINE)
    _images[key] = centre
    return centre


def _eye_pair(head_path, head_img):
    """The head's two eye centres, left then right (picture pixels), or None
    when they cannot be found."""
    key = ("eye_pair", head_path)
    if key in _images:
        return _images[key]
    pair = None
    try:
        import game.ui.eye_rig as eye_rig
        rig = eye_rig.rig_for(head_path, head_img.width())
        if rig is not None and len(rig.centres) >= 2:
            pair = tuple(sorted(rig.centres[:2]))
    except Exception:
        pair = None
    _images[key] = pair
    return pair


def placement(head_path, head_img, worn, size):
    """How a head and its helmet sit in a *size*-pixel square.

    The helmet is the same for every head: as large as fits the square,
    centred. The head moves to it -- shifted so its eyes sit in the visor's
    openings and, for eye slits, scaled so the eyes match the slits' spacing
    -- since only the face, through the visor, shows. Returns
    ``((left, top, width, height), (scale, dx, dy))``: the helmet's rect,
    and the head drawn at *scale* times the square's size, offset (dx, dy)."""
    helmet, _outline, (ox, oy) = worn[:3]
    pw, ph = float(max(1, helmet.width())), float(max(1, helmet.height()))
    k = min(HELMET_WIDTH * size / pw, 0.98 * size / ph)
    left, top = (size - pw * k) / 2.0, (size - ph * k) / 2.0
    hs = size / float(max(head_img.width(), head_img.height()))
    ex, ey = _eyes(head_path, head_img)
    scale = 1.0
    slits = worn_slits(worn)
    pair = _eye_pair(head_path, head_img)
    if slits is not None and pair is not None:
        gap_eyes = abs(pair[1][0] - pair[0][0]) * hs
        gap_slits = abs(slits[1] - slits[0]) * k
        if gap_eyes > 1:
            scale = max(0.8, min(1.25, gap_slits / gap_eyes))
    dx = left + ox * k - ex * hs * scale
    dy = top + oy * k - ey * hs * scale
    return (left, top, pw * k, ph * k), (scale, dx, dy)


def worn_slits(worn):
    """The x centres of a slit visor's two openings in the worn picture, or
    None for an open face."""
    return worn[3] if len(worn) > 3 else None


def composite(head_path, item_id):
    """The head at *head_path* wearing *item_id*, as a ``QImage`` the head's
    size: only what shows through the visor is left of the head -- nothing
    of it outside the helmet -- with the helmet over it. None when either
    picture is missing. Cached."""
    key = ("worn", head_path, item_id)
    if key in _images:
        return _images[key]
    head = _image(head_path)
    worn = helmet_picture(item_id)
    out = None
    if head is not None and worn is not None:
        from PyQt5.QtCore import QRectF
        from PyQt5.QtGui import QImage, QPainter
        size = max(head.width(), head.height())
        box, (scale, dx, dy) = placement(head_path, head, worn, size)
        rect = QRectF(*box)
        mask = QImage(head.size(), QImage.Format_ARGB32_Premultiplied)
        mask.fill(0)
        p = QPainter(mask)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(rect, worn[1])                  # the helmet's whole shape
        p.end()
        out = QImage(head.size(), QImage.Format_ARGB32_Premultiplied)
        out.fill(0)
        p = QPainter(out)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(QRectF(dx, dy, size * scale, size * scale), head)   # eyes in the visor
        p.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        p.drawImage(0, 0, mask)                     # the head, inside it only
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.drawImage(rect, worn[0])                  # the helmet, openings cut
        p.end()
        out = out.convertToFormat(QImage.Format_ARGB32)
    _images[key] = out
    return out


def draw_worn(painter, head_path, item_id, x, y, size) -> bool:
    """Draw the head at *head_path* wearing *item_id* as a *size*-pixel
    square at (*x*, *y*) (see :func:`composite`). False when there is nothing
    to draw (the caller draws the bare head)."""
    img = composite(head_path, item_id)
    if img is None:
        return False
    from PyQt5.QtCore import QRectF
    painter.save()
    painter.setRenderHint(painter.SmoothPixmapTransform, True)
    painter.drawImage(QRectF(x, y, size, size), img)
    painter.restore()
    return True


def sprite_path(head_path, item_id) -> str:
    """The overhead sprite for a head wearing *item_id*: *head_path* itself
    with no helmet (or no picture for it), else a cached image of
    :func:`composite` (written once per head and helmet)."""
    if not item_id:
        return head_path
    head_abs = head_path if os.path.isabs(head_path) else os.path.join(_ROOT, head_path)
    stem = os.path.splitext(os.path.basename(head_abs))[0]
    out = os.path.join(_CACHE_DIR, f"{stem}__{item_id}__v7.png")
    if os.path.isfile(out):
        return out
    img = composite(head_abs, item_id)
    if img is None:
        return head_path
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        tmp = out + f".{os.getpid()}.tmp"
        if not img.save(tmp, "PNG"):
            return head_path
        os.replace(tmp, out)
        return out
    except Exception:
        return head_path
