"""
Real dice for the dice panel: shaded polyhedra that tumble and roll.

Each die is its true solid -- a d4 tetrahedron, d6 cube, d8 octahedron,
d10 pentagonal trapezohedron, d12 dodecahedron, d20 icosahedron -- with a
number on every face. While it rolls it tumbles about its own axis, comes in
from the side and bounces to rest; it settles with the face it rolled turned
to the player. Every die gets its own timing and spin (:func:`motion`), so two
dice thrown together tumble out of step.

Drawn with QPainter only (no textures), so it works on the HUD's GL paint
engine and in tests alike.
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Sequence, Tuple

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainterPath, QPen, QPolygonF

Vec = Tuple[float, float, float]

_PHI = (1.0 + math.sqrt(5.0)) / 2.0
_LIGHT = None


# ------------------------------------------------------------------ vectors
def _norm(v: Vec) -> Vec:
    n = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / n, v[1] / n, v[2] / n)


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec, b: Vec) -> Vec:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


Mat = Tuple[Vec, Vec, Vec]


def _mat_mul(a: Mat, b: Mat) -> Mat:
    cols = list(zip(*b))
    return tuple(tuple(_dot(row, col) for col in cols) for row in a)   # type: ignore


def _apply(m: Mat, v: Vec) -> Vec:
    return (_dot(m[0], v), _dot(m[1], v), _dot(m[2], v))


def _axis_angle(axis: Vec, angle: float) -> Mat:
    x, y, z = _norm(axis)
    c, s = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    return ((t * x * x + c, t * x * y - s * z, t * x * z + s * y),
            (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
            (t * x * z - s * y, t * y * z + s * x, t * z * z + c))


def _align(a: Vec, b: Vec) -> Mat:
    """The rotation turning direction *a* onto direction *b*."""
    a, b = _norm(a), _norm(b)
    axis = _cross(a, b)
    s = math.sqrt(_dot(axis, axis))
    c = _dot(a, b)
    if s < 1e-9:
        if c > 0:
            return ((1, 0, 0), (0, 1, 0), (0, 0, 1))
        perp = _norm(_cross(a, (1.0, 0.0, 0.0) if abs(a[0]) < 0.9 else (0.0, 1.0, 0.0)))
        return _axis_angle(perp, math.pi)
    return _axis_angle(axis, math.atan2(s, c))


# ------------------------------------------------------------------- solids
def _hull_normals(verts: Sequence[Vec]) -> List[Vec]:
    """The outward face normals of the convex solid on *verts* (every plane
    through three vertices with all the others on one side), one per face."""
    found: List[Vec] = []
    n_v = len(verts)
    for i in range(n_v):
        for j in range(i + 1, n_v):
            for k in range(j + 1, n_v):
                n = _cross(_sub(verts[j], verts[i]), _sub(verts[k], verts[i]))
                if _dot(n, n) < 1e-12:
                    continue
                n = _norm(n)
                d = _dot(n, verts[i])
                side = [_dot(n, v) - d for v in verts]
                if all(x <= 1e-6 for x in side):
                    pass
                elif all(x >= -1e-6 for x in side):
                    n, d = (-n[0], -n[1], -n[2]), -d
                else:
                    continue
                if d < 0:
                    continue
                if not any(_dot(n, f) > 1 - 1e-6 for f in found):
                    found.append(n)
    return found


def _faces_from_normals(verts: Sequence[Vec], normals: Sequence[Vec]):
    """Faces of a convex solid: for each face normal, the vertices furthest
    along it, in order around it."""
    faces = []
    for n in normals:
        n = _norm(n)
        best = max(_dot(v, n) for v in verts)
        idx = [i for i, v in enumerate(verts) if _dot(v, n) > best - 1e-6]
        cx = sum(verts[i][0] for i in idx) / len(idx)
        cy = sum(verts[i][1] for i in idx) / len(idx)
        cz = sum(verts[i][2] for i in idx) / len(idx)
        centre = (cx, cy, cz)
        u = _norm(_sub(verts[idx[0]], centre))
        w = _cross(n, u)
        idx.sort(key=lambda i: math.atan2(_dot(_sub(verts[i], centre), w),
                                          _dot(_sub(verts[i], centre), u)))
        faces.append((idx, n))
    return faces


def _trapezohedron():
    """The d10: two apexes and a zig-zag ring of ten, ten kite faces."""
    c = 0.105
    def planar_gap(h):
        top = (0.0, 0.0, h)
        u0 = (1.0, 0.0, c)
        l0 = (math.cos(math.radians(36)), math.sin(math.radians(36)), -c)
        u1 = (math.cos(math.radians(72)), math.sin(math.radians(72)), c)
        return _dot(_sub(l0, top), _cross(_sub(u0, top), _sub(u1, top)))
    lo, hi = 0.2, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if (planar_gap(lo) > 0) == (planar_gap(mid) > 0):
            lo = mid
        else:
            hi = mid
    h = (lo + hi) / 2.0
    verts: List[Vec] = [(0.0, 0.0, h), (0.0, 0.0, -h)]
    for i in range(5):
        a = math.radians(72 * i)
        verts.append((math.cos(a), math.sin(a), c))                       # upper
    for i in range(5):
        a = math.radians(72 * i + 36)
        verts.append((math.cos(a), math.sin(a), -c))                      # lower
    up = lambda i: 2 + i % 5
    low = lambda i: 7 + i % 5
    faces = []
    for i in range(5):
        for idx in ((0, up(i), low(i), up(i + 1)), (1, low(i), up(i + 1), low(i + 1))):
            pts = [verts[k] for k in idx]
            n = _norm(_cross(_sub(pts[1], pts[0]), _sub(pts[2], pts[0])))
            centre = tuple(sum(p[j] for p in pts) / 4.0 for j in range(3))
            if _dot(n, centre) < 0:
                n = (-n[0], -n[1], -n[2])
                idx = tuple(reversed(idx))
            faces.append((list(idx), n))
    return verts, faces


def _solid(sides: int):
    if sides == 4:
        verts = [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]
        normals = [tuple(-c for c in v) for v in verts]
    elif sides == 6:
        verts = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        normals = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
    elif sides == 8:
        verts = [(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]
        normals = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    elif sides == 10:
        return _trapezohedron()
    elif sides == 12:
        p, q = _PHI, 1.0 / _PHI
        verts = ([(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
                 + [(0, a * q, b * p) for a in (-1, 1) for b in (-1, 1)]
                 + [(a * q, b * p, 0) for a in (-1, 1) for b in (-1, 1)]
                 + [(a * p, 0, b * q) for a in (-1, 1) for b in (-1, 1)])
        normals = ([(0, a, b * p) for a in (-1, 1) for b in (-1, 1)]
                   + [(a, b * p, 0) for a in (-1, 1) for b in (-1, 1)]
                   + [(a * p, 0, b) for a in (-1, 1) for b in (-1, 1)])
    else:                                                     # d20 (and fallback)
        p = _PHI
        verts = ([(0, a, b * p) for a in (-1, 1) for b in (-1, 1)]
                 + [(a, b * p, 0) for a in (-1, 1) for b in (-1, 1)]
                 + [(a * p, 0, b) for a in (-1, 1) for b in (-1, 1)])
        q = 1.0 / _PHI
        normals = ([(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
                   + [(0, a * q, b * p) for a in (-1, 1) for b in (-1, 1)]
                   + [(a * q, b * p, 0) for a in (-1, 1) for b in (-1, 1)]
                   + [(a * p, 0, b * q) for a in (-1, 1) for b in (-1, 1)])
    verts = [tuple(float(c) for c in v) for v in verts]
    radius = max(math.sqrt(_dot(v, v)) for v in verts)
    verts = [(v[0] / radius, v[1] / radius, v[2] / radius) for v in verts]
    # The faces from the solid itself (its convex hull), not a hand table.
    return verts, _faces_from_normals(verts, _hull_normals(verts))


_SOLIDS: Dict[int, tuple] = {}


def solid(sides: int):
    """``(vertices, [(vertex indices, normal), ...])`` for a die of *sides*
    (any other count draws as a d20)."""
    sides = int(sides) if int(sides) in (4, 6, 8, 10, 12, 20) else 20
    if sides not in _SOLIDS:
        verts, faces = _solid(sides)
        if sides == 10:
            radius = max(math.sqrt(_dot(v, v)) for v in verts)
            verts = [(v[0] / radius, v[1] / radius, v[2] / radius) for v in verts]
        _SOLIDS[sides] = (verts, faces)
    return _SOLIDS[sides]


def face_label(sides: int, index: int) -> str:
    """The number on face *index* of a die of *sides*."""
    return str(index + 1)


# ------------------------------------------------------------------ motion
# -- timing (tweak here) ---------------------------------------------------
# Every die lands -- its face readable -- quickly, so a result (and the
# damage) is told within DAMAGE_TOLD_BY seconds of the blow. Now and then a
# roll keeps rattling after it lands (the rolled face staying up), for a
# little drama, but no roll ever lasts longer than ROLL_MAX_SECONDS.
DAMAGE_TOLD_BY = 1.0       # the damage is always shown by now (seconds)
ROLL_MAX_SECONDS = 1.2     # no roll, rattle and all, lasts longer
#: How long a die tumbles before it lands (seconds, a range).
TUMBLE_SECONDS = (0.45, 0.68)
#: A die may start up to this late, so a pair is never thrown in step.
START_JITTER = 0.04
#: The second die (damage) is thrown this much after the first (to hit).
SECOND_DIE_DELAY = 0.10
#: Every roll as a whole runs this much faster or slower (+/-), so no two
#: rolls feel the same.
ROLL_SPEED_VARIANCE = 0.10
#: About this share of rolls keep rattling after they land ...
LONG_RATTLE_CHANCE = 0.25
#: ... rocking up to this many degrees, dying away.
RATTLE_DEGREES = 11.0


def roll_speed(seed: int) -> float:
    """A whole roll's speed factor: about 1.0, +/- ROLL_SPEED_VARIANCE."""
    return 1.0 + random.Random(seed * 7919 + 17).uniform(-ROLL_SPEED_VARIANCE,
                                                           ROLL_SPEED_VARIANCE)


