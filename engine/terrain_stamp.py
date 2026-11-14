"""Terrain stamp files: placed texture stamps saved apart from the map.

A ``.stamp`` file is a delta: just the stamps placed on a terrain -- each one's
id, texture, world X/Z position, radius, angle, feather and opacity. It holds
no terrain height, sculpting or baked pixels, so the stamps can be laid back
onto a map whose height has changed since; importing bakes them into that
terrain's paint.

Importing is idempotent: stamps are matched by id, so a stamp already on the
terrain is left alone (or moved back to the file's position if it was moved
since) and applying the same file twice never duplicates a stamp.

**A map's own stamp file** (version 2) also carries its baked paint: a map
with terrain paint is saved as ``<map>.json`` without it and ``<map>.stamp``
beside it holding the paint chunks (``paint``) and the placed stamps, and the
map's ``terrain_data`` names the file (``paint_file``). Paint is binary data
-- ten megabytes of it for the overworld's roads -- and has no place in a
JSON document people diff and merge. :func:`write_level` splits a level so,
:func:`merge_level_paint` puts the paint back as a map is read (from disk or
a mounted archive), so everything after the file boundary sees the level as
it always did. A map with its paint inline (an older one) loads as before
and is split the next time it is saved.
"""

import json
import os
from typing import Optional

from .fileio import write_json_atomic

STAMP_FORMAT = "terrain_stamp"
STAMP_VERSION = 2
STAMP_EXTENSION = ".stamp"

_STAMP_FIELDS = ("id", "texture", "x", "z", "radius", "angle", "feather", "opacity")


class StampError(ValueError):
    """A stamp file that cannot be read."""


def default_stamp_path(map_path: Optional[str], fallback_dir: str = "") -> str:
    """``<map dir>/<map name>.stamp`` for a map file, else ``untitled.stamp``."""
    if map_path:
        base, _ext = os.path.splitext(os.path.abspath(map_path))
        return base + STAMP_EXTENSION
    return os.path.join(fallback_dir or os.getcwd(), "untitled" + STAMP_EXTENSION)


def export_stamp(terrain) -> dict:
    """The terrain's placed stamps as a JSON-ready stamp file dict."""
    return {
        "format": STAMP_FORMAT,
        "version": STAMP_VERSION,
        "stamps": [{key: stamp[key] for key in _STAMP_FIELDS}
                   for stamp in terrain.paint_stamps],
    }


def save_stamp_file(terrain, path: str) -> dict:
    """Write the terrain's placed stamps to ``path``; returns the file dict.

    Exporting over a map's own stamp file keeps the paint it holds: the
    export is the stamps, and the map still reads its paint from there."""
    data = export_stamp(terrain)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            old = json.load(fh)
        if isinstance(old, dict) and isinstance(old.get("paint"), dict):
            data["paint"] = old["paint"]
    except (OSError, ValueError):
        pass
    write_json_atomic(path, data, indent=None if "paint" in data else 1,
                      separators=(",", ":") if "paint" in data else None)
    return data


