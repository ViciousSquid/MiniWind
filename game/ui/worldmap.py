"""
The world's map picture, and the minimap drawn from it.

:class:`WorldMap` paints the whole world once: the terrain's height sampled
over a grid, coloured by height and slope (meadow, upland, rock, snow) and
hill-shaded from the north-west, with the map's water, woods and buildings laid
over it from its brushes. That takes a few seconds for a big world, so it runs
on a background thread, in strips, and is cached on disk per map (``cache/``),
so a map is only ever painted once. Until it is ready the minimap says so.

:func:`draw_minimap` paints the square minimap in the top-right corner of the
play view, under the clock: north up (the overhead camera's north), about
:data:`MINIMAP_SPAN` world units across, with the player's arrow, the people
and creatures nearby (red: hostile to the player, green: friendly, grey:
anyone else), and the tracked quest's target as a yellow diamond, pinned to
the edge when it is off the map.
"""

from __future__ import annotations

import hashlib
import math
import os
import threading
import time

import numpy as np

#: Samples along the world's longer side.
RESOLUTION = 1024
#: World units the minimap shows across.
MINIMAP_SPAN = 6400.0
#: Where cached map pictures are kept.
CACHE_DIR = "cache"
#: Bumped whenever the painting changes, so old caches are not reused.
STYLE_VERSION = 2

_TREE_HINT = "tree"


def _brush_kind(brush):
    """'water', 'tree', 'paving' or 'building' (None: draws nothing)."""
    try:
        from engine.constants import is_water_brush
        if is_water_brush(brush):
            return "water"
    except Exception:
        pass
    textures = brush.get("textures") or {}
    names = list(textures.values()) if isinstance(textures, dict) else list(textures)
    names = [str(n).lower() for n in names if n]
    if any(_TREE_HINT in n for n in names):
        return "tree"
    if not names or all("nodraw" in n for n in names):
        return None
    if brush.get("is_trigger") or brush.get("hidden"):
        return None
    try:
        if float((brush.get("size") or (0, 64, 0))[1]) < 24.0:
            return "paving"         # a street, a yard, a floor: thin and flat
    except (TypeError, ValueError, IndexError):
        pass
    return "building"


def colour_terrain(heights, cell):
    """``(H, W, 3)`` uint8 colours for a height grid sampled every *cell* units."""
    h = np.asarray(heights, dtype=np.float32)
    lo, hi = float(np.percentile(h, 1)), float(np.percentile(h, 99.5))
    hn = np.clip((h - lo) / max(1e-3, hi - lo), 0.0, 1.0)
    gz, gx = np.gradient(h, cell)
    slope = np.sqrt(gx * gx + gz * gz)
    # Height ramp: meadow, upland, heath, rock, snow.
    stops = np.array([0.0, 0.30, 0.55, 0.78, 0.90, 1.0], dtype=np.float32)
    ramp = np.array([[84, 122, 58], [104, 132, 66], [124, 128, 78],
                     [128, 118, 100], [150, 146, 140], [236, 238, 242]], dtype=np.float32)
    rgb = np.empty(h.shape + (3,), dtype=np.float32)
    for c in range(3):
        rgb[..., c] = np.interp(hn, stops, ramp[:, c])
    # Steep ground is bare rock, whatever its height.
    rock = np.clip((slope - 0.45) / 0.6, 0.0, 1.0)[..., None]
    rgb = rgb * (1.0 - rock) + np.array([122, 116, 108], np.float32) * rock
    # Hill shade, lit from the north-west (top-left of the map).
    nx, nz = -gx, -gz
    ny = np.full_like(h, 1.0)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    light = np.array([-0.55, 0.70, -0.45], np.float32)
    light /= np.linalg.norm(light)
    shade = (nx * light[0] + ny * light[1] + nz * light[2]) / norm
    rgb *= (0.55 + 0.6 * np.clip(shade, 0.0, 1.0))[..., None]
    return np.clip(rgb, 0, 255).astype(np.uint8)