def rattles(seed: int) -> bool:
    """Whether a roll keeps rattling after its dice land (LONG_RATTLE_CHANCE)."""
    return random.Random(seed * 104729 + 3).random() < LONG_RATTLE_CHANCE


def motion(seed: int, *, delay: float = 0.0, speed: float = 1.0,
           rattle: bool = False) -> Dict:
    """One die's own throw: its delay, how long it tumbles, its spin axis and
    turns, where it comes in from and how it bounces -- and, with *rattle*,
    how long it keeps rocking after it lands (never past ROLL_MAX_SECONDS).
    Different for every seed, so dice thrown together never move in step;
    *speed* scales the whole of it (a roll's own pace, :func:`roll_speed`)."""
    rng = random.Random(seed)
    m = {
        "delay": (delay + rng.uniform(0.0, START_JITTER)) * speed,
        "duration": rng.uniform(*TUMBLE_SECONDS) * speed,
        "axis": _norm((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))),
        "turns": rng.uniform(2.0, 3.2),
        "settle_spin": rng.uniform(-0.6, 0.6),
        "from_x": rng.choice((-1.0, 1.0)) * rng.uniform(0.9, 1.5),
        "bounces": rng.choice((2, 3)),
        "hop": rng.uniform(0.35, 0.6),
        "rattle": 0.0,
    }
    if rattle:
        room = ROLL_MAX_SECONDS - (m["delay"] + m["duration"])
        m["rattle"] = max(0.0, room * rng.uniform(0.5, 1.0))
    return m