def load_stamp_file(path: str) -> dict:
    """Read and validate a stamp file."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise StampError(f"Could not read stamp file: {exc}") from exc
    if not isinstance(data, dict) or data.get("format") != STAMP_FORMAT:
        raise StampError("Not a terrain stamp file")
    try:
        version = int(data.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version < 1 or version > STAMP_VERSION:
        raise StampError(f"Unsupported stamp version: {data.get('version')!r}")
    if not isinstance(data.get("stamps", []), list):
        raise StampError("Stamp file has no stamp list")
    return data


def apply_stamp(terrain, data: dict) -> int:
    """Merge a stamp file dict into ``terrain``; returns stamps added or moved."""
    return terrain.merge_paint_stamps(data.get("stamps", []))


def apply_stamp_file(terrain, path: str) -> int:
    """Load ``path`` and merge its stamps into ``terrain``."""
    return apply_stamp(terrain, load_stamp_file(path))


# ---------------------------------------------------------------------------
# A map's paint in its own stamp file
# ---------------------------------------------------------------------------
#: The terrain_data fields that live in a map's stamp file.
PAINT_FIELDS = ("texture_paint", "texture_paint_resolution", "texture_paint_base",
                "paint_stamps")
#: The terrain_data field naming a map's stamp file (beside the map).
PAINT_FILE_FIELD = "paint_file"


def map_stamp_path(map_path: str) -> str:
    """``<map dir>/<map name>.stamp`` for a map file."""
    base, _ext = os.path.splitext(map_path)
    return base + STAMP_EXTENSION


def split_level_paint(level: dict, map_path: str):
    """*level* without its terrain paint, and the stamp file dict holding
    it: ``(level, stamp)``. A level with no paint comes back as it is, with
    ``None``. *level* itself is not changed."""
    td = level.get("terrain_data") if isinstance(level, dict) else None
    if not isinstance(td, dict) or not any(td.get(k) for k in
                                           ("texture_paint", "texture_paint_base", "paint_stamps")):
        return level, None
    stamp = {
        "format": STAMP_FORMAT,
        "version": STAMP_VERSION,
        "stamps": [dict(s) for s in td.get("paint_stamps") or [] if isinstance(s, dict)],
        "paint": {
            "resolution": td.get("texture_paint_resolution"),
            "chunks": list(td.get("texture_paint") or []),
            "base": list(td.get("texture_paint_base") or []),
        },
    }
    terrain = {k: v for k, v in td.items() if k not in PAINT_FIELDS}
    terrain[PAINT_FILE_FIELD] = os.path.basename(map_stamp_path(map_path))
    out = dict(level)
    out["terrain_data"] = terrain
    return out, stamp


def _read_bytes(path: str):
    try:
        from . import asset_archives
        if asset_archives.in_archive(path):
            return asset_archives.read(path)
    except ImportError:
        pass
    with open(path, "rb") as fh:
        return fh.read()


def merge_level_paint(level: dict, map_path: str = "", read=None) -> dict:
    """Put the paint a map keeps in its stamp file back into *level*'s
    ``terrain_data`` (in place; returns *level*). *read* is how a path's
    bytes are read (default: a mounted archive, else the disk). A missing
    or unreadable file leaves the map without paint, and says so."""
    td = level.get("terrain_data") if isinstance(level, dict) else None
    if not isinstance(td, dict):
        return level
    name = td.pop(PAINT_FILE_FIELD, None)
    if not name:
        return level
    name = os.path.basename(str(name))
    path = os.path.join(os.path.dirname(map_path), name) if map_path else name
    try:
        raw = (read or _read_bytes)(path)
        if raw is None:
            raise OSError("not found")
        data = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
        if not isinstance(data, dict) or data.get("format") != STAMP_FORMAT:
            raise StampError("not a terrain stamp file")
    except (OSError, ValueError) as exc:
        print(f"[Terrain] {map_path or 'map'}: its paint ({name}) could not be read: {exc}")
        return level
    paint = data.get("paint") if isinstance(data.get("paint"), dict) else {}
    if paint.get("chunks"):
        td["texture_paint"] = list(paint["chunks"])
        if paint.get("resolution"):
            td["texture_paint_resolution"] = paint["resolution"]
    if paint.get("base"):
        td["texture_paint_base"] = list(paint["base"])
    stamps = [s for s in data.get("stamps") or [] if isinstance(s, dict)]
    if stamps:
        td["paint_stamps"] = stamps
    return level


def write_level(path: str, level: dict, **dump_kwargs) -> None:
    """Save *level* to *path*, its terrain paint to ``<map>.stamp`` beside
    it (:func:`split_level_paint`); the stamp file first, so a map is never
    on disk naming paint that is not there yet."""
    out, stamp = split_level_paint(level, path)
    if stamp is not None:
        write_json_atomic(map_stamp_path(path), stamp, separators=(",", ":"))
    write_json_atomic(path, out, **dump_kwargs)
