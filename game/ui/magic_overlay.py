"""
Whole-screen magic washes, drawn with the overlay painter over the world and
under the HUD (the tints of :meth:`game.magic_fx.MagicFX.frame`):

* ``blood`` -- the resurrection: the middle of the screen sinks into a dark
  red with a slow heartbeat in it, while the edges darken in a grainy
  halftone, streaked like an old print -- the red never reaches them;
* ``vignette`` -- a hit by fire, arcane force or disintegration: the edges of
  sight flare in the spell's colour;
* ``frost`` -- frostbite: rime creeps in from the corners, white-blue and
  splintered;
* ``flash`` -- lightning: one bright blink.
"""

from __future__ import annotations

import math
import random
import threading

import numpy as np
from PyQt5.QtCore import QPointF, QRect
from PyQt5.QtGui import QColor, QImage, QPainter, QPen, QRadialGradient

#: Rime lines in the frost wash: generated once, in unit coordinates.
_RIME = None
#: The halftone masks, built once at this resolution (scaled up unsmoothed, so
#: the grain stays crisp), and how many there are to churn between.
HALFTONE_SIZE = (800, 450)
HALFTONE_FRAMES = 6
#: The grain jumps this often: to a random mask, at a random jitter of up to
#: HALFTONE_JITTER pixels, so it boils rather than cycles.
HALFTONE_FPS = 24.0
HALFTONE_JITTER = 9
#: The halftone's ink, and the red in the middle.
HALFTONE_INK = (14, 8, 10)
_HALFTONE = None
_BUILD_LOCK = threading.Lock()
#: (frame, colour) -> the centre mask filled with that colour.
_TINTED = {}


def _halftone_masks():
    """``[(edge, centre)]`` QImages: grainy dark edges and the red middle that
    is everything they leave (see the module doc)."""
    global _HALFTONE
    if _HALFTONE is not None:
        return _HALFTONE
    with _BUILD_LOCK:
        if _HALFTONE is None:
            _HALFTONE = _build_halftone()
    return _HALFTONE


def prepare() -> None:
    """Build the halftone masks in the background (a resurrection's first
    frame would otherwise wait for them)."""
    import threading
    threading.Thread(target=_halftone_masks, name="halftone", daemon=True).start()