#: How a settled die is tipped toward the light: its rolled face up and to
#: the front, its neighbours just showing.
REST_TILT = _mat_mul(_axis_angle((1.0, 0.0, 0.0), math.radians(-11)),
                     _axis_angle((0.0, 1.0, 0.0), math.radians(9)))


def _ease_out(p: float) -> float:
    return 1.0 - (1.0 - p) ** 3


def pose(sides: int, value: int, m: Dict, local: float):
    """Where the die is *local* seconds into its throw: ``(rotation, dx, dy,
    settled)`` -- dx, dy as shares of its size."""
    verts, faces = solid(sides)
    index = max(0, min(len(faces) - 1, int(value) - 1))
    # At rest the rolled face looks at the player, tipped a little so the
    # die still reads as a solid.
    rest = _mat_mul(REST_TILT,
                    _mat_mul(_axis_angle((0.0, 0.0, 1.0), m["settle_spin"]),
                             _align(faces[index][1], (0.0, 0.0, 1.0))))
    duration = max(0.05, m["duration"])
    p = max(0.0, min(1.0, local / duration))
    if p >= 1.0:
        # Landed: its face is the result. A long roll keeps rocking a while,
        # the rolled face staying up, dying away.
        t, rattle = local - duration, float(m.get("rattle", 0.0))
        if 0.0 <= t < rattle:
            fade = (1.0 - t / rattle) ** 1.5
            wobble = math.radians(RATTLE_DEGREES) * fade * math.sin(t * 38.0)
            return (_mat_mul(rest, _axis_angle(m["axis"], wobble)),
                    0.03 * fade * math.sin(t * 29.0), 0.0, True)
        return rest, 0.0, 0.0, True
    left = (1.0 - _ease_out(p))
    angle = m["turns"] * 2.0 * math.pi * left * left
    rotation = _mat_mul(rest, _axis_angle(m["axis"], angle))
    dx = m["from_x"] * left
    hops = abs(math.sin(p * math.pi * m["bounces"]))
    dy = -m["hop"] * hops * left
    return rotation, dx, dy, False