def paint_brushes(rgb, brushes, bounds, cell):
    """Lay water, woods and buildings over the terrain colours, in place."""
    (min_x, _max_x), (min_z, _max_z) = bounds
    rows, cols = rgb.shape[:2]
    colours = {"water": (62, 112, 168), "paving": (156, 140, 110),
               "tree": (44, 84, 40), "building": (104, 84, 66)}
    order = {"water": 0, "paving": 1, "tree": 2, "building": 3}
    drawn = []
    for brush in brushes or ():
        kind = _brush_kind(brush)
        if kind is None:
            continue
        try:
            px, _py, pz = (float(v) for v in brush.get("pos", (0, 0, 0)))
            sx, _sy, sz = (float(v) for v in brush.get("size", (64, 64, 64)))
        except Exception:
            continue
        drawn.append((order[kind], kind, px, pz, sx, sz))
    for _o, kind, px, pz, sx, sz in sorted(drawn, key=lambda d: d[0]):
        c0 = int((px - sx / 2 - min_x) / cell)
        c1 = int(math.ceil((px + sx / 2 - min_x) / cell))
        r0 = int((pz - sz / 2 - min_z) / cell)
        r1 = int(math.ceil((pz + sz / 2 - min_z) / cell))
        c0, r0 = max(0, c0), max(0, r0)
        c1, r1 = min(cols, max(c1, c0 + 1)), min(rows, max(r1, r0 + 1))
        if c0 >= cols or r0 >= rows or c1 <= 0 or r1 <= 0:
            continue
        rgb[r0:r1, c0:c1] = colours[kind]