def _build_halftone():
    w, h = HALFTONE_SIZE
    rng = np.random.default_rng(11)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    # An uneven ellipse: its rim wobbles with a coarse noise.
    coarse = rng.random((9, 16)).astype(np.float32)
    wobble = np.kron(coarse, np.ones((h // 9 + 1, w // 16 + 1), np.float32))[:h, :w]
    d = np.sqrt(((xx - w / 2) / (w * 0.40)) ** 2 + ((yy - h / 2) / (h * 0.38)) ** 2)
    d += (wobble - 0.5) * 0.22
    edge = np.clip((d - 0.62) / 0.75, 0.0, 1.0)
    frames = []
    for _ in range(HALFTONE_FRAMES):
        # Horizontal streaks: noise stretched along each row, plus fine grain.
        cols = w // 7 + 2
        streak = rng.random((h, cols)).astype(np.float32)
        streak = np.repeat(streak, 7, axis=1)[:, :w]
        shift = rng.integers(0, 7, size=h)
        streak = np.stack([np.roll(row, k) for row, k in zip(streak, shift)])
        grain = rng.random((h, w)).astype(np.float32)
        noise = streak * 0.6 + grain * 0.4
        ink = noise < edge
        edge_rgba = np.zeros((h, w, 4), np.uint8)
        edge_rgba[ink] = (*HALFTONE_INK, 255)
        centre_rgba = np.zeros((h, w, 4), np.uint8)
        centre_rgba[~ink, 3] = 255
        frames.append((_qimage(edge_rgba), _qimage(centre_rgba)))
    return frames


def _qimage(rgba):
    h, w = rgba.shape[:2]
    data = np.ascontiguousarray(rgba)
    image = QImage(data.data, w, h, w * 4, QImage.Format_RGBA8888)
    return image.copy()            # own the pixels, not the numpy buffer


def _draw_halftone(painter, rect, colour, alpha, envelope, now):
    frames = _halftone_masks()
    # Chaos: each step picks a mask and an offset from a hash of the step.
    step = int(now * HALFTONE_FPS)
    chaos = random.Random(step * 7919)
    index = chaos.randrange(len(frames))
    jx = chaos.randint(-HALFTONE_JITTER, HALFTONE_JITTER)
    jy = chaos.randint(-HALFTONE_JITTER, HALFTONE_JITTER)
    flip = chaos.random() < 0.5
    rect = rect.adjusted(-HALFTONE_JITTER + jx, -HALFTONE_JITTER + jy,
                         HALFTONE_JITTER + jx, HALFTONE_JITTER + jy)
    edge, centre = frames[index]
    beat = 0.92 + 0.08 * math.sin(now * 5.5)
    # The red middle: the centre mask, filled with the tint (once per colour).
    red = _TINTED.get((index, colour))
    if red is None:
        red = QImage(centre)
        p = QPainter(red)
        p.setCompositionMode(QPainter.CompositionMode_SourceIn)
        p.fillRect(red.rect(), QColor(*colour, 255))
        p.end()
        _TINTED[(index, colour)] = red
    if flip:
        red, edge = _mirrored(index, colour, red, edge)
    painter.setOpacity(max(0.0, min(1.0, alpha * beat)))
    painter.drawImage(rect, red)
    painter.setOpacity(max(0.0, min(1.0, envelope)))
    painter.drawImage(rect, edge)
    painter.setOpacity(1.0)


def _mirrored(index, colour, red, edge):
    """The pair mirrored left to right: twice the masks for the churn, free."""
    key = (index, colour, "flip")
    pair = _TINTED.get(key)
    if pair is None:
        pair = _TINTED[key] = (red.mirrored(True, False), edge.mirrored(True, False))
    return pair


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
    """Draw every live tint (``((r, g, b), alpha, style, progress, envelope)``)."""
    if not tints:
        return
    painter.save()
    rect = QRect(0, 0, width, height)
    centre = QPointF(width / 2.0, height / 2.0)
    reach = math.hypot(width, height) * 0.55
    for colour, alpha, style, _progress, envelope in tints:
        if alpha <= 0.003:
            continue
        r, g, b = (int(max(0, min(255, c * 255))) for c in colour)
        if style == "blood":
            painter.setRenderHint(QPainter.SmoothPixmapTransform, False)
            _draw_halftone(painter, rect, (r, g, b), alpha, envelope, now)
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


def draw_aim(painter, pos, colour, now=0.0) -> None:
    """The aiming reticle at the cursor (cast mode "aimed"): a turning rune
    ring in the spell's colour, ticks pointing in, a dot at the middle."""
    if pos is None:
        return
    r, g, b = (int(max(0, min(255, c))) for c in colour[:3])
    x, y = float(pos[0]), float(pos[1])
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    pulse = 1.0 + 0.08 * math.sin(now * 6.0)
    radius = 18.0 * pulse
    pen = QPen(QColor(0, 0, 0, 150))
    pen.setWidthF(4.0)
    painter.setPen(pen)
    painter.drawEllipse(QPointF(x, y), radius, radius)
    pen = QPen(QColor(r, g, b, 230))
    pen.setWidthF(2.0)
    painter.setPen(pen)
    painter.drawEllipse(QPointF(x, y), radius, radius)
    spin = now * 1.5
    for k in range(4):
        a = spin + k * math.pi / 2
        painter.drawLine(QPointF(x + math.cos(a) * (radius + 9), y + math.sin(a) * (radius + 9)),
                         QPointF(x + math.cos(a) * (radius - 5), y + math.sin(a) * (radius - 5)))
    painter.setBrush(QColor(r, g, b, 230))
    painter.drawEllipse(QPointF(x, y), 2.5, 2.5)
    painter.restore()