# ----------------------------------------------------------------- drawing
#: The player's dice are in colour -- the d20 red with gold numbers, any
#: other die bone with dark ink. Anyone else's dice are greyscale: a dark
#: grey d20 with pale numbers, any other die light grey with dark ones.
D20_BODY = QColor(150, 30, 34)
D20_INK = QColor(255, 222, 140)
OTHER_D20_BODY = QColor(62, 62, 66)
OTHER_D20_INK = QColor(226, 226, 230)
OTHER_DIE_BODY = QColor(196, 196, 200)
OTHER_DIE_INK = QColor(40, 40, 44)


def colours(sides: int, player: bool):
    """``(body, ink)`` for a die of *sides* rolled by the player (colour) or
    by anyone else (greyscale)."""
    if player:
        return (D20_BODY, D20_INK) if sides == 20 else (DIE_BODY, DIE_INK)
    return (OTHER_D20_BODY, OTHER_D20_INK) if sides == 20 else (OTHER_DIE_BODY, OTHER_DIE_INK)
DIE_BODY = QColor(226, 214, 186)
DIE_INK = QColor(48, 34, 22)


def draw_die(painter, sides: int, value: int, cx: float, cy: float, size: float,
             rotation, alpha: int = 255, body: QColor = None, ink: QColor = None,
             tumbling: bool = False, flicker: int = 0) -> None:
    """Draw the die of *sides* at (*cx*, *cy*), *size* across, turned by
    *rotation*. Its front faces carry their numbers; the face toward the
    player shows *value* once settled."""
    global _LIGHT
    if _LIGHT is None:
        _LIGHT = _norm((-0.45, 0.65, 0.75))
    verts, faces = solid(sides)
    if body is None:
        body = D20_BODY if sides == 20 else DIE_BODY
    if ink is None:
        ink = D20_INK if sides == 20 else DIE_INK
    r = size * 0.5
    pts = []
    for v in verts:
        x, y, z = _apply(rotation, v)
        k = 1.0 / (1.0 - z * 0.12)               # a little perspective
        pts.append((cx + x * r * k, cy - y * r * k, z))
    shown = []
    for i, (idx, n) in enumerate(faces):
        rn = _apply(rotation, n)
        if rn[2] <= 0.02:
            continue
        shown.append((sum(pts[j][2] for j in idx) / len(idx), i, idx, rn))
    shown.sort()
    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    a = max(0, min(255, int(alpha)))
    edge = QColor(body.darker(240))
    edge.setAlpha(a)
    for _z, i, idx, rn in shown:
        light = 0.42 + 0.58 * max(0.0, _dot(rn, _LIGHT))
        colour = QColor(min(255, int(body.red() * light + 18 * rn[2])),
                        min(255, int(body.green() * light + 14 * rn[2])),
                        min(255, int(body.blue() * light + 12 * rn[2])), a)
        poly = QPolygonF([QPointF(pts[j][0], pts[j][1]) for j in idx])
        painter.setPen(QPen(edge, max(1.0, size / 70.0)))
        painter.setBrush(colour)
        painter.drawPolygon(poly)
        # The face's number, screen-upright, fading as it turns away; none on
        # a face turned well aside.
        if rn[2] < 0.3:
            continue
        fx = sum(pts[j][0] for j in idx) / len(idx)
        fy = sum(pts[j][1] for j in idx) / len(idx)
        label = face_label(sides, i)
        rolled = not tumbling and i == max(0, min(len(faces) - 1, int(value) - 1))
        if rolled:
            label = str(int(value))
        elif tumbling and flicker:
            label = str((i * 7 + flicker) % sides + 1)
        span = max(abs(pts[j][0] - fx) for j in idx) + max(abs(pts[j][1] - fy) for j in idx)
        share = {20: 0.34, 12: 0.5, 10: 0.48}.get(sides, 0.5)
        px = min(size * 0.28, span * share) * rn[2] ** 0.5
        if not tumbling:
            # Settled: the rolled number stands out, the rest recede.
            px *= 1.3 if rolled else 0.7
        px = max(6, int(px))
        font = QFont("Segoe UI")
        font.setPixelSize(px)
        font.setBold(True)
        painter.setFont(font)
        tint = QColor(ink)
        tint.setAlpha(int(a * min(1.0, 0.25 + rn[2])))
        painter.setPen(tint)
        painter.drawText(QRectF(fx - px * 1.2, fy - px * 0.75, px * 2.4, px * 1.5),
                         int(Qt.AlignCenter), label)
    painter.restore()