class WorldMap:
    """The map picture of one world; built in the background, then cached."""

    def __init__(self):
        self.bounds = None          # ((min_x, max_x), (min_z, max_z))
        self.cell = 1.0
        self.rgb = None             # (H, W, 3) uint8 when ready
        self._image = None          # QImage made from rgb, on the UI thread
        self._thread = None
        self._key = None
        self.error = None

    @property
    def ready(self) -> bool:
        return self.rgb is not None

    @property
    def building(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # -- building -------------------------------------------------------------
    @staticmethod
    def cache_key(map_path, terrain_data) -> str:
        h = hashlib.sha1()
        h.update(str(STYLE_VERSION).encode())
        h.update(str(RESOLUTION).encode())
        try:
            h.update(os.path.abspath(str(map_path)).encode())
            h.update(str(os.path.getmtime(map_path)).encode())
        except (OSError, TypeError):
            h.update(repr(sorted((terrain_data or {}).items()))[:4096].encode())
        return h.hexdigest()[:20]

    def ensure(self, terrain, brushes, map_path=None, terrain_data=None):
        """Start painting this world if it is not painted (or being painted)."""
        key = self.cache_key(map_path, terrain_data)
        if key == self._key and (self.ready or self.building):
            return
        self._key = key
        self.rgb = None
        self._image = None
        self.error = None
        cached = self._load_cache(key)
        if cached is not None:
            self.rgb, self.bounds, self.cell = cached
            return
        if terrain is None:
            self.error = "no terrain"
            return
        brushes = [dict(b) for b in (brushes or ()) if isinstance(b, dict)]
        self._thread = threading.Thread(
            target=self._build, args=(key, terrain, brushes), daemon=True,
            name="MiniWind-worldmap")
        self._thread.start()

    def _build(self, key, terrain, brushes):
        try:
            (min_x, max_x), (min_z, max_z) = terrain.get_terrain_bounds()
            span = max(max_x - min_x, max_z - min_z)
            cell = span / float(RESOLUTION)
            cols = max(2, int(round((max_x - min_x) / cell)))
            rows = max(2, int(round((max_z - min_z) / cell)))
            xs = min_x + (np.arange(cols) + 0.5) * cell
            heights = np.empty((rows, cols), dtype=np.float32)
            strip = 24      # rows per batch: short enough to let the game run
            for r0 in range(0, rows, strip):
                r1 = min(rows, r0 + strip)
                zs = min_z + (np.arange(r0, r1) + 0.5) * cell
                X, Z = np.meshgrid(xs, zs)
                heights[r0:r1] = terrain._get_heights_batch(
                    X.ravel(), Z.ravel()).reshape(r1 - r0, cols)
                time.sleep(0.002)
            rgb = colour_terrain(heights, cell)
            bounds = ((min_x, max_x), (min_z, max_z))
            paint_brushes(rgb, brushes, bounds, cell)
            if key != self._key:
                return                      # a newer world asked meanwhile
            self.bounds, self.cell, self.rgb = bounds, cell, rgb
            self._save_cache(key)
        except Exception as exc:            # never take the game down
            self.error = str(exc)

    def _cache_path(self, key):
        return os.path.join(CACHE_DIR, f"worldmap_{key}.npz")

    def _load_cache(self, key):
        try:
            with np.load(self._cache_path(key)) as data:
                b = data["bounds"]
                return (data["rgb"], ((float(b[0]), float(b[1])), (float(b[2]), float(b[3]))),
                        float(data["cell"]))
        except Exception:
            return None

    def _save_cache(self, key):
        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
            (a, b), (c, d) = self.bounds
            np.savez_compressed(self._cache_path(key), rgb=self.rgb,
                                bounds=np.array([a, b, c, d]), cell=self.cell)
        except Exception:
            pass

    # -- using ----------------------------------------------------------------
    def image(self):
        """The picture as a QImage (made once, on the UI thread), or None."""
        if self.rgb is None:
            return None
        if self._image is None:
            from PyQt5.QtGui import QImage
            rgb = np.ascontiguousarray(self.rgb)
            h, w = rgb.shape[:2]
            self._image = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        return self._image

    def to_image(self, x, z):
        """Map-picture pixel of a world point (may lie outside the picture)."""
        (min_x, _), (min_z, _) = self.bounds
        return (x - min_x) / self.cell, (z - min_z) / self.cell


#: The process-wide map of the world being played.
WORLD = WorldMap()


def ensure_for(logic, view=None):
    """Make sure the world being played is (being) painted."""
    terrain = getattr(logic, "terrain", None)
    state = getattr(logic, "editor_state", None)
    editor = getattr(view, "editor", None) if view is not None else None
    map_path = getattr(editor, "file_path", None)
    brushes = getattr(state, "brushes", None)
    terrain_data = getattr(state, "terrain_data", None)
    if map_path and os.path.isfile(str(map_path)):
        # The map file holds every brush, streamed in or not.
        brushes = _map_brushes(map_path) or brushes
    WORLD.ensure(terrain, brushes, map_path, terrain_data)


_BRUSH_CACHE = {}


def _map_brushes(path):
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    got = _BRUSH_CACHE.get(path)
    if got is not None and got[0] == mtime:
        return got[1]
    try:
        import json
        with open(path, "r", encoding="utf-8") as fh:
            brushes = json.load(fh).get("brushes") or []
    except Exception:
        return None
    _BRUSH_CACHE.clear()
    _BRUSH_CACHE[path] = (mtime, brushes)
    return brushes


# --------------------------------------------------------------------- minimap

def minimap_rect(width, height):
    """``(x, y, size)`` of the minimap: top-right, under the clock."""
    size = int(max(140, min(230, height * 0.24)))
    return width - size - 16, 126, size


def _relation_colour(session, thing):
    from PyQt5.QtGui import QColor
    props = getattr(thing, "properties", {}) or {}
    if str(props.get("aggression", "")).lower() == "hostile":
        return QColor(225, 70, 60)
    try:
        from ..rpg import factions
        team = props.get("team") or props.get("faction") or ""
        if factions.is_hostile("player", team):
            return QColor(225, 70, 60)
        if factions.is_friendly("player", team):
            return QColor(110, 210, 110)
    except Exception:
        pass
    return QColor(200, 200, 200)


def draw_minimap(painter, session, viewport, width, height, world=None):
    """Paint the square minimap (see the module docstring)."""
    from PyQt5.QtCore import QPointF, QRectF, Qt
    from PyQt5.QtGui import QBrush, QColor, QPainterPath, QPen, QPolygonF
    from . import theme as T

    world = world or WORLD
    logic = getattr(session, "logic", None)
    player = getattr(logic, "player", None)
    if player is None:
        return
    x0, y0, size = minimap_rect(width, height)
    centre = QPointF(x0 + size / 2.0, y0 + size / 2.0)
    radius = size / 2.0
    px, pz = float(player.pos[0]), float(player.pos[2])
    scale = size / MINIMAP_SPAN            # screen px per world unit

    painter.save()
    painter.setRenderHint(painter.Antialiasing, True)
    painter.setRenderHint(painter.SmoothPixmapTransform, True)
    frame = QRectF(x0, y0, size, size)
    window = QPainterPath()
    window.addRect(frame)
    painter.fillPath(window, QColor(20, 24, 20, 230))
    painter.setClipPath(window)

    image = world.image() if world.ready else None
    if image is not None:
        ix, iz = world.to_image(px, pz)
        half = (MINIMAP_SPAN / 2.0) / world.cell       # picture px each side
        src = QRectF(ix - half, iz - half, half * 2.0, half * 2.0)
        painter.drawImage(QRectF(x0, y0, size, size), image, src)
    else:
        painter.setPen(QColor(200, 200, 190))
        painter.setFont(T.font(9, italic=True))
        painter.drawText(QRectF(x0, y0, size, size), int(Qt.AlignCenter),
                         "mapping…" if not world.error else "no map")

    def to_screen(x, z):
        return QPointF(centre.x() + (x - px) * scale, centre.y() + (z - pz) * scale)

    # People and creatures nearby.
    reach2 = (MINIMAP_SPAN / 2.0) ** 2
    try:
        actors = session._live_actors()
    except Exception:
        actors = []
    painter.setPen(QPen(QColor(0, 0, 0, 160), 1))
    for thing in actors:
        props = getattr(thing, "properties", {}) or {}
        if props.get("dead") or props.get("hidden"):
            continue
        dx, dz = thing.pos[0] - px, thing.pos[2] - pz
        if dx * dx + dz * dz > reach2:
            continue
        painter.setBrush(QBrush(_relation_colour(session, thing)))
        painter.drawEllipse(to_screen(thing.pos[0], thing.pos[2]), 3.2, 3.2)

    # The tracked quest's target: a yellow diamond, held on the edge if far.
    try:
        targets = session.quest_arrow_targets()
    except Exception:
        targets = []
    for pos, _qid, _name in targets[:3]:
        p = to_screen(pos[0], pos[2])
        dx, dy = p.x() - centre.x(), p.y() - centre.y()
        limit = radius - 9
        reach = max(abs(dx), abs(dy))
        if reach > limit:
            # Along the line to it, stopped at the square's inner edge.
            p = QPointF(centre.x() + dx / reach * limit, centre.y() + dy / reach * limit)
        diamond = QPolygonF([p + QPointF(0, -7), p + QPointF(6, 0),
                             p + QPointF(0, 7), p + QPointF(-6, 0)])
        painter.setBrush(QBrush(QColor(250, 214, 70)))
        painter.setPen(QPen(QColor(60, 40, 0), 1.2))
        painter.drawPolygon(diamond)

    # The player: an arrow pointing the way they face, at the centre.
    angle = float(getattr(player, "angle", 0.0))
    fx, fz = math.sin(angle), math.cos(angle)
    # Overhead north-up: screen x follows world x, screen y follows world z.
    tip = QPointF(centre.x() + fx * 9, centre.y() + fz * 9)
    left = QPointF(centre.x() + (-fz * 6 - fx * 6), centre.y() + (fx * 6 - fz * 6))
    right = QPointF(centre.x() + (fz * 6 - fx * 6), centre.y() + (-fx * 6 - fz * 6))
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    painter.setPen(QPen(QColor(20, 20, 20), 1.5))
    painter.drawPolygon(QPolygonF([tip, left, centre, right]))

    painter.setClipping(False)
    painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(T.GILD, 2.5))
    painter.drawRect(frame)
    painter.setPen(QPen(QColor(90, 74, 44), 1))
    painter.drawRect(frame.adjusted(4, 4, -4, -4))
    # North.
    painter.setFont(T.font(10, bold=True))
    painter.setPen(T.GOLD_BRIGHT)
    painter.drawText(QRectF(centre.x() - 10, y0 - 2, 20, 16), int(Qt.AlignCenter), "N")
    painter.restore()
